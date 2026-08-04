using System.ComponentModel.DataAnnotations;

namespace McpServer.Models;

/// <summary>POST /gvl/create</summary>
public sealed class GvlCreateRequest
{
    [Required(AllowEmptyStrings = false)]
    public string ProjectPath { get; set; } = string.Empty;

    [Required(AllowEmptyStrings = false)]
    public string Name { get; set; } = string.Empty;

    /// <summary>Optional project-relative folder path.</summary>
    public string? ParentPath { get; set; }

    /// <summary>Optional initial variables.</summary>
    public List<VariableDefinition>? Variables { get; set; }
}

public sealed class VariableDefinition
{
    [Required(AllowEmptyStrings = false)]
    public string Name { get; set; } = string.Empty;

    [Required(AllowEmptyStrings = false)]
    public string Type { get; set; } = string.Empty;

    /// <summary>Optional initial value, e.g. "0" or "TRUE".</summary>
    public string? InitialValue { get; set; }

    /// <summary>Optional trailing comment.</summary>
    public string? Comment { get; set; }
}
