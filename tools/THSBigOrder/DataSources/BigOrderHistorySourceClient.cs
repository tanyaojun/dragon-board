using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;
using THSBigOrder.Models;
using THSBigOrder.Parsing;

namespace THSBigOrder.DataSources
{
    internal sealed class BigOrderHistorySourceClient
    {
        private readonly HttpClient _http;
        private readonly string _baseUrl;
        private readonly ThsPayloadParser _parser;

        public BigOrderHistorySourceClient(HttpClient http, string baseUrl, ThsPayloadParser parser)
        {
            _http = http;
            _baseUrl = baseUrl.TrimEnd('/');
            _parser = parser;
        }

        public async Task<SourceLoadResult<BigOrderSourceData>> LoadAsync(
            BigOrderDataSource source, string stockCode, DateTime sessionDate, CancellationToken cancellationToken)
        {
            var name = source == BigOrderDataSource.Longhu ? "longhu" : "ths";
            var url = _baseUrl + "/api/big-order/history?source=" + name + "&stockCode=" + stockCode +
                "&sessionDate=" + sessionDate.ToString("yyyy-MM-dd");
            using (var response = await _http.GetAsync(url, cancellationToken).ConfigureAwait(false))
            {
                var text = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                if (!response.IsSuccessStatusCode)
                {
                    JObject errorEnvelope = null;
                    try { errorEnvelope = JObject.Parse(text); }
                    catch { }
                    var errorCode = (string)errorEnvelope?["errorCode"];
                    if (errorCode == "archive_not_found")
                        throw new PayloadParseException("所选日期没有该股票的大单归档");
                    if ((string)errorEnvelope?["detail"] == "Not Found")
                        throw new PayloadParseException("QuantBoard 后端未加载历史大单接口，请重启后端");
                    throw new PayloadParseException(
                        (string)errorEnvelope?["error"] ?? errorCode ?? text);
                }
                var envelope = JObject.Parse(text);
                var archive = envelope["data"] as JObject;
                var payload = archive?["data"] as JObject;
                if (envelope.Value<bool?>("ok") != true || payload == null ||
                    !DateTime.TryParse((string)archive["sessionDate"], out var actual) || actual.Date != sessionDate.Date)
                    throw new PayloadParseException("历史大单数据日期不匹配");
                var data = source == BigOrderDataSource.Longhu
                    ? new BigOrderSourceData { Orders = _parser.ParseLonghuOrders(payload["List"] as JArray), SessionDate = actual.Date }
                    : _parser.ParseBigOrderSource(stockCode, payload, actual.Date);
                return new SourceLoadResult<BigOrderSourceData>
                {
                    Data = data, Freshness = DataFreshness.Fresh, Transport = DataTransport.ProxyPrimary,
                    FetchedAt = DateTime.Now,
                };
            }
        }
    }
}
