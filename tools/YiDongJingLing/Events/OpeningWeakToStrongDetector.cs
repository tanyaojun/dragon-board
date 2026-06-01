using System.Globalization;
using System.Text;
using System.Text.Json;

namespace YiDongJingLing.Events;

public sealed record OpeningWeakToStrongRules(
    string AuctionTrendStart,
    string InitialBaselineStart,
    string InitialBaselineEnd,
    string AuctionStart,
    string AuctionEnd,
    string DetectStart,
    string DetectEnd,
    decimal AuctionWeakMaxPct,
    decimal AuctionGapJumpMinPctPoint,
    decimal AuctionGapFirstWindowMinPct,
    decimal LowOpenRedJumpMinPctPoint,
    decimal LowOpenRedFirstWindowMinPct,
    decimal StrongOpenFirstWindowMinPct,
    decimal NearLimitDistancePct,
    decimal MinCurrentAmount,
    decimal MinAmountDelta,
    decimal OpeningLiquidityMinAmount,
    string AuctionLateLiftStart,
    decimal AuctionLateLiftTotalMinPctPoint,
    decimal AuctionLateLiftLateMinPctPoint,
    decimal AuctionPriceLiftMinPctPoint,
    decimal AuctionAmountLiftMinRatio,
    decimal AuctionLatePriceLiftMinPctPoint,
    decimal AuctionLateAmountLiftMinRatio,
    decimal AuctionLateLiftFinalMinPct,
    /// <summary>V5 起不再参与检测逻辑，仅保留兼容旧配置。从 ConfigHash 中排除。</summary>
    decimal AuctionLateLiftAmountDeltaMin,
    /// <summary>V5 起不再参与检测逻辑，仅保留兼容旧配置。从 ConfigHash 中排除。</summary>
    decimal AuctionLateLiftLateAmountDeltaMin,
    decimal AuctionLateLiftFirstWindowMinPct,
    decimal AuctionLateLiftJumpMinPctPoint,
    decimal AuctionLateHighRetreatPctPoint,
    decimal PreviousWeakScoreMin,
    decimal MinAuctionCoverageRatio,
    int MaxQuoteAgeMs,
    decimal MinCurrentVolume,
    decimal OpeningSupportOpenRatio,
    decimal AuctionGapMaxScore = 40m,
    decimal AuctionGapScoreSlope = 4m,
    decimal AuctionGapOpenStrengthScore = 15m,
    decimal AuctionGapAmountStrongScore = 20m,
    decimal AuctionGapAmountWeakScore = 10m,
    decimal AuctionGapQualityGoodScore = 8m,
    decimal AuctionGapQualityDegradedScore = 3m,
    decimal AuctionLateLiftCoreScore = 25m,
    decimal AuctionLateLiftAmountRatioScore = 18m,
    decimal AuctionLateLiftOpenStrengthScore = 18m,
    decimal StrongOpenNearLimitScore = 25m,
    decimal StrongOpenOpenStrengthScore = 25m,
    decimal LowOpenRedReversalScore = 22m,
    decimal LowOpenTurnRedScore = 10m,
    decimal PreviousWeakContextScore = 8m)
{
    public static OpeningWeakToStrongRules FromJson(JsonElement element)
    {
        return new OpeningWeakToStrongRules(
            GetString(element, "auctionTrendStart"),
            GetStringOrDefault(element, "initialBaselineStart", "09:20:00"),
            GetStringOrDefault(element, "initialBaselineEnd", "09:20:30"),
            GetString(element, "auctionStart"),
            GetString(element, "auctionEnd"),
            GetString(element, "detectStart"),
            GetString(element, "detectEnd"),
            GetDecimal(element, "auctionWeakMaxPct"),
            GetDecimal(element, "auctionGapJumpMinPctPoint"),
            GetDecimal(element, "auctionGapFirstWindowMinPct"),
            GetDecimal(element, "lowOpenRedJumpMinPctPoint"),
            GetDecimal(element, "lowOpenRedFirstWindowMinPct"),
            GetDecimal(element, "strongOpenFirstWindowMinPct"),
            GetDecimal(element, "nearLimitDistancePct"),
            GetDecimal(element, "minCurrentAmount"),
            GetDecimal(element, "minAmountDelta"),
            GetDecimalOrDefault(element, "openingLiquidityMinAmount", 5_000_000m),
            GetString(element, "auctionLateLiftStart"),
            GetDecimal(element, "auctionLateLiftTotalMinPctPoint"),
            GetDecimal(element, "auctionLateLiftLateMinPctPoint"),
            GetDecimalOrDefault(element, "auctionPriceLiftMinPctPoint", 0.8m),
            GetDecimalOrDefault(element, "auctionAmountLiftMinRatio", 0.35m),
            GetDecimalOrDefault(element, "auctionLatePriceLiftMinPctPoint", 0.3m),
            GetDecimalOrDefault(element, "auctionLateAmountLiftMinRatio", 0.2m),
            GetDecimal(element, "auctionLateLiftFinalMinPct"),
            GetDecimal(element, "auctionLateLiftAmountDeltaMin"),
            GetDecimal(element, "auctionLateLiftLateAmountDeltaMin"),
            GetDecimal(element, "auctionLateLiftFirstWindowMinPct"),
            GetDecimal(element, "auctionLateLiftJumpMinPctPoint"),
            GetDecimal(element, "auctionLateHighRetreatPctPoint"),
            GetDecimalOrDefault(element, "previousWeakScoreMin", 30m),
            GetDecimalOrDefault(element, "minAuctionCoverageRatio", 0.95m),
            (int)GetDecimalOrDefault(element, "maxQuoteAgeMs", 10_000m),
            GetDecimalOrDefault(element, "minCurrentVolume", 1_000_000m),
            GetDecimalOrDefault(element, "openingSupportOpenRatio", 0.995m),
            AuctionGapMaxScore: GetDecimalOrDefault(element, "auctionGapMaxScore", 40m),
            AuctionGapScoreSlope: GetDecimalOrDefault(element, "auctionGapScoreSlope", 4m),
            AuctionGapOpenStrengthScore: GetDecimalOrDefault(element, "auctionGapOpenStrengthScore", 15m),
            AuctionGapAmountStrongScore: GetDecimalOrDefault(element, "auctionGapAmountStrongScore", 20m),
            AuctionGapAmountWeakScore: GetDecimalOrDefault(element, "auctionGapAmountWeakScore", 10m),
            AuctionGapQualityGoodScore: GetDecimalOrDefault(element, "auctionGapQualityGoodScore", 8m),
            AuctionGapQualityDegradedScore: GetDecimalOrDefault(element, "auctionGapQualityDegradedScore", 3m),
            AuctionLateLiftCoreScore: GetDecimalOrDefault(element, "auctionLateLiftCoreScore", 25m),
            AuctionLateLiftAmountRatioScore: GetDecimalOrDefault(element, "auctionLateLiftAmountRatioScore", 18m),
            AuctionLateLiftOpenStrengthScore: GetDecimalOrDefault(element, "auctionLateLiftOpenStrengthScore", 18m),
            StrongOpenNearLimitScore: GetDecimalOrDefault(element, "strongOpenNearLimitScore", 25m),
            StrongOpenOpenStrengthScore: GetDecimalOrDefault(element, "strongOpenOpenStrengthScore", 25m),
            LowOpenRedReversalScore: GetDecimalOrDefault(element, "lowOpenRedReversalScore", 22m),
            LowOpenTurnRedScore: GetDecimalOrDefault(element, "lowOpenTurnRedScore", 10m),
            PreviousWeakContextScore: GetDecimalOrDefault(element, "previousWeakContextScore", 8m));
    }

    private static string GetString(JsonElement element, string name)
    {
        return element.GetProperty(name).GetString() ?? "";
    }

    private static string GetStringOrDefault(JsonElement element, string name, string fallback)
    {
        return element.TryGetProperty(name, out var property) ? property.GetString() ?? fallback : fallback;
    }

    private static decimal GetDecimal(JsonElement element, string name)
    {
        return element.GetProperty(name).GetDecimal();
    }

    private static decimal GetDecimalOrDefault(JsonElement element, string name, decimal fallback)
    {
        return element.TryGetProperty(name, out var property) && property.ValueKind is JsonValueKind.Number
            ? property.GetDecimal()
            : fallback;
    }
}

