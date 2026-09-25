# -*- coding: utf-8 -*-
"""
Persistent CODESYS session host.

Starting CODESYS and loading a project dominates the cost of every script run, so
instead of launching CODESYS.exe per request the .NET CodesysSession starts it once:

    CODESYS.exe --noUI --runscript=session_host.py --scriptargs:<session.json>

and this script then serves requests until told to stop, keeping the project open.

Queue protocol (all files live in config["queueDirectory"])
----------------------------------------------------------
* The server drops `<id>.req.json` (moved in atomically). The request is the usual
  mcp_io request plus a "script" member naming the script to run, e.g. "pou_read.py".
* The host claims it by renaming it to `<id>.req.json.working`, loads the script (its
  mcp_io.run(handler) call only registers the handler in hosted mode), calls the handler
  and writes the envelope to request["resultPath"] exactly like a one-shot run.
* A request whose script is "__shutdown__" makes the host close the project and exit.

The host also exits on its own when the server process disappears (so an orphaned
CODESYS never keeps the project locked) or after config["idleShutdownSeconds"].

Project handling between requests
---------------------------------
* A request for a different project closes the open one first.
* If the .project file changed on disk since the host last touched it, the open copy
  is closed and the project is reloaded, so external edits are never overwritten.
* If a request fails and leaves unsaved changes behind, the project is closed without
  saving, matching the one-shot behaviour where a failed run simply lost its changes.
"""

from __future__ import print_function

# Snapshot of the names the Scripting Engine injected (system, projects, PouType, ...),
# taken before this module defines anything. Every hosted script runs in a copy of it.
_ENGINE_GLOBALS = dict(globals())

import codecs
import json
import os
import sys
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mcp_io
from mcp_io import log
import codesys_api

REQUEST_SUFFIX = ".req.json"
CLAIMED_SUFFIX = ".working"
SHUTDOWN_SCRIPT = "__shutdown__"
PARENT_CHECK_SECONDS = 2.0


def main():
    config = _read_json(sys.argv[1])
    queue = config["queueDirectory"]
    parent_pid = config.get("parentProcessId")
    poll_seconds = max(10, int(config.get("pollIntervalMs") or 100)) / 1000.0
    idle_seconds = int(config.get("idleShutdownSeconds") or 0)
    keep_files = bool(config.get("keepTempFiles"))

    session = _ProjectSession()
    log("Session host ready (pid parent=%s); watching %s" % (parent_pid, queue))

    last_activity = time.time()
    last_parent_check = 0.0

    while True:
        now = time.time()

        if parent_pid and now - last_parent_check >= PARENT_CHECK_SECONDS:
            last_parent_check = now
            if not _process_alive(parent_pid):
                log("Server process %s is gone; shutting down." % parent_pid)
                break

        claimed = _claim_next(queue)
        if claimed is None:
            if idle_seconds and now - last_activity >= idle_seconds:
                log("Idle for %ds; shutting down." % idle_seconds)
                break
            _sleep(poll_seconds)
            continue

        stop = _serve(session, claimed)

        if not keep_files:
            _try_remove(claimed)

        last_activity = time.time()
        if stop:
            break

    session.close("session host stopping")
    mcp_io._exit(0)


# ---------------------------------------------------------------------------
# Request handling
# ---------------------------------------------------------------------------

def _serve(session, path):
    """Run one claimed request. Returns True when the host should stop."""
    request = None
    try:
        request = _read_json(path)
        script = request.get("script") or u""

        if script == SHUTDOWN_SCRIPT:
            log("Shutdown requested.")
            mcp_io.emit(request, {"stopping": True}, True, None, echo=False)
            return True

        started = time.time()
        log("---- %s ----" % script)

        handler = _load_handler(script)
        session.prepare(request.get("projectPath"))
        data = handler(request)

        mcp_io.emit(request, data, True, None, echo=False)
        log("---- %s done in %.2fs ----" % (script, time.time() - started))
    except Exception as ex:
        message = mcp_io._describe(ex)
        log("FAILED: " + message)
        mcp_io.emit(request, None, False,
                    {"message": message, "traceback": traceback.format_exc()},
                    echo=False)
        session.discard_unsaved_changes()
    finally:
        session.remember_disk_state()

    return False


