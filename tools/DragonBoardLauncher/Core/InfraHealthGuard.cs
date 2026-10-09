namespace DragonBoardLauncher.Core;

/// <summary>基础设施存活守护决策：是否应拉起、以及需要记录的一次性日志。</summary>
internal sealed record InfraHealthDecision(bool ShouldRestart, string? LogMessage);

/// <summary>
/// 基础设施服务（MongoDB/Redis）存活守护内核（无 UI 依赖，可单测）。
///
/// 背景（2026-10-09 日志审计 P0-A）：mongo/redis 盘中静默死亡后 launcher 不会
/// 自动拉起，09-22 曾 45 分钟无库（含收盘采集窗），且两者多次同秒双死。
///
/// 规则：
/// - 可达（端口连接探测，已含 TCP 表损坏回退）：视为在线，清零公告状态；
/// - 不可达：视为进程死亡，应拉起（直接 StartService，不杀任何进程，交易时段
///   内也允许；外部实例占端口时可达，不会进入此分支，refuse/reuse 语义不变）；
/// - 同一服务离线只公告一次，恢复在线时公告一次，避免 3 秒轮询刷日志。
/// 用户手动停止的意图由调用方过滤（与 collector 自动重启一致）。
/// 冷却/连续失败上限/指数退避由调用方配合 RestartPolicy 执行。
/// </summary>
internal sealed class InfraHealthGuard
{
    private readonly HashSet<string> _offlineAnnounced = new(StringComparer.Ordinal);

    public InfraHealthDecision Evaluate(string key, string displayName, bool reachable)
    {
        if (reachable)
        {
            if (_offlineAnnounced.Remove(key))
                return new InfraHealthDecision(false, $"{displayName} 已恢复在线（存活守护）。");
            return new InfraHealthDecision(false, null);
        }

        if (_offlineAnnounced.Add(key))
            return new InfraHealthDecision(true, $"{displayName} 离线，存活守护将自动拉起。");
        return new InfraHealthDecision(true, null);
    }
}
