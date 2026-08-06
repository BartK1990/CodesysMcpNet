using System.ComponentModel.DataAnnotations;

namespace CodesysMcpServer.Web.Models;

/// <summary>POST /pou/update. Acts on the project configured via the settings page.</summary>
public sealed class PouUpdateRequest
{
    /// <summary>POU name. Use "Parent.Child" to target a method/action/property part.</summary>
    [Required(AllowEmptyStrings = false)]
    public string PouName { get; set; } = string.Empty;

    /// <summary>New implementation (body) text of the POU.</summary>
    [Required]
    public string NewCode { get; set; } = string.Empty;

    /// <summary>Optional replacement for the declaration part (VAR blocks). Left untouched when null.</summary>
    public string? NewDeclaration { get; set; }
}
