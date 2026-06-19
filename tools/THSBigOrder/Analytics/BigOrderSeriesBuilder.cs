using System;
using System.Collections.Generic;
using System.Linq;

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
    }

    public sealed class BigOrderSeriesBuilder
    {
        private static readonly double[] AmountThresholds =
        {
            300000, 500000, 1000000, 3000000, 5000000, 7000000, 10000000,
        };

        public BigOrderSeries Build(IEnumerable<BigOrderItem> source)
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

            return new BigOrderSeries { Minutes = minutes, NetFlow = netFlow, Thresholds = thresholds };
        }
    }
}
