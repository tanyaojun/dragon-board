using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using THSBigOrder.Models;
using THSBigOrder.Parsing;
using THSBigOrder.DataSources;

namespace THSBigOrder
{
    public class THSBigOrderDataProvider : IMarketSnapshotProvider, IDisposable
    {
        private readonly HttpClient _httpClient;
        private readonly bool _ownsHttpClient;
        private readonly IMarketSourceClient<BigOrderSourceData> _bigOrderSource;
        private readonly IMarketSourceClient<StockSummary> _quoteSource;
        private readonly IMarketSourceClient<IReadOnlyList<MinuteTurnoverPoint>> _minuteSource;
        private readonly IMarketSourceClient<LimitUpSourceData> _limitUpSource;
        private readonly Dictionary<string, MarketSnapshot> _lastGood = new Dictionary<string, MarketSnapshot>();

        public THSBigOrderDataProvider(HttpClient httpClient = null, string baseUrl = "http://127.0.0.1:3000")
        {
            _ownsHttpClient = httpClient == null;
            _httpClient = httpClient ?? new HttpClient();
            _httpClient.Timeout = TimeSpan.FromSeconds(15);
            var proxyBase = (baseUrl ?? "").TrimEnd('/');
            var parser = new ThsPayloadParser();
            _bigOrderSource = new ThsBigOrderSourceClient(_httpClient, proxyBase, parser);
            _quoteSource = new SinaQuoteSourceClient(_httpClient, proxyBase, parser);
            _minuteSource = new TencentMinuteSourceClient(_httpClient, proxyBase, parser);
            _limitUpSource = new ThsLimitUpSourceClient(_httpClient, proxyBase, parser);
        }

        internal THSBigOrderDataProvider(
            IMarketSourceClient<BigOrderSourceData> bigOrderSource,
            IMarketSourceClient<StockSummary> quoteSource,
            IMarketSourceClient<IReadOnlyList<MinuteTurnoverPoint>> minuteSource,
            IMarketSourceClient<LimitUpSourceData> limitUpSource)
        {
            _bigOrderSource = bigOrderSource;
            _quoteSource = quoteSource;
            _minuteSource = minuteSource;
            _limitUpSource = limitUpSource;
        }

        public async Task<MarketSnapshot> LoadSnapshotAsync(string stockCode, CancellationToken cancellationToken)
        {
            if (string.IsNullOrWhiteSpace(stockCode) || stockCode.Length != 6 || !stockCode.All(char.IsDigit))
                throw new ArgumentException("stockCode 必须是六位数字", nameof(stockCode));

            var bigTask = LoadDirectFirstAsync(_bigOrderSource, stockCode, cancellationToken);
            var quoteTask = LoadDirectFirstAsync(_quoteSource, stockCode, cancellationToken);
            var minuteTask = LoadDirectFirstAsync(_minuteSource, stockCode, cancellationToken);
            var limitTask = LoadDirectFirstAsync(_limitUpSource, stockCode, cancellationToken);
            await Task.WhenAll((Task)bigTask, quoteTask, minuteTask, limitTask).ConfigureAwait(false);

            var big = bigTask.Result;
            var quote = quoteTask.Result;
            var minute = minuteTask.Result;
            var limit = limitTask.Result;
            MarketSnapshot cached;
            _lastGood.TryGetValue(stockCode, out cached);
            ApplyStaleFallback(cached, big, quote, minute, limit);

            var bigData = big.Data ?? new BigOrderSourceData();
            var stock = quote.Data ?? new StockSummary { Code = stockCode };
            if (string.IsNullOrWhiteSpace(stock.Name)) stock.Name = bigData.StockFallback?.Name ?? "";
            if (!stock.Price.HasValue) stock.Price = bigData.StockFallback?.Price;
            var snapshot = new MarketSnapshot(
                stockCode,
                stock,
                bigData.MainFunds ?? new MainFundSummary(),
                limit.Data?.Context ?? new LimitUpContext(),
                bigData.Orders ?? new BigOrderItem[0],
                bigData.Prices ?? new PricePoint[0],
                minute.Data ?? new MinuteTurnoverPoint[0],
                big.Freshness,
                quote.Freshness,
                minute.Freshness,
                limit.Freshness,
                big.FetchedAt == default(DateTime) ? DateTime.Now : big.FetchedAt,
                DateTime.Now,
                new[] { big.Error, quote.Error, minute.Error, limit.Error }
                    .Where(value => !string.IsNullOrWhiteSpace(value)).ToArray(),
                new MarketSourceTransports
                {
                    BigOrder = big.Transport,
                    Quote = quote.Transport,
                    Minute = minute.Transport,
                    LimitUp = limit.Transport,
                });
            _lastGood[stockCode] = snapshot;
            return snapshot;
        }

