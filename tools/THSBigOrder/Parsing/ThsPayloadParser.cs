using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Newtonsoft.Json.Linq;
using THSBigOrder.Models;

namespace THSBigOrder.Parsing
{
    public sealed class PayloadParseException : Exception
    {
        public PayloadParseException(string message) : base(message) { }
    }

    public sealed class ThsPayloadParser
    {
        public BigOrderItem ParseOrder(JObject value)
        {
            var nature = (string)value["nature"] ?? "";
            int type;
            switch (nature)
            {
                case "主力被卖": type = 1; break;
                case "主力主买": type = 2; break;
                case "主力被买": type = 3; break;
                case "主力主卖": type = 4; break;
                default: throw new PayloadParseException("unknown order nature: " + nature);
            }

            var timeText = (string)value["otime"] ?? (string)value["ctime"];
            DateTime time;
            if (!DateTime.TryParse(timeText, CultureInfo.InvariantCulture, DateTimeStyles.AllowWhiteSpaces, out time))
            {
                TimeSpan clock;
                if (!TimeSpan.TryParse(timeText, CultureInfo.InvariantCulture, out clock))
                    throw new PayloadParseException("invalid order time: " + timeText);
                time = DateTime.Today.Add(clock);
            }

            return new BigOrderItem
            {
                Type = type,
                Volume = RequiredNumber(value["volume"], "volume"),
                Amount = RequiredNumber(value["money"] ?? value["value"], "money"),
                Price = RequiredNumber(value["avgprice"], "avgprice"),
                Time = time,
            };
        }

        public MarketSnapshot ParseSnapshot(
            string stockCode,
            JObject bigOrderEnvelope,
            JObject quotePayload,
            JObject limitUpPayload,
            DateTime refreshedAt)
        {
            var issues = new List<string>();
            var orders = new List<BigOrderItem>();
            var prices = new List<PricePoint>();
            var stock = ParseQuote(stockCode, quotePayload, issues);
            var limitUp = ParseLimitUp(stockCode, limitUpPayload, issues);
            var quoteFreshness = HasQuote(stockCode, quotePayload) ? DataFreshness.Fresh : DataFreshness.Missing;
            var limitFreshness = HasLimitUp(stockCode, limitUpPayload) ? DataFreshness.Fresh : DataFreshness.Missing;
            var bigFreshness = DataFreshness.Failed;
            var fetchedAt = refreshedAt;
            var mainFunds = new MainFundSummary();

            if (bigOrderEnvelope != null && bigOrderEnvelope.Value<bool?>("ok") == true)
            {
                var data = bigOrderEnvelope["data"] as JObject;
                if (data != null)
                {
                    bigFreshness = data.SelectToken("dragonMeta.cache.stale")?.Value<bool>() == true
                        ? DataFreshness.Stale
                        : DataFreshness.Fresh;
                    fetchedAt = UnixMilliseconds(bigOrderEnvelope["fetchedAt"], refreshedAt);
                    var title = data["title"] as JObject ?? new JObject();
                    if (string.IsNullOrWhiteSpace(stock.Name)) stock.Name = (string)title["stockname"] ?? "";
                    if (!stock.Price.HasValue) stock.Price = FiniteNumber(title["price"]);

                    foreach (var token in data["list"] as JArray ?? new JArray())
                    {
                        try { orders.Add(ParseOrder((JObject)token)); }
                        catch (Exception error) { issues.Add(error.Message); }
                    }
                    ParsePrices(data["pricechange"] as JArray, prices, issues);
                    mainFunds.MainBuy = ChineseAmount(title["mainbuy"]);
                    mainFunds.MainSell = ChineseAmount(title["mainsell"]);
                    if (mainFunds.MainBuy.HasValue && mainFunds.MainSell.HasValue)
                        mainFunds.NetAmount = mainFunds.MainBuy.Value - mainFunds.MainSell.Value;
                }
            }
            else if (bigOrderEnvelope == null || !bigOrderEnvelope.HasValues)
            {
                bigFreshness = DataFreshness.Missing;
            }
            mainFunds.OrderCount = orders.Count;

            return new MarketSnapshot(
                stockCode, stock, mainFunds, limitUp, orders, prices,
                bigFreshness, quoteFreshness, limitFreshness, fetchedAt, refreshedAt, issues);
        }

