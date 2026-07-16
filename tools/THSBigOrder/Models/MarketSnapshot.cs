using System;
using System.Collections.Generic;
using THSBigOrder.DataSources;

namespace THSBigOrder.Models
{
    public enum DataFreshness { Fresh, Stale, Missing, Failed }

    public sealed class ProxyEnvelope<T>
    {
        public bool Ok { get; set; }
        public bool Degraded { get; set; }
        public string ErrorCode { get; set; }
        public long FetchedAt { get; set; }
        public long ServedAt { get; set; }
        public T Data { get; set; }
    }

    public sealed class StockSummary
    {
        public string Code { get; set; }
        public string Name { get; set; }
        public double? Price { get; set; }
        public double? ChangePercent { get; set; }
        public double? TotalAmount { get; set; }
        public double? Volume { get; set; }
        public double? TurnoverRate { get; set; }
        public double? VolumeRatio { get; set; }
    }

    public sealed class MainFundSummary
    {
        public double? MainBuy { get; set; }
        public double? MainSell { get; set; }
        public double? NetAmount { get; set; }
        public int OrderCount { get; set; }
    }

    public sealed class LimitUpContext
    {
        public double? SealAmount { get; set; }
        public double? SealVolume { get; set; }
        public int? OpenCount { get; set; }
        public string HighDays { get; set; }
        public double? SuccessRate { get; set; }
        public double? TurnoverRate { get; set; }
        public string ReasonType { get; set; }
        public string FirstLimitTime { get; set; }
        public string LastLimitTime { get; set; }
    }

    public sealed class PricePoint
    {
        public DateTime Time { get; set; }
        public double ChangePercent { get; set; }
    }

    public sealed class MinuteTurnoverPoint
    {
        public DateTime Time { get; set; }
        public double Price { get; set; }
        public double CumulativeVolume { get; set; }
        public double CumulativeAmount { get; set; }
    }

    public sealed class MarketSnapshot
    {
        public MarketSnapshot(
            string stockCode,
            StockSummary stock,
            MainFundSummary mainFunds,
            LimitUpContext limitUp,
            IReadOnlyList<BigOrderItem> orders,
            IReadOnlyList<PricePoint> prices,
            DataFreshness bigOrderFreshness,
            DataFreshness quoteFreshness,
            DataFreshness limitUpFreshness,
            DateTime bigOrderFetchedAt,
            DateTime refreshedAt,
            IReadOnlyList<string> issues = null,
            MarketSourceTransports transports = null,
            DateTime? bigOrderSessionDate = null)
            : this(
                stockCode, stock, mainFunds, limitUp, orders, prices,
                new MinuteTurnoverPoint[0], bigOrderFreshness, quoteFreshness,
                DataFreshness.Missing, limitUpFreshness, bigOrderFetchedAt, refreshedAt, issues, transports,
                bigOrderSessionDate)
        {
        }

        public MarketSnapshot(
            string stockCode,
            StockSummary stock,
            MainFundSummary mainFunds,
            LimitUpContext limitUp,
            IReadOnlyList<BigOrderItem> orders,
            IReadOnlyList<PricePoint> prices,
            IReadOnlyList<MinuteTurnoverPoint> minuteTurnover,
            DataFreshness bigOrderFreshness,
            DataFreshness quoteFreshness,
            DataFreshness minuteTurnoverFreshness,
            DataFreshness limitUpFreshness,
            DateTime bigOrderFetchedAt,
            DateTime refreshedAt,
            IReadOnlyList<string> issues = null,
            MarketSourceTransports transports = null,
            DateTime? bigOrderSessionDate = null)
        {
            StockCode = stockCode;
            Stock = stock;
            MainFunds = mainFunds;
            LimitUp = limitUp;
            Orders = orders;
            Prices = prices;
            MinuteTurnover = minuteTurnover ?? new MinuteTurnoverPoint[0];
            BigOrderFreshness = bigOrderFreshness;
            QuoteFreshness = quoteFreshness;
            MinuteTurnoverFreshness = minuteTurnoverFreshness;
            LimitUpFreshness = limitUpFreshness;
            BigOrderFetchedAt = bigOrderFetchedAt;
            RefreshedAt = refreshedAt;
            Issues = issues ?? new string[0];
            Transports = transports ?? new MarketSourceTransports
            {
                BigOrder = DefaultTransport(bigOrderFreshness),
                Quote = DefaultTransport(quoteFreshness),
                Minute = DefaultTransport(minuteTurnoverFreshness),
                LimitUp = DefaultTransport(limitUpFreshness),
            };
            BigOrderSessionDate = bigOrderSessionDate?.Date;
        }

        public string StockCode { get; private set; }
        public StockSummary Stock { get; private set; }
        public MainFundSummary MainFunds { get; private set; }
        public LimitUpContext LimitUp { get; private set; }
        public IReadOnlyList<BigOrderItem> Orders { get; private set; }
        public IReadOnlyList<PricePoint> Prices { get; private set; }
        public IReadOnlyList<MinuteTurnoverPoint> MinuteTurnover { get; private set; }
        public DataFreshness BigOrderFreshness { get; private set; }
        public DataFreshness QuoteFreshness { get; private set; }
        public DataFreshness MinuteTurnoverFreshness { get; private set; }
        public DataFreshness LimitUpFreshness { get; private set; }
        public DateTime BigOrderFetchedAt { get; private set; }
        public DateTime RefreshedAt { get; private set; }
        public IReadOnlyList<string> Issues { get; private set; }
        public MarketSourceTransports Transports { get; private set; }
        public DateTime? BigOrderSessionDate { get; private set; }

        private static DataTransport DefaultTransport(DataFreshness freshness)
        {
            if (freshness == DataFreshness.Failed) return DataTransport.Failed;
            if (freshness == DataFreshness.Missing) return DataTransport.Missing;
            if (freshness == DataFreshness.Stale) return DataTransport.Stale;
            return DataTransport.Direct;
        }
    }
}
