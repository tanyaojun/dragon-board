namespace YiDongJingLing.Events;

public sealed class EventDeduper
{
    private readonly Dictionary<string, DateTimeOffset> _lastEmittedAt = new(StringComparer.Ordinal);
    private readonly TimeSpan _defaultCooldown;

    public EventDeduper(TimeSpan? defaultCooldown = null)
    {
        _defaultCooldown = defaultCooldown ?? TimeSpan.FromSeconds(180);
    }

    public void Clear() => _lastEmittedAt.Clear();

    public IReadOnlyList<EventRecord> Filter(IReadOnlyList<EventRecord> events)
    {
        var result = new List<EventRecord>();
        foreach (var group in events.GroupBy(BatchGroupKey))
        {
            foreach (var item in group.OrderByDescending(Score).ThenByDescending(item => item.Timestamp))
            {
                if (!CanEmit(item)) continue;
                _lastEmittedAt[item.DedupeKey] = item.Timestamp;
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
        if (!_lastEmittedAt.TryGetValue(item.DedupeKey, out var last)) return true;
        return item.Timestamp - last >= CooldownFor(item.Type);
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
