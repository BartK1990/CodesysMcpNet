using System.ComponentModel.DataAnnotations;

namespace McpServer.Models;

/// <summary>
/// POST /enum/create.
/// Values accept plain names ("Idle") or explicit assignments ("Idle := 10").
/// </summary>
public sealed class EnumCreateRequest
{
    [Required(AllowEmptyStrings = false)]
    public string ProjectPath { get; set; } = string.Empty;

    [Required(AllowEmptyStrings = false)]
    public string Name { get; set; } = string.Empty;

    [Required]
    [MinLength(1, ErrorMessage = "At least one value is required.")]
    public List<string> Values { get; set; } = [];

    /// <summary>Underlying base type, e.g. INT or DINT. Defaults to INT.</summary>
    public string? BaseType { get; set; }

    /// <summary>Optional project-relative folder path.</summary>
    public string? ParentPath { get; set; }
}
