using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Newtonsoft.Json.Linq;
using THSBigOrder;
using THSBigOrder.Controls;
using THSBigOrder.DataSources;
using THSBigOrder.Models;
using THSBigOrder.Parsing;

internal static class LonghuFeatureTests
{
    internal static void TestAnnouncementTracker()
    {
        var tracker = new BigOrderAnnouncementTracker();
        var day = new DateTime(2026, 7, 17);
        var repeated = new BigOrderItem
        {
            Time = day.AddHours(9).AddMinutes(30),
            Type = 2,
            Volume = 100,
            Amount = 1000,
            Price = 10,
        };
        AssertEqual(0, tracker.Observe("002297", BigOrderDataSource.Ths, day, new[] { repeated, repeated }).Count,
            "first snapshot baseline");
        var added = tracker.Observe("002297", BigOrderDataSource.Ths, day.AddHours(12),
            new[] { repeated, repeated, repeated });
        AssertEqual(1, added.Count, "duplicate occurrence increment");
        AssertEqual(0, tracker.Observe("002297", BigOrderDataSource.Ths, day,
            new[] { repeated, repeated }).Count, "count decrease does not replay");
        AssertEqual(0, tracker.Observe("002297", BigOrderDataSource.Ths, day,
            new[] { repeated, repeated, repeated }).Count, "restored count does not replay");

        var later = new BigOrderItem
        {
            Time = day.AddHours(9).AddMinutes(31),
            Type = 4,
            Volume = 200,
            Amount = 2000,
            Price = 10,
        };
        var earlier = new BigOrderItem
        {
            Time = day.AddHours(9).AddMinutes(29),
            Type = 2,
            Volume = 300,
            Amount = 3000,
            Price = 10,
        };
        var ordered = tracker.Observe("002297", BigOrderDataSource.Ths, day,
            new[] { later, repeated, repeated, repeated, earlier });
        AssertEqual(2, ordered.Count, "two new rows");
        AssertTrue(ordered[0].Time < ordered[1].Time, "new rows sorted oldest first");
        AssertEqual(0, tracker.Observe("600519", BigOrderDataSource.Ths, day,
            new[] { later }).Count, "stock switch baseline");
    }

    internal static void TestVoiceBatch()
    {
        var queue = new RecordingSpeechQueue();
        using (var voice = new VoiceService(queue))
        {
            voice.AnnounceBatch(new[]
            {
                new BigOrderAnnouncement { Type = BigOrderAnnouncementType.Ignite, Amount = 5000000 },
                new BigOrderAnnouncement { Type = BigOrderAnnouncementType.Smash, Amount = 8000000 },
                new BigOrderAnnouncement { Type = BigOrderAnnouncementType.BuyActive },
            });
            voice.AnnounceBatch(new[]
            {
                new BigOrderAnnouncement { Type = BigOrderAnnouncementType.GoodSupport },
            });
            AssertEqual(2, queue.Texts.Count, "FIFO batches");
            AssertTrue(queue.Texts[0].Contains("点火 500万"), "ignite text");
            AssertTrue(queue.Texts[0].Contains("砸盘 800万"), "smash text");
            AssertTrue(queue.Texts[0].Contains("买活跃"), "buy active text");
            AssertEqual(0, queue.CancelCount, "ordinary batches do not cancel");
            voice.CancelPending();
            AssertEqual(1, queue.CancelCount, "explicit cancel");
        }
        AssertEqual(2, queue.CancelCount, "dispose cancels");
        AssertTrue(queue.Disposed, "dispose releases queue");
    }