def _load_handler(script_name):
    """Execute a script file in hosted mode and return the handler it registered."""
    file_name = os.path.basename(script_name or u"")
    path = os.path.join(_HERE, file_name)
    if not file_name.endswith(".py") or not os.path.isfile(path):
        raise IOError("Script not found: " + str(script_name))

    namespace = dict(_ENGINE_GLOBALS)
    namespace["__name__"] = "__mcp_hosted__"
    namespace["__file__"] = path

    captured = []
    mcp_io.HOSTED_HANDLERS = captured
    try:
        _exec_file(path, namespace)
    finally:
        mcp_io.HOSTED_HANDLERS = None

    if not captured:
        raise RuntimeError(file_name + " did not register a handler via mcp_io.run().")
    return captured[-1]


def _exec_file(path, namespace):
    # execfile honours the "coding" header; compile() of a unicode string would not
    # under Python 2. Python 3 has no execfile but has no such restriction either.
    runner = getattr(__builtins__, "execfile", None)
    if runner is None and isinstance(__builtins__, dict):
        runner = __builtins__.get("execfile")
    if runner is not None:
        runner(path, namespace)
        return

    handle = codecs.open(path, "r", "utf-8-sig")
    try:
        source = handle.read()
    finally:
        handle.close()
    exec(compile(source, path, "exec"), namespace)


# ---------------------------------------------------------------------------
# Open project bookkeeping
# ---------------------------------------------------------------------------

class _ProjectSession(object):

    def __init__(self):
        self._stamp = None       # (mtime, size) of the .project file as we last left it

    def prepare(self, project_path):
        """Make sure the requested project is the open one and is current."""
        primary = _primary()
        if primary is None:
            return

        open_path = codesys_api._project_path(primary)
        if not project_path or not codesys_api._same_path(open_path, project_path):
            self.close("switching project from " + open_path)
            return

        if self._stamp is not None and _disk_stamp(project_path) != self._stamp:
            self.close("project file changed on disk; reloading")

    def remember_disk_state(self):
        primary = _primary()
        self._stamp = _disk_stamp(codesys_api._project_path(primary)) if primary is not None else None

    def discard_unsaved_changes(self):
        primary = _primary()
        if primary is not None and _flag(primary, "dirty"):
            self.close("failed request left unsaved changes; discarding them")

    def close(self, reason):
        primary = _primary()
        if primary is None:
            return
        log("Closing project (" + reason + ")")
        try:
            primary.close()
        except Exception as ex:
            log("Could not close the project: " + mcp_io._describe(ex))
        self._stamp = None


def _primary():
    projects = codesys_api.resolve("projects", required=False)
    if projects is None:
        return None
    try:
        return projects.primary
    except Exception:
        return None


def _flag(obj, name):
    try:
        return bool(getattr(obj, name))
    except Exception:
        return False


def _disk_stamp(path):
    try:
        info = os.stat(path)
        return (info.st_mtime, info.st_size)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Queue / process helpers
# ---------------------------------------------------------------------------

def _claim_next(queue):
    """Atomically take the oldest pending request; None when the queue is empty."""
    try:
        names = [n for n in os.listdir(queue) if n.endswith(REQUEST_SUFFIX)]
    except Exception:
        return None

    candidates = []
    for name in names:
        path = os.path.join(queue, name)
        try:
            candidates.append((os.path.getmtime(path), path))
        except Exception:
            continue
    candidates.sort()

    for _mtime, path in candidates:
        claimed = path + CLAIMED_SUFFIX
        try:
            os.rename(path, claimed)   # loses the race if the server withdrew it
            return claimed
        except Exception:
            continue
    return None


def _process_alive(pid):
    try:
        from System.Diagnostics import Process  # IronPython: straight .NET access
    except ImportError:
        return True
    try:
        return not Process.GetProcessById(int(pid)).HasExited
    except Exception:
        return False


def _sleep(seconds):
    # Deliberately NOT system.delay(): that pumps CODESYS's message loop, which lets
    # background work (e.g. precompiling a freshly opened project) run on this thread,
    # and a single such chunk was observed to block the queue for ~19 minutes.
    time.sleep(seconds)


def _read_json(path):
    handle = codecs.open(path, "r", "utf-8-sig")
    try:
        return json.loads(handle.read())
    finally:
        handle.close()


def _try_remove(path):
    try:
        os.remove(path)
    except Exception:
        pass


try:
    main()
except Exception:
    print("[mcp] Session host crashed: " + traceback.format_exc())
    mcp_io._exit(1)
