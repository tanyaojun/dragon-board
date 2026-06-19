using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Newtonsoft.Json.Linq;
using THSBigOrder;
using THSBigOrder.Models;
using THSBigOrder.Parsing;
using THSBigOrder.Analytics;
using THSBigOrder.Controls;
using THSBigOrder.Filtering;
using THSBigOrder.Refresh;

internal static class Program
{
    [STAThread]
    private static int Main()
    {
        Run("Assembly and provider use THSBigOrder names", () =>
        {
            AssertEqual("THSBigOrder", typeof(THSBigOrderDataProvider).Assembly.GetName().Name, "assembly");
            AssertEqual("THSBigOrder", typeof(THSBigOrderDataProvider).Namespace, "namespace");
        });
        Run("THS order parser maps four natures and formatted values", TestOrderParsing);
        Run("THS snapshot parser merges title, quote, limit-up and price points", TestSnapshotParsing);
        Run("Proxy envelope maps degraded, stale and fresh empty states", TestEnvelopeStates);
        Run("Provider loads three proxy routes in parallel", () => TestProviderParallelLoad().GetAwaiter().GetResult());
        Run("Provider stale fallback is isolated by stock code", () => TestProviderStaleIsolation().GetAwaiter().GetResult());
        Run("Provider preserves optional degraded and stale states", () => TestProviderOptionalStates().GetAwaiter().GetResult());
        Run("Series builder aggregates minute flow and thresholds", TestSeriesBuilder);
        Run("Legacy marker thresholds remain stable", TestLegacyMarkers);
        Run("Chart control binds three layout bands and draws empty data", TestChartControl);
        Run("Order filter composes amount, side and marker", TestOrderFilter);
        Run("Refresh coordinator cancels superseded code and blocks reentry", TestRefreshCoordinator);
        Run("Main form exposes 72/28 chart and order tabs", TestMainFormLayout);
        Run("Main form ignores superseded refresh completion", () => TestMainFormRefreshRace().GetAwaiter().GetResult());
        return Environment.ExitCode;
    }

