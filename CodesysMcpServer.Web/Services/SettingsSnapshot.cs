namespace CodesysMcpServer.Web.Services;

/// <summary>Current CODESYS executable/project paths, as returned by GET and POST /settings.</summary>
/// <param name="ProjectPath">The default project.</param>
/// <param name="MaxProjects">How many projects may be configured (1 = only the default one).</param>
/// <param name="MaxProjectsLimit">Upper bound accepted for <paramref name="MaxProjects"/>.</param>
/// <param name="AdditionalProjects">Further configured projects besides the default one.</param>
public sealed record SettingsSnapshot(
    string ExecutablePath,
    string ProjectPath,
    string Profile,
    bool ExecutableExists,
    bool ProjectExists,
    int MaxProjects,
    int MaxProjectsLimit,
    IReadOnlyList<ProjectPathStatus> AdditionalProjects);

/// <summary>A configured project path and whether it exists on this machine.</summary>
public sealed record ProjectPathStatus(string Path, bool Exists);
