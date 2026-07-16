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
    internal sealed class LonghuBigOrderSourceClient : IMarketSourceClient<BigOrderSourceData>
    {
        private const int PageSize = 200;
        private const int MaxPages = 200;
        private readonly HttpClient _http;
        private readonly string _proxyBase;
        private readonly ThsPayloadParser _parser;

        public LonghuBigOrderSourceClient(HttpClient http, string proxyBase, ThsPayloadParser parser)
        {
            _http = http;
            _proxyBase = proxyBase.TrimEnd('/');
            _parser = parser;
        }

        public Task<SourceLoadResult<BigOrderSourceData>> LoadDirectAsync(
            string stockCode, CancellationToken cancellationToken)
        {
            var deviceId = Guid.NewGuid().ToString("N");
            return LoadPagesAsync(
                (index, token) => LoadDirectPageAsync(stockCode, deviceId, index, token),
                DataTransport.Direct,
                cancellationToken);
        }

        public Task<SourceLoadResult<BigOrderSourceData>> LoadProxyAsync(
            string stockCode, CancellationToken cancellationToken)
        {
            return LoadPagesAsync(
                (index, token) => LoadProxyPageAsync(stockCode, index, token),
                DataTransport.ProxyFallback,
                cancellationToken);
        }

        private async Task<SourceLoadResult<BigOrderSourceData>> LoadPagesAsync(
            Func<int, CancellationToken, Task<JObject>> loadPage,
            DataTransport transport,
            CancellationToken cancellationToken)
        {
            var allOrders = new List<BigOrderItem>();
            var index = 0;
            int? expectedTotal = null;
            for (var page = 0; page < MaxPages; page++)
            {
                var payload = await loadPage(index, cancellationToken).ConfigureAwait(false);
                ValidatePayload(payload);
                var list = payload["List"] as JArray;
                if (list == null) throw new PayloadParseException("invalid Longhu List");
                var pageOrders = _parser.ParseLonghuOrders(list);
                if (list.Count > 0 && pageOrders.Count == 0)
                    throw new PayloadParseException("Longhu List contains no valid rows");
                allOrders.AddRange(pageOrders);

                var total = payload.Value<int?>("Total");
                if (total.HasValue)
                {
                    if (total.Value < 0) throw new PayloadParseException("invalid Longhu Total");
                    if (!expectedTotal.HasValue) expectedTotal = total;
                    else if (expectedTotal.Value != total.Value)
                        throw new PayloadParseException("Longhu Total changed during pagination");
                }

                index += list.Count;
                if (expectedTotal.HasValue)
                {
                    if (index > expectedTotal.Value)
                        throw new PayloadParseException("Longhu response exceeds Total");
                    if (index >= expectedTotal.Value)
                        return Success(allOrders, transport);
                    if (list.Count < PageSize)
                        throw new PayloadParseException("truncated Longhu response");
                }
                else if (list.Count < PageSize)
                {
                    return Success(allOrders, transport);
                }
            }

            throw new PayloadParseException("Longhu pagination exceeded maximum pages");
        }

        private static SourceLoadResult<BigOrderSourceData> Success(
            IReadOnlyList<BigOrderItem> orders,
            DataTransport transport)
        {
            return new SourceLoadResult<BigOrderSourceData>
            {
                Data = new BigOrderSourceData { Orders = orders },
                Freshness = DataFreshness.Fresh,
                Transport = transport,
                FetchedAt = DateTime.Now,
            };
        }

        private async Task<JObject> LoadDirectPageAsync(
            string stockCode, string deviceId, int index, CancellationToken cancellationToken)
        {
            var values = new Dictionary<string, string>
            {
                ["Order"] = "0",
                ["st"] = PageSize.ToString(),
                ["a"] = "GetMainMonitor_w30",
                ["c"] = "StockYiDongKanPan",
                ["DeviceID"] = deviceId,
                ["PhoneOSNew"] = "1",
                ["VerSion"] = "5.17.0.4",
                ["Index"] = index.ToString(),
                ["Money"] = "0",
                ["apiv"] = "w36",
                ["StockID"] = stockCode,
                ["IsBS"] = "0",
            };
            using (var request = new HttpRequestMessage(
                HttpMethod.Post, "https://apphwhq.longhuvip.com/w1/api/index.php"))
            {
                request.Headers.UserAgent.ParseAdd(
                    "Dalvik/2.1.0 (Linux; U; Android 9; MI 8 MIUI/V11.0.5.0.PEACNXM)");
                request.Content = new FormUrlEncodedContent(values);
                return await GetJsonAsync(request, cancellationToken).ConfigureAwait(false);
            }
        }

        private async Task<JObject> LoadProxyPageAsync(
            string stockCode, int index, CancellationToken cancellationToken)
        {
            var url = _proxyBase + "/api/big-order/main-monitor?stockCode=" +
                      Uri.EscapeDataString(stockCode) + "&limit=" + PageSize +
                      "&money=0&index=" + index;
            using (var request = new HttpRequestMessage(HttpMethod.Get, url))
            {
                return await GetJsonAsync(request, cancellationToken).ConfigureAwait(false);
            }
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

        private static void ValidatePayload(JObject payload)
        {
            if (payload == null || payload.Value<bool?>("ok") == false ||
                payload.Value<string>("errcode") != "0")
                throw new PayloadParseException(
                    (string)payload?["msg"] ?? (string)payload?["errorCode"] ??
                    "invalid Longhu payload");
        }

    }
}
