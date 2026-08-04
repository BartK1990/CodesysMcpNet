# -*- coding: utf-8 -*-
"""
GET /dut/content

Returns every field of a structure / union DUT with its type, initial value and comment.
Enumerations are served by enum_read.py instead.
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

    app = Application()
    project = app.OpenProject(project_path)

    dut = project.FindDut(name)
    content = dut.Content()
    log("Reading DUT '" + dut.Path + "' (" + str(dut.Kind) + "): "
        + str(len(content["fields"])) + " field(s)")

    return content


mcp_io.run(handler)
