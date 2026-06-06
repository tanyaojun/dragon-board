using YiDongJingLing;
using Xunit;

namespace YiDongJingLing.Tests;

public sealed class MainFormOpeningRoutingTests
{
    [Fact]
    public void Opening_preopen_checkpoint_should_be_evaluated_even_when_quote_is_first_seen()
    {
        var checkpoint = DateTimeOffset.Parse("2026-06-05T09:25:00+08:00");

        Assert.True(MainForm.ShouldEvaluateOpeningWeakToStrongPreopenQuote(checkpoint));
    }

    [Fact]
    public void Opening_preopen_initial_baseline_window_should_only_prime()
    {
        var initialBaseline = DateTimeOffset.Parse("2026-06-05T09:20:00+08:00");

        Assert.False(MainForm.ShouldEvaluateOpeningWeakToStrongPreopenQuote(initialBaseline));
    }
}
