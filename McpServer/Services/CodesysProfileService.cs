namespace McpServer.Services;

/// <summary>
/// Backs the settings page's profile picker (<c>GET /profiles</c>). The name passed to
/// <c>CODESYS.exe --profile=</c> must exactly match a version profile installed alongside that
/// executable — a free-text field invites the exact kind of typo/mismatch that makes
/// <c>--noUI</c> runs fail with "you must specify a profile". Each install registers its own
/// profile(s) as <c>*.profile</c> / <c>*.profile.xml</c> files directly under
/// <c>&lt;install&gt;\Profiles</c> (sibling of the <c>Common</c> folder containing CODESYS.exe).
/// The <c>Profiles\Informational</c> subfolder holds definitions for older versions kept around
/// for backward-compatible project loading only — CODESYS rejects those if passed to --profile,
/// so it is deliberately not scanned here.
/// </summary>
public sealed class CodesysProfileService
{
    public IReadOnlyList<CodesysProfileEntry> List(string executablePath)
    {
        if (string.IsNullOrWhiteSpace(executablePath))
            throw new CodesysValidationException("executablePath is required.");

        var commonDir = Path.GetDirectoryName(executablePath);
        var installDir = commonDir is null ? null : Path.GetDirectoryName(commonDir);

        if (installDir is null)
            throw new CodesysValidationException($"Could not resolve an install directory from: {executablePath}");

        var profilesDir = Path.Combine(installDir, "Profiles");

        if (!Directory.Exists(profilesDir))
            throw new CodesysValidationException($"Profiles folder not found: {profilesDir}");

        var names = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var file in Directory.EnumerateFiles(profilesDir))
        {
            var name = ProfileNameFromFileName(Path.GetFileName(file));
            if (name is not null)
                names.Add(name);
        }

        return names.Select(n => new CodesysProfileEntry(n)).ToList();
    }

    private static string? ProfileNameFromFileName(string fileName)
    {
        if (fileName.EndsWith(".profile.xml", StringComparison.OrdinalIgnoreCase))
            return fileName[..^".profile.xml".Length];

        if (fileName.EndsWith(".profile", StringComparison.OrdinalIgnoreCase))
            return fileName[..^".profile".Length];

        return null;
    }
}
