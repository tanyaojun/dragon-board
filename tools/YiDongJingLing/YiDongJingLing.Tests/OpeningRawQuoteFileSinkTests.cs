using System.Text.Json;
using YiDongJingLing.Diagnostics;
using YiDongJingLing.MarketData;
using Xunit;

namespace YiDongJingLing.Tests;

public sealed class OpeningRawQuoteFileSinkTests
{
    [Fact]
    public void Raw_quote_sink_writes_received_quote_fields_for_replay()
    {
        using var temp = new TempDirectory();
        var sink = new OpeningRawQuoteFileSink(temp.Path);
        var at = DateTimeOffset.Parse("2026-06-05T09:15:00+08:00");
        var quote = new QuoteSnapshot(
            "002552",
            "宝鼎科技",
            9.8m,
            -2m,
            -0.2m,
            100000m,
            1000000m,
            0m,
            9.8m,
            9.8m,
            10m,
            [],
            [],
            at,
            at,
            at,
            true,
            1,
            1,
            12,
            0,
            0);

        sink.Record(quote, "yidong-jingling-ws");

        var path = System.IO.Path.Combine(temp.Path, "opening-raw-quotes-2026-06-05.jsonl");
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var row = document.RootElement;
        Assert.Equal("yidong-jingling-ws", row.GetProperty("source").GetString());
        Assert.Equal("002552", row.GetProperty("code").GetString());
        Assert.Equal(9.8m, row.GetProperty("lastPrice").GetDecimal());
        Assert.Equal(1000000m, row.GetProperty("amount").GetDecimal());
        Assert.True(row.GetProperty("openingForcedSample").GetBoolean());
    }

    private sealed class TempDirectory : IDisposable
    {
        public string Path { get; } = System.IO.Path.Combine(
            System.IO.Path.GetTempPath(),
            "yidong-raw-quotes-" + Guid.NewGuid().ToString("N"));

        public TempDirectory()
        {
            Directory.CreateDirectory(Path);
        }

        public void Dispose()
        {
            if (Directory.Exists(Path))
            {
                foreach (var file in Directory.EnumerateFiles(Path))
                {
                    File.Delete(file);
                }
                Directory.Delete(Path);
            }
        }
    }
}
