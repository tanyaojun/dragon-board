using YiDongJingLing.Settings;

namespace YiDongJingLing.Events;

public static class EventVoicePolicy
{
    public static IReadOnlyList<EventRecord> FilterForVoice(
        IEnumerable<EventRecord> events,
        VoiceMode mode)
    {
        return mode switch
        {
            VoiceMode.Muted => [],
            VoiceMode.All => events.ToArray(),
            _ => events.Where(IsStrongSignal).ToArray(),
        };
    }

    public static bool IsStrongSignal(EventRecord item)
    {
        return item.Severity is L1EventSeverity.Critical or L1EventSeverity.Important &&
            item.Type is not L1EventType.BidPressure and not L1EventType.AskPressure and not L1EventType.SpreadWidened;
    }

    public static string DisplayName(VoiceMode mode)
    {
        return mode switch
        {
            VoiceMode.All => "播报全部",
            VoiceMode.Muted => "静音",
            _ => "只播强信号",
        };
    }
}
