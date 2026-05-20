namespace YiDongJingLing.MarketData;

public sealed record QuoteLevel(decimal Price, decimal Volume);

public sealed record QuoteSnapshot(
    string Code,
    string Name,
    decimal LastPrice,
    decimal ChangePct,
    decimal ChangeAmount,
    decimal Volume,
    decimal Amount,
    decimal Open,
    decimal High,
    decimal Low,
    decimal PreClose,
    IReadOnlyList<QuoteLevel> Bids,
    IReadOnlyList<QuoteLevel> Asks,
    DateTimeOffset SourceTime)
{
    public decimal Bid1Price => Bids.Count > 0 ? Bids[0].Price : 0m;
    public decimal Bid1Volume => Bids.Count > 0 ? Bids[0].Volume : 0m;
    public decimal Ask1Price => Asks.Count > 0 ? Asks[0].Price : 0m;
    public decimal Ask1Volume => Asks.Count > 0 ? Asks[0].Volume : 0m;
    public decimal BidVolume5 => Bids.Take(5).Sum(level => level.Volume);
    public decimal AskVolume5 => Asks.Take(5).Sum(level => level.Volume);
}
