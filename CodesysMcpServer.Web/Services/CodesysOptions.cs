namespace CodesysMcpServer.Web.Services;

/// <summary>
/// Configuration for how the Python scripts are launched (bound from the "Codesys" section).
/// </summary>
public sealed class CodesysOptions
{
    public const string SectionName = "Codesys";

    /// <summary>
    /// When true the scripts run inside CODESYS via <c>CODESYS.exe --runscript</c> (the only mode
    /// where the Scripting Engine is available). When false they run under a plain Python/IronPython
    /// interpreter, which is useful for smoke-testing the request/response plumbing.
    /// </summary>
    public bool UseCodesys { get; set; } = true;

    /// <summary>Full path to CODESYS.exe.</summary>
    public string ExecutablePath { get; set; } =
        @"C:\Program Files\CODESYS 3.5.20.0\CODESYS\Common\CODESYS.exe";

    /// <summary>
    /// Full path to the currently selected .project file. Every endpoint and MCP tool operates
    /// on this project — set it via the settings page (<c>/</c>) or <c>POST /settings</c>,
    /// which persists it to <c>appsettings.production.json</c> next to the running binary.
    /// </summary>
    public string? ProjectPath { get; set; }

    /// <summary>Profile name passed to <c>--profile</c>. Leave empty to use the default profile.</summary>
    public string Profile { get; set; } = "CODESYS V3.5 SP20 Patch 0";

    /// <summary>Start CODESYS without its user interface.</summary>
    public bool NoUserInterface { get; set; } = true;

    /// <summary>Extra command line arguments appended verbatim before the script arguments.</summary>
    public List<string> AdditionalArguments { get; set; } = [];

    /// <summary>Python interpreter used when <see cref="UseCodesys"/> is false.</summary>
    public string PythonExecutablePath { get; set; } = "python";

    /// <summary>Directory holding the .py files. Relative paths resolve against the app base directory.</summary>
    public string ScriptsDirectory { get; set; } = "Scripts";

    /// <summary>
    /// Working directory for the request/response hand-off files.
    /// Keep it free of spaces — CODESYS splits <c>--scriptargs</c> on whitespace.
    /// </summary>
    public string WorkDirectory { get; set; } = @"C:\ProgramData\CodesysMcpNet\work";

    /// <summary>Per-script timeout in seconds. CODESYS start-up alone can take a minute.</summary>
    public int TimeoutSeconds { get; set; } = 600;

    /// <summary>Keep the temporary request/result files for troubleshooting.</summary>
    public bool KeepTempFiles { get; set; }

    /// <summary>
    /// Keep one CODESYS instance running with the project open and send every request to it
    /// (see <see cref="CodesysSession"/>), instead of starting CODESYS.exe per request. Start-up
    /// and project load are then paid once instead of on every call. Only applies when
    /// <see cref="UseCodesys"/> is true.
    /// </summary>
    public bool KeepSessionAlive { get; set; } = true;

    /// <summary>Start the session and open the project as soon as the server starts.</summary>
    public bool StartSessionOnStartup { get; set; } = true;

    /// <summary>
    /// Stop the session after this many idle minutes, releasing CODESYS and the project file.
    /// 0 keeps it running until the server stops or <c>POST /session/stop</c> is called.
    /// </summary>
    public int SessionIdleMinutes { get; set; }
}
