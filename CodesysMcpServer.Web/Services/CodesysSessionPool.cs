using System.Security.Cryptography;
using System.Text;
using Microsoft.Extensions.Options;

namespace CodesysMcpServer.Web.Services;

/// <summary>
/// Owns the persistent <see cref="CodesysSession"/>s and the gate that serializes work on each.
///
/// With <see cref="CodesysOptions.MaxProjects"/> = 1 there is exactly one session, shared by
/// whatever the configured project is — switching projects on the settings page just makes its
/// host close the old project and open the new one, as it always did. With more, every
/// configured project gets its own session (its own CODESYS instance with that project kept
/// open), so alternating between projects never pays a project reload, and requests for
/// different projects run side by side. Requests for the same project are still strictly
/// one at a time: a single CODESYS instance can only run one script at once.
///
/// Sessions of projects that are no longer configured are stopped when the configuration
/// changes, releasing their project files.
/// </summary>
public sealed class CodesysSessionPool : IAsyncDisposable
{
    private const string SharedKey = "default";

    private readonly IOptionsMonitor<CodesysOptions> _options;
    private readonly ProjectPasswords _passwords;
    private readonly ILogger _logger;
    private readonly ILogger _sessionLogger;
    private readonly IDisposable? _changeSubscription;
    private readonly Dictionary<string, Entry> _entries = new(StringComparer.Ordinal);
    private readonly object _lock = new();

    public CodesysSessionPool(
        IOptionsMonitor<CodesysOptions> options,
        ProjectPasswords passwords,
        ILoggerFactory loggerFactory)
    {
        _options = options;
        _passwords = passwords;
        _logger = loggerFactory.CreateLogger<CodesysSessionPool>();
        _sessionLogger = loggerFactory.CreateLogger<CodesysSession>();
        _changeSubscription = options.OnChange(_ => PruneInBackground());
    }

    /// <summary>Whether requests should go through a session rather than a one-shot CODESYS run.</summary>
    public bool Enabled => _options.CurrentValue is { UseCodesys: true, KeepSessionAlive: true };

    /// <summary>Runs <paramref name="work"/> on the session of <paramref name="projectPath"/>, under its gate.</summary>
    public async Task<T> RunAsync<T>(string projectPath, Func<CodesysSession, Task<T>> work, CancellationToken ct)
    {
        while (true)
        {
            var entry = GetEntry(projectPath);
            await entry.Gate.WaitAsync(ct);
            try
            {
                // Retired while we waited: the project was reconfigured, pick up the current entry.
                if (entry.Retired)
                    continue;

                return await work(entry.Session);
            }
            finally
            {
                entry.Gate.Release();
            }
        }
    }

    public CodesysSessionStatus GetStatus(CodesysProject project) =>
        GetEntry(project.Path).Session.GetStatus() with
        {
            Project = project.Name,
            ProjectPath = project.Path,
            PasswordNeeded = _passwords.Needed(project.Path),
            HasPassword = _passwords.Has(project.Path),
        };

    /// <summary>Records a session-level failure (e.g. a failed warm-up) for the status display.</summary>
    public void ReportFailure(string projectPath, string message) =>
        GetEntry(projectPath).Session.ReportFailure(message);

    /// <summary>Stops the project's session once any in-flight script on it has finished.</summary>
    public async Task StopAsync(string projectPath, CancellationToken ct)
    {
        var entry = GetEntry(projectPath);
        entry.Session.MarkStopping();

        try
        {
            await entry.Gate.WaitAsync(ct);
        }
        catch (OperationCanceledException)
        {
            // The caller stopped waiting, but the stop request stands.
            _ = StopInBackgroundAsync(entry);
            throw;
        }

        try
        {
            await entry.Session.StopAsync();
        }
        finally
        {
            entry.Gate.Release();
        }
    }

    public async ValueTask DisposeAsync()
    {
        _changeSubscription?.Dispose();

        List<Entry> entries;
        lock (_lock)
        {
            entries = [.. _entries.Values];
            _entries.Clear();
        }

        foreach (var entry in entries)
        {
            entry.Retired = true;
            await entry.Session.DisposeAsync();
        }
    }

    private Entry GetEntry(string projectPath)
    {
        var key = KeyFor(projectPath, _options.CurrentValue);

        lock (_lock)
        {
            if (!_entries.TryGetValue(key, out var entry))
            {
                entry = new Entry(new CodesysSession(_options, _sessionLogger, key));
                _entries[key] = entry;
            }

            return entry;
        }
    }

    private void PruneInBackground() => _ = PruneAsync();

    /// <summary>Stops the sessions of projects that are no longer configured.</summary>
    private async Task PruneAsync()
    {
        try
        {
            var options = _options.CurrentValue;
            var wanted = ProjectCatalog.List(options)
                .Select(p => KeyFor(p.Path, options))
                .ToHashSet(StringComparer.Ordinal);

            List<Entry> retired;
            lock (_lock)
            {
                retired = _entries.Where(e => !wanted.Contains(e.Key)).Select(e => e.Value).ToList();
                foreach (var key in _entries.Keys.Where(k => !wanted.Contains(k)).ToList())
                    _entries.Remove(key);
            }

            foreach (var entry in retired)
            {
                entry.Retired = true;
                if (entry.Session.GetStatus().Running)
                    _logger.LogInformation("Project no longer configured; stopping its CODESYS session");

                await StopInBackgroundAsync(entry);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Stopping CODESYS sessions of removed projects failed");
        }
    }

    private async Task StopInBackgroundAsync(Entry entry)
    {
        await entry.Gate.WaitAsync();
        try
        {
            await entry.Session.StopAsync();
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Stopping the CODESYS session failed");
        }
        finally
        {
            entry.Gate.Release();
        }
    }

    /// <summary>
    /// One shared session when a single project is allowed, otherwise one per project, keyed
    /// by a short hash of its path (it names the session's queue directory).
    /// </summary>
    private static string KeyFor(string projectPath, CodesysOptions options)
    {
        if (options.EffectiveMaxProjects == 1)
            return SharedKey;

        var normalized = ProjectCatalog.Normalize(projectPath).ToUpperInvariant();
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(normalized)), 0, 4).ToLowerInvariant();
        return $"{Sanitize(ProjectCatalog.NameOf(projectPath))}-{hash}";
    }

    // The key becomes a directory name that CODESYS gets on its command line: keep it to
    // characters that need no quoting.
    private static string Sanitize(string name)
    {
        var chars = name.Select(c => char.IsAsciiLetterOrDigit(c) || c is '-' or '_' ? c : '_').ToArray();
        var text = new string(chars);
        return text.Length > 32 ? text[..32] : text;
    }

    private sealed class Entry(CodesysSession session)
    {
        public CodesysSession Session { get; } = session;
        public SemaphoreSlim Gate { get; } = new(1, 1);
        public volatile bool Retired;
    }
}
