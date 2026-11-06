# -*- coding: utf-8 -*-
"""
GET /recipes

Without a definition: every Recipe Manager of the project with its settings and a
summary of each recipe definition (variable count, recipe names).

With a definition: its variables (expression, type, name, comment, min/max) and the
value of each in every recipe (or only in the given recipe), one page at a time.
"""

from __future__ import print_function

import os
import sys

_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or sys.argv[0]))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import mcp_io
from mcp_io import log, require
from codesys_api import Application, DEFAULT_RECIPE_PAGE


def handler(request):
    project_path = require(request, "projectPath")
    name = request.get("definition")

    app = Application()
    project = app.OpenProject(project_path)

    if not name:
        result = project.Recipes()
        log("Recipe managers: %d" % len(result["recipeManagers"]))
        return result

    definition = project.FindRecipeDefinition(name, request.get("application"))
    result = definition.Content(
        name_filter=request.get("filter"),
        recipe=request.get("recipe"),
        offset=request.get("offset") or 0,
        limit=request.get("maxVariables") or DEFAULT_RECIPE_PAGE)
    log("Recipe definition '%s': %d of %d variable(s) returned"
        % (definition.Path, result["returnedVariableCount"], result["totalVariableCount"]))
    return result


mcp_io.run(handler)