public sealed record OpeningWeakToStrongQuote(
    string Code,
    string Name,
    DateTimeOffset At,
    decimal LastPrice,
    decimal PreClose,
    decimal Open,
    decimal Amount,
    decimal Volume,
    decimal LimitUpPrice,
    DateTimeOffset? CapturedAt,
    DateTimeOffset? BridgeTs,
    bool OpeningForcedSample = false,
    int? RequestedCount = null,
    int? ReceivedCount = null,
    int? ElapsedMs = null,
    int? SlowBatches = null,
    int? TruncatedBatches = null,
    decimal? PreviousWeakScore = null,
    IReadOnlyList<string>? PreviousWeakSignals = null,
    string PreviousWeakSource = "",
    bool DryRun = false)
{
    public static OpeningWeakToStrongQuote FromJson(JsonElement element)
    {
        return new OpeningWeakToStrongQuote(
            GetString(element, "code"),
            GetString(element, "name"),
            DateTimeOffset.Parse(GetString(element, "at")),
            GetDecimal(element, "lastPrice"),
            GetDecimal(element, "preClose"),
            GetDecimal(element, "open"),
            GetDecimal(element, "amount"),
            GetDecimal(element, "volume"),
            GetDecimal(element, "limitUpPrice"),
            GetDateTimeOffset(element, "capturedAt"),
            GetDateTimeOffset(element, "bridgeTs"),
            GetBool(element, "openingForcedSample"),
            GetInt(element, "requestedCount"),
            GetInt(element, "receivedCount"),
            GetInt(element, "elapsedMs"),
            GetInt(element, "slowBatches"),
            GetInt(element, "truncatedBatches"),
            GetOptionalDecimal(element, "previousWeakScore"),
            GetStringArray(element, "previousWeakSignals"),
            GetString(element, "previousWeakSource"),
            GetBool(element, "dryRun"));
    }

    private static string GetString(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var property) ? property.GetString() ?? "" : "";
    }

    private static decimal GetDecimal(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var property) && property.ValueKind is JsonValueKind.Number
            ? property.GetDecimal()
            : 0m;
    }

    private static decimal? GetOptionalDecimal(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var property) && property.ValueKind is JsonValueKind.Number
            ? property.GetDecimal()
            : null;
    }

    private static DateTimeOffset? GetDateTimeOffset(JsonElement element, string name)
    {
        var value = GetString(element, name);
        return string.IsNullOrWhiteSpace(value) ? null : DateTimeOffset.Parse(value);
    }

    private static bool GetBool(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var property) &&
            property.ValueKind is JsonValueKind.True or JsonValueKind.False &&
            property.GetBoolean();
    }

    private static int? GetInt(JsonElement element, string name)
    {
        return element.TryGetProperty(name, out var property) && property.ValueKind is JsonValueKind.Number
            ? property.GetInt32()
            : null;
    }

    private static IReadOnlyList<string> GetStringArray(JsonElement element, string name)
    {
        if (!element.TryGetProperty(name, out var property) || property.ValueKind != JsonValueKind.Array)
            return Array.Empty<string>();

        return property
            .EnumerateArray()
            .Select(item => item.GetString()?.Trim() ?? "")
            .Where(item => !string.IsNullOrWhiteSpace(item))
            .ToArray();
    }
}

public sealed record OpeningWeakToStrongBaseline(
    string Code,
    string TradingDate,
    string Name,
    decimal AuctionFinalPrice,
    decimal AuctionPct,
    decimal AuctionAmount,
    decimal PreClose,
    DateTimeOffset CapturedAt,
    DateTimeOffset? BridgeTs,
    int SampleCount,
    string Quality,
    bool OpeningForcedSample,
    int? RequestedCount,
    int? ReceivedCount,
    int? ElapsedMs,
    int? SlowBatches,
    int? TruncatedBatches,
    OpeningAuctionPriceVolumeProfile? AuctionProfile);

public sealed record OpeningAuctionPriceVolumeProfile(
    int SampleCount,
    DateTimeOffset? InitialAt,
    decimal? InitialPrice,
    decimal? InitialPct,
    decimal? InitialAmount,
    DateTimeOffset? LateAt,
    decimal? LatePrice,
    decimal? LateAmount,
    DateTimeOffset? FinalAt,
    decimal? FinalPrice,
    decimal? FinalAmount,
    decimal? StartPct,
    decimal? LateStartPct,
    decimal? FinalPct,
    decimal? HighPct,
    decimal? TotalLiftPctPoint,
    decimal? LateLiftPctPoint,
    decimal? AmountDelta,
    decimal? LateAmountDelta,
    decimal? AmountLiftRatio,
    decimal? LateAmountLiftRatio,
    bool PriceVolumeConfirmed,
    bool LateLiftConfirmed,
    IReadOnlyList<string> RiskFlags);

public sealed record OpeningWeakToStrongFactor(
    string Key,
    object Value,
    decimal? Threshold,
    decimal Score);

public sealed record OpeningWeakToStrongRiskFlag(
    string Key,
    string Severity,
    decimal Penalty);

public sealed record OpeningWeakToStrongResult(
    bool Triggered,
    string SignalType,
    string DisplayName,
    string Code,
    string Name,
    string? Variant,
    string? Confidence,
    decimal Score,
    decimal? AuctionFinalPrice,
    decimal? AuctionPct,
    decimal? OfficialOpen,
    decimal? OfficialOpenPct,
    decimal? FirstWindowPrice,
    decimal? FirstWindowPct,
    decimal? JumpPctPoint,
    decimal Amount,
    decimal? AmountDelta,
    DateTimeOffset? InitialBaselineAt,
    decimal? InitialBaselinePrice,
    decimal? InitialBaselinePct,
    decimal? InitialBaselineAmount,
    DateTimeOffset? LateBaselineAt,
    decimal? LateBaselinePrice,
    decimal? LateBaselinePct,
    decimal? LateBaselineAmount,
    DateTimeOffset? FinalBaselineAt,
    decimal? FinalBaselinePrice,
    decimal? FinalBaselinePct,
    decimal? FinalBaselineAmount,
    decimal? AuctionPriceLiftPctPoint,
    decimal? LatePriceLiftPctPoint,
    decimal? AuctionAmountDelta,
    decimal? LateAmountDelta,
    decimal? AuctionAmountLiftRatio,
    decimal? LateAmountLiftRatio,
    bool? PriceVolumeConfirmed,
    string LiquidityTier,
    string LiquidityTierMode,
    string LiquidityTierBasis,
    string LiquidityTierThresholds,
    string LiquidityTierVersion,
    decimal? LimitDistancePct,
    DateTimeOffset TriggerAt,
    string BaselineQuality,
    DateTimeOffset? AuctionCapturedAt,
    DateTimeOffset? BridgeTs,
    DateTimeOffset? QuoteCapturedAt,
    int? AuctionSampleCount,
    int? QuoteAgeMs,
    int? LatencyMs,
    bool OpeningForcedSample,
    int? RequestedCount,
    int? ReceivedCount,
    int? ElapsedMs,
    int? SlowBatches,
    int? TruncatedBatches,
    decimal? PreviousWeakScore,
    IReadOnlyList<string> PreviousWeakSignals,
    string PreviousWeakSource,
    decimal? AuctionCoverageRatio,
    string? IntradayStatus,
    string? IntradayOutcome,
    DateTimeOffset? IntradayStatusAt,
    decimal? IntradayPrice,
    decimal? IntradayPct,
    decimal? IntradayAmount,
    string? IntradayNote,
    bool DryRun,
    IReadOnlyList<OpeningWeakToStrongFactor> Factors,
    IReadOnlyList<OpeningWeakToStrongRiskFlag> RiskFlags,
    string? InvalidReason,
    string RuleVersion,
    string ConfigHash);

