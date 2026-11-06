using System.Text.Json;
using CodesysMcpServer.Web.Models;

namespace CodesysMcpServer.Web.Services;

/// <summary>A configured project plus the state of its CODESYS session (<c>GET /projects</c>, <c>projects</c> tool).</summary>
/// <param name="Session">Session state, as in <see cref="CodesysSessionStatus.State"/>.</param>
/// <param name="PasswordNeeded">
/// <c>password_required</c> / <c>password_invalid</c> when the project could not be opened for
/// its password — the user has to enter it on the settings page; null otherwise.
/// </param>
/// <param name="HasPassword">Whether a password was entered for this project (it is never returned).</param>
public sealed record ProjectSummary(
    string Name, string Path, bool IsDefault, bool Exists, string Session, string? PasswordNeeded, bool HasPassword);

/// <summary>
/// The one place that knows how to turn a request into a CODESYS script run. Both the REST
/// endpoints in <c>Program.cs</c> and the MCP tools in <c>Mcp/CodesysTools.cs</c> call these
/// methods; neither talks to <see cref="PythonRunner"/> directly. This is where request
/// validation, script selection and payload shaping live, so the two transports can never
/// drift apart on what an operation actually does — only on how they report success/failure.
///
/// Every operation acts on a project configured via the settings page: the default one
/// (<see cref="CodesysOptions.ProjectPath"/>) unless the optional <c>project</c> argument names
/// another configured project (see <see cref="ProjectCatalog.Resolve"/>). Callers can never pass
/// an arbitrary project path in.
/// </summary>
public sealed class CodesysOperations
{
    private readonly PythonRunner _runner;
    private readonly ProjectCatalog _projects;
    private readonly CodesysSessionPool _sessions;
    private readonly ProjectPasswords _passwords;

    public CodesysOperations(
        PythonRunner runner, ProjectCatalog projects, CodesysSessionPool sessions, ProjectPasswords passwords)
    {
        _runner = runner;
        _projects = projects;
        _sessions = sessions;
        _passwords = passwords;
    }

    public IReadOnlyList<ProjectSummary> ListProjects() =>
        _projects.List()
            .Select(p => new ProjectSummary(
                p.Name, p.Path, p.IsDefault, p.Exists, _sessions.GetStatus(p).State,
                _passwords.Needed(p.Path), _passwords.Has(p.Path)))
            .ToList();

    /// <summary>Stores (or, when empty, forgets) the password of a configured project.</summary>
    public CodesysProject SetProjectPassword(string? project, string? password)
    {
        var resolved = _projects.Resolve(project);
        _passwords.Set(resolved.Path, password);
        return resolved;
    }

    /// <summary>Opens the project and nothing else — warms up the persistent CODESYS session.</summary>
    public Task<JsonElement> OpenProjectAsync(string? project, CancellationToken ct) =>
        RunAsync("ping.py", project, projectPath => new { projectPath }, ct);

    public Task<JsonElement> GetStructureAsync(string? project, CancellationToken ct) =>
        GetStructureAsync(project, library: null, ct);

    public Task<JsonElement> GetStructureAsync(string? project, string? library, CancellationToken ct) =>
        RunReadAsync("structure.py", project, library, projectPath => new { projectPath }, ct);

    public Task<JsonElement> GetPouContentAsync(string name, string? project, CancellationToken ct) =>
        GetPouContentAsync(name, project, library: null, ct);

    public Task<JsonElement> GetPouContentAsync(string name, string? project, string? library, CancellationToken ct) =>
        RunReadAsync("pou_read.py", project, library, projectPath => new { projectPath, name }, ct);

    public Task<JsonElement> GetGvlContentAsync(string name, string? filter, string? project, CancellationToken ct) =>
        GetGvlContentAsync(name, filter, project, library: null, ct);

