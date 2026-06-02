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
            VoiceMode.All => events.Where(IsVoiceEligible).ToArray(),
            _ => events.Where(item => IsVoiceEligible(item) && IsStrongSignal(item)).ToArray(),
        };
    }

    private static bool IsVoiceEligible(EventRecord item)
    {
        if (item.OpeningSignal is null) return true;
        if (item.OpeningSignal.DryRun) return false;
        return item.OpeningSignal.IntradayStatus != "preopen_candidate" &&
            item.OpeningSignal.IntradayOutcome != "preopen_candidate";
    }

    public static bool IsStrongSignal(EventRecord item)
    {
        return item.Severity is L1EventSeverity.Critical or L1EventSeverity.Important &&
            item.Type is not L1EventType.BidPressure and not L1EventType.AskPressure and not L1EventType.SpreadWidened
                and not L1EventType.LargeBidOrder and not L1EventType.LargeAskOrder;
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
