using System.ComponentModel.DataAnnotations;

namespace McpServer.Models;

/// <summary>POST /compile</summary>
public sealed class CompileRequest
{
    /// <summary>Absolute path to the .project file.</summary>
    [Required(AllowEmptyStrings = false)]
    public string ProjectPath { get; set; } = string.Empty;

    /// <summary>Run a clean build before generating code.</summary>
    public bool Clean { get; set; }

    /// <summary>Save the project after a successful compile.</summary>
    public bool SaveAfterCompile { get; set; }
}
