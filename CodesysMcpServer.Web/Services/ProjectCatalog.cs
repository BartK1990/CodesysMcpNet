using Microsoft.Extensions.Options;

namespace CodesysMcpServer.Web.Services;

/// <summary>A configured project, as returned by <c>GET /projects</c> and the <c>projects</c> tool.</summary>
/// <param name="Name">File name without extension — what callers pass as <c>project</c>.</param>
/// <param name="Path">Full path to the .project or .library file.</param>
/// <param name="IsDefault">Whether this is the project used when the caller names none.</param>
/// <param name="Exists">Whether the file exists on this machine.</param>
public sealed record CodesysProject(string Name, string Path, bool IsDefault, bool Exists)
{
    /// <summary><c>project</c> for a .project file, <c>library</c> for a source .library.</summary>
    public string Kind => ProjectCatalog.KindOf(Path);
}

/// <summary>
/// The projects callers may act on: the default <see cref="CodesysOptions.ProjectPath"/> plus,
/// when <see cref="CodesysOptions.MaxProjects"/> allows it, the
/// <see cref="CodesysOptions.AdditionalProjectPaths"/>. Read fresh on every call so a save on
/// the settings page applies to the next request.
///
/// Only configured projects can be selected — a caller can never point the server at an
/// arbitrary file on disk.
/// </summary>
public sealed class ProjectCatalog
{
    private readonly IOptionsMonitor<CodesysOptions> _options;

    public ProjectCatalog(IOptionsMonitor<CodesysOptions> options)
    {
        _options = options;
    }

    /// <summary>Extensions of the files that can be configured: a project or a source library.</summary>
    public static readonly string[] SupportedExtensions = [".project", ".library"];

    /// <summary>
    /// Compiled libraries carry no source, so they cannot be opened for editing. Checked before
    /// <see cref="SupportedExtensions"/>, as ".compiled-library" also ends in "library".
    /// </summary>
    private static readonly string[] CompiledLibraryExtensions = [".compiled-library", ".compiled-library-v3"];

    /// <summary><c>library</c> for a .library file, <c>project</c> otherwise.</summary>
    public static string KindOf(string path) =>
        path.Trim().EndsWith(".library", StringComparison.OrdinalIgnoreCase) ? "library" : "project";

    /// <summary>
    /// Throws unless <paramref name="path"/> names a file CODESYS can open as the primary project:
    /// a <c>.project</c> or a source <c>.library</c>.
    /// </summary>
    public static void ValidateExtension(string path)
    {
        var trimmed = path.Trim();

        if (CompiledLibraryExtensions.Any(e => trimmed.EndsWith(e, StringComparison.OrdinalIgnoreCase)))
        {
            throw new CodesysValidationException(
                $"A compiled library carries no source and cannot be opened: {trimmed}. Use its source .library file.");
        }

        if (!SupportedExtensions.Any(e => trimmed.EndsWith(e, StringComparison.OrdinalIgnoreCase)))
        {
            throw new CodesysValidationException(
                $"Not a CODESYS project or library: {trimmed}. Expected a .project or .library file.");
        }
    }

    /// <summary>Configured projects, default first, without duplicates.</summary>
    public IReadOnlyList<CodesysProject> List() => List(_options.CurrentValue);

    public static IReadOnlyList<CodesysProject> List(CodesysOptions options)
    {
        var paths = new List<string>();

        if (!string.IsNullOrWhiteSpace(options.ProjectPath))
            paths.Add(options.ProjectPath.Trim());

        // Without a default there is nothing to fall back on, so additional projects are only
        // honoured next to one — the settings page always saves them together.
        if (paths.Count > 0)
        {
            foreach (var path in options.AdditionalProjectPaths)
            {
                if (paths.Count >= options.EffectiveMaxProjects)
                    break;

                if (!string.IsNullOrWhiteSpace(path) && !paths.Any(p => SamePath(p, path)))
                    paths.Add(path.Trim());
            }
        }

        return paths
            .Select((path, index) => new CodesysProject(NameOf(path), path, index == 0, File.Exists(path)))
            .ToList();
    }

    /// <summary>
    /// Picks the project a request acts on: the default one when <paramref name="project"/> is
    /// empty, otherwise the configured project with that full path or name (file name, with or
    /// without its <c>.project</c> / <c>.library</c> extension, case-insensitive).
    /// </summary>
    public CodesysProject Resolve(string? project)
    {
        var projects = List();

        if (projects.Count == 0)
        {
            throw new CodesysValidationException(
                "No project is configured. Set one on the settings page (/) or via POST /settings.");
        }

        if (string.IsNullOrWhiteSpace(project))
            return projects[0];

        var wanted = project.Trim();

        var byPath = projects.FirstOrDefault(p => SamePath(p.Path, wanted));
        if (byPath is not null)
            return byPath;

        var byName = projects
            .Where(p => string.Equals(p.Name, wanted, StringComparison.OrdinalIgnoreCase) ||
                        SupportedExtensions.Any(e =>
                            string.Equals(p.Name + e, wanted, StringComparison.OrdinalIgnoreCase)))
            .ToList();

        if (byName.Count == 1)
            return byName[0];

        if (byName.Count > 1)
        {
            throw new CodesysValidationException(
                $"Project name '{wanted}' is ambiguous; pass the full path instead: " +
                string.Join(", ", byName.Select(p => p.Path)));
        }

        throw new CodesysValidationException(
            $"Project '{wanted}' is not configured. Available: {Describe(projects)}.");
    }

    private static string Describe(IEnumerable<CodesysProject> projects) =>
        string.Join(", ", projects.Select(p => p.IsDefault ? $"{p.Name} (default)" : p.Name));

    /// <summary>File name without extension, splitting on both separators regardless of OS.</summary>
    public static string NameOf(string path)
    {
        var fileName = path.Trim().TrimEnd('\\', '/');
        var cut = fileName.LastIndexOfAny(['\\', '/']);
        if (cut >= 0)
            fileName = fileName[(cut + 1)..];

        var dot = fileName.LastIndexOf('.');
        return dot > 0 ? fileName[..dot] : fileName;
    }

    public static bool SamePath(string a, string b) =>
        string.Equals(Normalize(a), Normalize(b), StringComparison.OrdinalIgnoreCase);

    public static string Normalize(string path)
    {
        var trimmed = path.Trim();
        try
        {
            return Path.GetFullPath(trimmed).Replace('/', '\\');
        }
        catch (Exception)
        {
            return trimmed.Replace('/', '\\');
        }
    }
}