        private static StockSummary ParseQuote(string stockCode, JObject payload, IList<string> issues)
        {
            var row = FindRow(payload?.SelectToken("data.diff") as JArray, stockCode);
            return new StockSummary
            {
                Code = stockCode,
                Name = (string)row?["f14"] ?? "",
                Price = FiniteNumber(row?["f2"]),
                ChangePercent = FiniteNumber(row?["f3"]),
                TotalAmount = FiniteNumber(row?["f5"]),
                Volume = FiniteNumber(row?["f6"]),
                TurnoverRate = FiniteNumber(row?["f8"]),
                VolumeRatio = FiniteNumber(row?["f10"]),
            };
        }

        private static LimitUpContext ParseLimitUp(string stockCode, JObject payload, IList<string> issues)
        {
            var row = FindRow(payload?.SelectToken("data.info") as JArray, stockCode);
            return new LimitUpContext
            {
                SealAmount = FiniteNumber(row?["order_amount"]),
                SealVolume = FiniteNumber(row?["order_volume"]),
                OpenCount = FiniteNumber(row?["open_num"]).HasValue ? (int?)FiniteNumber(row["open_num"]).Value : null,
                HighDays = (string)row?["high_days"],
                SuccessRate = FiniteNumber(row?["limit_up_suc_rate"]),
                ReasonType = (string)row?["reason_type"],
            };
        }

        private static JObject FindRow(JArray rows, string stockCode)
        {
            if (rows == null) return null;
            return rows.OfType<JObject>().FirstOrDefault(row =>
                string.Equals((string)row["f12"] ?? (string)row["code"], stockCode, StringComparison.Ordinal));
        }

        private static bool HasQuote(string stockCode, JObject payload) => FindRow(payload?.SelectToken("data.diff") as JArray, stockCode) != null;
        private static bool HasLimitUp(string stockCode, JObject payload) => FindRow(payload?.SelectToken("data.info") as JArray, stockCode) != null;

        private static void ParsePrices(JArray values, IList<PricePoint> output, IList<string> issues)
        {
            foreach (var row in values?.OfType<JObject>() ?? Enumerable.Empty<JObject>())
            {
                DateTime time;
                if (!DateTime.TryParseExact((string)row["1"], "yyyyMMddHHmm", CultureInfo.InvariantCulture, DateTimeStyles.None, out time))
                {
                    issues.Add("invalid pricechange time");
                    continue;
                }
                var change = row.Properties().Where(property => property.Name != "1")
                    .Select(property => FiniteNumber(property.Value)).FirstOrDefault(value => value.HasValue);
                if (!change.HasValue)
                {
                    issues.Add("missing pricechange value");
                    continue;
                }
                output.Add(new PricePoint { Time = time, ChangePercent = change.Value });
            }
        }

        private static DateTime UnixMilliseconds(JToken token, DateTime fallback)
        {
            var value = FiniteNumber(token);
            if (!value.HasValue) return fallback;
            try { return DateTimeOffset.FromUnixTimeMilliseconds((long)value.Value).LocalDateTime; }
            catch { return fallback; }
        }

        private static double RequiredNumber(JToken token, string field)
        {
            var value = FiniteNumber(token);
            if (!value.HasValue) throw new PayloadParseException("invalid " + field);
            return value.Value;
        }

        private static double? ChineseAmount(JToken token)
        {
            var text = token?.ToString()?.Trim();
            if (string.IsNullOrEmpty(text)) return null;
            var multiplier = text.EndsWith("亿", StringComparison.Ordinal) ? 100000000d
                : text.EndsWith("万", StringComparison.Ordinal) ? 10000d : 1d;
            var value = FiniteNumber(text.TrimEnd('亿', '万'));
            return value.HasValue ? (double?)(value.Value * multiplier) : null;
        }

        private static double? FiniteNumber(JToken token) => FiniteNumber(token?.ToString());

        private static double? FiniteNumber(string text)
        {
            if (string.IsNullOrWhiteSpace(text)) return null;
            var normalized = text.Trim().Replace(",", "").Replace("手", "").Replace("%", "");
            double value;
            if (!double.TryParse(normalized, NumberStyles.Float, CultureInfo.InvariantCulture, out value)) return null;
            return double.IsNaN(value) || double.IsInfinity(value) ? (double?)null : value;
        }
    }
}