    internal static async Task TestMainFormAnnouncementBatch()
    {
        var day = new DateTime(2026, 7, 17);
        var baseline = Signal(day.AddHours(9).AddMinutes(30), "点火", "");
        var added = new[]
        {
            Signal(day.AddHours(9).AddMinutes(31), "点火", ""),
            Signal(day.AddHours(9).AddMinutes(32), "砸盘", ""),
            Signal(day.AddHours(9).AddMinutes(33), "", "买活跃"),
        };
        var provider = new SequenceProvider(
            Snapshot(day, new[] { baseline }),
            Snapshot(day, new[] { baseline }.Concat(added).ToArray()));
        var voice = new RecordingVoice();
        using (var form = new MainForm(provider, false, voice))
        {
            await form.RefreshStockAsync("002297", true);
            AssertEqual(0, voice.Batches.Count, "first snapshot only establishes baseline");
            await form.RefreshStockAsync("002297", false);
            AssertEqual(1, voice.Batches.Count, "one voice batch");
            AssertEqual(3, voice.Batches[0].Count, "all new signals announced");
            AssertEqual(BigOrderAnnouncementType.Ignite, voice.Batches[0][0].Type, "first signal");
            AssertEqual(BigOrderAnnouncementType.Smash, voice.Batches[0][1].Type, "second signal");
            AssertEqual(BigOrderAnnouncementType.BuyActive, voice.Batches[0][2].Type, "third signal");
        }
    }

