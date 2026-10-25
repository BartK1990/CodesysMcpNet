using System.Reflection;
using System.Text.Json;
using CodesysMcpServer.Web.Logging;
using CodesysMcpServer.Web.Mcp;
using CodesysMcpServer.Web.Models;
using CodesysMcpServer.Web.Services;

// Launched by a stdio-only MCP client: forward to the running HTTP server instead of hosting.
if (StdioProxy.TryGetEndpoint(args, out var proxyEndpoint))
    return await StdioProxy.RunAsync(proxyEndpoint);

var builder = WebApplication.CreateBuilder(args);

builder.Host.UseWindowsService();

// Machine-local overrides (CODESYS.exe path, selected project, ...) written by the settings
// page at runtime. Not part of source control or the publish output — see McpServer.csproj
// and .gitignore. Read from next to the binary regardless of the process's working directory,
// and reloaded on change so a save takes effect without restarting the server.
var productionSettingsPath = Path.Combine(AppContext.BaseDirectory, "appsettings.production.json");
builder.Configuration.AddJsonFile(productionSettingsPath, optional: true, reloadOnChange: true);

// ---------------------------------------------------------------------------
// Logging: console + rolling files under ./Logs
// ---------------------------------------------------------------------------
builder.Logging.ClearProviders();
builder.Logging.AddConfiguration(builder.Configuration.GetSection("Logging"));
builder.Logging.AddSimpleConsole(options =>
{
    options.SingleLine = true;
    options.TimestampFormat = "HH:mm:ss.fff ";
});
builder.Logging.AddDebug();
builder.Logging.AddFile(builder.Configuration.GetSection("FileLogging"));

// Release version, set by <Version> in CodesysMcpServer.Web.csproj.
var appVersion = typeof(Program).Assembly
    .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
    ?? typeof(Program).Assembly.GetName().Version?.ToString(3)
    ?? "0.0.0";

// ---------------------------------------------------------------------------
// Services
// ---------------------------------------------------------------------------
builder.Services.Configure<CodesysOptions>(builder.Configuration.GetSection(CodesysOptions.SectionName));
builder.Services.AddSingleton<ProjectCatalog>();
builder.Services.AddSingleton<CodesysSessionPool>();
builder.Services.AddSingleton<PythonRunner>();
builder.Services.AddSingleton<CodesysOperations>();
builder.Services.AddSingleton<AppSettingsWriter>();
builder.Services.AddSingleton<FileBrowserService>();
builder.Services.AddSingleton<CodesysProfileService>();
builder.Services.AddProblemDetails();

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(options =>
{
    options.SwaggerDoc("v1", new Microsoft.OpenApi.Models.OpenApiInfo
    {
        Title = "CODESYS MCP Server",
        Version = appVersion,
        Description = "Local HTTP API that drives a CODESYS project via the official Scripting Engine.",
    });
});

builder.Services.ConfigureHttpJsonOptions(options =>
{
    options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.CamelCase;
    options.SerializerOptions.PropertyNameCaseInsensitive = true;
    options.SerializerOptions.WriteIndented = true;
});

// Same CodesysOperations the REST endpoints below use, exposed as MCP tools over
// Streamable HTTP at /mcp. See Mcp/CodesysTools.cs.
builder.Services
    .AddMcpServer()
    .WithHttpTransport()
    .WithTools<CodesysTools>();

var app = builder.Build();

app.UseExceptionHandler();
app.UseStatusCodePages();

// Settings page (wwwroot/index.html) — serves it at "/" and its static assets.
app.UseDefaultFiles();
app.UseStaticFiles();

app.UseSwagger();
app.UseSwaggerUI(options =>
{
    options.SwaggerEndpoint("/swagger/v1/swagger.json", "CODESYS MCP Server v1");
    options.RoutePrefix = "swagger";
});

app.MapMcp("/mcp");

var log = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("McpServer");
var ops = app.Services.GetRequiredService<CodesysOperations>();
var settings = app.Services.GetRequiredService<AppSettingsWriter>();
var fileBrowser = app.Services.GetRequiredService<FileBrowserService>();
var profiles = app.Services.GetRequiredService<CodesysProfileService>();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Runs a CodesysOperations call and maps its exceptions onto ProblemDetails responses.
// CodesysOperations (Services/CodesysOperations.cs) is the shared implementation behind both
// this REST API and the MCP tools in Mcp/CodesysTools.cs; this helper only adds the
// REST-specific error shape on top.
async Task<IResult> RunAsync(Func<CancellationToken, Task<JsonElement>> operation, CancellationToken ct)
{
    try
    {
        var data = await operation(ct);
        return Results.Json(data, statusCode: StatusCodes.Status200OK);
    }
    catch (CodesysValidationException ex)
    {
        return ValidationProblemResult(ex);
    }
    catch (ScriptExecutionException ex)
    {
        log.LogError(ex, "Script {Script} failed: {Message}", ex.ScriptName, ex.Message);

        return Results.Problem(
            title: $"CODESYS script '{ex.ScriptName}' failed",
            detail: ex.Message,
            statusCode: StatusCodes.Status502BadGateway,
            extensions: new Dictionary<string, object?>
            {
                ["script"] = ex.ScriptName,
                ["exitCode"] = ex.ExitCode,
                ["pythonTraceback"] = ex.PythonTraceback,
                ["stderr"] = ex.StandardError,
            });
    }
    catch (OperationCanceledException) when (ct.IsCancellationRequested)
    {
        // 499: client closed the request while CODESYS was still working.
        return Results.StatusCode(499);
    }
}

