# -*- coding: utf-8 -*-
"""
Request/response plumbing shared by every CODESYS MCP script.

Contract with the ASP.NET Core PythonRunner
-------------------------------------------
argv[1] is the path to a UTF-8 JSON request file. The file always carries a
"resultPath" member telling the script where to write its answer.

The script answers with an envelope:

    { "ok": true,  "data": <payload>, "error": null }
    { "ok": false, "data": null,      "error": { "message": "...", "traceback": "..." } }

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


def emit(request, data=None, ok=True, error=None):
    """Write the result envelope to stdout and to the result file."""
    envelope = {"ok": bool(ok), "data": data, "error": error}

    try:
        text = json.dumps(envelope, indent=2, sort_keys=True)
    except Exception:
        # Last resort: never lose the failure reason because of a serialization problem.
        text = json.dumps({
            "ok": False,
            "data": None,
            "error": {
                "message": "Result payload could not be serialized to JSON.",
                "traceback": traceback.format_exc(),
            },
        }, indent=2)

    print(RESULT_BEGIN)
    print(text)
    print(RESULT_END)
    _flush()

    result_path = None
    if isinstance(request, dict):
        result_path = request.get("resultPath")

    if result_path:
        try:
            handle = codecs.open(result_path, "w", "utf-8")
            try:
                handle.write(text)
            finally:
                handle.close()
        except Exception:
            print("[mcp] WARNING: could not write result file: " + traceback.format_exc())
            _flush()


def run(handler):
    """
    Entry point used by every script: read the request, invoke the handler,
    emit the envelope, and exit with a meaningful status code.
    """
    request = None
    try:
        request = read_request()
    except Exception as ex:
        emit(None, None, False, {"message": str(ex), "traceback": traceback.format_exc()})
        _exit(2)
        return

    try:
        data = handler(request)
        emit(request, data, True, None)
        _exit(0)
    except Exception as ex:
        message = _describe(ex)
        log("FAILED: " + message)
        emit(request, None, False, {"message": message, "traceback": traceback.format_exc()})
        _exit(1)


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
