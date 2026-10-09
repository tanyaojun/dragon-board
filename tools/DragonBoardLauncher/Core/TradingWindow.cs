namespace DragonBoardLauncher.Core;

/// <summary>
/// A 股连续交易时段窗口（无 UI 依赖，可单测）。
///
/// 用途（2026-10-09 审计 P0-B）：交易时段内禁止 launcher 对「仍在监听但健康异常」
/// 的实例执行停启式重启——09-15 10:00 健康探针 10 秒超时误杀健康采集服务，
/// 恰逢采集时点，代价是 10:30 槽位丢失。窗口内只允许拉起已死（端口关闭）的服务。
/// 窗口取 09:15（集合竞价缓冲）~ 15:10（收盘后 10 分钟缓冲），全周生效：
/// 非交易日推修复只是保守延迟，无害；不引入交易日历依赖。
/// </summary>
internal static class TradingWindow
{
    public static readonly TimeSpan Start = new(9, 15, 0);
    public static readonly TimeSpan End = new(15, 10, 0);

    public static bool IsInside(TimeSpan timeOfDay) => timeOfDay >= Start && timeOfDay <= End;

    public static bool IsInsideNow() => IsInside(DateTime.Now.TimeOfDay);
}
