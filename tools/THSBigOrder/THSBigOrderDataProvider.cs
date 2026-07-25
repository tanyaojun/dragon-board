using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using THSBigOrder.Models;
using THSBigOrder.Parsing;
using THSBigOrder.DataSources;
using THSBigOrder.Analytics;

namespace THSBigOrder
{
    public enum BigOrderDataSource
    {
        Ths,
        Longhu,
    }

    public class THSBigOrderDataProvider : IMarketSnapshotProvider, IDisposable
    {
        private readonly HttpClient _httpClient;
        private readonly HttpClient _longhuHttpClient;
        private readonly bool _ownsHttpClient;
        private readonly bool _bigOrderProxyPrimary;
        private readonly IMarketSourceClient<BigOrderSourceData> _thsBigOrderSource;
        private readonly IMarketSourceClient<BigOrderSourceData> _longhuBigOrderSource;
        private readonly IMarketSourceClient<StockSummary> _quoteSource;
        private readonly IMarketSourceClient<IReadOnlyList<MinuteTurnoverPoint>> _minuteSource;
        private readonly IMarketSourceClient<LimitUpSourceData> _limitUpSource;
        private readonly Dictionary<string, SourceLoadResult<BigOrderSourceData>> _bigOrderCache =
            new Dictionary<string, SourceLoadResult<BigOrderSourceData>>();
        private readonly Dictionary<string, SourceLoadResult<StockSummary>> _quoteCache =
            new Dictionary<string, SourceLoadResult<StockSummary>>();
        private readonly Dictionary<string, SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>> _minuteCache =
            new Dictionary<string, SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>>();
        private readonly Dictionary<string, SourceLoadResult<LimitUpSourceData>> _limitCache =
            new Dictionary<string, SourceLoadResult<LimitUpSourceData>>();

        public BigOrderDataSource DataSource { get; set; } = BigOrderDataSource.Ths;

        public THSBigOrderDataProvider(
            HttpClient httpClient = null,
            string baseUrl = "http://127.0.0.1:3000",
            string thsBaseUrl = "http://127.0.0.1:8000",
            string bridgeBaseUrl = "http://127.0.0.1:8765")
        {
            _ownsHttpClient = httpClient == null;
            _bigOrderProxyPrimary = true;
            _httpClient = httpClient ?? new HttpClient();
            _httpClient.Timeout = TimeSpan.FromSeconds(15);
            _longhuHttpClient = httpClient ?? new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
            var proxyBase = (baseUrl ?? "").TrimEnd('/');
            var thsBase = (thsBaseUrl ?? "").TrimEnd('/');
            var bridgeBase = (bridgeBaseUrl ?? "").TrimEnd('/');
            var parser = new ThsPayloadParser();
            _thsBigOrderSource = new ThsBigOrderSourceClient(_httpClient, thsBase, parser);
            _longhuBigOrderSource = new LonghuBigOrderSourceClient(_longhuHttpClient, proxyBase, parser);
            _quoteSource = new SinaQuoteSourceClient(_httpClient, proxyBase, parser);
            _minuteSource = new TdxMinuteSourceClient(_httpClient, bridgeBase, parser);
            _limitUpSource = new ThsLimitUpSourceClient(_httpClient, proxyBase, parser);
        }

        internal THSBigOrderDataProvider(
            IMarketSourceClient<BigOrderSourceData> thsBigOrderSource,
            IMarketSourceClient<BigOrderSourceData> longhuBigOrderSource,
            IMarketSourceClient<StockSummary> quoteSource,
            IMarketSourceClient<IReadOnlyList<MinuteTurnoverPoint>> minuteSource,
            IMarketSourceClient<LimitUpSourceData> limitUpSource)
        {
            _bigOrderProxyPrimary = false;
            _thsBigOrderSource = thsBigOrderSource;
            _longhuBigOrderSource = longhuBigOrderSource;
            _quoteSource = quoteSource;
            _minuteSource = minuteSource;
            _limitUpSource = limitUpSource;
        }

        internal THSBigOrderDataProvider(
            IMarketSourceClient<BigOrderSourceData> bigOrderSource,
            IMarketSourceClient<StockSummary> quoteSource,
            IMarketSourceClient<IReadOnlyList<MinuteTurnoverPoint>> minuteSource,
            IMarketSourceClient<LimitUpSourceData> limitUpSource)
            : this(bigOrderSource, bigOrderSource, quoteSource, minuteSource, limitUpSource)
        {
        }

