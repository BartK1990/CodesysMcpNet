# -*- coding: utf-8 -*-
"""
GET /libraries

Lists the library references of the project (the project-level library manager and the
one of every application): name, namespace, placeholder, requested and effective
resolution, and the file the library can be read from - a source .library in a library
repository or next to the project - when there is one.

With "name", returns only the matching reference (placeholder name, title, namespace,
reference name or resolution, case-insensitive); the server uses that to find the file
the library tools read from.
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
    name = request.get("name")

    app = Application()
    project = app.OpenProject(project_path)

    if name:
        found = project.FindLibrary(name)
        source = found.get("source")
        log("Library '%s' -> %s" % (name, source["file"] if source else "no readable file"))
        return found

    result = project.LibraryReferences()
    log("%d library reference(s)" % result["count"])
    return result


mcp_io.run(handler)
