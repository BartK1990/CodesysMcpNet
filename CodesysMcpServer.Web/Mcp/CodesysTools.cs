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
    private const string ProjectDescription =
        "Optional: which configured project to act on, by name (file name without .project/.library) or full path. " +
        "Omit for the default project. The projects tool lists the configured ones; a configured .library " +
        "(kind library) is edited like a project.";

    private const string LibraryDescription =
        "Optional: read from a library the project references instead of the project itself - its title, " +
        "placeholder or namespace as the libraries tool lists them (e.g. \"Standard\"). Only libraries " +
        "available as source (.library) can be read.";

    private readonly CodesysOperations _ops;

    public CodesysTools(CodesysOperations ops)
    {
        _ops = ops;
    }

    [McpServerTool(Name = "projects")]
    [Description("Projects this server is configured for: name, path, whether it is the default one (used when a tool's project argument is omitted), kind (project for a .project file, library for a source .library opened and edited like a project), whether the file exists, the state of its CODESYS session, and passwordNeeded when the project is password protected and its password has to be entered on the settings page. Pass a name from this list as the project argument of the other tools.")]
    public IReadOnlyList<ProjectSummary> Projects() => _ops.ListProjects();

    [McpServerTool(Name = "libraries")]
    [Description("Libraries the project references (project-level and per application): name, namespace, placeholder, requested and effective resolution (title, version, company), and source - the file the library can be read from (a .library in a library repository or next to the project; kind source or compiled), or null when none was found. Pass a title from this list as the library argument of structure, pou_content, gvl_content, dut_content, enum_content and search_text to read the library's code. Acts on the default project unless project names another configured one.")]
    public Task<JsonElement> LibrariesAsync(
        [Description(ProjectDescription)] string? project = null,
        CancellationToken ct = default) =>
        Run(() => _ops.ListLibrariesAsync(project, name: null, ct));

    [McpServerTool(Name = "structure")]
    [Description("Full project structure: POUs, GVLs, DUTs and ENUMs - or, with library, those of a referenced library. kind is project or library; for a configured .library, libraryInfo carries its title, version, company and default namespace. Acts on the default project unless project names another configured one.")]
    public Task<JsonElement> StructureAsync(
        [Description(ProjectDescription)] string? project = null,
        [Description(LibraryDescription)] string? library = null,
        CancellationToken ct = default) =>
        Run(() => _ops.GetStructureAsync(project, library, ct));

    [McpServerTool(Name = "pou_content")]
    [Description("Full ST source (declaration + implementation) of a POU, or of one of its methods, actions, properties or transitions - in the project or, with library, in a referenced library. Acts on the default project unless project names another configured one.")]
    public Task<JsonElement> PouContentAsync(
        [Description("POU name or path. Use \"Parent.Member\" for a method/action/property/transition (e.g. \"FB_Motor.Reset\"), and \"Parent.Property.Get\" for a property accessor.")] string name,
        [Description(ProjectDescription)] string? project = null,
        [Description(LibraryDescription)] string? library = null,
        CancellationToken ct = default) =>
        Run(() => _ops.GetPouContentAsync(name, project, library, ct));

    [McpServerTool(Name = "gvl_content")]
    [Description("Variables of a global variable list, with types and initial values. Pass a filter for large lists: the result then holds only matching variables and omits the full declaration text. With library, reads a GVL of a referenced library. Acts on the default project unless project names another configured one.")]
    public Task<JsonElement> GvlContentAsync(
        [Description("GVL name.")] string name,
        [Description("Optional case-insensitive variable-name filter: a wildcard pattern (\"*Fault*\", \"x?Run\") or, without * or ?, a substring.")] string? filter = null,
        [Description(ProjectDescription)] string? project = null,
        [Description(LibraryDescription)] string? library = null,
        CancellationToken ct = default) =>
        Run(() => _ops.GetGvlContentAsync(name, filter, project, library, ct));

    [McpServerTool(Name = "search_text")]
    [Description("Search the declarations and implementations of all POUs (incl. methods, actions, properties, transitions), GVLs, DUTs and ENUMs - of the project or, with library, of a referenced library. Returns one hit per matching line: POU, member, section, 1-based line number and the line text. Use a regex such as \"\\bxFault\\s*:=\" to find writes to a variable. Graphical (FBD/LD/CFC/SFC) bodies are not searchable and are listed in implementationNotTextual. Acts on the default project unless project names another configured one.")]
    public Task<JsonElement> SearchTextAsync(
        [Description("Text to find. Plain text unless regex is true.")] string pattern,
        [Description("Treat pattern as a Python regular expression.")] bool regex = false,
        [Description("Match case exactly (default: case-insensitive).")] bool caseSensitive = false,
        [Description("Skip matches inside comments and pragmas.")] bool ignoreComments = false,
        [Description("Maximum number of hits to return (1-5000, default 200). The result says when it was truncated.")] int? maxResults = null,
        [Description(ProjectDescription)] string? project = null,
        [Description(LibraryDescription)] string? library = null,
        CancellationToken ct = default) =>
        Run(() => _ops.SearchTextAsync(pattern, regex, caseSensitive, ignoreComments, maxResults, project, library, ct));

    [McpServerTool(Name = "task_config")]
    [Description("Task configuration of every application: per task its kind (Cyclic/Event/Status/Freewheeling/External), priority, interval (also normalized to ms), event variable or external event, watchdog, and the POUs it calls, in call order. Only the POUs attached directly to the task are listed, not what they call in turn. Acts on the default project unless project names another configured one.")]
    public Task<JsonElement> TaskConfigAsync(
        [Description(ProjectDescription)] string? project = null,
        CancellationToken ct = default) =>
        Run(() => _ops.GetTaskConfigurationAsync(project, ct));

    [McpServerTool(Name = "recipes")]
    [Description("Recipe Manager contents. Without definition: every Recipe Manager (its application and settings: storage type/path/extension/separator/columns, load and write mode, recipe management in PLC, ...) with a summary of each recipe definition (variable count, recipe names). With definition: that definition's variables - variable expression, type, display name, comment, min/max - each with its value in every recipe (or only in recipe), one page at a time; use filter and offset for large definitions. Acts on the default project unless project names another configured one.")]
    public Task<JsonElement> RecipesAsync(
        [Description("Optional recipe definition name or path. Omit for the overview of all Recipe Managers.")] string? definition = null,
        [Description("Optional variable filter (case-insensitive) on the variable expression or display name: a wildcard pattern (\"*Speed*\") or, without * or ?, a substring.")] string? filter = null,
        [Description("Optional: return the values of this recipe only.")] string? recipe = null,
        [Description("Index of the first matching variable to return (default 0). Pass the nextOffset of the previous result to page on.")] int? offset = null,
        [Description("Maximum number of variables to return (1-5000, default 500). The result says when it was truncated.")] int? maxVariables = null,
        [Description("Optional application (name or path) whose Recipe Manager holds the definition. Needed only when several applications have one with the same definition name.")] string? application = null,
        [Description(ProjectDescription)] string? project = null,
        CancellationToken ct = default) =>
        Run(() => _ops.GetRecipesAsync(definition, application, filter, recipe, offset, maxVariables, project, ct));

    [McpServerTool(Name = "recipe_update")]
    [Description("Change a recipe definition of a Recipe Manager, then save the project: add or update variables (display name, comment, min/max), remove variables, create recipes or set their values, remove recipes - in one call. With create, the definition is created first when missing (the application must already have a Recipe Manager). Every name is checked before anything changes. Values outside a variable's min/max and variables whose type does not resolve are reported as warnings, not rejected. Acts on the default project unless project names another configured one.")]
    public Task<JsonElement> RecipeUpdateAsync(
        RecipeUpdateRequest request,
        [Description(ProjectDescription)] string? project = null,
        CancellationToken ct = default) =>
        Run(() => _ops.UpdateRecipesAsync(request, project, ct));

    [McpServerTool(Name = "dut_content")]
    [Description("Fields of a structure/union DUT - in the project or, with library, in a referenced library. Acts on the default project unless project names another configured one.")]
    public Task<JsonElement> DutContentAsync(
        [Description("DUT name.")] string name,
        [Description(ProjectDescription)] string? project = null,
        [Description(LibraryDescription)] string? library = null,
        CancellationToken ct = default) =>
        Run(() => _ops.GetDutContentAsync(name, project, library, ct));

    [McpServerTool(Name = "enum_content")]
    [Description("Values of an ENUM DUT - in the project or, with library, in a referenced library. Acts on the default project unless project names another configured one.")]
    public Task<JsonElement> EnumContentAsync(
        [Description("ENUM name.")] string name,
        [Description(ProjectDescription)] string? project = null,
        [Description(LibraryDescription)] string? library = null,
        CancellationToken ct = default) =>
        Run(() => _ops.GetEnumContentAsync(name, project, library, ct));

    [McpServerTool(Name = "pou_update")]
    [Description("Replace a POU's implementation (and optionally its declaration).")]
    public Task<JsonElement> PouUpdateAsync(
        PouUpdateRequest request,
        [Description(ProjectDescription)] string? project = null,
        CancellationToken ct = default) =>
        Run(() => _ops.UpdatePouAsync(request, project, ct));

    [McpServerTool(Name = "pou_create")]
    [Description("Create a new POU (PRG, FB or FUN).")]
    public Task<JsonElement> PouCreateAsync(
        PouCreateRequest request,
        [Description(ProjectDescription)] string? project = null,
        CancellationToken ct = default) =>
        Run(() => _ops.CreatePouAsync(request, project, ct));

    [McpServerTool(Name = "gvl_create")]
    [Description("Create a new global variable list, optionally with initial variables.")]
    public Task<JsonElement> GvlCreateAsync(
        GvlCreateRequest request,
        [Description(ProjectDescription)] string? project = null,
        CancellationToken ct = default) =>
        Run(() => _ops.CreateGvlAsync(request, project, ct));

    [McpServerTool(Name = "dut_create")]
    [Description("Create a new STRUCT data unit type with the given fields.")]
    public Task<JsonElement> DutCreateAsync(
        DutCreateRequest request,
        [Description(ProjectDescription)] string? project = null,
        CancellationToken ct = default) =>
        Run(() => _ops.CreateDutAsync(request, project, ct));

    [McpServerTool(Name = "enum_create")]
    [Description("Create a new ENUM data unit type with the given values.")]
    public Task<JsonElement> EnumCreateAsync(
        EnumCreateRequest request,
        [Description(ProjectDescription)] string? project = null,
        CancellationToken ct = default) =>
        Run(() => _ops.CreateEnumAsync(request, project, ct));

    [McpServerTool(Name = "compile")]
    [Description("Generate code for every application in the project and return the compiler verdict. A library (kind library) has no application, so its objects are checked instead (Build > Check all pool objects).")]
    public Task<JsonElement> CompileAsync(
        CompileRequest request,
        [Description(ProjectDescription)] string? project = null,
        CancellationToken ct = default) =>
        Run(() => _ops.CompileAsync(request, project, ct));

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
        catch (ProjectPasswordException ex)
        {
            // Only the user can supply it: point them (via the model) at the settings page.
            throw new McpException(ex.Message + " Ask the user to enter it there; do not ask them for the password in chat.");
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
