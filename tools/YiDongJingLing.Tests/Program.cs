using YiDongJingLing;
using YiDongJingLing.Blocks;
using YiDongJingLing.Events;
using YiDongJingLing.MarketData;
using YiDongJingLing.Notifications;
using YiDongJingLing.Settings;
using YiDongJingLing.Speech;
using System.Net;
using System.Text;
using System.Text.Json;

System.Text.Encoding.RegisterProvider(System.Text.CodePagesEncodingProvider.Instance);

Run("Block parser normalizes TDX block codes and filters invalid rows", () =>
{
    var parser = new BlockFileParser();
    var result = parser.ParseLines(
        "sample.blk",
        [
            "0300834",
            "0002082",
            "1603072",
            "1000001",
            "1880491",
            "0300834",
            "not-a-code",
        ]);

    AssertSequence(["300834", "002082", "603072"], result.Codes.Select(item => item.Code).ToArray(), "codes");
    AssertTrue(result.Issues.Any(issue => issue.Reason == "invalid_code" && issue.RawLine == "1000001"), "index filtered");
    AssertTrue(result.Issues.Any(issue => issue.Reason == BlockFileParser.DuplicateReason), "duplicate issue");
});

Run("Event engine emits limit-up seal and open events", () =>
{
    var engine = new L1EventEngine();
    var first = Quote("002445", "中南文化", 10.8m, 8m, 10m, bids: [Level(10.8m, 1000)]);
    var second = Quote("002445", "中南文化", 11m, 10m, 10m, bids: [Level(11m, 2000)]);
    var third = Quote("002445", "中南文化", 10.9m, 9m, 10m, bids: [Level(10.89m, 100)]);

    _ = engine.Evaluate(first, null, [first]);
    var seal = engine.Evaluate(second, first, [first, second]);
    var open = engine.Evaluate(third, second, [first, second, third]);

    AssertTrue(seal.Any(item => item.Type == L1EventType.LimitUpSealed), "limit-up sealed");
    AssertTrue(seal.Any(item => item.Type == L1EventType.LimitUpSealed && item.Reason.Contains("220万")), "limit-up seal amount unit");
    AssertTrue(open.Any(item => item.Type == L1EventType.LimitUpOpened), "limit-up opened");
});

Run("Event engine emits upcoming limit-up open warning from weak bid seal", () =>
{
    var engine = new L1EventEngine();
    var t0 = DateTimeOffset.Parse("2026-05-20T10:00:00+08:00");
    var strongSeal = Quote("002445", "中南文化", 11m, 10m, 10m, bids: [Level(11m, 1_000_000m)], time: t0);
    var weakSeal = Quote("002445", "中南文化", 11m, 10m, 10m, bids: [Level(11m, 20_000m)], time: t0.AddSeconds(8));

    _ = engine.Evaluate(strongSeal, null, [strongSeal]);
    var events = engine.Evaluate(weakSeal, strongSeal, [strongSeal, weakSeal]);

    AssertTrue(events.Any(item => item.Type == L1EventType.UpcomingLimitUpOpen), "upcoming limit-up open");
});

Run("Event engine emits upcoming limit-down open warning from weak ask seal", () =>
{
    var engine = new L1EventEngine();
    var t0 = DateTimeOffset.Parse("2026-05-20T10:00:00+08:00");
    var strongSeal = Quote("002445", "中南文化", 9m, -10m, 10m, asks: [Level(9m, 1_000_000m)], time: t0);
    var weakSeal = Quote("002445", "中南文化", 9m, -10m, 10m, asks: [Level(9m, 20_000m)], time: t0.AddSeconds(8));

    _ = engine.Evaluate(strongSeal, null, [strongSeal]);
    var events = engine.Evaluate(weakSeal, strongSeal, [strongSeal, weakSeal]);

    AssertTrue(events.Any(item => item.Type == L1EventType.UpcomingLimitDownOpen), "upcoming limit-down open");
});

Run("Event engine carries volume into event records", () =>
{
    var engine = new L1EventEngine();
    var quote = Quote("600000", "浦发银行", 10m, 0m, 10m, volume: 123456m, amount: 100000000m);
    var events = engine.Evaluate(quote, null, [quote]);

    AssertTrue(events.Any(item => item.Type == L1EventType.AmountTier && item.Volume == 123456m), "event volume");
});

Run("Event engine emits highest crossed rise and amount tiers", () =>
{
    var engine = new L1EventEngine();
    var quote = Quote("600000", "浦发银行", 10.9m, 9m, 10m, amount: 1_000_000_000m);
    var events = engine.Evaluate(quote, null, [quote]);

    AssertTrue(events.Any(item => item.Type == L1EventType.BigRiseTier && item.Reason.Contains("9%")), "highest rise tier");
    AssertTrue(events.Any(item => item.Type == L1EventType.AmountTier && item.Reason.Contains("10亿")), "highest amount tier");
    AssertEqual(1, events.Count(item => item.Type == L1EventType.BigRiseTier), "rise tier count");
    AssertEqual(1, events.Count(item => item.Type == L1EventType.AmountTier), "amount tier count");
});

Run("Event engine emits drop tier, large orders, and open shape events", () =>
{
    var engine = new L1EventEngine(new L1EventRules
    {
        RiseTiers = [7m],
        DropTiers = [7m],
        AmountTiers = [100_000_000m],
        LargeOrderAmount = 10_000_000m,
        OpenGapPct = 1m,
        LongBodyPct = 4m,
    });
    var drop = Quote("600000", "浦发银行", 9.2m, -8m, 10m, asks: [Level(9.21m, 20_000m)]);
    var lowOpenLongYang = Quote("300001", "特锐德", 10.3m, 3m, 10m) with { Open = 9.8m };

    var dropEvents = engine.Evaluate(drop, null, [drop]);
    var shapeEvents = engine.Evaluate(lowOpenLongYang, null, [lowOpenLongYang]);

    AssertTrue(dropEvents.Any(item => item.Type == L1EventType.BigDropTier && item.Reason.Contains("7%")), "drop tier");
    AssertTrue(dropEvents.Any(item => item.Type == L1EventType.LargeAskOrder), "large ask order");
    AssertTrue(shapeEvents.Any(item => item.Type == L1EventType.LowOpenLongYang), "low open long yang");
});

Run("Event engine priming suppresses existing rise and amount tiers", () =>
{
    var engine = new L1EventEngine();
    var quote = Quote("600000", "浦发银行", 10.9m, 9m, 10m, amount: 1_000_000_000m);
    var next = quote with
    {
        SourceTime = quote.SourceTime.AddSeconds(3),
        Volume = quote.Volume + 100m,
    };

    engine.Prime(quote);
    var events = engine.Evaluate(next, quote, [quote, next]);

    AssertEqual(0, events.Count(item => item.Type == L1EventType.BigRiseTier), "rise tier after prime");
    AssertEqual(0, events.Count(item => item.Type == L1EventType.AmountTier), "amount tier after prime");
});

Run("Event engine priming suppresses existing open shape events", () =>
{
    var engine = new L1EventEngine(new L1EventRules
    {
        OpenGapPct = 1m,
        LongBodyPct = 4m,
    });
    var quote = Quote("300001", "特锐德", 10.3m, 3m, 10m) with { Open = 9.8m };
    var next = quote with { SourceTime = quote.SourceTime.AddSeconds(3) };

    engine.Prime(quote);
    var events = engine.Evaluate(next, quote, [quote, next]);

    AssertEqual(0, events.Count(item => item.Type == L1EventType.LowOpenLongYang), "low open long yang after prime");
});

Run("Trading session excludes lunch break snapshots", () =>
{
    var lunch = DateTimeOffset.Parse("2026-05-20T12:43:45+08:00");
    var morning = DateTimeOffset.Parse("2026-05-20T10:00:00+08:00");
    var afternoon = DateTimeOffset.Parse("2026-05-20T13:30:00+08:00");

    AssertTrue(!TradingSession.IsContinuousAuction(lunch), "lunch break excluded");
    AssertTrue(TradingSession.IsContinuousAuction(morning), "morning included");
    AssertTrue(TradingSession.IsContinuousAuction(afternoon), "afternoon included");
});

