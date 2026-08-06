using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Options;

namespace CodesysMcpServer.Web.Services;

/// <summary>Successful result of a script run.</summary>
/// <param name="Data">The <c>data</c> member of the script's JSON envelope.</param>
/// <param name="ExitCode">Process exit code.</param>
/// <param name="Duration">Wall-clock duration of the process.</param>
public sealed record ScriptResult(JsonElement Data, int ExitCode, TimeSpan Duration);

/// <summary>
/// Executes the CODESYS Python scripts and marshals their JSON result back to the API layer.
///
/// Hand-off protocol
/// -----------------
/// The runner writes the request payload to a JSON file and passes that single path to the
/// script (as <c>--scriptargs</c> under CODESYS, or as <c>argv[1]</c> under a plain interpreter).
/// The script writes its envelope both to a result file and to stdout between sentinel markers;
/// the file is preferred because CODESYS itself writes plenty of unrelated banner text to stdout.
///
/// Every line the script prints is logged as it arrives, so Python progress shows up live in the
/// console and in the log files.
/// </summary>
public sealed class PythonRunner
{
    internal const string ResultBeginMarker = "<<<MCP_RESULT_BEGIN>>>";
    internal const string ResultEndMarker = "<<<MCP_RESULT_END>>>";

    private static readonly UTF8Encoding Utf8NoBom = new(encoderShouldEmitUTF8Identifier: false);

