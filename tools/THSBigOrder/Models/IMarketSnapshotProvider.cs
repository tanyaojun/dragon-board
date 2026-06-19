using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace THSBigOrder.Models
{
    public interface IMarketSnapshotProvider
    {
        Task<MarketSnapshot> LoadSnapshotAsync(string stockCode, CancellationToken cancellationToken);
        void CalculateMarkers(List<BigOrderItem> data);
    }
}