Run("Opening weak-to-strong detector matches shared golden fixture cases", () =>
{
    var fixturePath = Path.Combine(
        ProjectRootLocator.Find(),
        "docs",
        "yidong-jingling",
        "fixtures",
        "opening-weak-to-strong-cases.json");
    using var document = JsonDocument.Parse(File.ReadAllText(fixturePath));
    var root = document.RootElement;
    var rules = OpeningWeakToStrongRules.FromJson(root.GetProperty("rules"));
    var ruleVersion = root.GetProperty("ruleVersion").GetString() ?? "opening-weak-to-strong.v1";

    foreach (var sample in root.GetProperty("cases").EnumerateArray())
    {
        var caseId = sample.GetProperty("caseId").GetString() ?? "";
        var expected = sample.GetProperty("expected");
        var store = new OpeningAuctionStateStore(rules);
        var detector = new OpeningWeakToStrongDetector(rules, ruleVersion);
        OpeningWeakToStrongResult? result = null;

        foreach (var quoteElement in sample.GetProperty("quotes").EnumerateArray())
        {
            var quote = OpeningWeakToStrongQuote.FromJson(quoteElement);
            store.Capture(quote);
            result = detector.Evaluate(quote, store.GetBaseline(quote.Code, quote.At));
        }

        var expectedTriggered = expected.GetProperty("triggered").GetBoolean();
        if (expectedTriggered)
        {
            AssertTrue(result is { Triggered: true }, $"{caseId} triggered");
            AssertEqual(expected.GetProperty("variant").GetString(), result!.Variant, $"{caseId} variant");
            AssertEqual(expected.GetProperty("confidence").GetString(), result.Confidence, $"{caseId} confidence");
            var scoreRange = expected.GetProperty("scoreRange").EnumerateArray().Select(item => item.GetDecimal()).ToArray();
            AssertTrue(result.Score >= scoreRange[0] && result.Score <= scoreRange[1], $"{caseId} score range");
        }
        else
        {
            AssertTrue(result is null or { Triggered: false }, $"{caseId} not triggered");
            AssertEqual(expected.GetProperty("invalidReason").GetString(), result?.InvalidReason, $"{caseId} invalid reason");
        }

        foreach (var riskFlag in expected.GetProperty("riskFlags").EnumerateArray())
        {
            var key = riskFlag.GetString() ?? "";
            AssertTrue(result?.RiskFlags.Any(item => item.Key == key) ?? false, $"{caseId} risk flag {key}");
        }
        if (expected.TryGetProperty("dryRun", out var dryRun))
        {
            AssertEqual(dryRun.GetBoolean(), result?.DryRun ?? false, $"{caseId} dryRun");
        }
        if (expected.TryGetProperty("auctionCoverageRatio", out var auctionCoverageRatio))
        {
            var actual = result?.AuctionCoverageRatio;
            if (!actual.HasValue) throw new InvalidOperationException($"{caseId} auction coverage ratio exists");
            AssertTrue(Math.Abs(actual.Value - auctionCoverageRatio.GetDecimal()) <= 0.01m, $"{caseId} auction coverage ratio");
        }
        if (expected.TryGetProperty("liquidityTier", out var liquidityTier))
        {
            AssertEqual(liquidityTier.GetString(), result?.LiquidityTier, $"{caseId} liquidity tier");
        }
        if (expected.TryGetProperty("liquidityTierMode", out var liquidityTierMode))
        {
            AssertEqual(liquidityTierMode.GetString(), result?.LiquidityTierMode, $"{caseId} liquidity tier mode");
        }
        if (expected.TryGetProperty("liquidityTierBasis", out var liquidityTierBasis))
        {
            AssertEqual(liquidityTierBasis.GetString(), result?.LiquidityTierBasis, $"{caseId} liquidity tier basis");
        }
        if (expected.TryGetProperty("liquidityTierThresholds", out var liquidityTierThresholds))
        {
            AssertEqual(liquidityTierThresholds.GetString(), result?.LiquidityTierThresholds, $"{caseId} liquidity tier thresholds");
        }
        if (expected.TryGetProperty("liquidityTierVersion", out var liquidityTierVersion))
        {
            AssertEqual(liquidityTierVersion.GetString(), result?.LiquidityTierVersion, $"{caseId} liquidity tier version");
        }
        if (expected.TryGetProperty("initialBaselineAt", out var initialBaselineAt))
        {
            AssertEqual(DateTimeOffset.Parse(initialBaselineAt.GetString() ?? ""), result?.InitialBaselineAt, $"{caseId} initial baseline at");
        }
        if (expected.TryGetProperty("initialBaselinePrice", out var initialBaselinePrice))
        {
            AssertEqual(initialBaselinePrice.GetDecimal(), result?.InitialBaselinePrice, $"{caseId} initial baseline price");
        }
        if (expected.TryGetProperty("initialBaselinePct", out var initialBaselinePct))
        {
            AssertEqual(initialBaselinePct.GetDecimal(), result?.InitialBaselinePct, $"{caseId} initial baseline pct");
        }
        if (expected.TryGetProperty("initialBaselineAmount", out var initialBaselineAmount))
        {
            AssertEqual(initialBaselineAmount.GetDecimal(), result?.InitialBaselineAmount, $"{caseId} initial baseline amount");
        }
        if (expected.TryGetProperty("lateBaselineAt", out var lateBaselineAt))
        {
            AssertEqual(DateTimeOffset.Parse(lateBaselineAt.GetString() ?? ""), result?.LateBaselineAt, $"{caseId} late baseline at");
        }
        if (expected.TryGetProperty("lateBaselinePrice", out var lateBaselinePrice))
        {
            AssertEqual(lateBaselinePrice.GetDecimal(), result?.LateBaselinePrice, $"{caseId} late baseline price");
        }
        if (expected.TryGetProperty("lateBaselinePct", out var lateBaselinePct))
        {
            AssertEqual(lateBaselinePct.GetDecimal(), result?.LateBaselinePct, $"{caseId} late baseline pct");
        }
        if (expected.TryGetProperty("lateBaselineAmount", out var lateBaselineAmount))
        {
            AssertEqual(lateBaselineAmount.GetDecimal(), result?.LateBaselineAmount, $"{caseId} late baseline amount");
        }
        if (expected.TryGetProperty("finalBaselineAt", out var finalBaselineAt))
        {
            AssertEqual(DateTimeOffset.Parse(finalBaselineAt.GetString() ?? ""), result?.FinalBaselineAt, $"{caseId} final baseline at");
        }
        if (expected.TryGetProperty("finalBaselinePrice", out var finalBaselinePrice))
        {
            AssertEqual(finalBaselinePrice.GetDecimal(), result?.FinalBaselinePrice, $"{caseId} final baseline price");
        }
        if (expected.TryGetProperty("finalBaselinePct", out var finalBaselinePct))
        {
            AssertEqual(finalBaselinePct.GetDecimal(), result?.FinalBaselinePct, $"{caseId} final baseline pct");
        }
        if (expected.TryGetProperty("finalBaselineAmount", out var finalBaselineAmount))
        {
            AssertEqual(finalBaselineAmount.GetDecimal(), result?.FinalBaselineAmount, $"{caseId} final baseline amount");
        }
        if (expected.TryGetProperty("auctionPriceLiftPctPoint", out var auctionPriceLiftPctPoint))
        {
            AssertEqual(auctionPriceLiftPctPoint.GetDecimal(), result?.AuctionPriceLiftPctPoint, $"{caseId} auction price lift");
        }
        if (expected.TryGetProperty("latePriceLiftPctPoint", out var latePriceLiftPctPoint))
        {
            AssertEqual(latePriceLiftPctPoint.GetDecimal(), result?.LatePriceLiftPctPoint, $"{caseId} late price lift");
        }
        if (expected.TryGetProperty("auctionAmountDelta", out var auctionAmountDelta))
        {
            AssertEqual(auctionAmountDelta.GetDecimal(), result?.AuctionAmountDelta, $"{caseId} auction amount delta");
        }
        if (expected.TryGetProperty("lateAmountDelta", out var lateAmountDelta))
        {
            AssertEqual(lateAmountDelta.GetDecimal(), result?.LateAmountDelta, $"{caseId} late amount delta");
        }
        if (expected.TryGetProperty("auctionAmountLiftRatio", out var auctionAmountLiftRatio))
        {
            AssertEqual(auctionAmountLiftRatio.GetDecimal(), result?.AuctionAmountLiftRatio, $"{caseId} auction amount lift ratio");
        }
        if (expected.TryGetProperty("lateAmountLiftRatio", out var lateAmountLiftRatio))
        {
            AssertEqual(lateAmountLiftRatio.GetDecimal(), result?.LateAmountLiftRatio, $"{caseId} late amount lift ratio");
        }
        if (expected.TryGetProperty("priceVolumeConfirmed", out var priceVolumeConfirmed))
        {
            AssertEqual(priceVolumeConfirmed.GetBoolean(), result?.PriceVolumeConfirmed, $"{caseId} price volume confirmed");
        }
        if (expected.TryGetProperty("intradayStatus", out var intradayStatus))
        {
            AssertEqual(intradayStatus.GetString(), result?.IntradayStatus, $"{caseId} intraday status");
        }
        if (expected.TryGetProperty("intradayOutcome", out var intradayOutcome))
        {
            AssertEqual(intradayOutcome.GetString(), result?.IntradayOutcome, $"{caseId} intraday outcome");
        }
        if (expected.TryGetProperty("intradayStatusAt", out var intradayStatusAt))
        {
            AssertEqual(DateTimeOffset.Parse(intradayStatusAt.GetString() ?? ""), result?.IntradayStatusAt, $"{caseId} intraday status at");
        }
        if (expected.TryGetProperty("intradayPrice", out var intradayPrice))
        {
            AssertEqual(intradayPrice.GetDecimal(), result?.IntradayPrice, $"{caseId} intraday price");
        }
        if (expected.TryGetProperty("intradayPct", out var intradayPct))
        {
            AssertEqual(intradayPct.GetDecimal(), result?.IntradayPct, $"{caseId} intraday pct");
        }
        if (expected.TryGetProperty("intradayAmount", out var intradayAmount))
        {
            AssertEqual(intradayAmount.GetDecimal(), result?.IntradayAmount, $"{caseId} intraday amount");
        }
        if (expected.TryGetProperty("intradayNote", out var intradayNote))
        {
            AssertEqual(intradayNote.GetString(), result?.IntradayNote, $"{caseId} intraday note");
        }
    }
});

Run("Opening weak-to-strong config hash includes auction price-volume rules", () =>
{
    var fixturePath = Path.Combine(
        ProjectRootLocator.Find(),
        "docs",
        "yidong-jingling",
        "fixtures",
        "opening-weak-to-strong-cases.json");
    using var document = JsonDocument.Parse(File.ReadAllText(fixturePath));
    var baseRules = OpeningWeakToStrongRules.FromJson(document.RootElement.GetProperty("rules"));
    var changedRules = baseRules with
    {
        AuctionLateLiftAmountDeltaMin = baseRules.AuctionLateLiftAmountDeltaMin + 1m
    };
    var quote = OpeningWeakToStrongQuote.FromJson(document.RootElement.GetProperty("cases")[0].GetProperty("quotes")[0]);

    var baseHash = new OpeningWeakToStrongDetector(baseRules).Evaluate(quote, null).ConfigHash;
    var changedHash = new OpeningWeakToStrongDetector(changedRules).Evaluate(quote, null).ConfigHash;

    AssertEqual("owts-08f44efb", baseHash, "fixture config hash matches web");
    AssertTrue(baseHash != changedHash, "auction price-volume rule hash changes");
});

Run("Opening weak-to-strong detector profiles delayed older auction quotes without rolling back baseline", () =>
{
    var fixturePath = Path.Combine(
        ProjectRootLocator.Find(),
        "docs",
        "yidong-jingling",
        "fixtures",
        "opening-weak-to-strong-cases.json");
    using var document = JsonDocument.Parse(File.ReadAllText(fixturePath));
    var rules = OpeningWeakToStrongRules.FromJson(document.RootElement.GetProperty("rules"));
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);
    var first = new OpeningWeakToStrongQuote(
        "002559",
        "乱序基线",
        DateTimeOffset.Parse("2026-05-22T09:25:05+08:00"),
        10.1m,
        10m,
        0m,
        20_000_000m,
        1_000_000m,
        0m,
        DateTimeOffset.Parse("2026-05-22T09:25:05+08:00"),
        DateTimeOffset.Parse("2026-05-22T09:25:05+08:00"));
    var initial = first with
    {
        At = DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"),
        LastPrice = 9.7m,
        Amount = 3_000_000m,
        CapturedAt = DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"),
        BridgeTs = DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"),
    };
    var delayed = first with
    {
        At = DateTimeOffset.Parse("2026-05-22T09:24:55+08:00"),
        LastPrice = 9.8m,
        Amount = 5_000_000m,
        CapturedAt = DateTimeOffset.Parse("2026-05-22T09:24:55+08:00"),
        BridgeTs = DateTimeOffset.Parse("2026-05-22T09:24:55+08:00"),
    };
    var open = first with
    {
        At = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00"),
        LastPrice = 10.31m,
        Open = 10.1m,
        Amount = 55_000_000m,
        CapturedAt = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00"),
        BridgeTs = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00"),
    };

    store.Capture(initial);
    store.Capture(first);
    store.Capture(delayed);
    var baseline = store.GetBaseline(open.Code, open.At);
    var result = detector.Evaluate(open, baseline);

    AssertEqual(1m, baseline?.AuctionPct ?? -1m, "auction pct remains latest baseline");
    AssertTrue(result.Triggered, "delayed older auction quote can complete auction profile");
    AssertEqual("auction_late_lift", result.Variant, "delayed older auction profile variant");
    AssertEqual(2, result.AuctionSampleCount ?? 0, "delayed older auction sample count");
    AssertEqual(DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"), result.InitialBaselineAt, "delayed older initial baseline");
});

