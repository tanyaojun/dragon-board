using System.Text;

namespace DragonBoardLauncher;

/// <summary>
/// 启动器本地日志落盘：按天分文件（logs\launcher\launcher-YYYY-MM-dd.log），
/// 追加写入、线程安全、自动清理 30 天前的旧文件。保存 UI 与子进程全量输出，
/// 便于排查采集服务/API 停摆类问题（内存缓冲会随窗口关闭丢失）。
/// </summary>
internal static class LogFile
{
    private const int MaxDays = 30;

    private static readonly object Sync = new();
    private static string? _root;
    private static string? _currentDate;
    private static StreamWriter? _writer;

    public static void Initialize(string root)
    {
        lock (Sync)
        {
            _root = root;
            _currentDate = null;
            _writer?.Dispose();
            _writer = null;
        }
    }

    public static void Append(string line)
    {
        lock (Sync)
        {
            var writer = GetWriter();
            if (writer is null) return;
            try
            {
                writer.WriteLine(line);
            }
            catch
            {
                // 磁盘异常不阻塞启动器功能
            }
        }
    }

    public static string CurrentLogPath()
    {
        lock (Sync)
        {
            var root = _root;
            if (string.IsNullOrWhiteSpace(root)) return "";
            return Path.Combine(root, "logs", "launcher", $"launcher-{DateTime.Now:yyyy-MM-dd}.log");
        }
    }

    private static StreamWriter? GetWriter()
    {
        var root = _root;
        if (string.IsNullOrWhiteSpace(root)) return null;

        var today = DateTime.Now.ToString("yyyy-MM-dd");
        if (_writer is not null && _currentDate == today) return _writer;

        _writer?.Dispose();
        _writer = null;
        _currentDate = null;
        try
        {
            var dir = Path.Combine(root, "logs", "launcher");
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, $"launcher-{today}.log");
            _writer = new StreamWriter(path, append: true, Encoding.UTF8) { AutoFlush = true };
            _currentDate = today;
            CleanupOldFiles(dir);
        }
        catch
        {
            _writer = null;
        }
        return _writer;
    }

    private static void CleanupOldFiles(string dir)
    {
        try
        {
            var cutoff = DateTime.Today.AddDays(-MaxDays);
            foreach (var file in Directory.EnumerateFiles(dir, "launcher-*.log"))
            {
                if (File.GetLastWriteTime(file) < cutoff)
                    File.Delete(file);
            }
        }
        catch
        {
        }
    }
}
