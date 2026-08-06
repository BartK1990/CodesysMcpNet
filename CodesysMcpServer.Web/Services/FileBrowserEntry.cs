namespace CodesysMcpServer.Web.Services;

/// <summary>One row in a <see cref="FileBrowserListing"/>: a drive, folder, or file.</summary>
public sealed record FileBrowserEntry(string Name, string FullPath, bool IsDirectory);

/// <summary>
/// Response of <see cref="FileBrowserService.List"/>. <see cref="Path"/> is null at the
/// drive list (the picker's root); <see cref="Parent"/> is null when there's nowhere to go
/// up to — the drive list itself, or a drive root.
/// </summary>
public sealed record FileBrowserListing(string? Path, string? Parent, IReadOnlyList<FileBrowserEntry> Entries);
