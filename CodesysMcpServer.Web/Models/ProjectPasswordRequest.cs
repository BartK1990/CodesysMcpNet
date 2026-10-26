namespace CodesysMcpServer.Web.Models;

/// <summary>POST /projects/password — kept in memory only, never saved or returned.</summary>
public sealed class ProjectPasswordRequest
{
    /// <summary>A configured project's name or full path; omit for the default project.</summary>
    public string? Project { get; set; }

    /// <summary>The project's password. Empty forgets a previously entered one.</summary>
    public string? Password { get; set; }
}
