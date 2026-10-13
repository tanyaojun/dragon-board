namespace YiDongJingLing.Events;

public sealed class EventDeduper
{
    private static readonly TimeSpan DefaultStateChangeCooldown = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan DefaultNoiseCooldown = TimeSpan.FromSeconds(180);

    private readonly Dictionary<string, DateTimeOffset> _lastEmittedAt = new(StringComparer.Ordinal);
    private readonly Dictionary<string, int> _lastOpeningIntradayPriority = new(StringComparer.Ordinal);
    private readonly TimeSpan _stateChangeCooldown;
    private readonly TimeSpan _noiseCooldown;

    public EventDeduper(TimeSpan? stateChangeCooldown = null, TimeSpan? noiseCooldown = null)
    {
        _stateChangeCooldown = stateChangeCooldown ?? DefaultStateChangeCooldown;
        _noiseCooldown = noiseCooldown ?? DefaultNoiseCooldown;
    }

    public void Clear()
    {
        _lastEmittedAt.Clear();
        _lastOpeningIntradayPriority.Clear();
    }

    public IReadOnlyList<EventRecord> Filter(IReadOnlyList<EventRecord> events)
    {
        var result = new List<EventRecord>();
        foreach (var item in events)
        {
            if (!CanEmit(item)) continue;
            _lastEmittedAt[item.DedupeKey] = item.Timestamp;
            RememberOpeningIntradayPriority(item);
            result.Add(item);
        }

        return result
            .OrderByDescending(Score)
            .ThenByDescending(item => item.Timestamp)
            .ToArray();
    }

    private bool CanEmit(EventRecord item)
    {
        if (IsOpeningIntradayUpgrade(item)) return true;
        if (!_lastEmittedAt.TryGetValue(item.DedupeKey, out var last)) return true;
        return item.Timestamp - last >= CooldownFor(item.Type);
    }

    private bool IsOpeningIntradayUpgrade(EventRecord item)
    {
        if (item.Type != L1EventType.OpeningWeakToStrong) return false;
        var priority = OpeningIntradayPriority(item);
        if (priority <= 0) return false;
        return _lastOpeningIntradayPriority.TryGetValue(item.DedupeKey, out var lastPriority) &&
            priority > lastPriority;
    }

    private void RememberOpeningIntradayPriority(EventRecord item)
    {
        if (item.Type != L1EventType.OpeningWeakToStrong) return;
        _lastOpeningIntradayPriority[item.DedupeKey] = OpeningIntradayPriority(item);
    }

    private static int OpeningIntradayPriority(EventRecord item)
    {
        var stagePriority = item.OpeningSignal?.Stage switch
        {
            "auctionConditionPassed" or "auctionConditionFailed" => 1,
            "gapAlert" or "noGap" => 2,
            "trendConfirm" or "trendWeak" => 3,
            "optionalFinalStatus" => 4,
            _ => 0,
        };
        return stagePriority;
    }

    private TimeSpan CooldownFor(L1EventType type)
    {
        return IsStateChangeType(type) ? _stateChangeCooldown : _noiseCooldown;
    }

    private static bool IsStateChangeType(L1EventType type)
    {
        return type is L1EventType.LimitUpSealed
            or L1EventType.LimitUpOpened
            or L1EventType.UpcomingLimitUpOpen
            or L1EventType.LimitDownSealed
            or L1EventType.LimitDownOpened
            or L1EventType.UpcomingLimitDownOpen
            or L1EventType.NearLimitUp
            or L1EventType.NearLimitDown
            or L1EventType.FastRise
            or L1EventType.FastDrop
            or L1EventType.TurnRed
            or L1EventType.TurnGreen
            or L1EventType.IntradayHigh
            or L1EventType.IntradayLow
            or L1EventType.OpeningWeakToStrong
            or L1EventType.LowOpenLongYang
            or L1EventType.HighOpenLongYin
            or L1EventType.NewStockOpened
            or L1EventType.NewStockReseal
            or L1EventType.LimitUpResealed;
    }

    public static string BuildSpeechText(IReadOnlyList<EventRecord> events)
    {
        return events.Count == 0
            ? ""
            : $"新增{events.Count}条异动，" + string.Join("，", events.Select(item => $"{item.DisplayName}{item.TypeName}"));
    }

    public static IReadOnlyList<string> BuildSpeechItems(IReadOnlyList<EventRecord> events)
    {
        return events
            .OrderBy(item => item.Timestamp)
            .Select(BuildSpeechTextForEvent)
            .ToArray();
    }

    public static string BuildSpeechTextForEvent(EventRecord item)
    {
        if (item.Type is L1EventType.LimitUpSealed or L1EventType.LimitDownSealed or L1EventType.LimitUpResealed)
        {
            return $"{item.DisplayName}，{item.TypeName}，{item.Reason}";
        }
        return ShouldSpeakChangePct(item.Type)
            ? $"{item.DisplayName}，{item.TypeName}，涨幅{item.ChangePct:0.##}%"
            : $"{item.DisplayName}，{item.TypeName}";
    }

    private static bool ShouldSpeakChangePct(L1EventType type)
    {
        return type is L1EventType.FastRise or L1EventType.FastDrop;
    }

    private static int Score(EventRecord item)
    {
        var severityScore = item.Severity switch
        {
            L1EventSeverity.Critical => 300,
            L1EventSeverity.Important => 200,
            _ => 100,
        };

        var typeScore = item.Type switch
        {
            L1EventType.LimitUpSealed => 50,
            L1EventType.LimitUpOpened => 45,
            L1EventType.NewStockOpened => 44,
            L1EventType.NewStockReseal => 43,
            L1EventType.LimitUpResealed => 47,
            L1EventType.UpcomingLimitUpOpen => 43,
            L1EventType.LimitDownSealed => 44,
            L1EventType.LimitDownOpened => 42,
            L1EventType.UpcomingLimitDownOpen => 41,
            L1EventType.FastRise => 35,
            L1EventType.FastDrop => 34,
            L1EventType.OpeningWeakToStrong => 34,
            L1EventType.LowOpenLongYang => 33,
            L1EventType.HighOpenLongYin => 32,
            L1EventType.NearLimitUp => 30,
            L1EventType.NearLimitDown => 28,
            L1EventType.BigRiseTier => 25,
            L1EventType.BigDropTier => 24,
            L1EventType.SectorLimitUpWave => 46,
            L1EventType.SectorLimitUpOpenWave => 42,
            L1EventType.SectorRush => 26,
            L1EventType.SectorDive => 25,
            _ => 0,
        };

        return severityScore + typeScore;
    }
}