public sealed record OpeningWeakToStrongSignal(
    string TradingDate,
    string Code,
    string Name,
    string SignalType,
    string Confidence,
    decimal Score,
    string Variant,
    DateTimeOffset TriggerAt,
    bool DryRun,
    decimal AuctionFinalPrice,
    decimal AuctionPct,
    decimal? OfficialOpen,
    decimal? OfficialOpenPct,
    decimal FirstWindowPrice,
    decimal FirstWindowPct,
    decimal JumpPctPoint,
    decimal Amount,
    decimal AmountDelta,
    DateTimeOffset? InitialBaselineAt,
    decimal? InitialBaselinePrice,
    decimal? InitialBaselinePct,
    decimal? InitialBaselineAmount,
    DateTimeOffset? LateBaselineAt,
    decimal? LateBaselinePrice,
    decimal? LateBaselinePct,
    decimal? LateBaselineAmount,
    DateTimeOffset? FinalBaselineAt,
    decimal? FinalBaselinePrice,
    decimal? FinalBaselinePct,
    decimal? FinalBaselineAmount,
    decimal? AuctionPriceLiftPctPoint,
    decimal? LatePriceLiftPctPoint,
    decimal? AuctionAmountDelta,
    decimal? LateAmountDelta,
    decimal? AuctionAmountLiftRatio,
    decimal? LateAmountLiftRatio,
    bool? PriceVolumeConfirmed,
    string LiquidityTier,
    string LiquidityTierMode,
    string LiquidityTierBasis,
    string LiquidityTierThresholds,
    string LiquidityTierVersion,
    decimal? LimitDistancePct,
    string BaselineQuality,
    DateTimeOffset? AuctionCapturedAt,
    DateTimeOffset? BridgeTs,
    DateTimeOffset? QuoteCapturedAt,
    int? AuctionSampleCount,
    int? QuoteAgeMs,
    int? LatencyMs,
    bool OpeningForcedSample,
    int? RequestedCount,
    int? ReceivedCount,
    int? ElapsedMs,
    int? SlowBatches,
    int? TruncatedBatches,
    decimal? PreviousWeakScore,
    IReadOnlyList<string> PreviousWeakSignals,
    string PreviousWeakSource,
    decimal? AuctionCoverageRatio,
    string? IntradayStatus,
    string? IntradayOutcome,
    DateTimeOffset? IntradayStatusAt,
    decimal? IntradayPrice,
    decimal? IntradayPct,
    decimal? IntradayAmount,
    string? IntradayNote,
    string RuleVersion,
    string ConfigHash,
    IReadOnlyList<OpeningWeakToStrongFactor> Factors,
    IReadOnlyList<OpeningWeakToStrongRiskFlag> RiskFlags);

public sealed class OpeningAuctionStateStore
{
    private readonly OpeningWeakToStrongRules _rules;
    private readonly Dictionary<string, OpeningWeakToStrongBaseline> _baselines = new(StringComparer.Ordinal);
    private readonly Dictionary<string, List<OpeningWeakToStrongQuote>> _samples = new(StringComparer.Ordinal);

    public OpeningAuctionStateStore(OpeningWeakToStrongRules rules)
    {
        _rules = rules;
    }

    public void Capture(OpeningWeakToStrongQuote quote)
    {
        if (!IsValidPrice(quote.LastPrice) || !IsValidPrice(quote.PreClose)) return;

        var tradingDate = TradingDate(quote.At);
        var key = BaselineKey(quote.Code, tradingDate);
        List<OpeningWeakToStrongQuote>? samplesForProfile = null;
        var inTrendWindow = IsInWindow(quote.At, _rules.AuctionTrendStart, _rules.AuctionEnd);
        if (inTrendWindow)
        {
            if (!_samples.TryGetValue(key, out var samples))
            {
                samples = [];
                _samples[key] = samples;
            }
            samples.Add(quote);
            samples.Sort((left, right) => left.At.CompareTo(right.At));
            if (samples.Count > 64)
            {
                samples.RemoveRange(0, samples.Count - 64);
            }
            samplesForProfile = samples;
        }

        _baselines.TryGetValue(key, out var previous);
        var auctionProfile = BuildAuctionProfile(samplesForProfile ?? [quote], _rules);
        if (!IsInWindow(quote.At, _rules.AuctionStart, _rules.AuctionEnd))
        {
            if (previous is not null && inTrendWindow)
            {
                _baselines[key] = previous with
                {
                    AuctionProfile = auctionProfile,
                };
            }
            return;
        }

        var capturedAt = quote.CapturedAt ?? quote.At;
        var auctionSampleCount = CountAuctionBaselineSamples(samplesForProfile ?? [quote], _rules);
        if (previous is not null && CompareQuoteFreshness(capturedAt, previous.CapturedAt) <= 0)
        {
            _baselines[key] = previous with
            {
                SampleCount = Math.Max(previous.SampleCount, auctionSampleCount),
                AuctionProfile = auctionProfile,
            };
            return;
        }

        var quality = quote.CapturedAt.HasValue || quote.BridgeTs.HasValue ? "good" : "degraded";
        _baselines[key] = new OpeningWeakToStrongBaseline(
            quote.Code,
            tradingDate,
            string.IsNullOrWhiteSpace(quote.Name) ? quote.Code : quote.Name,
            quote.LastPrice,
            Pct(quote.LastPrice, quote.PreClose),
            quote.Amount,
            quote.PreClose,
            capturedAt,
            quote.BridgeTs,
            Math.Max(previous?.SampleCount ?? 0, auctionSampleCount),
            quality,
            quote.OpeningForcedSample,
            quote.RequestedCount,
            quote.ReceivedCount,
            quote.ElapsedMs,
            quote.SlowBatches,
            quote.TruncatedBatches,
            auctionProfile);
    }

    public OpeningWeakToStrongBaseline? GetBaseline(string code, DateTimeOffset timestamp)
    {
        return _baselines.TryGetValue(BaselineKey(code, TradingDate(timestamp)), out var baseline) ? baseline : null;
    }

    public void Clear()
    {
        _baselines.Clear();
        _samples.Clear();
    }

    private static bool IsValidPrice(decimal value) => value > 0m;

    internal static bool IsInWindow(DateTimeOffset timestamp, string start, string end)
    {
        var value = timestamp.ToLocalTime().TimeOfDay;
        return value >= TimeSpan.Parse(start) && value <= TimeSpan.Parse(end);
    }

    internal static decimal Pct(decimal price, decimal preClose)
    {
        return (price - preClose) / preClose * 100m;
    }

    private static long CompareQuoteFreshness(DateTimeOffset quoteCapturedAt, DateTimeOffset baselineCapturedAt)
    {
        return quoteCapturedAt.ToUnixTimeMilliseconds() - baselineCapturedAt.ToUnixTimeMilliseconds();
    }

    private static decimal Round2(decimal value) => Math.Round(value, 2, MidpointRounding.AwayFromZero);

    private static bool Meets(decimal value, decimal threshold) => value + 0.000001m >= threshold;

    private static decimal? RatioFromBase(decimal? delta, decimal? baseline)
    {
        return delta.HasValue && baseline.HasValue && baseline.Value > 0m ? delta.Value / baseline.Value : null;
    }

