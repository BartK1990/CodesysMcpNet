using System.ComponentModel;
using System.Text.Json;
using CodesysMcpServer.Web.Models;
using CodesysMcpServer.Web.Services;
using ModelContextProtocol;
using ModelContextProtocol.Server;

namespace CodesysMcpServer.Web.Mcp;

/// <summary>
/// The MCP tool surface. Every tool is a direct pass-through to <see cref="CodesysOperations"/> —
/// the same service the REST endpoints in <c>Program.cs</c> call — so there's exactly one place
/// that knows how to talk to CODESYS. This class only adapts <see cref="CodesysOperations"/>'
/// exceptions into <see cref="McpException"/>, which is how MCP tools report a recoverable
/// error message back to the calling model.
/// </summary>
[McpServerToolType]
public sealed class CodesysTools
{
    private readonly CodesysOperations _ops;

    public CodesysTools(CodesysOperations ops)
    {
        _ops = ops;
    }

    [McpServerTool(Name = "structure")]
    [Description("Full project structure: POUs, GVLs, DUTs and ENUMs. Acts on the project configured via the settings page.")]
    public Task<JsonElement> StructureAsync(CancellationToken ct) =>
        Run(() => _ops.GetStructureAsync(ct));

    [McpServerTool(Name = "pou_content")]
    [Description("Full ST source (declaration + implementation) of a POU, or of one of its methods, actions, properties or transitions. Acts on the project configured via the settings page.")]
    public Task<JsonElement> PouContentAsync(
        [Description("POU name or path. Use \"Parent.Member\" for a method/action/property/transition (e.g. \"FB_Motor.Reset\"), and \"Parent.Property.Get\" for a property accessor.")] string name,
        CancellationToken ct) =>
        Run(() => _ops.GetPouContentAsync(name, ct));

    [McpServerTool(Name = "gvl_content")]
    [Description("Variables of a global variable list, with types and initial values. Pass a filter for large lists: the result then holds only matching variables and omits the full declaration text. Acts on the project configured via the settings page.")]
    public Task<JsonElement> GvlContentAsync(
        [Description("GVL name.")] string name,
        [Description("Optional case-insensitive variable-name filter: a wildcard pattern (\"*Fault*\", \"x?Run\") or, without * or ?, a substring.")] string? filter = null,
        CancellationToken ct = default) =>
        Run(() => _ops.GetGvlContentAsync(name, filter, ct));

    [McpServerTool(Name = "search_text")]
    [Description("Search the declarations and implementations of all POUs (incl. methods, actions, properties, transitions), GVLs, DUTs and ENUMs. Returns one hit per matching line: POU, member, section, 1-based line number and the line text. Use a regex such as \"\\bxFault\\s*:=\" to find writes to a variable. Graphical (FBD/LD/CFC/SFC) bodies are not searchable and are listed in implementationNotTextual. Acts on the project configured via the settings page.")]
    public Task<JsonElement> SearchTextAsync(
        [Description("Text to find. Plain text unless regex is true.")] string pattern,
        [Description("Treat pattern as a Python regular expression.")] bool regex = false,
        [Description("Match case exactly (default: case-insensitive).")] bool caseSensitive = false,
        [Description("Skip matches inside comments and pragmas.")] bool ignoreComments = false,
        [Description("Maximum number of hits to return (1-5000, default 200). The result says when it was truncated.")] int? maxResults = null,
        CancellationToken ct = default) =>
        Run(() => _ops.SearchTextAsync(pattern, regex, caseSensitive, ignoreComments, maxResults, ct));

    [McpServerTool(Name = "task_config")]
    [Description("Task configuration of every application: per task its kind (Cyclic/Event/Status/Freewheeling/External), priority, interval (also normalized to ms), event variable or external event, watchdog, and the POUs it calls, in call order. Only the POUs attached directly to the task are listed, not what they call in turn. Acts on the project configured via the settings page.")]
    public Task<JsonElement> TaskConfigAsync(CancellationToken ct) =>
        Run(() => _ops.GetTaskConfigurationAsync(ct));

    [McpServerTool(Name = "dut_content")]
    [Description("Fields of a structure/union DUT. Acts on the project configured via the settings page.")]
    public Task<JsonElement> DutContentAsync(
        [Description("DUT name.")] string name,
        CancellationToken ct) =>
        Run(() => _ops.GetDutContentAsync(name, ct));

    [McpServerTool(Name = "enum_content")]
    [Description("Values of an ENUM DUT. Acts on the project configured via the settings page.")]
    public Task<JsonElement> EnumContentAsync(
        [Description("ENUM name.")] string name,
        CancellationToken ct) =>
        Run(() => _ops.GetEnumContentAsync(name, ct));

    [McpServerTool(Name = "pou_update")]
    [Description("Replace a POU's implementation (and optionally its declaration).")]
    public Task<JsonElement> PouUpdateAsync(PouUpdateRequest request, CancellationToken ct) =>
        Run(() => _ops.UpdatePouAsync(request, ct));

    [McpServerTool(Name = "pou_create")]
    [Description("Create a new POU (PRG, FB or FUN).")]
    public Task<JsonElement> PouCreateAsync(PouCreateRequest request, CancellationToken ct) =>
        Run(() => _ops.CreatePouAsync(request, ct));

    [McpServerTool(Name = "gvl_create")]
    [Description("Create a new global variable list, optionally with initial variables.")]
    public Task<JsonElement> GvlCreateAsync(GvlCreateRequest request, CancellationToken ct) =>
        Run(() => _ops.CreateGvlAsync(request, ct));

    [McpServerTool(Name = "dut_create")]
    [Description("Create a new STRUCT data unit type with the given fields.")]
    public Task<JsonElement> DutCreateAsync(DutCreateRequest request, CancellationToken ct) =>
        Run(() => _ops.CreateDutAsync(request, ct));

    [McpServerTool(Name = "enum_create")]
    [Description("Create a new ENUM data unit type with the given values.")]
    public Task<JsonElement> EnumCreateAsync(EnumCreateRequest request, CancellationToken ct) =>
        Run(() => _ops.CreateEnumAsync(request, ct));

    [McpServerTool(Name = "compile")]
    [Description("Generate code for every application in the project and return the compiler verdict.")]
    public Task<JsonElement> CompileAsync(CompileRequest request, CancellationToken ct) =>
        Run(() => _ops.CompileAsync(request, ct));

    /// <summary>
    /// Translates <see cref="CodesysOperations"/>' exceptions into <see cref="McpException"/> so
    /// their message reaches the model — any other exception type is reported back only as a
    /// generic error by the SDK, to avoid leaking internal details.
    /// </summary>
    private static async Task<JsonElement> Run(Func<Task<JsonElement>> operation)
    {
        try
        {
            return await operation();
        }
        catch (CodesysValidationException ex)
        {
            throw new McpException(ex.Message);
        }
        catch (ScriptExecutionException ex)
        {
            var message = $"CODESYS script '{ex.ScriptName}' failed: {ex.Message}";
            if (!string.IsNullOrWhiteSpace(ex.PythonTraceback))
                message += $"\n{ex.PythonTraceback}";

            throw new McpException(message);
        }
    }
}
