using System.Text.Json;

namespace DragonBoardLauncher;

internal sealed record SnapshotCollectorHealth(bool IsHealthy, string Fingerprint, string Message)
{
    public static SnapshotCollectorHealth Healthy() => new(true, "healthy", "快照采集运行正常");

    public static SnapshotCollectorHealth Unhealthy(string fingerprint, string message) =>
        new(false, fingerprint, message);
}

internal static class SnapshotCollectorProbe
{
    private static readonly Uri HealthUri = new("http://127.0.0.1:8000/api/health");

    public static async Task<SnapshotCollectorHealth> GetHealthAsync()
    {
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
            using var response = await client.GetAsync(HealthUri);
            if (!response.IsSuccessStatusCode)
            {
                return SnapshotCollectorHealth.Unhealthy(
                    $"http:{(int)response.StatusCode}",
                    $"快照采集错误: Quant API 健康检查返回 HTTP {(int)response.StatusCode}");
            }

            await using var stream = await response.Content.ReadAsStreamAsync();
            using var document = await JsonDocument.ParseAsync(stream);
            if (!document.RootElement.TryGetProperty("snapshotCollector", out var collector))
            {
                return SnapshotCollectorHealth.Unhealthy(
                    "missing-status",
                    "快照采集错误: Quant API 未返回 snapshotCollector 状态");
            }

            var issues = new List<string>();
            if (!ReadBoolean(collector, "enabled")) issues.Add("调度器未启用");
            if (!ReadBoolean(collector, "running")) issues.Add("调度任务未运行");

            var lastError = ReadString(collector, "last_error");
            if (!string.IsNullOrWhiteSpace(lastError)) issues.Add($"最近异常: {lastError}");

            var missingSlots = ReadStrings(collector, "overdue_missing_slots");
            if (missingSlots.Count > 0)
                issues.Add($"逾期缺失槽位({missingSlots.Count}): {string.Join(", ", missingSlots)}");

            var lastPollAt = ReadString(collector, "last_poll_at");
            var pollSeconds = ReadDouble(collector, "poll_seconds", 1);
            if (DateTimeOffset.TryParse(lastPollAt, out var lastPoll))
            {
                var staleAfter = TimeSpan.FromSeconds(Math.Max(15, pollSeconds * 10));
                if (DateTimeOffset.Now - lastPoll > staleAfter)
                    issues.Add($"调度心跳已停止: {lastPoll:yyyy-MM-dd HH:mm:ss}");
            }
            else if (ReadBoolean(collector, "running"))
            {
                issues.Add("调度器没有轮询心跳");
            }

            if (issues.Count == 0) return SnapshotCollectorHealth.Healthy();

            var message = $"快照采集错误: {string.Join("；", issues)}";
            return SnapshotCollectorHealth.Unhealthy(message, message);
        }
        catch (Exception ex)
        {
            return SnapshotCollectorHealth.Unhealthy(
                $"probe:{ex.GetType().Name}:{ex.Message}",
                $"快照采集错误: 无法读取 Quant API 健康状态: {ex.Message}");
        }
    }

    private static bool ReadBoolean(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.True;

    private static string? ReadString(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static double ReadDouble(JsonElement element, string name, double fallback) =>
        element.TryGetProperty(name, out var value) && value.TryGetDouble(out var number)
            ? number
            : fallback;

    private static List<string> ReadStrings(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind != JsonValueKind.Array)
            return [];

        return value.EnumerateArray()
            .Where(item => item.ValueKind == JsonValueKind.String)
            .Select(item => item.GetString())
            .Where(item => !string.IsNullOrWhiteSpace(item))
            .Cast<string>()
            .ToList();
    }
}
