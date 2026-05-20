namespace YiDongJingLing;

public static class ProjectRootLocator
{
    public static string Find()
    {
        var dir = AppContext.BaseDirectory;
        while (!string.IsNullOrWhiteSpace(dir))
        {
            if (File.Exists(Path.Combine(dir, "package.json")) &&
                Directory.Exists(Path.Combine(dir, "python-bridge")))
                return dir.TrimEnd(Path.DirectorySeparatorChar);

            var parent = Directory.GetParent(dir);
            if (parent == null) break;
            dir = parent.FullName;
        }

        return Directory.GetCurrentDirectory();
    }
}
