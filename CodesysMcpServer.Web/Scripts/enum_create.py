# -*- coding: utf-8 -*-
"""
POST /enum/create

Creates an enumeration DUT. Values may be plain names ("Idle") or explicit
assignments ("Idle := 10"). The project is saved afterwards.
"""

from __future__ import print_function

import os
import sys

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mcp_io
from mcp_io import log, require
from codesys_api import Application, Enum, build_enum_declaration


def handler(request):
    project_path = require(request, "projectPath")
    name = require(request, "name")
    values = request.get("values") or []
    base_type = request.get("baseType") or "INT"
    parent_path = request.get("parentPath")

    if not values:
        raise ValueError("At least one value is required to create an ENUM.")

    app = Application()
    project = app.OpenProject(project_path)

    log("Creating ENUM '" + name + "' with " + str(len(values)) + " value(s)")
    created = project.CreateDut(
        name=name,
        dut_kind="enum",
        base_type=None,
        parent_path=parent_path)

    path = (parent_path.rstrip("/") + "/" + name) if parent_path else name

    enumeration = Enum(created, path, parsed={"kind": "enum", "name": name,
                                              "baseType": base_type, "elements": [], "values": []})
    enumeration.SetText(declaration=build_enum_declaration(name, values, base_type))
    project.Save()

    result = Enum(created, path).Content()
    result["created"] = True
    result["saved"] = True
    return result


mcp_io.run(handler)
