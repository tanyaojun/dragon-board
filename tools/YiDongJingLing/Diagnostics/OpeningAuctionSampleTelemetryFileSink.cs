using System.Text;
using System.Text.Json;
using YiDongJingLing.Events;

namespace YiDongJingLing.Diagnostics;

public sealed class OpeningAuctionSampleTelemetryFileSink
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly string _directory;
    private readonly Action<string>? _log;
    private bool _reportedFailure;

    public OpeningAuctionSampleTelemetryFileSink(string directory, Action<string>? log = null)
    {
        _directory = directory;
        _log = log;
    }

    public void Record(OpeningAuctionSampleTelemetryRecord record)
    {
        try
        {
            Directory.CreateDirectory(_directory);
            var path = Path.Combine(_directory, $"opening-auction-samples-{record.TradingDate}.jsonl");
            var json = JsonSerializer.Serialize(record, JsonOptions);
            File.AppendAllText(path, json + Environment.NewLine, Encoding.UTF8);
        }
        catch (Exception ex)
        {
            if (_reportedFailure) return;
            _reportedFailure = true;
            _log?.Invoke($"竞价采样 telemetry 写入失败: {ex.Message}");
        }
    }
}
