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
    decimal AuctionLateLiftAmountDeltaMin,
    decimal AuctionLateLiftLateAmountDeltaMin,
    decimal AuctionLateLiftFirstWindowMinPct,
    decimal AuctionLateLiftJumpMinPctPoint,
    decimal AuctionLateHighRetreatPctPoint,
    decimal PreviousWeakScoreMin,
    decimal MinAuctionCoverageRatio,
    int MaxQuoteAgeMs,
    decimal MinCurrentVolume,
    decimal OpeningSupportOpenRatio)
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
            GetDecimalOrDefault(element, "openingSupportOpenRatio", 0.995m));
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
    DateTimeOffset? FinalBaselineAt,
    decimal? FinalBaselinePrice,
    decimal? FinalBaselinePct,
    decimal? FinalBaselineAmount,
    decimal? AuctionPriceLiftPctPoint,
    decimal? AuctionAmountLiftRatio,
    decimal? LateAmountLiftRatio,
    bool? PriceVolumeConfirmed,
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
    DateTimeOffset? FinalBaselineAt,
    decimal? FinalBaselinePrice,
    decimal? FinalBaselinePct,
    decimal? FinalBaselineAmount,
    decimal? AuctionPriceLiftPctPoint,
    decimal? AuctionAmountLiftRatio,
    decimal? LateAmountLiftRatio,
    bool? PriceVolumeConfirmed,
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
                !highRetreated &&
                finalPct >= rules.AuctionLateLiftFinalMinPct,
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
    private readonly OpeningWeakToStrongRules _rules;
    private readonly string _ruleVersion;

    public OpeningWeakToStrongDetector(
        OpeningWeakToStrongRules rules,
        string ruleVersion = "opening-weak-to-strong.v1")
    {
        _rules = rules;
        _ruleVersion = ruleVersion;
    }

    public OpeningWeakToStrongResult Evaluate(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline? baseline)
    {
        if (!OpeningAuctionStateStore.IsInWindow(quote.At, _rules.DetectStart, _rules.DetectEnd))
            return Rejected(quote, baseline, "outside_detection_window");
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

        if (quote.Amount < _rules.OpeningLiquidityMinAmount)
            return Rejected(quote, baseline, "opening_amount_too_small");
        if (quote.Open > 0m && quote.LastPrice < Math.Max(quote.PreClose, quote.Open * _rules.OpeningSupportOpenRatio))
            return Rejected(quote, baseline, "opening_support_lost");

        var strongOpenCandidate =
            firstWindowPct >= _rules.StrongOpenFirstWindowMinPct &&
            limitDistancePct.HasValue &&
            limitDistancePct.Value <= _rules.NearLimitDistancePct;
        if (strongOpenCandidate && !weakPrecondition)
            return Rejected(quote, baseline, "weak_precondition_missing");

        string? variant = null;
        var auctionProfile = baseline.AuctionProfile;
        var hasAuctionProfile = auctionProfile?.InitialAt is not null && auctionProfile.FinalAt is not null;
        var priceVolumeConfirmed = auctionProfile?.PriceVolumeConfirmed == true;
        var canStrongBroadcast = hasAuctionProfile && priceVolumeConfirmed;
        if (strongOpenCandidate && weakPrecondition)
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
        else if ((auctionPct <= 0m || (officialOpenPct.HasValue && officialOpenPct.Value <= _rules.AuctionWeakMaxPct)) &&
            firstWindowPct >= _rules.LowOpenRedFirstWindowMinPct &&
            jumpPctPoint >= _rules.LowOpenRedJumpMinPctPoint)
        {
            variant = "low_open_red_reversal";
        }

        if (variant is null) return Rejected(quote, baseline, "variant_not_matched");
        if (hasAuctionProfile && !canStrongBroadcast && !HasOpeningCoreEvidence(auctionProfile))
            return Rejected(quote, baseline, "auction_price_volume_core_missing");

        var quality = OpeningQuality(quote, baseline);
        var riskKeys = new List<string>(auctionProfile?.RiskFlags ?? []);
        riskKeys.AddRange(quality.RiskKeys);
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
        var confidence = riskFlags.Length > 0
            ? "watch"
            : score >= 80m ? "critical" : score >= 60m ? "strong" : "watch";
        return new OpeningWeakToStrongResult(
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
            auctionProfile?.FinalAt,
            auctionProfile?.FinalPrice,
            auctionProfile?.FinalPct,
            auctionProfile?.FinalAmount,
            auctionProfile?.TotalLiftPctPoint,
            auctionProfile?.AmountLiftRatio,
            auctionProfile?.LateAmountLiftRatio,
            priceVolumeConfirmed,
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
            quote.DryRun || quality.DryRun,
            factors,
            riskFlags,
            null,
            _ruleVersion,
            ConfigHash(_rules));
    }

    private OpeningWeakToStrongResult Rejected(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline? baseline,
        string invalidReason)
    {
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
            factors.Add(new("auctionLateLift", Round2(auctionProfile?.TotalLiftPctPoint ?? 0m), _rules.AuctionPriceLiftMinPctPoint, 24m));
            factors.Add(new("auctionAmountLiftRatio", Round2(auctionProfile?.AmountLiftRatio ?? 0m), _rules.AuctionAmountLiftMinRatio, 18m));
            factors.Add(new("openStrength", Round2(firstWindowPct), _rules.AuctionLateLiftFirstWindowMinPct, 18m));
        }
        else if (variant == "strong_open_board_attempt")
        {
            factors.Add(new("nearLimit", Round2(limitDistancePct ?? 99m), _rules.NearLimitDistancePct, 30m));
            factors.Add(new("openStrength", Round2(firstWindowPct), _rules.StrongOpenFirstWindowMinPct, 25m));
        }
        else if (variant == "auction_gap_reversal")
        {
            factors.Add(new("auctionGap", Round2(jumpPctPoint), _rules.AuctionGapJumpMinPctPoint, Math.Min(35m, 20m + jumpPctPoint * 3m)));
            factors.Add(new("openStrength", Round2(firstWindowPct), _rules.AuctionGapFirstWindowMinPct, 10m));
        }
        else
        {
            factors.Add(new("redReversal", Round2(jumpPctPoint), _rules.LowOpenRedJumpMinPctPoint, 28m));
            factors.Add(new("turnRed", Round2(firstWindowPct), _rules.LowOpenRedFirstWindowMinPct, 12m));
        }

        factors.Add(new(
            "openingAmount",
            amount,
            _rules.OpeningLiquidityMinAmount,
            amount >= _rules.MinCurrentAmount || amountDelta >= _rules.MinAmountDelta ? 18m : 8m));
        factors.Add(new("baselineQuality", baselineQuality, null, baselineQuality == "good" ? 10m : 4m));
        if (previousWeakScore >= _rules.PreviousWeakScoreMin)
        {
            factors.Add(new("previousWeakContext", previousWeakScore, _rules.PreviousWeakScoreMin, 12m));
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
        return new OpeningWeakToStrongRiskFlag(key, high ? "high" : "medium", high ? -100m : -35m);
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

    private static string ConfigHash(OpeningWeakToStrongRules rules)
    {
        var values = new SortedDictionary<string, object>(StringComparer.Ordinal)
        {
            ["auctionEnd"] = rules.AuctionEnd,
            ["auctionGapFirstWindowMinPct"] = rules.AuctionGapFirstWindowMinPct,
            ["auctionGapJumpMinPctPoint"] = rules.AuctionGapJumpMinPctPoint,
            ["auctionAmountLiftMinRatio"] = rules.AuctionAmountLiftMinRatio,
            ["auctionLateHighRetreatPctPoint"] = rules.AuctionLateHighRetreatPctPoint,
            ["auctionLateLiftAmountDeltaMin"] = rules.AuctionLateLiftAmountDeltaMin,
            ["auctionLateLiftFinalMinPct"] = rules.AuctionLateLiftFinalMinPct,
            ["auctionLateLiftFirstWindowMinPct"] = rules.AuctionLateLiftFirstWindowMinPct,
            ["auctionLateLiftJumpMinPctPoint"] = rules.AuctionLateLiftJumpMinPctPoint,
            ["auctionLateLiftLateAmountDeltaMin"] = rules.AuctionLateLiftLateAmountDeltaMin,
            ["auctionLateLiftLateMinPctPoint"] = rules.AuctionLateLiftLateMinPctPoint,
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
