# -*- coding: utf-8 -*-
"""
GET /enum/content

Returns every enumerator of an ENUM DUT with its explicit value (when written),
the resolved ordinal and its comment.
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

    enumeration = project.FindEnum(name)
    content = enumeration.Content()
    log("Reading ENUM '" + enumeration.Path + "': " + str(len(content["values"])) + " value(s)")

    return content


mcp_io.run(handler)
