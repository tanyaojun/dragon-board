using System.Globalization;
using System.Text;
using System.Text.Json;
using static YiDongJingLing.Events.OpeningWeakToStrongMath;

namespace YiDongJingLing.Events;

public sealed record OpeningWeakToStrongRules(
    string AuctionTrendStart,
    string InitialBaselineStart,
    string InitialBaselineEnd,
    string AuctionLateLiftStart,
    string AuctionStart,
    string AuctionEnd,
    string DetectStart,
    string DetectEnd,
    decimal OpeningSupportImproveMinPctPoint,
    decimal OpeningSupportAmountMinRatio,
    decimal AuctionPriceLiftMinPctPoint,
    decimal AuctionAmountLiftMinRatio,
    decimal AuctionLatePriceLiftMinPctPoint,
    decimal AuctionLateAmountLiftMinRatio,
    int CheckpointWindowThresholdSeconds = 30)
{
    public static OpeningWeakToStrongRules FromJson(JsonElement element)
    {
        return new OpeningWeakToStrongRules(
            GetStringOrDefault(element, "auctionTrendStart", "09:20:00"),
            GetStringOrDefault(element, "initialBaselineStart", "09:20:00"),
            GetStringOrDefault(element, "initialBaselineEnd", "09:20:30"),
            GetStringOrDefault(element, "auctionLateLiftStart", "09:24:00"),
            GetStringOrDefault(element, "auctionStart", "09:24:50"),
            GetStringOrDefault(element, "auctionEnd", "09:25:10"),
            GetStringOrDefault(element, "detectStart", "09:30:00"),
            GetStringOrDefault(element, "detectEnd", "09:35:00"),
            GetDecimalOrDefault(element, "openingSupportImproveMinPctPoint", 1.2m),
            GetDecimalOrDefault(element, "openingSupportAmountMinRatio", 1m),
            GetDecimalOrDefault(element, "auctionPriceLiftMinPctPoint", 0.8m),
            GetDecimalOrDefault(element, "auctionAmountLiftMinRatio", 0.35m),
            GetDecimalOrDefault(element, "auctionLatePriceLiftMinPctPoint", 0.3m),
            GetDecimalOrDefault(element, "auctionLateAmountLiftMinRatio", 0.2m),
            GetIntOrDefault(element, "checkpointWindowThresholdSeconds", 30));
    }

    private static string GetStringOrDefault(JsonElement element, string name, string fallback)
    {
        return element.TryGetProperty(name, out var property) ? property.GetString() ?? fallback : fallback;
    }

    private static int GetIntOrDefault(JsonElement element, string name, int fallback)
    {
        return element.TryGetProperty(name, out var property) && property.ValueKind is JsonValueKind.Number
            ? property.GetInt32()
            : fallback;
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
    int? TruncatedBatches = null)
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
            GetInt(element, "truncatedBatches"));
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
    DateTimeOffset? LateBaselineAt,
    decimal? LateBaselinePrice,
    decimal? LateBaselinePct,
    decimal? LateBaselineAmount,
    DateTimeOffset? FinalAt,
    decimal? FinalPrice,
    decimal? FinalAmount,
    decimal? FinalPct,
    decimal? TotalLiftPctPoint,
    decimal? LatePriceLiftPctPoint,
    decimal? AmountDelta,
    decimal? LateAmountDelta,
    decimal? AmountLiftRatio,
    decimal? LateAmountLiftRatio,
    bool PriceVolumeConfirmed);

public sealed record OpeningWeakToStrongResult(
    bool Triggered,
    string SignalType,
    string DisplayName,
    string Code,
    string Name,
    string Stage,
    string Status,
    bool VoiceEligible,
    string Reason,
    DateTimeOffset Time,
    decimal Price,
    decimal Pct,
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
    decimal? AuctionAmountDelta,
    decimal? AuctionAmountLiftRatio,
    bool? PriceVolumeConfirmed,
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
    string? InvalidReason,
    string RuleVersion,
    string ConfigHash);

