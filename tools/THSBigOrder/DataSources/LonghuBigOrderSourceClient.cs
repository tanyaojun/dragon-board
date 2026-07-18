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
        private readonly HttpClient _http;
        private readonly string _proxyBase;
        private readonly ThsPayloadParser _parser;

        public LonghuBigOrderSourceClient(HttpClient http, string proxyBase, ThsPayloadParser parser)
        {
            _http = http;
            _proxyBase = proxyBase.TrimEnd('/');
            _parser = parser;
        }

        public async Task<SourceLoadResult<BigOrderSourceData>> LoadProxyAsync(
            string stockCode,
            CancellationToken cancellationToken)
        {
            using (var request = new HttpRequestMessage(
                HttpMethod.Get,
                _proxyBase + "/api/big-order/longhu/all-day?stockCode=" +
                Uri.EscapeDataString(stockCode) + "&money=0"))
            using (var response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false))
            {
                var text = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                response.EnsureSuccessStatusCode();
                var envelope = JObject.Parse(text);
                if (envelope.Value<bool?>("ok") != true || !(envelope["data"] is JObject data))
                    throw new PayloadParseException(
                        (string)envelope["errorCode"] ?? "Longhu proxy degraded");
                DateTime sessionDate;
                if (!DateTime.TryParse(envelope.Value<string>("sessionDate"), out sessionDate))
                    throw new PayloadParseException("Longhu proxy missing sessionDate");
                var rows = data["List"] as JArray;
                if (rows == null) throw new PayloadParseException("invalid Longhu List");
                var orders = _parser.ParseLonghuOrders(rows);
                if (rows.Count > 0 && orders.Count == 0)
                    throw new PayloadParseException("Longhu List contains no valid rows");
                var fetchedAt = DateTime.Now;
                var milliseconds = envelope.Value<long?>("fetchedAt");
                if (milliseconds.HasValue)
                    fetchedAt = DateTimeOffset.FromUnixTimeMilliseconds(milliseconds.Value).LocalDateTime;
                return new SourceLoadResult<BigOrderSourceData>
                {
                    Data = new BigOrderSourceData
                    {
                        Orders = orders,
                        SessionDate = sessionDate.Date,
                    },
                    Freshness = data.SelectToken("dragonMeta.cache.uiStale")?.Value<bool>() == true
                        ? DataFreshness.Stale
                        : DataFreshness.Fresh,
                    Transport = DataTransport.ProxyPrimary,
                    FetchedAt = fetchedAt,
                };
            }
        }

        public async Task<SourceLoadResult<BigOrderSourceData>> LoadDirectAsync(
            string stockCode,
            CancellationToken cancellationToken)
        {
            var device = Guid.NewGuid().ToString("N");
            var allOrders = new List<BigOrderItem>();
            var index = 0;
            int? total = null;
            for (var page = 0; page < 200; page++)
            {
                var values = new Dictionary<string, string>
                {
                    ["Order"] = "0", ["st"] = "200", ["a"] = "GetMainMonitor_w30",
                    ["c"] = "StockYiDongKanPan", ["DeviceID"] = device, ["PhoneOSNew"] = "1",
                    ["VerSion"] = "5.17.0.4", ["Index"] = index.ToString(), ["Money"] = "0",
                    ["apiv"] = "w36", ["StockID"] = stockCode, ["IsBS"] = "0",
                };
                using (var request = new HttpRequestMessage(
                    HttpMethod.Post, "https://apphwhq.longhuvip.com/w1/api/index.php"))
                {
                    request.Headers.UserAgent.ParseAdd(
                        "Dalvik/2.1.0 (Linux; U; Android 9; MI 8 MIUI/V11.0.5.0.PEACNXM)");
                    request.Content = new FormUrlEncodedContent(values);
                    using (var response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false))
                    {
                        var payload = JObject.Parse(
                            await response.Content.ReadAsStringAsync().ConfigureAwait(false));
                        response.EnsureSuccessStatusCode();
                        var rows = payload["List"] as JArray;
                        var pageTotal = payload.Value<int?>("Total");
                        if (payload.Value<string>("errcode") != "0" || rows == null || !pageTotal.HasValue)
                            throw new PayloadParseException("invalid Longhu payload");
                        if (!total.HasValue) total = pageTotal;
                        else if (total.Value != pageTotal.Value)
                            throw new PayloadParseException("Longhu Total changed during pagination");
                        var parsed = _parser.ParseLonghuOrders(rows);
                        if (rows.Count > 0 && parsed.Count == 0)
                            throw new PayloadParseException("Longhu List contains no valid rows");
                        allOrders.AddRange(parsed);
                        index += rows.Count;
                        if (index > total.Value)
                            throw new PayloadParseException("Longhu response exceeds Total");
                        if (index == total.Value) break;
                        if (rows.Count < 200) throw new PayloadParseException("truncated Longhu response");
                    }
                }
            }
            if (!total.HasValue || index != total.Value)
                throw new PayloadParseException("Longhu pagination exceeded maximum pages");
            return new SourceLoadResult<BigOrderSourceData>
            {
                Data = new BigOrderSourceData
                {
                    Orders = allOrders,
                    SessionDate = allOrders.Count > 0 ? (DateTime?)allOrders[0].Time.Date : null,
                },
                Freshness = DataFreshness.Fresh,
                Transport = DataTransport.Direct,
                FetchedAt = DateTime.Now,
            };
        }
    }
}
