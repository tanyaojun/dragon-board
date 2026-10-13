using YiDongJingLing.Concepts;
using YiDongJingLing.MarketData;

namespace YiDongJingLing.Events;

/// <summary>板块异动触发阈值，语义对齐异动精灵概念聚合行（涨家数 + 板块均涨 + 封板/开板波次）。</summary>
public sealed class SectorEventRules
{
    public int MinRiseCount { get; init; } = 3;
    public decimal RiseRatio { get; init; } = 0.6m;
    public decimal RushMinAvgPct { get; init; } = 1.0m;
    public int MinFallCount { get; init; } = 3;
    public decimal FallRatio { get; init; } = 0.6m;
    public decimal DiveMaxAvgPct { get; init; } = -1.0m;
    public int WaveThreshold { get; init; } = 2;
    public TimeSpan WaveWindow { get; init; } = TimeSpan.FromSeconds(600);
    public TimeSpan Cooldown { get; init; } = TimeSpan.FromSeconds(600);
}

/// <summary>
/// 板块异动聚合引擎：每轮行情批量后按板块归属聚合监控池内成员。
/// 只产事件不做展示；无映射或成员缺失时安静返回空（映射告警由 ConceptMapResult.Errors 上报）。
/// </summary>
public sealed class SectorEventEngine
{
    private readonly SectorEventRules _rules;
    private readonly Dictionary<string, Queue<(DateTimeOffset At, string Code)>> _sealWindow = new(StringComparer.Ordinal);
    private readonly Dictionary<string, Queue<(DateTimeOffset At, string Code)>> _openWindow = new(StringComparer.Ordinal);
    private readonly Dictionary<string, DateTimeOffset> _lastEmitted = new(StringComparer.Ordinal);

    public SectorEventEngine(SectorEventRules? rules = null)
    {
        _rules = rules ?? new SectorEventRules();
    }

    public void Clear()
    {
        _sealWindow.Clear();
        _openWindow.Clear();
        _lastEmitted.Clear();
    }

    public IReadOnlyList<EventRecord> Evaluate(
        IReadOnlyList<QuoteSnapshot> quotes,
        IReadOnlyList<EventRecord> stockEvents,
        ConceptMapResult map,
        DateTimeOffset now)
    {
        var results = new List<EventRecord>();
        if (quotes.Count == 0 || map.SectorToStocks.Count == 0) return results;

        var quotesByCode = new Dictionary<string, QuoteSnapshot>(StringComparer.Ordinal);
        foreach (var quote in quotes)
        {
            quotesByCode[quote.Code] = quote;
        }

        // 1) 板块成员行情聚合（仅统计监控池内出现快照的成员）
        var sectorMembers = new Dictionary<string, List<QuoteSnapshot>>(StringComparer.Ordinal);
        foreach (var pair in map.SectorToStocks)
        {
            var members = new List<QuoteSnapshot>();
            foreach (var code in pair.Value)
            {
                if (quotesByCode.TryGetValue(code, out var quote)) members.Add(quote);
            }
            if (members.Count > 0) sectorMembers[pair.Key] = members;
        }

        // 2) 封板/开板事件滚入板块滚动窗口。
        // 注意：回封（LimitUpResealed）与首封同等计入涨停潮——反复回封的强势股是潮的一部分；
        // 窗口输入是 MainForm 经 EnabledEvents 过滤后的 emitted，因此个股"封涨停板/涨停回封"开关是板块涨停潮的前置依赖。
        foreach (var evt in stockEvents)
        {
            if (evt.Type is not (L1EventType.LimitUpSealed or L1EventType.LimitUpResealed or L1EventType.LimitUpOpened)) continue;
            var window = evt.Type == L1EventType.LimitUpOpened ? _openWindow : _sealWindow;
            foreach (var sector in map.SectorsOf(evt.Code))
            {
                if (!window.TryGetValue(sector, out var queue))
                {
                    queue = new Queue<(DateTimeOffset At, string Code)>();
                    window[sector] = queue;
                }
                queue.Enqueue((evt.Timestamp, evt.Code));
            }
        }

        // 3) 触发判定
        foreach (var (sector, members) in sectorMembers)
        {
            var rise = members.Count(item => item.ChangePct > 0m);
            var fall = members.Count(item => item.ChangePct < 0m);
            var avg = Math.Round(members.Average(item => item.ChangePct), 2, MidpointRounding.AwayFromZero);

            if (WaveTriggered(_sealWindow, sector, now))
            {
                if (TryEmit(results, sector, L1EventType.SectorLimitUpWave, "板块涨停潮",
                        L1EventSeverity.Critical, members, rise, fall, avg, now,
                        WindowCodes(_sealWindow, sector)))
                {
                    _sealWindow[sector].Clear();
                }
            }
            if (WaveTriggered(_openWindow, sector, now))
            {
                if (TryEmit(results, sector, L1EventType.SectorLimitUpOpenWave, "板块开板潮",
                        L1EventSeverity.Critical, members, rise, fall, avg, now,
                        WindowCodes(_openWindow, sector)))
                {
                    _openWindow[sector].Clear();
                }
            }
            if (rise >= _rules.MinRiseCount &&
                members.Count > 0 &&
                rise >= (decimal)members.Count * _rules.RiseRatio &&
                avg >= _rules.RushMinAvgPct)
            {
                TryEmit(results, sector, L1EventType.SectorRush, "板块拉升",
                    L1EventSeverity.Important, members, rise, fall, avg, now);
            }
            if (fall >= _rules.MinFallCount &&
                members.Count > 0 &&
                fall >= (decimal)members.Count * _rules.FallRatio &&
                avg <= _rules.DiveMaxAvgPct)
            {
                TryEmit(results, sector, L1EventType.SectorDive, "板块跳水",
                    L1EventSeverity.Important, members, rise, fall, avg, now);
            }
        }

        PruneWindows(now);
        return results;
    }

