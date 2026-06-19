using System;
using System.Collections.Generic;
using System.Linq;
using THSBigOrder.Models;

namespace THSBigOrder.Analytics
{
    public sealed class MinuteFlow
    {
        public DateTime Minute { get; set; }
        public double BuyAmount { get; set; }
        public double SellAmount { get; set; }
    }

    public sealed class NetFlowPoint
    {
        public DateTime Time { get; set; }
        public double Value { get; set; }
    }

    public sealed class ThresholdFlow
    {
        public double Amount { get; set; }
        public double BuyAmount { get; set; }
        public double SellAmount { get; set; }
        public double NetAmount => BuyAmount - SellAmount;
    }

    public sealed class BigOrderSeries
    {
        public IReadOnlyList<MinuteFlow> Minutes { get; set; }
        public IReadOnlyList<NetFlowPoint> NetFlow { get; set; }
        public IReadOnlyList<ThresholdFlow> Thresholds { get; set; }
        public IReadOnlyList<HalfHourAmount> HalfHours { get; set; }
    }

    public sealed class HalfHourAmount
    {
        public string Label { get; set; }
        public double? TotalAmount { get; set; }
        public double BigOrderAmount { get; set; }
    }

    public sealed class BigOrderSeriesBuilder
    {
        private static readonly double[] AmountThresholds =
        {
            300000, 500000, 1000000, 3000000, 5000000, 7000000, 10000000,
        };

        public BigOrderSeries Build(IEnumerable<BigOrderItem> source)
        {
            return Build(source, new MinuteTurnoverPoint[0], DataFreshness.Missing);
        }

        public BigOrderSeries Build(
            IEnumerable<BigOrderItem> source,
            IEnumerable<MinuteTurnoverPoint> turnover,
            DataFreshness turnoverFreshness)
        {
            var orders = (source ?? Enumerable.Empty<BigOrderItem>()).OrderBy(item => item.Time).ToList();
            var minutes = orders
                .GroupBy(item => new DateTime(item.Time.Year, item.Time.Month, item.Time.Day, item.Time.Hour, item.Time.Minute, 0))
                .OrderBy(group => group.Key)
                .Select(group => new MinuteFlow
                {
                    Minute = group.Key,
                    BuyAmount = group.Where(item => item.IsBuy).Sum(item => item.Amount),
                    SellAmount = group.Where(item => item.IsSell).Sum(item => item.Amount),
                })
                .ToList();

            double cumulative = 0;
            var netFlow = minutes.Select(minute =>
            {
                cumulative += minute.BuyAmount - minute.SellAmount;
                return new NetFlowPoint { Time = minute.Minute, Value = cumulative };
            }).ToList();

            var thresholds = AmountThresholds.Select(amount => new ThresholdFlow
            {
                Amount = amount,
                BuyAmount = orders.Where(item => item.IsBuy && item.Amount >= amount).Sum(item => item.Amount),
                SellAmount = orders.Where(item => item.IsSell && item.Amount >= amount).Sum(item => item.Amount),
            }).ToList();

            var hasTurnover = turnoverFreshness == DataFreshness.Fresh ||
                              turnoverFreshness == DataFreshness.Stale;
            var halfHours = CreateHalfHours(hasTurnover);
            foreach (var order in orders)
            {
                var index = HalfHourIndex(order.Time);
                if (index >= 0) halfHours[index].BigOrderAmount += order.Amount;
            }

            if (hasTurnover)
            {
                double previousAmount = 0;
                foreach (var point in (turnover ?? Enumerable.Empty<MinuteTurnoverPoint>())
                    .OrderBy(value => value.Time))
                {
                    var index = HalfHourIndex(point.Time);
                    var delta = point.CumulativeAmount - previousAmount;
                    if (index >= 0 && delta >= 0)
                        halfHours[index].TotalAmount = halfHours[index].TotalAmount.GetValueOrDefault() + delta;
                    previousAmount = point.CumulativeAmount;
                }
            }

            return new BigOrderSeries
            {
                Minutes = minutes,
                NetFlow = netFlow,
                Thresholds = thresholds,
                HalfHours = halfHours,
            };
        }

        private static List<HalfHourAmount> CreateHalfHours(bool hasTurnover)
        {
            var labels = new[]
            {
                "09:30-10:00", "10:00-10:30", "10:30-11:00", "11:00-11:30",
                "13:00-13:30", "13:30-14:00", "14:00-14:30", "14:30-15:00",
            };
            return labels.Select(label => new HalfHourAmount
            {
                Label = label,
                TotalAmount = hasTurnover ? (double?)0 : null,
            }).ToList();
        }

        private static int HalfHourIndex(DateTime time)
        {
            var minutes = time.Hour * 60 + time.Minute;
            const int morningStart = 9 * 60 + 30;
            const int morningEnd = 11 * 60 + 30;
            const int afternoonStart = 13 * 60;
            const int afternoonEnd = 15 * 60;
            if (minutes >= morningStart && minutes <= morningEnd)
                return minutes == morningEnd ? 3 : (minutes - morningStart) / 30;
            if (minutes >= afternoonStart && minutes <= afternoonEnd)
                return minutes == afternoonEnd ? 7 : 4 + (minutes - afternoonStart) / 30;
            return -1;
        }
    }
}