    public Task<JsonElement> GetGvlContentAsync(
        string name, string? filter, string? project, string? library, CancellationToken ct) =>
        RunReadAsync(
            "gvl_read.py",
            project,
            library,
            projectPath => new { projectPath, name, filter = string.IsNullOrWhiteSpace(filter) ? null : filter },
            ct);

    /// <summary>
    /// Library references of the project, each with the file it can be read from. With
    /// <paramref name="name"/>, only the matching reference.
    /// </summary>
    public Task<JsonElement> ListLibrariesAsync(string? project, string? name, CancellationToken ct) =>
        RunAsync(
            "libraries.py",
            project,
            projectPath => new { projectPath, name = string.IsNullOrWhiteSpace(name) ? null : name.Trim() },
            ct);

    public Task<JsonElement> GetTaskConfigurationAsync(string? project, CancellationToken ct) =>
        RunAsync("task_config.py", project, projectPath => new { projectPath }, ct);

    public const int MaxSearchResults = 5000;

    public Task<JsonElement> SearchTextAsync(
        string pattern, bool regex, bool caseSensitive, bool ignoreComments, int? maxResults, string? project, CancellationToken ct) =>
        SearchTextAsync(pattern, regex, caseSensitive, ignoreComments, maxResults, project, library: null, ct);

    public Task<JsonElement> SearchTextAsync(
        string pattern, bool regex, bool caseSensitive, bool ignoreComments, int? maxResults, string? project,
        string? library, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(pattern))
            throw new CodesysValidationException("A search pattern is required.");

        if (maxResults is < 1 or > MaxSearchResults)
            throw new CodesysValidationException($"maxResults must be between 1 and {MaxSearchResults}.");

