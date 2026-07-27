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
    internal sealed class TdxMinuteSourceClient : IMarketSourceClient<IReadOnlyList<MinuteTurnoverPoint>>
    {
        private readonly HttpClient _http;
        private readonly string _bridgeBase;
        private readonly ThsPayloadParser _parser;

        public TdxMinuteSourceClient(HttpClient http, string bridgeBase, ThsPayloadParser parser)
        {
            _http = http;
            _bridgeBase = bridgeBase.TrimEnd('/');
            _parser = parser;
        }

        public async Task<SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>> LoadDirectAsync(
            string stockCode, CancellationToken cancellationToken)
        {
            return await LoadDirectAsync(stockCode, null, cancellationToken).ConfigureAwait(false);
        }

        public async Task<SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>> LoadDirectAsync(
            string stockCode, DateTime? sessionDate, CancellationToken cancellationToken)
        {
            using (var request = new HttpRequestMessage(HttpMethod.Get,
                _bridgeBase + "/api/quotes/minute?code=" + stockCode +
                (sessionDate.HasValue ? "&date=" + sessionDate.Value.ToString("yyyyMMdd") : "")))
            {
                var envelope = await GetJsonAsync(request, cancellationToken).ConfigureAwait(false);
                if (envelope.Value<bool?>("ok") != true || !(envelope["data"] is JObject data))
                    throw new PayloadParseException((string)envelope["errorCode"] ?? "TDX minute unavailable");
                if (data.Value<bool?>("expectedComplete") == true &&
                    data.Value<bool?>("complete") != true)
                    throw new PayloadParseException("TDX completed-session minute data is incomplete");
                return new SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>
                {
                    Data = _parser.ParseNormalizedMinute(data),
                    Transport = DataTransport.Direct,
                    Freshness = DataFreshness.Fresh,
                    FetchedAt = DateTime.Now,
                };
            }
        }

        public Task<SourceLoadResult<IReadOnlyList<MinuteTurnoverPoint>>> LoadProxyAsync(
            string stockCode, CancellationToken cancellationToken)
        {
            throw new NotSupportedException("TDX minute has no Tencent fallback");
        }

        private async Task<JObject> GetJsonAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            using (var response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false))
            {
                var text = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                response.EnsureSuccessStatusCode();
                return JObject.Parse(text);
            }
        }
    }
}
