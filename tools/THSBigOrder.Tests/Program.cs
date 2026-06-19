using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using THSBigOrder;
using THSBigOrder.Models;
using THSBigOrder.Parsing;

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
        return Environment.ExitCode;
    }

    private static void TestOrderParsing()
    {
        var parser = new ThsPayloadParser();
        var item = parser.ParseOrder(JObject.Parse(@"{
          'nature':'主力主买','volume':'5,000手','avgprice':'1,215.00',
          'money':607500000,'otime':'2026-06-18 11:29:50'
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
}