        return RunReadAsync(
            "search_text.py",
            project,
            library,
            projectPath => new
            {
                projectPath,
                pattern,
                regex,
                caseSensitive,
                ignoreComments,
                maxResults = maxResults ?? 200,
            },
            ct);
    }

    public Task<JsonElement> GetDutContentAsync(string name, string? project, CancellationToken ct) =>
        GetDutContentAsync(name, project, library: null, ct);

    public Task<JsonElement> GetDutContentAsync(string name, string? project, string? library, CancellationToken ct) =>
        RunReadAsync("dut_read.py", project, library, projectPath => new { projectPath, name }, ct);

    public Task<JsonElement> GetEnumContentAsync(string name, string? project, CancellationToken ct) =>
        GetEnumContentAsync(name, project, library: null, ct);

    public Task<JsonElement> GetEnumContentAsync(string name, string? project, string? library, CancellationToken ct) =>
        RunReadAsync("enum_read.py", project, library, projectPath => new { projectPath, name }, ct);

    public Task<JsonElement> UpdatePouAsync(PouUpdateRequest request, string? project, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "pou_update.py",
            project,
            projectPath => new
            {
                projectPath,
                name = request.PouName,
                implementation = request.NewCode,
                declaration = request.NewDeclaration,
            },
            ct);
    }

    public Task<JsonElement> CreatePouAsync(PouCreateRequest request, string? project, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "pou_create.py",
            project,
            projectPath => new
            {
                projectPath,
                name = request.Name,
                type = request.Type,
                language = request.Language,
                returnType = request.ReturnType,
                parentPath = request.ParentPath,
                implementation = request.Implementation,
                declaration = request.Declaration,
            },
            ct);
    }

    public Task<JsonElement> CreateGvlAsync(GvlCreateRequest request, string? project, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "gvl_create.py",
            project,
            projectPath => new
            {
                projectPath,
                name = request.Name,
                parentPath = request.ParentPath,
                variables = request.Variables?.Select(v => new
                {
                    name = v.Name,
                    type = v.Type,
                    initialValue = v.InitialValue,
                    comment = v.Comment,
                }),
            },
            ct);
    }

    public Task<JsonElement> CreateDutAsync(DutCreateRequest request, string? project, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "dut_create.py",
            project,
            projectPath => new
            {
                projectPath,
                name = request.Name,
                baseType = request.BaseType,
                parentPath = request.ParentPath,
                fields = request.Fields.Select(f => new
                {
                    name = f.Name,
                    type = f.Type,
                    initialValue = f.InitialValue,
                    comment = f.Comment,
                }),
            },
            ct);
    }

    public Task<JsonElement> CreateEnumAsync(EnumCreateRequest request, string? project, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "enum_create.py",
            project,
            projectPath => new
            {
                projectPath,
                name = request.Name,
                values = request.Values,
                baseType = request.BaseType,
                parentPath = request.ParentPath,
            },
            ct);
    }

    public Task<JsonElement> CompileAsync(CompileRequest request, string? project, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "compile.py",
            project,
            projectPath => new
            {
                projectPath,
                clean = request.Clean,
                save = request.SaveAfterCompile,
            },
            ct);
    }

    /// <summary>
    /// A read-only operation on the project itself or, with <paramref name="library"/>, on one of
    /// the libraries it references. The library's file is never taken from the caller: it is the
    /// one the configured project's own reference resolves to (see <c>libraries.py</c>), and only
    /// source libraries (<c>.library</c>) can be read — compiled ones carry no source.
    /// </summary>
    private async Task<JsonElement> RunReadAsync(
        string script, string? project, string? library, Func<string, object> payload, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(library))
            return await RunAsync(script, project, payload, ct);

        var libraryPath = await ResolveLibraryFileAsync(project, library, ct);
        return await RunOnFileAsync(script, libraryPath, payload, ct);
    }

    private async Task<string> ResolveLibraryFileAsync(string? project, string library, CancellationToken ct)
    {
        var reference = await ListLibrariesAsync(project, library, ct);
        var title = reference.TryGetProperty("title", out var t) && t.ValueKind == JsonValueKind.String
            ? t.GetString()
            : library;

        if (!reference.TryGetProperty("source", out var source) || source.ValueKind != JsonValueKind.Object)
        {
            var resolution = reference.TryGetProperty("effectiveResolution", out var r) ? r.ToString() : "?";
            throw new CodesysValidationException(
                $"Library '{title}' ({resolution}) is referenced, but no file for it was found: it is not " +
                "installed in a library repository and there is no matching .library file next to the project.");
        }

        var file = source.GetProperty("file").GetString()!;
        var kind = source.TryGetProperty("kind", out var k) ? k.GetString() : null;
        if (!string.Equals(kind, "source", StringComparison.OrdinalIgnoreCase))
        {
            throw new CodesysValidationException(
                $"Library '{title}' is only available compiled ({file}); a compiled library carries no " +
                "readable source. Install or place its .library file next to the project.");
        }

        return file;
    }

    /// <summary>Runs a read script against a file that is not a configured project (a referenced library).</summary>
    private async Task<JsonElement> RunOnFileAsync(
        string script, string filePath, Func<string, object> payload, CancellationToken ct)
    {
        if (!File.Exists(filePath))
            throw new CodesysValidationException($"Library file not found: {filePath}");

        var result = await _runner.ExecuteAsync(script, filePath, payload(filePath), projectPassword: null, ct);
        return result.Data;
    }

    private async Task<JsonElement> RunAsync(
        string script, string? project, Func<string, object> payload, CancellationToken ct)
    {
        var resolved = _projects.Resolve(project);
        var projectPath = resolved.Path;

        if (!File.Exists(projectPath))
            throw new CodesysValidationException($"Project file not found: {projectPath}");

        try
        {
            var result = await _runner.ExecuteAsync(
                script, projectPath, payload(projectPath), _passwords.Get(projectPath), ct);
            _passwords.MarkOpened(projectPath);
            return result.Data;
        }
        catch (ScriptExecutionException ex) when (ProjectPasswords.IsPasswordCode(ex.ErrorCode))
        {
            _passwords.MarkNeeded(projectPath, ex.ErrorCode!);
            throw new ProjectPasswordException(resolved, ex.ErrorCode!, ex);
        }
    }
}
