using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using THSBigOrder.Models;
using THSBigOrder.Parsing;

namespace THSBigOrder
{
    public class THSBigOrderDataProvider : IDisposable
    {
        private readonly HttpClient _httpClient;
        private readonly bool _ownsHttpClient;
        private readonly string _baseUrl;
        private readonly ThsPayloadParser _parser = new ThsPayloadParser();
        private readonly Dictionary<string, MarketSnapshot> _lastGood = new Dictionary<string, MarketSnapshot>();

        public THSBigOrderDataProvider(HttpClient httpClient = null, string baseUrl = "http://127.0.0.1:3000")
        {
            _ownsHttpClient = httpClient == null;
            _httpClient = httpClient ?? new HttpClient();
            _httpClient.Timeout = TimeSpan.FromSeconds(15);
            _baseUrl = (baseUrl ?? "").TrimEnd('/');
        }

        public async Task<MarketSnapshot> LoadSnapshotAsync(string stockCode, CancellationToken cancellationToken)
        {
            if (string.IsNullOrWhiteSpace(stockCode) || stockCode.Length != 6 || !stockCode.All(char.IsDigit))
                throw new ArgumentException("stockCode 必须是六位数字", nameof(stockCode));

            var bigTask = GetJsonAsync("/api/big-order/ths-detail?stockCode=" + stockCode, cancellationToken);
            var quoteTask = TryGetJsonAsync("/api/quotes/tencent?codes=" + stockCode, cancellationToken);
            var limitTask = TryGetJsonAsync("/api/limitup/10jqka", cancellationToken);
            try
            {
                await Task.WhenAll((Task)bigTask, quoteTask, limitTask).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw;
            }
            catch
            {
                // 主数据错误在下方按股票代码执行 stale 回退；可选请求已各自封装错误。
            }

            JObject bigOrder;
            try
            {
                bigOrder = await bigTask.ConfigureAwait(false);
                if (bigOrder.Value<bool?>("ok") != true)
                    throw new HttpRequestException((string)bigOrder["errorCode"] ?? "big-order degraded");
            }
            catch (Exception) when (!cancellationToken.IsCancellationRequested)
            {
                MarketSnapshot cached;
                if (_lastGood.TryGetValue(stockCode, out cached)) return WithBigOrderFreshness(cached, DataFreshness.Stale);
                return FailedSnapshot(stockCode, quoteTask.Result, limitTask.Result);
            }

            var quote = quoteTask.Result;
            var limitUp = limitTask.Result;
            var snapshot = _parser.ParseSnapshot(
                stockCode,
                bigOrder,
                quote.Data ?? new JObject(),
                limitUp.Data ?? new JObject(),
                DateTime.Now);
            snapshot = WithOptionalFreshness(
                snapshot,
                quote.Error == null ? snapshot.QuoteFreshness : DataFreshness.Failed,
                limitUp.Error == null ? snapshot.LimitUpFreshness : DataFreshness.Failed);
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

        private async Task<JObject> GetJsonAsync(string path, CancellationToken cancellationToken)
        {
            using (var response = await _httpClient.GetAsync(_baseUrl + path, cancellationToken).ConfigureAwait(false))
            {
                var json = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                response.EnsureSuccessStatusCode();
                return JObject.Parse(json);
            }
        }

        private async Task<RequestResult> TryGetJsonAsync(string path, CancellationToken cancellationToken)
        {
            try { return new RequestResult { Data = await GetJsonAsync(path, cancellationToken).ConfigureAwait(false) }; }
            catch (OperationCanceledException) { throw; }
            catch (Exception error) { return new RequestResult { Error = error }; }
        }

        private MarketSnapshot FailedSnapshot(string stockCode, RequestResult quote, RequestResult limitUp)
        {
            var degraded = JObject.Parse("{\"ok\":false,\"degraded\":true,\"data\":null}");
            var snapshot = _parser.ParseSnapshot(
                stockCode, degraded, quote.Data ?? new JObject(), limitUp.Data ?? new JObject(), DateTime.Now);
            return WithOptionalFreshness(
                snapshot,
                quote.Error == null ? snapshot.QuoteFreshness : DataFreshness.Failed,
                limitUp.Error == null ? snapshot.LimitUpFreshness : DataFreshness.Failed);
        }

        private static MarketSnapshot WithBigOrderFreshness(MarketSnapshot source, DataFreshness freshness)
        {
            return new MarketSnapshot(
                source.StockCode, source.Stock, source.MainFunds, source.LimitUp, source.Orders, source.Prices,
                freshness, source.QuoteFreshness, source.LimitUpFreshness,
                source.BigOrderFetchedAt, DateTime.Now, source.Issues);
        }

        private static MarketSnapshot WithOptionalFreshness(MarketSnapshot source, DataFreshness quote, DataFreshness limitUp)
        {
            return new MarketSnapshot(
                source.StockCode, source.Stock, source.MainFunds, source.LimitUp, source.Orders, source.Prices,
                source.BigOrderFreshness, quote, limitUp,
                source.BigOrderFetchedAt, source.RefreshedAt, source.Issues);
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

        private sealed class RequestResult
        {
            public JObject Data { get; set; }
            public Exception Error { get; set; }
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
