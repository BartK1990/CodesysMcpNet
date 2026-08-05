using System.ComponentModel.DataAnnotations;

namespace McpServer.Models;

/// <summary>POST /settings — saved to appsettings.production.json.</summary>
public sealed class SettingsRequest
{
    /// <summary>Full path to CODESYS.exe.</summary>
    [Required(AllowEmptyStrings = false)]
    public string ExecutablePath { get; set; } = string.Empty;

    /// <summary>Full path to the .project file every endpoint and MCP tool should act on.</summary>
    [Required(AllowEmptyStrings = false)]
    public string ProjectPath { get; set; } = string.Empty;

    /// <summary>Profile name passed to <c>--profile</c>. Empty uses CODESYS's default profile.</summary>
    public string Profile { get; set; } = string.Empty;
}