    internal static void TestParser()
    {
        var parser = new ThsPayloadParser();
        var compact = parser.ParseLonghuOrder(JArray.Parse(
            "['order-1','1784168251','2026-07-16 10:17:31','17.19','623','2','002297']"));
        AssertEqual(2, compact.Type, "compact type");
        AssertEqual(623d, compact.Volume, "compact volume");
        AssertNear(10709.37d, compact.Amount, 0.001d, "compact amount");
        AssertEqual(17.19d, compact.Price, "compact price");
        AssertEqual(new DateTime(2026, 7, 16, 10, 17, 31), compact.Time, "compact time");

        var upstream = parser.ParseLonghuOrder(JArray.Parse(
            "['2','1784168251','623','1070937','17.19','2026-07-16 10:17:31']"));
        AssertEqual(1070937d, upstream.Amount, "upstream money");

        var parsed = parser.ParseLonghuOrders(JArray.Parse(
            "[['order-1','1784168251','2026-07-16 10:17:31','17.19','623','2','002297'],['bad']]"));
        AssertEqual(1, parsed.Count, "invalid rows skipped");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse("['bad']")), "invalid row");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse(
                "['order-2','1784168251','2026-07-16 10:17:31','17.19','623','1.5','002297']")),
            "fractional tradetype");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse(
                "['order-3','0','2026-07-16 10:17:31','17.19','623','2','002297']")),
            "zero unix seconds");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse(
                "['order-4','1784168251','2026-07-16 10:17:31','0','623','2','002297']")),
            "zero price");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse(
                "['order-5','1784168251','2026-07-16 10:17:31','17.19','0','2','002297']")),
            "zero volume");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse(
                "['2','1784168251','623','-1','17.19','2026-07-16 10:17:31']")),
            "negative money");
    }

    private sealed class RecordingSpeechQueue : ISpeechQueue
    {
        public List<string> Texts { get; } = new List<string>();
        public int CancelCount { get; private set; }
        public bool Disposed { get; private set; }
        public void SpeakAsync(string text) { Texts.Add(text); }
        public void CancelAll() { CancelCount++; }
        public void Dispose() { Disposed = true; }
    }

    private static BigOrderItem Signal(DateTime time, string fund, string buy)
    {
        return new BigOrderItem
        {
            Time = time,
            Type = fund == "砸盘" ? 4 : 2,
            Volume = 500000,
            Amount = 5000000,
            Price = 10,
            FundMarker = fund,
            BuyMarker = buy,
        };
    }

    private static MarketSnapshot Snapshot(DateTime day, IReadOnlyList<BigOrderItem> orders)
    {
        return new MarketSnapshot(
            "002297",
            new StockSummary { Code = "002297", Name = "测试", Price = 10 },
            new MainFundSummary(),
            new LimitUpContext(),
            orders,
            new PricePoint[0],
            new MinuteTurnoverPoint[0],
            DataFreshness.Fresh,
            DataFreshness.Fresh,
            DataFreshness.Missing,
            DataFreshness.Missing,
            day,
            day,
            bigOrderSessionDate: day);
    }

    private sealed class SequenceProvider : IMarketSnapshotProvider
    {
        private readonly Queue<MarketSnapshot> _snapshots;
        public SequenceProvider(params MarketSnapshot[] snapshots)
        {
            _snapshots = new Queue<MarketSnapshot>(snapshots);
        }
        public Task<MarketSnapshot> LoadSnapshotAsync(
            string stockCode, CancellationToken cancellationToken)
        {
            return Task.FromResult(_snapshots.Dequeue());
        }
        public void CalculateMarkers(List<BigOrderItem> data) { }
    }

    private sealed class RecordingVoice : IBigOrderVoice
    {
        public bool Enabled { get; set; } = true;
        public List<IReadOnlyList<BigOrderAnnouncement>> Batches { get; } =
            new List<IReadOnlyList<BigOrderAnnouncement>>();
        public void AnnounceBatch(IReadOnlyList<BigOrderAnnouncement> announcements)
        {
            if (announcements.Count > 0) Batches.Add(announcements.ToArray());
        }
        public void CancelPending() { }
        public void Dispose() { }
    }

    internal static async Task TestDirectSuccess()
    {
        var handler = new LonghuHandler { DirectMode = LonghuMode.OneValid };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(1, snapshot.Orders.Count, "direct order count");
            AssertEqual(DataTransport.Direct, snapshot.Transports.BigOrder, "direct transport");
            AssertEqual(0, handler.ProxyCalls, "proxy not called");
            var form = handler.DirectForms.Single();
            AssertEqual("0", form["Order"], "direct Order");
            AssertEqual("GetMainMonitor_w30", form["a"], "direct operation");
            AssertEqual("200", form["st"], "direct page size");
            AssertEqual("StockYiDongKanPan", form["c"], "direct controller");
            AssertEqual("1", form["PhoneOSNew"], "direct PhoneOSNew");
            AssertEqual("5.17.0.4", form["VerSion"], "direct version");
            AssertEqual("002297", form["StockID"], "direct stock");
            AssertEqual("w36", form["apiv"], "direct api version");
            AssertEqual("0", form["IsBS"], "direct IsBS");
            AssertTrue(!form.ContainsKey("PageSize"), "legacy PageSize removed");
            AssertTrue(!form.ContainsKey("Type"), "legacy Type removed");
        }
    }

    internal static async Task TestDirectFailureProxyFallback()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.HttpFailure,
            ProxyMode = LonghuMode.OneValid,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(1, snapshot.Orders.Count, "proxy order count");
            AssertEqual(DataTransport.ProxyPrimary, snapshot.Transports.BigOrder, "proxy transport");
            AssertEqual(1, handler.ProxyCalls, "proxy called");
            AssertEqual(
                "/api/big-order/longhu/all-day?stockCode=002297&money=0",
                handler.ProxyUris.Single().PathAndQuery,
                "proxy contract");
        }
    }

    internal static async Task TestPagination()
    {
        var handler = new LonghuHandler { DirectMode = LonghuMode.Paginated201 };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(201, snapshot.Orders.Count, "all pages");
            AssertSequence(new[] { 0, 200 }, handler.DirectIndexes, "direct indexes");
            AssertEqual(1, handler.DeviceIds.Distinct().Count(), "DeviceID reused");
        }
    }

    internal static async Task TestMidPageFailure()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.FailAfterFirstFullPage,
            ProxyMode = LonghuMode.OneValid,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(1, snapshot.Orders.Count, "no partial direct rows");
            AssertEqual(DataTransport.ProxyPrimary, snapshot.Transports.BigOrder, "whole request falls back");
        }
    }

    internal static async Task TestProxyPagination()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.HttpFailure,
            ProxyMode = LonghuMode.Paginated201,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(201, snapshot.Orders.Count, "proxy full snapshot");
            AssertEqual(1, handler.ProxyCalls, "proxy aggregate called once");
        }
    }

    internal static async Task TestMissingTotalPageGuard()
    {
        var handler = new LonghuHandler { DirectMode = LonghuMode.FullPagesWithoutTotal };
        using (var http = new HttpClient(handler))
        {
            var client = new LonghuBigOrderSourceClient(
                http, "http://127.0.0.1:3000", new ThsPayloadParser());
            try
            {
                await client.LoadDirectAsync("002297", CancellationToken.None);
            }
            catch (PayloadParseException)
            {
                AssertEqual(1, handler.DirectIndexes.Count, "missing Total rejected immediately");
                return;
            }
        }
        throw new InvalidOperationException("missing Total full pages expected PayloadParseException");
    }

    internal static async Task TestTotalOverrun()
    {
        var handler = new LonghuHandler { DirectMode = LonghuMode.TotalOverrun };
        using (var http = new HttpClient(handler))
        {
            var client = new LonghuBigOrderSourceClient(
                http, "http://127.0.0.1:3000", new ThsPayloadParser());
            try
            {
                await client.LoadDirectAsync("002297", CancellationToken.None);
            }
            catch (PayloadParseException)
            {
                return;
            }
        }
        throw new InvalidOperationException("rows beyond Total expected PayloadParseException");
    }

    internal static async Task TestTruncatedResponse()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.Truncated,
            ProxyMode = LonghuMode.OneValid,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(1, snapshot.Orders.Count, "proxy rows after truncation");
            AssertEqual(DataTransport.ProxyPrimary, snapshot.Transports.BigOrder, "truncation fallback");
        }
    }

    internal static async Task TestValidEmptyList()
    {
        var handler = new LonghuHandler { DirectMode = LonghuMode.Empty };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(0, snapshot.Orders.Count, "empty rows");
            AssertEqual(DataTransport.Direct, snapshot.Transports.BigOrder, "empty direct transport");
            AssertEqual(0, handler.ProxyCalls, "empty does not fallback");
        }
    }

    internal static async Task TestAllInvalidFallback()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.AllInvalid,
            ProxyMode = LonghuMode.OneValid,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(1, snapshot.Orders.Count, "valid proxy row");
            AssertEqual(DataTransport.ProxyPrimary, snapshot.Transports.BigOrder, "invalid direct fallback");
        }
    }

    internal static async Task TestProviderRouting()
    {
        var sources = SourceSet.Create();
        using (var provider = sources.CreateProvider())
        {
            var ths = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(BigOrderDataSource.Ths, provider.DataSource, "default source");
            AssertEqual(2, ths.Orders.Single().Type, "THS order");
            AssertEqual(0, sources.Longhu.DirectCalls, "default skips Longhu");

            provider.DataSource = BigOrderDataSource.Longhu;
            var longhu = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(4, longhu.Orders.Single().Type, "Longhu order");
            AssertEqual(123d, longhu.MainFunds.MainBuy.Value, "THS summary retained");
            AssertEqual(1, longhu.Prices.Count, "THS prices retained");
            AssertEqual(DataTransport.Direct, longhu.Transports.BigOrder, "Longhu transport");

            sources.Ths.Direct = _ => Task.FromResult(SourceSet.BigResult(2, true, 456));
            await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            sources.Ths.Direct = _ => throw new HttpRequestException("THS direct failed");
            provider.DataSource = BigOrderDataSource.Ths;
            var staleThs = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(2, staleThs.Orders.Single().Type, "THS stale orders retained");
            AssertEqual(456d, staleThs.MainFunds.MainBuy.Value, "shared THS summary cache retained");
        }
    }

    internal static async Task TestProviderCacheIsolation()
    {
        var sources = SourceSet.Create();
        using (var provider = sources.CreateProvider())
        {
            await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            sources.Longhu.Direct = _ => throw new HttpRequestException("longhu direct failed");
            sources.Longhu.Proxy = _ => throw new HttpRequestException("longhu proxy failed");
            provider.DataSource = BigOrderDataSource.Longhu;
            var missingLonghu = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(0, missingLonghu.Orders.Count, "THS orders not reused for Longhu");
            AssertEqual(DataTransport.Failed, missingLonghu.Transports.BigOrder, "Longhu initially failed");

            sources.Longhu.Direct = _ => Task.FromResult(SourceSet.BigResult(4));
            var longhu = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(4, longhu.Orders.Single().Type, "Longhu cached");
            sources.Longhu.Direct = _ => throw new HttpRequestException("longhu direct failed");
            var staleLonghu = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(4, staleLonghu.Orders.Single().Type, "Longhu stale reused");
            AssertEqual(DataTransport.Stale, staleLonghu.Transports.BigOrder, "Longhu stale transport");
        }
    }

    internal static async Task TestMainFormDataSourceSwitch()
    {
        var sources = SourceSet.Create();
        using (var provider = sources.CreateProvider())
        using (var form = new MainForm(provider, false))
        {
            var combo = (ComboBox)typeof(MainForm)
                .GetField("cboDataSource", BindingFlags.Instance | BindingFlags.NonPublic)
                ?.GetValue(form);
            AssertTrue(combo != null, "ComboBox exists");
            AssertSequence(new[] { "龙虎大单", "THS大单" },
                combo.Items.Cast<object>().Select(value => value.ToString()), "options");
            AssertEqual(1, combo.SelectedIndex, "THS default selection");
            AssertEqual(BigOrderDataSource.Ths, provider.DataSource, "THS default provider");

            await form.RefreshStockAsync("002963", true);
            var ordersField = typeof(MainForm)
                .GetField("_allData", BindingFlags.Instance | BindingFlags.NonPublic);
            var grid = (DataGridView)typeof(MainForm)
                .GetField("dataGridView1", BindingFlags.Instance | BindingFlags.NonPublic)
                ?.GetValue(form);
            var chart = (BigOrderChartControl)typeof(MainForm)
                .GetField("bigOrderChart", BindingFlags.Instance | BindingFlags.NonPublic)
                ?.GetValue(form);
            AssertEqual(2, ((List<BigOrderItem>)ordersField.GetValue(form)).Single().Type,
                "initial THS list");
            AssertEqual(1, form.VisibleChartOrderEvents.Count, "initial THS point");
            AssertEqual(1, grid.Rows.Count, "initial THS grid");
            AssertEqual(1, chart.BigOrderLinePercents.Count, "initial THS blue line");
            AssertEqual(2, chart.MinutePriceLinePercents.Count, "initial white line");
            AssertEqual(2, chart.MarketLinePercents.Count, "initial yellow line");

            var pendingLonghu =
                new TaskCompletionSource<SourceLoadResult<BigOrderSourceData>>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
            sources.Longhu.Direct = _ => pendingLonghu.Task;
            combo.SelectedIndex = 0;
            await WaitUntil(() => sources.Longhu.DirectCalls > 0, "Longhu refresh");
            AssertEqual(BigOrderDataSource.Longhu, provider.DataSource, "provider switched");
            AssertEqual(0, ((List<BigOrderItem>)ordersField.GetValue(form)).Count,
                "old source list cleared while loading");
            AssertEqual(0, form.VisibleChartOrderEvents.Count,
                "old source points cleared while loading");
            AssertEqual(0, grid.Rows.Count, "old source grid cleared while loading");
            AssertEqual(0, chart.BigOrderLinePercents.Count,
                "old source blue line cleared while loading");
            AssertEqual(2, chart.MinutePriceLinePercents.Count,
                "white line retained while loading");
            AssertEqual(2, chart.MarketLinePercents.Count,
                "yellow line retained while loading");

            pendingLonghu.SetResult(SourceSet.BigResult(4));
            WaitUntilWithMessages(
                () => ((List<BigOrderItem>)ordersField.GetValue(form))
                    .Any(order => order.Type == 4),
                "Longhu list rebound");
            AssertEqual(4, ((List<BigOrderItem>)ordersField.GetValue(form)).Single().Type,
                "Longhu list rebound");
            AssertEqual(4, form.VisibleChartOrderEvents.Single().Type,
                "Longhu point rebound");
            AssertEqual(1, grid.Rows.Count, "Longhu grid rebound");
            AssertEqual("002963", form.BoundStockCode, "full refresh bound current code");
        }
    }

    internal static async Task TestMainFormDataSourceSwitchRace()
    {
        var sources = SourceSet.Create();
        using (var provider = sources.CreateProvider())
        using (var form = new MainForm(provider, false))
        {
            await form.RefreshStockAsync("002963", true);
            var ordersField = typeof(MainForm)
                .GetField("_allData", BindingFlags.Instance | BindingFlags.NonPublic);
            var combo = (ComboBox)typeof(MainForm)
                .GetField("cboDataSource", BindingFlags.Instance | BindingFlags.NonPublic)
                ?.GetValue(form);

            var pendingLonghu =
                new TaskCompletionSource<SourceLoadResult<BigOrderSourceData>>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
            sources.Longhu.Direct = _ => pendingLonghu.Task;
            combo.SelectedIndex = 0;
            await WaitUntil(() => sources.Longhu.DirectCalls > 0, "first Longhu request");

            var pendingThs =
                new TaskCompletionSource<SourceLoadResult<BigOrderSourceData>>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
            var previousThsCalls = sources.Ths.DirectCalls;
            sources.Ths.Direct = _ => pendingThs.Task;
            combo.SelectedIndex = 1;
            await WaitUntil(
                () => sources.Ths.DirectCalls > previousThsCalls,
                "latest THS request");

            pendingThs.SetResult(SourceSet.BigResult(2, true));
            WaitUntilWithMessages(
                () => ((List<BigOrderItem>)ordersField.GetValue(form))
                    .Any(order => order.Type == 2),
                "latest THS result");

            pendingLonghu.SetResult(SourceSet.BigResult(4));
            for (var attempt = 0; attempt < 20; attempt++)
            {
                Application.DoEvents();
                Thread.Sleep(10);
            }
            AssertEqual(2, ((List<BigOrderItem>)ordersField.GetValue(form)).Single().Type,
                "late Longhu result ignored");
            AssertEqual(BigOrderDataSource.Ths, provider.DataSource,
                "latest selected source retained");
        }
    }

    private static THSBigOrderDataProvider CreateHttpProvider(LonghuHandler handler)
    {
        var http = new HttpClient(handler);
        var parser = new ThsPayloadParser();
        return new THSBigOrderDataProvider(
            new ThsBigOrderSourceClient(http, "http://127.0.0.1:3000", parser),
            new LonghuBigOrderSourceClient(http, "http://127.0.0.1:3000", parser),
            new FixedSource<StockSummary>(new StockSummary { Code = "002297", Name = "测试", Price = 10 }),
            new FixedSource<IReadOnlyList<MinuteTurnoverPoint>>(new MinuteTurnoverPoint[0]),
            new FixedSource<LimitUpSourceData>(new LimitUpSourceData()));
    }

    private enum LonghuMode
    {
        OneValid,
        Paginated201,
        FullPagesWithoutTotal,
        TotalOverrun,
        FailAfterFirstFullPage,
        Truncated,
        Empty,
        AllInvalid,
        HttpFailure,
    }

    private sealed class LonghuHandler : HttpMessageHandler
    {
        public LonghuMode DirectMode { get; set; } = LonghuMode.OneValid;
        public LonghuMode ProxyMode { get; set; } = LonghuMode.OneValid;
        public int ProxyCalls { get; private set; }
        public List<int> DirectIndexes { get; } = new List<int>();
        public List<int> ProxyIndexes { get; } = new List<int>();
        public List<string> DeviceIds { get; } = new List<string>();
        public List<Dictionary<string, string>> DirectForms { get; } =
            new List<Dictionary<string, string>>();
        public List<Uri> ProxyUris { get; } = new List<Uri>();

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var direct = request.RequestUri.Host == "apphwhq.longhuvip.com";
            var proxy = request.RequestUri.AbsolutePath == "/api/big-order/longhu/all-day";
            if (!direct && !proxy)
            {
                var thsJson = request.RequestUri.Host == "vaserviece.10jqka.com.cn"
                    ? "{'errorcode':0,'title':{'stockname':'测试','price':10,'mainbuy':'1万','mainsell':'0万'},'list':[],'pricechange':[]}"
                    : "{'ok':true,'data':{'title':{'stockname':'测试','price':10,'mainbuy':'1万','mainsell':'0万'},'list':[],'pricechange':[]}}";
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(thsJson, Encoding.UTF8, "application/json"),
                };
            }
            var values = direct
                ? ParsePairs(await request.Content.ReadAsStringAsync())
                : ParsePairs(request.RequestUri.Query.TrimStart('?'));
            var index = direct ? int.Parse(values["Index"]) : 0;
            var mode = direct ? DirectMode : ProxyMode;
            if (direct)
            {
                DirectIndexes.Add(index);
                DeviceIds.Add(values["DeviceID"]);
                DirectForms.Add(values);
            }
            else
            {
                ProxyCalls++;
                ProxyIndexes.Add(index);
                ProxyUris.Add(request.RequestUri);
            }

            if (mode == LonghuMode.HttpFailure ||
                mode == LonghuMode.FailAfterFirstFullPage && index >= 200)
            {
                return new HttpResponseMessage(HttpStatusCode.BadGateway)
                {
                    Content = new StringContent("upstream failed"),
                };
            }

            var rows = new JArray();
            var total = 1;
            if (mode == LonghuMode.Paginated201)
            {
                total = 201;
                AddRows(rows, proxy ? 201 : index == 0 ? 200 : 1);
            }
            else if (mode == LonghuMode.FullPagesWithoutTotal)
            {
                AddRows(rows, 200);
            }
            else if (mode == LonghuMode.TotalOverrun)
            {
                total = 1;
                AddRows(rows, 2);
            }
            else if (mode == LonghuMode.FailAfterFirstFullPage)
            {
                total = 201;
                AddRows(rows, 200);
            }
            else if (mode == LonghuMode.Truncated)
            {
                total = 201;
                AddRows(rows, 1);
            }
            else if (mode == LonghuMode.Empty)
            {
                total = 0;
            }
            else if (mode == LonghuMode.AllInvalid)
            {
                rows.Add(new JArray("bad"));
            }
            else
            {
                AddRows(rows, 1);
            }

            var payload = new JObject
            {
                ["List"] = rows,
                ["errcode"] = "0",
            };
            if (mode != LonghuMode.FullPagesWithoutTotal) payload["Total"] = total;
            if (proxy)
            {
                payload = new JObject
                {
                    ["ok"] = true,
                    ["sessionDate"] = "2026-07-16",
                    ["fetchedAt"] = 1784168251000,
                    ["data"] = new JObject
                    {
                        ["List"] = rows,
                        ["Total"] = total,
                        ["errcode"] = "0",
                        ["dragonMeta"] = new JObject
                        {
                            ["cache"] = new JObject { ["uiStale"] = false },
                        },
                    },
                };
            }
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(payload.ToString(), Encoding.UTF8, "application/json"),
            };
        }

        private static void AddRows(JArray rows, int count)
        {
            for (var index = 0; index < count; index++)
            {
                rows.Add(new JArray(
                    "order-" + index, "1784168251", "2026-07-16 10:17:31",
                    "17.19", "623", "2", "002297"));
            }
        }
    }

    private sealed class SourceSet
    {
        public StubSource<BigOrderSourceData> Ths { get; private set; }
        public StubSource<BigOrderSourceData> Longhu { get; private set; }
        public StubSource<StockSummary> Quote { get; private set; }
        public StubSource<IReadOnlyList<MinuteTurnoverPoint>> Minute { get; private set; }
        public StubSource<LimitUpSourceData> Limit { get; private set; }

        public static SourceSet Create()
        {
            return new SourceSet
            {
                Ths = new StubSource<BigOrderSourceData> { Direct = _ => Task.FromResult(BigResult(2, true)) },
                Longhu = new StubSource<BigOrderSourceData> { Direct = _ => Task.FromResult(BigResult(4)) },
                Quote = new StubSource<StockSummary>
                {
                    Direct = _ => Task.FromResult(Result(new StockSummary
                    {
                        Code = "002297", Name = "测试", Price = 10, ChangePercent = 0,
                    })),
                },
                Minute = new StubSource<IReadOnlyList<MinuteTurnoverPoint>>
                {
                    Direct = _ => Task.FromResult(Result<IReadOnlyList<MinuteTurnoverPoint>>(
                        new[]
                        {
                            new MinuteTurnoverPoint
                            {
                                Time = new DateTime(2026, 7, 16, 9, 30, 0),
                                Price = 10,
                                CumulativeVolume = 100,
                                CumulativeAmount = 100000,
                            },
                            new MinuteTurnoverPoint
                            {
                                Time = new DateTime(2026, 7, 16, 9, 31, 0),
                                Price = 10.1,
                                CumulativeVolume = 200,
                                CumulativeAmount = 202000,
                            },
                        })),
                },
                Limit = new StubSource<LimitUpSourceData>
                {
                    Direct = _ => Task.FromResult(Result(new LimitUpSourceData())),
                },
            };
        }

        public THSBigOrderDataProvider CreateProvider()
        {
            return new THSBigOrderDataProvider(Ths, Longhu, Quote, Minute, Limit);
        }

        public static SourceLoadResult<BigOrderSourceData> BigResult(
            int type, bool summary = false, double mainBuy = 123)
        {
            return Result(new BigOrderSourceData
            {
                StockFallback = new StockSummary { Code = "002297", Name = "摘要", Price = 10 },
                MainFunds = summary
                    ? new MainFundSummary
                    {
                        MainBuy = mainBuy,
                        MainSell = 23,
                        NetAmount = mainBuy - 23,
                    }
                    : new MainFundSummary(),
                Orders = new[]
                {
                    new BigOrderItem
                    {
                        Type = type, Price = 10, Volume = 500000, Amount = 5000000,
                        Time = new DateTime(2026, 7, 16, 10, 0, 0),
                    },
                },
                Prices = summary
                    ? new[] { new PricePoint { Time = new DateTime(2026, 7, 16, 10, 0, 0), ChangePercent = 1 } }
                    : new PricePoint[0],
            });
        }
    }

    private sealed class FixedSource<T> : IMarketSourceClient<T>
    {
        private readonly T _data;
        public FixedSource(T data) { _data = data; }
        public Task<SourceLoadResult<T>> LoadDirectAsync(string stockCode, CancellationToken cancellationToken)
        {
            return Task.FromResult(Result(_data));
        }
        public Task<SourceLoadResult<T>> LoadProxyAsync(string stockCode, CancellationToken cancellationToken)
        {
            throw new InvalidOperationException("unexpected proxy call");
        }
    }

    private sealed class StubSource<T> : IMarketSourceClient<T>
    {
        public Func<CancellationToken, Task<SourceLoadResult<T>>> Direct { get; set; }
        public Func<CancellationToken, Task<SourceLoadResult<T>>> Proxy { get; set; }
        public int DirectCalls { get; private set; }

        public Task<SourceLoadResult<T>> LoadDirectAsync(string stockCode, CancellationToken cancellationToken)
        {
            DirectCalls++;
            return Direct(cancellationToken);
        }

        public Task<SourceLoadResult<T>> LoadProxyAsync(string stockCode, CancellationToken cancellationToken)
        {
            if (Proxy == null) throw new InvalidOperationException("unexpected proxy call");
            return Proxy(cancellationToken);
        }
    }

    private static SourceLoadResult<T> Result<T>(T data)
    {
        return new SourceLoadResult<T>
        {
            Data = data,
            Freshness = DataFreshness.Fresh,
            Transport = DataTransport.Direct,
            FetchedAt = DateTime.Now,
        };
    }

    private static Dictionary<string, string> ParsePairs(string value)
    {
        return value.Split(new[] { '&' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(part => part.Split(new[] { '=' }, 2))
            .ToDictionary(
                pair => Uri.UnescapeDataString(pair[0]),
                pair => pair.Length == 1 ? "" : Uri.UnescapeDataString(pair[1]));
    }

    private static async Task WaitUntil(Func<bool> condition, string label)
    {
        for (var attempt = 0; attempt < 80; attempt++)
        {
            if (condition()) return;
            await Task.Delay(25);
        }
        throw new InvalidOperationException(label + " timed out");
    }

    private static void WaitUntilWithMessages(Func<bool> condition, string label)
    {
        for (var attempt = 0; attempt < 80; attempt++)
        {
            Application.DoEvents();
            if (condition()) return;
            Thread.Sleep(25);
        }
        throw new InvalidOperationException(label + " timed out");
    }

    private static void AssertEqual<T>(T expected, T actual, string label)
    {
        if (!Equals(expected, actual))
            throw new InvalidOperationException(label + " expected " + expected + ", actual " + actual);
    }

    private static void AssertNear(double expected, double actual, double tolerance, string label)
    {
        if (Math.Abs(expected - actual) > tolerance)
            throw new InvalidOperationException(label + " expected " + expected + ", actual " + actual);
    }

    private static void AssertTrue(bool value, string label)
    {
        if (!value) throw new InvalidOperationException(label);
    }

    private static void AssertSequence<T>(IEnumerable<T> expected, IEnumerable<T> actual, string label)
    {
        if (!expected.SequenceEqual(actual))
            throw new InvalidOperationException(label + " sequence mismatch");
    }

    private static void AssertThrows<T>(Action action, string label) where T : Exception
    {
        try { action(); }
        catch (T) { return; }
        throw new InvalidOperationException(label + " expected " + typeof(T).Name);
    }
}