static IResult Problem(string detail, int statusCode) =>
    Results.Problem(detail: detail, statusCode: statusCode);

static IResult ValidationProblemResult(CodesysValidationException ex) =>
    ex.Errors is not null
        ? Results.ValidationProblem(ex.Errors)
        : Problem(ex.Message, StatusCodes.Status400BadRequest);

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

app.MapGet("/health", () => Results.Ok(new
{
    status = "ok",
    version = appVersion,
    utc = DateTimeOffset.UtcNow,
}))
.WithName("Health")
.WithTags("Health")
.WithSummary("Liveness check.");

app.MapGet("/version", () => Results.Json(new { version = appVersion }))
.WithName("Version")
.WithTags("Health")
.WithSummary("Release version of the running server.");

// 0. Settings: CODESYS.exe path + selected project, edited from the page at "/" ----------
app.MapGet("/settings", () => Results.Json(settings.GetCurrent()))
    .WithName("GetSettings")
    .WithTags("Settings")
    .WithSummary("Current CODESYS executable, project paths and project limit.");

app.MapPost("/settings", async (SettingsRequest request, CancellationToken ct) =>
    {
        try
        {
            RequestValidator.Validate(request);

            var saved = await settings.SaveAsync(request, ct);
            return Results.Json(saved);
        }
        catch (CodesysValidationException ex)
        {
            return ValidationProblemResult(ex);
        }
    })
    .WithName("SaveSettings")
    .WithTags("Settings")
    .WithSummary("Create or update appsettings.production.json with the CODESYS executable, project paths and project limit.");

app.MapGet("/files", (string? path, string? filter) =>
    {
        try
        {
            return Results.Json(fileBrowser.List(path, filter));
        }
        catch (CodesysValidationException ex)
        {
            return ValidationProblemResult(ex);
        }
    })
    .WithName("BrowseFiles")
    .WithTags("Settings")
    .WithSummary("List drives (path omitted) or a directory's folders/files, for the settings page's path picker.");

app.MapGet("/profiles", (string? executablePath) =>
    {
        try
        {
            var path = string.IsNullOrWhiteSpace(executablePath)
                ? settings.GetCurrent().ExecutablePath
                : executablePath;

            return Results.Json(profiles.List(path));
        }
        catch (CodesysValidationException ex)
        {
            return ValidationProblemResult(ex);
        }
    })
    .WithName("ListProfiles")
    .WithTags("Settings")
    .WithSummary("CODESYS version profiles installed alongside the given (or currently saved) CODESYS.exe.");

// 0b. Projects and their persistent CODESYS sessions ------------------------------
var sessions = app.Services.GetRequiredService<CodesysSessionPool>();
var projects = app.Services.GetRequiredService<ProjectCatalog>();

app.MapGet("/projects", () => Results.Json(ops.ListProjects()))
    .WithName("ListProjects")
    .WithTags("Projects")
    .WithSummary("Configured projects (default first) with the state of their CODESYS session.");

app.MapGet("/sessions", () => Results.Json(projects.List().Select(sessions.GetStatus)))
    .WithName("ListSessions")
    .WithTags("Session")
    .WithSummary("Persistent CODESYS session status of every configured project.");

app.MapGet("/session", (string? project) =>
    {
        try
        {
            return Results.Json(sessions.GetStatus(projects.Resolve(project)));
        }
        catch (CodesysValidationException ex)
        {
            return ValidationProblemResult(ex);
        }
    })
    .WithName("GetSession")
    .WithTags("Session")
    .WithSummary("Whether the persistent CODESYS instance of a project (default: the default project) is running, and since when.");

app.MapPost("/session/start", (string? project, CancellationToken ct) =>
        RunAsync(async ct2 =>
        {
            try
            {
                return await ops.OpenProjectAsync(project, ct2);
            }
            catch (ScriptExecutionException ex)
            {
                // Opening the project is the point of a start, so its failure is session state.
                sessions.ReportFailure(projects.Resolve(project).Path, $"Start failed: {ex.Message}");
                throw;
            }
        }, ct))
    .WithName("StartSession")
    .WithTags("Session")
    .WithSummary("Start CODESYS (if needed) and open a configured project (default: the default project), so later calls are fast.");

app.MapPost("/session/stop", async (string? project, CancellationToken ct) =>
    {
        CodesysProject resolved;
        try
        {
            resolved = projects.Resolve(project);
        }
        catch (CodesysValidationException ex)
        {
            return ValidationProblemResult(ex);
        }

        await sessions.StopAsync(resolved.Path, ct);
        return Results.Json(sessions.GetStatus(resolved));
    })
    .WithName("StopSession")
    .WithTags("Session")
    .WithSummary("Close a project (default: the default project) and stop its CODESYS instance, releasing the project file.");