Run("Opening weak-to-strong detector downgrades amount regression", () =>
{
    var fixturePath = Path.Combine(
        ProjectRootLocator.Find(),
        "docs",
        "yidong-jingling",
        "fixtures",
        "opening-weak-to-strong-cases.json");
    using var document = JsonDocument.Parse(File.ReadAllText(fixturePath));
    var rules = OpeningWeakToStrongRules.FromJson(document.RootElement.GetProperty("rules"));
    var sample = document.RootElement.GetProperty("cases")
        .EnumerateArray()
        .First(item => item.GetProperty("caseId").GetString() == "002552-auction-gap-reversal");
    var quotes = sample.GetProperty("quotes")
        .EnumerateArray()
        .Select(OpeningWeakToStrongQuote.FromJson)
        .ToArray();
    var open = quotes[^1] with { Amount = 60_000_000m };
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);

    foreach (var quote in quotes[..^1])
    {
        store.Capture(IsAuctionFinalQuote(quote) ? quote with { Amount = 80_000_000m } : quote);
    }
    var result = detector.Evaluate(open, store.GetBaseline(open.Code, open.At));

    AssertTrue(result.Triggered, "amount regression still records candidate");
    AssertEqual("watch", result.Confidence, "amount regression confidence");
    AssertTrue(result.RiskFlags.Any(item => item.Key == "amount_regressed"), "amount regression risk flag");
});

Run("Opening weak-to-strong detector emits preopen candidate after final baseline", () =>
{
    var fixturePath = Path.Combine(
        ProjectRootLocator.Find(),
        "docs",
        "yidong-jingling",
        "fixtures",
        "opening-weak-to-strong-cases.json");
    using var document = JsonDocument.Parse(File.ReadAllText(fixturePath));
    var rules = OpeningWeakToStrongRules.FromJson(document.RootElement.GetProperty("rules"));
    var sample = document.RootElement.GetProperty("cases")
        .EnumerateArray()
        .First(item => item.GetProperty("caseId").GetString() == "002552-auction-gap-reversal");
    var quotes = sample.GetProperty("quotes")
        .EnumerateArray()
        .Select(OpeningWeakToStrongQuote.FromJson)
        .ToArray();
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);

    foreach (var quote in quotes[..^1])
    {
        store.Capture(quote);
    }

    var finalQuote = quotes[^2];
    var candidate = finalQuote with
    {
        At = DateTimeOffset.Parse("2026-05-22T09:25:12+08:00"),
        CapturedAt = DateTimeOffset.Parse("2026-05-22T09:25:12+08:00"),
        BridgeTs = DateTimeOffset.Parse("2026-05-22T09:25:12+08:00"),
    };
    var result = detector.Evaluate(candidate, store.GetBaseline(candidate.Code, candidate.At));

    AssertTrue(result.Triggered, "preopen candidate triggered");
    AssertEqual("auction_late_lift", result.Variant, "preopen candidate variant");
    AssertEqual("strong", result.Confidence, "preopen candidate confidence");
    AssertEqual("preopen_candidate", result.IntradayStatus, "preopen candidate status");
    AssertEqual("preopen_candidate", result.IntradayOutcome, "preopen candidate outcome");
    AssertEqual("竞价量价齐升，等待开盘承接验证", result.IntradayNote, "preopen candidate note");
    AssertTrue(result.PriceVolumeConfirmed == true, "preopen candidate price-volume confirmed");
    AssertEqual(0, result.RiskFlags.Count, "preopen candidate risk flags");
});

Run("Opening weak-to-strong detector includes 09:25:10 in preopen candidate window", () =>
{
    var fixturePath = Path.Combine(
        ProjectRootLocator.Find(),
        "docs",
        "yidong-jingling",
        "fixtures",
        "opening-weak-to-strong-cases.json");
    using var document = JsonDocument.Parse(File.ReadAllText(fixturePath));
    var rules = OpeningWeakToStrongRules.FromJson(document.RootElement.GetProperty("rules"));
    var sample = document.RootElement.GetProperty("cases")
        .EnumerateArray()
        .First(item => item.GetProperty("caseId").GetString() == "002552-auction-gap-reversal");
    var quotes = sample.GetProperty("quotes")
        .EnumerateArray()
        .Select(OpeningWeakToStrongQuote.FromJson)
        .ToArray();
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);

    foreach (var quote in quotes[..^1])
    {
        store.Capture(quote);
    }

    var finalQuote = quotes[^2];
    var candidate = finalQuote with
    {
        At = DateTimeOffset.Parse("2026-05-22T09:25:10+08:00"),
        CapturedAt = DateTimeOffset.Parse("2026-05-22T09:25:10+08:00"),
        BridgeTs = DateTimeOffset.Parse("2026-05-22T09:25:10+08:00"),
    };
    var result = detector.Evaluate(candidate, store.GetBaseline(candidate.Code, candidate.At));

    AssertTrue(result.Triggered, "09:25:10 preopen candidate triggered");
    AssertEqual("preopen_candidate", result.IntradayStatus, "09:25:10 preopen status");
    AssertEqual("preopen_candidate", result.IntradayOutcome, "09:25:10 preopen outcome");
});

Run("Opening weak-to-strong detector does not confirm preopen candidate without pending check", () =>
{
    var fixturePath = Path.Combine(
        ProjectRootLocator.Find(),
        "docs",
        "yidong-jingling",
        "fixtures",
        "opening-weak-to-strong-cases.json");
    using var document = JsonDocument.Parse(File.ReadAllText(fixturePath));
    var rules = OpeningWeakToStrongRules.FromJson(document.RootElement.GetProperty("rules"));
    var sample = document.RootElement.GetProperty("cases")
        .EnumerateArray()
        .First(item => item.GetProperty("caseId").GetString() == "002552-auction-gap-reversal");
    var quotes = sample.GetProperty("quotes")
        .EnumerateArray()
        .Select(OpeningWeakToStrongQuote.FromJson)
        .ToArray();
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);

    foreach (var quote in quotes[..^1])
    {
        store.Capture(quote);
    }

    var finalQuote = quotes[^2];
    var candidateQuote = finalQuote with
    {
        At = DateTimeOffset.Parse("2026-05-22T09:25:12+08:00"),
        CapturedAt = DateTimeOffset.Parse("2026-05-22T09:25:12+08:00"),
        BridgeTs = DateTimeOffset.Parse("2026-05-22T09:25:12+08:00"),
    };
    var candidate = detector.Evaluate(candidateQuote, store.GetBaseline(candidateQuote.Code, candidateQuote.At));
    var intradayQuote = quotes[^1] with
    {
        At = DateTimeOffset.Parse("2026-05-22T09:36:00+08:00"),
        CapturedAt = DateTimeOffset.Parse("2026-05-22T09:36:00+08:00"),
        BridgeTs = DateTimeOffset.Parse("2026-05-22T09:36:00+08:00"),
        LastPrice = 38.5m,
        Amount = 90_000_000m,
    };
    var intraday = detector.Evaluate(intradayQuote, store.GetBaseline(intradayQuote.Code, intradayQuote.At));

    AssertEqual("preopen_candidate", candidate.IntradayStatus, "preopen candidate status");
    AssertTrue(intraday.IntradayStatus != "confirmed", "preopen candidate is not confirmed directly");
    AssertTrue(intraday.IntradayOutcome != "confirmed_strong", "preopen candidate outcome is not confirmed directly");
});

