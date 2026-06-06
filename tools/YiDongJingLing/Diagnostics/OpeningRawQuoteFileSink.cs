using System.Text;
using System.Text.Json;
using YiDongJingLing.MarketData;

namespace YiDongJingLing.Diagnostics;

public sealed class OpeningRawQuoteFileSink
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly string _directory;
    private readonly Action<string>? _log;
    private bool _reportedFailure;

    public OpeningRawQuoteFileSink(string directory, Action<string>? log = null)
    {
        _directory = directory;
        _log = log;
    }

    public void Record(QuoteSnapshot quote, string source)
    {
        try
        {
            Directory.CreateDirectory(_directory);
            var tradingDate = quote.SourceTime.ToLocalTime().ToString("yyyy-MM-dd");
            var path = Path.Combine(_directory, $"opening-raw-quotes-{tradingDate}.jsonl");
            var json = JsonSerializer.Serialize(
                new
                {
                    Source = source,
                    TradingDate = tradingDate,
                    Timestamp = quote.SourceTime,
                    quote.Code,
                    quote.Name,
                    quote.LastPrice,
                    quote.PreClose,
                    quote.Open,
                    quote.High,
                    quote.Low,
                    quote.ChangePct,
                    quote.ChangeAmount,
                    quote.Volume,
                    quote.Amount,
                    quote.OpeningForcedSample,
                    quote.RequestedCount,
                    quote.ReceivedCount,
                    quote.ElapsedMs,
                    quote.SlowBatches,
                    quote.TruncatedBatches,
                    quote.CapturedAt,
                    quote.BridgeTs,
                },
                JsonOptions);
            File.AppendAllText(path, json + Environment.NewLine, Encoding.UTF8);
        }
        catch (Exception ex)
        {
            if (_reportedFailure) return;
            _reportedFailure = true;
            _log?.Invoke($"竞价原始 quote 写入失败: {ex.Message}");
        }
    }
}
