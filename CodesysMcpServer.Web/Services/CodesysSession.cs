using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Microsoft.Extensions.Options;

namespace CodesysMcpServer.Web.Services;

/// <summary>Snapshot of the persistent CODESYS session, for <c>GET /session</c> and the settings page.</summary>
/// <param name="State">
/// <c>disabled</c> (KeepSessionAlive off), <c>stopped</c>, <c>starting</c> (CODESYS launching /
/// project loading), <c>ready</c> (idle with the project open), <c>busy</c> (running a script)
/// or <c>stopping</c>.
/// </param>
/// <param name="CurrentScript">Script being run right now, if any.</param>
/// <param name="BusySince">When the current script was submitted.</param>
/// <param name="LastError">Last session-level failure (crash, timeout, failed start), cleared by the next success.</param>
public sealed record CodesysSessionStatus(
    string State,
    bool Enabled,
    bool Running,
    int? ProcessId,
    DateTimeOffset? StartedAt,
    int RequestsServed,
    string? CurrentScript,
    DateTimeOffset? BusySince,
    string? LastError,
    DateTimeOffset? LastErrorAt);

/// <summary>
/// Keeps one CODESYS instance alive running <c>Scripts/session_host.py</c>, which holds the
/// project open and serves script requests from a queue directory. Starting CODESYS and
/// loading a project take minutes; a request against a warm session takes seconds.
///
/// Hand-off protocol
/// -----------------
/// The request file written by <see cref="PythonRunner"/> (it carries the script name and
/// the result path) is moved atomically into the queue directory. The host claims it by
/// renaming it, runs the script and writes the usual envelope to the result path, which
/// this class polls for. See session_host.py for the host side.
///
/// Lifetime
/// --------
/// Started lazily on the first request (or at server start-up, see
/// <see cref="CodesysOptions.StartSessionOnStartup"/>), restarted automatically after a crash
/// or when the CODESYS executable/profile settings change, and stopped when the server stops.
/// The host also exits by itself when this server process disappears, so it never lingers
/// holding the project locked.
///
/// Not thread-safe on purpose: every call arrives under <see cref="PythonRunner"/>'s gate,
/// except <see cref="DisposeAsync"/> at shutdown.
/// </summary>
public sealed class CodesysSession : IAsyncDisposable
{
    private const string HostScript = "session_host.py";
    private const string ShutdownScript = "__shutdown__";
    private const int OutputTailLines = 200;

    private static readonly UTF8Encoding Utf8NoBom = new(encoderShouldEmitUTF8Identifier: false);
    private static readonly TimeSpan PollInterval = TimeSpan.FromMilliseconds(100);
    private static readonly TimeSpan ShutdownGracePeriod = TimeSpan.FromSeconds(20);

    private readonly IOptionsMonitor<CodesysOptions> _optionsMonitor;
    private readonly ILogger<CodesysSession> _logger;
    private readonly Queue<string> _outputTail = new();

    private Process? _process;
    private string? _signature;
    private string? _queueDirectory;
    private DateTimeOffset? _startedAt;
    private int _requestsServed;

    // Read by GetStatus from other threads; only ever informational.
    private volatile string? _currentScript;
    private DateTimeOffset? _busySince;
    private volatile bool _stopping;
    private string? _lastError;
    private DateTimeOffset? _lastErrorAt;

    public CodesysSession(IOptionsMonitor<CodesysOptions> options, ILogger<CodesysSession> logger)
    {
        _optionsMonitor = options;
        _logger = logger;
    }

    private CodesysOptions Options => _optionsMonitor.CurrentValue;

    /// <summary>Whether requests should go through the session rather than a one-shot CODESYS run.</summary>
    public bool Enabled => Options.UseCodesys && Options.KeepSessionAlive;

    public CodesysSessionStatus GetStatus()
    {
        var process = _process;
        var running = IsRunning(process);
        var currentScript = _currentScript;

        var state =
            !Enabled ? "disabled" :
            _stopping ? "stopping" :
            currentScript is not null && (!running || _requestsServed == 0) ? "starting" :
            currentScript is not null ? "busy" :
            running ? "ready" :
            "stopped";

        return new CodesysSessionStatus(
            state,
            Enabled,
            running,
            running ? process!.Id : null,
            running ? _startedAt : null,
            _requestsServed,
            currentScript,
            currentScript is not null ? _busySince : null,
            _lastError,
            _lastErrorAt);
    }

