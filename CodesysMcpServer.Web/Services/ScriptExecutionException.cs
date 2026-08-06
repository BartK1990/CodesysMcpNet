namespace CodesysMcpServer.Web.Services;

/// <summary>
/// Raised when a Python script fails: non-zero exit code, missing/garbled result envelope,
/// or an envelope reporting <c>ok: false</c>.
/// </summary>
public sealed class ScriptExecutionException : Exception
{
    public ScriptExecutionException(
        string scriptName,
        string message,
        int? exitCode = null,
        string? pythonTraceback = null,
        string? stderr = null,
        Exception? inner = null)
        : base(message, inner)
    {
        ScriptName = scriptName;
        ExitCode = exitCode;
        PythonTraceback = pythonTraceback;
        StandardError = stderr;
    }

    public string ScriptName { get; }

    public int? ExitCode { get; }

    public string? PythonTraceback { get; }

    public string? StandardError { get; }
}
