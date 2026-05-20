namespace YiDongJingLing.Blocks;

public sealed record BlockFileInfo(
    string Name,
    string Path,
    long Length,
    DateTime LastWriteTime,
    int StockCount,
    int IssueCount);

public sealed class BlockFileScanner
{
    private readonly BlockFileParser _parser = new();

    public IReadOnlyList<BlockFileInfo> Scan(string directory)
    {
        if (!Directory.Exists(directory)) return Array.Empty<BlockFileInfo>();

        return Directory
            .EnumerateFiles(directory, "*.blk", SearchOption.TopDirectoryOnly)
            .OrderBy(path => Path.GetFileName(path), StringComparer.OrdinalIgnoreCase)
            .Select(BuildInfo)
            .ToArray();
    }

    private BlockFileInfo BuildInfo(string path)
    {
        var file = new FileInfo(path);
        var result = _parser.ParseFile(path);
        return new BlockFileInfo(
            file.Name,
            file.FullName,
            file.Length,
            file.LastWriteTime,
            result.Codes.Count,
            result.Issues.Count);
    }
}