public sealed record OpeningWeakToStrongSignal(
    string TradingDate,
    string Code,
    string Name,
    string SignalType,
    string Stage,
    string Status,
    bool VoiceEligible,
    string Reason,
    DateTimeOffset Time,
    decimal Price,
    decimal Pct,
    DateTimeOffset TriggerAt,
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
    decimal? AuctionAmountDelta,
    decimal? AuctionAmountLiftRatio,
    bool? PriceVolumeConfirmed,
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
    string RuleVersion,
    string ConfigHash);

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
            samples.Sort((left, right) => left.At.ToLocalTime().TimeOfDay.CompareTo(right.At.ToLocalTime().TimeOfDay));
            samplesForProfile = samples.TakeLast(16).ToList();
            _samples[key] = samplesForProfile;
        }

        var previous = _baselines.GetValueOrDefault(key);
        var auctionProfile = BuildAuctionProfile(samplesForProfile ?? [quote], _rules);
        if (!IsConfirmBaselineTime(quote.At))
        {
            if (previous is not null && inTrendWindow)
            {
                _baselines[key] = previous with { AuctionProfile = auctionProfile };
            }
            return;
        }

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
            Math.Max(previous?.SampleCount ?? 0, CountAuctionBaselineSamples(samplesForProfile ?? [quote], _rules)),
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
        return _baselines.GetValueOrDefault(BaselineKey(code, TradingDate(timestamp)));
    }

    public void Clear()
    {
        _baselines.Clear();
        _samples.Clear();
    }

    public static bool IsInWindow(DateTimeOffset timestamp, string start, string end)
    {
        var value = timestamp.ToLocalTime().TimeOfDay;
        return value >= TimeSpan.Parse(start, CultureInfo.InvariantCulture) &&
            value <= TimeSpan.Parse(end, CultureInfo.InvariantCulture);
    }

    public static decimal Pct(decimal price, decimal preClose) => (price - preClose) / preClose * 100m;

    private static OpeningAuctionPriceVolumeProfile? BuildAuctionProfile(
        IReadOnlyList<OpeningWeakToStrongQuote> samples,
        OpeningWeakToStrongRules rules)
    {
        var trusted = samples
            .Where(item => IsInWindow(item.At, rules.AuctionTrendStart, rules.AuctionEnd))
            .Where(item => IsValidPrice(item.LastPrice) && IsValidPrice(item.PreClose))
            .OrderBy(item => item.At.ToLocalTime().TimeOfDay)
            .ToArray();
        if (trusted.Length < 2) return null;

        var initial = trusted.FirstOrDefault(item => IsInWindow(item.At, rules.InitialBaselineStart, rules.InitialBaselineEnd));
        var final = trusted.LastOrDefault(item => IsConfirmBaselineTime(item.At, rules)) ?? trusted[^1];
        var lateStartTime = TimeSpan.Parse(rules.AuctionLateLiftStart, CultureInfo.InvariantCulture);
        var lateBaseline = trusted.FirstOrDefault(item => item.At.ToLocalTime().TimeOfDay >= lateStartTime) ?? final;
        var startPct = initial is null ? (decimal?)null : Pct(initial.LastPrice, initial.PreClose);
        var lateBaselinePct = Pct(lateBaseline.LastPrice, lateBaseline.PreClose);
        var finalPct = Pct(final.LastPrice, final.PreClose);
        var initialAmount = initial?.Amount;
        var lateBaselineAmount = lateBaseline.Amount;
        var amountDelta = initialAmount.HasValue ? final.Amount - initialAmount.Value : (decimal?)null;
        var lateAmountDelta = final.Amount - lateBaselineAmount;
        var amountLiftRatio = amountDelta.HasValue && initialAmount > 0m ? amountDelta / initialAmount : null;
        decimal? lateAmountLiftRatio = lateBaselineAmount > 0m ? lateAmountDelta / lateBaselineAmount : null;
        var totalLiftPctPoint = startPct.HasValue ? finalPct - startPct.Value : (decimal?)null;
        var latePriceLiftPctPoint = finalPct - lateBaselinePct;
        var priceVolumeConfirmed =
            initial is not null &&
            totalLiftPctPoint.HasValue &&
            amountLiftRatio.HasValue &&
            lateAmountLiftRatio.HasValue &&
            (
                (totalLiftPctPoint.Value >= rules.AuctionPriceLiftMinPctPoint &&
                 amountLiftRatio.Value >= rules.AuctionAmountLiftMinRatio) ||
                (latePriceLiftPctPoint >= rules.AuctionLatePriceLiftMinPctPoint &&
                 lateAmountLiftRatio.Value >= rules.AuctionLateAmountLiftMinRatio)
            );

        return new OpeningAuctionPriceVolumeProfile(
            trusted.Length,
            initial?.At,
            initial?.LastPrice,
            startPct.HasValue ? Round2(startPct.Value) : null,
            initialAmount,
            lateBaseline.At,
            lateBaseline.LastPrice,
            Round2(lateBaselinePct),
            lateBaselineAmount,
            final.At,
            final.LastPrice,
            final.Amount,
            Round2(finalPct),
            totalLiftPctPoint.HasValue ? Round2(totalLiftPctPoint.Value) : null,
            Round2(latePriceLiftPctPoint),
            amountDelta,
            lateAmountDelta,
            amountLiftRatio.HasValue ? Round2(amountLiftRatio.Value) : null,
            lateAmountLiftRatio.HasValue ? Round2(lateAmountLiftRatio.Value) : null,
            priceVolumeConfirmed);
    }

    private static int CountAuctionBaselineSamples(
        IReadOnlyList<OpeningWeakToStrongQuote> samples,
        OpeningWeakToStrongRules rules)
    {
        return samples.Count(item => IsConfirmBaselineTime(item.At, rules));
    }

    private static string TradingDate(DateTimeOffset timestamp)
    {
        return timestamp.ToLocalTime().ToString("yyyy-MM-dd");
    }

    private static string BaselineKey(string code, string tradingDate)
    {
        return $"{tradingDate}:{code}";
    }

    private bool IsConfirmBaselineTime(DateTimeOffset timestamp)
    {
        return IsConfirmBaselineTime(timestamp, _rules);
    }

    private static bool IsConfirmBaselineTime(DateTimeOffset timestamp, OpeningWeakToStrongRules rules)
    {
        return IsInWindow(timestamp, rules.AuctionStart, rules.AuctionEnd);
    }
}