// 1. Project structure -------------------------------------------------------
app.MapGet("/structure", (string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.GetStructureAsync(project, ct2), ct))
    .WithName("GetStructure")
    .WithTags("Structure")
    .WithSummary("Full project structure: POUs, GVLs, DUTs and ENUMs.");

// 2. Read object contents ----------------------------------------------------
app.MapGet("/pou/content", (string name, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.GetPouContentAsync(name, project, ct2), ct))
    .WithName("GetPouContent")
    .WithTags("Read")
    .WithSummary("Full ST source (declaration + implementation) of a POU.");

app.MapGet("/gvl/content", (string name, string? filter, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.GetGvlContentAsync(name, filter, project, ct2), ct))
    .WithName("GetGvlContent")
    .WithTags("Read")
    .WithSummary("Variables of a global variable list, with types and initial values; optional name filter.");

app.MapGet("/dut/content", (string name, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.GetDutContentAsync(name, project, ct2), ct))
    .WithName("GetDutContent")
    .WithTags("Read")
    .WithSummary("Fields of a structure/union DUT.");

app.MapGet("/enum/content", (string name, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.GetEnumContentAsync(name, project, ct2), ct))
    .WithName("GetEnumContent")
    .WithTags("Read")
    .WithSummary("Values of an ENUM DUT.");

app.MapGet("/search", (string pattern, bool? regex, bool? caseSensitive, bool? ignoreComments, int? maxResults, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.SearchTextAsync(
            pattern, regex ?? false, caseSensitive ?? false, ignoreComments ?? false, maxResults, project, ct2), ct))
    .WithName("SearchText")
    .WithTags("Read")
    .WithSummary("Search declarations and implementations of all POUs, members, GVLs, DUTs and ENUMs.");

app.MapGet("/tasks", (string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.GetTaskConfigurationAsync(project, ct2), ct))
    .WithName("GetTaskConfiguration")
    .WithTags("Read")
    .WithSummary("Tasks with kind, priority, interval, event trigger, watchdog and called POUs.");

// 3. Update POU code ---------------------------------------------------------
app.MapPost("/pou/update", (PouUpdateRequest request, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.UpdatePouAsync(request, project, ct2), ct))
    .WithName("UpdatePou")
    .WithTags("Update")
    .WithSummary("Replace a POU's implementation (and optionally its declaration).");

// 4. Create new objects ------------------------------------------------------
app.MapPost("/pou/create", (PouCreateRequest request, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.CreatePouAsync(request, project, ct2), ct))
    .WithName("CreatePou")
    .WithTags("Create")
    .WithSummary("Create a new POU (PRG, FB or FUN).");

app.MapPost("/gvl/create", (GvlCreateRequest request, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.CreateGvlAsync(request, project, ct2), ct))
    .WithName("CreateGvl")
    .WithTags("Create")
    .WithSummary("Create a new global variable list, optionally with initial variables.");

app.MapPost("/dut/create", (DutCreateRequest request, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.CreateDutAsync(request, project, ct2), ct))
    .WithName("CreateDut")
    .WithTags("Create")
    .WithSummary("Create a new STRUCT data unit type with the given fields.");

app.MapPost("/enum/create", (EnumCreateRequest request, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.CreateEnumAsync(request, project, ct2), ct))
    .WithName("CreateEnum")
    .WithTags("Create")
    .WithSummary("Create a new ENUM data unit type with the given values.");

// 5. Compile -----------------------------------------------------------------
app.MapPost("/compile", (CompileRequest request, string? project, CancellationToken ct) =>
        RunAsync(ct2 => ops.CompileAsync(request, project, ct2), ct))
    .WithName("Compile")
    .WithTags("Build")
    .WithSummary("Generate code for every application in the project and return the compiler verdict.");

log.LogInformation(
    "CODESYS MCP server {Version} starting. REST on this Kestrel instance, MCP tools at /mcp. " +
    "Scripts for one project run serially against its CODESYS instance.", appVersion);

// Pay CODESYS start-up and project load in the background now rather than on the first call —
// for every configured project, each in its own session when more than one is allowed.
app.Lifetime.ApplicationStarted.Register(() =>
{
    var options = app.Services.GetRequiredService<Microsoft.Extensions.Options.IOptionsMonitor<CodesysOptions>>().CurrentValue;
    if (!sessions.Enabled || !options.StartSessionOnStartup)
        return;

    foreach (var project in projects.List())
    {
        _ = Task.Run(async () =>
        {
            try
            {
                log.LogInformation("Warming up the CODESYS session with {Project}", project.Path);
                await ops.OpenProjectAsync(project.Path, app.Lifetime.ApplicationStopping);
                log.LogInformation("CODESYS session for {Project} is warm", project.Name);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                log.LogWarning(ex, "Warming up the CODESYS session for {Project} failed; it will be retried on the first request", project.Name);
                sessions.ReportFailure(project.Path, $"Warm-up failed: {ex.Message}");
            }
            catch (OperationCanceledException)
            {
            }
        });
    }
});

app.Run();
return 0;
