using System.ComponentModel.DataAnnotations;
using System.Text.Json;
using McpServer.Logging;
using McpServer.Models;
using McpServer.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Host.UseWindowsService();
builder.Configuration.AddJsonFile("appsettings.production.json", optional: true, reloadOnChange: false);

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

var app = builder.Build();

app.UseExceptionHandler();
app.UseStatusCodePages();

app.UseSwagger();
app.UseSwaggerUI(options =>
{
    options.SwaggerEndpoint("/swagger/v1/swagger.json", "CODESYS MCP Server v1");
    options.RoutePrefix = "swagger";
});

var log = app.Services.GetRequiredService<ILoggerFactory>().CreateLogger("McpServer");
var runner = app.Services.GetRequiredService<PythonRunner>();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Runs a script and maps failures onto ProblemDetails responses.
async Task<IResult> RunScriptAsync(string script, object payload, string? projectPath, CancellationToken ct)
{
    if (string.IsNullOrWhiteSpace(projectPath))
        return Problem("projectPath is required.", StatusCodes.Status400BadRequest);

    if (!File.Exists(projectPath))
        return Problem($"Project file not found: {projectPath}", StatusCodes.Status400BadRequest);

    try
    {
        var result = await runner.ExecuteAsync(script, payload, ct);
        return Results.Json(result.Data, statusCode: StatusCodes.Status200OK);
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

// DataAnnotations validation for POST bodies.
static bool TryValidate(object model, out IResult? failure)
{
    var context = new ValidationContext(model);
    var results = new List<ValidationResult>();

    if (Validator.TryValidateObject(model, context, results, validateAllProperties: true))
    {
        failure = null;
        return true;
    }

    var errors = results
        .SelectMany(r => r.MemberNames.DefaultIfEmpty(string.Empty), (r, member) => (member, r.ErrorMessage))
        .GroupBy(x => string.IsNullOrEmpty(x.member) ? "request" : x.member)
        .ToDictionary(g => g.Key, g => g.Select(x => x.ErrorMessage ?? "Invalid value").ToArray());

    failure = Results.ValidationProblem(errors);
    return false;
}

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

// 1. Project structure -------------------------------------------------------
app.MapGet("/structure", (string projectPath, CancellationToken ct) =>
        RunScriptAsync("structure.py", new { projectPath }, projectPath, ct))
    .WithName("GetStructure")
    .WithTags("Structure")
    .WithSummary("Full project structure: POUs, GVLs, DUTs and ENUMs.");

// 2. Read object contents ----------------------------------------------------
app.MapGet("/pou/content", (string projectPath, string name, CancellationToken ct) =>
        RunScriptAsync("pou_read.py", new { projectPath, name }, projectPath, ct))
    .WithName("GetPouContent")
    .WithTags("Read")
    .WithSummary("Full ST source (declaration + implementation) of a POU.");

app.MapGet("/gvl/content", (string projectPath, string name, CancellationToken ct) =>
        RunScriptAsync("gvl_read.py", new { projectPath, name }, projectPath, ct))
    .WithName("GetGvlContent")
    .WithTags("Read")
    .WithSummary("Variables of a global variable list, with types and initial values.");

app.MapGet("/dut/content", (string projectPath, string name, CancellationToken ct) =>
        RunScriptAsync("dut_read.py", new { projectPath, name }, projectPath, ct))
    .WithName("GetDutContent")
    .WithTags("Read")
    .WithSummary("Fields of a structure/union DUT.");

app.MapGet("/enum/content", (string projectPath, string name, CancellationToken ct) =>
        RunScriptAsync("enum_read.py", new { projectPath, name }, projectPath, ct))
    .WithName("GetEnumContent")
    .WithTags("Read")
    .WithSummary("Values of an ENUM DUT.");

// 3. Update POU code ---------------------------------------------------------
app.MapPost("/pou/update", async (PouUpdateRequest request, CancellationToken ct) =>
    {
        if (!TryValidate(request, out var failure))
            return failure!;

        return await RunScriptAsync(
            "pou_update.py",
            new
            {
                projectPath = request.ProjectPath,
                name = request.PouName,
                implementation = request.NewCode,
                declaration = request.NewDeclaration,
            },
            request.ProjectPath,
            ct);
    })
    .WithName("UpdatePou")
    .WithTags("Update")
    .WithSummary("Replace a POU's implementation (and optionally its declaration).");

// 4. Create new objects ------------------------------------------------------
app.MapPost("/pou/create", async (PouCreateRequest request, CancellationToken ct) =>
    {
        if (!TryValidate(request, out var failure))
            return failure!;

        return await RunScriptAsync(
            "pou_create.py",
            new
            {
                projectPath = request.ProjectPath,
                name = request.Name,
                type = request.Type,
                language = request.Language,
                returnType = request.ReturnType,
                parentPath = request.ParentPath,
                implementation = request.Implementation,
                declaration = request.Declaration,
            },
            request.ProjectPath,
            ct);
    })
    .WithName("CreatePou")
    .WithTags("Create")
    .WithSummary("Create a new POU (PRG, FB or FUN).");

app.MapPost("/gvl/create", async (GvlCreateRequest request, CancellationToken ct) =>
    {
        if (!TryValidate(request, out var failure))
            return failure!;

        return await RunScriptAsync(
            "gvl_create.py",
            new
            {
                projectPath = request.ProjectPath,
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
            request.ProjectPath,
            ct);
    })
    .WithName("CreateGvl")
    .WithTags("Create")
    .WithSummary("Create a new global variable list, optionally with initial variables.");

app.MapPost("/dut/create", async (DutCreateRequest request, CancellationToken ct) =>
    {
        if (!TryValidate(request, out var failure))
            return failure!;

        return await RunScriptAsync(
            "dut_create.py",
            new
            {
                projectPath = request.ProjectPath,
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
            request.ProjectPath,
            ct);
    })
    .WithName("CreateDut")
    .WithTags("Create")
    .WithSummary("Create a new STRUCT data unit type with the given fields.");

app.MapPost("/enum/create", async (EnumCreateRequest request, CancellationToken ct) =>
    {
        if (!TryValidate(request, out var failure))
            return failure!;

        return await RunScriptAsync(
            "enum_create.py",
            new
            {
                projectPath = request.ProjectPath,
                name = request.Name,
                values = request.Values,
                baseType = request.BaseType,
                parentPath = request.ParentPath,
            },
            request.ProjectPath,
            ct);
    })
    .WithName("CreateEnum")
    .WithTags("Create")
    .WithSummary("Create a new ENUM data unit type with the given values.");

// 5. Compile -----------------------------------------------------------------
app.MapPost("/compile", async (CompileRequest request, CancellationToken ct) =>
    {
        if (!TryValidate(request, out var failure))
            return failure!;

        return await RunScriptAsync(
            "compile.py",
            new
            {
                projectPath = request.ProjectPath,
                clean = request.Clean,
                save = request.SaveAfterCompile,
            },
            request.ProjectPath,
            ct);
    })
    .WithName("Compile")
    .WithTags("Build")
    .WithSummary("Generate code for every application in the project and return the compiler verdict.");

log.LogInformation("CODESYS MCP server starting. Scripts are executed serially against a single CODESYS instance.");

app.Run();
