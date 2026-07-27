using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using THSBigOrder.Models;

namespace THSBigOrder.DataSources
{
    public enum DataTransport { Direct, ProxyPrimary, ProxyFallback, Stale, Missing, Failed }

    public sealed class SourceLoadResult<T>
    {
        public T Data { get; set; }
        public DataFreshness Freshness { get; set; }
        public DataTransport Transport { get; set; }
        public DateTime FetchedAt { get; set; }
        public string Error { get; set; }
    }

    public sealed class BigOrderSourceData
    {
        public DateTime? SessionDate { get; set; }
        public StockSummary StockFallback { get; set; } = new StockSummary();
        public MainFundSummary MainFunds { get; set; } = new MainFundSummary();
        public IReadOnlyList<BigOrderItem> Orders { get; set; } = new BigOrderItem[0];
        public IReadOnlyList<PricePoint> Prices { get; set; } = new PricePoint[0];
    }

    public sealed class LimitUpSourceData
    {
        public bool Found { get; set; }
        public LimitUpContext Context { get; set; } = new LimitUpContext();
    }

    public sealed class MarketSourceTransports
    {
        public DataTransport BigOrder { get; set; }
        public DataTransport Quote { get; set; }
        public DataTransport Minute { get; set; }
        public DataTransport LimitUp { get; set; }
        public string Summary => SourceStatusFormatter.Format(this);
    }

    internal static class SourceStatusFormatter
    {
        public static string Format(MarketSourceTransports value)
        {
            var rows = new[]
            {
                new { Name = "大单", Value = value.BigOrder },
                new { Name = "行情", Value = value.Quote },
                new { Name = "分时", Value = value.Minute },
                new { Name = "涨停", Value = value.LimitUp },
            };
            var failed = rows.Where(x => x.Value == DataTransport.Failed || x.Value == DataTransport.Missing)
                .Select(x => x.Name).ToArray();
            var stale = rows.Where(x => x.Value == DataTransport.Stale).Select(x => x.Name).ToArray();
            if (failed.Length > 0)
            {
                var unavailable = "数据不可用: " + string.Join("/", failed);
                return stale.Length > 0 ? unavailable + "; 数据陈旧: " + string.Join("/", stale) : unavailable;
            }
            if (stale.Length > 0) return "数据陈旧: " + string.Join("/", stale);
            var proxy = rows.Where(x => x.Value == DataTransport.ProxyFallback).Select(x => x.Name).ToArray();
            if (proxy.Length > 0) return "备用通道: " + string.Join("/", proxy);
            var primary = rows.Where(x => x.Value == DataTransport.ProxyPrimary).Select(x => x.Name).ToArray();
            return primary.Length > 0 ? "代理通道: " + string.Join("/", primary) : "直连";
        }
    }

    internal interface IMarketSourceClient<T>
    {
        Task<SourceLoadResult<T>> LoadDirectAsync(string stockCode, CancellationToken cancellationToken);
        Task<SourceLoadResult<T>> LoadProxyAsync(string stockCode, CancellationToken cancellationToken);
    }
}
