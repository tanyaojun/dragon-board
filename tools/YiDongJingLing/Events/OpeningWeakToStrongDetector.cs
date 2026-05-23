using System.Text;
using System.Text.Json;

namespace YiDongJingLing.Events;

public sealed record OpeningWeakToStrongRules(
    string AuctionTrendStart,
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
    string AuctionLateLiftStart,
    decimal AuctionLateLiftTotalMinPctPoint,
    decimal AuctionLateLiftLateMinPctPoint,
    decimal AuctionLateLiftFinalMinPct,
    decimal AuctionLateLiftAmountDeltaMin,
    decimal AuctionLateLiftLateAmountDeltaMin,
    decimal AuctionLateLiftFirstWindowMinPct,
    decimal AuctionLateLiftJumpMinPctPoint,
    decimal AuctionLateHighRetreatPctPoint)
{
    public static OpeningWeakToStrongRules FromJson(JsonElement element)
    {
        return new OpeningWeakToStrongRules(
            GetString(element, "auctionTrendStart"),
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
            GetString(element, "auctionLateLiftStart"),
            GetDecimal(element, "auctionLateLiftTotalMinPctPoint"),
            GetDecimal(element, "auctionLateLiftLateMinPctPoint"),
            GetDecimal(element, "auctionLateLiftFinalMinPct"),
            GetDecimal(element, "auctionLateLiftAmountDeltaMin"),
            GetDecimal(element, "auctionLateLiftLateAmountDeltaMin"),
            GetDecimal(element, "auctionLateLiftFirstWindowMinPct"),
            GetDecimal(element, "auctionLateLiftJumpMinPctPoint"),
            GetDecimal(element, "auctionLateHighRetreatPctPoint"));
    }

    private static string GetString(JsonElement element, string name)
    {
        return element.GetProperty(name).GetString() ?? "";
    }

    private static decimal GetDecimal(JsonElement element, string name)
    {
        return element.GetProperty(name).GetDecimal();
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
    DateTimeOffset? BridgeTs)
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
            GetDateTimeOffset(element, "bridgeTs"));
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

    private static DateTimeOffset? GetDateTimeOffset(JsonElement element, string name)
    {
        var value = GetString(element, name);
        return string.IsNullOrWhiteSpace(value) ? null : DateTimeOffset.Parse(value);
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
    OpeningAuctionPriceVolumeProfile? AuctionProfile);

