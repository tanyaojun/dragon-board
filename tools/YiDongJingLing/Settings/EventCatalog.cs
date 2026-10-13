using YiDongJingLing.Events;

namespace YiDongJingLing.Settings;

public sealed record EventCatalogEntry(L1EventType Type, string Label, string Note, bool DefaultVoice);

/// <summary>
/// 异动事件目录：全部事件类型的中文名/说明/默认语音开关的单一事实源。
/// SettingsForm 的启用/语音勾选与默认强信号集合都从这里取，避免枚举新增后 UI 漏项。
/// </summary>
public static class EventCatalog
{
    public static IReadOnlyList<EventCatalogEntry> Entries { get; } =
    [
        new(L1EventType.LimitUpSealed, "封涨停板", "涨停价+买一封单", true),
        new(L1EventType.LimitUpOpened, "打开涨停板", "跌离涨停封单", true),
        new(L1EventType.UpcomingLimitUpOpen, "即将打开涨停", "买一封单骤降", true),
        new(L1EventType.NearLimitUp, "逼近涨停", "距涨停1%内", true),
        new(L1EventType.LimitDownSealed, "封跌停板", "跌停价+卖一封单", true),
        new(L1EventType.LimitDownOpened, "打开跌停板", "脱离跌停封单", true),
        new(L1EventType.UpcomingLimitDownOpen, "即将打开跌停", "卖一封单骤降", true),
        new(L1EventType.NearLimitDown, "逼近跌停", "距跌停1%内", true),
        new(L1EventType.LimitUpResealed, "涨停回封", "打开后重新封回", true),
        new(L1EventType.SealOrderIncreased, "封单增强", "封单较前帧增50%", true),
        new(L1EventType.SealOrderWeakened, "封单变弱", "封单较前帧减半", true),
        new(L1EventType.BigRiseTier, "大幅拉升", "当日涨幅破阈值", true),
        new(L1EventType.BigDropTier, "大幅跳水", "当日跌幅破阈值", true),
        new(L1EventType.FastRise, "快速拉升", "30/60秒或5分钟急涨", true),
        new(L1EventType.FastDrop, "快速跳水", "30/60秒或5分钟急跌", true),
        new(L1EventType.OpeningWeakToStrong, "竞价弱转强", "09:25弱到09:30转强", true),
        new(L1EventType.LowOpenLongYang, "低开长阳", "低开后大幅拉起", true),
        new(L1EventType.HighOpenLongYin, "高开长阴", "高开后大幅回落", true),
        new(L1EventType.NewStockOpened, "新股开板", "冲高回落破阈值", true),
        new(L1EventType.NewStockReseal, "新股开板回封", "回撤收窄至高点附近", true),
        new(L1EventType.SectorRush, "板块拉升", "成员普涨且均涨破阈值", true),
        new(L1EventType.SectorDive, "板块跳水", "成员普跌且均跌破阈值", true),
        new(L1EventType.SectorLimitUpWave, "板块涨停潮", "窗口内多只成员封板", true),
        new(L1EventType.SectorLimitUpOpenWave, "板块开板潮", "窗口内多只成员开板", true),
        new(L1EventType.TurnRed, "翻红", "涨跌幅由负转正", false),
        new(L1EventType.TurnGreen, "翻绿", "涨跌幅由正转负", false),
        new(L1EventType.IntradayHigh, "创日内新高", "刷新启动后高点", false),
        new(L1EventType.IntradayLow, "创日内新低", "刷新启动后低点", false),
        new(L1EventType.AmountTier, "成交额跨档", "累计成交额破门槛", false),
        new(L1EventType.VolumeAcceleration, "成交增量加速", "近30秒成交量放大", false),
        new(L1EventType.LargeBidOrder, "出现大买挂盘", "买一挂单额过大", false),
        new(L1EventType.LargeAskOrder, "出现大卖挂盘", "卖一挂单额过大", false),
        new(L1EventType.BidPressure, "盘口买压增强", "五档买量压卖量", false),
        new(L1EventType.AskPressure, "盘口卖压增强", "五档卖量压买量", false),
        new(L1EventType.SpreadWidened, "买卖价差异常", "买卖一价差过大", false),
    ];

    /// <summary>默认播语音的事件集合（对齐历史"只播强信号"行为）。</summary>
    public static HashSet<string> DefaultVoiceSet(StringComparer? comparer = null)
    {
        return new HashSet<string>(
            Entries.Where(entry => entry.DefaultVoice).Select(entry => entry.Type.ToString()),
            comparer ?? StringComparer.OrdinalIgnoreCase);
    }
}
