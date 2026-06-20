using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using THSBigOrder.Models;
using THSBigOrder.Parsing;

namespace THSBigOrder.DataSources
{
    internal sealed class TencentMinuteSourceClient : IMarketSourceClient<IReadOnlyList<MinuteTurnoverPoint>>
    {
        private readonly HttpClient _http;
        private readonly string _proxyBase;
        private readonly ThsPayloadParser _parser;

        public TencentMinuteSourceClient(HttpClient http, string proxyBase, ThsPayloadParser parser)
        {
            _http = http;
            _proxyBase = proxyBase.TrimEnd('/');
            _parser = parser;
        }

        public async Task<SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>> LoadDirectAsync(
            string stockCode, CancellationToken cancellationToken)
        {
            var marketCode = (stockCode.StartsWith("6") ? "sh" : "sz") + stockCode;
            using (var request = new HttpRequestMessage(HttpMethod.Get,
                "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=" + marketCode))
            {
                request.Headers.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64)");
                var payload = await GetJsonAsync(request, cancellationToken).ConfigureAwait(false);
                return Success(_parser.ParseTencentMinute(stockCode, payload), DataTransport.Direct, DataFreshness.Fresh);
            }
        }

        public async Task<SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>> LoadProxyAsync(
            string stockCode, CancellationToken cancellationToken)
        {
            using (var request = new HttpRequestMessage(HttpMethod.Get,
                _proxyBase + "/api/quotes/tencent/minute?code=" + stockCode))
            {
                var envelope = await GetJsonAsync(request, cancellationToken).ConfigureAwait(false);
                if (envelope.Value<bool?>("ok") != true || !(envelope["data"] is JObject data))
                    throw new PayloadParseException("Tencent minute proxy degraded");
                var stale = data.SelectToken("dragonMeta.cache.stale")?.Value<bool>() == true;
                return Success(_parser.ParseNormalizedMinute(data), DataTransport.ProxyFallback,
                    stale ? DataFreshness.Stale : DataFreshness.Fresh);
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

        private static SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>> Success(
            IReadOnlyList<MinuteTurnoverPoint> data, DataTransport transport, DataFreshness freshness)
        {
            return new SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>
            {
                Data = data, Transport = transport, Freshness = freshness, FetchedAt = DateTime.Now,
            };
        }
    }
}