Run("Event engine emits opening weak-to-strong from auction baseline", () =>
{
    var engine = new L1EventEngine();
    var auction = Quote(
        "002552",
        "宝鼎科技",
        35.68m,
        -1.44m,
        36.2m,
        amount: 6_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"));
    var open = Quote(
        "002552",
        "宝鼎科技",
        37.48m,
        3.54m,
        36.2m,
        volume: 1_495_000m,
        amount: 56_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:30:06+08:00")) with { Open = 36.92m };

    engine.Prime(auction);
    var events = engine.Evaluate(open, auction, [auction, open]);

    AssertTrue(events.Any(item => item.Type == L1EventType.OpeningWeakToStrong), "opening weak-to-strong event");
    var signal = events.Single(item => item.Type == L1EventType.OpeningWeakToStrong);
    AssertEqual("竞价弱转强", signal.TypeName, "event type name");
    AssertTrue(signal.Reason.Contains("09:25 -1.44%"), "auction pct in reason");
    AssertTrue(signal.Reason.Contains("09:30 +3.54%"), "open pct in reason");
    AssertTrue(signal.OpeningSignal is not null, "opening canonical signal attached");
    AssertEqual("opening_weak_to_strong", signal.OpeningSignal!.SignalType, "opening signal type");
    AssertEqual("2026-05-22", signal.OpeningSignal.TradingDate, "opening trading date");
    AssertTrue(signal.OpeningSignal.ConfigHash.StartsWith("owts-", StringComparison.Ordinal), "opening config hash");
    AssertEqual("active", signal.OpeningSignal.LiquidityTier, "opening liquidity tier");
    AssertEqual("review_only", signal.OpeningSignal.LiquidityTierMode, "opening liquidity tier mode");
    AssertEqual("liquidity-review.v1", signal.OpeningSignal.LiquidityTierVersion, "opening liquidity tier version");
    AssertEqual("degraded", signal.OpeningSignal.BaselineQuality, "missing per-code capture metadata stays degraded");
    AssertTrue(signal.OpeningSignal.AuctionCapturedAt is not null, "auction fallback timestamp exists for replay");
    AssertTrue(signal.OpeningSignal.BridgeTs is null, "missing per-code bridgeTs is not forged from source time");
});

Run("Event engine emits preopen weak-to-strong candidate before continuous auction", () =>
{
    var engine = new L1EventEngine();
    var first = Quote(
        "002552",
        "宝鼎科技",
        35m,
        -3.31m,
        36.2m,
        amount: 2_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"));
    var late = Quote(
        "002552",
        "宝鼎科技",
        35.3m,
        -2.49m,
        36.2m,
        amount: 4_500_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:24:05+08:00"));
    var auction = Quote(
        "002552",
        "宝鼎科技",
        35.68m,
        -1.44m,
        36.2m,
        volume: 1_680_000m,
        amount: 6_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"));
    var candidate = auction with
    {
        SourceTime = DateTimeOffset.Parse("2026-05-22T09:25:12+08:00"),
        CapturedAt = DateTimeOffset.Parse("2026-05-22T09:25:12+08:00"),
        BridgeTs = DateTimeOffset.Parse("2026-05-22T09:25:12+08:00"),
    };

    engine.Prime(first);
    engine.Prime(late);
    engine.Prime(auction);
    var events = engine.Evaluate(candidate, auction, [first, late, auction, candidate]);

    var signal = events.Single(item => item.Type == L1EventType.OpeningWeakToStrong);
    AssertEqual("竞价弱转强候选", signal.TypeName, "preopen event type name");
    AssertEqual("preopen_candidate", signal.OpeningSignal?.IntradayStatus, "preopen event status");
    AssertEqual("preopen_candidate", signal.OpeningSignal?.IntradayOutcome, "preopen event outcome");
    AssertTrue(signal.Reason.Contains("待开盘验证"), "preopen event reason");
    AssertEqual(L1EventSeverity.Important, signal.Severity, "preopen event severity");
});

Run("Event engine emits opening weak-to-strong intraday outcome update", () =>
{
    var engine = new L1EventEngine();
    var auction = Quote(
        "002552",
        "宝鼎科技",
        35.68m,
        -1.44m,
        36.2m,
        amount: 6_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"));
    var open = Quote(
        "002552",
        "宝鼎科技",
        37.48m,
        3.54m,
        36.2m,
        volume: 1_495_000m,
        amount: 56_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:30:06+08:00")) with { Open = 36.92m };
    var failed = open with
    {
        LastPrice = 36.7m,
        ChangePct = 1.38m,
        Amount = 98_000_000m,
        SourceTime = DateTimeOffset.Parse("2026-05-22T09:42:00+08:00"),
    };

    engine.Prime(auction);
    _ = engine.Evaluate(open, auction, [auction, open]);
    var updates = engine.Evaluate(failed, open, [auction, open, failed]);

    var update = updates.Single(item => item.Type == L1EventType.OpeningWeakToStrong);
    AssertEqual("failed", update.OpeningSignal?.IntradayStatus, "intraday update status");
    AssertEqual("failed_open_dump", update.OpeningSignal?.IntradayOutcome, "intraday update outcome");
    AssertTrue(update.Reason.Contains("盘中失败"), "intraday failure reason");
});

Run("Event engine uses TDX block context for opening board attempt", () =>
{
    var engine = new L1EventEngine();
    engine.ReplaceTdxBlockWeakContext(["600010"]);
    var auction = Quote(
        "600010",
        "TDX候选",
        10.18m,
        1.8m,
        10m,
        amount: 12_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"));
    var open = Quote(
        "600010",
        "TDX候选",
        10.86m,
        8.6m,
        10m,
        amount: 86_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:30:20+08:00")) with { Open = 10.2m };

    engine.Prime(auction);
    var events = engine.Evaluate(open, auction, [auction, open]);
    var signal = events.Single(item => item.Type == L1EventType.OpeningWeakToStrong).OpeningSignal;

    AssertEqual("strong_open_board_attempt", signal?.Variant, "tdx context variant");
    AssertEqual(30m, signal?.PreviousWeakScore ?? 0m, "tdx context score");
    AssertEqual("tdx_block", signal?.PreviousWeakSource, "tdx context source");
    AssertTrue(signal?.Factors.Any(item => item.Key == "previousWeakContext") ?? false, "previous context factor");
});

Run("Event engine keeps watch opening weak-to-strong out of strong voice policy", () =>
{
    var engine = new L1EventEngine();
    var first = Quote(
        "002554",
        "无量抬价",
        9.8m,
        -2m,
        10m,
        amount: 5_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"));
    var late = Quote(
        "002554",
        "无量抬价",
        9.95m,
        -0.5m,
        10m,
        amount: 5_200_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:24:10+08:00"));
    var auction = Quote(
        "002554",
        "无量抬价",
        10.02m,
        0.2m,
        10m,
        amount: 5_400_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"));
    var open = Quote(
        "002554",
        "无量抬价",
        10.36m,
        3.6m,
        10m,
        volume: 4_000_000m,
        amount: 40_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:30:07+08:00")) with { Open = 10.1m };

    engine.Prime(first);
    engine.Prime(late);
    engine.Prime(auction);
    var events = engine.Evaluate(open, auction, [first, late, auction, open]);
    var signal = events.Single(item => item.Type == L1EventType.OpeningWeakToStrong);

    AssertEqual("watch", signal.OpeningSignal?.Confidence, "watch confidence");
    AssertEqual(L1EventSeverity.Normal, signal.Severity, "watch opening severity");
    AssertEqual(0, EventVoicePolicy.FilterForVoice([signal], VoiceMode.StrongOnly).Count, "watch opening not strong voice");
    AssertEqual(DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"), signal.OpeningSignal?.InitialBaselineAt, "watch initial baseline at");
    AssertEqual(9.8m, signal.OpeningSignal?.InitialBaselinePrice, "watch initial baseline price");
    AssertEqual(DateTimeOffset.Parse("2026-05-22T09:24:10+08:00"), signal.OpeningSignal?.LateBaselineAt, "watch late baseline at");
    AssertEqual(9.95m, signal.OpeningSignal?.LateBaselinePrice, "watch late baseline price");
    AssertEqual(DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"), signal.OpeningSignal?.FinalBaselineAt, "watch final baseline at");
    AssertEqual(10.02m, signal.OpeningSignal?.FinalBaselinePrice, "watch final baseline price");
    AssertEqual(2.2m, signal.OpeningSignal?.AuctionPriceLiftPctPoint, "watch auction price lift");
    AssertEqual(0.7m, signal.OpeningSignal?.LatePriceLiftPctPoint, "watch late price lift");
    AssertEqual(400_000m, signal.OpeningSignal?.AuctionAmountDelta, "watch auction amount delta");
    AssertEqual(200_000m, signal.OpeningSignal?.LateAmountDelta, "watch late amount delta");
    AssertEqual("active", signal.OpeningSignal?.LiquidityTier, "watch liquidity tier");
    AssertEqual("review_only", signal.OpeningSignal?.LiquidityTierMode, "watch liquidity tier mode");
    AssertEqual("liquidity-review.v1", signal.OpeningSignal?.LiquidityTierVersion, "watch liquidity tier version");
});

Run("Opening weak-to-strong detector rejects previous trading day baseline", () =>
{
    var rules = new OpeningWeakToStrongRules(
        "09:20:00",
        "09:20:00",
        "09:20:30",
        "09:24:50",
        "09:25:10",
        "09:30:00",
        "09:35:00",
        0.5m,
        3m,
        1.5m,
        1.5m,
        1m,
        3m,
        2m,
        30_000_000m,
        20_000_000m,
        5_000_000m,
        "09:24:00",
        1m,
        0.5m,
        0.8m,
        0.35m,
        0.3m,
        0.2m,
        0m,
        8_000_000m,
        5_000_000m,
        2.5m,
        2m,
        0.2m,
        30m,
        0.95m,
        10_000,
        1_000_000m,
        0.995m);
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);
    var auction = new OpeningWeakToStrongQuote(
        "002552",
        "宝鼎科技",
        DateTimeOffset.Parse("2026-05-21T09:25:00+08:00"),
        35.68m,
        36.2m,
        0m,
        6_000_000m,
        1_680_000m,
        0m,
        DateTimeOffset.Parse("2026-05-21T09:25:00+08:00"),
        DateTimeOffset.Parse("2026-05-21T09:25:00+08:00"));
    var nextDayOpen = auction with
    {
        At = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00"),
        LastPrice = 37.48m,
        Open = 36.92m,
        Amount = 56_000_000m,
        CapturedAt = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00"),
        BridgeTs = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00"),
    };

    store.Capture(auction);
    var result = detector.Evaluate(nextDayOpen, store.GetBaseline(nextDayOpen.Code, nextDayOpen.At));

    AssertTrue(!result.Triggered, "previous day baseline rejected");
    AssertEqual("baseline_missing", result.InvalidReason, "previous day invalid reason");
});

Run("Event engine does not reuse previous trading day opening state", () =>
{
    var engine = new L1EventEngine();
    var auction = Quote(
        "002552",
        "宝鼎科技",
        35.68m,
        -1.44m,
        36.2m,
        amount: 6_000_000m,
        time: DateTimeOffset.Parse("2026-05-21T09:25:00+08:00"));
    var nextDayOpen = Quote(
        "002552",
        "宝鼎科技",
        37.48m,
        3.54m,
        36.2m,
        amount: 56_000_000m,
        time: DateTimeOffset.Parse("2026-05-22T09:30:06+08:00")) with { Open = 36.92m };

    engine.Prime(auction);
    var events = engine.Evaluate(nextDayOpen, null, [nextDayOpen]);

    AssertEqual(0, events.Count(item => item.Type == L1EventType.OpeningWeakToStrong), "no cross-day opening signal");
});

Run("Event engine allows opening weak-to-strong again on the next trading day", () =>
{
    var engine = new L1EventEngine();
    var day1Auction = Quote(
        "002552",
        "宝鼎科技",
        35.68m,
        -1.44m,
        36.2m,
        amount: 6_000_000m,
        time: DateTimeOffset.Parse("2026-05-21T09:25:00+08:00"));
    var day1Open = Quote(
        "002552",
        "宝鼎科技",
        37.48m,
        3.54m,
        36.2m,
        amount: 56_000_000m,
        time: DateTimeOffset.Parse("2026-05-21T09:30:06+08:00")) with { Open = 36.92m };
    var day2Auction = day1Auction with
    {
        SourceTime = DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"),
    };
    var day2Open = day1Open with
    {
        SourceTime = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00"),
    };

    engine.Prime(day1Auction);
    var day1Events = engine.Evaluate(day1Open, day1Auction, [day1Auction, day1Open]);
    engine.Prime(day2Auction);
    var day2Events = engine.Evaluate(day2Open, day2Auction, [day2Auction, day2Open]);

    AssertTrue(day1Events.Any(item => item.Type == L1EventType.OpeningWeakToStrong), "day 1 opening signal");
    AssertTrue(day2Events.Any(item => item.Type == L1EventType.OpeningWeakToStrong), "day 2 opening signal");
});

Run("Event engine emits fast rise and fast drop from local history", () =>
{
    var engine = new L1EventEngine();
    var t0 = DateTimeOffset.Parse("2026-05-20T09:30:00+08:00");
    var old = Quote("300001", "特锐德", 10m, 0m, 10m, time: t0);
    var rise = Quote("300001", "特锐德", 10.35m, 3.5m, 10m, time: t0.AddSeconds(60));
    var drop = Quote("300001", "特锐德", 10m, 0m, 10m, time: t0.AddSeconds(120));

    _ = engine.Evaluate(old, null, [old]);
    var riseEvents = engine.Evaluate(rise, old, [old, rise]);
    var dropEvents = engine.Evaluate(drop, rise, [old, rise, drop]);

    AssertTrue(riseEvents.Any(item => item.Type == L1EventType.FastRise), "fast rise");
    AssertTrue(dropEvents.Any(item => item.Type == L1EventType.FastDrop), "fast drop");
});

Run("Event engine emits five minute fast move from local history", () =>
{
    var engine = new L1EventEngine(new L1EventRules
    {
        FastRise30SecPct = 99m,
        FastRise60SecPct = 99m,
        FastRise300SecPct = 5m,
        FastDrop30SecPct = -99m,
        FastDrop60SecPct = -99m,
        FastDrop300SecPct = -5m,
    });
    var t0 = DateTimeOffset.Parse("2026-05-20T09:30:00+08:00");
    var old = Quote("300001", "特锐德", 10m, 0m, 10m, time: t0);
    var rise = Quote("300001", "特锐德", 10.6m, 6m, 10m, time: t0.AddMinutes(5));

    _ = engine.Evaluate(old, null, [old]);
    var events = engine.Evaluate(rise, old, [old, rise]);

    AssertTrue(events.Any(item => item.Type == L1EventType.FastRise && item.Reason.Contains("5分钟 6.00%")), "five minute fast rise");
});

Run("Quote state store keeps enough history for five minute fast move", () =>
{
    var store = new QuoteStateStore();
    var t0 = DateTimeOffset.Parse("2026-05-20T09:30:00+08:00");
    var old = Quote("300001", "特锐德", 10m, 0m, 10m, time: t0);
    var current = Quote("300001", "特锐德", 10.6m, 6m, 10m, time: t0.AddMinutes(5));

    _ = store.Apply(old);
    _ = store.Apply(current);
    var history = store.GetHistory("300001");

    AssertTrue(history.Any(item => item.SourceTime == t0), "five minute baseline retained");
});

Run("Event engine clear resets per-stock state", () =>
{
    var engine = new L1EventEngine();
    var first = Quote("002445", "中南文化", 11m, 10m, 10m, bids: [Level(11m, 2000)]);

    var initial = engine.Evaluate(first, null, [first]);
    engine.Clear();
    var afterClear = engine.Evaluate(first, null, [first]);

    AssertTrue(initial.Any(item => item.Type == L1EventType.LimitUpSealed), "initial seal");
    AssertTrue(afterClear.Any(item => item.Type == L1EventType.LimitUpSealed), "seal after clear");
});

Run("Event deduper applies cooldown and builds merged speech text", () =>
{
    var deduper = new EventDeduper(TimeSpan.FromSeconds(180));
    var now = DateTimeOffset.Parse("2026-05-20T10:00:00+08:00");
    var first = Event("002445", "中南文化", L1EventType.FastRise, "快速拉升", now);
    var repeat = first with { Timestamp = now.AddSeconds(60) };
    var second = Event("300001", "特锐德", L1EventType.NearLimitUp, "逼近涨停", now.AddSeconds(61));

    var emitted = deduper.Filter([first, repeat, second]);
    var speech = EventDeduper.BuildSpeechText(emitted);

    AssertEqual(2, emitted.Count, "emitted count");
    AssertEqual("新增2条异动，中南文化快速拉升，特锐德逼近涨停", speech, "speech");
});

Run("Event deduper clear allows immediate repeat", () =>
{
    var deduper = new EventDeduper(TimeSpan.FromSeconds(180));
    var now = DateTimeOffset.Parse("2026-05-20T10:00:00+08:00");
    var first = Event("002445", "中南文化", L1EventType.FastRise, "快速拉升", now);
    var repeat = first with { Timestamp = now.AddSeconds(1) };

    _ = deduper.Filter([first]);
    AssertEqual(0, deduper.Filter([repeat]).Count, "repeat blocked before clear");
    deduper.Clear();
    AssertEqual(1, deduper.Filter([repeat]).Count, "repeat allowed after clear");
});

Run("Event deduper keeps only highest priority event per stock in one batch", () =>
{
    var deduper = new EventDeduper(TimeSpan.FromSeconds(180));
    var now = DateTimeOffset.Parse("2026-05-20T10:00:00+08:00");
    var low = Event("002445", "中南文化", L1EventType.AmountTier, "成交额跨档", now);
    var high = Event("002445", "中南文化", L1EventType.FastRise, "快速拉升", now.AddSeconds(1));

    var emitted = deduper.Filter([low, high]);

    AssertEqual(1, emitted.Count, "emitted count");
    AssertEqual(L1EventType.FastRise, emitted[0].Type, "highest priority");
});

Run("Event deduper keeps opening weak-to-strong even with same-stock ordinary events", () =>
{
    var deduper = new EventDeduper(TimeSpan.FromSeconds(180));
    var now = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00");
    var opening = Event("002552", "宝鼎科技", L1EventType.OpeningWeakToStrong, "竞价弱转强", now)
        with { Severity = L1EventSeverity.Important };
    var fastRise = Event("002552", "宝鼎科技", L1EventType.FastRise, "快速拉升", now.AddSeconds(1))
        with { Severity = L1EventSeverity.Important };

    var emitted = deduper.Filter([opening, fastRise]);

    AssertEqual(2, emitted.Count, "opening plus ordinary event count");
    AssertTrue(emitted.Any(item => item.Type == L1EventType.OpeningWeakToStrong), "opening event preserved");
    AssertTrue(emitted.Any(item => item.Type == L1EventType.FastRise), "ordinary event preserved");
});

Run("Event deduper emits opening weak-to-strong intraday status upgrades inside cooldown", () =>
{
    var deduper = new EventDeduper(TimeSpan.FromSeconds(180));
    var now = DateTimeOffset.Parse("2026-05-22T09:34:50+08:00");
    var pending = Event("002552", "宝鼎科技", L1EventType.OpeningWeakToStrong, "竞价弱转强", now) with
    {
        OpeningSignal = TestOpeningSignal(now, dryRun: false) with
        {
            IntradayStatus = "pending",
            IntradayOutcome = "pending",
            IntradayStatusAt = now,
        }
    };
    var failedAt = now.AddSeconds(11);
    var failed = pending with
    {
        Timestamp = failedAt,
        OpeningSignal = pending.OpeningSignal! with
        {
            IntradayStatus = "failed",
            IntradayOutcome = "failed_open_dump",
            IntradayStatusAt = failedAt,
        }
    };

    AssertEqual(1, deduper.Filter([pending]).Count, "pending emitted");
    var update = deduper.Filter([failed]);

    AssertEqual(1, update.Count, "status update emitted");
    AssertEqual("failed", update[0].OpeningSignal?.IntradayStatus, "updated status");
    AssertEqual("failed_open_dump", update[0].OpeningSignal?.IntradayOutcome, "updated outcome");
});

Run("Event deduper keeps different stocks in one batch", () =>
{
    var deduper = new EventDeduper(TimeSpan.FromSeconds(180));
    var now = DateTimeOffset.Parse("2026-05-20T10:00:00+08:00");
    var first = Event("002445", "中南文化", L1EventType.FastRise, "快速拉升", now);
    var second = Event("300001", "特锐德", L1EventType.AmountTier, "成交额跨档", now);

    AssertEqual(2, deduper.Filter([first, second]).Count, "different stocks");
});

Run("Voice policy defaults to strong signals and excludes weak pressure events", () =>
{
    var now = DateTimeOffset.Parse("2026-05-20T10:00:00+08:00");
    var fastRise = Event("002445", "中南文化", L1EventType.FastRise, "快速拉升", now);
    var bidPressure = Event("300001", "特锐德", L1EventType.BidPressure, "盘口买压增强", now)
        with { Severity = L1EventSeverity.Normal };
    var strong = EventVoicePolicy.FilterForVoice([fastRise, bidPressure], VoiceMode.StrongOnly);

    AssertEqual(1, strong.Count, "strong signal count");
    AssertEqual(L1EventType.FastRise, strong[0].Type, "strong signal type");
    AssertEqual(2, EventVoicePolicy.FilterForVoice([fastRise, bidPressure], VoiceMode.All).Count, "all mode");
    AssertEqual(0, EventVoicePolicy.FilterForVoice([fastRise, bidPressure], VoiceMode.Muted).Count, "muted mode");
});

Run("Voice policy does not announce dry-run opening signals", () =>
{
    var now = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00");
    var dryRunOpening = Event("002560", "低覆盖", L1EventType.OpeningWeakToStrong, "竞价弱转强", now) with
    {
        OpeningSignal = TestOpeningSignal(now, dryRun: true)
    };

    AssertEqual(0, EventVoicePolicy.FilterForVoice([dryRunOpening], VoiceMode.All).Count, "all mode dry-run muted");
    AssertEqual(0, EventVoicePolicy.FilterForVoice([dryRunOpening], VoiceMode.StrongOnly).Count, "strong mode dry-run muted");
});

Run("Stock name resolver reads TDX tnf cache records", () =>
{
    var tempRoot = Path.Combine(Path.GetTempPath(), "YiDongJingLingTests", Guid.NewGuid().ToString("N"));
    var hqCache = Path.Combine(tempRoot, "T0002", "hq_cache");
    Directory.CreateDirectory(hqCache);
    var bytes = new List<byte>();
    bytes.AddRange(new byte[0x32]);
    bytes.AddRange(StockNameResolver.BuildTnfRecordForTest("600158", "中体产业"));
    File.WriteAllBytes(Path.Combine(hqCache, "shs.tnf"), bytes.ToArray());

    var resolver = new StockNameResolver();
    resolver.LoadFromBlockDirectory(Path.Combine(tempRoot, "T0002", "blocknew"));

    AssertEqual("中体产业", resolver.Resolve("600158"), "stock name");
});

Run("Stock name resolver prefers TDX cache and rejects numeric fallback names", () =>
{
    var tempRoot = Path.Combine(Path.GetTempPath(), "YiDongJingLingTests", Guid.NewGuid().ToString("N"));
    var hqCache = Path.Combine(tempRoot, "T0002", "hq_cache");
    Directory.CreateDirectory(hqCache);
    var bytes = new List<byte>();
    bytes.AddRange(new byte[0x32]);
    bytes.AddRange(StockNameResolver.BuildTnfRecordForTest("600158", "中体产业"));
    File.WriteAllBytes(Path.Combine(hqCache, "shs.tnf"), bytes.ToArray());

    var resolver = new StockNameResolver();
    resolver.LoadFromBlockDirectory(Path.Combine(tempRoot, "T0002", "blocknew"));

    AssertEqual("中体产业", resolver.Resolve("600158", "100"), "cached name priority");
    AssertEqual("", resolver.Resolve("000001", "100"), "numeric fallback rejected");
    AssertEqual("平安银行", resolver.Resolve("000001", "平安银行"), "valid fallback accepted");
});

Run("Stock name resolver reads local TDX cache when available", () =>
{
    var blockDir = @"D:\APP_SOFT\TDX\T0002\blocknew";
    var hqCache = @"D:\APP_SOFT\TDX\T0002\hq_cache";
    if (!Directory.Exists(blockDir) || !File.Exists(Path.Combine(hqCache, "shs.tnf")))
    {
        Console.WriteLine("SKIP local TDX cache is not available");
        return;
    }

    var resolver = new StockNameResolver();
    resolver.LoadFromBlockDirectory(blockDir);

    AssertNotCode("600580", resolver.Resolve("600580"), "600580 name");
    AssertNotCode("002594", resolver.Resolve("002594"), "002594 name");
});

Run("App settings clone is independent", () =>
{
    var original = new AppSettings
    {
        BridgeUrl = "ws://old",
        StockPoolSource = StockPoolSource.Hotlist,
        FilterStStocks = true,
        SyncMessages = true,
        RiseBreakthroughPct = 8m,
        DropBreakthroughPct = 6m,
        FiveMinuteMovePct = 4m,
        LargeAmountThresholdWan = 5_000m,
        LargeOrderThresholdWan = 800m,
        OpenGapPct = 1.5m,
        LongBodyPct = 3.5m,
        VoiceMode = VoiceMode.All,
        SelectedBlockFiles = ["old.blk"],
        EnabledEvents = { [L1EventType.FastRise.ToString()] = true },
    };

    var copy = original.Clone();
    copy.BridgeUrl = "ws://new";
    copy.VoiceMode = VoiceMode.Muted;
    copy.SelectedBlockFiles.Add("new.blk");
    copy.EnabledEvents[L1EventType.FastRise.ToString()] = false;

    AssertEqual("ws://old", original.BridgeUrl, "bridge url unchanged");
    AssertEqual(StockPoolSource.Hotlist, original.StockPoolSource, "stock pool source unchanged");
    AssertTrue(original.FilterStStocks, "filter ST unchanged");
    AssertTrue(original.SyncMessages, "sync messages unchanged");
    AssertEqual(8m, original.RiseBreakthroughPct, "rise threshold unchanged");
    AssertEqual(6m, original.DropBreakthroughPct, "drop threshold unchanged");
    AssertEqual(4m, original.FiveMinuteMovePct, "five minute threshold unchanged");
    AssertEqual(5_000m, original.LargeAmountThresholdWan, "amount threshold unchanged");
    AssertEqual(800m, original.LargeOrderThresholdWan, "order threshold unchanged");
    AssertEqual(1.5m, original.OpenGapPct, "open gap unchanged");
    AssertEqual(3.5m, original.LongBodyPct, "long body unchanged");
    AssertEqual(VoiceMode.All, original.VoiceMode, "voice mode unchanged");
    AssertEqual(1, original.SelectedBlockFiles.Count, "selected files unchanged");
    AssertTrue(original.EnabledEvents[L1EventType.FastRise.ToString()], "event setting unchanged");
});

Run("Main form resolves TDX root from blocknew directory", () =>
{
    var tempRoot = Path.Combine(Path.GetTempPath(), "YiDongJingLingTests", Guid.NewGuid().ToString("N"), "TDX");
    var blockDir = Path.Combine(tempRoot, "T0002", "blocknew");
    Directory.CreateDirectory(blockDir);
    Directory.CreateDirectory(Path.Combine(tempRoot, "T0002", "hq_cache"));

    AssertEqual(tempRoot, MainForm.ResolveTdxRootFromBlockDirectory(blockDir), "tdx root");
});

Run("Main form resolves bridge port from configured URL", () =>
{
    AssertEqual(8765, MainForm.ResolveBridgePort("ws://127.0.0.1:8765/ws/quotes"), "default port");
    AssertEqual(9876, MainForm.ResolveBridgePort("ws://127.0.0.1:9876/ws/quotes"), "custom port");
    AssertEqual(8765, MainForm.ResolveBridgePort("not-a-url"), "fallback port");
});

Run("Main form formats opening auction coverage status", () =>
{
    AssertTrue(
        MainForm.IsOpeningAuctionCoverageWindow(DateTimeOffset.Parse("2026-05-22T09:25:00+08:00")),
        "auction coverage window includes 09:25");
    AssertTrue(
        !MainForm.IsOpeningAuctionCoverageWindow(DateTimeOffset.Parse("2026-05-22T09:30:00+08:00")),
        "auction coverage window excludes 09:30");
    AssertEqual(
        "竞价覆盖 90% 90/100 慢2 截1 演练",
        MainForm.OpeningCoverageStatusText("90%", "90", "100", " 慢2 截1", " 演练"),
        "coverage status text");
    AssertTrue(MainForm.IsOpeningCoverageLow(189m / 200m), "raw 94.5% coverage is low");
    AssertTrue(!MainForm.IsOpeningCoverageLow(0.95m), "raw 95% coverage passes");
});

Run("Main form preserves TDX block selection until list is loaded", () =>
{
    var saved = new[] { "old-a.blk", "old-b.blk" };
    var checkedPaths = Array.Empty<string>();

    AssertSequence(
        saved,
        MainForm.ResolveSelectedBlockFilesForSave(StockPoolSource.TdxBlock, saved, checkedPaths, false),
        "preserve unloaded TDX selection");
    AssertSequence(
        saved,
        MainForm.ResolveSelectedBlockFilesForSave(StockPoolSource.Hotlist, saved, checkedPaths, false),
        "preserve hotlist selection");
    AssertSequence(
        ["new.blk"],
        MainForm.ResolveSelectedBlockFilesForSave(StockPoolSource.TdxBlock, saved, ["new.blk"], true),
        "persist loaded TDX selection");
});

Run("Hotlist pool loader normalizes platform payloads", () =>
{
    using var eastmoney = JsonDocument.Parse("""{"data":[{"sc":"SZ000001","sn":"平安银行"},{"sc":"SH688001","sn":"样本股"}]}""");
    using var ths = JsonDocument.Parse("""{"data":{"stock_list":[{"code":"300750","name":"宁德时代"}]}}""");
    using var kpl = JsonDocument.Parse("""{"List":[["600519","贵州茅台","1.2","",1]]}""");
    using var cls = JsonDocument.Parse("""{"errno":0,"data":[{"stock":{"StockID":"002594","name":"比亚迪"}}]}""");
    using var tgb = JsonDocument.Parse("""{"dto":[{"fullCode":"SZ002475","stockName":"立讯精密"}]}""");
    using var dzh = JsonDocument.Parse("""{"result":[{"SH600000":100}]}""");

    var stocks = HotlistPoolLoader.ExtractStocks("eastmoney", eastmoney.RootElement)
        .Concat(HotlistPoolLoader.ExtractStocks("ths", ths.RootElement))
        .Concat(HotlistPoolLoader.ExtractStocks("kpl", kpl.RootElement))
        .Concat(HotlistPoolLoader.ExtractStocks("cls", cls.RootElement))
        .Concat(HotlistPoolLoader.ExtractStocks("tgb", tgb.RootElement))
        .Concat(HotlistPoolLoader.ExtractStocks("dzh", dzh.RootElement))
        .ToArray();

    AssertSequence(
        ["000001", "688001", "300750", "600519", "002594", "002475", "600000"],
        stocks.Select(stock => stock.Code).ToArray(),
        "hotlist codes");
    AssertEqual("平安银行", stocks[0].Name, "hotlist stock name");
});

Run("Hotlist pool loader rejects non A-share codes", () =>
{
    AssertEqual(null, HotlistPoolLoader.NormalizeStockCode("HK00700"), "HK code rejected");
    AssertEqual(null, HotlistPoolLoader.NormalizeStockCode("1000001"), "index code rejected");
    AssertEqual("000001", HotlistPoolLoader.NormalizeStockCode("SZ000001"), "A-share normalized");
});

Run("Main form detects ST stock names", () =>
{
    AssertTrue(MainForm.IsStStockName("ST中南"), "ST prefix");
    AssertTrue(MainForm.IsStStockName("*ST华铁"), "*ST prefix");
    AssertTrue(MainForm.IsStStockName("华铁退"), "delisting name");
    AssertTrue(!MainForm.IsStStockName("平安银行"), "normal name");
});

Run("Settings form annotates event type options", () =>
{
    var settingsFormType = typeof(MainForm).Assembly.GetType("YiDongJingLing.SettingsForm")
        ?? throw new InvalidOperationException("SettingsForm type not found");
    var eventTypeOptions = settingsFormType.GetMethod(
        "EventTypeOptions",
        System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)
        ?? throw new InvalidOperationException("EventTypeOptions method not found");
    var options = eventTypeOptions.Invoke(null, []) as System.Collections.IEnumerable
        ?? throw new InvalidOperationException("EventTypeOptions result is not enumerable");
    var labels = options.Cast<object>().Select(item => item.ToString() ?? "").ToArray();

    AssertTrue(labels.Length > 0, "event options exist");
    AssertTrue(labels.All(item => item.Contains(" - ", StringComparison.Ordinal)), "all options include rule notes");
    AssertTrue(labels.Contains("封涨停板 - 涨停价+买一封单"), "limit-up note");
    AssertTrue(labels.Contains("成交增量加速 - 近30秒成交量放大"), "volume acceleration note");
    AssertTrue(labels.Contains("买卖价差异常 - 买卖一价差过大"), "spread note");
});

Run("Event radar message notifier posts compatible payload to proxy", () =>
{
    var handler = new StubNotificationHandler();
    using var notifier = new EventRadarMessageNotifier(handler);
    var timestamp = DateTimeOffset.Parse("2026-05-20T10:00:00+08:00");

    var result = notifier.SendEventsAsync(
        [Event("002445", "中南文化", L1EventType.FastRise, "快速拉升", timestamp)],
        new Uri("http://127.0.0.1:3000"))
        .GetAwaiter()
        .GetResult();

    AssertEqual(1, result.Queued, "queued count");
    AssertEqual("/api/notifications/event-radar/events", handler.LastRequestPath, "request path");
    using var document = JsonDocument.Parse(handler.LastRequestBody);
    var root = document.RootElement;
    AssertEqual("yidong-jingling", root.GetProperty("source").GetString(), "source");
    var payload = root.GetProperty("events")[0];
    AssertEqual("快速拉升", payload.GetProperty("typeName").GetString(), "typeName");
    AssertEqual("002445", payload.GetProperty("code").GetString(), "code");
    AssertEqual("中南文化", payload.GetProperty("name").GetString(), "name");
    AssertEqual(timestamp.ToUnixTimeMilliseconds(), payload.GetProperty("timestamp").GetInt64(), "timestamp");
    AssertEqual(5m, payload.GetProperty("changePct").GetDecimal(), "change pct");
});

Run("Opening signal reporter posts canonical payload to proxy", () =>
{
    var handler = new StubNotificationHandler("""{"ok":true,"accepted":true,"voiceOwner":"desktop","dedupeAction":"created"}""");
    using var reporter = new OpeningSignalReporter(handler);
    var timestamp = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00");
    var item = Event("002552", "宝鼎科技", L1EventType.OpeningWeakToStrong, "竞价弱转强", timestamp) with
    {
        OpeningSignal = new OpeningWeakToStrongSignal(
            "2026-05-22",
            "002552",
            "宝鼎科技",
            "opening_weak_to_strong",
            "strong",
            82m,
            "auction_gap_reversal",
            timestamp,
            false,
            35.68m,
            -1.44m,
            36.92m,
            1.99m,
            37.48m,
            3.54m,
            4.98m,
            56_000_000m,
            50_000_000m,
            DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"),
            35m,
            -3.31m,
            2_000_000m,
            DateTimeOffset.Parse("2026-05-22T09:24:05+08:00"),
            35.3m,
            -2.49m,
            4_500_000m,
            DateTimeOffset.Parse("2026-05-22T09:25:01+08:00"),
            35.68m,
            -1.44m,
            6_000_000m,
            1.87m,
            1.05m,
            4_000_000m,
            1_500_000m,
            2.0m,
            0.33m,
            true,
            "active",
            "review_only",
            "amount=56000000;volume=14950000",
            "openingLiquidityMinAmount=5000000;minCurrentAmount=30000000;hotAmount=100000000;minCurrentVolume=1000000",
            "liquidity-review.v1",
            null,
            "good",
            DateTimeOffset.Parse("2026-05-22T09:25:01+08:00"),
            DateTimeOffset.Parse("2026-05-22T09:25:01+08:00"),
            DateTimeOffset.Parse("2026-05-22T09:30:06+08:00"),
            1,
            0,
            305_000,
            true,
            132,
            128,
            420,
            1,
            2,
            null,
            [],
            "",
            0.97m,
            "pending",
            "pending",
            timestamp,
            37.48m,
            3.54m,
            56_000_000m,
            "09:30-09:35已触发，等待盘中确认",
            "opening-weak-to-strong.v1",
            "owts-test",
            [],
            [])
    };

    var result = reporter.ReportAsync(item, new Uri("http://127.0.0.1:3000"))
        .GetAwaiter()
        .GetResult();

    AssertEqual("/api/opening-signals", handler.LastRequestPath, "opening request path");
    AssertEqual("desktop", result.VoiceOwner, "voice owner");
    using var document = JsonDocument.Parse(handler.LastRequestBody);
    var root = document.RootElement;
    AssertEqual("desktop", root.GetProperty("source").GetString(), "source");
    var payload = root.GetProperty("signal");
    AssertEqual("opening_weak_to_strong", payload.GetProperty("signalType").GetString(), "signal type");
    AssertEqual("002552", payload.GetProperty("code").GetString(), "signal code");
    AssertEqual(82m, payload.GetProperty("score").GetDecimal(), "signal score");
    AssertEqual(1, payload.GetProperty("auctionSampleCount").GetInt32(), "auction sample count");
    AssertEqual(128, payload.GetProperty("receivedCount").GetInt32(), "received count");
    AssertEqual(0.97m, payload.GetProperty("auctionCoverageRatio").GetDecimal(), "auction coverage ratio");
    AssertEqual(305000, payload.GetProperty("latencyMs").GetInt32(), "latency ms");
    AssertEqual(35.3m, payload.GetProperty("lateBaselinePrice").GetDecimal(), "late baseline price");
    AssertEqual(35.68m, payload.GetProperty("finalBaselinePrice").GetDecimal(), "final baseline price");
    AssertEqual(1.05m, payload.GetProperty("latePriceLiftPctPoint").GetDecimal(), "late price lift");
    AssertEqual(4_000_000m, payload.GetProperty("auctionAmountDelta").GetDecimal(), "auction amount delta");
    AssertEqual(1_500_000m, payload.GetProperty("lateAmountDelta").GetDecimal(), "late amount delta");
    AssertTrue(payload.GetProperty("priceVolumeConfirmed").GetBoolean(), "price volume confirmed");
    AssertEqual("active", payload.GetProperty("liquidityTier").GetString(), "liquidity tier");
    AssertEqual("review_only", payload.GetProperty("liquidityTierMode").GetString(), "liquidity tier mode");
    AssertEqual("amount=56000000;volume=14950000", payload.GetProperty("liquidityTierBasis").GetString(), "liquidity tier basis");
    AssertEqual(
        "openingLiquidityMinAmount=5000000;minCurrentAmount=30000000;hotAmount=100000000;minCurrentVolume=1000000",
        payload.GetProperty("liquidityTierThresholds").GetString(),
        "liquidity tier thresholds");
    AssertEqual("liquidity-review.v1", payload.GetProperty("liquidityTierVersion").GetString(), "liquidity tier version");
});

Run("Event export includes opening weak-to-strong replay fields", () =>
{
    var timestamp = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00");
    var item = Event("002552", "宝鼎科技", L1EventType.OpeningWeakToStrong, "竞价弱转强", timestamp) with
    {
        OpeningSignal = new OpeningWeakToStrongSignal(
            "2026-05-22",
            "002552",
            "宝鼎科技",
            "opening_weak_to_strong",
            "strong",
            82m,
            "auction_gap_reversal",
            timestamp,
            false,
            35.68m,
            -1.44m,
            36.92m,
            1.99m,
            37.48m,
            3.54m,
            4.98m,
            56_000_000m,
            50_000_000m,
            DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"),
            35m,
            -3.31m,
            2_000_000m,
            DateTimeOffset.Parse("2026-05-22T09:24:05+08:00"),
            35.3m,
            -2.49m,
            4_500_000m,
            DateTimeOffset.Parse("2026-05-22T09:25:01+08:00"),
            35.68m,
            -1.44m,
            6_000_000m,
            1.87m,
            1.05m,
            4_000_000m,
            1_500_000m,
            2.0m,
            0.33m,
            true,
            "active",
            "review_only",
            "amount=56000000;volume=14950000",
            "openingLiquidityMinAmount=5000000;minCurrentAmount=30000000;hotAmount=100000000;minCurrentVolume=1000000",
            "liquidity-review.v1",
            6.2m,
            "good",
            DateTimeOffset.Parse("2026-05-22T09:25:01+08:00"),
            DateTimeOffset.Parse("2026-05-22T09:25:01+08:00"),
            DateTimeOffset.Parse("2026-05-22T09:30:06+08:00"),
            2,
            0,
            305_000,
            true,
            132,
            128,
            420,
            1,
            2,
            30m,
            ["tdx_block_candidate"],
            "tdx_block",
            0.97m,
            "pending",
            "pending",
            timestamp,
            37.48m,
            3.54m,
            56_000_000m,
            "09:30-09:35已触发，等待盘中确认",
            "opening-weak-to-strong.v1",
            "owts-test",
            [],
            [new OpeningWeakToStrongRiskFlag("amount_regressed", "medium", -35m)])
    };

    var lines = MainForm.BuildExportLines([item], csv: true);
    var header = lines[0].Split(',');
    var values = lines[1].Split(',');
    var byHeader = header
        .Select((name, index) => new { name, index })
        .ToDictionary(item => item.name, item => values[item.index], StringComparer.Ordinal);

    AssertTrue(lines[0].Contains("弱转强形态"), "opening export header");
    AssertTrue(lines[0].Contains("流动性分层"), "liquidity export header");
    AssertEqual(header.Length, values.Length, "csv header and value count");
    AssertEqual("pending", byHeader["盘中状态"], "intraday status column");
    AssertEqual("pending", byHeader["盘中结果"], "intraday outcome column");
    AssertEqual("2026-05-22 09:30:06", byHeader["盘中状态时间"], "intraday status time column");
    AssertEqual("37.48", byHeader["盘中价"], "intraday price column");
    AssertEqual("3.54", byHeader["盘中涨幅"], "intraday pct column");
    AssertEqual("5600万", byHeader["盘中成交额"], "intraday amount column");
    AssertEqual("09:30-09:35已触发，等待盘中确认", byHeader["盘中说明"], "intraday note column");
    AssertTrue(lines[1].Contains("auction_gap_reversal"), "opening variant exported");
    AssertTrue(lines[1].Contains("35.68"), "auction final price exported");
    AssertTrue(lines[1].Contains("35.3"), "late baseline price exported");
    AssertTrue(lines[1].Contains("37.48"), "first window price exported");
    AssertTrue(lines[1].Contains("4.98"), "jump pct point exported");
    AssertTrue(lines[1].Contains("150万"), "late amount delta exported");
    AssertTrue(lines[1].Contains("active"), "liquidity tier exported");
    AssertTrue(lines[1].Contains("review_only"), "liquidity tier mode exported");
    AssertTrue(lines[1].Contains("amount=56000000;volume=14950000"), "liquidity tier basis exported");
    AssertTrue(lines[1].Contains("openingLiquidityMinAmount=5000000"), "liquidity tier thresholds exported");
    AssertTrue(lines[1].Contains("5000万"), "amount delta exported");
    AssertTrue(lines[1].Contains("128"), "received count exported");
    AssertTrue(lines[1].Contains("0.97"), "coverage ratio exported");
    AssertTrue(lines[1].Contains("tdx_block"), "previous weak context exported");
    AssertTrue(lines[1].Contains("amount_regressed"), "risk flag exported");
});

Run("TDX bridge full state merges quote and depth into one snapshot", () =>
{
    using var client = new TdxBridgeClient("ws://127.0.0.1:8765/ws/quotes");
    IReadOnlyList<QuoteSnapshot> received = [];
    client.QuotesReceived += (_, quotes) => received = quotes;

    var message = """
        {
          "type": "full_state",
          "serverTs": 1779252000000,
          "quotes": [
            { "code": "600000", "name": "浦发银行", "lastPrice": 10.5, "changePct": 5, "volume": 1000, "amount": 1050000, "preClose": 10, "capturedAt": "2026-05-20T09:25:01+08:00", "bridgeTs": "2026-05-20T09:25:02+08:00", "openingForcedSample": true, "requestedCount": 132, "receivedCount": 128, "elapsedMs": 420, "slowBatches": 1, "truncatedBatches": 2 }
          ],
          "depth": [
            { "code": "600000", "bids": [{ "price": 10.5, "volume": 2000 }], "asks": [{ "price": 10.51, "volume": 1500 }] }
          ]
        }
        """;
    InvokeHandleMessage(client, message);

    AssertEqual(1, received.Count, "snapshot count");
    AssertEqual("600000", received[0].Code, "snapshot code");
    AssertEqual(1, received[0].Bids.Count, "bid levels");
    AssertEqual(1, received[0].Asks.Count, "ask levels");
    AssertEqual(DateTimeOffset.Parse("2026-05-20T09:25:01+08:00"), received[0].CapturedAt, "capturedAt");
    AssertEqual(DateTimeOffset.Parse("2026-05-20T09:25:02+08:00"), received[0].BridgeTs, "bridgeTs");
    AssertTrue(received[0].OpeningForcedSample, "opening forced sample");
    AssertEqual(132, received[0].RequestedCount ?? -1, "requested count");
    AssertEqual(128, received[0].ReceivedCount ?? -1, "received count");
    AssertEqual(420, received[0].ElapsedMs ?? -1, "elapsed ms");
    AssertEqual(1, received[0].SlowBatches ?? -1, "slow batches");
    AssertEqual(2, received[0].TruncatedBatches ?? -1, "truncated batches");
});

Run("Speech announcer sends selected voice to VoiceWorker", () =>
{
    var handler = new StubVoiceWorkerHandler();
    using var announcer = new SpeechAnnouncer(ProjectRootLocator.Find(), handler: handler)
    {
        Enabled = true,
        Rate = 1.2,
        Volume = 80,
        Voice = "Microsoft Kangkang",
    };

    announcer.AnnounceAsync([Event("002445", "中南文化", L1EventType.FastRise, "快速拉升", DateTimeOffset.Now)])
        .GetAwaiter()
        .GetResult();

    AssertEqual("Microsoft Kangkang", handler.LastSpeakVoice, "selected voice");
    AssertEqual(1.2d, handler.LastSpeakRate, "rate");
    AssertEqual(80, handler.LastSpeakVolume, "volume");
});

Console.WriteLine("All YiDongJingLing tests passed.");

static QuoteSnapshot Quote(
    string code,
    string name,
    decimal price,
    decimal changePct,
    decimal preClose,
    IReadOnlyList<QuoteLevel>? bids = null,
    IReadOnlyList<QuoteLevel>? asks = null,
    DateTimeOffset? time = null,
    decimal volume = 10000,
    decimal amount = 100000000)
{
    return new QuoteSnapshot(
        code,
        name,
        price,
        changePct,
        price - preClose,
        volume,
        amount,
        preClose,
        Math.Max(price, preClose),
        Math.Min(price, preClose),
        preClose,
        bids ?? [],
        asks ?? [],
        time ?? DateTimeOffset.Parse("2026-05-20T10:00:00+08:00"));
}

static QuoteLevel Level(decimal price, decimal volume) => new(price, volume);

static EventRecord Event(string code, string name, L1EventType type, string typeName, DateTimeOffset timestamp)
{
    return new EventRecord(
        type,
        typeName,
        code,
        name,
        10m,
        5m,
        10000m,
        100000000m,
        timestamp,
        L1EventSeverity.Important,
        "test");
}

static OpeningWeakToStrongSignal TestOpeningSignal(DateTimeOffset timestamp, bool dryRun)
{
    return new OpeningWeakToStrongSignal(
        timestamp.ToString("yyyy-MM-dd"),
        "002560",
        "低覆盖",
        "opening_weak_to_strong",
        "strong",
        82m,
        "auction_gap_reversal",
        timestamp,
        dryRun,
        9.9m,
        -1m,
        10.1m,
        1m,
        10.35m,
        3.5m,
        4.5m,
        50_000_000m,
        45_000_000m,
        DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"),
        9.8m,
        -2m,
        2_000_000m,
        DateTimeOffset.Parse("2026-05-22T09:24:00+08:00"),
        9.85m,
        -1.5m,
        3_000_000m,
        DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"),
        9.9m,
        -1m,
        5_000_000m,
        1m,
        0.5m,
        3_000_000m,
        2_000_000m,
        1.5m,
        0.2m,
        true,
        "active",
        "review_only",
        "amount=50000000;volume=5000000",
        "openingLiquidityMinAmount=5000000;minCurrentAmount=30000000;hotAmount=100000000;minCurrentVolume=1000000",
        "liquidity-review.v1",
        null,
        "good",
        DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"),
        DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"),
        timestamp,
        1,
        0,
        306_000,
        true,
        100,
        90,
        1800,
        2,
        1,
        null,
        [],
        "",
        0.9m,
        "pending",
        "pending",
        timestamp,
        10.35m,
        3.5m,
        50_000_000m,
        "09:30-09:35已触发，等待盘中确认",
        "opening-weak-to-strong.v1",
        "owts-test",
        [],
        [new OpeningWeakToStrongRiskFlag("auction_coverage_low", "medium", -35m)]);
}

static bool IsAuctionFinalQuote(OpeningWeakToStrongQuote quote)
{
    return quote.At.ToLocalTime().TimeOfDay >= TimeSpan.Parse("09:25:00") &&
        quote.At.ToLocalTime().TimeOfDay < TimeSpan.Parse("09:26:00");
}

static void InvokeHandleMessage(TdxBridgeClient client, string message)
{
    var method = typeof(TdxBridgeClient).GetMethod(
        "HandleMessage",
        System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
    if (method is null) throw new InvalidOperationException("HandleMessage not found");
    method.Invoke(client, [message]);
}

static void Run(string name, Action action)
{
    try
    {
        action();
        Console.WriteLine($"PASS {name}");
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"FAIL {name}: {ex.Message}");
        Environment.ExitCode = 1;
        throw;
    }
}

static void AssertEqual<T>(T expected, T actual, string label)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
        throw new InvalidOperationException($"{label}: expected {expected}, got {actual}");
}

static void AssertTrue(bool value, string label)
{
    if (!value) throw new InvalidOperationException(label);
}

static void AssertNotCode(string code, string actual, string label)
{
    if (string.IsNullOrWhiteSpace(actual) || actual == code)
        throw new InvalidOperationException($"{label}: expected stock name, got {actual}");
}

static void AssertSequence<T>(IReadOnlyList<T> expected, IReadOnlyList<T> actual, string label)
{
    if (expected.Count != actual.Count)
        throw new InvalidOperationException($"{label}: expected {expected.Count} items, got {actual.Count}");

    for (var i = 0; i < expected.Count; i++)
    {
        if (!EqualityComparer<T>.Default.Equals(expected[i], actual[i]))
            throw new InvalidOperationException($"{label}[{i}]: expected {expected[i]}, got {actual[i]}");
    }
}

sealed class StubVoiceWorkerHandler : HttpMessageHandler
{
    public string LastSpeakVoice { get; private set; } = "";
    public double LastSpeakRate { get; private set; }
    public int LastSpeakVolume { get; private set; }

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var path = request.RequestUri?.AbsolutePath ?? "";
        if (request.Method == HttpMethod.Get && path == "/health")
        {
            return JsonResponse(new { ok = true, service = "VoiceWorker" });
        }

        if (request.Method == HttpMethod.Get && path == "/status")
        {
            return JsonResponse(new
            {
                ok = true,
                supported = true,
                engine = "local-onecore",
                voice = "Microsoft Kangkang",
                voices = new[] { new { name = "Microsoft Kangkang", culture = "zh-CN", gender = "Male" } },
            });
        }

        if (request.Method == HttpMethod.Post && path == "/speak")
        {
            var json = request.Content?.ReadAsStringAsync(cancellationToken).GetAwaiter().GetResult() ?? "{}";
            using var document = JsonDocument.Parse(json);
            LastSpeakVoice = document.RootElement.GetProperty("voice").GetString() ?? "";
            LastSpeakRate = document.RootElement.GetProperty("rate").GetDouble();
            LastSpeakVolume = document.RootElement.GetProperty("volume").GetInt32();
            return JsonResponse(new { ok = true, queued = true });
        }

        if (request.Method == HttpMethod.Post && (path == "/stop" || path == "/shutdown" || path == "/test"))
        {
            return JsonResponse(new { ok = true });
        }

        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
    }

    private static Task<HttpResponseMessage> JsonResponse(object payload)
    {
        var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions(JsonSerializerDefaults.Web));
        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(json, Encoding.UTF8, "application/json"),
        });
    }
}

sealed class StubNotificationHandler : HttpMessageHandler
{
    private readonly string _responseBody;
    public string LastRequestPath { get; private set; } = "";
    public string LastRequestBody { get; private set; } = "";

    public StubNotificationHandler(string responseBody = """{"ok":true,"queued":1,"sent":0,"skipped":0}""")
    {
        _responseBody = responseBody;
    }

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        LastRequestPath = request.RequestUri?.AbsolutePath ?? "";
        LastRequestBody = request.Content?.ReadAsStringAsync(cancellationToken).GetAwaiter().GetResult() ?? "";
        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(_responseBody, Encoding.UTF8, "application/json"),
        });
    }
}
