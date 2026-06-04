namespace YiDongJingLing.Events;

public sealed record OpeningWeakToStrongTelemetryRecord(
    string TradingDate,
    DateTimeOffset Timestamp,
    string Code,
    string Name,
    string Decision,
    bool Triggered,
    string Stage,
    bool VoiceEligible,
    string Reason,
    string? InvalidReason,
    decimal? AuctionPct,
    decimal? OfficialOpenPct,
    decimal? FirstWindowPct,
    decimal? JumpPctPoint,
    decimal Amount,
    decimal? AmountDelta,
    string BaselineQuality,
    int? AuctionSampleCount,
    int? QuoteAgeMs,
    int? LatencyMs)
{
    public static OpeningWeakToStrongTelemetryRecord FromResult(
        OpeningWeakToStrongResult result,
        string decision)
    {
        return new OpeningWeakToStrongTelemetryRecord(
            result.TriggerAt.ToLocalTime().ToString("yyyy-MM-dd"),
            result.TriggerAt,
            result.Code,
            result.Name,
            decision,
            result.Triggered,
            result.Stage,
            result.VoiceEligible,
            result.Reason,
            result.InvalidReason,
            result.AuctionPct,
            result.OfficialOpenPct,
            result.FirstWindowPct,
            result.JumpPctPoint,
            result.Amount,
            result.AmountDelta,
            result.BaselineQuality,
            result.AuctionSampleCount,
            result.QuoteAgeMs,
            result.LatencyMs);
    }
}
