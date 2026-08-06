# -*- coding: utf-8 -*-
"""
POST /compile

Generates code for every application in the project and returns the compiler verdict
together with whatever messages the engine exposes.

Note on messages: the accessor for the CODESYS message store differs between engine
versions and is missing in some. codesys_api._collect_messages() probes the known
candidates; `messagesAvailable` in the response tells you whether the message list is
authoritative. The `success` flag is always meaningful because it also reflects whether
the build call itself threw.
"""

from __future__ import print_function

import os
import sys

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mcp_io
from mcp_io import log, require
from codesys_api import Application


def handler(request):
    project_path = require(request, "projectPath")
    clean = bool(request.get("clean"))
    save = bool(request.get("save"))

    app = Application()
    project = app.OpenProject(project_path)

    compiler = project.Compiler()
    log("Compiling project" + (" (clean build)" if clean else ""))
    result = compiler.Compile(clean=clean)

    result["projectPath"] = project_path
    result["saved"] = False

    if save and result.get("success"):
        project.Save()
        result["saved"] = True

    log("Compile finished: success=%s errors=%s warnings=%s" % (
        result.get("success"), result.get("errorCount"), result.get("warningCount")))

    return result


mcp_io.run(handler)