public sealed class OpeningWeakToStrongDetector
{
    public const string ConfirmBaselineTime = "09:25:00";
    private const string SignalType = "opening_weak_to_strong";
    private const string DisplayName = "竞价弱转强";
    private const string GapAnchorTime = "09:30:00";
    private const string TrendAnchorTime = "09:35:00";
    private const string FinalAnchorTime = "10:00:00";
    private readonly OpeningWeakToStrongRules _rules;
    private readonly string _ruleVersion;
    private readonly string _configHash;
    private readonly Dictionary<string, OpeningWeakToStrongResult> _activeSignals = new(StringComparer.Ordinal);
    private readonly HashSet<string> _strongToday = new(StringComparer.Ordinal);

    public OpeningWeakToStrongDetector(
        OpeningWeakToStrongRules rules,
        string ruleVersion = "opening-weak-to-strong.v2")
    {
        _rules = rules;
        _ruleVersion = ruleVersion;
        _configHash = ComputeConfigHash(rules);
    }

    public void Clear()
    {
        _activeSignals.Clear();
    }

    public OpeningWeakToStrongResult Evaluate(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline? baseline)
    {
        var invalid = Rejected(quote, baseline, "not_checkpoint");
        if (!IsValidPrice(quote.LastPrice) || !IsValidPrice(quote.PreClose)) return invalid;

        var activeKey = BaselineKey(quote.Code, TradingDate(quote.At));
        _activeSignals.TryGetValue(activeKey, out var activeSignal);
        var time = quote.At.ToLocalTime().TimeOfDay;
        OpeningWeakToStrongResult? result = null;
        if (OpeningAuctionStateStore.IsInWindow(quote.At, _rules.AuctionStart, _rules.AuctionEnd))
        {
            result = EvaluateAuctionCheckpoint(quote, baseline);
        }
        else if (IsCheckpointWindow(quote.At, GapAnchorTime, _rules.CheckpointWindowThresholdSeconds))
        {
            result = EvaluateGapCheckpoint(quote, baseline, activeSignal);
        }
        else if (IsCheckpointWindow(quote.At, TrendAnchorTime, _rules.CheckpointWindowThresholdSeconds))
        {
            result = EvaluateTrendCheckpoint(quote, baseline, activeSignal);
        }
        else if (IsCheckpointWindow(quote.At, FinalAnchorTime, _rules.CheckpointWindowThresholdSeconds))
        {
            var isAlreadyStrong = _strongToday.Contains(activeKey);
            result = isAlreadyStrong
                ? Rejected(quote, baseline, "already_strong_at_final")
                : CheckpointSignal(
                    quote,
                    baseline,
                    "optionalFinalStatus",
                    false,
                    "10:00窗口结束未转强，记录失败状态",
                    firstWindowPrice: quote.LastPrice,
                    firstWindowPct: Round2(OpeningAuctionStateStore.Pct(quote.LastPrice, quote.PreClose)),
                    amount: quote.Amount);
        }

        if (result is null) return invalid;
        if (result.Triggered)
        {
            _activeSignals[activeKey] = result;
            if (result.Stage is "gapAlert" or "trendConfirm")
            {
                _strongToday.Add(activeKey);
            }
        }
        return result;
    }