    private static OpeningAuctionPriceVolumeProfile? BuildAuctionProfile(
        IReadOnlyList<OpeningWeakToStrongQuote> samples,
        OpeningWeakToStrongRules rules)
    {
        var trusted = samples
            .Where(item => IsInWindow(item.At, rules.AuctionTrendStart, rules.AuctionEnd))
            .Where(item => IsValidPrice(item.LastPrice) && IsValidPrice(item.PreClose))
            .OrderBy(item => item.At)
            .ToArray();
        if (trusted.Length < 2) return null;

        var initial = trusted.FirstOrDefault(item => IsInWindow(item.At, rules.InitialBaselineStart, rules.InitialBaselineEnd));
        var finalSamples = trusted.Where(item => IsInWindow(item.At, rules.AuctionStart, rules.AuctionEnd)).ToArray();
        var final = finalSamples.Length > 0 ? finalSamples[^1] : trusted[^1];
        var lateStartTime = TimeSpan.Parse(rules.AuctionLateLiftStart);
        var lateStart = trusted.FirstOrDefault(item => item.At.ToLocalTime().TimeOfDay >= lateStartTime) ?? final;
        decimal? startPct = initial is null ? null : Pct(initial.LastPrice, initial.PreClose);
        var lateStartPct = Pct(lateStart.LastPrice, lateStart.PreClose);
        var finalPct = Pct(final.LastPrice, final.PreClose);
        var highPct = trusted.Max(item => Pct(item.LastPrice, item.PreClose));
        decimal? totalLiftPctPoint = startPct.HasValue ? finalPct - startPct.Value : null;
        var lateLiftPctPoint = finalPct - lateStartPct;
        decimal? initialAmount = initial?.Amount;
        var finalAmount = final.Amount;
        var lateStartAmount = lateStart.Amount;
        decimal? amountDelta = initialAmount.HasValue ? finalAmount - initialAmount.Value : null;
        var lateAmountDelta = final.Amount - lateStart.Amount;
        var amountLiftRatio = RatioFromBase(amountDelta, initialAmount);
        var lateAmountLiftRatio = RatioFromBase(lateAmountDelta, lateStartAmount);
        var totalPriceLifted = totalLiftPctPoint.HasValue && Meets(totalLiftPctPoint.Value, rules.AuctionPriceLiftMinPctPoint);
        var latePriceLifted = Meets(lateLiftPctPoint, rules.AuctionLatePriceLiftMinPctPoint);
        var totalAmountExpanded = amountLiftRatio.HasValue && Meets(amountLiftRatio.Value, rules.AuctionAmountLiftMinRatio);
        var lateAmountExpanded = lateAmountLiftRatio.HasValue && Meets(lateAmountLiftRatio.Value, rules.AuctionLateAmountLiftMinRatio);
        var priceLifted = totalPriceLifted || latePriceLifted;
        var amountExpanded = totalAmountExpanded || lateAmountExpanded;
        var highRetreated = Meets(highPct - finalPct, rules.AuctionLateHighRetreatPctPoint);
        var riskFlags = new List<string>();
        if (initial is not null && priceLifted && !amountExpanded) riskFlags.Add("auction_price_volume_desynced");
        if (initial is not null && amountExpanded && !priceLifted) riskFlags.Add("auction_price_volume_desynced");
        if (priceLifted && !amountExpanded) riskFlags.Add("price_lift_without_volume");
        if (amountExpanded && !priceLifted) riskFlags.Add("volume_without_price_lift");
        if (highRetreated) riskFlags.Add("auction_late_high_retreated");

        return new OpeningAuctionPriceVolumeProfile(
            trusted.Length,
            initial?.At,
            initial?.LastPrice,
            startPct.HasValue ? Round2(startPct.Value) : null,
            initialAmount,
            lateStart.At,
            lateStart.LastPrice,
            lateStartAmount,
            final.At,
            final.LastPrice,
            finalAmount,
            startPct.HasValue ? Round2(startPct.Value) : null,
            Round2(lateStartPct),
            Round2(finalPct),
            Round2(highPct),
            totalLiftPctPoint.HasValue ? Round2(totalLiftPctPoint.Value) : null,
            Round2(lateLiftPctPoint),
            amountDelta,
            lateAmountDelta,
            amountLiftRatio.HasValue ? Round2(amountLiftRatio.Value) : null,
            lateAmountLiftRatio.HasValue ? Round2(lateAmountLiftRatio.Value) : null,
            initial is not null &&
                totalPriceLifted &&
                totalAmountExpanded &&
                latePriceLifted &&
                lateAmountExpanded &&
                !highRetreated,
            initial is not null &&
                totalPriceLifted &&
                totalAmountExpanded &&
                latePriceLifted &&
                lateAmountExpanded &&
                !highRetreated,
            riskFlags);
    }

    private static int CountAuctionBaselineSamples(
        IReadOnlyList<OpeningWeakToStrongQuote> samples,
        OpeningWeakToStrongRules rules)
    {
        return samples.Count(item => IsInWindow(item.At, rules.AuctionStart, rules.AuctionEnd));
    }

    private static string TradingDate(DateTimeOffset timestamp)
    {
        return timestamp.ToLocalTime().ToString("yyyy-MM-dd");
    }

    private static string BaselineKey(string code, string tradingDate)
    {
        return $"{tradingDate}:{code}";
    }
}

public sealed class OpeningWeakToStrongDetector
{
    private const string SignalType = "opening_weak_to_strong";
    private const string DisplayName = "竞价弱转强";
    private const string LiquidityTierVersion = "liquidity-review.v1";
    private const decimal HotAmount = 100_000_000m;
    private const string PreopenCandidateStart = "09:25:00";
    private const string IntradayConfirmEnd = "10:00:00";
    private const decimal IntradayConfirmAdvancePctPoint = 1m;
    private readonly OpeningWeakToStrongRules _rules;
    private readonly string _ruleVersion;
    private readonly Dictionary<string, OpeningWeakToStrongResult> _activeSignals = new(StringComparer.Ordinal);

    public OpeningWeakToStrongDetector(
        OpeningWeakToStrongRules rules,
        string ruleVersion = "opening-weak-to-strong.v1")
    {
        _rules = rules;
        _ruleVersion = ruleVersion;
    }

    public void Clear()
    {
        _activeSignals.Clear();
    }

