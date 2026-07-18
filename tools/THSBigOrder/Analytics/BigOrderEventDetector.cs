using System;
using System.Collections.Generic;
using System.Linq;

namespace THSBigOrder.Analytics
{
    internal sealed class BigOrderEventDetector
    {
        private const double AbsoluteLargeOrder = 5000000d;
        private const double ActivePurity = 0.70d;
        private const double MinimumPriceImpact = 0.0003d;
        private static readonly TimeSpan EventWindow = TimeSpan.FromSeconds(10);
        private static readonly TimeSpan ConfirmationStart = TimeSpan.FromSeconds(8);
        private static readonly TimeSpan ConfirmationEnd = TimeSpan.FromSeconds(10);
        private static readonly TimeSpan Cooldown = TimeSpan.FromSeconds(20);

        public void Apply(IList<BigOrderItem> data)
        {
            if (data == null) return;
            foreach (var item in data)
            {
                if (item == null) continue;
                item.FundMarker = "";
                item.BuyMarker = "";
            }

            var rows = data.Select((item, index) => new IndexedRow(item, index))
                .Where(value => IsValid(value.Item))
                .OrderBy(value => value.Item.Time)
                .ThenBy(value => value.Index)
                .ToList();
            if (rows.Count == 0) return;

            var thresholdCache = new Dictionary<string, double>();
            foreach (var dayGroup in rows.GroupBy(value => value.Item.Time.Date))
            {
                var dayRows = dayGroup.ToList();
                ApplySession(dayRows.Where(value => Session(value.Item.Time) == 1).ToList(),
                    dayRows, thresholdCache);
                ApplySession(dayRows.Where(value => Session(value.Item.Time) == 2).ToList(),
                    dayRows, thresholdCache);
            }
        }

        private static void ApplySession(
            List<IndexedRow> sessionRows,
            List<IndexedRow> dayRows,
            IDictionary<string, double> thresholdCache)
        {
            if (sessionRows.Count == 0) return;
            var buckets = sessionRows.GroupBy(value => TruncateSecond(value.Item.Time))
                .Select(group => new SecondBucket(group.Key, group.ToList()))
                .OrderBy(value => value.Time)
                .ToList();
            var bucketIndexes = buckets.Select((bucket, index) => new { bucket.Time, index })
                .ToDictionary(value => value.Time, value => value.index);
            var lastConfirmed = new Dictionary<int, DateTime>();
            var windowStart = 0;

            for (var bucketIndex = 0; bucketIndex < buckets.Count; bucketIndex++)
            {
                var bucket = buckets[bucketIndex];
                while (windowStart < sessionRows.Count &&
                       sessionRows[windowStart].Item.Time < bucket.Time - EventWindow)
                    windowStart++;
                List<IndexedRow> window = null;

                foreach (var direction in new[] { 2, 4 })
                {
                    if (!bucket.Rows.Any(value => value.Item.Type == direction &&
                                                  value.Item.Amount >= AbsoluteLargeOrder))
                        continue;
                    var threshold = Threshold(dayRows, bucket.Time, direction, thresholdCache);
                    if (!bucket.Rows.Any(value => value.Item.Type == direction &&
                                                  value.Item.Amount >= threshold))
                        continue;
                    if (window == null)
                    {
                        var windowEnd = UpperBound(sessionRows, bucket.Time);
                        window = sessionRows.GetRange(windowStart, windowEnd - windowStart);
                    }
                    var qualifying = window.Where(value => value.Item.Type == direction &&
                        value.Item.Amount >= Threshold(
                            dayRows, value.Item.Time, direction, thresholdCache)).ToList();
                    if (qualifying.Count < 3 || DirectionPurity(window, direction) < ActivePurity)
                        continue;

                    var firstSecond = TruncateSecond(qualifying[0].Item.Time);
                    int firstBucketIndex;
                    if (!bucketIndexes.TryGetValue(firstSecond, out firstBucketIndex) ||
                        firstBucketIndex == 0)
                        continue;
                    var baseline = buckets[firstBucketIndex - 1].Price;
                    var impact = DirectionalMove(baseline, bucket.Price, direction);
                    if (impact < MinimumPriceImpact) continue;

                    var confirmation = ConfirmationBucket(buckets, bucketIndex, bucket.Time);
                    if (confirmation == null) continue;
                    var retained = DirectionalMove(baseline, confirmation.Price, direction);
                    if (retained < impact * 0.5d) continue;

                    DateTime previous;
                    if (lastConfirmed.TryGetValue(direction, out previous) &&
                        bucket.Time - previous < Cooldown)
                        continue;

                    var display = bucket.Rows.Where(value => value.Item.Type == direction)
                        .OrderByDescending(value => value.Item.Amount)
                        .ThenBy(value => value.Index)
                        .First().Item;
                    display.FundMarker = direction == 2 ? "点火" : "砸盘";
                    if (direction == 2 && HasBuyFollowThrough(
                        sessionRows, bucket.Time, threshold))
                        display.BuyMarker = "买活跃";
                    if (direction == 4 && HasGoodSupport(
                        sessionRows, buckets, bucketIndex, bucket.Time,
                        confirmation, baseline, threshold))
                        display.BuyMarker = "承接好";
                    lastConfirmed[direction] = bucket.Time;
                    break;
                }
            }
        }

