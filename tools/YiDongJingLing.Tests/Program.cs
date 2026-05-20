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
            { "code": "600000", "name": "浦发银行", "lastPrice": 10.5, "changePct": 5, "volume": 1000, "amount": 1050000, "preClose": 10 }
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
    public string LastRequestPath { get; private set; } = "";
    public string LastRequestBody { get; private set; } = "";

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        LastRequestPath = request.RequestUri?.AbsolutePath ?? "";
        LastRequestBody = request.Content?.ReadAsStringAsync(cancellationToken).GetAwaiter().GetResult() ?? "";
        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent("""{"ok":true,"queued":1,"sent":0,"skipped":0}""", Encoding.UTF8, "application/json"),
        });
    }
}