    private OpeningWeakToStrongResult EvaluateAuctionCheckpoint(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline? baseline)
    {
        if (baseline?.AuctionProfile?.InitialAt is null)
        {
            return CheckpointSignal(quote, baseline, "auctionConditionFailed", false, "缺少09:20初始基线");
        }

        var profile = baseline.AuctionProfile;
        if (profile.LateBaselineAt is null)
        {
            return CheckpointSignal(quote, baseline, "auctionConditionFailed", false, "缺少09:24临门基线");
        }

        var passed = IsValidPrice(baseline.AuctionFinalPrice) &&
            profile.PriceVolumeConfirmed;
        if (!passed && !OpeningAuctionStateStore.IsInWindow(quote.At, _rules.AuctionStart, _rules.AuctionEnd))
        {
            return CheckpointSignal(quote, baseline, "auctionConditionFailed", false, "竞价量价确认未通过");
        }
        // In window: only emit triggered if passed==true
        // passed==false in window is expected (still building baseline), no triggered event
        if (!passed) {
            return Rejected(quote, baseline, "building_baseline");
        }
        return CheckpointSignal(
            quote,
            baseline,
            "auctionConditionPassed",
            false,
            "09:20总量价与09:24临门量价均通过，列入候选");
    }

    private OpeningWeakToStrongResult EvaluateGapCheckpoint(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline? baseline,
        OpeningWeakToStrongResult? activeSignal)
    {
        if (activeSignal?.Triggered == true && activeSignal?.Stage == "gapAlert")
        {
            return Rejected(quote, baseline, "already_gapAlert");
        }
        if (!HasConfirmBaseline(baseline))
        {
            return Rejected(quote, baseline, "missing_09_25_confirm_baseline");
        }

        var open = quote.Open > 0m ? quote.Open : quote.LastPrice;
        var openPct = OpeningAuctionStateStore.Pct(open, quote.PreClose);
        var firstWindowPct = OpeningAuctionStateStore.Pct(quote.LastPrice, quote.PreClose);
        var improvePctPoint = firstWindowPct - baseline!.AuctionPct;
        var baseAmount = baseline.AuctionAmount;
        var amountRatio = baseAmount > 0m ? quote.Amount / baseAmount : 0m;
        var supported = improvePctPoint >= _rules.OpeningSupportImproveMinPctPoint &&
            quote.LastPrice >= baseline.AuctionFinalPrice &&
            open >= baseline.AuctionFinalPrice &&
            (baseAmount <= 0m || amountRatio >= _rules.OpeningSupportAmountMinRatio);
        return CheckpointSignal(
            quote,
            baseline,
            supported ? "gapAlert" : "noGap",
            supported,
            supported ? "09:30较09:25明显改善，开盘承接转强" : "09:30未形成有效开盘承接转强",
            officialOpen: open,
            officialOpenPct: Round2(openPct),
            firstWindowPrice: quote.LastPrice,
            firstWindowPct: Round2(firstWindowPct),
            jumpPctPoint: Round2(improvePctPoint),
            amount: quote.Amount);
    }