    /// <summary>Records a session-level failure (e.g. a failed warm-up) for the status display.</summary>
    public void ReportFailure(string message)
    {
        _lastError = message;
        _lastErrorAt = DateTimeOffset.UtcNow;
    }

    /// <summary>Flags a pending stop so the status shows it while in-flight work finishes.</summary>
    public void MarkStopping() => _stopping = true;

    /// <summary>
    /// Queues a request with the session (starting it if needed) and waits for its result file.
    /// Returns the time spent waiting; the caller reads and interprets the envelope.
    /// </summary>
    public async Task<TimeSpan> RunAsync(
        string scriptName,
        string scriptsDirectory,
        string workDirectory,
        string requestPath,
        string resultPath,
        CancellationToken ct)
    {
        _busySince = DateTimeOffset.UtcNow;
        _currentScript = scriptName;
        try
        {
            var elapsed = await RunCoreAsync(scriptName, scriptsDirectory, workDirectory, requestPath, resultPath, ct);
            _lastError = null;
            _lastErrorAt = null;
            return elapsed;
        }
        catch (ScriptExecutionException ex)
        {
            ReportFailure(ex.Message);
            throw;
        }
        finally
        {
            _currentScript = null;
        }
    }

    private async Task<TimeSpan> RunCoreAsync(
        string scriptName,
        string scriptsDirectory,
        string workDirectory,
        string requestPath,
        string resultPath,
        CancellationToken ct)
    {
        var process = await EnsureStartedAsync(scriptsDirectory, workDirectory);
        var queuedPath = Path.Combine(_queueDirectory!, Path.GetFileName(requestPath));

        File.Move(requestPath, queuedPath);

        var stopwatch = Stopwatch.StartNew();
        var timeout = TimeSpan.FromSeconds(Math.Max(1, Options.TimeoutSeconds));
        var withdrawn = false;

        while (!File.Exists(resultPath))
        {
            if (process.HasExited)
            {
                throw new ScriptExecutionException(
                    scriptName,
                    $"The CODESYS session exited (code {process.ExitCode}) while running '{scriptName}'. " +
                    "It will be restarted on the next request.",
                    process.ExitCode,
                    stderr: OutputTail());
            }

            if (stopwatch.Elapsed > timeout)
            {
                _logger.LogWarning("Script {Script} timed out after {Timeout}s; killing the CODESYS session", scriptName, Options.TimeoutSeconds);
                Kill(process);
                throw new ScriptExecutionException(
                    scriptName,
                    $"Script '{scriptName}' timed out after {Options.TimeoutSeconds}s. The CODESYS session was terminated " +
                    "and will be restarted on the next request.",
                    stderr: OutputTail());
            }

            // A request the host has not picked up yet can be withdrawn cleanly. Once claimed it
            // cannot be interrupted without killing the session, so it is allowed to finish.
            if (ct.IsCancellationRequested && !withdrawn)
            {
                withdrawn = true;
                if (TryWithdraw(queuedPath))
                    ct.ThrowIfCancellationRequested();

                _logger.LogInformation("Request for {Script} was cancelled but CODESYS is already running it; waiting for it to finish", scriptName);
            }

            await Task.Delay(PollInterval, CancellationToken.None);
        }

        _requestsServed++;
        return stopwatch.Elapsed;
    }

    /// <summary>Stops the session gracefully (the host closes the project without saving).</summary>
    public async Task StopAsync()
    {
        try
        {
            await StopCoreAsync();
        }
        finally
        {
            _stopping = false;
        }
    }

