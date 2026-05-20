namespace YiDongJingLing.MarketData;

public sealed class QuoteStateStore
{
    private readonly Dictionary<string, QuoteSnapshot> _latest = new(StringComparer.Ordinal);
    private readonly Dictionary<string, List<QuoteSnapshot>> _history = new(StringComparer.Ordinal);
    private readonly TimeSpan _historyWindow = TimeSpan.FromMinutes(3);

    public QuoteSnapshot? GetLatest(string code)
    {
        return _latest.TryGetValue(code, out var quote) ? quote : null;
    }

    public IReadOnlyList<QuoteSnapshot> GetHistory(string code)
    {
        return _history.TryGetValue(code, out var history) ? history : Array.Empty<QuoteSnapshot>();
    }

    public QuoteSnapshot? Apply(QuoteSnapshot quote)
    {
        _latest.TryGetValue(quote.Code, out var previous);
        _latest[quote.Code] = quote;

        if (!_history.TryGetValue(quote.Code, out var history))
        {
            history = [];
            _history[quote.Code] = history;
        }

        history.Add(quote);
        var cutoff = quote.SourceTime - _historyWindow;
        history.RemoveAll(item => item.SourceTime < cutoff);
        return previous;
    }

    public void Clear()
    {
        _latest.Clear();
        _history.Clear();
    }
}