    public OpeningWeakToStrongResult Evaluate(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline? baseline)
    {
        var activeKey = BaselineKey(quote.Code, TradingDate(quote.At));
        _activeSignals.TryGetValue(activeKey, out var activeSignal);
        if (!OpeningAuctionStateStore.IsInWindow(quote.At, _rules.DetectStart, _rules.DetectEnd))
        {
            if (OpeningAuctionStateStore.IsInWindow(quote.At, PreopenCandidateStart, BeforeWindow(_rules.DetectStart)))
            {
                var preopenCandidate = EvaluatePreopenCandidate(quote, baseline);
                if (preopenCandidate.Triggered)
                {
                    _activeSignals[activeKey] = preopenCandidate;
                }
                return preopenCandidate;
            }

            var update = activeSignal is null ? null : EvaluateIntradayUpdate(quote, activeSignal);
            if (update is not null)
            {
                _activeSignals[activeKey] = update;
                return update;
            }
            return Rejected(quote, baseline, "outside_detection_window");
        }
        if (baseline is null)
            return Rejected(quote, null, "baseline_missing");
        if (!IsValidPrice(quote.LastPrice) || !IsValidPrice(quote.PreClose))
            return Rejected(quote, baseline, "invalid_price");

        var auctionPct = baseline.AuctionPct;
        var firstWindowPct = OpeningAuctionStateStore.Pct(quote.LastPrice, quote.PreClose);
        var officialOpenPct = quote.Open > 0m ? OpeningAuctionStateStore.Pct(quote.Open, quote.PreClose) : (decimal?)null;
        var jumpPctPoint = firstWindowPct - auctionPct;
        var amountDelta = quote.Amount - baseline.AuctionAmount;
        var limitDistancePct = quote.LimitUpPrice > 0m
            ? (quote.LimitUpPrice - quote.LastPrice) / quote.LimitUpPrice * 100m
            : (decimal?)null;
        var previousWeakScore = quote.PreviousWeakScore ?? 0m;
        var previousWeakPrecondition = previousWeakScore >= _rules.PreviousWeakScoreMin;
        var weakPrecondition =
            auctionPct <= _rules.AuctionWeakMaxPct ||
            (officialOpenPct.HasValue && officialOpenPct.Value <= _rules.AuctionWeakMaxPct) ||
            previousWeakPrecondition;

        var strongOpenCandidate =
            firstWindowPct >= _rules.StrongOpenFirstWindowMinPct &&
            limitDistancePct.HasValue &&
            limitDistancePct.Value <= _rules.NearLimitDistancePct;

        string? variant = null;
        var auctionProfile = baseline.AuctionProfile;
        var hasAuctionProfile = auctionProfile?.InitialAt is not null && auctionProfile.FinalAt is not null;
        var priceVolumeConfirmed = auctionProfile?.PriceVolumeConfirmed == true;
        var canStrongBroadcast = hasAuctionProfile && priceVolumeConfirmed;
        if (strongOpenCandidate)
        {
            variant = "strong_open_board_attempt";
        }
        else if (auctionProfile is { LateLiftConfirmed: true } &&
            firstWindowPct >= _rules.AuctionLateLiftFirstWindowMinPct &&
            jumpPctPoint >= _rules.AuctionLateLiftJumpMinPctPoint)
        {
            variant = "auction_late_lift";
        }
        else if (auctionPct <= _rules.AuctionWeakMaxPct &&
            jumpPctPoint >= _rules.AuctionGapJumpMinPctPoint &&
            firstWindowPct >= _rules.AuctionGapFirstWindowMinPct)
        {
            variant = "auction_gap_reversal";
        }
        else if ((auctionPct <= _rules.AuctionWeakMaxPct || (officialOpenPct.HasValue && officialOpenPct.Value <= _rules.AuctionWeakMaxPct)) &&
            firstWindowPct >= _rules.LowOpenRedFirstWindowMinPct &&
            jumpPctPoint >= _rules.LowOpenRedJumpMinPctPoint)
        {
            variant = "low_open_red_reversal";
        }

        if (variant is null) return Rejected(quote, baseline, "variant_not_matched");

        var quality = OpeningQuality(quote, baseline);
        var riskKeys = new List<string>(auctionProfile?.RiskFlags ?? []);
        riskKeys.AddRange(quality.RiskKeys);
        if (quote.Amount < _rules.OpeningLiquidityMinAmount) riskKeys.Add("opening_amount_too_small");
        if (quote.Open > 0m && quote.LastPrice < Math.Max(quote.PreClose, quote.Open * _rules.OpeningSupportOpenRatio))
            riskKeys.Add("opening_support_lost");
        if (strongOpenCandidate && !weakPrecondition) riskKeys.Add("weak_precondition_missing");
        if (!hasAuctionProfile)
        {
            if (auctionProfile is null) riskKeys.Add("auction_profile_missing");
            else if (auctionProfile.InitialAt is null) riskKeys.Add("auction_initial_baseline_missing");
            else riskKeys.Add("auction_profile_missing");
        }
        else if (!priceVolumeConfirmed)
        {
            riskKeys.Add("auction_price_volume_unverified");
        }
        if (hasAuctionProfile && !canStrongBroadcast && !HasOpeningCoreEvidence(auctionProfile))
            riskKeys.Add("auction_price_volume_core_missing");
        if (baseline.AuctionAmount <= 0m) riskKeys.Add("auction_amount_missing");
        else if (quote.Amount < baseline.AuctionAmount) riskKeys.Add("amount_regressed");
        if (quote.Volume > 0m && quote.Volume < _rules.MinCurrentVolume) riskKeys.Add("low_liquidity_jump");
        var factors = BuildFactors(
            variant,
            jumpPctPoint,
            firstWindowPct,
            quote.Amount,
            amountDelta,
            limitDistancePct,
            baseline.Quality,
            auctionProfile,
            previousWeakScore,
            quote.PreviousWeakSource);
        var riskFlags = riskKeys.Distinct(StringComparer.Ordinal).Select(RiskFlag).ToArray();
        var riskPenalty = TotalRiskPenalty(riskFlags);
        var score = ClampScore(factors.Sum(item => item.Score) - riskPenalty);
        var confidence = score >= 80m ? "critical" : score >= 60m ? "strong" : "watch";
        var liquidityReview = LiquidityReviewFields(quote.Amount, quote.Volume);
        var result = new OpeningWeakToStrongResult(
            true,
            SignalType,
            DisplayName,
            quote.Code,
            string.IsNullOrWhiteSpace(quote.Name) ? baseline.Name : quote.Name,
            variant,
            confidence,
            score,
            baseline.AuctionFinalPrice,
            Round2(auctionPct),
            quote.Open > 0m ? quote.Open : null,
            officialOpenPct.HasValue ? Round2(officialOpenPct.Value) : null,
            quote.LastPrice,
            Round2(firstWindowPct),
            Round2(jumpPctPoint),
            quote.Amount,
            amountDelta,
            auctionProfile?.InitialAt,
            auctionProfile?.InitialPrice,
            auctionProfile?.InitialPct,
            auctionProfile?.InitialAmount,
            auctionProfile?.LateAt,
            auctionProfile?.LatePrice,
            auctionProfile?.LateStartPct,
            auctionProfile?.LateAmount,
            auctionProfile?.FinalAt,
            auctionProfile?.FinalPrice,
            auctionProfile?.FinalPct,
            auctionProfile?.FinalAmount,
            auctionProfile?.TotalLiftPctPoint,
            auctionProfile?.LateLiftPctPoint,
            auctionProfile?.AmountDelta,
            auctionProfile?.LateAmountDelta,
            auctionProfile?.AmountLiftRatio,
            auctionProfile?.LateAmountLiftRatio,
            priceVolumeConfirmed,
            liquidityReview.Tier,
            "review_only",
            liquidityReview.Basis,
            liquidityReview.Thresholds,
            LiquidityTierVersion,
            limitDistancePct.HasValue ? Round2(limitDistancePct.Value) : null,
            quote.At,
            baseline.Quality,
            baseline.CapturedAt,
            baseline.BridgeTs,
            quote.CapturedAt ?? quote.BridgeTs ?? quote.At,
            baseline.SampleCount,
            AgeMs(quote.CapturedAt ?? quote.BridgeTs ?? quote.At, quote.At),
            AgeMs(baseline.CapturedAt, quote.At),
            baseline.OpeningForcedSample,
            baseline.RequestedCount,
            baseline.ReceivedCount,
            baseline.ElapsedMs,
            baseline.SlowBatches,
            baseline.TruncatedBatches,
            quote.PreviousWeakScore,
            quote.PreviousWeakSignals ?? Array.Empty<string>(),
            quote.PreviousWeakSource,
            quality.AuctionCoverageRatio,
            "pending",
            "pending",
            quote.At,
            quote.LastPrice,
            Round2(firstWindowPct),
            quote.Amount,
            "09:30-09:35已触发，等待盘中确认",
            quote.DryRun || quality.DryRun,
            factors,
            riskFlags,
            null,
            _ruleVersion,
            ConfigHash(_rules));
        _activeSignals[activeKey] = result;
        return result;
    }

