using System.Text.Json;
using YiDongJingLing.Events;
using YiDongJingLing.MarketData;
using Xunit;

namespace YiDongJingLing.Tests;

public sealed class OpeningWeakToStrongReplayFixtureTests
{
    [Fact]
    public void Public_platform_probe_fixture_is_rejected_when_auction_checkpoints_are_incomplete()
    {
        var fixture = LoadFixture("public-platform-probe-2026-06-05.json");

        Assert.False(fixture.HasCompleteOpeningReplay());
        Assert.Contains("09:20", fixture.MissingCheckpointTimes());
        Assert.Contains("09:24", fixture.MissingCheckpointTimes());
        Assert.Contains("09:35", fixture.MissingCheckpointTimes());
    }

    [Fact]
    public void Complete_replay_fixture_emits_candidate_then_voice_eligible_gap_and_trend_events()
    {
        var fixture = LoadFixture("opening-replay-complete-2026-06-05.json");

        Assert.True(fixture.HasCompleteOpeningReplay());

        var engine = new L1EventEngine(openingWeakRules: L1EventEngine.DefaultOpeningRules());
        var history = new List<QuoteSnapshot>();
        var openingEvents = new List<EventRecord>();

        foreach (var quote in fixture.ToQuotes())
        {
            if (MainForm.IsOpeningWeakToStrongPreopenWindow(quote.SourceTime))
            {
                engine.Prime(quote);
                if (MainForm.ShouldEvaluateOpeningWeakToStrongPreopenQuote(quote.SourceTime))
                {
                    openingEvents.AddRange(engine
                        .Evaluate(quote, history.LastOrDefault(), history)
                        .Where(item => item.Type == L1EventType.OpeningWeakToStrong));
                }
            }
            else
            {
                openingEvents.AddRange(engine
                    .Evaluate(quote, history.LastOrDefault(), history)
                    .Where(item => item.Type == L1EventType.OpeningWeakToStrong));
            }
            history.Add(quote);
        }

        var stages = openingEvents.Select(item => item.OpeningSignal?.Stage).ToArray();
        Assert.Equal(new[] { "auctionConditionPassed", "gapAlert", "trendConfirm" }, stages);
        Assert.Equal(new[] { false, true, true }, openingEvents.Select(item => item.OpeningSignal?.VoiceEligible == true));
    }

    [Fact]
    public void Missing_early_baseline_replay_still_evaluates_09_25_checkpoint()
    {
        var fixture = LoadFixture("opening-replay-missing-0920-2026-06-05.json");

        Assert.False(fixture.HasCompleteOpeningReplay());
        Assert.Contains("09:20", fixture.MissingCheckpointTimes());

        var engine = new L1EventEngine(openingWeakRules: L1EventEngine.DefaultOpeningRules());
        var history = new List<QuoteSnapshot>();
        var openingEvents = new List<EventRecord>();

        foreach (var quote in fixture.ToQuotes())
        {
            if (MainForm.IsOpeningWeakToStrongPreopenWindow(quote.SourceTime))
            {
                engine.Prime(quote);
            }
            openingEvents.AddRange(engine
                .Evaluate(quote, history.LastOrDefault(), history)
                .Where(item => item.Type == L1EventType.OpeningWeakToStrong));
            history.Add(quote);
        }

        Assert.NotEmpty(openingEvents);
        Assert.Equal("auctionConditionFailed", openingEvents[0].OpeningSignal?.Stage);
        Assert.False(openingEvents[0].OpeningSignal?.VoiceEligible);
    }

    private static ReplayFixture LoadFixture(string fileName)
    {
        var path = Path.Combine(
            ProjectRootLocator.Find(),
            "tools",
            "YiDongJingLing",
            "YiDongJingLing.Tests",
            "fixtures",
            fileName);
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        return ReplayFixture.FromJson(document.RootElement);
    }

    private sealed record ReplayFixture(string Source, ReplayQuote[] Quotes)
    {
        public static ReplayFixture FromJson(JsonElement element)
        {
            return new ReplayFixture(
                element.GetProperty("source").GetString() ?? "",
                element.GetProperty("quotes")
                    .EnumerateArray()
                    .Select(ReplayQuote.FromJson)
                    .ToArray());
        }

        public bool HasCompleteOpeningReplay()
        {
            return MissingCheckpointTimes().Count == 0;
        }

        public IReadOnlyList<string> MissingCheckpointTimes()
        {
            var times = Quotes
                .Select(item => item.At.ToLocalTime().ToString("HH:mm"))
                .ToHashSet(StringComparer.Ordinal);
            return new[] { "09:20", "09:24", "09:25", "09:30", "09:35" }
                .Where(item => !times.Contains(item))
                .ToArray();
        }

        public IEnumerable<QuoteSnapshot> ToQuotes()
        {
            return Quotes.Select(item =>
                new QuoteSnapshot(
                    item.Code,
                    item.Name,
                    item.LastPrice,
                    item.PreClose > 0m ? (item.LastPrice - item.PreClose) / item.PreClose * 100m : 0m,
                    item.PreClose > 0m ? item.LastPrice - item.PreClose : 0m,
                    item.Volume,
                    item.Amount,
                    item.Open,
                    item.LastPrice,
                    item.LastPrice,
                    item.PreClose,
                    [],
                    [],
                    item.At,
                    item.At,
                    item.At,
                    item.OpeningForcedSample));
        }
    }

    private sealed record ReplayQuote(
        string Code,
        string Name,
        DateTimeOffset At,
        decimal LastPrice,
        decimal PreClose,
        decimal Open,
        decimal Amount,
        decimal Volume,
        bool OpeningForcedSample)
    {
        public static ReplayQuote FromJson(JsonElement element)
        {
            return new ReplayQuote(
                element.GetProperty("code").GetString() ?? "",
                element.GetProperty("name").GetString() ?? "",
                DateTimeOffset.Parse(element.GetProperty("at").GetString() ?? ""),
                element.GetProperty("lastPrice").GetDecimal(),
                element.GetProperty("preClose").GetDecimal(),
                element.TryGetProperty("open", out var open) ? open.GetDecimal() : 0m,
                element.GetProperty("amount").GetDecimal(),
                element.GetProperty("volume").GetDecimal(),
                element.TryGetProperty("openingForcedSample", out var forced) && forced.GetBoolean());
        }
    }
}