public sealed record OpeningAuctionPriceVolumeProfile(
    int SampleCount,
    decimal? StartPct,
    decimal? LateStartPct,
    decimal? FinalPct,
    decimal? HighPct,
    decimal? TotalLiftPctPoint,
    decimal? LateLiftPctPoint,
    decimal? AmountDelta,
    decimal? LateAmountDelta,
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
    decimal? LimitDistancePct,
    DateTimeOffset TriggerAt,
    string BaselineQuality,
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
    decimal? LimitDistancePct,
    string BaselineQuality,
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
        if (IsInWindow(quote.At, _rules.AuctionTrendStart, _rules.AuctionEnd))
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
        }

        if (!IsInWindow(quote.At, _rules.AuctionStart, _rules.AuctionEnd)) return;

        _baselines.TryGetValue(key, out var previous);
        var capturedAt = quote.CapturedAt ?? quote.At;
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
            (previous?.SampleCount ?? 0) + 1,
            quality,
            BuildAuctionProfile(_samples.TryGetValue(key, out var samplesForProfile) ? samplesForProfile : [quote], _rules));
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

    private static decimal Round2(decimal value) => Math.Round(value, 2, MidpointRounding.AwayFromZero);

    private static bool Meets(decimal value, decimal threshold) => value + 0.000001m >= threshold;

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

        var first = trusted[0];
        var final = trusted[^1];
        var lateStartTime = TimeSpan.Parse(rules.AuctionLateLiftStart);
        var lateStart = trusted.FirstOrDefault(item => item.At.ToLocalTime().TimeOfDay >= lateStartTime) ?? final;
        var startPct = Pct(first.LastPrice, first.PreClose);
        var lateStartPct = Pct(lateStart.LastPrice, lateStart.PreClose);
        var finalPct = Pct(final.LastPrice, final.PreClose);
        var highPct = trusted.Max(item => Pct(item.LastPrice, item.PreClose));
        var totalLiftPctPoint = finalPct - startPct;
        var lateLiftPctPoint = finalPct - lateStartPct;
        var amountDelta = final.Amount - first.Amount;
        var lateAmountDelta = final.Amount - lateStart.Amount;
        var priceLifted = Meets(totalLiftPctPoint, rules.AuctionLateLiftTotalMinPctPoint) ||
            Meets(lateLiftPctPoint, rules.AuctionLateLiftLateMinPctPoint);
        var amountExpanded = Meets(amountDelta, rules.AuctionLateLiftAmountDeltaMin) ||
            Meets(lateAmountDelta, rules.AuctionLateLiftLateAmountDeltaMin);
        var highRetreated = Meets(highPct - finalPct, rules.AuctionLateHighRetreatPctPoint);
        var riskFlags = new List<string>();
        if (priceLifted && !amountExpanded) riskFlags.Add("price_lift_without_volume");
        if (amountExpanded && !priceLifted) riskFlags.Add("volume_without_price_lift");
        if (highRetreated) riskFlags.Add("auction_late_high_retreated");

        return new OpeningAuctionPriceVolumeProfile(
            trusted.Length,
            Round2(startPct),
            Round2(lateStartPct),
            Round2(finalPct),
            Round2(highPct),
            Round2(totalLiftPctPoint),
            Round2(lateLiftPctPoint),
            amountDelta,
            lateAmountDelta,
            priceLifted && amountExpanded && !highRetreated && finalPct >= rules.AuctionLateLiftFinalMinPct,
            riskFlags);
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
        var amountOk = quote.Amount >= _rules.MinCurrentAmount || amountDelta >= _rules.MinAmountDelta;
        var weakPrecondition =
            auctionPct <= _rules.AuctionWeakMaxPct ||
            (officialOpenPct.HasValue && officialOpenPct.Value <= _rules.AuctionWeakMaxPct);

        if (!amountOk) return Rejected(quote, baseline, "opening_amount_too_small");

        var strongOpenCandidate =
            firstWindowPct >= _rules.StrongOpenFirstWindowMinPct &&
            limitDistancePct.HasValue &&
            limitDistancePct.Value <= _rules.NearLimitDistancePct;
        if (strongOpenCandidate && !weakPrecondition)
            return Rejected(quote, baseline, "weak_precondition_missing");

        string? variant = null;
        var auctionProfile = baseline.AuctionProfile;
        if (auctionProfile is { LateLiftConfirmed: true } &&
            firstWindowPct >= _rules.AuctionLateLiftFirstWindowMinPct &&
            jumpPctPoint >= _rules.AuctionLateLiftJumpMinPctPoint)
        {
            variant = "auction_late_lift";
        }
        else if (strongOpenCandidate && weakPrecondition)
        {
            variant = "strong_open_board_attempt";
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

        var factors = BuildFactors(variant, jumpPctPoint, firstWindowPct, quote.Amount, amountDelta, limitDistancePct, baseline.Quality, auctionProfile);
        var riskFlags = (auctionProfile?.RiskFlags ?? []).Select(RiskFlag).ToArray();
        var riskPenalty = riskFlags.Sum(item => Math.Abs(item.Penalty));
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
            limitDistancePct.HasValue ? Round2(limitDistancePct.Value) : null,
            quote.At,
            baseline.Quality,
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
            quote.At,
            baseline?.Quality ?? "missing",
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
        OpeningAuctionPriceVolumeProfile? auctionProfile)
    {
        var factors = new List<OpeningWeakToStrongFactor>();
        if (variant == "auction_late_lift")
        {
            factors.Add(new("auctionLateLift", Round2(auctionProfile?.TotalLiftPctPoint ?? 0m), _rules.AuctionLateLiftTotalMinPctPoint, 24m));
            factors.Add(new("auctionLateAmount", auctionProfile?.LateAmountDelta ?? 0m, _rules.AuctionLateLiftLateAmountDeltaMin, 18m));
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

        factors.Add(new("openingAmount", amount, _rules.MinCurrentAmount, amountDelta >= _rules.MinAmountDelta ? 18m : 12m));
        factors.Add(new("baselineQuality", baselineQuality, null, baselineQuality == "good" ? 10m : 4m));
        return factors;
    }

    private static OpeningWeakToStrongRiskFlag RiskFlag(string key)
    {
        return new OpeningWeakToStrongRiskFlag(key, key == "baseline_missing" ? "high" : "medium", key == "baseline_missing" ? -100m : -35m);
    }

    private static bool IsValidPrice(decimal value) => value > 0m;
    private static decimal Round2(decimal value) => Math.Round(value, 2, MidpointRounding.AwayFromZero);
    private static decimal ClampScore(decimal value) => Math.Max(0m, Math.Min(100m, Math.Round(value, 0, MidpointRounding.AwayFromZero)));

    private static string ConfigHash(OpeningWeakToStrongRules rules)
    {
        var text = string.Join("|",
            rules.AuctionStart,
            rules.AuctionEnd,
            rules.DetectStart,
            rules.DetectEnd,
            rules.AuctionWeakMaxPct,
            rules.AuctionGapJumpMinPctPoint,
            rules.AuctionGapFirstWindowMinPct,
            rules.LowOpenRedJumpMinPctPoint,
            rules.LowOpenRedFirstWindowMinPct,
            rules.StrongOpenFirstWindowMinPct,
            rules.NearLimitDistancePct,
            rules.MinCurrentAmount,
            rules.MinAmountDelta);
        uint hash = 2166136261;
        foreach (var value in Encoding.UTF8.GetBytes(text))
        {
            hash ^= value;
            hash *= 16777619;
        }
        return $"owts-{hash:x8}";
    }
}
