using System.ComponentModel.DataAnnotations;

namespace McpServer.Models;

/// <summary>POST /dut/create. Acts on the project configured via the settings page.</summary>
public sealed class DutCreateRequest
{
    [Required(AllowEmptyStrings = false)]
    public string Name { get; set; } = string.Empty;

    /// <summary>Struct fields.</summary>
    [Required]
    [MinLength(1, ErrorMessage = "At least one field is required.")]
    public List<DutFieldDefinition> Fields { get; set; } = [];

    /// <summary>Optional base type for EXTENDS.</summary>
    public string? BaseType { get; set; }

    /// <summary>Optional project-relative folder path.</summary>
    public string? ParentPath { get; set; }
}

public sealed class DutFieldDefinition
{
    [Required(AllowEmptyStrings = false)]
    public string Name { get; set; } = string.Empty;

    [Required(AllowEmptyStrings = false)]
    public string Type { get; set; } = string.Empty;

    public string? InitialValue { get; set; }

    public string? Comment { get; set; }
}
