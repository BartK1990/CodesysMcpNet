# -*- coding: utf-8 -*-
"""
GET /search

Searches the declarations and implementations of every POU (methods, actions,
properties and transitions included), GVL, DUT and ENUM, and returns one hit per
matching line: object, member, section, line number and the line itself.
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
    pattern = require(request, "pattern")

    app = Application()
    project = app.OpenProject(project_path)

    result = project.SearchText(
        pattern,
        is_regex=bool(request.get("regex")),
        case_sensitive=bool(request.get("caseSensitive")),
        ignore_comments=bool(request.get("ignoreComments")),
        max_results=int(request.get("maxResults") or 200))

    log("Search '%s': %d match(es) in %d object(s)%s" % (
        pattern, result["matchCount"], result["objectsSearched"],
        " (truncated)" if result["truncated"] else ""))

    return result


mcp_io.run(handler)
