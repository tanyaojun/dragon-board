using YiDongJingLing;
using YiDongJingLing.Blocks;
using YiDongJingLing.Diagnostics;
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

Run("Opening weak-to-strong detector matches five checkpoint PASS/FAIL acceptance", () =>
{
    var rules = LoadOpeningRules();
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);
    var results = RunOpeningCheckpointAcceptance(store, detector);

    AssertSequence(
        ["09:20:PASS:auctionConditionPassed:False", "09:25:PASS:auctionConditionPassed:False", "09:30:PASS:gapAlert:True", "09:35:PASS:trendConfirm:True", "10:00:PASS:optionalFinalStatus:False"],
        results,
        "opening checkpoint acceptance");
});

Run("Opening weak-to-strong detector rejects candidate when 09:24 late baseline does not lift enough", () =>
{
    var rules = LoadOpeningRules();
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);
    OpeningWeakToStrongResult? result = null;
    var quotes = new[]
    {
        OpeningCheckpointQuote("2026-06-03", "09:20:00", 9.7m, 10m, 1_000_000m, 100_000m),
        OpeningCheckpointQuote("2026-06-03", "09:24:00", 9.9m, 10m, 1_900_000m, 170_000m),
        OpeningCheckpointQuote("2026-06-03", "09:25:00", 9.92m, 10m, 2_000_000m, 180_000m),
    };

    foreach (var quote in quotes)
    {
        store.Capture(quote);
        result = detector.Evaluate(quote, store.GetBaseline(quote.Code, quote.At));
    }

    AssertTrue(result?.Triggered == false, "late baseline should not be triggered");
    AssertEqual("", result?.Stage ?? "missing", "late baseline failed stage should be empty");
});

Run("Opening weak-to-strong detector accepts candidate when 09:24 late baseline confirms", () =>
{
    var rules = LoadOpeningRules();
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);
    OpeningWeakToStrongResult? result = null;
    var quotes = new[]
    {
        OpeningCheckpointQuote("2026-06-03", "09:20:00", 9.7m, 10m, 1_000_000m, 100_000m),
        OpeningCheckpointQuote("2026-06-03", "09:24:00", 9.86m, 10m, 1_500_000m, 150_000m),
        OpeningCheckpointQuote("2026-06-03", "09:25:00", 9.92m, 10m, 2_000_000m, 180_000m),
    };

    foreach (var quote in quotes)
    {
        store.Capture(quote);
        result = detector.Evaluate(quote, store.GetBaseline(quote.Code, quote.At));
    }

    AssertEqual("auctionConditionPassed", result?.Stage ?? "", "late baseline passed stage");
    AssertTrue(result?.VoiceEligible == false, "late baseline passed voice");
});

Run("Opening weak-to-strong detector treats delayed 09:25 auction sample as confirm baseline", () =>
{
    var rules = LoadOpeningRules();
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);
    var initial = OpeningCheckpointQuote("2026-06-04", "09:20:00", 9.7m, 10m, 1_000_000m, 100_000m);
    var late = OpeningCheckpointQuote("2026-06-04", "09:24:00", 9.86m, 10m, 1_500_000m, 150_000m);
    var delayedFinal = OpeningCheckpointQuote("2026-06-04", "09:25:01", 9.92m, 10m, 2_000_000m, 180_000m);
    var gap = OpeningCheckpointQuote("2026-06-04", "09:30:00", 10.23m, 10m, 2_800_000m, 230_000m) with
    {
        Open = 10.23m,
    };

    foreach (var quote in new[] { initial, late, delayedFinal })
    {
        store.Capture(quote);
        var candidate = detector.Evaluate(quote, store.GetBaseline(quote.Code, quote.At));
        if (quote == delayedFinal)
        {
            AssertEqual("auctionConditionPassed", candidate.Stage, "delayed 09:25 baseline emits candidate");
        }
    }

    var result = detector.Evaluate(gap, store.GetBaseline(gap.Code, gap.At));

    AssertEqual("gapAlert", result.Stage, "delayed 09:25 baseline supports gap alert");
    AssertTrue(result.VoiceEligible, "delayed 09:25 baseline voice");
    AssertEqual(null, result.InvalidReason, "delayed 09:25 baseline invalid reason");
});

