# -*- coding: utf-8 -*-
"""
GET /structure

Opens the project and returns its full object structure:
POUs (name, type, language), GVLs (name, variable count),
DUTs (name, fields) and ENUMs (name, values).
"""

from __future__ import print_function

import os
import sys

# CODESYS launches the script by absolute path; make the script directory importable
# before pulling in the shared modules.
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

    structure = project.Structure()
    log("Structure: %d POU, %d GVL, %d DUT, %d ENUM" % (
        structure["counts"]["pous"],
        structure["counts"]["gvls"],
        structure["counts"]["duts"],
        structure["counts"]["enums"]))

    return structure


mcp_io.run(handler)
