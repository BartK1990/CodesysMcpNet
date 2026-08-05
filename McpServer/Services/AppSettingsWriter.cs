using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Extensions.Options;

namespace McpServer.Services;

/// <summary>
/// Backs the settings page (<c>wwwroot/index.html</c>, <c>GET</c>/<c>POST /settings</c>).
/// Persists the CODESYS executable path and the selected project path to
/// <c>appsettings.production.json</c> next to the running binary (<see cref="AppContext.BaseDirectory"/>)
/// — the same path <c>Program.cs</c> registers as a reloading configuration source, so a save
/// takes effect immediately without restarting the server. That file is excluded from source
/// control and from the build/publish output (see McpServer.csproj and .gitignore): it only
/// ever exists as a machine-local file created the first time someone saves settings.
/// </summary>
public sealed class AppSettingsWriter
{
    private static readonly JsonSerializerOptions WriteOptions = new() { WriteIndented = true };

    // Guards read-modify-write of the settings file against concurrent saves.
    private static readonly SemaphoreSlim FileLock = new(1, 1);

    private readonly string _path;
    private readonly IOptionsMonitor<CodesysOptions> _options;

    public AppSettingsWriter(IOptionsMonitor<CodesysOptions> options)
    {
        _options = options;
        _path = Path.Combine(AppContext.BaseDirectory, "appsettings.production.json");
    }

    public SettingsSnapshot GetCurrent()
    {
        var current = _options.CurrentValue;
        return Describe(current.ExecutablePath, current.ProjectPath ?? string.Empty, current.Profile ?? string.Empty);
    }

    public async Task<SettingsSnapshot> SaveAsync(
        string executablePath,
        string projectPath,
        string profile,
        CancellationToken ct)
    {
        await FileLock.WaitAsync(ct);
        try
        {
            var root = await ReadRootAsync(ct);

            if (root[CodesysOptions.SectionName] is not JsonObject codesys)
            {
                codesys = new JsonObject();
                root[CodesysOptions.SectionName] = codesys;
            }

            codesys["ExecutablePath"] = executablePath;
            codesys["ProjectPath"] = projectPath;
            codesys["Profile"] = profile;

            await File.WriteAllTextAsync(_path, root.ToJsonString(WriteOptions), ct);
        }
        finally
        {
            FileLock.Release();
        }

        return Describe(executablePath, projectPath, profile);
    }

    private async Task<JsonObject> ReadRootAsync(CancellationToken ct)
    {
        if (!File.Exists(_path))
            return new JsonObject();

        var text = await File.ReadAllTextAsync(_path, ct);
        if (string.IsNullOrWhiteSpace(text))
            return new JsonObject();

        return JsonNode.Parse(text) as JsonObject ?? new JsonObject();
    }

    private static SettingsSnapshot Describe(string executablePath, string projectPath, string profile) => new(
        executablePath,
        projectPath,
        profile,
        !string.IsNullOrWhiteSpace(executablePath) && File.Exists(executablePath),
        !string.IsNullOrWhiteSpace(projectPath) && File.Exists(projectPath));
}
