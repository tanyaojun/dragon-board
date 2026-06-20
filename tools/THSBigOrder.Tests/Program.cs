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
using THSBigOrder.DataSources;
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
        Run("THS snapshot parser reads Tencent minute turnover", TestMinuteTurnoverParsing);
        Run("Direct Sina quote parser decodes GBK fields", TestDirectSinaQuoteParsing);
        Run("Direct Tencent minute parser validates nested rows", TestDirectTencentMinuteParsing);
        Run("Direct THS payload parsers distinguish empty limit-up", TestDirectThsParsing);
        Run("Direct source clients use upstream and matching proxy contracts", () => TestDirectSourceClients().GetAwaiter().GetResult());
        Run("Proxy envelope maps degraded, stale and fresh empty states", TestEnvelopeStates);
        Run("Provider stale fallback is isolated by stock code", () => TestProviderStaleIsolation().GetAwaiter().GetResult());
        Run("Provider direct success does not call proxy", () => TestDirectSuccess().GetAwaiter().GetResult());
        Run("Provider falls back only the failed source", () => TestIndependentProxyFallback().GetAwaiter().GetResult());
        Run("Provider does not fallback valid empty limit-up", () => TestValidEmptyLimitUp().GetAwaiter().GetResult());
        Run("Provider uses same-stock stale only after both attempts fail", () => TestPerSourceStale().GetAwaiter().GetResult());
        Run("Series builder aggregates minute flow and thresholds", TestSeriesBuilder);
        Run("Series builder computes Tencent market VWAP", TestMarketAveragePrices);
        Run("Series builder computes cumulative big-order average price", TestBigOrderAveragePrices);
        Run("Series builder aggregates eight half-hour turnover bands", TestHalfHourSeries);
        Run("Legacy marker thresholds remain stable", TestLegacyMarkers);
        Run("Chart control binds three layout bands and draws empty data", TestChartControl);
        Run("Chart control exposes paired axes and intraday grids", TestIntradayChartLayout);
        Run("Chart control maps both average prices to one axis", TestAveragePriceAxis);
        Run("Chart control falls back to THS percent only for market line", TestThsPriceFallback);
        Run("Chart control normalizes half-hour heat rows independently", TestHalfHourHeatRatios);
        Run("Chart heat text stays readable at maximum intensity", TestHeatTextContrast);
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

    private static void TestMinuteTurnoverParsing()
    {
        var parser = new ThsPayloadParser();
        var ths = JObject.Parse("{'ok':true,'data':{'title':{},'list':[],'pricechange':[]}}");
        var minute = JObject.Parse(@"{
          'ok':true,'data':{'date':'20260618','points':[
            {'time':'0930','price':25.70,'cumulativeVolume':11848,'cumulativeAmount':30449360.00},
            {'time':'0931','price':26.25,'cumulativeVolume':71011,'cumulativeAmount':184435426.43},
            {'time':'0932','price':26.20,'cumulativeVolume':70000,'cumulativeAmount':180000000.00},
            {'time':'bad','price':26.20,'cumulativeVolume':72000,'cumulativeAmount':185000000.00}
          ]}}");

        var snapshot = parser.ParseSnapshot(
            "002297", ths, new JObject(), minute, new JObject(),
            DateTime.Parse("2026-06-18 10:00:00"));

        AssertEqual(2, snapshot.MinuteTurnover.Count, "valid minute points");
        AssertEqual(new DateTime(2026, 6, 18, 9, 30, 0), snapshot.MinuteTurnover[0].Time, "minute time");
        AssertEqual(184435426.43d, snapshot.MinuteTurnover[1].CumulativeAmount, "minute cumulative amount");
        AssertEqual(DataFreshness.Fresh, snapshot.MinuteTurnoverFreshness, "minute freshness");
        AssertTrue(snapshot.Issues.Count >= 2, "invalid minute points reported");
    }

    private static void TestDirectSinaQuoteParsing()
    {
        var bytes = Encoding.GetEncoding(936).GetBytes(
            "var hq_str_sz002297=\"博云新材,25.70,25.76,28.36,28.36,25.69,0,0,117850000,3342254360,0\";");
        var quote = new ThsPayloadParser().ParseSinaQuote("002297", bytes);
        AssertEqual("博云新材", quote.Name, "sina name");
        AssertNear(28.36d, quote.Price.Value, 0.0001d, "sina price");
        AssertNear(10.0932d, quote.ChangePercent.Value, 0.001d, "sina change");
        AssertEqual(117850000d, quote.Volume.Value, "sina volume shares");
        AssertEqual(3342254360d, quote.TotalAmount.Value, "sina amount");
        AssertEqual<double?>(null, quote.TurnoverRate, "sina turnover unavailable");
        AssertEqual<double?>(null, quote.VolumeRatio, "sina ratio unavailable");
    }

    private static void TestDirectTencentMinuteParsing()
    {
        var payload = JObject.Parse(@"{
          'code':0,
          'data':{'sz002297':{'data':{'date':'20260618','data':[
            '0930 25.70 11848 30449360.00',
            '0931 25.98 71011 184435426.43'
          ]}}}
        }");
        var points = new ThsPayloadParser().ParseTencentMinute("002297", payload);
        AssertEqual(2, points.Count, "direct minute count");
        AssertEqual(new DateTime(2026, 6, 18, 9, 30, 0), points[0].Time, "direct minute time");
        AssertEqual(184435426.43d, points[1].CumulativeAmount, "direct minute amount");

        AssertThrows<PayloadParseException>(() =>
            new ThsPayloadParser().ParseTencentMinute("002297", JObject.Parse("{'code':1,'msg':'blocked'}")),
            "tencent error code");
        AssertThrows<PayloadParseException>(() =>
            new ThsPayloadParser().ParseTencentMinute("002297", JObject.Parse(
                "{'code':0,'data':{'sz002297':{'data':{'date':'bad','data':[]}}}}")),
            "tencent invalid date");
    }

    private static void TestDirectThsParsing()
    {
        var parser = new ThsPayloadParser();
        var big = parser.ParseBigOrderSource("002297", JObject.Parse(@"{
          'errorcode':0,
          'title':{'stockname':'博云新材','price':28.36,'mainbuy':'100万','mainsell':'40万'},
          'list':[{'nature':'主力主买','volume':'10手','avgprice':'28.36','money':28360,'otime':'2026-06-18 09:30:01'}],
          'pricechange':[]
        }"));
        AssertEqual("博云新材", big.StockFallback.Name, "direct THS name");
        AssertEqual(1, big.Orders.Count, "direct THS orders");
        AssertEqual(600000d, big.MainFunds.NetAmount.Value, "direct THS net");

        var empty = parser.ParseLimitUpSource("002297", JObject.Parse("{'data':{'info':[]}}"));
        AssertTrue(!empty.Found, "empty limit-up is valid");
        AssertEqual<double?>(null, empty.Context.SealAmount, "empty limit-up context");
        AssertThrows<PayloadParseException>(() =>
            parser.ParseBigOrderSource("002297", JObject.Parse("{'errorcode':1,'msg':'blocked'}")),
            "THS error code");
    }

    private static async Task TestDirectSourceClients()
    {
        var handler = new SourceClientHandler();
        using (var http = new HttpClient(handler))
        {
            var parser = new ThsPayloadParser();
            var big = new ThsBigOrderSourceClient(http, "http://127.0.0.1:3000", parser);
            var quote = new SinaQuoteSourceClient(http, "http://127.0.0.1:3000", parser);
            var minute = new TencentMinuteSourceClient(http, "http://127.0.0.1:3000", parser);
            var limit = new ThsLimitUpSourceClient(http, "http://127.0.0.1:3000", parser);

            AssertEqual(DataTransport.Direct, (await big.LoadDirectAsync("002297", CancellationToken.None)).Transport, "big direct");
            AssertEqual(DataTransport.Direct, (await quote.LoadDirectAsync("002297", CancellationToken.None)).Transport, "quote direct");
            AssertEqual(DataTransport.Direct, (await minute.LoadDirectAsync("002297", CancellationToken.None)).Transport, "minute direct");
            var empty = await limit.LoadDirectAsync("002297", CancellationToken.None);
            AssertEqual(DataTransport.Direct, empty.Transport, "limit direct");
            AssertTrue(!empty.Data.Found, "valid empty limit-up");

            await big.LoadProxyAsync("002297", CancellationToken.None);
            await quote.LoadProxyAsync("002297", CancellationToken.None);
            await minute.LoadProxyAsync("002297", CancellationToken.None);
            await limit.LoadProxyAsync("002297", CancellationToken.None);

            AssertTrue(handler.Records.Any(x => x.Uri.Host == "vaserviece.10jqka.com.cn" && x.Uri.Query.Contains("op=mainMonitorDetail") && x.Uri.Query.Contains("stockcode=002297")), "big direct url");
            AssertTrue(handler.Records.Any(x => x.Uri.Host == "hq.sinajs.cn" && x.Uri.AbsoluteUri.Contains("sz002297")), "sina direct url");
            AssertTrue(handler.Records.Any(x => x.Uri.Host == "web.ifzq.gtimg.cn" && x.Uri.Query.Contains("sz002297")), "tencent direct url");
            AssertTrue(handler.Records.Any(x => x.Uri.Host == "data.10jqka.com.cn" && x.Uri.AbsolutePath.Contains("limit_up_pool")), "limit direct url");
            AssertTrue(handler.Records.Any(x => x.Uri.PathAndQuery == "/api/big-order/ths-detail?stockCode=002297"), "big proxy path");
            AssertTrue(handler.Records.Any(x => x.Uri.PathAndQuery == "/api/quotes/sina?codes=002297"), "sina proxy path");
            AssertTrue(handler.Records.Any(x => x.Uri.PathAndQuery == "/api/quotes/tencent/minute?code=002297"), "minute proxy path");
            AssertTrue(handler.Records.Any(x => x.Uri.PathAndQuery == "/api/limitup/10jqka"), "limit proxy path");

            var bigRecord = handler.Records.First(x => x.Uri.Host == "vaserviece.10jqka.com.cn");
            AssertTrue(!string.IsNullOrEmpty(bigRecord.UserAgent), "THS user agent");
            AssertTrue(bigRecord.Referer.Contains("10jqka"), "THS referer");
            var sinaRecord = handler.Records.First(x => x.Uri.Host == "hq.sinajs.cn");
            AssertTrue(sinaRecord.Referer.Contains("finance.sina.com.cn"), "Sina referer");
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

    private static async Task TestDirectSuccess()
    {
        var sources = CreateSourceStubs();
        using (var provider = CreateProvider(sources))
        {
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(DataTransport.Direct, snapshot.Transports.BigOrder, "big direct transport");
            AssertEqual(DataTransport.Direct, snapshot.Transports.Quote, "quote direct transport");
            AssertEqual(DataTransport.Direct, snapshot.Transports.Minute, "minute direct transport");
            AssertEqual(DataTransport.Direct, snapshot.Transports.LimitUp, "limit direct transport");
            AssertEqual(0, sources.Big.ProxyCalls + sources.Quote.ProxyCalls + sources.Minute.ProxyCalls + sources.Limit.ProxyCalls, "no proxy calls");
        }
    }

    private static async Task TestIndependentProxyFallback()
    {
        var sources = CreateSourceStubs();
        sources.Minute.Direct = _ => throw new HttpRequestException("Tencent direct blocked");
        sources.Minute.Proxy = _ => Task.FromResult(new SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>
        {
            Data = new[] { MinutePoint() }, Freshness = DataFreshness.Fresh,
            Transport = DataTransport.ProxyFallback, FetchedAt = DateTime.Now,
        });
        using (var provider = CreateProvider(sources))
        {
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(DataTransport.ProxyFallback, snapshot.Transports.Minute, "minute proxy transport");
            AssertEqual(1, sources.Minute.ProxyCalls, "minute proxy called once");
            AssertEqual(0, sources.Big.ProxyCalls + sources.Quote.ProxyCalls + sources.Limit.ProxyCalls, "other proxies untouched");
        }
    }

    private static async Task TestValidEmptyLimitUp()
    {
        var sources = CreateSourceStubs();
        sources.Limit.Direct = _ => Task.FromResult(new SourceLoadResult<LimitUpSourceData>
        {
            Data = new LimitUpSourceData { Found = false, Context = new LimitUpContext() },
            Freshness = DataFreshness.Missing, Transport = DataTransport.Direct, FetchedAt = DateTime.Now,
        });
        using (var provider = CreateProvider(sources))
        {
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(DataFreshness.Missing, snapshot.LimitUpFreshness, "valid empty freshness");
            AssertEqual(DataTransport.Direct, snapshot.Transports.LimitUp, "valid empty transport");
            AssertEqual(0, sources.Limit.ProxyCalls, "valid empty skips proxy");
        }
    }

    private static async Task TestPerSourceStale()
    {
        var sources = CreateSourceStubs();
        using (var provider = CreateProvider(sources))
        {
            var fresh = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            sources.Big.Direct = _ => throw new HttpRequestException("direct blocked");
            sources.Big.Proxy = _ => throw new HttpRequestException("proxy stopped");
            var stale = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(fresh.Orders.Count, stale.Orders.Count, "same-stock big orders retained");
            AssertEqual(DataFreshness.Stale, stale.BigOrderFreshness, "big stale freshness");
            AssertEqual(DataTransport.Stale, stale.Transports.BigOrder, "big stale transport");
            AssertEqual(DataTransport.Direct, stale.Transports.Quote, "quote keeps direct");
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

    private static void TestMarketAveragePrices()
    {
        var day = new DateTime(2026, 6, 20);
        var turnover = new[]
        {
            new MinuteTurnoverPoint
            {
                Time = day.AddHours(9).AddMinutes(31),
                CumulativeVolume = 71011,
                CumulativeAmount = 184435426.43,
            },
            new MinuteTurnoverPoint
            {
                Time = day.AddHours(9).AddMinutes(30),
                CumulativeVolume = 11848,
                CumulativeAmount = 30449360,
            },
            new MinuteTurnoverPoint
            {
                Time = day.AddHours(9).AddMinutes(32),
                CumulativeVolume = 0,
                CumulativeAmount = 200000000,
            },
            new MinuteTurnoverPoint
            {
                Time = day.AddHours(9).AddMinutes(33),
                CumulativeVolume = double.NaN,
                CumulativeAmount = double.PositiveInfinity,
            },
            new MinuteTurnoverPoint
            {
                Time = day.AddHours(13),
                CumulativeVolume = 71011,
                CumulativeAmount = -1,
            },
        };

        var series = new BigOrderSeriesBuilder().Build(
            new BigOrderItem[0], turnover, DataFreshness.Fresh);

        AssertEqual(2, series.MarketAveragePrices.Count, "valid market VWAP count");
        AssertEqual(day.AddHours(9).AddMinutes(30), series.MarketAveragePrices[0].Time, "market VWAP order");
        AssertNear(25.70d, series.MarketAveragePrices[0].Price, 0.001d, "09:30 market VWAP");
        AssertNear(25.9728d, series.MarketAveragePrices[1].Price, 0.001d, "09:31 market VWAP");

        var unavailable = new BigOrderSeriesBuilder().Build(
            new BigOrderItem[0], turnover, DataFreshness.Failed);
        AssertEqual(0, unavailable.MarketAveragePrices.Count, "failed turnover has no market VWAP");
    }

    private static void TestBigOrderAveragePrices()
    {
        var day = new DateTime(2026, 6, 20);
        var orders = new[]
        {
            new BigOrderItem { Time = day.AddHours(9).AddMinutes(31).AddSeconds(2), Price = 20, Volume = 300, Amount = 1, Type = 3 },
            new BigOrderItem { Time = day.AddHours(9).AddMinutes(30).AddSeconds(1), Price = 10, Volume = 100, Amount = 99999, Type = 2 },
            new BigOrderItem { Time = day.AddHours(9).AddMinutes(32).AddSeconds(3), Price = 30, Volume = 100, Amount = 1, Type = 4 },
            new BigOrderItem { Time = day.AddHours(9).AddMinutes(32).AddSeconds(3), Price = 40, Volume = 100, Amount = 2, Type = 2 },
            new BigOrderItem { Time = day.AddHours(9).AddMinutes(33), Price = 0, Volume = 100, Amount = 1, Type = 2 },
            new BigOrderItem { Time = day.AddHours(9).AddMinutes(34), Price = 40, Volume = 0, Amount = 1, Type = 2 },
            new BigOrderItem { Time = day.AddHours(9).AddMinutes(35), Price = double.NaN, Volume = 10, Amount = 1, Type = 2 },
            new BigOrderItem { Time = day.AddHours(9).AddMinutes(36), Price = 50, Volume = double.PositiveInfinity, Amount = 1, Type = 2 },
        };

        var series = new BigOrderSeriesBuilder().Build(orders);

        AssertEqual(4, series.BigOrderAveragePrices.Count, "valid big-order average count");
        AssertNear(10d, series.BigOrderAveragePrices[0].Price, 0.0001d, "first big-order average");
        AssertNear(17.5d, series.BigOrderAveragePrices[1].Price, 0.0001d, "weighted big-order average");
        AssertNear(20d, series.BigOrderAveragePrices[2].Price, 0.0001d, "cumulative big-order average");
        AssertNear(23.333333d, series.BigOrderAveragePrices[3].Price, 0.0001d, "same-second average");
        AssertEqual(4, series.BigOrderEvents.Count, "one event per valid order");
        AssertEqual(day.AddHours(9).AddMinutes(30).AddSeconds(1), series.BigOrderEvents[0].Time, "seconds retained");
        AssertNear(series.BigOrderAveragePrices[0].Price, series.BigOrderEvents[0].AveragePrice, 0.0001d, "event lies on white line");
        AssertEqual(2, series.BigOrderEvents[0].Type, "active buy retained");
        AssertEqual(3, series.BigOrderEvents[1].Type, "passive type retained");
        AssertEqual(4, series.BigOrderEvents[2].Type, "active sell retained");
        AssertEqual(series.BigOrderEvents[2].Time, series.BigOrderEvents[3].Time, "same-second orders preserved");
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

    private static void TestHalfHourSeries()
    {
        var day = new DateTime(2026, 6, 18);
        var orders = new[]
        {
            new BigOrderItem { Type = 2, Amount = 1000000, Time = day.AddHours(9).AddMinutes(30) },
            new BigOrderItem { Type = 4, Amount = 800000, Time = day.AddHours(9).AddMinutes(59) },
            new BigOrderItem { Type = 2, Amount = 2000000, Time = day.AddHours(10) },
            new BigOrderItem { Type = 4, Amount = 3000000, Time = day.AddHours(11).AddMinutes(30) },
            new BigOrderItem { Type = 2, Amount = 4000000, Time = day.AddHours(15) },
        };
        var turnover = new[]
        {
            new MinuteTurnoverPoint { Time = day.AddHours(9).AddMinutes(30), CumulativeAmount = 100 },
            new MinuteTurnoverPoint { Time = day.AddHours(9).AddMinutes(59), CumulativeAmount = 300 },
            new MinuteTurnoverPoint { Time = day.AddHours(10), CumulativeAmount = 500 },
            new MinuteTurnoverPoint { Time = day.AddHours(11).AddMinutes(30), CumulativeAmount = 900 },
            new MinuteTurnoverPoint { Time = day.AddHours(13), CumulativeAmount = 900 },
            new MinuteTurnoverPoint { Time = day.AddHours(14).AddMinutes(30), CumulativeAmount = 1000 },
            new MinuteTurnoverPoint { Time = day.AddHours(15), CumulativeAmount = 1300 },
        };

        var series = new BigOrderSeriesBuilder().Build(orders, turnover, DataFreshness.Fresh);

        AssertEqual(8, series.HalfHours.Count, "eight half-hours");
        AssertEqual(300d, series.HalfHours[0].TotalAmount.Value, "first total amount");
        AssertEqual(1800000d, series.HalfHours[0].BigOrderAmount, "first big-order total");
        AssertEqual(200d, series.HalfHours[1].TotalAmount.Value, "10:00 boundary");
        AssertEqual(400d, series.HalfHours[3].TotalAmount.Value, "11:30 close boundary");
        AssertEqual(0d, series.HalfHours[4].TotalAmount.Value, "13:00 unchanged cumulative");
        AssertEqual(400d, series.HalfHours[7].TotalAmount.Value, "15:00 close boundary");
        AssertEqual(4000000d, series.HalfHours[7].BigOrderAmount, "last big-order total");
        AssertEqual("14:30-15:00", series.HalfHours[7].Label, "last label");

        var missing = new BigOrderSeriesBuilder().Build(orders, new MinuteTurnoverPoint[0], DataFreshness.Failed);
        AssertTrue(missing.HalfHours.All(value => !value.TotalAmount.HasValue), "failed turnover is missing");
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

    private static void TestIntradayChartLayout()
    {
        var day = new DateTime(2026, 6, 18);
        var snapshot = new MarketSnapshot(
            "002297",
            new StockSummary { Code = "002297", Price = 28.36, ChangePercent = 10.0 },
            new MainFundSummary(),
            new LimitUpContext(),
            new BigOrderItem[0],
            new[]
            {
                new PricePoint { Time = day.AddHours(9).AddMinutes(30), ChangePercent = 0 },
                new PricePoint { Time = day.AddHours(10).AddMinutes(30), ChangePercent = 10 },
            },
            new[]
            {
                new MinuteTurnoverPoint { Time = day.AddHours(9).AddMinutes(30), CumulativeAmount = 100 },
            },
            DataFreshness.Fresh,
            DataFreshness.Fresh,
            DataFreshness.Fresh,
            DataFreshness.Missing,
            day.AddHours(10).AddMinutes(30),
            day.AddHours(10).AddMinutes(30));
        var series = new BigOrderSeriesBuilder().Build(
            snapshot.Orders, snapshot.MinuteTurnover, snapshot.MinuteTurnoverFreshness);

        using (var control = new BigOrderChartControl())
        {
            control.Size = new Size(1000, 650);
            control.SetSnapshot(snapshot, series);
            AssertTrue(control.LayoutBands[0].Left >= 52, "left price axis margin");
            AssertTrue(control.ClientSize.Width - control.LayoutBands[0].Right >= 48, "right pct axis margin");
            AssertEqual(5, control.HourGridXs.Count, "four hour cells");
            AssertEqual(9, control.HalfHourGridXs.Count, "eight half-hour cells");
            AssertEqual(2, control.HalfHourRows.Count, "turnover and big-order rows");
            AssertEqual(5, control.AxisTicks.Count, "paired axis ticks");
            AssertTrue(control.AxisTicks.All(value => value.Price.HasValue), "price ticks available");
            using (var bitmap = new Bitmap(1000, 650))
                control.DrawToBitmap(bitmap, control.ClientRectangle);
        }
    }

    private static void TestAveragePriceAxis()
    {
        var day = new DateTime(2026, 6, 20);
        var snapshot = CreateChartSnapshot(day, new PricePoint[0]);
        var series = new BigOrderSeries
        {
            Minutes = new MinuteFlow[0],
            NetFlow = new NetFlowPoint[0],
            Thresholds = new ThresholdFlow[0],
            HalfHours = new HalfHourAmount[0],
            MarketAveragePrices = new[]
            {
                new AveragePricePoint { Time = day.AddHours(9).AddMinutes(30), Price = 10.5 },
                new AveragePricePoint { Time = day.AddHours(9).AddMinutes(31), Price = 11 },
            },
            BigOrderAveragePrices = new[]
            {
                new AveragePricePoint { Time = day.AddHours(9).AddMinutes(30), Price = 10.2 },
                new AveragePricePoint { Time = day.AddHours(9).AddMinutes(31), Price = 10.8 },
            },
        };

        using (var control = new BigOrderChartControl())
        {
            control.Size = new Size(1000, 650);
            control.SetSnapshot(snapshot, series);
            AssertNear(5d, control.MarketLinePercents[0].Value, 0.0001d, "market line shared percent");
            AssertNear(10d, control.MarketLinePercents[1].Value, 0.0001d, "market line second percent");
            AssertNear(2d, control.BigOrderLinePercents[0].Value, 0.0001d, "big-order line shared percent");
            AssertNear(8d, control.BigOrderLinePercents[1].Value, 0.0001d, "big-order line second percent");
            AssertTrue(control.AxisTicks.First().Percent <= 0, "axis contains zero percent");
            AssertTrue(control.AxisTicks.Last().Percent >= 10, "axis contains both lines");
        }
    }

    private static void TestThsPriceFallback()
    {
        var day = new DateTime(2026, 6, 20);
        var thsPrices = new[]
        {
            new PricePoint { Time = day.AddHours(9).AddMinutes(30), ChangePercent = 1.25 },
            new PricePoint { Time = day.AddHours(9).AddMinutes(31), ChangePercent = 2.5 },
        };
        var snapshot = CreateChartSnapshot(day, thsPrices);
        var series = new BigOrderSeriesBuilder().Build(new BigOrderItem[0]);

        using (var control = new BigOrderChartControl())
        {
            control.SetSnapshot(snapshot, series);
            AssertEqual(2, control.MarketLinePercents.Count, "THS market fallback count");
            AssertNear(1.25d, control.MarketLinePercents[0].Value, 0.0001d, "THS market fallback value");
            AssertEqual(0, control.BigOrderLinePercents.Count, "net flow is not a price line");
        }
    }

    private static MarketSnapshot CreateChartSnapshot(
        DateTime day, IReadOnlyList<PricePoint> prices)
    {
        return new MarketSnapshot(
            "002297",
            new StockSummary { Code = "002297", Price = 11, ChangePercent = 10 },
            new MainFundSummary(),
            new LimitUpContext(),
            new BigOrderItem[0],
            prices,
            DataFreshness.Fresh,
            DataFreshness.Fresh,
            DataFreshness.Missing,
            day.AddHours(10),
            day.AddHours(10));
    }

    private static void TestHalfHourHeatRatios()
    {
        var day = new DateTime(2026, 6, 20);
        var halfHours = new[]
        {
            new HalfHourAmount { TotalAmount = 100000000, BigOrderAmount = 1000000 },
            new HalfHourAmount { TotalAmount = 50000000, BigOrderAmount = 4000000 },
            new HalfHourAmount { TotalAmount = 0, BigOrderAmount = 0 },
            new HalfHourAmount { TotalAmount = null, BigOrderAmount = 2000000 },
        };
        var series = new BigOrderSeries
        {
            Minutes = new MinuteFlow[0],
            NetFlow = new NetFlowPoint[0],
            Thresholds = new ThresholdFlow[0],
            HalfHours = halfHours,
            MarketAveragePrices = new AveragePricePoint[0],
            BigOrderAveragePrices = new AveragePricePoint[0],
        };

        using (var control = new BigOrderChartControl())
        {
            control.SetSnapshot(CreateChartSnapshot(day, new PricePoint[0]), series);
            AssertEqual(8, control.TotalHeatRatios.Count, "total heat cell count");
            AssertEqual(8, control.BigOrderHeatRatios.Count, "big-order heat cell count");
            AssertNear(1d, control.TotalHeatRatios[0].Value, 0.0001d, "total row max");
            AssertNear(0.5d, control.TotalHeatRatios[1].Value, 0.0001d, "total row half");
            AssertNear(0d, control.TotalHeatRatios[2].Value, 0.0001d, "zero has no heat");
            AssertTrue(!control.TotalHeatRatios[3].HasValue, "missing has no ratio");
            AssertNear(0.25d, control.BigOrderHeatRatios[0], 0.0001d, "big row independent scale");
            AssertNear(1d, control.BigOrderHeatRatios[1], 0.0001d, "big row max");
            AssertNear(0.5d, control.BigOrderHeatRatios[3], 0.0001d, "big row half");
            AssertTrue(control.TotalHeatRatios.Skip(4).All(value => !value.HasValue), "missing total cells padded");
            AssertTrue(control.BigOrderHeatRatios.Skip(4).All(value => value == 0), "missing big cells padded");
        }

        var zeroSeries = new BigOrderSeries
        {
            HalfHours = Enumerable.Range(0, 8)
                .Select(_ => new HalfHourAmount { TotalAmount = 0, BigOrderAmount = 0 })
                .ToArray(),
        };
        using (var control = new BigOrderChartControl())
        {
            control.SetSnapshot(CreateChartSnapshot(day, new PricePoint[0]), zeroSeries);
            AssertTrue(control.TotalHeatRatios.All(value => value.GetValueOrDefault() == 0), "all-zero total row");
            AssertTrue(control.BigOrderHeatRatios.All(value => value == 0), "all-zero big row");
        }
    }

    private static void TestHeatTextContrast()
    {
        AssertTrue(
            ContrastRatio(
                BigOrderChartControl.BigOrderHeatTextColor,
                BigOrderChartControl.BigOrderHeatHighColor) >= 4.5,
            "big-order heat text contrast");
    }

    private static double ContrastRatio(Color first, Color second)
    {
        var firstLuminance = RelativeLuminance(first);
        var secondLuminance = RelativeLuminance(second);
        return (Math.Max(firstLuminance, secondLuminance) + 0.05) /
               (Math.Min(firstLuminance, secondLuminance) + 0.05);
    }

    private static double RelativeLuminance(Color color)
    {
        Func<int, double> channel = value =>
        {
            var normalized = value / 255d;
            return normalized <= 0.03928
                ? normalized / 12.92
                : Math.Pow((normalized + 0.055) / 1.055, 2.4);
        };
        return 0.2126 * channel(color.R) +
               0.7152 * channel(color.G) +
               0.0722 * channel(color.B);
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

    private static void AssertNear(double expected, double actual, double tolerance, string label)
    {
        if (Math.Abs(expected - actual) > tolerance)
        {
            throw new InvalidOperationException(
                label + ": expected " + expected + ", actual " + actual);
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

    private static SourceStubs CreateSourceStubs()
    {
        var day = new DateTime(2026, 6, 18);
        return new SourceStubs
        {
            Big = new StubSourceClient<BigOrderSourceData>
            {
                Direct = _ => Task.FromResult(new SourceLoadResult<BigOrderSourceData>
                {
                    Data = new BigOrderSourceData
                    {
                        StockFallback = new StockSummary { Code = "002297", Name = "博云新材", Price = 28.36 },
                        MainFunds = new MainFundSummary { MainBuy = 1000000, MainSell = 400000, NetAmount = 600000, OrderCount = 1 },
                        Orders = new[] { new BigOrderItem { Time = day.AddHours(9).AddMinutes(30), Price = 28.36, Volume = 10, Amount = 28360, Type = 2 } },
                        Prices = new PricePoint[0],
                    },
                    Freshness = DataFreshness.Fresh, Transport = DataTransport.Direct, FetchedAt = DateTime.Now,
                }),
            },
            Quote = new StubSourceClient<StockSummary>
            {
                Direct = _ => Task.FromResult(new SourceLoadResult<StockSummary>
                {
                    Data = new StockSummary { Code = "002297", Name = "博云新材", Price = 28.36, ChangePercent = 10.09, TotalAmount = 3342254360 },
                    Freshness = DataFreshness.Fresh, Transport = DataTransport.Direct, FetchedAt = DateTime.Now,
                }),
            },
            Minute = new StubSourceClient<IReadOnlyList<MinuteTurnoverPoint>>
            {
                Direct = _ => Task.FromResult(new SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>
                {
                    Data = new[] { MinutePoint() }, Freshness = DataFreshness.Fresh,
                    Transport = DataTransport.Direct, FetchedAt = DateTime.Now,
                }),
            },
            Limit = new StubSourceClient<LimitUpSourceData>
            {
                Direct = _ => Task.FromResult(new SourceLoadResult<LimitUpSourceData>
                {
                    Data = new LimitUpSourceData { Found = true, Context = new LimitUpContext { SealAmount = 45049860 } },
                    Freshness = DataFreshness.Fresh, Transport = DataTransport.Direct, FetchedAt = DateTime.Now,
                }),
            },
        };
    }

    private static MinuteTurnoverPoint MinutePoint()
    {
        return new MinuteTurnoverPoint
        {
            Time = new DateTime(2026, 6, 18, 9, 30, 0), Price = 25.70,
            CumulativeVolume = 11848, CumulativeAmount = 30449360,
        };
    }

    private static THSBigOrderDataProvider CreateProvider(SourceStubs value)
    {
        return new THSBigOrderDataProvider(value.Big, value.Quote, value.Minute, value.Limit);
    }

    private sealed class SourceStubs
    {
        public StubSourceClient<BigOrderSourceData> Big { get; set; }
        public StubSourceClient<StockSummary> Quote { get; set; }
        public StubSourceClient<IReadOnlyList<MinuteTurnoverPoint>> Minute { get; set; }
        public StubSourceClient<LimitUpSourceData> Limit { get; set; }
    }

    private sealed class StubSourceClient<T> : IMarketSourceClient<T>
    {
        public Func<CancellationToken, Task<SourceLoadResult<T>>> Direct { get; set; }
        public Func<CancellationToken, Task<SourceLoadResult<T>>> Proxy { get; set; }
        public int DirectCalls { get; private set; }
        public int ProxyCalls { get; private set; }

        public Task<SourceLoadResult<T>> LoadDirectAsync(string stockCode, CancellationToken cancellationToken)
        {
            DirectCalls++;
            return Direct(cancellationToken);
        }

        public Task<SourceLoadResult<T>> LoadProxyAsync(string stockCode, CancellationToken cancellationToken)
        {
            ProxyCalls++;
            if (Proxy == null) throw new InvalidOperationException("unexpected proxy call");
            return Proxy(cancellationToken);
        }
    }

    private sealed class SourceRequestRecord
    {
        public Uri Uri { get; set; }
        public string UserAgent { get; set; }
        public string Referer { get; set; }
    }

    private sealed class SourceClientHandler : HttpMessageHandler
    {
        public List<SourceRequestRecord> Records { get; } = new List<SourceRequestRecord>();

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Records.Add(new SourceRequestRecord
            {
                Uri = request.RequestUri,
                UserAgent = request.Headers.UserAgent.ToString(),
                Referer = request.Headers.Referrer?.ToString() ?? "",
            });

            HttpContent content;
            var host = request.RequestUri.Host;
            var path = request.RequestUri.AbsolutePath;
            if (host == "hq.sinajs.cn")
            {
                content = new ByteArrayContent(Encoding.GetEncoding(936).GetBytes(
                    "var hq_str_sz002297=\"博云新材,25.70,25.76,28.36,28.36,25.69,0,0,117850000,3342254360,0\";"));
            }
            else
            {
                string json;
                if (host == "vaserviece.10jqka.com.cn")
                    json = "{'errorcode':0,'title':{'stockname':'博云新材','price':28.36},'list':[],'pricechange':[]}";
                else if (host == "web.ifzq.gtimg.cn")
                    json = "{'code':0,'data':{'sz002297':{'data':{'date':'20260618','data':['0930 25.70 11848 30449360']}}}}";
                else if (host == "data.10jqka.com.cn")
                    json = "{'data':{'info':[]}}";
                else if (path == "/api/big-order/ths-detail")
                    json = "{'ok':true,'fetchedAt':1781746200000,'data':{'title':{'stockname':'博云新材','price':28.36},'list':[],'pricechange':[]}}";
                else if (path == "/api/quotes/sina")
                    json = "{'data':{'diff':[{'f12':'002297','f14':'博云新材','f2':28.36,'f3':10.09,'f5':3342254360,'f6':117850000}]}}";
                else if (path == "/api/quotes/tencent/minute")
                    json = "{'ok':true,'data':{'date':'20260618','points':[{'time':'0930','price':25.70,'cumulativeVolume':11848,'cumulativeAmount':30449360}]}}";
                else
                    json = "{'data':{'info':[]}}";
                content = new StringContent(json, Encoding.UTF8, "application/json");
            }
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = content });
        }
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
            if (_barrier) await Task.Delay(50, cancellationToken);
            lock (Paths) { _pending--; }

            if (path.StartsWith("/api/big-order/") && FailBigOrder)
                throw new HttpRequestException("big order blocked");

            string json;
            if (path.StartsWith("/api/big-order/"))
                json = "{'ok':true,'fetchedAt':1781746200000,'data':{'title':{'stockname':'博云新材','price':28.36},'list':[{'nature':'主力主买','volume':'10手','avgprice':'28.36','money':28360,'otime':'2026-06-18 09:30:01'}],'pricechange':[]}}";
            else if (path.StartsWith("/api/quotes/tencent/minute"))
                json = "{'ok':true,'data':{'date':'20260618','points':[{'time':'0930','price':25.70,'cumulativeVolume':11848,'cumulativeAmount':30449360.00}]}}";
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
