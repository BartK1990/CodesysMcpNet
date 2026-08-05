using System.Text.Json;
using McpServer.Logging;
using McpServer.Mcp;
using McpServer.Models;
using McpServer.Services;

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

// ---------------------------------------------------------------------------
// Services
// ---------------------------------------------------------------------------
builder.Services.Configure<CodesysOptions>(builder.Configuration.GetSection(CodesysOptions.SectionName));
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
        Version = "v1",
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
    utc = DateTimeOffset.UtcNow,
}))
.WithName("Health")
.WithTags("Health")
.WithSummary("Liveness check.");

// 0. Settings: CODESYS.exe path + selected project, edited from the page at "/" ----------
app.MapGet("/settings", () => Results.Json(settings.GetCurrent()))
    .WithName("GetSettings")
    .WithTags("Settings")
    .WithSummary("Current CODESYS executable and project paths.");

app.MapPost("/settings", async (SettingsRequest request, CancellationToken ct) =>
    {
        try
        {
            RequestValidator.Validate(request);

            if (!File.Exists(request.ExecutablePath))
                throw new CodesysValidationException($"CODESYS executable not found: {request.ExecutablePath}");

            if (!File.Exists(request.ProjectPath))
                throw new CodesysValidationException($"Project file not found: {request.ProjectPath}");

            var saved = await settings.SaveAsync(request.ExecutablePath, request.ProjectPath, request.Profile, ct);
            return Results.Json(saved);
        }
        catch (CodesysValidationException ex)
        {
            return ValidationProblemResult(ex);
        }
    })
    .WithName("SaveSettings")
    .WithTags("Settings")
    .WithSummary("Create or update appsettings.production.json with the CODESYS executable and project paths.");

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

// 1. Project structure -------------------------------------------------------
app.MapGet("/structure", (CancellationToken ct) =>
        RunAsync(ct2 => ops.GetStructureAsync(ct2), ct))
    .WithName("GetStructure")
    .WithTags("Structure")
    .WithSummary("Full project structure: POUs, GVLs, DUTs and ENUMs.");

// 2. Read object contents ----------------------------------------------------
app.MapGet("/pou/content", (string name, CancellationToken ct) =>
        RunAsync(ct2 => ops.GetPouContentAsync(name, ct2), ct))
    .WithName("GetPouContent")
    .WithTags("Read")
    .WithSummary("Full ST source (declaration + implementation) of a POU.");

app.MapGet("/gvl/content", (string name, CancellationToken ct) =>
        RunAsync(ct2 => ops.GetGvlContentAsync(name, ct2), ct))
    .WithName("GetGvlContent")
    .WithTags("Read")
    .WithSummary("Variables of a global variable list, with types and initial values.");

app.MapGet("/dut/content", (string name, CancellationToken ct) =>
        RunAsync(ct2 => ops.GetDutContentAsync(name, ct2), ct))
    .WithName("GetDutContent")
    .WithTags("Read")
    .WithSummary("Fields of a structure/union DUT.");

app.MapGet("/enum/content", (string name, CancellationToken ct) =>
        RunAsync(ct2 => ops.GetEnumContentAsync(name, ct2), ct))
    .WithName("GetEnumContent")
    .WithTags("Read")
    .WithSummary("Values of an ENUM DUT.");

// 3. Update POU code ---------------------------------------------------------
app.MapPost("/pou/update", (PouUpdateRequest request, CancellationToken ct) =>
        RunAsync(ct2 => ops.UpdatePouAsync(request, ct2), ct))
    .WithName("UpdatePou")
    .WithTags("Update")
    .WithSummary("Replace a POU's implementation (and optionally its declaration).");

// 4. Create new objects ------------------------------------------------------
app.MapPost("/pou/create", (PouCreateRequest request, CancellationToken ct) =>
        RunAsync(ct2 => ops.CreatePouAsync(request, ct2), ct))
    .WithName("CreatePou")
    .WithTags("Create")
    .WithSummary("Create a new POU (PRG, FB or FUN).");

app.MapPost("/gvl/create", (GvlCreateRequest request, CancellationToken ct) =>
        RunAsync(ct2 => ops.CreateGvlAsync(request, ct2), ct))
    .WithName("CreateGvl")
    .WithTags("Create")
    .WithSummary("Create a new global variable list, optionally with initial variables.");

app.MapPost("/dut/create", (DutCreateRequest request, CancellationToken ct) =>
        RunAsync(ct2 => ops.CreateDutAsync(request, ct2), ct))
    .WithName("CreateDut")
    .WithTags("Create")
    .WithSummary("Create a new STRUCT data unit type with the given fields.");

app.MapPost("/enum/create", (EnumCreateRequest request, CancellationToken ct) =>
        RunAsync(ct2 => ops.CreateEnumAsync(request, ct2), ct))
    .WithName("CreateEnum")
    .WithTags("Create")
    .WithSummary("Create a new ENUM data unit type with the given values.");

// 5. Compile -----------------------------------------------------------------
app.MapPost("/compile", (CompileRequest request, CancellationToken ct) =>
        RunAsync(ct2 => ops.CompileAsync(request, ct2), ct))
    .WithName("Compile")
    .WithTags("Build")
    .WithSummary("Generate code for every application in the project and return the compiler verdict.");

log.LogInformation(
    "CODESYS MCP server starting. REST on this Kestrel instance, MCP tools at /mcp. " +
    "Scripts are executed serially against a single CODESYS instance.");

app.Run();
