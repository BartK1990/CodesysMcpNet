using System.ComponentModel.DataAnnotations;

namespace CodesysMcpServer.Web.Models;

/// <summary>POST /pou/create. Acts on the project configured via the settings page.</summary>
public sealed class PouCreateRequest
{
    [Required(AllowEmptyStrings = false)]
    public string Name { get; set; } = string.Empty;

    /// <summary>PRG | FB | FUN (aliases: Program, FunctionBlock, Function).</summary>
    [Required(AllowEmptyStrings = false)]
    public string Type { get; set; } = "PRG";

    /// <summary>ST | IL | LD | FBD | SFC | CFC. Defaults to ST.</summary>
    public string Language { get; set; } = "ST";

    /// <summary>Return type, only meaningful for FUN. Defaults to BOOL when omitted.</summary>
    public string? ReturnType { get; set; }

    /// <summary>Optional project-relative folder path, e.g. "Application/Logic".</summary>
    public string? ParentPath { get; set; }

    /// <summary>Optional initial implementation text.</summary>
    public string? Implementation { get; set; }

    /// <summary>Optional initial declaration text (replaces the generated header when provided).</summary>
    public string? Declaration { get; set; }
}
