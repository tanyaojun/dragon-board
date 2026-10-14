using YiDongJingLing.Events;
using YiDongJingLing.MarketData;
using Xunit;

namespace YiDongJingLing.Tests;

public sealed class L1EventEngineTests
{
    private static QuoteSnapshot Quote(
        string name,
        decimal lastPrice,
        decimal changePct,
        decimal preClose,
        DateTimeOffset time,
        decimal open,
        decimal high,
        decimal? bid1Price = null,
        decimal bid1Volume = 0m)
    {
        var bids = bid1Price is null
            ? Array.Empty<QuoteLevel>()
            : new[] { new QuoteLevel(bid1Price.Value, bid1Volume) };
        return new QuoteSnapshot(
            "600000", name, lastPrice, changePct, 0m, 0m, 0m,
            open, high, open, preClose,
            bids, Array.Empty<QuoteLevel>(), time);
    }

    [Fact]
    public void New_stock_first_day_should_not_emit_limit_events_beyond_limit_pct()
    {
        var engine = new L1EventEngine();
        var at = DateTimeOffset.Parse("2026-10-13T09:32:00+08:00");
        // 新股首日无涨跌幅限制：发行价 10，现价 11.10（+11%），买一封在 11.10
        var quote = Quote("N新股份", 11.10m, 11m, 10m, at, open: 10.5m, high: 11.2m,
            bid1Price: 11.10m, bid1Volume: 5000);

        var events = engine.Evaluate(quote, null, Array.Empty<QuoteSnapshot>());

        Assert.DoesNotContain(events, item => item.Type is L1EventType.LimitUpSealed or L1EventType.NearLimitUp);
    }

    [Fact]
    public void New_stock_day_two_to_five_should_not_emit_limit_events()
    {
        var engine = new L1EventEngine();
        var at = DateTimeOffset.Parse("2026-10-13T09:32:00+08:00");
        // 第2-5日新股（C前缀）同样无涨跌幅限制：20% 档误判防护
        var quote = Quote("C新股份", 24.20m, 21m, 20m, at, open: 21m, high: 24.5m,
            bid1Price: 24.20m, bid1Volume: 5000);

        var events = engine.Evaluate(quote, null, Array.Empty<QuoteSnapshot>());

        Assert.DoesNotContain(events, item => item.Type is L1EventType.LimitUpSealed or L1EventType.NearLimitUp);
    }

    [Fact]
    public void Normal_stock_near_limit_should_still_emit()
    {
        var engine = new L1EventEngine();
        var at = DateTimeOffset.Parse("2026-10-13T09:32:00+08:00");
        var quote = Quote("普通股份", 10.95m, 9.5m, 10m, at, open: 10.2m, high: 10.98m);

        var events = engine.Evaluate(quote, null, Array.Empty<QuoteSnapshot>());

        Assert.Contains(events, item => item.Type == L1EventType.NearLimitUp);
        Assert.DoesNotContain(events, item => item.Type == L1EventType.NewStockOpened);
    }

    [Fact]
    public void New_stock_high_drawdown_should_emit_opened_once()
    {
        var engine = new L1EventEngine();
        var at = DateTimeOffset.Parse("2026-10-13T09:32:00+08:00");
        // 发行价 10，冲高 16（+60%），回落 15（自高点回撤 6.25% ≥ 5%）
        var surge = Quote("N新股份", 16m, 60m, 10m, at, open: 14m, high: 16m);
        engine.Evaluate(surge, null, Array.Empty<QuoteSnapshot>());
        var drop = Quote("N新股份", 15m, 50m, 10m, at.AddSeconds(30), open: 14m, high: 16m);

        var events = engine.Evaluate(drop, surge, new[] { surge });

        Assert.Contains(events, item => item.Type == L1EventType.NewStockOpened);
        // 再次评估不重复
        var again = engine.Evaluate(
            Quote("N新股份", 14.8m, 48m, 10m, at.AddSeconds(60), open: 14m, high: 16m),
            drop, new[] { surge, drop });
        Assert.DoesNotContain(again, item => item.Type == L1EventType.NewStockOpened);
    }

    [Fact]
    public void New_stock_recovering_high_should_emit_reseal_once_after_opened()
    {
        var engine = new L1EventEngine();
        var at = DateTimeOffset.Parse("2026-10-13T09:32:00+08:00");
        var surge = Quote("N新股份", 16m, 60m, 10m, at, open: 14m, high: 16m);
        engine.Evaluate(surge, null, Array.Empty<QuoteSnapshot>());
        var drop = Quote("N新股份", 15m, 50m, 10m, at.AddSeconds(30), open: 14m, high: 16m);
        engine.Evaluate(drop, surge, new[] { surge });
        var recover = Quote("N新股份", 15.95m, 59.5m, 10m, at.AddSeconds(60), open: 14m, high: 16m);

        var events = engine.Evaluate(recover, drop, new[] { surge, drop });

        Assert.Contains(events, item => item.Type == L1EventType.NewStockReseal);
        // 回封只报一次
        var again = engine.Evaluate(
            Quote("N新股份", 15.97m, 59.7m, 10m, at.AddSeconds(90), open: 14m, high: 16m),
            recover, new[] { surge, drop, recover });
        Assert.DoesNotContain(again, item => item.Type == L1EventType.NewStockReseal);
    }

    [Fact]
    public void Speed_window_should_ignore_stale_baseline()
    {
        var engine = new L1EventEngine();
        var at = DateTimeOffset.Parse("2026-10-13T09:40:00+08:00");
        var baseline = Quote("普通股份", 10m, 0m, 10m, at, open: 10m, high: 10m);
        // 快照断档 45 秒：30 秒窗口内无合法基线，基线已过期，不得按旧基线误报暴涨速
        var current = Quote("普通股份", 10.35m, 3.5m, 10m, at.AddSeconds(45), open: 10m, high: 10m);

        var events = engine.Evaluate(current, baseline, new[] { baseline });

        Assert.DoesNotContain(events, item => item.Type == L1EventType.FastRise);
    }

    [Fact]
    public void Speed_window_should_still_use_fresh_baseline()
    {
        var engine = new L1EventEngine();
        var at = DateTimeOffset.Parse("2026-10-13T09:40:00+08:00");
        var baseline = Quote("普通股份", 10m, 0m, 10m, at, open: 10m, high: 10m);
        // 基线 31 秒前，刚出 30 秒窗口且未过期：+3.5% 触发快速拉升
        var current = Quote("普通股份", 10.35m, 3.5m, 10m, at.AddSeconds(31), open: 10m, high: 10m);

        var events = engine.Evaluate(current, baseline, new[] { baseline });

        Assert.Contains(events, item => item.Type == L1EventType.FastRise);
    }
}
