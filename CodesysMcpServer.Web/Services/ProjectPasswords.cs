using System.Collections.Concurrent;

namespace CodesysMcpServer.Web.Services;

/// <summary>
/// Passwords of password-protected projects, entered on the settings page, and which projects
/// are currently known to need one.
///
/// Kept in memory only: never written to settings files and never returned by the API, so a
/// password has to be entered again after the server restarts. Scripts receive it through a
/// short-lived file next to the request (see <see cref="PythonRunner"/>), deleted as soon as
/// the request is done.
/// </summary>
public sealed class ProjectPasswords
{
    public const string RequiredCode = "password_required";
    public const string InvalidCode = "password_invalid";

    private readonly ConcurrentDictionary<string, string> _passwords = new(StringComparer.OrdinalIgnoreCase);
    private readonly ConcurrentDictionary<string, string> _needed = new(StringComparer.OrdinalIgnoreCase);

    public string? Get(string projectPath) =>
        _passwords.TryGetValue(Key(projectPath), out var password) ? password : null;

    public bool Has(string projectPath) => _passwords.ContainsKey(Key(projectPath));

    /// <summary>Stores (or, when empty, forgets) a project's password.</summary>
    public void Set(string projectPath, string? password)
    {
        if (string.IsNullOrEmpty(password))
            _passwords.TryRemove(Key(projectPath), out _);
        else
            _passwords[Key(projectPath)] = password;

        // A new password deserves a fresh attempt; the next open reports again if it's wrong.
        _needed.TryRemove(Key(projectPath), out _);
    }

    /// <summary>
    /// <see cref="RequiredCode"/> or <see cref="InvalidCode"/> when the last attempt to open
    /// the project failed for its password; null otherwise.
    /// </summary>
    public string? Needed(string projectPath) =>
        _needed.TryGetValue(Key(projectPath), out var code) ? code : null;

    public void MarkNeeded(string projectPath, string code) => _needed[Key(projectPath)] = code;

    public void MarkOpened(string projectPath) => _needed.TryRemove(Key(projectPath), out _);

    public static bool IsPasswordCode(string? code) => code is RequiredCode or InvalidCode;

    private static string Key(string projectPath) => ProjectCatalog.Normalize(projectPath);
}

/// <summary>
/// A project could not be opened without (the right) password. Maps to HTTP 401 in the REST
/// layer; the settings page then asks for the password.
/// </summary>
public sealed class ProjectPasswordException : Exception
{
    public ProjectPasswordException(CodesysProject project, string code, Exception inner)
        : base(code == ProjectPasswords.InvalidCode
            ? $"The password for project '{project.Name}' was rejected. Enter the correct one on the settings page."
            : $"Project '{project.Name}' is password protected. Enter its password on the settings page.",
            inner)
    {
        Project = project;
        Code = code;
    }

    public CodesysProject Project { get; }

    /// <summary><see cref="ProjectPasswords.RequiredCode"/> or <see cref="ProjectPasswords.InvalidCode"/>.</summary>
    public string Code { get; }
}
