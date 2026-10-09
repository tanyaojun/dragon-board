using System.Text.Json;

namespace DragonBoardLauncher;

internal sealed record SnapshotCollectorHealth(
    bool IsHealthy,
    string Fingerprint,
    string Message,
    bool Restartable = true)
{
    public static SnapshotCollectorHealth Healthy() => new(true, "healthy", "快照采集运行正常");

    public static SnapshotCollectorHealth Unhealthy(
        string fingerprint,
        string message,
        bool Restartable = true) =>
        new(false, fingerprint, message, Restartable);

    // 业务进度类告警（盘中长时间未采集等）：展示并记录日志，但不触发自动重启。
    // 漏槽/超时未采集是数据可用性问题，重启无法补采，还可能引发锁竞争和
    // 重启风暴（见 2026-08-05 快照采集启动异常复盘）。
    public static SnapshotCollectorHealth Warning(string fingerprint, string message) =>
        new(false, fingerprint, message, Restartable: false);
}

internal static class SnapshotCollectorProbe
{
    // 快照采集已迁移到独立 collector 进程（collector_main，8001），由 launcher
    // 作为核心启动项管理；健康检查跟随采集服务本身，不再依赖 Quant API(8000)。
    private static readonly Uri HealthUri = new("http://127.0.0.1:8001/api/health");

    /// <summary>启动失败标记文件（collector_main 锁冲突等失败时落盘）。</summary>
    private const string StartupFailureFileName = "collector-startup-failure.json";

    /// <summary>启动失败标记新鲜度窗口：超过该时长视为过期，不再据此抑制重启。</summary>
    private static readonly TimeSpan StartupFailureFreshWindow = TimeSpan.FromMinutes(10);

    /// <summary>
    /// 健康证据是否不可靠（P0-B 细化 + P1-C，2026-10-09 审计）：探针根本没读到
    /// 服务自报状态（超时/连接失败，fingerprint 前缀 probe:）。这类证据在交易
    /// 时段内推迟停启式重启（09-15 10:00 探针超时误杀健康实例的教训）。
    /// 服务自报的契约异常（fingerprint 为 hard:/http:/startup-failure:/等）是
    /// 可靠证据，随时允许修复性重启——调度器锁丢失自停（调度器未运行，
    /// restartable=true）依赖它盘中恢复，不能被交易窗推迟。
    /// </summary>
    public static bool IsUnreliableHealthEvidence(string fingerprint) =>
        !string.IsNullOrWhiteSpace(fingerprint) &&
        fingerprint.StartsWith("probe:", StringComparison.Ordinal);

    /// <summary>
    /// 是否为锁冲突启动失败标记（collector_main 写入的 wait 标记，fingerprint
    /// 前缀 startup-failure:）。P1-C 补充：该标记只应保护“正在等锁的活进程”；
    /// 调用方在 tracked 进程已退出后读到它时，应视为标记失效并立即重新拉起
    /// （旧锁 TTL ≤120s 早已过期，新实例等锁/清理不会双采）。
    /// </summary>
    public static bool IsLockWaitStartupFailureMarker(string fingerprint) =>
        !string.IsNullOrWhiteSpace(fingerprint) &&
        fingerprint.StartsWith("startup-failure:", StringComparison.Ordinal);

    public static async Task<SnapshotCollectorHealth> GetHealthAsync()
    {
        try
        {
            // 后端启动预热（akshare 资金流/行情缓存）期间健康检查可能瞬时超过 2s，
            // 收紧到 2s 会在启动窗口内误报"无法读取健康状态"；10s 覆盖预热尖峰。
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
            using var response = await client.GetAsync(HealthUri);
            if (!response.IsSuccessStatusCode)
            {
                return SnapshotCollectorHealth.Unhealthy(
                    $"http:{(int)response.StatusCode}",
                    $"快照采集错误: 采集服务(8001)健康检查返回 HTTP {(int)response.StatusCode}");
            }

            await using var stream = await response.Content.ReadAsStreamAsync();
            using var document = await JsonDocument.ParseAsync(stream);
            var root = document.RootElement;

            // 优先消费后端健康契约（status/restartable/recommendedAction/reason），
            // 不再解析 snapshotCollector 内部字段猜语义。
            var contract = ReadContract(root);
            if (contract is not null)
                return contract;

            // 兼容旧版 health（无契约字段）：回退到 snapshotCollector 内部字段解析。
            return ParseLegacySnapshotCollector(root);
        }
        catch (Exception ex)
        {
            // 8001 不可达：可能是锁冲突导致的启动失败（collector_main 已把原因落盘）。
            // 若存在新鲜的启动失败标记，按 restartable=false/wait 处理，不触发重启风暴。
            var failure = TryReadStartupFailure();
            if (failure is not null)
            {
                return failure;
            }

            return SnapshotCollectorHealth.Unhealthy(
                $"probe:{ex.GetType().Name}:{ex.Message}",
                $"快照采集错误: 无法读取采集服务(8001)健康状态: {ex.Message}");
        }
    }

