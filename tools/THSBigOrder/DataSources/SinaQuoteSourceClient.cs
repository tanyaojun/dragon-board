using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using THSBigOrder.Models;
using THSBigOrder.Parsing;

namespace THSBigOrder.DataSources
{
    internal sealed class SinaQuoteSourceClient : IMarketSourceClient<StockSummary>
    {
        private readonly HttpClient _http;
        private readonly string _proxyBase;
        private readonly ThsPayloadParser _parser;

        public SinaQuoteSourceClient(HttpClient http, string proxyBase, ThsPayloadParser parser)
        {
            _http = http;
            _proxyBase = proxyBase.TrimEnd('/');
            _parser = parser;
        }

        public async Task<SourceLoadResult<StockSummary>> LoadDirectAsync(string stockCode, CancellationToken cancellationToken)
        {
            var marketCode = (stockCode.StartsWith("6") ? "sh" : "sz") + stockCode;
            using (var request = new HttpRequestMessage(HttpMethod.Get, "http://qt.gtimg.cn/q=" + marketCode))
            {
                request.Headers.Referrer = new Uri("http://stockapp.finance.qq.com/");
                using (var response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false))
                {
                    var bytes = await response.Content.ReadAsByteArrayAsync().ConfigureAwait(false);
                    response.EnsureSuccessStatusCode();
                    return Success(_parser.ParseTencentQuote(stockCode, bytes), DataTransport.Direct, DataFreshness.Fresh);
                }
            }
        }

        public async Task<SourceLoadResult<StockSummary>> LoadProxyAsync(string stockCode, CancellationToken cancellationToken)
        {
            using (var response = await _http.GetAsync(
                _proxyBase + "/api/quotes/tencent?codes=" + stockCode, cancellationToken).ConfigureAwait(false))
            {
                var payload = JObject.Parse(await response.Content.ReadAsStringAsync().ConfigureAwait(false));
                response.EnsureSuccessStatusCode();
                if (payload.Value<bool?>("ok") == false && payload.Value<bool?>("degraded") == true)
                    throw new PayloadParseException("Sina proxy degraded");
                var stale = payload.SelectToken("dragonMeta.cache.stale")?.Value<bool>() == true;
                return Success(_parser.ParseNormalizedQuote(stockCode, payload), DataTransport.ProxyFallback,
                    stale ? DataFreshness.Stale : DataFreshness.Fresh);
            }
        }

        private static SourceLoadResult<StockSummary> Success(
            StockSummary data, DataTransport transport, DataFreshness freshness)
        {
            return new SourceLoadResult<StockSummary>
            {
                Data = data, Transport = transport, Freshness = freshness, FetchedAt = DateTime.Now,
            };
        }
    }
}
