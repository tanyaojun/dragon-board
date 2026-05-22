using System.Text;
using System.Text.Json;

namespace YiDongJingLing.Events;

public sealed record OpeningWeakToStrongRules(
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
    decimal MinAmountDelta)
{
    public static OpeningWeakToStrongRules FromJson(JsonElement element)
    {
        return new OpeningWeakToStrongRules(
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
            GetDecimal(element, "minAmountDelta"));
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
    string Quality);

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

    public OpeningAuctionStateStore(OpeningWeakToStrongRules rules)
    {
        _rules = rules;
    }

    public void Capture(OpeningWeakToStrongQuote quote)
    {
        if (!IsInWindow(quote.At, _rules.AuctionStart, _rules.AuctionEnd)) return;
        if (!IsValidPrice(quote.LastPrice) || !IsValidPrice(quote.PreClose)) return;

        var tradingDate = TradingDate(quote.At);
        var key = BaselineKey(quote.Code, tradingDate);
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
            quality);
    }

    public OpeningWeakToStrongBaseline? GetBaseline(string code, DateTimeOffset timestamp)
    {
        return _baselines.TryGetValue(BaselineKey(code, TradingDate(timestamp)), out var baseline) ? baseline : null;
    }

    public void Clear() => _baselines.Clear();

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
        if (strongOpenCandidate && weakPrecondition)
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

        var factors = BuildFactors(variant, jumpPctPoint, firstWindowPct, quote.Amount, amountDelta, limitDistancePct, baseline.Quality);
        var score = ClampScore(factors.Sum(item => item.Score));
        return new OpeningWeakToStrongResult(
            true,
            SignalType,
            DisplayName,
            quote.Code,
            string.IsNullOrWhiteSpace(quote.Name) ? baseline.Name : quote.Name,
            variant,
            score >= 80m ? "critical" : score >= 60m ? "strong" : "watch",
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
            [],
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
        string baselineQuality)
    {
        var factors = new List<OpeningWeakToStrongFactor>();
        if (variant == "strong_open_board_attempt")
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
        return new OpeningWeakToStrongRiskFlag(key, key == "baseline_missing" ? "high" : "medium", -100m);
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
