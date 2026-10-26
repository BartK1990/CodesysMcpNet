using System.ComponentModel.DataAnnotations;
using CodesysMcpServer.Web.Services;

namespace CodesysMcpServer.Web.Models;

/// <summary>POST /settings — saved to appsettings.production.json.</summary>
public sealed class SettingsRequest
{
    /// <summary>Full path to CODESYS.exe.</summary>
    [Required(AllowEmptyStrings = false)]
    public string ExecutablePath { get; set; } = string.Empty;

    /// <summary>Full path to the default .project file — the one endpoints and MCP tools act on when no project is named.</summary>
    [Required(AllowEmptyStrings = false)]
    public string ProjectPath { get; set; } = string.Empty;

    /// <summary>Profile name passed to <c>--profile</c>. Empty uses CODESYS's default profile.</summary>
    public string Profile { get; set; } = string.Empty;

    /// <summary>How many projects may be configured (1 = only <see cref="ProjectPath"/>). Omit to keep the current value.</summary>
    [Range(1, CodesysOptions.MaxProjectsLimit)]
    public int? MaxProjects { get; set; }

    /// <summary>
    /// Further .project files, at most <see cref="MaxProjects"/> - 1 of them. Omit to keep the
    /// current list; pass an empty list to clear it.
    /// </summary>
    public List<string>? AdditionalProjectPaths { get; set; }
}
