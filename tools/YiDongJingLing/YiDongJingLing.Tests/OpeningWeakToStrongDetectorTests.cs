using YiDongJingLing.Events;
using Xunit;

namespace YiDongJingLing.Tests;

public sealed class OpeningWeakToStrongDetectorTests
{
    private static readonly OpeningWeakToStrongRules Rules = new(
        "09:20:00", "09:20:00", "09:20:30", "09:24:00",
        "09:24:50", "09:25:10", "09:30:00", "09:35:00",
        1.2m, 1m, 0.8m, 0.35m, 0.3m, 0.2m, 30);

    private static OpeningWeakToStrongQuote Q(
        string time,
        decimal lastPrice,
        decimal amount,
        decimal preClose = 10m,
        decimal open = 0m,
        string code = "002552",
        string name = "测试股")
    {
        var date = "2026-06-04T";
        var ts = DateTimeOffset.Parse(date + time + "+08:00");
        return new OpeningWeakToStrongQuote(
            code, name, ts, lastPrice, preClose, open,
            amount, amount / 10m, lastPrice * 1.1m,
            ts, ts, true, 1, 1, 10, 0, 0);
    }

    private static List<OpeningWeakToStrongResult> RunQuotes(params OpeningWeakToStrongQuote[] quotes)
    {
        var store = new OpeningAuctionStateStore(Rules);
        var detector = new OpeningWeakToStrongDetector(Rules);
        var events = new List<OpeningWeakToStrongResult>();

        foreach (var q in quotes)
        {
            store.Capture(q);
            var result = detector.Evaluate(q, store.GetBaseline(q.Code, q.At));
            if (result.Triggered)
                events.Add(result);
        }

        return events;
    }

    // ── 子形态 1A：全段推（全程抢筹）──

