using System.Text.Json;
using McpServer.Models;
using Microsoft.Extensions.Options;

namespace McpServer.Services;

/// <summary>
/// The one place that knows how to turn a request into a CODESYS script run. Both the REST
/// endpoints in <c>Program.cs</c> and the MCP tools in <c>Mcp/CodesysTools.cs</c> call these
/// methods; neither talks to <see cref="PythonRunner"/> directly. This is where request
/// validation, script selection and payload shaping live, so the two transports can never
/// drift apart on what an operation actually does — only on how they report success/failure.
///
/// Every operation acts on the single project configured via the settings page
/// (<see cref="CodesysOptions.ProjectPath"/>) — callers no longer pass a project path in.
/// </summary>
public sealed class CodesysOperations
{
    private readonly PythonRunner _runner;
    private readonly IOptionsMonitor<CodesysOptions> _options;

    public CodesysOperations(PythonRunner runner, IOptionsMonitor<CodesysOptions> options)
    {
        _runner = runner;
        _options = options;
    }

    private string? CurrentProjectPath => _options.CurrentValue.ProjectPath;

    public Task<JsonElement> GetStructureAsync(CancellationToken ct) =>
        RunAsync("structure.py", new { projectPath = CurrentProjectPath }, ct);

    public Task<JsonElement> GetPouContentAsync(string name, CancellationToken ct) =>
        RunAsync("pou_read.py", new { projectPath = CurrentProjectPath, name }, ct);

    public Task<JsonElement> GetGvlContentAsync(string name, CancellationToken ct) =>
        RunAsync("gvl_read.py", new { projectPath = CurrentProjectPath, name }, ct);

    public Task<JsonElement> GetDutContentAsync(string name, CancellationToken ct) =>
        RunAsync("dut_read.py", new { projectPath = CurrentProjectPath, name }, ct);

    public Task<JsonElement> GetEnumContentAsync(string name, CancellationToken ct) =>
        RunAsync("enum_read.py", new { projectPath = CurrentProjectPath, name }, ct);

    public Task<JsonElement> UpdatePouAsync(PouUpdateRequest request, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "pou_update.py",
            new
            {
                projectPath = CurrentProjectPath,
                name = request.PouName,
                implementation = request.NewCode,
                declaration = request.NewDeclaration,
            },
            ct);
    }

    public Task<JsonElement> CreatePouAsync(PouCreateRequest request, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "pou_create.py",
            new
            {
                projectPath = CurrentProjectPath,
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

    public Task<JsonElement> CreateGvlAsync(GvlCreateRequest request, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "gvl_create.py",
            new
            {
                projectPath = CurrentProjectPath,
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

    public Task<JsonElement> CreateDutAsync(DutCreateRequest request, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "dut_create.py",
            new
            {
                projectPath = CurrentProjectPath,
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

    public Task<JsonElement> CreateEnumAsync(EnumCreateRequest request, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "enum_create.py",
            new
            {
                projectPath = CurrentProjectPath,
                name = request.Name,
                values = request.Values,
                baseType = request.BaseType,
                parentPath = request.ParentPath,
            },
            ct);
    }

    public Task<JsonElement> CompileAsync(CompileRequest request, CancellationToken ct)
    {
        RequestValidator.Validate(request);

        return RunAsync(
            "compile.py",
            new
            {
                projectPath = CurrentProjectPath,
                clean = request.Clean,
                save = request.SaveAfterCompile,
            },
            ct);
    }

    private async Task<JsonElement> RunAsync(string script, object payload, CancellationToken ct)
    {
        var projectPath = CurrentProjectPath;

        if (string.IsNullOrWhiteSpace(projectPath))
        {
            throw new CodesysValidationException(
                "No project is configured. Set one on the settings page (/) or via POST /settings.");
        }

        if (!File.Exists(projectPath))
            throw new CodesysValidationException($"Project file not found: {projectPath}");

        var result = await _runner.ExecuteAsync(script, payload, ct);
        return result.Data;
    }
}
