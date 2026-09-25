# -*- coding: utf-8 -*-
"""
GET /tasks

Returns every task configuration in the project: per task its kind, priority,
interval, event / external-event trigger, watchdog and the POUs it calls (in call
order).
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

    app = Application()
    project = app.OpenProject(project_path)

    result = project.TaskConfiguration()
    for configuration in result["taskConfigurations"]:
        log("Task configuration '%s': %d task(s)" % (configuration["path"], configuration["taskCount"]))

    return result


mcp_io.run(handler)
