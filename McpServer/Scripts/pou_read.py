# -*- coding: utf-8 -*-
"""
GET /pou/content

Returns the full ST source of a POU: declaration, implementation, the two combined,
plus its type, language and members (methods / actions / properties).
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

    pou = project.FindPou(name)
    log("Reading POU '" + pou.Path + "' (" + str(pou.Type) + ", " + str(pou.Language) + ")")

    return pou.Content()


mcp_io.run(handler)
