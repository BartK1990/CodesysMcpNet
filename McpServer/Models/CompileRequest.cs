using System.ComponentModel.DataAnnotations;

namespace McpServer.Models;

/// <summary>POST /compile. Acts on the project configured via the settings page.</summary>
public sealed class CompileRequest
{
    /// <summary>Run a clean build before generating code.</summary>
    public bool Clean { get; set; }

    /// <summary>Save the project after a successful compile.</summary>
    public bool SaveAfterCompile { get; set; }
}
