# -*- coding: utf-8 -*-
"""
POST /dut/create

Creates a STRUCT data unit type with the supplied fields, then saves the project.
The generated declaration replaces the empty skeleton CODESYS creates.
"""

from __future__ import print_function

import os
import sys

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mcp_io
from mcp_io import log, require
from codesys_api import Application, Dut, build_struct_declaration


def handler(request):
    project_path = require(request, "projectPath")
    name = require(request, "name")
    fields = request.get("fields") or []
    base_type = request.get("baseType")
    parent_path = request.get("parentPath")

    if not fields:
        raise ValueError("At least one field is required to create a DUT.")

    app = Application()
    project = app.OpenProject(project_path)

    log("Creating DUT '" + name + "' with " + str(len(fields)) + " field(s)")
    created = project.CreateDut(
        name=name,
        dut_kind="struct",
        base_type=base_type,
        parent_path=parent_path)

    path = (parent_path.rstrip("/") + "/" + name) if parent_path else name
    dut = Dut(created, path, parsed={"kind": "struct", "name": name,
                                     "baseType": base_type, "elements": [], "values": []})

    dut.SetText(declaration=build_struct_declaration(name, fields, base_type))
    project.Save()

    # Re-parse from what is now actually stored in the project.
    result = Dut(created, path).Content()
    result["created"] = True
    result["saved"] = True
    return result


mcp_io.run(handler)
