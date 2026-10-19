namespace DragonBoardLauncher.Core;

/// <summary>
/// 采集服务存活判定（无 UI 依赖，可单测）：把端口探测与 8001 HTTP 健康契约合并。
///
/// 规则：
/// - 端口探测说在跑 → 在跑；
/// - 端口探测假阴性但 HTTP 契约自报成功（<see cref="SnapshotCollectorHealth.HttpReached"/>）
///   → 仍在跑（能连上 8001 就证明端口在听）；
/// - 两者都拿不到 → 离线，交给离线重启路径拉起。
///
/// 2026-10-19 复盘：旧实现以端口探测做门禁，TCP 表损坏（LISTENING 行缺失）叠加线程池
/// 争用时会对活着的 8001 连续假阴性，被当成"离线"触发停启式重启，打断采集链并留下
/// 残留锁（等锁实例随后 RuntimeError 自杀）。
/// </summary>
internal static class CollectorStatusResolver
{
    public static bool IsRunning(bool portProbeSaysRunning, SnapshotCollectorHealth health) =>
        portProbeSaysRunning || health.HttpReached;
}