Run("Opening weak-to-strong detector alerts water-under auction lift with opening support", () =>
{
    var rules = LoadOpeningRules();
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);
    var quotes = new[]
    {
        OpeningCheckpointQuote("2026-06-04", "09:20:00", 96.5m, 100m, 9_000_000m, 90_000m, "600360", "华微电子"),
        OpeningCheckpointQuote("2026-06-04", "09:24:50", 97.12m, 100m, 13_310_000m, 133_100m, "600360", "华微电子"),
        OpeningCheckpointQuote("2026-06-04", "09:24:59", 97.43m, 100m, 17_480_000m, 174_800m, "600360", "华微电子"),
        OpeningCheckpointQuote("2026-06-04", "09:30:00", 99.8m, 100m, 42_000_000m, 420_000m, "600360", "华微电子") with
        {
            Open = 99.6m,
        },
        OpeningCheckpointQuote("2026-06-04", "09:35:00", 99.82m, 100m, 68_000_000m, 680_000m, "600360", "华微电子") with
        {
            Open = 99.6m,
        },
    };
    var results = new List<OpeningWeakToStrongResult>();

    foreach (var quote in quotes)
    {
        store.Capture(quote);
        var result = detector.Evaluate(quote, store.GetBaseline(quote.Code, quote.At));
        if (result.Triggered)
        {
            results.Add(result);
        }
    }

    AssertSequence(
        ["auctionConditionPassed:False", "gapAlert:True", "trendConfirm:True"],
        results.Select(item => $"{item.Stage}:{item.VoiceEligible}").ToArray(),
        "water-under opening support stages");
    AssertTrue(results[1].Reason.Contains("承接"), "opening support reason");
});

Run("Opening weak-to-strong detector alerts delayed 600703 opening rebound", () =>
{
    var rules = LoadOpeningRules();
    var store = new OpeningAuctionStateStore(rules);
    var detector = new OpeningWeakToStrongDetector(rules);
    var quotes = new[]
    {
        OpeningCheckpointQuote("2026-06-04", "09:20:00", 15.32m, 15.51m, 12_000_000m, 780_000m, "600703", "三安光电"),
        OpeningCheckpointQuote("2026-06-04", "09:24:48", 15.30m, 15.51m, 27_450_000m, 1_794_400m, "600703", "三安光电"),
        OpeningCheckpointQuote("2026-06-04", "09:25:01", 15.47m, 15.51m, 43_032_900m, 2_782_000m, "600703", "三安光电"),
        OpeningCheckpointQuote("2026-06-04", "09:30:01", 15.79m, 15.51m, 125_000_000m, 8_018_300m, "600703", "三安光电") with
        {
            Open = 15.47m,
        },
        OpeningCheckpointQuote("2026-06-04", "09:35:01", 16.01m, 15.51m, 630_600_000m, 39_388_000m, "600703", "三安光电") with
        {
            Open = 15.47m,
        },
    };
    var results = new List<OpeningWeakToStrongResult>();

    foreach (var quote in quotes)
    {
        store.Capture(quote);
        var result = detector.Evaluate(quote, store.GetBaseline(quote.Code, quote.At));
        if (result.Triggered)
        {
            results.Add(result);
        }
    }

    AssertSequence(
        ["auctionConditionPassed:False", "gapAlert:True", "trendConfirm:True"],
        results.Select(item => $"{item.Stage}:{item.VoiceEligible}").ToArray(),
        "delayed 600703 opening rebound stages");
});

