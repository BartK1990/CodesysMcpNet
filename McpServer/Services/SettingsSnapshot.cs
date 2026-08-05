namespace McpServer.Services;

/// <summary>Current CODESYS executable/project paths, as returned by GET and POST /settings.</summary>
public sealed record SettingsSnapshot(
    string ExecutablePath,
    string ProjectPath,
    bool ExecutableExists,
    bool ProjectExists);
