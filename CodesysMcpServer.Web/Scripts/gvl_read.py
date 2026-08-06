# -*- coding: utf-8 -*-
"""
GET /gvl/content

Returns every variable of a global variable list with its type, initial value,
address, block qualifiers and comment.
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

    gvl = project.FindGvl(name)
    content = gvl.Content()
    log("Reading GVL '" + gvl.Path + "': " + str(len(content["variables"])) + " variable(s)")

    return content


mcp_io.run(handler)
