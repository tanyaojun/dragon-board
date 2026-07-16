using System;
using System.Collections.Generic;
using System.Linq;

namespace THSBigOrder
{
    internal sealed class BigOrderAnnouncementTracker
    {
        private string _scope;
        private readonly Dictionary<string, int> _maximumCounts = new Dictionary<string, int>();

        public IReadOnlyList<BigOrderItem> Observe(
            string stockCode,
            BigOrderDataSource dataSource,
            DateTime sessionDate,
            IReadOnlyList<BigOrderItem> currentOrders)
        {
            var scope = stockCode + "|" + dataSource + "|" + sessionDate.Date.ToString("yyyyMMdd");
            var rows = currentOrders ?? new BigOrderItem[0];
            var counts = Count(rows);
            if (!string.Equals(_scope, scope, StringComparison.Ordinal))
            {
                _scope = scope;
                _maximumCounts.Clear();
                foreach (var pair in counts) _maximumCounts[pair.Key] = pair.Value;
                return new BigOrderItem[0];
            }

            var seen = new Dictionary<string, int>();
            var added = new List<BigOrderItem>();
            foreach (var row in rows.OrderBy(value => value.Time))
            {
                var fingerprint = Fingerprint(row);
                int current;
                seen.TryGetValue(fingerprint, out current);
                current++;
                seen[fingerprint] = current;
                int maximum;
                _maximumCounts.TryGetValue(fingerprint, out maximum);
                if (current > maximum) added.Add(row);
            }
            foreach (var pair in counts)
            {
                int maximum;
                _maximumCounts.TryGetValue(pair.Key, out maximum);
                if (pair.Value > maximum) _maximumCounts[pair.Key] = pair.Value;
            }
            return added;
        }

        public void Reset()
        {
            _scope = null;
            _maximumCounts.Clear();
        }

        private static Dictionary<string, int> Count(IEnumerable<BigOrderItem> rows)
        {
            var result = new Dictionary<string, int>();
            foreach (var row in rows)
            {
                var key = Fingerprint(row);
                int count;
                result.TryGetValue(key, out count);
                result[key] = count + 1;
            }
            return result;
        }

        private static string Fingerprint(BigOrderItem row)
        {
            return row.Time.Ticks + "|" + row.Type + "|" +
                   row.Volume.ToString("R", System.Globalization.CultureInfo.InvariantCulture) + "|" +
                   row.Amount.ToString("R", System.Globalization.CultureInfo.InvariantCulture) + "|" +
                   row.Price.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
        }
    }
}
