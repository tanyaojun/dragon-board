using System.Collections.Generic;
using System.Linq;

namespace THSBigOrder.Filtering
{
    public enum OrderSide { All, Buy, Sell }

    public static class OrderFilter
    {
        public static List<BigOrderItem> Apply(
            IEnumerable<BigOrderItem> source,
            double minimumAmount,
            OrderSide side,
            string specialMarker)
        {
            var query = (source ?? Enumerable.Empty<BigOrderItem>())
                .Where(item => item.Amount >= minimumAmount);
            if (side == OrderSide.Buy) query = query.Where(item => item.IsBuy);
            if (side == OrderSide.Sell) query = query.Where(item => item.IsSell);
            if (!string.IsNullOrWhiteSpace(specialMarker))
                query = query.Where(item => item.FundMarker == specialMarker || item.BuyMarker == specialMarker);
            return query.ToList();
        }
    }
}