    private OpeningWeakToStrongResult EvaluateTrendCheckpoint(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline? baseline,
        OpeningWeakToStrongResult? activeSignal)
    {
        if (!HasConfirmBaseline(baseline))
        {
            return Rejected(quote, baseline, "missing_09_25_confirm_baseline");
        }

        var open = activeSignal?.OfficialOpen ?? quote.Open;
        var openPct = open > 0m ? OpeningAuctionStateStore.Pct(open, quote.PreClose) : (decimal?)null;
        var currentPct = OpeningAuctionStateStore.Pct(quote.LastPrice, quote.PreClose);
        var baseAmount = baseline?.AuctionAmount ?? 0m;
        var improvePctPoint = baseline is null ? 0m : currentPct - baseline.AuctionPct;
        var strong = open > 0m &&
            quote.LastPrice >= open &&
            baseline is not null &&
            currentPct >= baseline.AuctionPct &&
            improvePctPoint >= _rules.OpeningSupportImproveMinPctPoint &&
            (baseAmount <= 0m || quote.Amount >= baseAmount);
        return CheckpointSignal(
            quote,
            baseline,
            strong ? "trendConfirm" : "trendWeak",
            strong,
            strong ? "09:30到09:35承接延续，开盘反攻确认" : "09:30到09:35承接不足，趋势转弱",
            officialOpen: open > 0m ? open : null,
            officialOpenPct: openPct.HasValue ? Round2(openPct.Value) : null,
            firstWindowPrice: quote.LastPrice,
            firstWindowPct: Round2(currentPct),
            amount: quote.Amount);
    }

