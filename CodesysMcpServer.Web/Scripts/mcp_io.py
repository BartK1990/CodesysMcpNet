# -*- coding: utf-8 -*-
"""
Request/response plumbing shared by every CODESYS MCP script.

Contract with the ASP.NET Core PythonRunner
-------------------------------------------
argv[1] is the path to a UTF-8 JSON request file. The file always carries a
"resultPath" member telling the script where to write its answer.

The script answers with an envelope:

    { "ok": true,  "data": <payload>, "error": null }
    { "ok": false, "data": null,      "error": { "message": "...", "traceback": "...", "code": "..." } }

"code" is only present for failures the server reacts to specifically, e.g.
"password_required" / "password_invalid" when the project could not be opened
without (the right) password.

The envelope is written to the result file *and* printed to stdout between
sentinel markers, because CODESYS floods stdout with unrelated start-up text.

Compatible with IronPython 2.7 (the interpreter embedded in CODESYS) and CPython 3.
"""

from __future__ import print_function

import codecs
import json
import os
import sys
import traceback

RESULT_BEGIN = "<<<MCP_RESULT_BEGIN>>>"
RESULT_END = "<<<MCP_RESULT_END>>>"

# Set by session_host.py while it loads a script: run() then hands the handler over
# instead of executing it and closing CODESYS. None means "one-shot" mode.
HOSTED_HANDLERS = None

# The request being served right now (one-shot or hosted), so shared helpers such as
# codesys_api.Application.OpenProject can read request-wide options like the project
# password without every script passing them through.
CURRENT_REQUEST = None


def log(message):
    """Print a progress line. The .NET runner logs every line as it arrives."""
    try:
        print("[mcp] " + _to_text(message))
    except Exception:
        print("[mcp] <unprintable log message>")
    _flush()


def read_request():
    """Load the JSON request file referenced by argv[1]."""
    if len(sys.argv) < 2 or not sys.argv[1]:
        raise ValueError("Missing request file argument (argv[1]).")

    path = sys.argv[1]
    if not os.path.isfile(path):
        raise IOError("Request file not found: " + path)

    # utf-8-sig tolerates a byte order mark, which some writers emit.
    handle = codecs.open(path, "r", "utf-8-sig")
    try:
        return json.loads(handle.read())
    finally:
        handle.close()


def require(request, key):
    """Fetch a mandatory, non-empty request member."""
    value = request.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("Request member '" + key + "' is required.")
    return value


def emit(request, data=None, ok=True, error=None, echo=True):
    """
    Write the result envelope to the result file and, when `echo` is set, to stdout.
    The file is written under a temporary name and renamed into place, so a reader
    polling for it never sees a half-written envelope.
    """
    envelope = {"ok": bool(ok), "data": data, "error": error}

    try:
        # ensure_ascii=False, then escaping by hand: IronPython's str is unicode, and its
        # json ASCII encoder "decodes" any string holding U+0080..U+00FF (e.g. a degree
        # sign or an umlaut in a comment) as UTF-8 and fails. The result stays pure ASCII.
        text = _ascii_escape(json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False))
    except Exception:
        # Last resort: never lose the failure reason because of a serialization problem.
        text = _ascii_escape(json.dumps({
            "ok": False,
            "data": None,
            "error": {
                "message": "Result payload could not be serialized to JSON.",
                "traceback": traceback.format_exc(),
            },
        }, indent=2, ensure_ascii=False))

    if echo:
        print(RESULT_BEGIN)
        print(text)
        print(RESULT_END)
        _flush()

    result_path = None
    if isinstance(request, dict):
        result_path = request.get("resultPath")

    if result_path:
        try:
            temp_path = result_path + ".tmp"
            handle = codecs.open(temp_path, "w", "utf-8")
            try:
                handle.write(text)
            finally:
                handle.close()
            if os.path.exists(result_path):
                os.remove(result_path)
            os.rename(temp_path, result_path)
        except Exception:
            print("[mcp] WARNING: could not write result file: " + traceback.format_exc())
            _flush()


def run(handler):
    """
    Entry point used by every script: read the request, invoke the handler,
    emit the envelope, and exit with a meaningful status code.

    Inside the persistent session host the handler is only registered; the host
    calls it per request and keeps CODESYS (and the open project) alive.
    """
    if HOSTED_HANDLERS is not None:
        HOSTED_HANDLERS.append(handler)
        return

    request = None
    try:
        request = read_request()
    except Exception as ex:
        emit(None, None, False, {"message": str(ex), "traceback": traceback.format_exc()})
        _exit(2)
        return

    global CURRENT_REQUEST
    CURRENT_REQUEST = request
    try:
        data = handler(request)
        emit(request, data, True, None)
        _exit(0)
    except Exception as ex:
        log("FAILED: " + _describe(ex))
        emit(request, None, False, error_payload(ex))
        _exit(1)


def error_payload(ex):
    """The envelope's "error" member for an exception raised by a handler."""
    error = {"message": _describe(ex), "traceback": traceback.format_exc()}
    code = getattr(ex, "code", None)
    if code:
        error["code"] = code
    return error


def request_password():
    """
    Password of the project the current request opens, or None. The server writes it to
    a separate file (deleted right after the request) rather than into the request itself,
    so it never lingers in kept request files.
    """
    request = CURRENT_REQUEST
    path = request.get("projectPasswordFile") if isinstance(request, dict) else None
    if not path or not os.path.isfile(path):
        return None
    handle = codecs.open(path, "r", "utf-8-sig")
    try:
        return handle.read() or None
    finally:
        handle.close()


def _describe(ex):
    name = type(ex).__name__
    text = _to_text(ex)
    if not text:
        return name
    return name + ": " + text


def _to_text(value):
    try:
        if isinstance(value, bytes):
            return value.decode("utf-8", "replace")
        return str(value)
    except Exception:
        return repr(value)


def _ascii_escape(text):
    """
    Replace every non-ASCII character of serialized JSON with a \\uXXXX escape. Such
    characters only occur inside JSON strings, where the escape means the same thing.
    """
    if isinstance(text, bytes):
        text = text.decode("utf-8")
    parts = []
    for char in text:
        code = ord(char)
        if code < 0x80:
            parts.append(char)
        elif code > 0xFFFF:
            # Wide builds hold astral characters as one code point; JSON wants a pair.
            code -= 0x10000
            parts.append(u"\\u%04x\\u%04x" % (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)))
        else:
            parts.append(u"\\u%04x" % code)
    return u"".join(parts)


def _flush():
    try:
        sys.stdout.flush()
    except Exception:
        pass


def _exit(code):
    """
    Close CODESYS when running inside it, otherwise exit the interpreter.
    The envelope has already been written at this point, so terminating is safe.
    """
    _flush()

    system = None
    for module_name in ("__builtin__", "builtins", "__main__"):
        module = sys.modules.get(module_name)
        if module is not None:
            system = getattr(module, "system", None)
            if system is not None:
                break

    if system is not None and hasattr(system, "exit"):
        try:
            system.exit(code)
            return
        except Exception:
            pass

    sys.exit(code)
