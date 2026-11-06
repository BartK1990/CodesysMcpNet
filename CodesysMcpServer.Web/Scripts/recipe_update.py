# -*- coding: utf-8 -*-
"""
POST /recipes/update

Changes one recipe definition - creating it first when asked - then saves the project:
removes recipes and variables, adds or updates variables (name, comment, min/max), and
creates recipes or sets their values. Every name is checked before anything changes.
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
    name = require(request, "definition")
    application = request.get("application")

    app = Application()
    project = app.OpenProject(project_path)

    created = False
    try:
        definition = project.FindRecipeDefinition(name, application)
    except LookupError:
        if not request.get("create"):
            raise
        log("Creating recipe definition '" + name + "'")
        definition = project.CreateRecipeDefinition(name, application)
        created = True

    changes, warnings = definition.Apply(
        variables=request.get("variables"),
        remove_variables=request.get("removeVariables"),
        recipes=request.get("recipes"),
        remove_recipes=request.get("removeRecipes"))
    log("Recipe definition '%s' updated: %s" % (
        definition.Path, ", ".join("%s=%d" % (k, len(v)) for k, v in sorted(changes.items()) if v) or "no changes"))

    project.Save()

    result = definition.Summary()
    result["created"] = created
    result["changes"] = changes
    result["warnings"] = warnings
    result["saved"] = True
    return result


mcp_io.run(handler)
