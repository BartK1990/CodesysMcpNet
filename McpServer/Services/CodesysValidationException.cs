namespace McpServer.Services;

/// <summary>
/// Raised for request problems caught before any script runs: DataAnnotations failures,
/// a missing <c>projectPath</c>, or a project file that doesn't exist. Maps to HTTP 400 in the
/// REST layer and to an <c>McpException</c> in the MCP tool layer.
/// </summary>
public sealed class CodesysValidationException : Exception
{
    public CodesysValidationException(string message, IReadOnlyDictionary<string, string[]>? errors = null)
        : base(message)
    {
        Errors = errors;
    }

    /// <summary>Per-field validation errors, when the failure came from DataAnnotations. Null otherwise.</summary>
    public IReadOnlyDictionary<string, string[]>? Errors { get; }
}
