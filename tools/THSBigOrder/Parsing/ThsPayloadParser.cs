using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Newtonsoft.Json.Linq;
using THSBigOrder.Models;
using THSBigOrder.DataSources;

namespace THSBigOrder.Parsing
{
    public sealed class PayloadParseException : Exception
    {
        public PayloadParseException(string message) : base(message) { }
    }

    public sealed class ThsPayloadParser
    {
        public BigOrderSourceData ParseBigOrderSource(
            string stockCode,
            JObject payload,
            DateTime? authoritativeSessionDate = null)
        {
            var errorCode = payload?.Value<int?>("errorcode");
            if (payload == null || errorCode.HasValue && errorCode.Value != 0 ||
                !(payload["title"] is JObject title) || !(payload["list"] is JArray list))
                throw new PayloadParseException("invalid THS big-order payload");

            var issues = new List<string>();
            var sessionDate = authoritativeSessionDate?.Date ?? InferThsSessionDate(payload);
            var orders = new List<BigOrderItem>();
            foreach (var token in list.OfType<JObject>())
            {
                try { orders.Add(ParseOrder(token, sessionDate)); }
                catch (Exception error) { issues.Add(error.Message); }
            }
            var prices = new List<PricePoint>();
            ParsePrices(payload["pricechange"] as JArray, prices, issues);
            var buy = ChineseAmount(title["mainbuy"]);
            var sell = ChineseAmount(title["mainsell"]);
            return new BigOrderSourceData
            {
                SessionDate = sessionDate,
                StockFallback = new StockSummary
                {
                    Code = stockCode,
                    Name = (string)title["stockname"] ?? "",
                    Price = FiniteNumber(title["price"]),
                },
                MainFunds = new MainFundSummary
                {
                    MainBuy = buy,
                    MainSell = sell,
                    NetAmount = buy.HasValue && sell.HasValue ? (double?)(buy.Value - sell.Value) : null,
                    OrderCount = orders.Count,
                },
                Orders = orders,
                Prices = prices,
            };
        }

        public StockSummary ParseSinaQuote(string stockCode, byte[] payload)
        {
            var text = System.Text.Encoding.GetEncoding(936).GetString(payload ?? new byte[0]);
            var marker = "hq_str_" + (stockCode.StartsWith("6") ? "sh" : "sz") + stockCode + "=\"";
            var start = text.IndexOf(marker, StringComparison.Ordinal);
            var end = start < 0 ? -1 : text.IndexOf('"', start + marker.Length);
            if (start < 0 || end < 0) throw new PayloadParseException("invalid Sina quote payload");
            var parts = text.Substring(start + marker.Length, end - start - marker.Length).Split(',');
            if (parts.Length < 10) throw new PayloadParseException("invalid Sina quote fields");
            var previousClose = FiniteNumber(parts[2]);
            var price = FiniteNumber(parts[3]);
            var volume = FiniteNumber(parts[8]);
            var amount = FiniteNumber(parts[9]);
            if (!amount.HasValue && volume.HasValue && price.HasValue) amount = volume.Value * price.Value;
            return new StockSummary
            {
                Code = stockCode,
                Name = parts[0],
                Price = price,
                ChangePercent = previousClose > 0 && price.HasValue
                    ? (double?)((price.Value - previousClose.Value) / previousClose.Value * 100d)
                    : null,
                Volume = volume,
                TotalAmount = amount,
            };
        }

        public StockSummary ParseTencentQuote(string stockCode, byte[] payload)
        {
            var text = System.Text.Encoding.GetEncoding(936).GetString(payload ?? new byte[0]);
            var marker = "v_" + (stockCode.StartsWith("6") ? "sh" : "sz") + stockCode + "=\"";
            var start = text.IndexOf(marker, StringComparison.Ordinal);
            var end = start < 0 ? -1 : text.IndexOf('"', start + marker.Length);
            if (start < 0 || end < 0) throw new PayloadParseException("invalid Tencent quote payload");
            var parts = text.Substring(start + marker.Length, end - start - marker.Length).Split('~');
            if (parts.Length < 50) throw new PayloadParseException("invalid Tencent quote fields");
            var price = FiniteNumber(parts[3]);
            var volume = FiniteNumber(parts[6]);
            return new StockSummary
            {
                Code = stockCode,
                Name = parts[1],
                Price = price,
                ChangePercent = FiniteNumber(parts[32]),
                Volume = volume,
                TotalAmount = price.HasValue && volume.HasValue ? (double?)(price.Value * volume.Value * 100d) : null,
                TurnoverRate = FiniteNumber(parts[38]),
                VolumeRatio = FiniteNumber(parts[49]),
            };
        }

