# -*- coding: utf-8 -*-
"""
POST /pou/update

Replaces the implementation text of a POU and, when a declaration is supplied,
its declaration too. The project is saved afterwards.
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
    implementation = request.get("implementation")
    declaration = request.get("declaration")

    if implementation is None and declaration is None:
        raise ValueError("Nothing to update: supply newCode and/or newDeclaration.")

    app = Application()
    project = app.OpenProject(project_path)

    pou = project.FindPou(name)
    before = pou.GetText()

    log("Updating POU '" + pou.Path + "'")
    changed = pou.SetText(implementation=implementation, declaration=declaration)

    project.Save()
    after = pou.GetText()

    return {
        "name": pou.Name,
        "path": pou.Path,
        "type": pou.Type,
        "language": pou.Language,
        "changed": changed,
        "saved": True,
        "previous": before,
        "current": after,
    }


mcp_io.run(handler)
