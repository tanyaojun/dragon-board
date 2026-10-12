namespace DragonBoardLauncher.Core;

/// <summary>
/// 同一服务最小拉起间隔节流（无 UI 依赖，可单测）。
///
/// _starting 并发守卫只挡同时进行中的启动，挡不住秒级连发：用户连点"启动"、
/// 修复性重启与锁等待重拉路径叠加时，会在数秒内拉起多个 collector 等锁实例；
/// 每个实例空转等锁后 RuntimeError 自杀，喂大连续失败计数直至触发重启熔断
/// （2026-10-12 复盘：11:32 三连发、11:34 双发、11:36 熔断）。
///
/// 规则：成功拉起后 MinInterval 内拒绝再次拉起；被节流实例退出（Exited）或
/// 显式停止（Stop）即清除节流——"进程已不在"时再拉永远是安全的。
/// </summary>
internal sealed class StartThrottle
{
    private readonly TimeSpan _minInterval;
    private readonly Dictionary<string, DateTime> _lastStartUtc = new(StringComparer.Ordinal);

    public StartThrottle(TimeSpan? minInterval = null)
    {
        _minInterval = minInterval ?? TimeSpan.FromSeconds(15);
    }

    /// <summary>是否允许立即拉起该服务；允许时记入节流窗口。</summary>
    public bool TryAcquire(string key)
    {
        var now = DateTime.UtcNow;
        if (_lastStartUtc.TryGetValue(key, out var last) && now - last < _minInterval)
            return false;
        _lastStartUtc[key] = now;
        return true;
    }

    /// <summary>进程退出/显式停止后清除节流：停止→再启动永远放行。</summary>
    public void Reset(string key) => _lastStartUtc.Remove(key);
}
