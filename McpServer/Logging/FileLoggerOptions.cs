namespace McpServer.Logging;

/// <summary>
/// Configuration for the built-in rolling file logger (bound from the "FileLogging" section).
/// </summary>
public sealed class FileLoggerOptions
{
    /// <summary>Target directory. Relative paths are resolved against the application base directory.</summary>
    public string Directory { get; set; } = "Logs";

    /// <summary>File name prefix; the final name is "{prefix}-yyyyMMdd[_NNN].log".</summary>
    public string FilePrefix { get; set; } = "mcpserver";

    /// <summary>Minimum level written to file.</summary>
    public LogLevel MinimumLevel { get; set; } = LogLevel.Information;

    /// <summary>Roll to a new file once the current one exceeds this size. 0 disables size rolling.</summary>
    public long FileSizeLimitBytes { get; set; } = 20L * 1024 * 1024;

    /// <summary>How many log files to keep. 0 disables clean-up.</summary>
    public int RetainedFileCountLimit { get; set; } = 30;
}