        public async Task<MarketSnapshot> LoadSnapshotAsync(string stockCode, CancellationToken cancellationToken)
        {
            if (string.IsNullOrWhiteSpace(stockCode) || stockCode.Length != 6 || !stockCode.All(char.IsDigit))
                throw new ArgumentException("stockCode 必须是六位数字", nameof(stockCode));

            var selectedSource = DataSource;
            var useLonghu = selectedSource == BigOrderDataSource.Longhu;
            var selectedBigOrderSource = useLonghu ? _longhuBigOrderSource : _thsBigOrderSource;
            var bigTask = _bigOrderProxyPrimary
                ? LoadProxyPrimaryAsync(selectedBigOrderSource, stockCode, cancellationToken)
                : LoadDirectFirstAsync(selectedBigOrderSource, stockCode, cancellationToken);
            var summaryTask = useLonghu
                ? (_bigOrderProxyPrimary
                    ? LoadProxyPrimaryAsync(_thsBigOrderSource, stockCode, cancellationToken)
                    : LoadDirectFirstAsync(_thsBigOrderSource, stockCode, cancellationToken))
                : null;
            var quoteTask = LoadDirectFirstAsync(_quoteSource, stockCode, cancellationToken);
            var minuteTask = LoadDirectFirstAsync(_minuteSource, stockCode, cancellationToken);
            var limitTask = LoadDirectFirstAsync(_limitUpSource, stockCode, cancellationToken);
            var tasks = new List<Task> { bigTask, quoteTask, minuteTask, limitTask };
            if (summaryTask != null) tasks.Add(summaryTask);
            await Task.WhenAll(tasks).ConfigureAwait(false);

            var big = bigTask.Result;
            var summary = summaryTask == null
                ? CopyResult(big)
                : summaryTask.Result;
            var quote = quoteTask.Result;
            var minute = minuteTask.Result;
            var limit = limitTask.Result;
            var selectedCacheKey = (useLonghu ? "longhu-orders:" : "ths-orders:") + stockCode;
            var thsCacheKey = "ths-summary:" + stockCode;
            var thsSessionDate = (useLonghu ? summary.Data?.SessionDate : big.Data?.SessionDate) ??
                CachedSessionDate(_bigOrderCache, useLonghu ? thsCacheKey : selectedCacheKey);
            var selectedSessionDate = big.Data?.SessionDate ?? thsSessionDate ??
                CachedSessionDate(_bigOrderCache, selectedCacheKey);
            ApplyBigOrderStaleFallback(
                _bigOrderCache,
                selectedCacheKey,
                big,
                selectedSessionDate,
                BigOrderLastGoodMaxAge(DateTime.Now, selectedSessionDate));
            ApplyBigOrderStaleFallback(
                _bigOrderCache,
                thsCacheKey,
                summary,
                thsSessionDate,
                BigOrderLastGoodMaxAge(DateTime.Now, thsSessionDate));
            ApplyStaleFallback(_quoteCache, stockCode, quote);
            ApplyMinuteStaleFallback(_minuteCache, stockCode, minute, thsSessionDate, DateTime.Now);
            ApplyStaleFallback(_limitCache, stockCode, limit);

            var bigData = MergeBigOrderData(big.Data, summary.Data);
            var stock = quote.Data ?? new StockSummary { Code = stockCode };
            var limitContext = limit.Data?.Context ?? new LimitUpContext();
            if (string.IsNullOrWhiteSpace(stock.Name)) stock.Name = bigData.StockFallback?.Name ?? "";
            if (!stock.Price.HasValue) stock.Price = bigData.StockFallback?.Price;
            if (!stock.TurnoverRate.HasValue) stock.TurnoverRate = limitContext.TurnoverRate;
            var snapshot = new MarketSnapshot(
                stockCode,
                stock,
                bigData.MainFunds ?? new MainFundSummary(),
                limitContext,
                bigData.Orders ?? new BigOrderItem[0],
                bigData.Prices ?? new PricePoint[0],
                minute.Data ?? new MinuteTurnoverPoint[0],
                big.Freshness,
                quote.Freshness,
                minute.Freshness,
                limit.Freshness,
                big.FetchedAt == default(DateTime) ? DateTime.Now : big.FetchedAt,
                DateTime.Now,
                new[] { big.Error, summary?.Error, quote.Error, minute.Error, limit.Error }
                    .Where(value => !string.IsNullOrWhiteSpace(value)).ToArray(),
                new MarketSourceTransports
                {
                    BigOrder = big.Transport,
                    Quote = quote.Transport,
                    Minute = minute.Transport,
                    LimitUp = limit.Transport,
                },
                big.Data?.SessionDate);
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

        // 当前权威会话最多 5 分钟；历史完成会话最多 7 天。
        internal static TimeSpan BigOrderLastGoodMaxAge(
            DateTime now,
            DateTime? expectedSessionDate)
        {
            return expectedSessionDate.HasValue && expectedSessionDate.Value.Date == now.Date
                ? TimeSpan.FromMinutes(5)
                : TimeSpan.FromDays(7);
        }

        private static async Task<SourceLoadResult<T>> LoadProxyPrimaryAsync<T>(
            IMarketSourceClient<T> source, string stockCode, CancellationToken cancellationToken)
        {
            try { return await source.LoadProxyAsync(stockCode, cancellationToken).ConfigureAwait(false); }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
            catch (Exception error)
            {
                return new SourceLoadResult<T>
                {
                    Freshness = DataFreshness.Failed,
                    Transport = DataTransport.Failed,
                    Error = error.Message,
                };
            }
        }

        private static BigOrderSourceData MergeBigOrderData(
            BigOrderSourceData orders,
            BigOrderSourceData summary)
        {
            orders = orders ?? new BigOrderSourceData();
            summary = summary ?? new BigOrderSourceData();
            return new BigOrderSourceData
            {
                StockFallback = summary.StockFallback ?? new StockSummary(),
                MainFunds = summary.MainFunds ?? new MainFundSummary(),
                Orders = orders.Orders ?? new BigOrderItem[0],
                Prices = summary.Prices ?? new PricePoint[0],
                SessionDate = orders.SessionDate,
            };
        }

        private static SourceLoadResult<T> CopyResult<T>(SourceLoadResult<T> value)
        {
            return new SourceLoadResult<T>
            {
                Data = value.Data,
                Freshness = value.Freshness,
                Transport = value.Transport,
                FetchedAt = value.FetchedAt,
                Error = value.Error,
            };
        }

        private static DateTime? InferMinuteSessionDate(
            IReadOnlyList<MinuteTurnoverPoint> points)
        {
            var dates = (points ?? new MinuteTurnoverPoint[0])
                .Where(point => point != null && point.Time != default(DateTime))
                .Select(point => point.Time.Date)
                .Distinct()
                .ToArray();
            return dates.Length == 1 ? (DateTime?)dates[0] : null;
        }

        private static DateTime? CachedSessionDate(
            IDictionary<string, SourceLoadResult<BigOrderSourceData>> cache,
            string key)
        {
            return cache.TryGetValue(key, out var cached)
                ? cached.Data?.SessionDate
                : null;
        }

        private static void ApplyBigOrderStaleFallback(
            IDictionary<string, SourceLoadResult<BigOrderSourceData>> cache,
            string key,
            SourceLoadResult<BigOrderSourceData> result,
            DateTime? expectedSessionDate,
            TimeSpan maxAge)
        {
            if (result == null) return;
            if (result.Transport == DataTransport.Direct ||
                result.Transport == DataTransport.ProxyPrimary ||
                result.Transport == DataTransport.ProxyFallback)
            {
                if (result.Data?.SessionDate.HasValue == true)
                    CacheSuccessful(cache, key, result);
                return;
            }
            if (result.Transport == DataTransport.Stale)
            {
                var validUpstreamStale =
                    expectedSessionDate.HasValue &&
                    result.Data?.SessionDate.HasValue == true &&
                    result.Data.SessionDate.Value.Date == expectedSessionDate.Value.Date &&
                    DateTime.Now - result.FetchedAt <= maxAge;
                if (validUpstreamStale) return;
                result.Data = null;
                result.Freshness = DataFreshness.Failed;
                result.Transport = DataTransport.Failed;
                result.Error = "THS stale data expired or belongs to another session";
            }
            SourceLoadResult<BigOrderSourceData> cached;
            if (result.Transport != DataTransport.Failed ||
                !expectedSessionDate.HasValue ||
                !cache.TryGetValue(key, out cached) ||
                cached.Data?.SessionDate.HasValue != true ||
                cached.Data.SessionDate.Value.Date != expectedSessionDate.Value.Date ||
                DateTime.Now - cached.FetchedAt > maxAge)
                return;
            result.Data = cached.Data;
            result.Freshness = DataFreshness.Stale;
            result.Transport = DataTransport.Stale;
            result.FetchedAt = cached.FetchedAt;
        }

        private static void ApplyStaleFallback<T>(
            IDictionary<string, SourceLoadResult<T>> cache,
            string key,
            SourceLoadResult<T> result,
            TimeSpan? maxAge = null)
        {
            if (result == null) return;
            if (result.Transport == DataTransport.Direct ||
                result.Transport == DataTransport.ProxyPrimary ||
                result.Transport == DataTransport.ProxyFallback)
            {
                CacheSuccessful(cache, key, result);
                return;
            }
            SourceLoadResult<T> cached;
            if (result.Transport != DataTransport.Failed || !cache.TryGetValue(key, out cached)) return;
            if (maxAge.HasValue &&
                DateTime.Now - cached.FetchedAt > maxAge.Value)
                return;
            result.Data = cached.Data;
            result.Freshness = DataFreshness.Stale;
            result.Transport = DataTransport.Stale;
            result.FetchedAt = cached.FetchedAt;
        }

        private static void ApplyMinuteStaleFallback(
            IDictionary<string, SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>> cache,
            string key,
            SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>> result,
            DateTime? expectedSessionDate,
            DateTime now)
        {
            if (result == null) return;
            if (result.Transport == DataTransport.Direct ||
                result.Transport == DataTransport.ProxyPrimary ||
                result.Transport == DataTransport.ProxyFallback)
            {
                var resultDate = InferMinuteSessionDate(result.Data);
                if (expectedSessionDate.HasValue &&
                    resultDate.HasValue &&
                    resultDate.Value.Date == expectedSessionDate.Value.Date)
                {
                    CacheSuccessful(cache, key, result);
                    return;
                }
                result.Data = new MinuteTurnoverPoint[0];
                result.Freshness = DataFreshness.Failed;
                result.Transport = DataTransport.Failed;
                result.Error = "TDX 分时日期与权威交易日期不一致";
            }
            SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>> cached;
            if (result.Transport != DataTransport.Failed ||
                !expectedSessionDate.HasValue ||
                !cache.TryGetValue(key, out cached)) return;
            var cachedDate = InferMinuteSessionDate(cached.Data);
            if (!cachedDate.HasValue || cachedDate.Value.Date != expectedSessionDate.Value.Date) return;
            var maxAge = expectedSessionDate.Value.Date == now.Date
                ? TimeSpan.FromMinutes(5)
                : TimeSpan.FromDays(7);
            if (now - cached.FetchedAt > maxAge) return;
            result.Data = cached.Data;
            result.Freshness = DataFreshness.Stale;
            result.Transport = DataTransport.Stale;
            result.FetchedAt = cached.FetchedAt;
        }

        private static void CacheSuccessful<T>(
            IDictionary<string, SourceLoadResult<T>> cache,
            string key,
            SourceLoadResult<T> result)
        {
            if (result == null ||
                result.Transport != DataTransport.Direct &&
                result.Transport != DataTransport.ProxyPrimary &&
                result.Transport != DataTransport.ProxyFallback) return;
            cache[key] = new SourceLoadResult<T>
            {
                Data = result.Data,
                Freshness = result.Freshness,
                Transport = result.Transport,
                FetchedAt = result.FetchedAt,
            };
        }

        public void CalculateMarkers(List<BigOrderItem> data)
        {
            new BigOrderEventDetector().Apply(data);
        }

        public void CalculateMarkers(List<BigOrderItem> data, string stockCode)
        {
            new BigOrderEventDetector().Apply(data, stockCode);
        }

        public void Dispose()
        {
            if (_ownsHttpClient) _httpClient?.Dispose();
            if (_ownsHttpClient && !ReferenceEquals(_httpClient, _longhuHttpClient))
                _longhuHttpClient?.Dispose();
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
