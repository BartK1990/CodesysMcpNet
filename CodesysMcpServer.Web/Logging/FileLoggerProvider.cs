using System.Collections.Concurrent;
using System.Text;
using Microsoft.Extensions.Options;

namespace CodesysMcpServer.Web.Logging;

/// <summary>
/// Minimal dependency-free rolling file logger provider.
/// Log records are queued and flushed by a single background thread so request
/// threads (and the Python stdout pump) are never blocked by disk I/O.
/// </summary>
[ProviderAlias("File")]
public sealed class FileLoggerProvider : ILoggerProvider
{
    private readonly FileLoggerOptions _options;
    private readonly string _directory;
    private readonly BlockingCollection<string> _queue = new(new ConcurrentQueue<string>(), 10_000);
    private readonly Thread _worker;
    private readonly ConcurrentDictionary<string, FileLogger> _loggers = new(StringComparer.Ordinal);

    private StreamWriter? _writer;
    private string? _currentPath;
    private DateOnly _currentDate;
    private long _currentSize;
    private bool _disposed;

    public FileLoggerProvider(IOptions<FileLoggerOptions> options)
    {
        _options = options.Value;
        _directory = Path.IsPathRooted(_options.Directory)
            ? _options.Directory
            : Path.Combine(AppContext.BaseDirectory, _options.Directory);

        System.IO.Directory.CreateDirectory(_directory);

        _worker = new Thread(ProcessQueue)
        {
            IsBackground = true,
            Name = "file-logger",
        };
        _worker.Start();
    }

    public ILogger CreateLogger(string categoryName) =>
        _loggers.GetOrAdd(categoryName, name => new FileLogger(name, this));

    internal bool IsEnabled(LogLevel level) => level != LogLevel.None && level >= _options.MinimumLevel;

    internal void Enqueue(string line)
    {
        if (_disposed)
            return;

        // Never block the caller: drop the record if the queue is saturated.
        _queue.TryAdd(line);
    }

    private void ProcessQueue()
    {
        foreach (var line in _queue.GetConsumingEnumerable())
        {
            try
            {
                var writer = EnsureWriter(Encoding.UTF8.GetByteCount(line));
                writer.Write(line);
                _currentSize += Encoding.UTF8.GetByteCount(line);

                if (_queue.Count == 0)
                    writer.Flush();
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"[file-logger] write failed: {ex.Message}");
            }
        }

        try
        {
            _writer?.Flush();
            _writer?.Dispose();
        }
        catch
        {
            // Nothing sensible to do while shutting down.
        }
    }

    private StreamWriter EnsureWriter(int incomingBytes)
    {
        var today = DateOnly.FromDateTime(DateTime.Now);
        var needsRoll =
            _writer is null ||
            today != _currentDate ||
            (_options.FileSizeLimitBytes > 0 && _currentSize + incomingBytes > _options.FileSizeLimitBytes);

        if (!needsRoll)
            return _writer!;

        _writer?.Flush();
        _writer?.Dispose();

        _currentDate = today;
        _currentPath = NextFilePath(today);
        var stream = new FileStream(_currentPath, FileMode.Append, FileAccess.Write, FileShare.ReadWrite);
        _currentSize = stream.Length;
        _writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = false };

        CleanupOldFiles();
        return _writer;
    }

    private string NextFilePath(DateOnly date)
    {
        var stamp = date.ToString("yyyyMMdd");
        var candidate = Path.Combine(_directory, $"{_options.FilePrefix}-{stamp}.log");

        if (_options.FileSizeLimitBytes <= 0)
            return candidate;

        for (var index = 0; index < 1000; index++)
        {
            candidate = index == 0
                ? Path.Combine(_directory, $"{_options.FilePrefix}-{stamp}.log")
                : Path.Combine(_directory, $"{_options.FilePrefix}-{stamp}_{index:D3}.log");

            var info = new FileInfo(candidate);
            if (!info.Exists || info.Length < _options.FileSizeLimitBytes)
                return candidate;
        }

        return candidate;
    }

    private void CleanupOldFiles()
    {
        if (_options.RetainedFileCountLimit <= 0)
            return;

        try
        {
            var files = new DirectoryInfo(_directory)
                .GetFiles($"{_options.FilePrefix}-*.log")
                .OrderByDescending(f => f.Name, StringComparer.Ordinal)
                .Skip(_options.RetainedFileCountLimit);

            foreach (var file in files)
            {
                if (!string.Equals(file.FullName, _currentPath, StringComparison.OrdinalIgnoreCase))
                    file.Delete();
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[file-logger] cleanup failed: {ex.Message}");
        }
    }

    public void Dispose()
    {
        if (_disposed)
            return;

        _disposed = true;
        _queue.CompleteAdding();
        _worker.Join(TimeSpan.FromSeconds(5));
        _queue.Dispose();
    }
}
