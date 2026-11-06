using System.ComponentModel;
using System.ComponentModel.DataAnnotations;

namespace CodesysMcpServer.Web.Models;

/// <summary>
/// POST /recipes/update. Changes one recipe definition of a Recipe Manager, then saves the
/// project. Applied in this order: remove recipes, remove variables, add/update variables,
/// create/update recipes. Every name is checked first, so a bad request changes nothing.
/// </summary>
public sealed class RecipeUpdateRequest
{
    [Required(AllowEmptyStrings = false)]
    [Description("Recipe definition name (e.g. \"Parameter\") or its path as the recipes tool lists it.")]
    public string Definition { get; set; } = string.Empty;

    [Description("Optional application (name or path) whose Recipe Manager holds the definition. Needed only when several applications have one.")]
    public string? Application { get; set; }

    [Description("Create the recipe definition in the application's Recipe Manager when it does not exist yet. The Recipe Manager itself must already exist.")]
    public bool Create { get; set; }

    [Description("Variables (rows) to add, or to update when the definition already has them. Fields left out stay unchanged.")]
    public List<RecipeVariableChange>? Variables { get; set; }

    [Description("Variable expressions (rows) to remove.")]
    public List<string>? RemoveVariables { get; set; }

    [Description("Recipes (value columns) to create, or to update when they exist, with the values to set.")]
    public List<RecipeChange>? Recipes { get; set; }

    [Description("Names of recipes to remove.")]
    public List<string>? RemoveRecipes { get; set; }
}

public sealed class RecipeVariableChange
{
    [Required(AllowEmptyStrings = false)]
    [Description("Full path of the PLC variable, e.g. \"GVL_Recipe.rSpeed\" or \"PLC_PRG.stParams.iCount\". Matched case-insensitively.")]
    public string Variable { get; set; } = string.Empty;

    [Description("Optional display name.")]
    public string? Name { get; set; }

    [Description("Optional comment.")]
    public string? Comment { get; set; }

    [Description("Optional minimum value, e.g. \"0\".")]
    public string? MinValue { get; set; }

    [Description("Optional maximum value, e.g. \"100\".")]
    public string? MaxValue { get; set; }
}

public sealed class RecipeChange
{
    [Required(AllowEmptyStrings = false)]
    [Description("Recipe name. Matched case-insensitively.")]
    public string Name { get; set; } = string.Empty;

    [Description("Values to set: variable expression -> value as text, as the recipe editor shows it (e.g. \"12.5\", \"TRUE\"). The variables must be in the definition (or added in the same request).")]
    public Dictionary<string, string?>? Values { get; set; }
}