Run("Event engine emits opening checkpoint events with stage names", () =>
{
    var engine = new L1EventEngine();
    var quotes = OpeningCheckpointSnapshots();

    engine.Prime(quotes[0]);
    engine.Prime(quotes[1]);
    engine.Prime(quotes[2]);
    var candidate = engine.Evaluate(quotes[2], quotes[1], quotes[..3]).Single(item => item.Type == L1EventType.OpeningWeakToStrong);
    var gap = engine.Evaluate(quotes[3], quotes[2], quotes[..4]).Single(item => item.Type == L1EventType.OpeningWeakToStrong);
    var trend = engine.Evaluate(quotes[4], quotes[3], quotes[..5]).Single(item => item.Type == L1EventType.OpeningWeakToStrong);
    var final = engine.Evaluate(quotes[5], quotes[4], quotes).Single(item => item.Type == L1EventType.OpeningWeakToStrong);

    AssertSequence(
        ["auctionConditionPassed", "gapAlert", "trendConfirm", "optionalFinalStatus"],
        [candidate.OpeningSignal?.Stage ?? "", gap.OpeningSignal?.Stage ?? "", trend.OpeningSignal?.Stage ?? "", final.OpeningSignal?.Stage ?? ""],
        "event stages");
    AssertSequence(
        ["竞价弱转强候选", "开盘承接转强", "开盘反攻确认", "竞价弱转强复盘"],
        [candidate.TypeName, gap.TypeName, trend.TypeName, final.TypeName],
        "event type names");
    AssertSequence(
        ["False", "True", "True", "False"],
        [candidate.OpeningSignal!.VoiceEligible.ToString(), gap.OpeningSignal!.VoiceEligible.ToString(), trend.OpeningSignal!.VoiceEligible.ToString(), final.OpeningSignal!.VoiceEligible.ToString()],
        "event voice flags");
});

Run("Event engine keeps opening checkpoints scoped to the trading day", () =>
{
    var engine = new L1EventEngine();
    var day1 = OpeningCheckpointSnapshots("2026-06-03");
    var day2 = OpeningCheckpointSnapshots("2026-06-04");

    engine.Prime(day1[0]);
    engine.Prime(day1[1]);
    engine.Prime(day1[2]);
    var day1Candidate = engine.Evaluate(day1[2], day1[1], day1[..3]);
    var crossDayWithoutBaseline = engine.Evaluate(day2[3], day1[2], [day2[3]]);
    engine.Prime(day2[0]);
    engine.Prime(day2[1]);
    engine.Prime(day2[2]);
    var day2Candidate = engine.Evaluate(day2[2], day2[1], day2[..3]);

    AssertEqual(1, day1Candidate.Count(item => item.Type == L1EventType.OpeningWeakToStrong), "day 1 candidate");
    AssertEqual(0, crossDayWithoutBaseline.Count(item => item.Type == L1EventType.OpeningWeakToStrong), "no cross-day gap without day baseline");
    AssertEqual(1, day2Candidate.Count(item => item.Type == L1EventType.OpeningWeakToStrong), "day 2 candidate");
});

