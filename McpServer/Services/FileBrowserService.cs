namespace McpServer.Services;

/// <summary>
/// Backs the settings page's "Browse…" path picker (<c>GET /files</c>). Browsers never expose
/// the true absolute path of a file picked through <c>&lt;input type="file"&gt;</c>, so instead
/// of a native OS dialog the page drives a small in-page file explorer over this listing API —
/// the server already has full local filesystem access, so it can just walk directories itself.
/// </summary>
public sealed class FileBrowserService
{
    public FileBrowserListing List(string? path, string? extensionFilter)
    {
        if (string.IsNullOrWhiteSpace(path))
            return ListDrives();

        if (!Directory.Exists(path))
            throw new CodesysValidationException($"Directory not found: {path}");

        var entries = new List<FileBrowserEntry>();

        try
        {
            foreach (var dir in Directory.EnumerateDirectories(path))
                entries.Add(new FileBrowserEntry(System.IO.Path.GetFileName(dir), dir, IsDirectory: true));

            foreach (var file in Directory.EnumerateFiles(path))
            {
                if (extensionFilter is not null &&
                    !file.EndsWith(extensionFilter, StringComparison.OrdinalIgnoreCase))
                    continue;

                entries.Add(new FileBrowserEntry(System.IO.Path.GetFileName(file), file, IsDirectory: false));
            }
        }
        catch (UnauthorizedAccessException)
        {
            throw new CodesysValidationException($"Access denied: {path}");
        }

        entries.Sort((a, b) => a.IsDirectory != b.IsDirectory
            ? (a.IsDirectory ? -1 : 1)
            : string.Compare(a.Name, b.Name, StringComparison.OrdinalIgnoreCase));

        var normalizedRoot = System.IO.Path.GetPathRoot(path);
        var isDriveRoot = string.Equals(normalizedRoot, path, StringComparison.OrdinalIgnoreCase);
        var parent = isDriveRoot ? null : Directory.GetParent(path)?.FullName;

        return new FileBrowserListing(path, parent, entries);
    }

    private static FileBrowserListing ListDrives()
    {
        var entries = DriveInfo.GetDrives()
            .Where(d => d.IsReady)
            .Select(d => new FileBrowserEntry(d.Name, d.Name, IsDirectory: true))
            .ToList();

        return new FileBrowserListing(Path: null, Parent: null, entries);
    }
}