        public StockSummary ParseNormalizedQuote(string stockCode, JObject payload)
        {
            return ParseQuote(stockCode, payload, new List<string>());
        }

        public IReadOnlyList<MinuteTurnoverPoint> ParseNormalizedMinute(JObject payload)
        {
            return ParseMinuteData(payload);
        }

        public LimitUpSourceData ParseLimitUpSource(string stockCode, JObject payload)
        {
            var rows = payload?.SelectToken("data.info") as JArray;
            if (rows == null) throw new PayloadParseException("invalid THS limit-up payload");
            var row = FindRow(rows, stockCode);
            return new LimitUpSourceData { Found = row != null, Context = ParseLimitUpRow(row) };
        }

        public BigOrderItem ParseOrder(JObject value, DateTime? sessionDate = null)
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
                if (!sessionDate.HasValue)
                    throw new PayloadParseException("order time requires authoritative session date");
                time = sessionDate.Value.Date.Add(clock);
            }
            else if (timeText != null && timeText.IndexOf('-') >= 0 && sessionDate.HasValue &&
                     time.Date != sessionDate.Value.Date)
            {
                throw new PayloadParseException("order date conflicts with session date");
            }
            else if (timeText != null && timeText.IndexOf('-') < 0)
            {
                if (!sessionDate.HasValue)
                    throw new PayloadParseException("order time requires authoritative session date");
                time = sessionDate.Value.Date.Add(time.TimeOfDay);
            }