    private async Task StopCoreAsync()
    {
        var process = _process;
        _process = null;
        _signature = null;
        _startedAt = null;

        if (!IsRunning(process))
        {
            process?.Dispose();
            return;
        }

        _logger.LogInformation("Stopping CODESYS session (pid {Pid})", process!.Id);

        try
        {
            var id = Guid.NewGuid().ToString("N");
            await EnqueueAsync(id, new { script = ShutdownScript, resultPath = Path.Combine(_queueDirectory!, id + ".res.json") });

            using var grace = new CancellationTokenSource(ShutdownGracePeriod);
            await process.WaitForExitAsync(grace.Token);
            _logger.LogInformation("CODESYS session stopped");
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "CODESYS session did not stop gracefully; killing it");
            Kill(process);
        }
        finally
        {
            process.Dispose();
        }
    }

    public async ValueTask DisposeAsync() => await StopAsync();

    private async Task<Process> EnsureStartedAsync(string scriptsDirectory, string workDirectory)
    {
        var options = Options;
        var signature = string.Join('|',
            options.ExecutablePath,
            options.Profile,
            options.NoUserInterface,
            string.Join(' ', options.AdditionalArguments),
            options.SessionIdleMinutes,
            workDirectory);

        if (IsRunning(_process))
        {
            if (signature == _signature)
                return _process!;

            _logger.LogInformation("CODESYS settings changed; restarting the session");
            await StopCoreAsync();
        }
        else if (_process is not null)
        {
            _logger.LogWarning("CODESYS session (pid {Pid}) is no longer running; starting a new one", _process.Id);
            _process.Dispose();
            _process = null;
        }

        _queueDirectory = Path.Combine(workDirectory, "session");
        ResetQueueDirectory(_queueDirectory);

        var configPath = Path.Combine(workDirectory, "session.json");
        var config = new
        {
            queueDirectory = _queueDirectory,
            parentProcessId = Environment.ProcessId,
            pollIntervalMs = (int)PollInterval.TotalMilliseconds,
            idleShutdownSeconds = Math.Max(0, options.SessionIdleMinutes) * 60,
            keepTempFiles = options.KeepTempFiles,
        };
        await File.WriteAllTextAsync(configPath, JsonSerializer.Serialize(config), Utf8NoBom);

        var startInfo = new ProcessStartInfo
        {
            FileName = options.ExecutablePath,
            Arguments = PythonRunner.BuildCodesysArguments(options, Path.Combine(scriptsDirectory, HostScript), [configPath]),
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            WorkingDirectory = scriptsDirectory,
        };

        _logger.LogInformation("Starting CODESYS session: {File} {Arguments}", startInfo.FileName, startInfo.Arguments);

        var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, e) => OnOutput(e.Data, isError: false);
        process.ErrorDataReceived += (_, e) => OnOutput(e.Data, isError: true);
        process.Exited += (_, _) => _logger.LogInformation("CODESYS session process exited");

        lock (_outputTail)
            _outputTail.Clear();

        try
        {
            process.Start();
        }
        catch (Exception ex)
        {
            process.Dispose();
            throw new ScriptExecutionException(
                HostScript,
                $"Failed to start '{startInfo.FileName}'. Check Codesys:ExecutablePath. {ex.Message}",
                inner: ex);
        }

        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        _process = process;
        _signature = signature;
        _startedAt = DateTimeOffset.UtcNow;
        _requestsServed = 0;
        return process;
    }

    private async Task EnqueueAsync(string id, object request)
    {
        var temp = Path.Combine(_queueDirectory!, id + ".tmp");
        await File.WriteAllTextAsync(temp, JsonSerializer.Serialize(request), Utf8NoBom);
        File.Move(temp, Path.Combine(_queueDirectory!, id + ".req.json"));
    }

    private void OnOutput(string? line, bool isError)
    {
        if (line is null)
            return;

        lock (_outputTail)
        {
            _outputTail.Enqueue(line);
            while (_outputTail.Count > OutputTailLines)
                _outputTail.Dequeue();
        }

        if (string.IsNullOrWhiteSpace(line))
            return;

        if (isError)
            _logger.LogWarning("[session:stderr] {Line}", line);
        else
            _logger.LogInformation("[session] {Line}", line);
    }

    private string OutputTail()
    {
        lock (_outputTail)
            return string.Join(Environment.NewLine, _outputTail);
    }

    private bool TryWithdraw(string queuedPath)
    {
        try
        {
            // Atomic with respect to the host's own rename: exactly one of the two wins.
            File.Move(queuedPath, queuedPath + ".cancelled");
            File.Delete(queuedPath + ".cancelled");
            return true;
        }
        catch (IOException)
        {
            return false;
        }
    }

    private void ResetQueueDirectory(string directory)
    {
        Directory.CreateDirectory(directory);

        foreach (var stale in Directory.EnumerateFiles(directory))
        {
            try
            {
                File.Delete(stale);
            }
            catch (Exception ex)
            {
                _logger.LogDebug(ex, "Could not delete stale queue file {Path}", stale);
            }
        }
    }

    private static bool IsRunning(Process? process)
    {
        try
        {
            return process is not null && !process.HasExited;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    private void Kill(Process process)
    {
        try
        {
            if (!process.HasExited)
                process.Kill(entireProcessTree: true);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to kill the CODESYS session");
        }
    }
}