    private OpeningWeakToStrongResult EvaluatePreopenCandidate(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline? baseline)
    {
        if (baseline is null)
            return Rejected(quote, null, "baseline_missing");
        if (!IsValidPrice(quote.LastPrice) || !IsValidPrice(quote.PreClose))
            return Rejected(quote, baseline, "invalid_price");

        var auctionProfile = baseline.AuctionProfile;
        var hasAuctionProfile = auctionProfile?.InitialAt is not null && auctionProfile.FinalAt is not null;
        if (!hasAuctionProfile || auctionProfile is null)
            return Rejected(quote, baseline, "preopen_candidate_unconfirmed");

        var quality = OpeningQuality(quote, baseline);
        var riskKeys = new List<string>(auctionProfile.RiskFlags);
        riskKeys.AddRange(quality.RiskKeys);
        if (auctionProfile.PriceVolumeConfirmed != true) riskKeys.Add("auction_price_volume_unverified");
        if (baseline.AuctionAmount <= 0m) riskKeys.Add("auction_amount_missing");
        var riskFlags = riskKeys.Distinct(StringComparer.Ordinal).Select(RiskFlag).ToArray();

        var auctionPct = baseline.AuctionPct;
        var amount = baseline.AuctionAmount;
        var amountDelta = auctionProfile.AmountDelta ?? 0m;
        var factors = BuildFactors(
            "auction_late_lift",
            auctionProfile.TotalLiftPctPoint ?? 0m,
            auctionPct,
            amount,
            amountDelta,
            null,
            baseline.Quality,
            auctionProfile,
            quote.PreviousWeakScore ?? 0m,
            quote.PreviousWeakSource);
        var score = ClampScore(factors.Sum(item => item.Score));
        var confidence = score >= 80m ? "critical" : score >= 60m ? "strong" : "watch";
        var liquidityReview = LiquidityReviewFields(amount, quote.Volume);

        return new OpeningWeakToStrongResult(
            true,
            SignalType,
            DisplayName,
            quote.Code,
            string.IsNullOrWhiteSpace(quote.Name) ? baseline.Name : quote.Name,
            "auction_late_lift",
            confidence,
            score,
            baseline.AuctionFinalPrice,
            Round2(auctionPct),
            null,
            null,
            baseline.AuctionFinalPrice,
            Round2(auctionPct),
            Round2(auctionProfile.TotalLiftPctPoint ?? 0m),
            amount,
            amountDelta,
            auctionProfile.InitialAt,
            auctionProfile.InitialPrice,
            auctionProfile.InitialPct,
            auctionProfile.InitialAmount,
            auctionProfile.LateAt,
            auctionProfile.LatePrice,
            auctionProfile.LateStartPct,
            auctionProfile.LateAmount,
            auctionProfile.FinalAt,
            auctionProfile.FinalPrice,
            auctionProfile.FinalPct,
            auctionProfile.FinalAmount,
            auctionProfile.TotalLiftPctPoint,
            auctionProfile.LateLiftPctPoint,
            auctionProfile.AmountDelta,
            auctionProfile.LateAmountDelta,
            auctionProfile.AmountLiftRatio,
            auctionProfile.LateAmountLiftRatio,
            true,
            liquidityReview.Tier,
            "review_only",
            liquidityReview.Basis,
            liquidityReview.Thresholds,
            LiquidityTierVersion,
            null,
            quote.At,
            baseline.Quality,
            baseline.CapturedAt,
            baseline.BridgeTs,
            quote.CapturedAt ?? quote.BridgeTs ?? quote.At,
            baseline.SampleCount,
            AgeMs(quote.CapturedAt ?? quote.BridgeTs ?? quote.At, quote.At),
            AgeMs(baseline.CapturedAt, quote.At),
            baseline.OpeningForcedSample,
            baseline.RequestedCount,
            baseline.ReceivedCount,
            baseline.ElapsedMs,
            baseline.SlowBatches,
            baseline.TruncatedBatches,
            quote.PreviousWeakScore,
            quote.PreviousWeakSignals ?? Array.Empty<string>(),
            quote.PreviousWeakSource,
            quality.AuctionCoverageRatio,
            "preopen_candidate",
            "preopen_candidate",
            quote.At,
            baseline.AuctionFinalPrice,
            Round2(auctionPct),
            amount,
            "竞价量价齐升，等待开盘承接验证",
            quote.DryRun || quality.DryRun,
            factors,
            riskFlags,
            null,
            _ruleVersion,
            ConfigHash(_rules));
    }

    private OpeningWeakToStrongResult? EvaluateIntradayUpdate(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongResult activeSignal)
    {
        if (!OpeningAuctionStateStore.IsInWindow(quote.At, AfterWindow(_rules.DetectEnd), IntradayConfirmEnd)) return null;
        if (!IsValidPrice(quote.LastPrice) || !IsValidPrice(quote.PreClose)) return null;
        if (activeSignal.IntradayStatus == "failed") return null;

        var intradayPct = OpeningAuctionStateStore.Pct(quote.LastPrice, quote.PreClose);
        var officialOpen = activeSignal.OfficialOpen.GetValueOrDefault(quote.Open);
        var support = Math.Max(
            quote.PreClose,
            officialOpen > 0m ? officialOpen * _rules.OpeningSupportOpenRatio : 0m);

        if (quote.LastPrice < support)
        {
            return activeSignal with
            {
                Confidence = "watch",
                Score = Math.Min(activeSignal.Score, 10m),
                Amount = quote.Amount,
                IntradayStatus = "failed",
                IntradayOutcome = "failed_open_dump",
                IntradayStatusAt = quote.At,
                IntradayPrice = quote.LastPrice,
                IntradayPct = Round2(intradayPct),
                IntradayAmount = quote.Amount,
                IntradayNote = "跌破开盘/昨收支撑，疑似竞价诱多",
                RiskFlags = MergeRiskFlags(activeSignal.RiskFlags, [RiskFlag("intraday_open_dump")]),
            };
        }

        var confirmPct = Math.Max(
            Math.Max(activeSignal.FirstWindowPct.GetValueOrDefault() + IntradayConfirmAdvancePctPoint, activeSignal.OfficialOpenPct.GetValueOrDefault()),
            activeSignal.AuctionPct.GetValueOrDefault());
        if (activeSignal.IntradayStatus == "pending" && intradayPct >= confirmPct && quote.LastPrice >= support)
        {
            return activeSignal with
            {
                Confidence = activeSignal.Confidence == "watch" ? "strong" : activeSignal.Confidence,
                Score = Math.Max(activeSignal.Score, 60m),
                Amount = quote.Amount,
                IntradayStatus = "confirmed",
                IntradayOutcome = "confirmed_strong",
                IntradayStatusAt = quote.At,
                IntradayPrice = quote.LastPrice,
                IntradayPct = Round2(intradayPct),
                IntradayAmount = quote.Amount,
                IntradayNote = "09:35后继续上攻并站稳，盘中确认成功",
            };
        }

        return null;
    }