            return new BigOrderItem
            {
                Type = type,
                Volume = RequiredNumber(value["volume"], "volume"),
                Amount = RequiredAmount(value["money"], value["value"]),
                Price = RequiredNumber(value["avgprice"], "avgprice"),
                Time = time,
            };
        }

        private static DateTime? InferThsSessionDate(JObject payload)
        {
            foreach (var field in new[] { "sessionDate", "tradeDate", "date" })
            {
                DateTime explicitDate;
                if (DateTime.TryParseExact((string)payload?[field], "yyyy-MM-dd",
                    CultureInfo.InvariantCulture, DateTimeStyles.None, out explicitDate))
                    return explicitDate.Date;
            }
            foreach (var row in (payload?["pricechange"] as JArray) ?? new JArray())
            {
                // 与 proxy 侧一致：pricechange 行兼容对象 {"1": "..."} 和数组 [.., "..."] 两种形态
                var raw = row is JObject rowObject
                    ? (string)rowObject["1"]
                    : row is JArray rowArray && rowArray.Count > 1 ? (string)rowArray[1] : null;
                DateTime value;
                if (DateTime.TryParseExact(raw, "yyyyMMddHHmm",
                    CultureInfo.InvariantCulture, DateTimeStyles.None, out value))
                    return value.Date;
            }
            foreach (var row in (payload?["list"] as JArray)?.OfType<JObject>() ??
                                Enumerable.Empty<JObject>())
            {
                DateTime value;
                if (DateTime.TryParse((string)row["otime"] ?? (string)row["ctime"],
                    CultureInfo.InvariantCulture, DateTimeStyles.AllowWhiteSpaces, out value) &&
                    (((string)row["otime"] ?? (string)row["ctime"]) ?? "").Contains("-"))
                    return value.Date;
            }
            return null;
        }

        public IReadOnlyList<BigOrderItem> ParseLonghuOrders(JArray values)
        {
            var orders = new List<BigOrderItem>();
            foreach (var value in values?.OfType<JArray>() ?? Enumerable.Empty<JArray>())
            {
                try { orders.Add(ParseLonghuOrder(value)); }
                catch (PayloadParseException) { }
            }
            return orders;
        }

        public BigOrderItem ParseLonghuOrder(JArray value)
        {
            if (value == null) throw new PayloadParseException("invalid Longhu order row");

            JToken typeToken;
            JToken unixToken;
            JToken timeToken;
            JToken priceToken;
            JToken volumeToken;
            JToken amountToken = null;
            var compact = value.Count >= 7 &&
                          DateTime.TryParseExact(value[2]?.ToString(), "yyyy-MM-dd HH:mm:ss",
                              CultureInfo.InvariantCulture, DateTimeStyles.None, out _);
            if (compact)
            {
                unixToken = value[1];
                timeToken = value[2];
                priceToken = value[3];
                volumeToken = value[4];
                typeToken = value[5];
            }
            else if (value.Count >= 6)
            {
                typeToken = value[0];
                unixToken = value[1];
                volumeToken = value[2];
                amountToken = value[3];
                priceToken = value[4];
                timeToken = value[5];
            }
            else
            {
                throw new PayloadParseException("invalid Longhu order row");
            }

            var typeNumber = RequiredNumber(typeToken, "tradetype");
            if (typeNumber != Math.Truncate(typeNumber))
                throw new PayloadParseException("invalid Longhu tradetype");
            var type = (int)typeNumber;
            if (type < 1 || type > 4) throw new PayloadParseException("invalid Longhu tradetype");
            var unixSeconds = RequiredNumber(unixToken, "unixSeconds");
            if (unixSeconds <= 0) throw new PayloadParseException("invalid unixSeconds");
            DateTime time;
            if (!DateTime.TryParseExact(timeToken?.ToString(), "yyyy-MM-dd HH:mm:ss",
                    CultureInfo.InvariantCulture, DateTimeStyles.None, out time))
                throw new PayloadParseException("invalid Longhu datetime");
            var price = RequiredNumber(priceToken, "price");
            var volume = RequiredNumber(volumeToken, "amount");
            if (price <= 0) throw new PayloadParseException("invalid price");
            if (volume <= 0) throw new PayloadParseException("invalid amount");
            var amount = amountToken == null ? price * volume : RequiredNumber(amountToken, "money");
            if (amount < 0) throw new PayloadParseException("invalid money");
            return new BigOrderItem
            {
                Type = type,
                Volume = volume,
                Amount = amount,
                Price = price,
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
            return ParseSnapshot(
                stockCode, bigOrderEnvelope, quotePayload, new JObject(), limitUpPayload, refreshedAt);
        }

        public MarketSnapshot ParseSnapshot(
            string stockCode,
            JObject bigOrderEnvelope,
            JObject quotePayload,
            JObject minuteEnvelope,
            JObject limitUpPayload,
            DateTime refreshedAt)
        {
            var issues = new List<string>();
            var orders = new List<BigOrderItem>();
            var prices = new List<PricePoint>();
            var minuteTurnover = new List<MinuteTurnoverPoint>();
            var stock = ParseQuote(stockCode, quotePayload, issues);
            var limitUp = ParseLimitUp(stockCode, limitUpPayload, issues);
            var quoteFreshness = HasQuote(stockCode, quotePayload) ? DataFreshness.Fresh : DataFreshness.Missing;
            var limitFreshness = HasLimitUp(stockCode, limitUpPayload) ? DataFreshness.Fresh : DataFreshness.Missing;
            var minuteFreshness = ParseMinuteTurnover(minuteEnvelope, minuteTurnover, issues);
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
                stockCode, stock, mainFunds, limitUp, orders, prices, minuteTurnover,
                bigFreshness, quoteFreshness, minuteFreshness, limitFreshness,
                fetchedAt, refreshedAt, issues);
        }

        private static DataFreshness ParseMinuteTurnover(
            JObject envelope,
            IList<MinuteTurnoverPoint> output,
            IList<string> issues)
        {
            if (envelope == null || !envelope.HasValues) return DataFreshness.Missing;
            if (envelope.Value<bool?>("ok") != true) return DataFreshness.Failed;
            var data = envelope["data"] as JObject;
            DateTime date;
            if (data == null || !DateTime.TryParseExact(
                (string)data["date"], "yyyyMMdd", CultureInfo.InvariantCulture,
                DateTimeStyles.None, out date))
            {
                issues.Add("invalid minute turnover date");
                return DataFreshness.Failed;
            }

            DateTime? previousTime = null;
            double previousVolume = 0;
            double previousAmount = 0;
            foreach (var row in (data["points"] as JArray)?.OfType<JObject>() ?? Enumerable.Empty<JObject>())
            {
                DateTime time;
                var volume = FiniteNumber(row["cumulativeVolume"]);
                var amount = FiniteNumber(row["cumulativeAmount"]);
                var price = FiniteNumber(row["price"]);
                if (!DateTime.TryParseExact(
                        date.ToString("yyyyMMdd", CultureInfo.InvariantCulture) + (string)row["time"],
                        "yyyyMMddHHmm", CultureInfo.InvariantCulture, DateTimeStyles.None, out time) ||
                    !price.HasValue || !volume.HasValue || !amount.HasValue ||
                    volume.Value < 0 || amount.Value < 0 ||
                    (previousTime.HasValue && (time <= previousTime.Value ||
                                               volume.Value < previousVolume ||
                                               amount.Value < previousAmount)) ||
                    !IsTradingTime(time))
                {
                    issues.Add("invalid minute turnover point");
                    continue;
                }
                output.Add(new MinuteTurnoverPoint
                {
                    Time = time,
                    Price = price.Value,
                    CumulativeVolume = volume.Value,
                    CumulativeAmount = amount.Value,
                });
                previousTime = time;
                previousVolume = volume.Value;
                previousAmount = amount.Value;
            }
            return data.SelectToken("dragonMeta.cache.stale")?.Value<bool>() == true
                ? DataFreshness.Stale
                : DataFreshness.Fresh;
        }

        private static IReadOnlyList<MinuteTurnoverPoint> ParseMinuteData(JObject data)
        {
            DateTime date;
            if (data == null || !DateTime.TryParseExact((string)data["date"], "yyyyMMdd",
                CultureInfo.InvariantCulture, DateTimeStyles.None, out date) || !(data["points"] is JArray))
                throw new PayloadParseException("invalid TDX minute payload");

            var output = new List<MinuteTurnoverPoint>();
            DateTime? previous = null;
            double previousVolume = 0;
            double previousAmount = 0;
            foreach (var row in ((JArray)data["points"]).OfType<JObject>())
            {
                DateTime time;
                var price = FiniteNumber(row["price"]);
                var volume = FiniteNumber(row["cumulativeVolume"]);
                var amount = FiniteNumber(row["cumulativeAmount"]);
                if (!DateTime.TryParseExact(date.ToString("yyyyMMdd") + (string)row["time"],
                        "yyyyMMddHHmm", CultureInfo.InvariantCulture, DateTimeStyles.None, out time))
                    throw new PayloadParseException("invalid TDX minute row");
                if (time.TimeOfDay > new TimeSpan(15, 0, 0)) continue;
                if (
                    !price.HasValue || !volume.HasValue || !amount.HasValue ||
                    price <= 0 || volume < 0 || amount < 0 || !IsTradingTime(time) ||
                    previous.HasValue && (time <= previous || volume < previousVolume || amount < previousAmount))
                    throw new PayloadParseException("invalid TDX minute row");
                output.Add(new MinuteTurnoverPoint
                {
                    Time = time, Price = price.Value, CumulativeVolume = volume.Value,
                    CumulativeAmount = amount.Value,
                });
                previous = time;
                previousVolume = volume.Value;
                previousAmount = amount.Value;
            }
            return output;
        }

        private static bool IsTradingTime(DateTime value)
        {
            var time = value.TimeOfDay;
            return (time >= new TimeSpan(9, 30, 0) && time <= new TimeSpan(11, 30, 0)) ||
                   (time >= new TimeSpan(13, 0, 0) && time <= new TimeSpan(15, 0, 0));
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
            return ParseLimitUpRow(row);
        }

        private static LimitUpContext ParseLimitUpRow(JObject row)
        {
            return new LimitUpContext
            {
                SealAmount = FiniteNumber(row?["order_amount"]),
                SealVolume = FiniteNumber(row?["order_volume"]),
                OpenCount = FiniteNumber(row?["open_num"]).HasValue ? (int?)FiniteNumber(row["open_num"]).Value : null,
                HighDays = (string)row?["high_days"],
                SuccessRate = FiniteNumber(row?["limit_up_suc_rate"]),
                TurnoverRate = FiniteNumber(row?["turnover_rate"]),
                ReasonType = (string)row?["reason_type"],
                FirstLimitTime = (string)row?["first_limit_up_time"],
                LastLimitTime = (string)row?["last_limit_up_time"],
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

        private static double RequiredAmount(JToken money, JToken displayValue)
        {
            var value = ChineseAmount(money) ?? ChineseAmount(displayValue);
            if (!value.HasValue) throw new PayloadParseException("invalid money");
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
