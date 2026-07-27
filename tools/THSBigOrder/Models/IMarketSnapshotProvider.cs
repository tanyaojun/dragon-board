using System.Collections.Generic;
using System;
using System.Threading;
using System.Threading.Tasks;

namespace THSBigOrder.Models
{
    public interface IMarketSnapshotProvider
    {
        Task<MarketSnapshot> LoadSnapshotAsync(string stockCode, CancellationToken cancellationToken);
        void CalculateMarkers(List<BigOrderItem> data);
    }

    public sealed class MarketLoadRequest
    {
        public string StockCode { get; set; }
        public DateTime RequestedDate { get; set; }
        public DateTime SessionDate { get; set; }
    }

    public interface ISessionMarketSnapshotProvider : IMarketSnapshotProvider
    {
        Task<MarketSnapshot> LoadSnapshotAsync(MarketLoadRequest request, CancellationToken cancellationToken);
    }
}