    private static IReadOnlyList<string> WindowCodes(
        Dictionary<string, Queue<(DateTimeOffset At, string Code)>> window,
        string sector)
    {
        return window.TryGetValue(sector, out var queue)
            ? queue.Select(item => item.Code).Distinct(StringComparer.Ordinal).ToArray()
            : Array.Empty<string>();
    }

    private bool WaveTriggered(Dictionary<string, Queue<(DateTimeOffset At, string Code)>> window, string sector, DateTimeOffset now)
    {
        if (!window.TryGetValue(sector, out var queue) || queue.Count < _rules.WaveThreshold) return false;
        while (queue.Count > 0 && now - queue.Peek().At > _rules.WaveWindow)
        {
            queue.Dequeue();
        }
        return queue.Count >= _rules.WaveThreshold;
    }

    private bool TryEmit(
        List<EventRecord> results,
        string sector,
        L1EventType type,
        string typeName,
        L1EventSeverity severity,
        List<QuoteSnapshot> members,
        int rise,
        int fall,
        decimal avg,
        DateTimeOffset now,
        IReadOnlyList<string>? memberCodes = null)
    {
        var key = $"S:{sector}:{type}";
        if (_lastEmitted.TryGetValue(key, out var last) && now - last < _rules.Cooldown) return false;
        _lastEmitted[key] = now;

        var leaders = members
            .OrderByDescending(item => item.ChangePct)
            .Take(3)
            .Select(item => $"{(string.IsNullOrWhiteSpace(item.Name) ? item.Code : item.Name)} {item.ChangePct:0.##}%")
            .ToArray();
        var reason = $"{members.Count} 只成员 {rise} 涨 {fall} 跌，均涨 {avg:0.##}%；领涨 " + string.Join("、", leaders);

        results.Add(new EventRecord(
            type,
            typeName,
            Code: "",
            Name: sector,
            Price: 0m,
            ChangePct: avg,
            Volume: 0m,
            Amount: 0m,
            Timestamp: now,
            Severity: severity,
            Reason: reason,
            OpeningSignal: null,
            Sector: sector,
            MemberCodes: memberCodes is null ? "" : string.Join(",", memberCodes)));
        return true;
    }

    private void PruneWindows(DateTimeOffset now)
    {
        Prune(_sealWindow, now);
        Prune(_openWindow, now);
    }

    private void Prune(Dictionary<string, Queue<(DateTimeOffset At, string Code)>> window, DateTimeOffset now)
    {
        foreach (var queue in window.Values)
        {
            while (queue.Count > 0 && now - queue.Peek().At > _rules.WaveWindow)
            {
                queue.Dequeue();
            }
        }
    }
}