        private static bool HasBuyFollowThrough(
            IEnumerable<IndexedRow> rows, DateTime eventTime, double threshold)
        {
            var after = rows.Where(value => value.Item.Time > eventTime &&
                value.Item.Time <= eventTime.AddSeconds(8)).ToList();
            var buys = after.Where(value => value.Item.Type == 2).ToList();
            return buys.Count >= 2 && buys.Sum(value => value.Item.Amount) >= threshold &&
                   DirectionPurity(after, 2) >= ActivePurity;
        }

        private static bool HasGoodSupport(
            IEnumerable<IndexedRow> rows,
            IList<SecondBucket> buckets,
            int eventBucketIndex,
            DateTime eventTime,
            SecondBucket confirmation,
            double baseline,
            double threshold)
        {
            var pressure = rows.Where(value =>
                value.Item.Time >= eventTime - EventWindow && value.Item.Time <= eventTime &&
                (value.Item.Type == 3 || value.Item.Type == 4)).ToList();
            var pressureAmount = pressure.Sum(value => value.Item.Amount);
            if (pressure.Count < 5 || pressureAmount < threshold * 2d) return false;

            var passiveAmount = pressure.Where(value => value.Item.Type == 3)
                .Sum(value => value.Item.Amount);
            var after = rows.Where(value => value.Item.Time > eventTime &&
                value.Item.Time <= eventTime.AddSeconds(8)).ToList();
            var counterAmount = after.Where(value => value.Item.Type == 2)
                .Sum(value => value.Item.Amount);
            if (passiveAmount / pressureAmount < 0.30d && counterAmount < threshold)
                return false;

            var response = buckets.Skip(eventBucketIndex + 1)
                .TakeWhile(value => value.Time <= confirmation.Time).ToList();
            if (response.Count == 0) return false;
            var low = response.Min(value => value.Price);
            var maximumDrop = baseline - low;
            return maximumDrop > 0d && confirmation.Price > low &&
                   confirmation.Price - low >= maximumDrop * 0.5d;
        }

        private static double DirectionPurity(IEnumerable<IndexedRow> rows, int direction)
        {
            var active = rows.Where(value => value.Item.Type == 2 || value.Item.Type == 4)
                .ToList();
            var total = active.Sum(value => value.Item.Amount);
            if (total <= 0d) return 0d;
            return active.Where(value => value.Item.Type == direction)
                .Sum(value => value.Item.Amount) / total;
        }

