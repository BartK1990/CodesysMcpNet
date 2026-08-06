# -*- coding: utf-8 -*-
"""
POST /pou/create

Creates a new POU (PRG / FB / FUN) in the requested implementation language,
optionally seeding its declaration and implementation, then saves the project.
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
    name = require(request, "name")
    pou_type = request.get("type") or "PRG"
    language = request.get("language") or "ST"
    return_type = request.get("returnType")
    parent_path = request.get("parentPath")
    implementation = request.get("implementation")
    declaration = request.get("declaration")

    app = Application()
    project = app.OpenProject(project_path)

    log("Creating POU '" + name + "' (" + str(pou_type) + ", " + str(language) + ")")
    pou = project.CreatePou(
        name=name,
        pou_type=pou_type,
        language=language,
        return_type=return_type,
        parent_path=parent_path)

    if declaration is not None or implementation is not None:
        # Only ST-like languages carry a textual implementation; a graphical POU
        # would raise here, which is the correct signal back to the caller.
        pou.SetText(implementation=implementation, declaration=declaration)

    project.Save()

    result = pou.Content()
    result["created"] = True
    result["saved"] = True
    return result


mcp_io.run(handler)