        public async Task<List<BigOrderItem>> GetAllDayDataAsync(string stockCode, int money = 0)
        {
            var snapshot = await LoadSnapshotAsync(stockCode, CancellationToken.None).ConfigureAwait(false);
            return snapshot.Orders.ToList();
        }

        public async Task<List<BigOrderItem>> GetBigOrderDataAsync(string stockCode, int limit = 100, int money = 0)
        {
            return (await GetAllDayDataAsync(stockCode, money).ConfigureAwait(false)).Take(limit).ToList();
        }

        public async Task<StockInfo> GetStockInfoAsync(string stockCode)
        {
            var snapshot = await LoadSnapshotAsync(stockCode, CancellationToken.None).ConfigureAwait(false);
            return new StockInfo
            {
                Code = stockCode,
                Name = snapshot.Stock.Name,
                Price = snapshot.Stock.Price ?? 0,
                Change = snapshot.Stock.ChangePercent ?? 0,
                TurnoverRate = snapshot.Stock.TurnoverRate ?? 0,
                VolumeRatio = snapshot.Stock.VolumeRatio ?? 0,
                TotalAmount = snapshot.Stock.TotalAmount ?? 0,
            };
        }

        private static async Task<SourceLoadResult<T>> LoadDirectFirstAsync<T>(
            IMarketSourceClient<T> source, string stockCode, CancellationToken cancellationToken)
        {
            try { return await source.LoadDirectAsync(stockCode, cancellationToken).ConfigureAwait(false); }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
            catch (Exception directError)
            {
                try { return await source.LoadProxyAsync(stockCode, cancellationToken).ConfigureAwait(false); }
                catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
                catch (Exception proxyError)
                {
                    return new SourceLoadResult<T>
                    {
                        Freshness = DataFreshness.Failed,
                        Transport = DataTransport.Failed,
                        Error = directError.Message + " | " + proxyError.Message,
                    };
                }
            }
        }

        private static void ApplyStaleFallback(
            MarketSnapshot cached,
            SourceLoadResult<BigOrderSourceData> big,
            SourceLoadResult<StockSummary> quote,
            SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>> minute,
            SourceLoadResult<LimitUpSourceData> limit)
        {
            if (cached == null) return;
            if (big.Transport == DataTransport.Failed && cached.Orders.Count > 0)
            {
                big.Data = new BigOrderSourceData
                {
                    StockFallback = cached.Stock,
                    MainFunds = cached.MainFunds,
                    Orders = cached.Orders,
                    Prices = cached.Prices,
                };
                big.Freshness = DataFreshness.Stale;
                big.Transport = DataTransport.Stale;
                big.FetchedAt = cached.BigOrderFetchedAt;
            }
            if (quote.Transport == DataTransport.Failed && cached.Stock != null)
            {
                quote.Data = cached.Stock;
                quote.Freshness = DataFreshness.Stale;
                quote.Transport = DataTransport.Stale;
            }
            if (minute.Transport == DataTransport.Failed && cached.MinuteTurnover.Count > 0)
            {
                minute.Data = cached.MinuteTurnover;
                minute.Freshness = DataFreshness.Stale;
                minute.Transport = DataTransport.Stale;
            }
            if (limit.Transport == DataTransport.Failed && cached.LimitUp != null)
            {
                limit.Data = new LimitUpSourceData
                {
                    Found = cached.LimitUpFreshness != DataFreshness.Missing,
                    Context = cached.LimitUp,
                };
                limit.Freshness = DataFreshness.Stale;
                limit.Transport = DataTransport.Stale;
            }
        }

