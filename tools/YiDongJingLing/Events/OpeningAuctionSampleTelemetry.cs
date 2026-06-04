using YiDongJingLing.MarketData;

namespace YiDongJingLing.Events;

public sealed record OpeningAuctionSampleTelemetryRecord(
    string TradingDate,
    DateTimeOffset Timestamp,
    string Code,
    string Name,
    bool InOpeningTrendWindow,
    bool InInitialBaselineWindow,
    bool InFinalBaselineWindow,
    bool OpeningForcedSample,
    int? RequestedCount,
    int? ReceivedCount,
    decimal? CoverageRatio,
    int? ElapsedMs,
    int? SlowBatches,
    int? TruncatedBatches,
    DateTimeOffset? CapturedAt,
    DateTimeOffset? BridgeTs,
    int? QuoteAgeMs)
{
    public static OpeningAuctionSampleTelemetryRecord FromQuote(QuoteSnapshot quote)
    {
        var time = quote.SourceTime.ToLocalTime().TimeOfDay;
        var capturedAt = quote.CapturedAt ?? quote.BridgeTs;
        return new OpeningAuctionSampleTelemetryRecord(
            quote.SourceTime.ToLocalTime().ToString("yyyy-MM-dd"),
            quote.SourceTime,
            quote.Code,
            quote.Name,
            time >= TimeSpan.Parse("09:20:00") && time <= TimeSpan.Parse("09:25:10"),
            time >= TimeSpan.Parse("09:20:00") && time <= TimeSpan.Parse("09:20:30"),
            time >= TimeSpan.Parse("09:24:50") && time <= TimeSpan.Parse("09:25:10"),
            quote.OpeningForcedSample,
            quote.RequestedCount,
            quote.ReceivedCount,
            quote.RequestedCount is > 0 && quote.ReceivedCount.HasValue
                ? Math.Round((decimal)quote.ReceivedCount.Value / quote.RequestedCount.Value, 2, MidpointRounding.AwayFromZero)
                : null,
            quote.ElapsedMs,
            quote.SlowBatches,
            quote.TruncatedBatches,
            quote.CapturedAt,
            quote.BridgeTs,
            capturedAt.HasValue ? Math.Max(0, (int)Math.Round((quote.SourceTime - capturedAt.Value).TotalMilliseconds)) : null);
    }
}
