using System.IO.Compression;
using System.Text;

namespace DragonBoardLauncher;

/// <summary>
/// 启动器本地日志落盘：按天分文件（logs\launcher\launcher-YYYY-MM-dd.log），
/// 追加写入、线程安全、自动清理 30 天前的旧文件。保存 UI 与子进程全量输出，
/// 便于排查采集服务/API 停摆类问题（内存缓冲会随窗口关闭丢失）。
/// 单文件超过 MaxLogBytes 后自动轮转并 gzip 压缩为 launcher-YYYY-MM-dd.N.log.gz，
/// 避免高频访问日志把单日文件撑到数百 MB。
/// </summary>
internal static class LogFile
{
    private const int MaxDays = 30;
    private const long MaxLogBytes = 10 * 1024 * 1024; // 单文件 10MB 轮转

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
                RotateIfNeeded();
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

    /// <summary>
    /// 单文件超过 MaxLogBytes 时轮转：关闭当前写入器，把当天 .log 压缩为
    /// launcher-YYYY-MM-dd.N.log.gz（序号递增），删除原文件，下次 Append 重建新文件。
    /// 压缩失败或删除失败都不阻塞后续写入（保留原文件继续追加）。
    /// </summary>
    private static void RotateIfNeeded()
    {
        var root = _root;
        var today = _currentDate;
        if (string.IsNullOrWhiteSpace(root) || today is null) return;

        try
        {
            var dir = Path.Combine(root, "logs", "launcher");
            var path = Path.Combine(dir, $"launcher-{today}.log");
            var info = new FileInfo(path);
            if (!info.Exists || info.Length < MaxLogBytes) return;

            _writer?.Dispose();
            _writer = null;
            _currentDate = null;

            var index = 1;
            while (File.Exists(Path.Combine(dir, $"launcher-{today}.{index}.log.gz")))
                index++;

            var archive = Path.Combine(dir, $"launcher-{today}.{index}.log.gz");
            using (var input = File.OpenRead(path))
            using (var output = File.Create(archive))
            using (var gzip = new GZipStream(output, CompressionLevel.SmallestSize))
                input.CopyTo(gzip);
            File.Delete(path);
        }
        catch
        {
            // 轮转失败不阻塞后续写入
        }
    }

    private static void CleanupOldFiles(string dir)
    {
        try
        {
            var cutoff = DateTime.Today.AddDays(-MaxDays);
            foreach (var file in Directory.EnumerateFiles(dir, "launcher-*.log*"))
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