    private static void TestOrderParsing()
    {
        var parser = new ThsPayloadParser();
        var item = parser.ParseOrder(JObject.Parse(@"{
          'nature':'主力主买','volume':'5,000手','avgprice':'1,215.00',
          'money':'60750万','otime':'2026-06-18 11:29:50'
        }"));
        AssertEqual(2, item.Type, "active buy type");
        AssertEqual(5000d, item.Volume, "volume");
        AssertEqual(1215d, item.Price, "price");
        AssertEqual(new DateTime(2026, 6, 18, 11, 29, 50), item.Time, "time");
        AssertEqual(3, parser.ParseOrder(JObject.Parse("{'nature':'主力被买','volume':'1手','avgprice':'1','money':1,'ctime':'09:30:01'}")).Type, "passive buy");
        AssertEqual(4, parser.ParseOrder(JObject.Parse("{'nature':'主力主卖','volume':'1手','avgprice':'1','money':1,'ctime':'09:30:01'}")).Type, "active sell");
        AssertEqual(1, parser.ParseOrder(JObject.Parse("{'nature':'主力被卖','volume':'1手','avgprice':'1','money':1,'ctime':'09:30:01'}")).Type, "passive sell");
        AssertThrows<PayloadParseException>(() => parser.ParseOrder(JObject.Parse("{'nature':'未知','volume':'1手','avgprice':'1','money':1,'ctime':'09:30:01'}")), "unknown nature");
    }

    private static void TestSnapshotParsing()
    {
        var parser = new ThsPayloadParser();
        var ths = JObject.Parse(@"{
          'ok':true,'fetchedAt':1781746200000,'data':{
            'title':{'stockcode':'002297','stockname':'博云新材','price':'28.36','mainbuy':'5.24亿','mainsell':'7.09亿'},
            'list':[{'nature':'主力主买','volume':'566手','avgprice':'28.36','money':800000,'otime':'2026-06-18 13:13:12'}],
            'pricechange':[{'1':'202606180930','2525646':0.5485}],
            'dragonMeta':{'cache':{'stale':false}}
          }
        }");
        var quote = JObject.Parse(@"{'data':{'diff':[{'f12':'002297','f14':'博云新材','f2':28.36,'f3':10.02,'f5':3342254360,'f6':1178510,'f8':'20.56%','f10':0.82}]}}" );
        var limitUp = JObject.Parse(@"{'data':{'info':[{'code':'002297','order_amount':45049860,'order_volume':1588500,'open_num':20,'high_days':'首板','limit_up_suc_rate':0.5882,'reason_type':'军工'}]}}" );

        var snapshot = parser.ParseSnapshot("002297", ths, quote, limitUp, DateTime.Parse("2026-06-18 13:15:00"));
        AssertEqual("博云新材", snapshot.Stock.Name, "name");
        AssertEqual(28.36d, snapshot.Stock.Price.Value, "price");
        AssertEqual(20.56d, snapshot.Stock.TurnoverRate.Value, "turnover");
        AssertEqual(0.82d, snapshot.Stock.VolumeRatio.Value, "volume ratio");
        AssertEqual(3342254360d, snapshot.Stock.TotalAmount.Value, "amount");
        AssertEqual(45049860d, snapshot.LimitUp.SealAmount.Value, "seal amount");
        AssertEqual("首板", snapshot.LimitUp.HighDays, "high days");
        AssertEqual(524000000d, snapshot.MainFunds.MainBuy.Value, "main buy");
        AssertEqual(709000000d, snapshot.MainFunds.MainSell.Value, "main sell");
        AssertEqual(-185000000d, snapshot.MainFunds.NetAmount.Value, "main net");
        AssertEqual(snapshot.Orders.Count, snapshot.MainFunds.OrderCount, "order count");
        AssertEqual(new DateTime(2026, 6, 18, 9, 30, 0), snapshot.Prices[0].Time, "price point time");
        AssertEqual(0.5485d, snapshot.Prices[0].ChangePercent, "price point pct");

        var invalidQuote = JObject.Parse("{'data':{'diff':[{'f12':'002297','f5':'-','f6':'NaN','f8':'Infinity','f10':'-'}]}}");
        var invalid = parser.ParseSnapshot("002297", ths, invalidQuote, new JObject(), DateTime.Now);
        AssertEqual<double?>(null, invalid.Stock.TotalAmount, "invalid amount");
        AssertEqual<double?>(null, invalid.Stock.Volume, "invalid volume");
        AssertEqual<double?>(null, invalid.Stock.TurnoverRate, "invalid turnover");
        AssertEqual<double?>(null, invalid.Stock.VolumeRatio, "invalid ratio");
    }

    private static void TestEnvelopeStates()
    {
        var parser = new ThsPayloadParser();
        var degraded = JObject.Parse("{'ok':false,'degraded':true,'errorCode':'upstream_unavailable','data':null}");
        var failed = parser.ParseSnapshot("002297", degraded, new JObject(), new JObject(), DateTime.Now);
        AssertEqual(DataFreshness.Failed, failed.BigOrderFreshness, "degraded freshness");

        var stale = JObject.Parse("{'ok':true,'fetchedAt':1781746200000,'data':{'title':{},'list':[],'pricechange':[],'dragonMeta':{'cache':{'stale':true}}}}");
        var cached = parser.ParseSnapshot("002297", stale, new JObject(), new JObject(), DateTime.Now);
        AssertEqual(DataFreshness.Stale, cached.BigOrderFreshness, "stale freshness");
        AssertEqual(DateTimeOffset.FromUnixTimeMilliseconds(1781746200000).LocalDateTime, cached.BigOrderFetchedAt, "fetched time");

        var fresh = JObject.Parse("{'ok':true,'fetchedAt':1781746200000,'data':{'title':{},'list':[],'pricechange':[]}}");
        AssertEqual(DataFreshness.Fresh, parser.ParseSnapshot("002297", fresh, new JObject(), new JObject(), DateTime.Now).BigOrderFreshness, "fresh empty");
    }

    private static async Task TestProviderParallelLoad()
    {
        var handler = new FixtureHandler(true);
        using (var provider = new THSBigOrderDataProvider(new HttpClient(handler), "http://127.0.0.1:3000"))
        {
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertSequence(new[] {
                "/api/big-order/ths-detail?stockCode=002297",
                "/api/limitup/10jqka",
                "/api/quotes/tencent?codes=002297"
            }, handler.Paths.OrderBy(value => value).ToArray(), "paths");
            AssertEqual(3, handler.PeakPending, "parallel requests");
            AssertEqual("002297", snapshot.StockCode, "stock code");
            AssertEqual("博云新材", snapshot.Stock.Name, "provider name");
        }
    }

    private static async Task TestProviderStaleIsolation()
    {
        var handler = new FixtureHandler(false);
        using (var provider = new THSBigOrderDataProvider(new HttpClient(handler), "http://127.0.0.1:3000"))
        {
            var fresh = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            handler.QuotePrice = 30;
            handler.FailBigOrder = true;
            var stale = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            var other = await provider.LoadSnapshotAsync("600519", CancellationToken.None);

            AssertEqual(DataFreshness.Fresh, fresh.BigOrderFreshness, "initial fresh");
            AssertEqual(DataFreshness.Stale, stale.BigOrderFreshness, "same-code stale");
            AssertEqual("002297", stale.StockCode, "stale code");
            AssertTrue(stale.Orders.Count > 0, "stale orders retained");
            AssertEqual(30d, stale.Stock.Price.Value, "stale refresh keeps current quote");
            AssertEqual(DataFreshness.Failed, other.BigOrderFreshness, "other failed");
            AssertTrue(other.Orders.Count == 0, "no cross-code stale orders");
        }
    }

    private static async Task TestProviderOptionalStates()
    {
        var handler = new FixtureHandler(false) { QuoteDegraded = true, LimitStale = true };
        using (var provider = new THSBigOrderDataProvider(new HttpClient(handler), "http://127.0.0.1:3000"))
        {
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(DataFreshness.Failed, snapshot.QuoteFreshness, "quote degraded");
            AssertEqual(DataFreshness.Stale, snapshot.LimitUpFreshness, "limit stale");
        }
    }

    private static void TestSeriesBuilder()
    {
        var day = new DateTime(2026, 6, 18);
        var orders = new[]
        {
            new BigOrderItem { Type = 2, Amount = 1000000, Time = day.AddHours(9).AddMinutes(30) },
            new BigOrderItem { Type = 3, Amount = 500000, Time = day.AddHours(9).AddMinutes(30).AddSeconds(10) },
            new BigOrderItem { Type = 4, Amount = 300000, Time = day.AddHours(9).AddMinutes(30).AddSeconds(20) },
            new BigOrderItem { Type = 1, Amount = 200000, Time = day.AddHours(9).AddMinutes(31) },
        };
        var series = new BigOrderSeriesBuilder().Build(orders);
        AssertEqual(1500000d, series.Minutes[0].BuyAmount, "09:30 buy");
        AssertEqual(300000d, series.Minutes[0].SellAmount, "09:30 sell");
        AssertEqual(1200000d, series.NetFlow[0].Value, "09:30 net");
        AssertEqual(1000000d, series.Thresholds.Single(value => value.Amount == 1000000).BuyAmount, "100w buy");
    }

    private static void TestLegacyMarkers()
    {
        var day = new DateTime(2026, 6, 18, 9, 30, 0);
        var ignite = new List<BigOrderItem>
        {
            new BigOrderItem { Type = 2, Amount = 100000, Time = day },
            new BigOrderItem { Type = 2, Amount = 4000000, Time = day.AddSeconds(10) },
        };
        var smash = new List<BigOrderItem>
        {
            new BigOrderItem { Type = 4, Amount = 100000, Time = day },
            new BigOrderItem { Type = 4, Amount = 4000000, Time = day.AddSeconds(10) },
        };
        using (var provider = new THSBigOrderDataProvider())
        {
            provider.CalculateMarkers(ignite);
            provider.CalculateMarkers(smash);
        }
        AssertEqual("点火", ignite[1].FundMarker, "ignite marker");
        AssertEqual("砸盘", smash[1].FundMarker, "smash marker");
    }

    private static void TestChartControl()
    {
        using (var control = new BigOrderChartControl())
        {
            control.Size = new Size(1000, 650);
            control.SetSnapshot(null, new BigOrderSeriesBuilder().Build(new BigOrderItem[0]));
            AssertEqual(3, control.LayoutBands.Count, "price/volume/heat bands");
            using (var bitmap = new Bitmap(1000, 650))
                control.DrawToBitmap(bitmap, control.ClientRectangle);
        }
    }

    private static void TestOrderFilter()
    {
        var rows = new[]
        {
            new BigOrderItem { Type = 2, Amount = 3000000, FundMarker = "点火" },
            new BigOrderItem { Type = 4, Amount = 4000000, FundMarker = "砸盘" },
            new BigOrderItem { Type = 3, Amount = 200000, FundMarker = "点火" },
        };
        var result = OrderFilter.Apply(rows, 1000000, OrderSide.Buy, "点火");
        AssertEqual(1, result.Count, "composed filter count");
        AssertEqual(2, result[0].Type, "composed filter type");
    }

    private static void TestRefreshCoordinator()
    {
        using (var coordinator = new RefreshCoordinator())
        {
            var first = coordinator.Begin("002297", false);
            var duplicate = coordinator.Begin("002297", false);
            var changed = coordinator.Begin("600519", true);
            AssertTrue(first.ShouldRun, "first refresh runs");
            AssertTrue(!duplicate.ShouldRun, "same code does not reenter");
            AssertTrue(first.CancellationToken.IsCancellationRequested, "old code cancelled");
            AssertTrue(coordinator.IsLatest(changed.Generation, "600519"), "latest generation");
        }
    }

    private static void TestMainFormLayout()
    {
        using (var form = new MainForm(null, false))
        {
            form.ClientSize = new Size(1280, 800);
            AssertEqual(Orientation.Vertical, form.MainSplit.Orientation, "split orientation");
            AssertTrue(form.MainSplit.SplitterDistance >= form.ClientSize.Width * 0.65, "left chart share");
            AssertEqual("全部", form.OrderTabs.TabPages[0].Text, "all tab");
            AssertEqual("买盘", form.OrderTabs.TabPages[1].Text, "buy tab");
            AssertEqual("卖盘", form.OrderTabs.TabPages[2].Text, "sell tab");
            form.ClientSize = new Size(1080, 800);
            AssertTrue(!form.ShowsLimitUpReason && form.ShowsSealRate, "1080 responsive band");
            form.ClientSize = new Size(980, 800);
            AssertTrue(!form.ShowsSealRate && !form.ShowsLastLimitTime, "980 responsive band");
            form.ClientSize = new Size(1280, 800);
            AssertTrue(form.ShowsLimitUpReason && form.ShowsSealRate && form.ShowsLastLimitTime, "responsive recovery");
        }
    }

    private static async Task TestMainFormRefreshRace()
    {
        var provider = new ControlledProvider();
        using (var form = new MainForm(provider, false))
        {
            var oldRequest = form.RefreshStockAsync("002297", true);
            var latestRequest = form.RefreshStockAsync("600519", true);
            provider.Complete("600519");
            await latestRequest;
            provider.Complete("002297");
            await oldRequest;
            AssertEqual("600519", form.BoundStockCode, "latest stock remains bound");
        }
    }

    private static void Run(string name, Action test)
    {
        try
        {
            test();
            Console.WriteLine("PASS " + name);
        }
        catch (Exception error)
        {
            Environment.ExitCode = 1;
            Console.Error.WriteLine("FAIL " + name + ": " + error.Message);
        }
    }

    private static void AssertEqual<T>(T expected, T actual, string label)
    {
        if (!Equals(expected, actual))
        {
            throw new InvalidOperationException(label + " expected " + expected + ", actual " + actual);
        }
    }

    private static void AssertThrows<T>(Action action, string label) where T : Exception
    {
        try
        {
            action();
        }
        catch (T)
        {
            return;
        }
        throw new InvalidOperationException(label + " expected " + typeof(T).Name);
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

    private sealed class FixtureHandler : HttpMessageHandler
    {
        private readonly bool _barrier;
        private readonly TaskCompletionSource<bool> _release = new TaskCompletionSource<bool>();
        private int _pending;

        public FixtureHandler(bool barrier) { _barrier = barrier; }
        public List<string> Paths { get; } = new List<string>();
        public bool FailBigOrder { get; set; }
        public bool QuoteDegraded { get; set; }
        public bool LimitStale { get; set; }
        public double QuotePrice { get; set; } = 28.36;
        public int PeakPending { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var path = request.RequestUri.PathAndQuery;
            lock (Paths)
            {
                Paths.Add(path);
                _pending++;
                PeakPending = Math.Max(PeakPending, _pending);
                if (_pending >= 3) _release.TrySetResult(true);
            }
            if (_barrier) await _release.Task;
            lock (Paths) { _pending--; }

            if (path.StartsWith("/api/big-order/") && FailBigOrder)
                throw new HttpRequestException("big order blocked");

            string json;
            if (path.StartsWith("/api/big-order/"))
                json = "{'ok':true,'fetchedAt':1781746200000,'data':{'title':{'stockname':'博云新材','price':28.36},'list':[{'nature':'主力主买','volume':'10手','avgprice':'28.36','money':28360,'otime':'2026-06-18 09:30:01'}],'pricechange':[]}}";
            else if (path.StartsWith("/api/quotes/"))
                json = QuoteDegraded
                    ? "{'ok':false,'degraded':true,'data':null}"
                    : "{'data':{'diff':[{'f12':'" + Code(path) + "','f14':'博云新材','f2':" + QuotePrice.ToString(System.Globalization.CultureInfo.InvariantCulture) + ",'f5':1000000,'f6':100,'f8':1.2,'f10':0.8}]}}";
            else
                json = "{'data':{'info':[{'code':'" + Code(path) + "','order_amount':45049860,'high_days':'首板'}]}" + (LimitStale ? ",'dragonMeta':{'cache':{'stale':true}}" : "") + "}";
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json, Encoding.UTF8, "application/json") };
        }

        private static string Code(string path)
        {
            var marker = path.Contains("codes=") ? "codes=" : "stockCode=";
            var index = path.IndexOf(marker, StringComparison.Ordinal);
            return index < 0 ? "002297" : path.Substring(index + marker.Length, 6);
        }
    }

    private sealed class ControlledProvider : IMarketSnapshotProvider
    {
        private readonly Dictionary<string, TaskCompletionSource<MarketSnapshot>> _pending =
            new Dictionary<string, TaskCompletionSource<MarketSnapshot>>();

        public Task<MarketSnapshot> LoadSnapshotAsync(string stockCode, CancellationToken cancellationToken)
        {
            var source = new TaskCompletionSource<MarketSnapshot>();
            _pending[stockCode] = source;
            return source.Task;
        }

        public void CalculateMarkers(List<BigOrderItem> data) { }

        public void Complete(string stockCode)
        {
            _pending[stockCode].SetResult(new MarketSnapshot(
                stockCode,
                new StockSummary { Code = stockCode, Name = stockCode, Price = 10 },
                new MainFundSummary(),
                new LimitUpContext(),
                new List<BigOrderItem>(),
                new List<PricePoint>(),
                DataFreshness.Fresh,
                DataFreshness.Fresh,
                DataFreshness.Missing,
                DateTime.Now,
                DateTime.Now));
        }
    }
}