        private static double Threshold(
            IEnumerable<IndexedRow> dayRows,
            DateTime eventTime,
            int direction,
            IDictionary<string, double> cache)
        {
            var minute = TradingMinute(eventTime);
            var key = eventTime.Date.ToString("yyyyMMdd") + "|" + direction + "|" + minute;
            double cached;
            if (cache.TryGetValue(key, out cached)) return cached;
            var amounts = dayRows.Where(value => value.Item.Type == direction)
                .Where(value =>
                {
                    var valueMinute = TradingMinute(value.Item.Time);
                    return valueMinute >= minute - 20 && valueMinute < minute;
                })
                .Select(value => value.Item.Amount)
                .OrderBy(value => value)
                .ToList();
            var threshold = AbsoluteLargeOrder;
            if (amounts.Count >= 30)
            {
                var percentileIndex = Math.Max(0, (int)Math.Ceiling(amounts.Count * 0.90d) - 1);
                threshold = Math.Max(threshold, amounts[percentileIndex]);
            }
            cache[key] = threshold;
            return threshold;
        }

        private static SecondBucket ConfirmationBucket(
            IList<SecondBucket> buckets, int eventIndex, DateTime eventTime)
        {
            if (buckets.Count == 0 || buckets[buckets.Count - 1].Time <= eventTime + ConfirmationEnd)
                return null;
            SecondBucket result = null;
            for (var index = eventIndex + 1; index < buckets.Count; index++)
            {
                var elapsed = buckets[index].Time - eventTime;
                if (elapsed > ConfirmationEnd) break;
                if (elapsed >= ConfirmationStart) result = buckets[index];
            }
            return result;
        }

        private static int UpperBound(IList<IndexedRow> rows, DateTime time)
        {
            var low = 0;
            var high = rows.Count;
            while (low < high)
            {
                var middle = low + (high - low) / 2;
                if (rows[middle].Item.Time <= time) low = middle + 1;
                else high = middle;
            }
            return low;
        }

        private static double DirectionalMove(double baseline, double price, int direction)
        {
            if (baseline <= 0d) return 0d;
            return direction == 2 ? (price - baseline) / baseline : (baseline - price) / baseline;
        }

        private static int TradingMinute(DateTime time)
        {
            var date = time.Date;
            if (time <= date.AddHours(11).AddMinutes(30))
                return Math.Min(119, Math.Max(0,
                    (int)(time - date.AddHours(9).AddMinutes(30)).TotalMinutes));
            return 120 + Math.Min(119, Math.Max(0,
                (int)(time - date.AddHours(13)).TotalMinutes));
        }

        private static int Session(DateTime time)
        {
            var date = time.Date;
            if (time >= date.AddHours(9).AddMinutes(30) &&
                time <= date.AddHours(11).AddMinutes(30)) return 1;
            if (time >= date.AddHours(13) && time <= date.AddHours(15)) return 2;
            return 0;
        }

        private static bool IsValid(BigOrderItem item)
        {
            return item != null && item.Type >= 1 && item.Type <= 4 &&
                   item.Amount >= 0d && !double.IsNaN(item.Amount) &&
                   !double.IsInfinity(item.Amount) && item.Price > 0d &&
                   !double.IsNaN(item.Price) && !double.IsInfinity(item.Price) &&
                   Session(item.Time) != 0;
        }

        private static DateTime TruncateSecond(DateTime time)
        {
            return new DateTime(time.Year, time.Month, time.Day,
                time.Hour, time.Minute, time.Second, time.Kind);
        }

        private sealed class IndexedRow
        {
            public IndexedRow(BigOrderItem item, int index)
            {
                Item = item;
                Index = index;
            }

            public BigOrderItem Item { get; private set; }
            public int Index { get; private set; }
        }

        private sealed class SecondBucket
        {
            public SecondBucket(DateTime time, List<IndexedRow> rows)
            {
                Time = time;
                Rows = rows;
                var weighted = rows.Where(value => value.Item.Amount > 0d).ToList();
                var amount = weighted.Sum(value => value.Item.Amount);
                Price = amount > 0d
                    ? weighted.Sum(value => value.Item.Price * value.Item.Amount) / amount
                    : rows.Average(value => value.Item.Price);
            }

            public DateTime Time { get; private set; }
            public List<IndexedRow> Rows { get; private set; }
            public double Price { get; private set; }
        }
    }
}