    private static readonly JsonSerializerOptions PayloadJsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
    };

    // CODESYS is effectively a single-instance desktop application: never run two scripts at once.
    private static readonly SemaphoreSlim Gate = new(1, 1);

    private readonly IOptionsMonitor<CodesysOptions> _optionsMonitor;
    private readonly ILogger<PythonRunner> _logger;
    private readonly string _scriptsDirectory;

    // Read fresh on every use (not just once, up front) so a setting saved through the
    // settings page — CODESYS.exe path, project path, profile, ... — takes effect on the
    // next script run without restarting the server.
    private CodesysOptions Options => _optionsMonitor.CurrentValue;

    public PythonRunner(IOptionsMonitor<CodesysOptions> options, ILogger<PythonRunner> logger)
    {
        _optionsMonitor = options;
        _logger = logger;
        _scriptsDirectory = Path.IsPathRooted(Options.ScriptsDirectory)
            ? Options.ScriptsDirectory
            : Path.Combine(AppContext.BaseDirectory, Options.ScriptsDirectory);
    }

    /// <summary>Runs a script with a strongly typed payload object (serialized to the request file).</summary>
    public Task<ScriptResult> ExecuteAsync(string scriptName, object payload, CancellationToken ct = default) =>
        ExecuteCoreAsync(scriptName, payload, extraArguments: null, ct);

    /// <summary>
    /// Runs a script with a plain argument list. The arguments are handed to the script as
    /// <c>argv[2..]</c> and are also available in the request file under <c>args</c>.
    /// </summary>
    public Task<ScriptResult> ExecuteAsync(
        string scriptName,
        IReadOnlyList<string> args,
        CancellationToken ct = default) =>
        ExecuteCoreAsync(scriptName, new { args }, args, ct);

    private async Task<ScriptResult> ExecuteCoreAsync(
        string scriptName,
        object payload,
        IReadOnlyList<string>? extraArguments,
        CancellationToken ct)
    {
        var scriptPath = ResolveScript(scriptName);
        var workDirectory = EnsureWorkDirectory();

        var correlation = Guid.NewGuid().ToString("N");
        var requestPath = Path.Combine(workDirectory, $"{correlation}.req.json");
        var resultPath = Path.Combine(workDirectory, $"{correlation}.res.json");

        await WriteRequestFileAsync(requestPath, resultPath, payload, ct);

        await Gate.WaitAsync(ct);
        try
        {
            using var scope = _logger.BeginScope($"script={scriptName} id={correlation[..8]}");
            return await RunProcessAsync(scriptName, scriptPath, requestPath, resultPath, extraArguments, ct);
        }
        finally
        {
            Gate.Release();

            if (!Options.KeepTempFiles)
            {
                TryDelete(requestPath);
                TryDelete(resultPath);
            }
        }
    }

    private async Task<ScriptResult> RunProcessAsync(
        string scriptName,
        string scriptPath,
        string requestPath,
        string resultPath,
        IReadOnlyList<string>? extraArguments,
        CancellationToken ct)
    {
        var startInfo = BuildStartInfo(scriptPath, requestPath, extraArguments);

        _logger.LogInformation(
            "Starting {File} {Arguments}",
            startInfo.FileName,
            startInfo.ArgumentList.Count > 0 ? string.Join(' ', startInfo.ArgumentList) : startInfo.Arguments);

        var stdout = new StringBuilder();
        var stderr = new StringBuilder();

        using var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };

        process.OutputDataReceived += (_, e) =>
        {
            if (e.Data is null)
                return;

            stdout.AppendLine(e.Data);
            if (!string.IsNullOrWhiteSpace(e.Data))
                _logger.LogInformation("[{Script}] {Line}", scriptName, e.Data);
        };

        process.ErrorDataReceived += (_, e) =>
        {
            if (e.Data is null)
                return;

            stderr.AppendLine(e.Data);
            if (!string.IsNullOrWhiteSpace(e.Data))
                _logger.LogWarning("[{Script}:stderr] {Line}", scriptName, e.Data);
        };

        var stopwatch = Stopwatch.StartNew();

        try
        {
            process.Start();
        }
        catch (Exception ex)
        {
            throw new ScriptExecutionException(
                scriptName,
                $"Failed to start '{startInfo.FileName}'. Check Codesys:ExecutablePath / Codesys:PythonExecutablePath. {ex.Message}",
                inner: ex);
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeoutCts.CancelAfter(TimeSpan.FromSeconds(Math.Max(1, Options.TimeoutSeconds)));

        try
        {
            await process.WaitForExitAsync(timeoutCts.Token);
        }
        catch (OperationCanceledException) when (!ct.IsCancellationRequested)
        {
            KillProcessTree(process, scriptName);
            throw new ScriptExecutionException(
                scriptName,
                $"Script '{scriptName}' timed out after {Options.TimeoutSeconds}s and was terminated.",
                stderr: stderr.ToString());
        }
        catch (OperationCanceledException)
        {
            KillProcessTree(process, scriptName);
            throw;
        }

        stopwatch.Stop();

        // Flush the async readers before inspecting the buffers.
        process.WaitForExit();

        var exitCode = process.ExitCode;
        _logger.LogInformation(
            "Script {Script} exited with code {ExitCode} after {Elapsed:0.00}s",
            scriptName,
            exitCode,
            stopwatch.Elapsed.TotalSeconds);

        var envelope = await ReadEnvelopeAsync(resultPath, stdout.ToString(), ct);

        if (envelope is null)
        {
            throw new ScriptExecutionException(
                scriptName,
                exitCode == 0
                    ? $"Script '{scriptName}' produced no result envelope."
                    : $"Script '{scriptName}' failed with exit code {exitCode} and produced no result envelope.",
                exitCode,
                stderr: Tail(stderr.ToString()));
        }

        using var document = envelope;
        var root = document.RootElement;

        var ok = root.TryGetProperty("ok", out var okElement) &&
                 okElement.ValueKind == JsonValueKind.True;

        if (!ok)
        {
            var message = $"Script '{scriptName}' reported a failure.";
            string? traceback = null;

            if (root.TryGetProperty("error", out var error) && error.ValueKind == JsonValueKind.Object)
            {
                if (error.TryGetProperty("message", out var m) && m.ValueKind == JsonValueKind.String)
                    message = m.GetString() ?? message;

                if (error.TryGetProperty("traceback", out var t) && t.ValueKind == JsonValueKind.String)
                    traceback = t.GetString();
            }

            throw new ScriptExecutionException(
                scriptName,
                message,
                exitCode,
                traceback,
                Tail(stderr.ToString()));
        }

        var data = root.TryGetProperty("data", out var dataElement)
            ? dataElement.Clone()
            : default;

        return new ScriptResult(data, exitCode, stopwatch.Elapsed);
    }

    private ProcessStartInfo BuildStartInfo(
        string scriptPath,
        string requestPath,
        IReadOnlyList<string>? extraArguments)
    {
        var startInfo = new ProcessStartInfo
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            WorkingDirectory = _scriptsDirectory,
        };

        if (Options.UseCodesys)
        {
            startInfo.FileName = Options.ExecutablePath;

            // CODESYS re-tokenizes its own raw command line on whitespace instead of trusting
            // the OS-level argv it was started with, so a value containing spaces (profile names
            // routinely do, e.g. "CODESYS V3.5 SP21 Patch 3") must be wrapped in literal quote
            // characters to survive as one token. Its tokenizer is naive, though: it just toggles
            // on a bare '"', with no idea what a backslash-escaped \" means. ProcessStartInfo.
            // ArgumentList would "helpfully" backslash-escape those quotes (correct for a normal
            // argv-parsing child, wrong here) and CODESYS would split on the space anyway. So the
            // whole command line is built by hand into Arguments — bypassing ArgumentList's
            // escaping — to keep the quotes exactly as CODESYS expects them.
            var arguments = new StringBuilder();

            if (!string.IsNullOrWhiteSpace(Options.Profile))
                arguments.Append("--profile=").Append(QuoteForCodesys(Options.Profile)).Append(' ');

            if (Options.NoUserInterface)
                arguments.Append("--noUI ");

            foreach (var extra in Options.AdditionalArguments)
                arguments.Append(extra).Append(' ');

            arguments.Append("--runscript=").Append(QuoteForCodesys(scriptPath)).Append(' ');

            // CODESYS splits the scriptargs value on whitespace, so everything the script needs
            // travels inside the single request file instead of on the command line.
            var scriptArgs = new List<string> { requestPath };
            if (extraArguments is { Count: > 0 })
                scriptArgs.AddRange(extraArguments);

            arguments.Append("--scriptargs:").Append(string.Join(' ', scriptArgs));

            startInfo.Arguments = arguments.ToString();
        }
        else
        {
            startInfo.FileName = Options.PythonExecutablePath;
            startInfo.ArgumentList.Add(scriptPath);
            startInfo.ArgumentList.Add(requestPath);

            if (extraArguments is not null)
            {
                foreach (var extra in extraArguments)
                    startInfo.ArgumentList.Add(extra);
            }

            startInfo.Environment["PYTHONIOENCODING"] = "utf-8";
            startInfo.Environment["PYTHONUNBUFFERED"] = "1";
        }

        return startInfo;
    }

    /// <summary>Wraps a value in the plain (unescaped) quotes CODESYS's own arg tokenizer expects.</summary>
    private static string QuoteForCodesys(string value) =>
        value.Contains(' ') ? $"\"{value}\"" : value;

    private async Task<JsonDocument?> ReadEnvelopeAsync(string resultPath, string stdout, CancellationToken ct)
    {
        if (File.Exists(resultPath))
        {
            try
            {
                var text = await File.ReadAllTextAsync(resultPath, ct);
                if (!string.IsNullOrWhiteSpace(text))
                    return JsonDocument.Parse(text);
            }
            catch (JsonException ex)
            {
                _logger.LogWarning(ex, "Result file {Path} is not valid JSON; falling back to stdout", resultPath);
            }
        }

        var begin = stdout.IndexOf(ResultBeginMarker, StringComparison.Ordinal);
        var end = stdout.LastIndexOf(ResultEndMarker, StringComparison.Ordinal);

        if (begin < 0 || end <= begin)
            return null;

        var start = begin + ResultBeginMarker.Length;
        var json = stdout[start..end].Trim();

        try
        {
            return JsonDocument.Parse(json);
        }
        catch (JsonException ex)
        {
            _logger.LogError(ex, "Result envelope on stdout is not valid JSON");
            return null;
        }
    }

    private async Task WriteRequestFileAsync(
        string requestPath,
        string resultPath,
        object payload,
        CancellationToken ct)
    {
        // Serialize the payload, then splice in the result path so scripts always know where to write.
        var node = JsonSerializer.SerializeToNode(payload, PayloadJsonOptions)?.AsObject()
                   ?? new System.Text.Json.Nodes.JsonObject();

        node["resultPath"] = resultPath;

        // UTF-8 without BOM: Python's json module rejects a leading BOM.
        await File.WriteAllTextAsync(requestPath, node.ToJsonString(PayloadJsonOptions), Utf8NoBom, ct);
    }

    private string ResolveScript(string scriptName)
    {
        var fileName = scriptName.EndsWith(".py", StringComparison.OrdinalIgnoreCase)
            ? scriptName
            : scriptName + ".py";

        var path = Path.Combine(_scriptsDirectory, fileName);

        if (!File.Exists(path))
        {
            throw new ScriptExecutionException(
                scriptName,
                $"Script '{fileName}' was not found in '{_scriptsDirectory}'.");
        }

        return path;
    }

    private string EnsureWorkDirectory()
    {
        var directory = Options.WorkDirectory;

        try
        {
            Directory.CreateDirectory(directory);
        }
        catch (Exception ex)
        {
            var fallback = Path.Combine(AppContext.BaseDirectory, "work");
            _logger.LogWarning(ex, "Cannot use work directory {Directory}; falling back to {Fallback}", directory, fallback);
            Directory.CreateDirectory(fallback);
            directory = fallback;
        }

        if (Options.UseCodesys && directory.Contains(' '))
        {
            _logger.LogWarning(
                "Work directory '{Directory}' contains spaces. CODESYS splits --scriptargs on whitespace, " +
                "so scripts may fail to locate their request file. Configure Codesys:WorkDirectory to a path without spaces.",
                directory);
        }

        return directory;
    }

    private void KillProcessTree(Process process, string scriptName)
    {
        try
        {
            if (!process.HasExited)
            {
                _logger.LogWarning("Killing process tree for {Script}", scriptName);
                process.Kill(entireProcessTree: true);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to kill process tree for {Script}", scriptName);
        }
    }

    private static string Tail(string text, int maxChars = 4000) =>
        text.Length <= maxChars ? text : text[^maxChars..];

    private void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
                File.Delete(path);
        }
        catch (Exception ex)
        {
            _logger.LogDebug(ex, "Could not delete temp file {Path}", path);
        }
    }
}