    private OpeningWeakToStrongResult Rejected(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline? baseline,
        string invalidReason)
    {
        var liquidityReview = LiquidityReviewFields(quote.Amount, quote.Volume);
        return new OpeningWeakToStrongResult(
            false,
            SignalType,
            DisplayName,
            quote.Code,
            string.IsNullOrWhiteSpace(quote.Name) ? baseline?.Name ?? quote.Code : quote.Name,
            null,
            null,
            0m,
            baseline?.AuctionFinalPrice,
            baseline?.AuctionPct,
            null,
            null,
            null,
            null,
            null,
            quote.Amount,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            liquidityReview.Tier,
            "review_only",
            liquidityReview.Basis,
            liquidityReview.Thresholds,
            LiquidityTierVersion,
            null,
            quote.At,
            baseline?.Quality ?? "missing",
            baseline?.CapturedAt,
            baseline?.BridgeTs,
            quote.CapturedAt ?? quote.BridgeTs ?? quote.At,
            baseline?.SampleCount,
            AgeMs(quote.CapturedAt ?? quote.BridgeTs ?? quote.At, quote.At),
            baseline is null ? null : AgeMs(baseline.CapturedAt, quote.At),
            baseline?.OpeningForcedSample ?? false,
            baseline?.RequestedCount,
            baseline?.ReceivedCount,
            baseline?.ElapsedMs,
            baseline?.SlowBatches,
            baseline?.TruncatedBatches,
            quote.PreviousWeakScore,
            quote.PreviousWeakSignals ?? Array.Empty<string>(),
            quote.PreviousWeakSource,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            null,
            quote.DryRun,
            [],
            [RiskFlag(invalidReason)],
            invalidReason,
            _ruleVersion,
            ConfigHash(_rules));
    }

    private IReadOnlyList<OpeningWeakToStrongFactor> BuildFactors(
        string variant,
        decimal jumpPctPoint,
        decimal firstWindowPct,
        decimal amount,
        decimal amountDelta,
        decimal? limitDistancePct,
        string baselineQuality,
        OpeningAuctionPriceVolumeProfile? auctionProfile,
        decimal previousWeakScore,
        string previousWeakSource)
    {
        var factors = new List<OpeningWeakToStrongFactor>();
        if (variant == "auction_late_lift")
        {
            factors.Add(new("auctionLateLift", Round2(auctionProfile?.TotalLiftPctPoint ?? 0m), _rules.AuctionPriceLiftMinPctPoint, _rules.AuctionLateLiftCoreScore));
            factors.Add(new("auctionAmountLiftRatio", Round2(auctionProfile?.AmountLiftRatio ?? 0m), _rules.AuctionAmountLiftMinRatio, _rules.AuctionLateLiftAmountRatioScore));
            factors.Add(new("openStrength", Round2(firstWindowPct), _rules.AuctionLateLiftFirstWindowMinPct, _rules.AuctionLateLiftOpenStrengthScore));
        }
        else if (variant == "strong_open_board_attempt")
        {
            factors.Add(new("nearLimit", Round2(limitDistancePct ?? 99m), _rules.NearLimitDistancePct, _rules.StrongOpenNearLimitScore));
            factors.Add(new("openStrength", Round2(firstWindowPct), _rules.StrongOpenFirstWindowMinPct, _rules.StrongOpenOpenStrengthScore));
        }
        else if (variant == "auction_gap_reversal")
        {
            factors.Add(new("auctionGap", Round2(jumpPctPoint), _rules.AuctionGapJumpMinPctPoint, Math.Min(_rules.AuctionGapMaxScore, 20m + jumpPctPoint * _rules.AuctionGapScoreSlope)));
            factors.Add(new("openStrength", Round2(firstWindowPct), _rules.AuctionGapFirstWindowMinPct, _rules.AuctionGapOpenStrengthScore));
        }
        else
        {
            factors.Add(new("redReversal", Round2(jumpPctPoint), _rules.LowOpenRedJumpMinPctPoint, _rules.LowOpenRedReversalScore));
            factors.Add(new("turnRed", Round2(firstWindowPct), _rules.LowOpenRedFirstWindowMinPct, _rules.LowOpenTurnRedScore));
        }

        factors.Add(new(
            "openingAmount",
            amount,
            _rules.OpeningLiquidityMinAmount,
            amount >= _rules.MinCurrentAmount || amountDelta >= _rules.MinAmountDelta ? _rules.AuctionGapAmountStrongScore : _rules.AuctionGapAmountWeakScore));
        factors.Add(new("baselineQuality", baselineQuality, null, baselineQuality == "good" ? _rules.AuctionGapQualityGoodScore : _rules.AuctionGapQualityDegradedScore));
        if (previousWeakScore >= _rules.PreviousWeakScoreMin)
        {
            factors.Add(new("previousWeakContext", previousWeakScore, _rules.PreviousWeakScoreMin, _rules.PreviousWeakContextScore));
            if (!string.IsNullOrWhiteSpace(previousWeakSource))
            {
                factors.Add(new("previousWeakSource", previousWeakSource, null, 0m));
            }
        }
        return factors;
    }

    private static OpeningWeakToStrongRiskFlag RiskFlag(string key)
    {
        var high = key is "baseline_missing" or "auction_price_volume_core_missing";
        var isProfileMissing = key is "auction_profile_missing" or "auction_initial_baseline_missing";
        return new OpeningWeakToStrongRiskFlag(
            key,
            high ? "high" : isProfileMissing ? "low" : "medium",
            high ? -100m : isProfileMissing ? -10m : -35m);
    }

    private static IReadOnlyList<OpeningWeakToStrongRiskFlag> MergeRiskFlags(
        IReadOnlyList<OpeningWeakToStrongRiskFlag> existing,
        IReadOnlyList<OpeningWeakToStrongRiskFlag> added)
    {
        return existing
            .Concat(added)
            .GroupBy(item => item.Key, StringComparer.Ordinal)
            .Select(group => group.Last())
            .ToArray();
    }

    private static decimal TotalRiskPenalty(IReadOnlyList<OpeningWeakToStrongRiskFlag> riskFlags)
    {
        return riskFlags
            .GroupBy(item => RiskPenaltyGroup(item.Key), StringComparer.Ordinal)
            .Sum(group => group.Max(item => Math.Abs(item.Penalty)));
    }

    private static string RiskPenaltyGroup(string key)
    {
        return key is "auction_price_volume_desynced"
            or "auction_price_volume_unverified"
            or "price_lift_without_volume"
            or "volume_without_price_lift"
            or "auction_late_high_retreated"
            ? "auction_price_volume"
            : key;
    }

    private (IReadOnlyList<string> RiskKeys, decimal? AuctionCoverageRatio, bool DryRun) OpeningQuality(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline baseline)
    {
        var riskKeys = new List<string>();
        decimal? auctionCoverageRatio = null;
        if (baseline.RequestedCount is > 0 && baseline.ReceivedCount.HasValue)
        {
            var rawCoverageRatio = (decimal)baseline.ReceivedCount.Value / baseline.RequestedCount.Value;
            auctionCoverageRatio = Round2(rawCoverageRatio);
            if (rawCoverageRatio < _rules.MinAuctionCoverageRatio)
            {
                riskKeys.Add("auction_coverage_low");
            }
        }

        var quoteAgeMs = AgeMs(quote.CapturedAt ?? quote.BridgeTs ?? quote.At, quote.At);
        if (quoteAgeMs.HasValue && quoteAgeMs.Value > _rules.MaxQuoteAgeMs)
        {
            riskKeys.Add("quote_time_untrusted");
        }
        if (!OpeningAuctionStateStore.IsInWindow(baseline.CapturedAt, _rules.AuctionStart, _rules.AuctionEnd))
        {
            riskKeys.Add("auction_time_untrusted");
        }

        var dryRun = riskKeys.Any(IsQualityDryRunRisk);
        return (riskKeys, auctionCoverageRatio, dryRun);
    }

    private (string Tier, string Basis, string Thresholds) LiquidityReviewFields(decimal amount, decimal volume)
    {
        return (
            LiquidityTier(amount, volume),
            $"amount={DecimalText(amount)};volume={DecimalText(volume)}",
            $"openingLiquidityMinAmount={DecimalText(_rules.OpeningLiquidityMinAmount)};" +
            $"minCurrentAmount={DecimalText(_rules.MinCurrentAmount)};hotAmount={DecimalText(HotAmount)};" +
            $"minCurrentVolume={DecimalText(_rules.MinCurrentVolume)}");
    }

