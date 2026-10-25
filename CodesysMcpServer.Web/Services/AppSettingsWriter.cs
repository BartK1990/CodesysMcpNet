using System.Text.Json;
using System.Text.Json.Nodes;
using CodesysMcpServer.Web.Models;
using Microsoft.Extensions.Options;

namespace CodesysMcpServer.Web.Services;

/// <summary>
/// Backs the settings page (<c>wwwroot/index.html</c>, <c>GET</c>/<c>POST /settings</c>).
/// Persists the CODESYS executable path, the default project path and any additional projects to
/// <c>appsettings.production.json</c> next to the running binary (<see cref="AppContext.BaseDirectory"/>)
/// — the same path <c>Program.cs</c> registers as a reloading configuration source, so a save
/// takes effect immediately without restarting the server. That file is excluded from source
/// control and from the build/publish output (see McpServer.csproj and .gitignore): it only
/// ever exists as a machine-local file created the first time someone saves settings.
/// </summary>
public sealed class AppSettingsWriter
{
    private static readonly JsonSerializerOptions WriteOptions = new() { WriteIndented = true };
    private static readonly TimeSpan ReloadWait = TimeSpan.FromSeconds(5);

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
        return Describe(
            current.ExecutablePath,
            current.ProjectPath ?? string.Empty,
            current.Profile ?? string.Empty,
            current.EffectiveMaxProjects,
            current.AdditionalProjectPaths);
    }

    /// <summary>
    /// Validates and saves <paramref name="request"/>. Paths must exist; <c>MaxProjects</c> and
    /// <c>AdditionalProjectPaths</c> keep their current values when omitted.
    /// </summary>
    public async Task<SettingsSnapshot> SaveAsync(SettingsRequest request, CancellationToken ct)
    {
        var current = _options.CurrentValue;
        var executablePath = request.ExecutablePath.Trim();
        var projectPath = request.ProjectPath.Trim();
        var profile = request.Profile.Trim();
        var maxProjects = request.MaxProjects ?? current.EffectiveMaxProjects;
        var additional = CleanAdditional(projectPath, request.AdditionalProjectPaths ?? current.AdditionalProjectPaths);

        if (!File.Exists(executablePath))
            throw new CodesysValidationException($"CODESYS executable not found: {executablePath}");

        if (!File.Exists(projectPath))
            throw new CodesysValidationException($"Project file not found: {projectPath}");

        if (additional.Count > maxProjects - 1)
        {
            throw new CodesysValidationException(maxProjects == 1
                ? "Max projects is 1, so no additional projects can be configured. Remove them or raise Max projects."
                : $"Max projects is {maxProjects}, so at most {maxProjects - 1} additional project(s) can be configured; got {additional.Count}.");
        }

        var missing = additional.FirstOrDefault(p => !File.Exists(p));
        if (missing is not null)
            throw new CodesysValidationException($"Project file not found: {missing}");

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
            codesys["MaxProjects"] = maxProjects;
            codesys["AdditionalProjectPaths"] = new JsonArray(additional.Select(p => (JsonNode?)JsonValue.Create(p)).ToArray());

            await File.WriteAllTextAsync(_path, root.ToJsonString(WriteOptions), ct);
        }
        finally
        {
            FileLock.Release();
        }

        await WaitForReloadAsync(executablePath, projectPath, profile, maxProjects, additional, ct);
        return Describe(executablePath, projectPath, profile, maxProjects, additional);
    }

    /// <summary>
    /// The file watcher reloads configuration shortly after the write. Wait for it (briefly), so
    /// the request right after a save — e.g. the page re-reading <c>/projects</c> — already sees it.
    /// </summary>
    private async Task WaitForReloadAsync(
        string executablePath, string projectPath, string profile, int maxProjects, List<string> additional, CancellationToken ct)
    {
        var deadline = DateTime.UtcNow + ReloadWait;
        while (DateTime.UtcNow < deadline)
        {
            var current = _options.CurrentValue;
            if (current.ExecutablePath == executablePath &&
                current.ProjectPath == projectPath &&
                (current.Profile ?? string.Empty) == profile &&
                current.EffectiveMaxProjects == maxProjects &&
                current.AdditionalProjectPaths.SequenceEqual(additional))
            {
                return;
            }

            await Task.Delay(50, ct);
        }
    }

    /// <summary>Trims, drops blanks, and removes duplicates (including of the default project).</summary>
    private static List<string> CleanAdditional(string projectPath, IEnumerable<string> paths)
    {
        var result = new List<string>();
        foreach (var raw in paths)
        {
            var path = raw?.Trim();
            if (string.IsNullOrEmpty(path) || ProjectCatalog.SamePath(path, projectPath) ||
                result.Any(p => ProjectCatalog.SamePath(p, path)))
            {
                continue;
            }

            result.Add(path);
        }

        return result;
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

    private static SettingsSnapshot Describe(
        string executablePath,
        string projectPath,
        string profile,
        int maxProjects,
        IEnumerable<string> additionalProjectPaths) => new(
        executablePath,
        projectPath,
        profile,
        !string.IsNullOrWhiteSpace(executablePath) && File.Exists(executablePath),
        !string.IsNullOrWhiteSpace(projectPath) && File.Exists(projectPath),
        maxProjects,
        CodesysOptions.MaxProjectsLimit,
        additionalProjectPaths
            .Where(p => !string.IsNullOrWhiteSpace(p))
            .Select(p => new ProjectPathStatus(p, File.Exists(p)))
            .ToList());
}
