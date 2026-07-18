using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using THSBigOrder.Models;
using THSBigOrder.Parsing;

namespace THSBigOrder.DataSources
{
    internal sealed class ThsBigOrderSourceClient : IMarketSourceClient<BigOrderSourceData>
    {
        private readonly HttpClient _http;
        private readonly string _proxyBase;
        private readonly ThsPayloadParser _parser;

        public ThsBigOrderSourceClient(HttpClient http, string proxyBase, ThsPayloadParser parser)
        {
            _http = http;
            _proxyBase = proxyBase.TrimEnd('/');
            _parser = parser;
        }

        public async Task<SourceLoadResult<BigOrderSourceData>> LoadDirectAsync(string stockCode, CancellationToken cancellationToken)
        {
            var url = "https://vaserviece.10jqka.com.cn/Level2/index.php?op=mainMonitorDetail&stockcode=" + stockCode;
            using (var request = new HttpRequestMessage(HttpMethod.Get, url))
            {
                request.Headers.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36");
                request.Headers.Referrer = new Uri("https://vaserviece.10jqka.com.cn/");
                request.Headers.Accept.ParseAdd("application/json,text/plain,*/*");
                var payload = await GetJsonAsync(request, cancellationToken).ConfigureAwait(false);
                return Success(_parser.ParseBigOrderSource(stockCode, payload), DataTransport.Direct, DataFreshness.Fresh);
            }
        }

        public async Task<SourceLoadResult<BigOrderSourceData>> LoadProxyAsync(string stockCode, CancellationToken cancellationToken)
        {
            using (var request = new HttpRequestMessage(HttpMethod.Get,
                _proxyBase + "/api/big-order/ths-detail?stockCode=" + stockCode))
            {
                var envelope = await GetJsonAsync(request, cancellationToken).ConfigureAwait(false);
                if (envelope.Value<bool?>("ok") != true || !(envelope["data"] is JObject data))
                    throw new PayloadParseException((string)envelope["errorCode"] ?? "big-order proxy degraded");
                DateTime sessionDate;
                DateTime? authoritativeDate = DateTime.TryParse(
                    envelope.Value<string>("sessionDate"), out sessionDate)
                    ? (DateTime?)sessionDate.Date
                    : null;
                var stale = data.SelectToken("dragonMeta.cache.uiStale")?.Value<bool>() == true;
                var result = Success(
                    _parser.ParseBigOrderSource(stockCode, data, authoritativeDate),
                    stale ? DataTransport.Stale : DataTransport.ProxyPrimary,
                    stale ? DataFreshness.Stale : DataFreshness.Fresh);
                var milliseconds = envelope.Value<long?>("fetchedAt");
                if (milliseconds.HasValue)
                    result.FetchedAt = DateTimeOffset.FromUnixTimeMilliseconds(milliseconds.Value).LocalDateTime;
                return result;
            }
        }

        private async Task<JObject> GetJsonAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            using (var response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false))
            {
                var text = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                response.EnsureSuccessStatusCode();
                return JObject.Parse(text);
            }
        }

        private static SourceLoadResult<BigOrderSourceData> Success(
            BigOrderSourceData data, DataTransport transport, DataFreshness freshness)
        {
            return new SourceLoadResult<BigOrderSourceData>
            {
                Data = data, Transport = transport, Freshness = freshness, FetchedAt = DateTime.Now,
            };
        }
    }
}
