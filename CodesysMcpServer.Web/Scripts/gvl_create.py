# -*- coding: utf-8 -*-
"""
POST /gvl/create

Creates a global variable list, optionally pre-filled with variables,
then saves the project.
"""

from __future__ import print_function

import os
import sys

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mcp_io
from mcp_io import log, require
from codesys_api import Application, build_gvl_declaration


def handler(request):
    project_path = require(request, "projectPath")
    name = require(request, "name")
    parent_path = request.get("parentPath")
    variables = request.get("variables") or []

    app = Application()
    project = app.OpenProject(project_path)

    log("Creating GVL '" + name + "' with " + str(len(variables)) + " variable(s)")
    gvl = project.CreateGvl(name=name, parent_path=parent_path)

    if variables:
        gvl.SetText(declaration=build_gvl_declaration(variables))

    project.Save()

    result = gvl.Content()
    result["created"] = True
    result["saved"] = True
    return result


mcp_io.run(handler)