    private string LiquidityTier(decimal amount, decimal volume)
    {
        if (amount <= 0m) return "unknown";
        if (amount < _rules.OpeningLiquidityMinAmount ||
            (volume > 0m && volume < _rules.MinCurrentVolume))
            return "thin";
        if (amount >= HotAmount) return "hot";
        if (amount >= _rules.MinCurrentAmount) return "active";
        return "normal";
    }

    private static bool IsQualityDryRunRisk(string key)
    {
        return key is "auction_coverage_low" or "quote_time_untrusted" or "auction_time_untrusted";
    }

    private static bool HasOpeningCoreEvidence(OpeningAuctionPriceVolumeProfile? profile)
    {
        if (profile is null || profile.InitialAt is null || profile.FinalAt is null) return false;
        return profile.PriceVolumeConfirmed ||
            (profile.TotalLiftPctPoint ?? 0m) >= 0.5m ||
            (profile.AmountLiftRatio ?? 0m) >= 0.35m;
    }

    private static int? AgeMs(DateTimeOffset? from, DateTimeOffset to)
    {
        if (!from.HasValue) return null;
        var elapsed = to - from.Value;
        return Math.Max(0, (int)Math.Round(elapsed.TotalMilliseconds));
    }

    private static bool IsValidPrice(decimal value) => value > 0m;
    private static decimal Round2(decimal value) => Math.Round(value, 2, MidpointRounding.AwayFromZero);
    private static decimal ClampScore(decimal value) => Math.Max(0m, Math.Min(100m, Math.Round(value, 0, MidpointRounding.AwayFromZero)));
    private static string DecimalText(decimal value) => value.ToString("0.#############################", CultureInfo.InvariantCulture);

    private static string AfterWindow(string value)
    {
        var time = TimeSpan.Parse(value).Add(TimeSpan.FromSeconds(1));
        if (time >= TimeSpan.FromDays(1)) time = TimeSpan.FromDays(1).Subtract(TimeSpan.FromSeconds(1));
        return time.ToString(@"hh\:mm\:ss", CultureInfo.InvariantCulture);
    }

    private static string BeforeWindow(string value)
    {
        var time = TimeSpan.Parse(value).Subtract(TimeSpan.FromSeconds(1));
        if (time < TimeSpan.Zero) time = TimeSpan.Zero;
        return time.ToString(@"hh\:mm\:ss", CultureInfo.InvariantCulture);
    }

    private static string TradingDate(DateTimeOffset timestamp)
    {
        return timestamp.ToLocalTime().ToString("yyyy-MM-dd");
    }

    private static string BaselineKey(string code, string tradingDate)
    {
        return $"{tradingDate}:{code}";
    }

    private static string ConfigHash(OpeningWeakToStrongRules rules)
    {
        var values = new SortedDictionary<string, object>(StringComparer.Ordinal)
        {
            ["auctionEnd"] = rules.AuctionEnd,
            ["auctionGapFirstWindowMinPct"] = rules.AuctionGapFirstWindowMinPct,
            ["auctionGapJumpMinPctPoint"] = rules.AuctionGapJumpMinPctPoint,
            ["auctionAmountLiftMinRatio"] = rules.AuctionAmountLiftMinRatio,
            ["auctionLateHighRetreatPctPoint"] = rules.AuctionLateHighRetreatPctPoint,
            ["auctionLateLiftFinalMinPct"] = rules.AuctionLateLiftFinalMinPct,
            ["auctionLateLiftFirstWindowMinPct"] = rules.AuctionLateLiftFirstWindowMinPct,
            ["auctionLateLiftJumpMinPctPoint"] = rules.AuctionLateLiftJumpMinPctPoint,
            ["auctionLateLiftStart"] = rules.AuctionLateLiftStart,
            ["auctionLateLiftTotalMinPctPoint"] = rules.AuctionLateLiftTotalMinPctPoint,
            ["auctionLateAmountLiftMinRatio"] = rules.AuctionLateAmountLiftMinRatio,
            ["auctionLatePriceLiftMinPctPoint"] = rules.AuctionLatePriceLiftMinPctPoint,
            ["auctionPriceLiftMinPctPoint"] = rules.AuctionPriceLiftMinPctPoint,
            ["auctionStart"] = rules.AuctionStart,
            ["auctionTrendStart"] = rules.AuctionTrendStart,
            ["auctionWeakMaxPct"] = rules.AuctionWeakMaxPct,
            ["detectEnd"] = rules.DetectEnd,
            ["detectStart"] = rules.DetectStart,
            ["initialBaselineEnd"] = rules.InitialBaselineEnd,
            ["initialBaselineStart"] = rules.InitialBaselineStart,
            ["lowOpenRedFirstWindowMinPct"] = rules.LowOpenRedFirstWindowMinPct,
            ["lowOpenRedJumpMinPctPoint"] = rules.LowOpenRedJumpMinPctPoint,
            ["minAmountDelta"] = rules.MinAmountDelta,
            ["maxQuoteAgeMs"] = rules.MaxQuoteAgeMs,
            ["minAuctionCoverageRatio"] = rules.MinAuctionCoverageRatio,
            ["minCurrentAmount"] = rules.MinCurrentAmount,
            ["minCurrentVolume"] = rules.MinCurrentVolume,
            ["nearLimitDistancePct"] = rules.NearLimitDistancePct,
            ["openingLiquidityMinAmount"] = rules.OpeningLiquidityMinAmount,
            ["openingSupportOpenRatio"] = rules.OpeningSupportOpenRatio,
            ["previousWeakScoreMin"] = rules.PreviousWeakScoreMin,
            ["strongOpenFirstWindowMinPct"] = rules.StrongOpenFirstWindowMinPct,
            ["auctionGapMaxScore"] = rules.AuctionGapMaxScore,
            ["auctionGapScoreSlope"] = rules.AuctionGapScoreSlope,
            ["auctionGapOpenStrengthScore"] = rules.AuctionGapOpenStrengthScore,
            ["auctionGapAmountStrongScore"] = rules.AuctionGapAmountStrongScore,
            ["auctionGapAmountWeakScore"] = rules.AuctionGapAmountWeakScore,
            ["auctionGapQualityGoodScore"] = rules.AuctionGapQualityGoodScore,
            ["auctionGapQualityDegradedScore"] = rules.AuctionGapQualityDegradedScore,
            ["auctionLateLiftCoreScore"] = rules.AuctionLateLiftCoreScore,
            ["auctionLateLiftAmountRatioScore"] = rules.AuctionLateLiftAmountRatioScore,
            ["auctionLateLiftOpenStrengthScore"] = rules.AuctionLateLiftOpenStrengthScore,
            ["strongOpenNearLimitScore"] = rules.StrongOpenNearLimitScore,
            ["strongOpenOpenStrengthScore"] = rules.StrongOpenOpenStrengthScore,
            ["lowOpenRedReversalScore"] = rules.LowOpenRedReversalScore,
            ["lowOpenTurnRedScore"] = rules.LowOpenTurnRedScore,
            ["previousWeakContextScore"] = rules.PreviousWeakContextScore,
        };
        var text = "{" + string.Join(",", values.Select(item => $"\"{item.Key}\":{JsonValue(item.Value)}")) + "}";
        uint hash = 2166136261;
        foreach (var value in text)
        {
            hash ^= value;
            hash *= 16777619;
        }
        return $"owts-{hash:x8}";
    }

    private static string JsonValue(object value)
    {
        return value switch
        {
            string text => $"\"{text}\"",
            decimal number => number.ToString("0.#############################", CultureInfo.InvariantCulture),
            _ => Convert.ToString(value, CultureInfo.InvariantCulture) ?? "",
        };
    }
}