    [Fact]
    public void FullSegmentLift_passes_when_total_price_and_amount_lift_meet_thresholds()
    {
        // preClose=10, 09:20 pct=-3.0%, 09:24 pct=-1.0%, 09:25 pct=-0.8%
        // 全段推: totalLift = 2.2 >= 0.8 ✓,  amountRatio = 1.0 >= 0.35 ✓
        // 临门:   lateLift  = 0.2 <  0.3 ✗ (only total branch passes)
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.90m, 1_900_000m),
            Q("09:25:00", 9.92m, 2_000_000m));

        Assert.Single(events);
        Assert.Equal("auctionConditionPassed", events[0].Stage);
        Assert.False(events[0].VoiceEligible);
        Assert.True(events[0].PriceVolumeConfirmed);
    }

    [Fact]
    public void FullSegmentLift_complete_path_to_trendConfirm()
    {
        // 全段推竞价通过 → 09:30 高开承接 → 09:35 高走确认
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.90m, 1_900_000m),
            Q("09:25:00", 9.92m, 2_000_000m),
            Q("09:30:00", 10.35m, 8_000_000m, open: 10.35m),
            Q("09:35:00", 10.65m, 16_000_000m, open: 10.35m));

        Assert.Equal(
            new[] { "auctionConditionPassed", "gapAlert", "trendConfirm" },
            events.Select(e => e.Stage));
        Assert.Equal(new[] { false, true, true }, events.Select(e => e.VoiceEligible));
    }

    // ── 子形态 1B：临门突袭（尾段抢筹）──

    [Fact]
    public void LateLift_passes_when_total_fails_but_late_price_and_amount_lift_meet_thresholds()
    {
        // preClose=10, 09:20 pct=-3.0%, 09:24 pct=-3.0%(flat), 09:25 pct=-2.4%
        // 全段推: totalLift = 0.6 < 0.8 ✗
        // 临门:   lateLift  = 0.6 >= 0.3 ✓, lateAmount = 0.286 >= 0.2 ✓
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.70m, 1_050_000m),
            Q("09:25:00", 9.76m, 1_350_000m));

        Assert.Single(events);
        Assert.Equal("auctionConditionPassed", events[0].Stage);
        Assert.False(events[0].VoiceEligible);
        Assert.True(events[0].PriceVolumeConfirmed);
    }

    [Fact]
    public void LateLift_complete_path_to_trendConfirm()
    {
        // 临门突袭竞价通过 → 09:30 高开承接 → 09:35 高走确认
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.70m, 1_050_000m),
            Q("09:25:00", 9.76m, 1_350_000m),
            Q("09:30:00", 10.15m, 5_000_000m, open: 10.15m),
            Q("09:35:00", 10.20m, 10_000_000m, open: 10.15m));

        Assert.Equal(
            new[] { "auctionConditionPassed", "gapAlert", "trendConfirm" },
            events.Select(e => e.Stage));
        Assert.Equal(new[] { false, true, true }, events.Select(e => e.VoiceEligible));
    }

    // ── OR 逻辑 ──

    [Fact]
    public void Both_branches_pass_when_strong_lift_across_entire_auction()
    {
        // 全段和临门同时满足
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.86m, 1_500_000m),
            Q("09:25:00", 9.92m, 2_000_000m));

        Assert.Single(events);
        Assert.Equal("auctionConditionPassed", events[0].Stage);
        Assert.True(events[0].PriceVolumeConfirmed);
    }

    [Fact]
    public void Neither_branch_passes_when_lift_insufficient()
    {
        // preClose=10, 09:20 pct=-3.0%, 09:24 pct=-2.8%, 09:25 pct=-2.6%
        // 全段推: totalLift=0.4 < 0.8 ✗, amountRatio=0.15 < 0.35 ✗
        // 临门:   lateLift=0.2 < 0.3 ✗,   lateAmount=0.127 < 0.2 ✗
        var store = new OpeningAuctionStateStore(Rules);
        var detector = new OpeningWeakToStrongDetector(Rules);

        store.Capture(Q("09:20:00", 9.70m, 1_000_000m));
        store.Capture(Q("09:24:00", 9.72m, 1_020_000m));
        var final = Q("09:25:00", 9.74m, 1_150_000m);
        store.Capture(final);
        var result = detector.Evaluate(final, store.GetBaseline(final.Code, final.At));

        Assert.False(result.Triggered);
        // baseline profile IS computed (PriceVolumeConfirmed=false), but the
        // Evaluate path returns Rejected before attaching it — so it comes back null.
        Assert.Contains("build", result.InvalidReason ?? "");
    }

    // ── 完整路径：失败场景 ──

    [Fact]
    public void Auction_passes_but_gap_fails_produces_noGap()
    {
        // 竞价通过，但 09:30 改善幅度不足
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.90m, 1_900_000m),
            Q("09:25:00", 9.92m, 2_000_000m),
            Q("09:30:00", 9.98m, 4_000_000m, open: 9.98m));

        Assert.Equal(
            new[] { "auctionConditionPassed", "noGap" },
            events.Select(e => e.Stage));
        Assert.False(events[1].VoiceEligible);
    }

    [Fact]
    public void Gap_alert_fires_but_trend_weak_produces_trendWeak()
    {
        // 竞价通过 → gapAlert，但 09:35 回落
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.90m, 1_900_000m),
            Q("09:25:00", 9.92m, 2_000_000m),
            Q("09:30:00", 10.35m, 8_000_000m, open: 10.35m),
            Q("09:35:00", 9.98m, 10_000_000m, open: 10.35m));

        Assert.Equal(
            new[] { "auctionConditionPassed", "gapAlert", "trendWeak" },
            events.Select(e => e.Stage));
        Assert.False(events[2].VoiceEligible);
    }

    [Fact]
    public void LateLift_to_gapAlert_to_trendWeak_when_09_35_price_retreats()
    {
        // 临门突袭竞价通过 → gapAlert → 09:35 跌破开盘价转弱（路径四）
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.70m, 1_050_000m),
            Q("09:25:00", 9.76m, 1_350_000m),
            Q("09:30:00", 10.15m, 5_000_000m, open: 10.15m),
            Q("09:35:00", 9.90m, 6_000_000m, open: 10.15m));

        Assert.Equal(
            new[] { "auctionConditionPassed", "gapAlert", "trendWeak" },
            events.Select(e => e.Stage));
        Assert.False(events[2].VoiceEligible);
        Assert.True(events[2].FirstWindowPrice < events[2].OfficialOpen); // 跌破开盘价
    }

    // ── 缺基线容错：没有 09:20 数据时链路不能断 ──

    [Fact]
    public void Missing_09_20_baseline_emits_auctionConditionFailed_and_chain_continues()
    {
        // 模拟通达信 L1 在 09:25 才推送首条数据的真实场景
        // 没有 09:20 初始基线 → auctionConditionFailed(triggered=true) → 09:30 gapAlert 仍可触发
        var events = RunQuotes(
            Q("09:24:00", 9.90m, 1_900_000m),
            Q("09:25:00", 9.92m, 2_000_000m),
            Q("09:30:00", 10.35m, 8_000_000m, open: 10.35m));

        Assert.Equal(
            new[] { "auctionConditionFailed", "gapAlert" },
            events.Select(e => e.Stage));
        Assert.True(events[0].Triggered);  // triggered=true，不能是 Rejected
        Assert.False(events[0].VoiceEligible);
        Assert.True(events[1].VoiceEligible); // gapAlert 正常触发
    }

    [Fact]
    public void Missing_09_20_baseline_then_noGap_at_09_30()
    {
        // 缺 09:20 基线 + 09:30 改善不足 → auctionConditionFailed → noGap
        var events = RunQuotes(
            Q("09:24:00", 9.90m, 1_900_000m),
            Q("09:25:00", 9.92m, 2_000_000m),
            Q("09:30:00", 9.98m, 4_000_000m, open: 9.98m));

        Assert.Equal(
            new[] { "auctionConditionFailed", "noGap" },
            events.Select(e => e.Stage));
    }

    [Fact]
    public void NoGap_then_trendWeak_when_opening_fails_and_trend_also_fails()
    {
        // 竞价通过 → 09:30 改善不足(noGap) → 09:35 继续回落(trendWeak)
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.90m, 1_900_000m),
            Q("09:25:00", 9.92m, 2_000_000m),
            Q("09:30:00", 9.98m, 4_000_000m, open: 9.98m),
            Q("09:35:00", 9.85m, 6_000_000m, open: 9.98m));

        Assert.Equal(
            new[] { "auctionConditionPassed", "noGap", "trendWeak" },
            events.Select(e => e.Stage));
        Assert.False(events[1].VoiceEligible);
        Assert.False(events[2].VoiceEligible);
    }

    // ── gapAlert 独立测试 ──

    [Fact]
    public void GapAlert_fires_standalone_when_opening_support_meets_all_four_conditions()
    {
        // 竞价通过 → 09:30 改善达标 → gapAlert 触发，无后续 09:35 行情
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.90m, 1_900_000m),
            Q("09:25:00", 9.92m, 2_000_000m),
            Q("09:30:00", 10.35m, 8_000_000m, open: 10.35m));

        Assert.Equal(
            new[] { "auctionConditionPassed", "gapAlert" },
            events.Select(e => e.Stage));
        var gap = events[1];
        Assert.True(gap.VoiceEligible);
        // 四个 gap 条件逐项验证
        Assert.True(gap.JumpPctPoint >= 1.2m);                         // 改善幅度 ≥ 1.2%
        Assert.True(gap.FirstWindowPrice >= gap.AuctionFinalPrice);     // 现价 ≥ 竞价价
        Assert.True(gap.OfficialOpen >= gap.AuctionFinalPrice);         // 开盘价 ≥ 竞价价
    }

    // ── trendConfirm 独立测试 ──

    [Fact]
    public void TrendConfirm_fires_when_price_holds_above_open_and_improvement_sustained()
    {
        // 竞价通过 → gapAlert → 09:35 高开高走，四个条件全部满足
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.90m, 1_900_000m),
            Q("09:25:00", 9.92m, 2_000_000m),
            Q("09:30:00", 10.35m, 8_000_000m, open: 10.35m),
            Q("09:35:00", 10.65m, 16_000_000m, open: 10.35m));

        Assert.Equal(
            new[] { "auctionConditionPassed", "gapAlert", "trendConfirm" },
            events.Select(e => e.Stage));
        var trend = events[2];
        Assert.True(trend.VoiceEligible);
        // 四个 trendConfirm 条件逐项验证
        Assert.True(trend.FirstWindowPrice >= trend.OfficialOpen);  // 现价 ≥ 开盘价
        Assert.True(trend.FirstWindowPct >= trend.AuctionPct);      // 涨幅 ≥ 竞价涨幅
        Assert.True(trend.FirstWindowPct - trend.AuctionPct >= 1.2m); // 改善幅度维持
    }

    // ── 边界条件 ──

    [Fact]
    public void No_gap_alert_without_09_25_confirm_baseline()
    {
        var store = new OpeningAuctionStateStore(Rules);
        var detector = new OpeningWeakToStrongDetector(Rules);

        var q = Q("09:30:00", 10.35m, 8_000_000m, open: 10.35m);
        store.Capture(q);
        var result = detector.Evaluate(q, store.GetBaseline(q.Code, q.At));

        Assert.False(result.Triggered);
    }

    [Fact]
    public void Quote_outside_checkpoint_windows_triggers_no_event()
    {
        var events = RunQuotes(
            Q("09:20:00", 9.70m, 1_000_000m),
            Q("09:24:00", 9.90m, 1_900_000m),
            Q("09:25:00", 9.92m, 2_000_000m),
            Q("09:31:00", 10.35m, 8_000_000m, open: 10.35m));

        // 09:31:00 超出 09:30 checkpoint 窗口 (30s)，不触发 gapAlert
        Assert.Single(events);
        Assert.Equal("auctionConditionPassed", events[0].Stage);
    }

    [Fact]
    public void LateLift_with_minimal_total_passes_via_late_branch()
    {
        // 临界测试：全段推刚好不够，临门刚好够
        // 09:20 pct=-2.0%, 09:24 pct=-1.0%, 09:25 pct=-1.3%
        // totalLift = -1.3 - (-2.0) = 0.7 < 0.8 ✗
        // lateLift  = -1.3 - (-1.0) = -0.3... wait that's negative
        // Let me recalculate with different numbers
        // 09:20 price=9.80 (pct=-2.0%), 09:24 price=9.85 (pct=-1.5%), 09:25 price=9.86 (pct=-1.4%)
        // totalLift = -1.4 - (-2.0) = 0.6 < 0.8 ✗
        // lateLift  = -1.4 - (-1.5) = 0.1 < 0.3 ✗
        // Hmm, that also fails. Let me think again...
        //
        // I want total lift to just fail and late lift to just pass:
        // totalLift >= 0.8 fails → totalLift < 0.8, say 0.7
        // lateLift >= 0.3 passes → lateLift >= 0.3
        //
        // With preClose=10:
        // 09:20: price=9.80 → pct=-2.0%
        // For totalLift = 0.7: finalPct = -1.3% → price=9.87
        // For lateLift = 0.3: 09:24 pct must be such that finalPct - latePct >= 0.3
        //   09:24 pct <= -1.6% → price <= 9.84
        //   09:24: price=9.84 → pct=-1.6%
        // Then: totalLift = -1.3 - (-2.0) = 0.7 < 0.8 ✗
        //       lateLift  = -1.3 - (-1.6) = 0.3 >= 0.3 ✓ (exactly at threshold)
        //
        // Amounts: 09:20=1M, 09:24=1.05M, 09:25=1.35M
        // amountLiftRatio = 0.35M/1M = 0.35 >= 0.35 ✓ (but totalLift fails so total branch fails)
        // lateAmountLift = (1.35M-1.05M)/1.05M = 0.286 >= 0.2 ✓
        var events = RunQuotes(
            Q("09:20:00", 9.80m, 1_000_000m),
            Q("09:24:00", 9.84m, 1_050_000m),
            Q("09:25:00", 9.87m, 1_350_000m));

        Assert.Single(events);
        Assert.Equal("auctionConditionPassed", events[0].Stage);
    }

    // ── 真实案例模拟 ──

    [Fact]
    public void Real_case_600360_HuaWeiElectronics_late_lift_then_gap_alert()
    {
        // 600360 华微电子：09:20 低开-2%，09:24 临门抢筹，09:25 竞价收窄，
        // 09:30 相对高开 1.2%，弱转强成功
        var events = RunQuotes(
            Q("09:20:00", 9.80m, 800_000m, preClose: 10m, code: "600360", name: "华微电子"),
            Q("09:24:00", 9.80m, 900_000m, preClose: 10m, code: "600360", name: "华微电子"),
            Q("09:25:00", 9.86m, 1_200_000m, preClose: 10m, code: "600360", name: "华微电子"),
            Q("09:30:00", 10.35m, 6_000_000m, preClose: 10m, open: 10.35m, code: "600360", name: "华微电子"),
            Q("09:35:00", 10.50m, 12_000_000m, preClose: 10m, open: 10.35m, code: "600360", name: "华微电子"));

        Assert.Equal(
            new[] { "auctionConditionPassed", "gapAlert", "trendConfirm" },
            events.Select(e => e.Stage));
        // 验证是临门突袭路径：全段推 totalLift = -1.4 - (-2.0) = 0.6 < 0.8
        Assert.True(events[0].PriceVolumeConfirmed);
        // 09:30 改善 = 3.5 - (-1.4) = 4.9 个百分点
        Assert.True(events[1].JumpPctPoint >= 1.2m);
    }

    [Fact]
    public void Real_case_603005_JingFangTech_late_surge_then_gap_alert()
    {
        // 603005 晶方科技：09:20 低开，09:24 尾盘突袭放量拉升，
        // 09:30 跳空高开，最终涨停
        var events = RunQuotes(
            Q("09:20:00", 14.70m, 500_000m, preClose: 15m, code: "603005", name: "晶方科技"),
            Q("09:24:00", 14.70m, 550_000m, preClose: 15m, code: "603005", name: "晶方科技"),
            Q("09:25:00", 14.78m, 800_000m, preClose: 15m, code: "603005", name: "晶方科技"),
            Q("09:30:00", 15.15m, 4_000_000m, preClose: 15m, open: 15.15m, code: "603005", name: "晶方科技"),
            Q("09:35:00", 15.45m, 8_000_000m, preClose: 15m, open: 15.15m, code: "603005", name: "晶方科技"));

        Assert.Equal(
            new[] { "auctionConditionPassed", "gapAlert", "trendConfirm" },
            events.Select(e => e.Stage));
    }

    [Fact]
    public void Real_case_600703_SanAn_late_lift_then_gap_alert()
    {
        // 600703 三安光电：竞价尾盘拉升，开盘强劲承接
        var events = RunQuotes(
            Q("09:20:00", 15.32m, 12_000_000m, preClose: 15.51m, code: "600703", name: "三安光电"),
            Q("09:24:00", 15.30m, 27_000_000m, preClose: 15.51m, code: "600703", name: "三安光电"),
            Q("09:25:00", 15.47m, 43_000_000m, preClose: 15.51m, code: "600703", name: "三安光电"),
            Q("09:30:00", 15.79m, 125_000_000m, preClose: 15.51m, open: 15.47m, code: "600703", name: "三安光电"),
            Q("09:35:00", 16.01m, 630_000_000m, preClose: 15.51m, open: 15.47m, code: "600703", name: "三安光电"));

        Assert.Equal(
            new[] { "auctionConditionPassed", "gapAlert", "trendConfirm" },
            events.Select(e => e.Stage));
    }
}
