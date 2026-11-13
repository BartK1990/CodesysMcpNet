# -*- coding: utf-8 -*-
"""
POST /tasks/system-events

Adds, changes or removes the handler of one System Event (Task Configuration > System
Events), then saves the project. Like the IDE's "Add Event Handler": a missing handler
function is created with the event's interface and the target's event libraries are
referenced when missing.
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
    event = require(request, "event")

    app = Application()
    project = app.OpenProject(project_path)

    result = project.UpdateSystemEvent(
        event,
        function=request.get("function"),
        active=request.get("active"),
        remove=bool(request.get("remove")),
        create_function=request.get("createFunction") is not False,
        parent_path=request.get("parentPath"),
        application=request.get("application"))
    log("System Event '%s' %s" % (result["event"], result["action"]))
    for warning in result["warnings"]:
        log("Warning: " + warning)

    project.Save()
    result["saved"] = True
    return result


mcp_io.run(handler)
