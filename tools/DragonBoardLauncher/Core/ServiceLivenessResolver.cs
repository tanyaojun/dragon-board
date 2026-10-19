namespace DragonBoardLauncher.Core;

/// <summary>
/// 通用服务存活判定（无 UI/无 IO 依赖，可单测）：端口探测是启发式，会让"活着但在忙"
/// 的服务假阴性，本类用"强证据 + 深探测复核"兜住。
///
/// 规则：
/// - 端口探测说在跑 → 在跑；
/// - 端口探测说没跑，但存在"它本该在跑"的强证据（跟踪的子进程仍存活，或本会话曾
///   观察到它确实在跑）→ 用更长超时深探测复核一次；
/// - 深探测也失败 → 认死（随后由启动/清理路径处理）。
///
/// 2026-10-19 复盘（用户反馈 3000/8000/8008/32145 盘中"掉线又自动恢复"）：<br/>
/// ① 显示层：<c>IsPortOpen</c> = TCP 表 + 500ms 连接探测，机器负载高或 Windows TCP 表
/// 损坏时，活着的服务被连续判成"已停止"，UI 红点/在线数抖动，3 秒后自己又变"运行中"
/// —— 这正是"掉线又自动恢复"的直接来源；<br/>
/// ② 真实伤害：假阴性会让"启动"按钮变可点，用户点下去时服务其实活着，新实例绑不上
/// 端口，<c>[Errno 10048]</c> 自杀（10-14 13:37:26 量化后端 API 实证）。
/// </summary>
internal static class ServiceLivenessResolver
{
    /// <param name="probeSaysRunning">快速端口探测结果（TCP 表 + 短超时连接）。</param>
    /// <param name="strongEvidenceAlive">是否有"本该在跑"的强证据（跟踪进程存活 / 本会话见过它运行）。</param>
    /// <param name="deepProbe">深探测（更长超时的连接探测或服务健康契约）。</param>
    public static bool IsRunning(
        bool probeSaysRunning,
        bool strongEvidenceAlive,
        Func<bool> deepProbe) =>
        probeSaysRunning || (strongEvidenceAlive && deepProbe());
}