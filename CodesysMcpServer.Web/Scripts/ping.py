# -*- coding: utf-8 -*-
"""
POST /session/start

Opens the configured project and does nothing else. Used to warm up the persistent
CODESYS session so the first real request does not pay for start-up and project load.
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

    Application().OpenProject(project_path)
    log("Project is open: " + project_path)

    return {"projectPath": project_path, "open": True}


mcp_io.run(handler)
