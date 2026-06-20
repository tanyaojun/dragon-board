using System;
using System.Globalization;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using THSBigOrder.Models;
using THSBigOrder.Parsing;

namespace THSBigOrder.DataSources
{
    internal sealed class ThsLimitUpSourceClient : IMarketSourceClient<LimitUpSourceData>
    {
        private readonly HttpClient _http;
        private readonly string _proxyBase;
        private readonly ThsPayloadParser _parser;

        public ThsLimitUpSourceClient(HttpClient http, string proxyBase, ThsPayloadParser parser)
        {
            _http = http;
            _proxyBase = proxyBase.TrimEnd('/');
            _parser = parser;
        }

        public async Task<SourceLoadResult<LimitUpSourceData>> LoadDirectAsync(
            string stockCode, CancellationToken cancellationToken)
        {
            var date = DateTime.Now.ToString("yyyyMMdd", CultureInfo.InvariantCulture);
            var url = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200&field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,9003,9004,continue_day,continue_day_cnt,high_days,reason_type&filter=HS,GEM2STAR&order_field=330324&order_type=0&date=" + date;
            using (var request = new HttpRequestMessage(HttpMethod.Get, url))
            {
                request.Headers.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64)");
                var data = _parser.ParseLimitUpSource(stockCode,
                    await GetJsonAsync(request, cancellationToken).ConfigureAwait(false));
                return Success(data, DataTransport.Direct);
            }
        }

        public async Task<SourceLoadResult<LimitUpSourceData>> LoadProxyAsync(
            string stockCode, CancellationToken cancellationToken)
        {
            using (var request = new HttpRequestMessage(HttpMethod.Get, _proxyBase + "/api/limitup/10jqka"))
            {
                var payload = await GetJsonAsync(request, cancellationToken).ConfigureAwait(false);
                if (payload.Value<bool?>("ok") == false && payload.Value<bool?>("degraded") == true)
                    throw new PayloadParseException("THS limit-up proxy degraded");
                return Success(_parser.ParseLimitUpSource(stockCode, payload), DataTransport.ProxyFallback);
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

        private static SourceLoadResult<LimitUpSourceData> Success(LimitUpSourceData data, DataTransport transport)
        {
            return new SourceLoadResult<LimitUpSourceData>
            {
                Data = data,
                Transport = transport,
                Freshness = data.Found ? DataFreshness.Fresh : DataFreshness.Missing,
                FetchedAt = DateTime.Now,
            };
        }
    }
}
