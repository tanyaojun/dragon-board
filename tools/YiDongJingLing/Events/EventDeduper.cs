namespace YiDongJingLing.Events;

public sealed class EventDeduper
{
    private readonly Dictionary<string, DateTimeOffset> _lastEmittedAt = new(StringComparer.Ordinal);
    private readonly Dictionary<string, int> _lastOpeningIntradayPriority = new(StringComparer.Ordinal);
    private readonly TimeSpan _defaultCooldown;

    public EventDeduper(TimeSpan? defaultCooldown = null)
    {
        _defaultCooldown = defaultCooldown ?? TimeSpan.FromSeconds(180);
    }

    public void Clear()
    {
        _lastEmittedAt.Clear();
        _lastOpeningIntradayPriority.Clear();
    }

    public IReadOnlyList<EventRecord> Filter(IReadOnlyList<EventRecord> events)
    {
        var result = new List<EventRecord>();
        foreach (var group in events.GroupBy(BatchGroupKey))
        {
            foreach (var item in group.OrderByDescending(Score).ThenByDescending(item => item.Timestamp))
            {
                if (!CanEmit(item)) continue;
                _lastEmittedAt[item.DedupeKey] = item.Timestamp;
                RememberOpeningIntradayPriority(item);
                result.Add(item);
                break;
            }
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
        var statusPriority = item.OpeningSignal?.IntradayStatus switch
        {
            "failed" => 4,
            "confirmed_reversal" => 4,
            "confirmed" => 3,
            "watch" => 2,
            "pending" => 1,
            "preopen_candidate" => 0,
            _ => 0,
        };
        var outcomePriority = item.OpeningSignal?.IntradayOutcome switch
        {
            "failed_open_dump" => 4,
            "confirmed_then_open_dump" => 4,
            "confirmed_strong" => 3,
            "watch_only" => 2,
            "pending" => 1,
            "preopen_candidate" => 0,
            _ => 0,
        };
        return Math.Max(statusPriority, outcomePriority);
    }

    private TimeSpan CooldownFor(L1EventType type)
    {
        return type is L1EventType.LimitUpOpened or L1EventType.LimitDownOpened
                or L1EventType.UpcomingLimitUpOpen or L1EventType.UpcomingLimitDownOpen
                or L1EventType.OpeningWeakToStrong
            ? TimeSpan.FromSeconds(30)
            : _defaultCooldown;
    }

    private static string BatchGroupKey(EventRecord item)
    {
        return item.Type == L1EventType.OpeningWeakToStrong
            ? $"{item.Code}:{item.Type}"
            : item.Code;
    }

    public static string BuildSpeechText(IReadOnlyList<EventRecord> events, int maxItems = 3)
    {
        if (events.Count == 0) return "";

        var items = events.Take(maxItems).Select(item => $"{item.DisplayName}{item.TypeName}").ToArray();
        return events.Count == 1
            ? $"{items[0]}，涨幅{events[0].ChangePct:0.##}%"
            : $"新增{events.Count}条异动，{string.Join("，", items)}";
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
            _ => 0,
        };

        return severityScore + typeScore;
    }
}
