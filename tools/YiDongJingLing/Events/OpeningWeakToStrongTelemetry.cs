namespace YiDongJingLing.Events;

public sealed record OpeningWeakToStrongTelemetryRecord(
    string TradingDate,
    DateTimeOffset Timestamp,
    string Code,
    string Name,
    string Decision,
    bool Triggered,
    string? InvalidReason,
    string? Variant,
    string? Confidence,
    decimal Score,
    decimal? AuctionPct,
    decimal? OfficialOpenPct,
    decimal? FirstWindowPct,
    decimal? JumpPctPoint,
    decimal Amount,
    decimal? AmountDelta,
    string BaselineQuality,
    bool DryRun,
    string? IntradayStatus,
    string? IntradayOutcome,
    int? AuctionSampleCount,
    int? QuoteAgeMs,
    int? LatencyMs,
    decimal? AuctionCoverageRatio,
    IReadOnlyList<string> RiskFlags)
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
            result.InvalidReason,
            result.Variant,
            result.Confidence,
            result.Score,
            result.AuctionPct,
            result.OfficialOpenPct,
            result.FirstWindowPct,
            result.JumpPctPoint,
            result.Amount,
            result.AmountDelta,
            result.BaselineQuality,
            result.DryRun,
            result.IntradayStatus,
            result.IntradayOutcome,
            result.AuctionSampleCount,
            result.QuoteAgeMs,
            result.LatencyMs,
            result.AuctionCoverageRatio,
            result.RiskFlags.Select(item => item.Key).ToArray());
    }
}