    /// <summary>解析后端健康契约；不存在契约字段时返回 null（走旧版解析）。</summary>
    private static SnapshotCollectorHealth? ReadContract(JsonElement root)
    {
        if (!root.TryGetProperty("restartable", out var restartable) ||
            restartable.ValueKind != JsonValueKind.True &&
            restartable.ValueKind != JsonValueKind.False)
        {
            return null;
        }

        var canRestart = restartable.ValueKind == JsonValueKind.True;
        var action = ReadString(root, "recommendedAction") ?? "none";
        var reason = ReadString(root, "reason") ?? "";
        var status = ReadString(root, "status") ?? "ok";

        if (status == "ok") return SnapshotCollectorHealth.Healthy();
        if (!canRestart)
        {
            // 后端判定不可重启（锁冲突等待/数据源失败告警）：只展示，不触发自动重启。
            var fingerprint = $"no-restart:{action}:{reason}";
            return SnapshotCollectorHealth.Unhealthy(fingerprint, $"快照采集提示: {reason}", Restartable: false);
        }

        return SnapshotCollectorHealth.Unhealthy(
            $"hard:{status}:{action}:{reason}",
            $"快照采集错误: {reason}");
    }

    /// <summary>旧版 health（无契约字段）回退：按 snapshotCollector 内部字段解析。</summary>
    private static SnapshotCollectorHealth ParseLegacySnapshotCollector(JsonElement root)
    {
        if (!root.TryGetProperty("snapshotCollector", out var collector))
        {
            return SnapshotCollectorHealth.Unhealthy(
                "missing-status",
                "快照采集错误: 采集服务(8001)未返回 snapshotCollector 状态");
        }

        // 硬故障：调度器本身不可用，重启有实际意义。
        var issues = new List<string>();
        if (!ReadBoolean(collector, "enabled")) issues.Add("调度器未启用");
        if (!ReadBoolean(collector, "running")) issues.Add("调度任务未运行");

        var lastError = ReadString(collector, "last_error");
        if (!string.IsNullOrWhiteSpace(lastError)) issues.Add($"最近异常: {lastError}");
        if (issues.Count > 0)
        {
            var message = $"快照采集错误: {string.Join("；", issues)}";
            return SnapshotCollectorHealth.Unhealthy(
                $"hard:{string.Join("|", issues)}",
                message);
        }

        var isTradingDay = ReadBoolean(collector, "is_trading_day");
        var inSession = ReadBoolean(collector, "in_session");
        var tradingDate = ReadString(collector, "trading_date");

        var lastRunAt = ReadString(collector, "last_run_at");
        var hasCollected = !string.IsNullOrWhiteSpace(lastRunAt);
        DateTimeOffset? lastRunDt = null;
        if (DateTimeOffset.TryParse(lastRunAt, out var parsed))
            lastRunDt = parsed;

        if (!isTradingDay) return SnapshotCollectorHealth.Healthy();
        if (!hasCollected && inSession) return SnapshotCollectorHealth.Healthy();

        var warnings = new List<string>();
        if (!hasCollected && !inSession)
        {
            // 交易日已收盘，但还未采集——可能刚启动
            if (tradingDate is { Length: > 0 })
                warnings.Add($"交易日 {tradingDate} 已收盘，但尚无采集记录");
        }

        if (lastRunDt.HasValue)
        {
            var elapsed = DateTimeOffset.Now - lastRunDt.Value;
            if (inSession && elapsed > TimeSpan.FromHours(2))
                warnings.Add($"最近采集于 {lastRunDt:yyyy-MM-dd HH:mm:ss}，超过2小时未执行");
        }

        if (warnings.Count == 0) return SnapshotCollectorHealth.Healthy();

        var warningMessage = $"快照采集提示: {string.Join("；", warnings)}";
        return SnapshotCollectorHealth.Warning(
            $"warn:{string.Join("|", warnings)}",
            warningMessage);
    }

    /// <summary>读取 collector_main 启动失败标记（8001 不可达/端口未开时的兜底依据）。
    /// 返回 null 表示无新鲜失败标记。</summary>
    public static SnapshotCollectorHealth? TryReadStartupFailure()
    {
        try
        {
            var root = ProjectRootLocator.Find();
            if (string.IsNullOrWhiteSpace(root)) return null;

            var path = Path.Combine(root, "logs", StartupFailureFileName);
            if (!File.Exists(path)) return null;

            var info = new FileInfo(path);
            if (DateTimeOffset.UtcNow - info.LastWriteTimeUtc > StartupFailureFreshWindow)
                return null;

            using var document = JsonDocument.Parse(File.ReadAllText(path));
            var element = document.RootElement;
            var reason = ReadString(element, "reason") ?? "collector 启动失败";
            var action = ReadString(element, "recommendedAction") ?? "wait";
            return SnapshotCollectorHealth.Unhealthy(
                $"startup-failure:{action}",
                $"快照采集提示: {reason}",
                Restartable: false);
        }
        catch
        {
            return null;
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