Run("Event deduper allows later opening checkpoint stages inside cooldown", () =>
{
    var deduper = new EventDeduper(TimeSpan.FromMinutes(5));
    var timestamp = DateTimeOffset.Parse("2026-06-03T09:25:00+08:00");
    var candidate = Event("002552", "宝鼎科技", L1EventType.OpeningWeakToStrong, "竞价弱转强候选", timestamp) with
    {
        OpeningSignal = TestOpeningSignal(timestamp) with { Stage = "auctionConditionPassed", VoiceEligible = false }
    };
    var gap = candidate with
    {
        TypeName = "开盘承接转强",
        Timestamp = timestamp.AddMinutes(5),
        OpeningSignal = TestOpeningSignal(timestamp.AddMinutes(5)) with { Stage = "gapAlert", VoiceEligible = true }
    };

    AssertEqual(1, deduper.Filter([candidate]).Count, "candidate emitted");
    var upgrade = deduper.Filter([gap]);

    AssertEqual(1, upgrade.Count, "later checkpoint emitted inside cooldown");
    AssertEqual("gapAlert", upgrade[0].OpeningSignal?.Stage, "later checkpoint stage");
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

Run("Push policy sends only strong event radar signals", () =>
{
    var now = DateTimeOffset.Parse("2026-05-20T10:00:00+08:00");
    var fastRise = Event("002445", "中南文化", L1EventType.FastRise, "快速拉升", now);
    var amountTier = Event("002446", "普通跨档", L1EventType.AmountTier, "成交额跨档", now)
        with { Severity = L1EventSeverity.Normal };
    var bidPressure = Event("300001", "特锐德", L1EventType.BidPressure, "盘口买压增强", now)
        with { Severity = L1EventSeverity.Normal };

    var pushEvents = EventVoicePolicy.FilterForPush([fastRise, amountTier, bidPressure]);

    AssertEqual(1, pushEvents.Count, "push count");
    AssertEqual(L1EventType.FastRise, pushEvents[0].Type, "push event type");
});

Run("Voice policy only announces 09:30 gap and 09:35 trend opening checkpoints", () =>
{
    var timestamp = DateTimeOffset.Parse("2026-06-03T09:30:00+08:00");
    var candidate = Event("002560", "竞价候选", L1EventType.OpeningWeakToStrong, "竞价弱转强候选", timestamp) with
    {
        OpeningSignal = TestOpeningSignal(timestamp) with
        {
            Stage = "auctionConditionPassed",
            VoiceEligible = false,
        }
    };
    var gap = candidate with
    {
        Code = "002561",
        OpeningSignal = TestOpeningSignal(timestamp) with
        {
            Code = "002561",
            Stage = "gapAlert",
            VoiceEligible = true,
        }
    };
    var trend = candidate with
    {
        Code = "002562",
        OpeningSignal = TestOpeningSignal(timestamp.AddMinutes(5)) with
        {
            Code = "002562",
            Stage = "trendConfirm",
            VoiceEligible = true,
        }
    };
    var final = candidate with
    {
        Code = "002563",
        OpeningSignal = TestOpeningSignal(timestamp.AddMinutes(30)) with
        {
            Code = "002563",
            Stage = "optionalFinalStatus",
            VoiceEligible = false,
        }
    };

    var voiceEvents = EventVoicePolicy.FilterForVoice([candidate, gap, trend, final], VoiceMode.StrongOnly);

    AssertSequence(["002561", "002562"], voiceEvents.Select(item => item.Code).ToArray(), "stage voice events");
});

Run("Push policy sends only voiced opening checkpoints", () =>
{
    var now = DateTimeOffset.Parse("2026-06-03T09:30:00+08:00");
    var candidate = Event("002560", "竞价候选", L1EventType.OpeningWeakToStrong, "竞价弱转强候选", now) with
    {
        OpeningSignal = TestOpeningSignal(now) with { Stage = "auctionConditionPassed", VoiceEligible = false }
    };
    var gap = candidate with
    {
        Code = "002561",
        OpeningSignal = TestOpeningSignal(now) with { Code = "002561", Stage = "gapAlert", VoiceEligible = true }
    };

    var pushEvents = EventVoicePolicy.FilterForPush([candidate, gap]);

    AssertEqual(1, pushEvents.Count, "opening push count");
    AssertEqual("002561", pushEvents[0].Code, "opening push code");
});

Run("TDX bridge normalizes mismatched source change percent from price and pre-close", () =>
{
    AssertEqual(
        -1.05m,
        Math.Round(TdxBridgeClient.NormalizeChangePct(9.895m, 10m, -94.74m), 2),
        "price-like source percent corrected");
    AssertEqual(
        -1.67m,
        Math.Round(TdxBridgeClient.NormalizeChangePct(9.833m, 10m, -0.0167m), 2),
        "ratio source percent corrected");
    AssertEqual(
        1.7m,
        Math.Round(TdxBridgeClient.NormalizeChangePct(10.17m, 10m, 1.7m), 2),
        "valid source percent preserved");
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
        MainForm.IsOpeningAuctionCoverageWindow(DateTimeOffset.Parse("2026-05-22T09:25:10+08:00")),
        "auction coverage window includes 09:25:10");
    AssertTrue(
        !MainForm.IsOpeningAuctionCoverageWindow(DateTimeOffset.Parse("2026-05-22T09:30:00+08:00")),
        "auction coverage window excludes 09:30");
    AssertTrue(
        MainForm.IsOpeningWeakToStrongPreopenWindow(DateTimeOffset.Parse("2026-05-22T09:25:00+08:00")),
        "preopen weak-to-strong window includes 09:25:00");
    AssertTrue(
        MainForm.IsOpeningWeakToStrongPreopenWindow(DateTimeOffset.Parse("2026-05-22T09:25:10+08:00")),
        "preopen weak-to-strong window includes 09:25:10");
    AssertTrue(
        MainForm.IsOpeningWeakToStrongPreopenWindow(DateTimeOffset.Parse("2026-05-22T09:29:59+08:00")),
        "preopen weak-to-strong window includes 09:29:59");
    AssertTrue(
        !MainForm.IsOpeningWeakToStrongPreopenWindow(DateTimeOffset.Parse("2026-05-22T09:30:00+08:00")),
        "preopen weak-to-strong window excludes 09:30");
    AssertEqual(
        "竞价覆盖 90% 90/100 慢2 截1",
        MainForm.OpeningCoverageStatusText("90%", "90", "100", " 慢2 截1"),
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
        OpeningSignal = TestOpeningSignal(timestamp)
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
    AssertSequence(
        ["amount", "code", "name", "pct", "price", "reason", "stage", "status", "time", "voiceEligible"],
        payload.EnumerateObject().Select(item => item.Name).Order(StringComparer.Ordinal).ToArray(),
        "canonical signal fields");
    AssertEqual("002552", payload.GetProperty("code").GetString(), "signal code");
    AssertEqual("gapAlert", payload.GetProperty("stage").GetString(), "signal stage");
    AssertEqual(true, payload.GetProperty("voiceEligible").GetBoolean(), "signal voice eligible");
    AssertEqual("2026-05-22T09:30:06+08:00", payload.GetProperty("time").GetString(), "signal time");
    AssertEqual(37.48m, payload.GetProperty("price").GetDecimal(), "signal price");
    AssertEqual(4.98m, payload.GetProperty("pct").GetDecimal(), "signal pct");
    AssertEqual(50_000_000m, payload.GetProperty("amount").GetDecimal(), "signal amount");
});

Run("Event export includes opening weak-to-strong replay fields", () =>
{
    var timestamp = DateTimeOffset.Parse("2026-05-22T09:30:06+08:00");
    var item = Event("002552", "宝鼎科技", L1EventType.OpeningWeakToStrong, "竞价弱转强", timestamp) with
    {
        OpeningSignal = TestOpeningSignal(timestamp)
    };

    var lines = MainForm.BuildExportLines([item], csv: true);
    var header = lines[0].Split(',');
    var values = lines[1].Split(',');
    var byHeader = header
        .Select((name, index) => new { name, index })
        .ToDictionary(item => item.name, item => values[item.index], StringComparer.Ordinal);

    AssertTrue(lines[0].Contains("弱转强阶段"), "opening export header");
    AssertTrue(!lines[0].Contains("流动性分层"), "liquidity review header removed");
    AssertEqual(header.Length, values.Length, "csv header and value count");
    AssertEqual("gapAlert", byHeader["弱转强阶段"], "opening stage column");
    AssertEqual("True", byHeader["可语音"], "voice eligible column");
    AssertTrue(lines[1].Contains("35.68"), "auction final price exported");
    AssertTrue(lines[1].Contains("37.48"), "first window price exported");
    AssertTrue(lines[1].Contains("4.98"), "jump pct point exported");
    AssertTrue(lines[1].Contains("5000万"), "amount delta exported");
    AssertTrue(lines[1].Contains("128"), "received count exported");
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
    AssertEqual(DateTimeOffset.Parse("2026-05-20T09:25:01+08:00"), received[0].SourceTime, "source time uses quote capturedAt");
    AssertEqual(DateTimeOffset.Parse("2026-05-20T09:25:01+08:00"), received[0].CapturedAt, "capturedAt");
    AssertEqual(DateTimeOffset.Parse("2026-05-20T09:25:02+08:00"), received[0].BridgeTs, "bridgeTs");
    AssertTrue(received[0].OpeningForcedSample, "opening forced sample");
    AssertEqual(132, received[0].RequestedCount ?? -1, "requested count");
    AssertEqual(128, received[0].ReceivedCount ?? -1, "received count");
    AssertEqual(420, received[0].ElapsedMs ?? -1, "elapsed ms");
    AssertEqual(1, received[0].SlowBatches ?? -1, "slow batches");
    AssertEqual(2, received[0].TruncatedBatches ?? -1, "truncated batches");
});

Run("Opening auction sample telemetry writes 09:20 baseline sample", () =>
{
    var tempRoot = Path.Combine(Path.GetTempPath(), "YiDongJingLingTests", Guid.NewGuid().ToString("N"));
    var sink = new OpeningAuctionSampleTelemetryFileSink(tempRoot);
    var timestamp = DateTimeOffset.Parse("2026-06-02T09:20:05+08:00");
    var quote = Quote(
        "600000",
        "浦发银行",
        9.8m,
        -2m,
        10m,
        time: timestamp,
        amount: 8_000_000m) with
    {
        CapturedAt = timestamp,
        BridgeTs = timestamp.AddMilliseconds(120),
        OpeningForcedSample = true,
        RequestedCount = 100,
        ReceivedCount = 96,
        ElapsedMs = 320,
        SlowBatches = 1,
        TruncatedBatches = 0,
    };

    sink.Record(OpeningAuctionSampleTelemetryRecord.FromQuote(quote));

    var path = Path.Combine(tempRoot, "opening-auction-samples-2026-06-02.jsonl");
    var line = File.ReadAllText(path);
    AssertTrue(line.Contains("\"inInitialBaselineWindow\":true"), "initial baseline window exported");
    AssertTrue(line.Contains("\"openingForcedSample\":true"), "forced sample exported");
    AssertTrue(line.Contains("\"coverageRatio\":0.96"), "coverage ratio exported");
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

static OpeningWeakToStrongRules LoadOpeningRules()
{
    var fixturePath = Path.Combine(
        ProjectRootLocator.Find(),
        "docs",
        "yidong-jingling",
        "fixtures",
        "opening-weak-to-strong-cases.json");
    using var document = JsonDocument.Parse(File.ReadAllText(fixturePath));
    return OpeningWeakToStrongRules.FromJson(document.RootElement.GetProperty("rules"));
}

static IReadOnlyList<OpeningWeakToStrongResult> RunOpeningCheckpoints(
    OpeningAuctionStateStore store,
    OpeningWeakToStrongDetector detector)
{
    var results = new List<OpeningWeakToStrongResult>();
    foreach (var quote in OpeningCheckpointQuotes())
    {
        store.Capture(quote);
        var result = detector.Evaluate(quote, store.GetBaseline(quote.Code, quote.At));
        if (result.Triggered) results.Add(result);
    }
    return results;
}

static IReadOnlyList<string> RunOpeningCheckpointAcceptance(
    OpeningAuctionStateStore store,
    OpeningWeakToStrongDetector detector)
{
    var results = RunOpeningCheckpoints(store, detector)
        .ToDictionary(item => item.Time.ToLocalTime().ToString("HH:mm"), item => item, StringComparer.Ordinal);
    return new[] { "09:20", "09:25", "09:30", "09:35", "10:00" }
        .Select(time =>
        {
            results.TryGetValue(time, out var result);
            var stage = result?.Stage ?? "auctionConditionPassed";
            var passFail = stage is "noGap" or "trendWeak" ? "FAIL" : "PASS";
            return $"{time}:{passFail}:{stage}:{result?.VoiceEligible.ToString() ?? "False"}";
        })
        .ToArray();
}

static OpeningWeakToStrongQuote[] OpeningCheckpointQuotes(string tradingDate = "2026-06-03")
{
    return
    [
        OpeningCheckpointQuote(tradingDate, "09:20:00", 9.8m, 10m, 1_000_000m, 100_000m),
        OpeningCheckpointQuote(tradingDate, "09:24:00", 9.9m, 10m, 1_500_000m, 150_000m),
        OpeningCheckpointQuote(tradingDate, "09:25:00", 9.95m, 10m, 2_000_000m, 180_000m),
        OpeningCheckpointQuote(tradingDate, "09:30:00", 10.35m, 10m, 8_000_000m, 600_000m) with { Open = 10.35m },
        OpeningCheckpointQuote(tradingDate, "09:35:00", 10.65m, 10m, 16_000_000m, 1_200_000m) with { Open = 10.35m },
        OpeningCheckpointQuote(tradingDate, "10:00:00", 10.7m, 10m, 25_000_000m, 2_000_000m) with { Open = 10.35m },
    ];
}

static OpeningWeakToStrongQuote OpeningCheckpointQuote(
    string tradingDate,
    string time,
    decimal lastPrice,
    decimal preClose,
    decimal amount,
    decimal volume,
    string code = "002552",
    string name = "宝鼎科技")
{
    var timestamp = DateTimeOffset.Parse($"{tradingDate}T{time}+08:00");
    return new OpeningWeakToStrongQuote(
        code,
        name,
        timestamp,
        lastPrice,
        preClose,
        0m,
        amount,
        volume,
        11m,
        timestamp,
        timestamp,
        true,
        132,
        128,
        420,
        1,
        2);
}

static QuoteSnapshot[] OpeningCheckpointSnapshots(string tradingDate = "2026-06-03")
{
    return
    [
        OpeningSnapshot(tradingDate, "09:20:00", 9.8m, -2m, 10m, 1_000_000m, 100_000m),
        OpeningSnapshot(tradingDate, "09:24:00", 9.9m, -1m, 10m, 1_500_000m, 150_000m),
        OpeningSnapshot(tradingDate, "09:25:00", 9.95m, -0.5m, 10m, 2_000_000m, 180_000m),
        OpeningSnapshot(tradingDate, "09:30:00", 10.35m, 3.5m, 10m, 8_000_000m, 600_000m) with { Open = 10.35m },
        OpeningSnapshot(tradingDate, "09:35:00", 10.65m, 6.5m, 10m, 16_000_000m, 1_200_000m) with { Open = 10.35m },
        OpeningSnapshot(tradingDate, "10:00:00", 10.7m, 7m, 10m, 25_000_000m, 2_000_000m) with { Open = 10.35m },
    ];
}

static QuoteSnapshot OpeningSnapshot(
    string tradingDate,
    string time,
    decimal price,
    decimal changePct,
    decimal preClose,
    decimal amount,
    decimal volume)
{
    var timestamp = DateTimeOffset.Parse($"{tradingDate}T{time}+08:00");
    return Quote("002552", "宝鼎科技", price, changePct, preClose, time: timestamp, volume: volume, amount: amount) with
    {
        CapturedAt = timestamp,
        BridgeTs = timestamp,
        OpeningForcedSample = true,
        RequestedCount = 132,
        ReceivedCount = 128,
        ElapsedMs = 420,
        SlowBatches = 1,
        TruncatedBatches = 2,
    };
}

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

static OpeningWeakToStrongSignal TestOpeningSignal(DateTimeOffset timestamp)
{
    return new OpeningWeakToStrongSignal(
        timestamp.ToString("yyyy-MM-dd"),
        "002552",
        "宝鼎科技",
        "opening_weak_to_strong",
        "gapAlert",
        "gapAlert",
        true,
        "09:30较09:25明显改善，开盘承接转强",
        timestamp,
        37.48m,
        4.98m,
        timestamp,
        35.68m,
        1.02m,
        37.48m,
        4.98m,
        37.48m,
        4.98m,
        3.96m,
        50_000_000m,
        50_000_000m,
        DateTimeOffset.Parse("2026-05-22T09:20:05+08:00"),
        35.32m,
        0m,
        1_000_000m,
        DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"),
        35.68m,
        1.02m,
        5_000_000m,
        1.02m,
        4_000_000m,
        4m,
        true,
        "good",
        DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"),
        DateTimeOffset.Parse("2026-05-22T09:25:00+08:00"),
        timestamp,
        1,
        0,
        305_000,
        true,
        132,
        128,
        1800,
        2,
        1,
        "opening-weak-to-strong.v1",
        "owts-test");
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