        public void CalculateMarkers(List<BigOrderItem> data)
        {
            if (data == null || data.Count == 0) return;
            var sorted = data.OrderBy(item => item.Time).ToList();
            double previousSellAverage = 0;
            double previousBuyAverage = 0;
            for (var index = 0; index < sorted.Count; index++)
            {
                var row = sorted[index];
                row.FundMarker = "";
                row.BuyMarker = "";
                var date = row.Time.Date;
                var tradeTime =
                    (row.Time >= date.AddHours(9).AddMinutes(30) && row.Time <= date.AddHours(11).AddMinutes(30)) ||
                    (row.Time >= date.AddHours(13) && row.Time <= date.AddHours(15));
                if (!tradeTime) continue;

                var recentSix = sorted.Take(index).Where(item => item.Time >= row.Time.AddSeconds(-6)).ToList();
                var recentFifty = sorted.Take(index).Where(item => item.Time >= row.Time.AddSeconds(-50)).ToList();
                var nextSix = sorted.Skip(index).Where(item => item.Time <= row.Time.AddSeconds(6)).ToList();
                if (recentFifty.Count > 0)
                {
                    var average = recentFifty.Average(item => item.Amount / 10000d);
                    var buy = row.Type == 2 ? row.Amount / 10000d : 0;
                    var sell = row.Type == 4 ? row.Amount / 10000d : 0;
                    if (buy >= 300 && buy / average > 2) row.FundMarker = "点火";
                    if (sell >= 300 && sell / average > 2) row.FundMarker = "砸盘";
                }
                if (nextSix.Count > 0)
                {
                    var sellAverage = nextSix.Average(item => item.Type == 4 || item.Type == 3 ? item.Amount / 10000d : 0);
                    var buyAverage = nextSix.Average(item => item.Type == 2 || item.Type == 1 ? item.Amount / 10000d : 0);
                    var support = index > 0 && sellAverage > previousSellAverage && sellAverage > 300 ? "承接好" : "";
                    var hasIgnite = recentSix.Any(item => item.FundMarker == "点火");
                    row.BuyMarker = index > 0 && buyAverage >= previousBuyAverage && buyAverage > 100 && hasIgnite ? "买活跃" : support;
                    previousSellAverage = sellAverage;
                    previousBuyAverage = buyAverage;
                }
            }
        }

        public void Dispose()
        {
            if (_ownsHttpClient) _httpClient.Dispose();
        }

    }

    public class BigOrderItem
    {
        public int Type { get; set; }
        public double Volume { get; set; }
        public double Amount { get; set; }
        public double Price { get; set; }
        public DateTime Time { get; set; }
        public string FundMarker { get; set; } = "";
        public string BuyMarker { get; set; } = "";
        public string TypeName => Type == 1 ? "被动卖" : Type == 2 ? "主动买" : Type == 3 ? "被动买" : Type == 4 ? "主动卖" : "未知";
        public string AmountStr => (Amount / 10000).ToString("F0") + "万";
        public string TimeStr => Time.ToString("HH:mm:ss");
        public bool IsBuy => Type == 2 || Type == 3;
        public bool IsSell => Type == 1 || Type == 4;
    }

    public class StockInfo
    {
        public string Code { get; set; }
        public string Name { get; set; }
        public double Price { get; set; }
        public double Change { get; set; }
        public double TurnoverRate { get; set; }
        public double VolumeRatio { get; set; }
        public double High { get; set; }
        public double Low { get; set; }
        public double Open { get; set; }
        public double PreClose { get; set; }
        public double TotalAmount { get; set; }
    }
}
