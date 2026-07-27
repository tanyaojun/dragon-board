using System;
using System.Threading;

namespace THSBigOrder.Refresh
{
    public sealed class RefreshRequest
    {
        public bool ShouldRun { get; set; }
        public string StockCode { get; set; }
        public long Generation { get; set; }
        public CancellationToken CancellationToken { get; set; }
    }

    public sealed class RefreshCoordinator : IDisposable
    {
        private readonly object _gate = new object();
        private CancellationTokenSource _active;
        private string _activeCode;
        private long _generation;

        public RefreshRequest Begin(string stockCode, bool forceForCodeChange)
        {
            lock (_gate)
            {
                if (_active != null && !_active.IsCancellationRequested &&
                    string.Equals(_activeCode, stockCode, StringComparison.Ordinal) && !forceForCodeChange)
                {
                    return new RefreshRequest { ShouldRun = false, StockCode = stockCode, Generation = _generation };
                }
                if (_active != null)
                {
                    _active.Cancel();
                    _active.Dispose();
                }
                _active = new CancellationTokenSource();
                _activeCode = stockCode;
                _generation++;
                return new RefreshRequest
                {
                    ShouldRun = true,
                    StockCode = stockCode,
                    Generation = _generation,
                    CancellationToken = _active.Token,
                };
            }
        }

        public bool IsLatest(long generation, string stockCode)
        {
            lock (_gate)
                return generation == _generation && string.Equals(stockCode, _activeCode, StringComparison.Ordinal);
        }

        public void Complete(long generation)
        {
            lock (_gate)
            {
                if (generation != _generation) return;
                _active?.Dispose();
                _active = null;
                _activeCode = null;
            }
        }

        public void Dispose()
        {
            lock (_gate)
            {
                _generation++;
                _active?.Cancel();
                _active?.Dispose();
                _active = null;
                _activeCode = null;
            }
        }
    }
}
