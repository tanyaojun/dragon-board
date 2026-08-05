namespace DragonBoardLauncher.Core;

/// <summary>
/// 服务自动重启策略（无 UI 依赖，可单测）。
///
/// 防重启风暴规则：
/// - 冷却：同一服务两次重启之间至少间隔 <see cref="CooldownSeconds"/> 秒；
/// - 上限：同一服务连续失败达到 <see cref="MaxConsecutive"/> 次后暂停，直到恢复健康；
/// - 指数退避：连续失败时等待时间按 1s→2s→4s→…→上限 <see cref="MaxBackoffSeconds"/> 增长，
///   叠加在固定冷却之上；
/// - 防并发：全局同一时刻至多允许一个"实际重启动作"（由调用方配合执行）。
/// 恢复健康（<see cref="Reset"/>）时清零失败计数。
/// </summary>
internal sealed class RestartPolicy
{
    private readonly TimeSpan _cooldown;
    private readonly int _maxConsecutive;
    private readonly TimeSpan _maxBackoff;

    private readonly Dictionary<string, DateTime> _lastRestartUtc = new(StringComparer.Ordinal);
    private readonly Dictionary<string, int> _failures = new(StringComparer.Ordinal);

    public RestartPolicy(
        TimeSpan? cooldown = null,
        int? maxConsecutive = null,
        TimeSpan? maxBackoff = null)
    {
        _cooldown = cooldown ?? TimeSpan.FromSeconds(60);
        _maxConsecutive = maxConsecutive ?? 3;
        _maxBackoff = maxBackoff ?? TimeSpan.FromSeconds(60);
    }

    /// <summary>当前是否允许对指定服务执行重启。不允许时返回 false 并给出稳定原因
    /// （不随时间变化的静态描述，供调用方去重；动态信息由 <see cref="DescribeBlock"/> 单独给出）。</summary>
    public bool TryRequestRestart(string key, out string? blockReason)
    {
        var now = DateTime.UtcNow;

        if (_failures.TryGetValue(key, out var failures) && failures >= _maxConsecutive)
        {
            blockReason = $"{key} 连续失败 {_maxConsecutive} 次，暂停自动重启";
            return false;
        }

        if (_lastRestartUtc.TryGetValue(key, out var last))
        {
            var wait = _cooldown + ComputeBackoff(key);
            if (now - last < wait)
            {
                blockReason = $"{key} 重启冷却中";
                return false;
            }
        }

        blockReason = null;
        return true;
    }

    /// <summary>冷却/退避的动态细节（供日志展示，不参与去重比较）。</summary>
    public string DescribeBlock(string key)
    {
        if (_lastRestartUtc.TryGetValue(key, out var last))
        {
            var wait = _cooldown + ComputeBackoff(key);
            var elapsed = DateTime.UtcNow - last;
            if (elapsed < wait)
            {
                var failures = _failures.GetValueOrDefault(key);
                return $"距上次重启 {elapsed.TotalSeconds:F0}s，还需 {(wait - elapsed).TotalSeconds:F0}s" +
                       (failures > 0 ? $"（连续失败 {failures} 次，退避中）" : "");
            }
        }
        return "";
    }

    /// <summary>记录一次重启（由调用方在真正启动服务前调用）。</summary>
    public void RecordRestart(string key)
    {
        _lastRestartUtc[key] = DateTime.UtcNow;
        _failures[key] = _failures.GetValueOrDefault(key) + 1;
    }

    /// <summary>服务恢复健康：清零失败计数并清除冷却时间（恢复后允许立即重启）。</summary>
    public void Reset(string key)
    {
        _failures[key] = 0;
        _lastRestartUtc.Remove(key);
    }

    private TimeSpan ComputeBackoff(string key)
    {
        var failures = Math.Max(0, _failures.GetValueOrDefault(key));
        var seconds = Math.Min(
            _maxBackoff.TotalSeconds,
            Math.Pow(2, Math.Max(0, failures - 1))); // 1,2,4,8,...
        return TimeSpan.FromSeconds(seconds);
    }
}
