namespace DragonBoardLauncher.Core;

/// <summary>
/// 采集服务健康决策结果：由 <see cref="CollectorHealthGuard.Evaluate"/> 产出，
/// 供 UI 层执行（重启由调用方配合冷却/上限策略执行）。
/// </summary>
internal sealed record CollectorHealthDecision(
    bool ShouldRestart,      // 是否应触发自动重启（已通过防抖与 Restartable 判定）
    bool CollectFailed,      // 是否应显示"采集异常"状态
    string? LogMessage);     // 需要写入日志的消息（状态变化时非空）

/// <summary>
/// 采集服务健康决策内核（无 UI 依赖，可单测）。
///
/// 职责：把一次健康轮询结果转换为"是否重启 / 是否标红 / 是否记日志"的决策。
/// 规则（与 LauncherForm 原逻辑等价，2026-08-05 复盘后强化）：
/// - 健康：恢复日志，重置防抖与异常标记；
/// - 运行中但不健康且后端判定可重启（Restartable=true）：同一 fingerprint 连续 2 次
///   轮询确认后才判失败（防抖），触发重启；消息只在 fingerprint 变化时记录一次；
/// - 运行中但不健康且后端判定不可重启（锁冲突 wait / 数据源失败 alert）：只展示与
///   记录，不触发重启（避免"漏槽→杀进程→锁竞争"死循环）；
/// - 服务离线（health 为 null）：由调用方按"未运行需拉起"处理，本类不拦截。
/// </summary>
internal sealed class CollectorHealthGuard
{
    private string _lastFingerprint = "";
    private string _pendingFingerprint = "";
    private int _pendingCount;
    private bool _wasUnhealthy;

    public CollectorHealthDecision Evaluate(SnapshotCollectorHealth? health)
    {
        if (health is null)
        {
            // 采集服务未运行/探针不可用：交给调用方按 offline 策略处理（通常需启动）。
            return new CollectorHealthDecision(ShouldRestart: true, CollectFailed: true, LogMessage: null);
        }

        if (health.IsHealthy)
        {
            var restored = _wasUnhealthy;
            _pendingFingerprint = "";
            _pendingCount = 0;
            _wasUnhealthy = false;
            _lastFingerprint = health.Fingerprint;
            return new CollectorHealthDecision(
                ShouldRestart: false,
                CollectFailed: false,
                LogMessage: restored ? "快照采集恢复正常：调度器心跳和槽位完整性检查均通过。" : null);
        }

        // 不健康。
        var fingerprint = health.Fingerprint;

        // 后端判定不可重启：锁冲突等待 / 数据源失败告警，只展示不重启。
        if (!health.Restartable)
        {
            var message = fingerprint != _lastFingerprint ? health.Message : null;
            _lastFingerprint = fingerprint;
            _wasUnhealthy = true;
            return new CollectorHealthDecision(
                ShouldRestart: false,
                CollectFailed: true,
                LogMessage: message);
        }

        // 可重启：同一 fingerprint 连续 2 次轮询确认（防抖），避免瞬时抖动误杀。
        if (fingerprint != _pendingFingerprint)
        {
            _pendingFingerprint = fingerprint;
            _pendingCount = 1;
            return new CollectorHealthDecision(ShouldRestart: false, CollectFailed: _wasUnhealthy, LogMessage: null);
        }

        _pendingCount++;
        if (_pendingCount < 2)
            return new CollectorHealthDecision(ShouldRestart: false, CollectFailed: _wasUnhealthy, LogMessage: null);

        var isNew = fingerprint != _lastFingerprint;
        _wasUnhealthy = true;
        _lastFingerprint = fingerprint;
        return new CollectorHealthDecision(
            ShouldRestart: true,
            CollectFailed: true,
            LogMessage: isNew ? health.Message : null);
    }
}