    private OpeningWeakToStrongResult CheckpointSignal(
        OpeningWeakToStrongQuote quote,
        OpeningWeakToStrongBaseline? baseline,
        string stage,
        bool voiceEligible,
        string reason,
        decimal? officialOpen = null,
        decimal? officialOpenPct = null,
        decimal? firstWindowPrice = null,
        decimal? firstWindowPct = null,
        decimal? jumpPctPoint = null,
        decimal? amount = null)
    {
        var price = firstWindowPrice ?? quote.LastPrice;
        var pct = firstWindowPct ?? Round2(OpeningAuctionStateStore.Pct(quote.LastPrice, quote.PreClose));
        return new OpeningWeakToStrongResult(
            true,
            SignalType,
            DisplayName,
            quote.Code,
            string.IsNullOrWhiteSpace(quote.Name) ? baseline?.Name ?? quote.Code : quote.Name,
            stage,
            stage,
            voiceEligible,
            reason,
            quote.At,
            price,
            pct,
            baseline?.AuctionFinalPrice,
            baseline is null ? null : Round2(baseline.AuctionPct),
            officialOpen,
            officialOpenPct,
            firstWindowPrice,
            firstWindowPct,
            jumpPctPoint,
            amount ?? quote.Amount,
            null,
            baseline?.AuctionProfile?.InitialAt,
            baseline?.AuctionProfile?.InitialPrice,
            baseline?.AuctionProfile?.InitialPct,
            baseline?.AuctionProfile?.InitialAmount,
            baseline?.AuctionProfile?.FinalAt,
            baseline?.AuctionProfile?.FinalPrice,
            baseline?.AuctionProfile?.FinalPct,
            baseline?.AuctionProfile?.FinalAmount,
            baseline?.AuctionProfile?.TotalLiftPctPoint,
            baseline?.AuctionProfile?.AmountDelta,
            baseline?.AuctionProfile?.AmountLiftRatio,
            baseline?.AuctionProfile?.PriceVolumeConfirmed,
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
            null,
            _ruleVersion,
            _configHash);
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
            "",
            "",
            false,
            invalidReason,
            quote.At,
            quote.LastPrice,
            IsValidPrice(quote.PreClose) && IsValidPrice(quote.LastPrice) ? Round2(OpeningAuctionStateStore.Pct(quote.LastPrice, quote.PreClose)) : 0m,
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
            invalidReason,
            _ruleVersion,
            _configHash);
    }

    private static string TradingDate(DateTimeOffset timestamp)
    {
        return timestamp.ToLocalTime().ToString("yyyy-MM-dd");
    }

    private bool HasConfirmBaseline(OpeningWeakToStrongBaseline? baseline)
    {
        return baseline is not null &&
            OpeningAuctionStateStore.IsInWindow(baseline.CapturedAt, _rules.AuctionStart, _rules.AuctionEnd);
    }

    private static string BaselineKey(string code, string tradingDate)
    {
        return $"{tradingDate}:{code}";
    }

    private static bool IsCheckpointWindow(DateTimeOffset timestamp, string anchor, int thresholdSeconds)
    {
        var delta = timestamp.ToLocalTime().TimeOfDay - TimeSpan.Parse(anchor, CultureInfo.InvariantCulture);
        return delta >= TimeSpan.Zero && delta.TotalSeconds <= thresholdSeconds;
    }

    private static int? AgeMs(DateTimeOffset? from, DateTimeOffset to)
    {
        if (!from.HasValue) return null;
        var elapsed = to - from.Value;
        return elapsed.TotalMilliseconds < 0 ? 0 : (int)Math.Round(elapsed.TotalMilliseconds);
    }

    private static string ComputeConfigHash(OpeningWeakToStrongRules rules)
    {
        var values = new Dictionary<string, object?>
        {
            ["auctionAmountLiftMinRatio"] = rules.AuctionAmountLiftMinRatio,
            ["auctionEnd"] = rules.AuctionEnd,
            ["auctionLateAmountLiftMinRatio"] = rules.AuctionLateAmountLiftMinRatio,
            ["auctionLateLiftStart"] = rules.AuctionLateLiftStart,
            ["auctionLatePriceLiftMinPctPoint"] = rules.AuctionLatePriceLiftMinPctPoint,
            ["auctionPriceLiftMinPctPoint"] = rules.AuctionPriceLiftMinPctPoint,
            ["auctionStart"] = rules.AuctionStart,
            ["auctionTrendStart"] = rules.AuctionTrendStart,
            ["initialBaselineEnd"] = rules.InitialBaselineEnd,
            ["initialBaselineStart"] = rules.InitialBaselineStart,
            ["openingSupportAmountMinRatio"] = rules.OpeningSupportAmountMinRatio,
            ["openingSupportImproveMinPctPoint"] = rules.OpeningSupportImproveMinPctPoint,
            ["checkpointWindowThresholdSeconds"] = rules.CheckpointWindowThresholdSeconds,
            ["detectStart"] = rules.DetectStart,
            ["detectEnd"] = rules.DetectEnd,
        };
        var json = JsonSerializer.Serialize(values.OrderBy(item => item.Key));
        unchecked
        {
            uint hash = 2166136261;
            foreach (var ch in json)
            {
                hash ^= ch;
                hash *= 16777619;
            }
            return $"owts-{hash:x8}";
        }
    }
}

internal static class OpeningWeakToStrongMath
{
    public static decimal Round2(decimal value) => Math.Round(value, 2, MidpointRounding.AwayFromZero);

    public static bool IsValidPrice(decimal value) => value > 0m;

    public static bool IsCheckpointTime(DateTimeOffset timestamp, string anchor)
    {
        return timestamp.ToLocalTime().TimeOfDay == TimeSpan.Parse(anchor, CultureInfo.InvariantCulture);
    }
}
