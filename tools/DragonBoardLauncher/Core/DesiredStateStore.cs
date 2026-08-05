using System.Text.Json;

namespace DragonBoardLauncher.Core;

/// <summary>
/// 用户启停偏好持久化（P1.2）：记录哪些展示/辅助服务应随启动器恢复。
///
/// 存储位置：%LOCALAPPDATA%\DragonBoardLauncher\state.json（用户态，跨仓库安全）。
/// 语义：核心服务（mongo/redis/proxy/bridge/quant-api/collector）总是随 StartAll 启动，
/// 本文件只记录"用户显式启动过"的展示/辅助服务（frontend/quant-ui/voice），
/// launcher 重启后按此恢复，避免用户手动停掉的服务被无条件重新拉起。
/// </summary>
internal sealed class DesiredStateStore
{
    private readonly string _path;

    public DesiredStateStore(string? root = null)
    {
        var baseDir = root ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "DragonBoardLauncher");
        Directory.CreateDirectory(baseDir);
        _path = Path.Combine(baseDir, "state.json");
    }

    public string FilePath => _path;

    /// <summary>读取已启用（用户显式启动过）的服务 key 集合；无文件返回空集。</summary>
    public HashSet<string> LoadEnabled()
    {
        try
        {
            if (!File.Exists(_path)) return new HashSet<string>(StringComparer.Ordinal);

            using var document = JsonDocument.Parse(File.ReadAllText(_path));
            var root = document.RootElement;
            if (!root.TryGetProperty("enabled", out var enabled) ||
                enabled.ValueKind != JsonValueKind.Array)
            {
                return new HashSet<string>(StringComparer.Ordinal);
            }

            var result = new HashSet<string>(StringComparer.Ordinal);
            foreach (var item in enabled.EnumerateArray())
            {
                if (item.ValueKind == JsonValueKind.String)
                {
                    var key = item.GetString();
                    if (!string.IsNullOrWhiteSpace(key)) result.Add(key);
                }
            }
            return result;
        }
        catch
        {
            return new HashSet<string>(StringComparer.Ordinal);
        }
    }

    /// <summary>持久化指定服务 key 的启用状态（原子写：临时文件 + 替换）。</summary>
    public void SaveEnabled(IEnumerable<string> keys)
    {
        try
        {
            var payload = new
            {
                enabled = keys.OrderBy(k => k, StringComparer.Ordinal).ToArray(),
                updatedAt = DateTimeOffset.Now.ToString("o")
            };
            var temp = _path + ".tmp";
            File.WriteAllText(temp, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }));
            File.Move(temp, _path, overwrite: true);
        }
        catch
        {
            // 持久化失败不影响启动器功能
        }
    }
}
