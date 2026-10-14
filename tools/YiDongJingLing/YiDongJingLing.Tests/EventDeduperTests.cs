using YiDongJingLing.Events;
using Xunit;

namespace YiDongJingLing.Tests;

public sealed class EventDeduperTests
{
    private static EventRecord Record(
        L1EventType type,
        string typeName,
        string code,
        decimal changePct,
        DateTimeOffset timestamp,
        L1EventSeverity severity = L1EventSeverity.Important,
        string reason = "reason")
    {
        return new EventRecord(
            type, typeName, code, "测试" + code, 10m, changePct, 0m, 0m,
            timestamp, severity, reason);
    }

    [Fact]
    public void Filter_same_stock_batch_should_emit_multiple_event_types()
    {
        var deduper = new EventDeduper();
        var at = DateTimeOffset.Parse("2026-10-13T09:35:00+08:00");
        var events = new List<EventRecord>
        {
            Record(L1EventType.FastRise, "快速拉升", "600000", 3.2m, at),
            Record(L1EventType.NearLimitUp, "逼近涨停", "600000", 8.9m, at.AddMilliseconds(200)),
        };

        var emitted = deduper.Filter(events);

        Assert.Equal(2, emitted.Count);
    }

    [Fact]
    public void Filter_same_type_within_cooldown_should_stay_suppressed()
    {
        var deduper = new EventDeduper();
        var at = DateTimeOffset.Parse("2026-10-13T09:35:00+08:00");
        deduper.Filter(new List<EventRecord>
        {
            Record(L1EventType.FastRise, "快速拉升", "600000", 3.2m, at),
        });

        var emitted = deduper.Filter(new List<EventRecord>
        {
            Record(L1EventType.FastRise, "快速拉升", "600000", 4.0m, at.AddSeconds(10)),
        });

        Assert.Empty(emitted);
    }

    [Fact]
    public void Filter_state_change_type_should_use_short_cooldown_and_noise_type_long()
    {
        var deduper = new EventDeduper();
        var at = DateTimeOffset.Parse("2026-10-13T09:35:00+08:00");
        deduper.Filter(new List<EventRecord>
        {
            Record(L1EventType.FastRise, "快速拉升", "600000", 3.2m, at),
            Record(L1EventType.BigRiseTier, "涨幅上台阶", "600001", 7.5m, at),
        });

        var emitted = deduper.Filter(new List<EventRecord>
        {
            Record(L1EventType.FastRise, "快速拉升", "600000", 4.4m, at.AddSeconds(40)),
            Record(L1EventType.BigRiseTier, "涨幅上台阶", "600001", 8.1m, at.AddSeconds(40)),
        });

        var item = Assert.Single(emitted);
        Assert.Equal(L1EventType.FastRise, item.Type);
    }

    [Fact]
    public void Filter_should_keep_score_ordering()
    {
        var deduper = new EventDeduper();
        var at = DateTimeOffset.Parse("2026-10-13T09:35:00+08:00");
        var events = new List<EventRecord>
        {
            Record(L1EventType.FastRise, "快速拉升", "600000", 3.2m, at),
            Record(L1EventType.LimitUpSealed, "封涨停板", "600001", 10m, at),
        };

        var emitted = deduper.Filter(events);

        Assert.Equal(L1EventType.LimitUpSealed, emitted[0].Type);
        Assert.Equal(L1EventType.FastRise, emitted[1].Type);
    }

    [Fact]
    public void BuildSpeechItems_should_return_one_item_per_event_in_time_order()
    {
        var at = DateTimeOffset.Parse("2026-10-13T09:35:00+08:00");
        var events = new List<EventRecord>
        {
            Record(L1EventType.NearLimitUp, "逼近涨停", "600002", 8.9m, at.AddSeconds(6)),
            Record(L1EventType.FastRise, "快速拉升", "600001", 3.2m, at),
        };

        var items = EventDeduper.BuildSpeechItems(events);

        Assert.Equal(2, items.Count);
        Assert.Equal("测试600001，快速拉升，涨幅3.2%", items[0]);
        Assert.Equal("测试600002，逼近涨停", items[1]);
    }

    [Fact]
    public void BuildSpeechItems_sealed_should_announce_reason_not_change_pct()
    {
        var at = DateTimeOffset.Parse("2026-10-13T09:35:00+08:00");

        var items = EventDeduper.BuildSpeechItems(new List<EventRecord>
        {
            Record(L1EventType.LimitUpSealed, "封涨停板", "600003", 10.02m, at,
                reason: "回封连板，封单增厚"),
        });

        var item = Assert.Single(items);
        // 封板类事件语音播报原因而非涨幅：涨停时念「涨幅10.02%」是冗余且误导的
        Assert.Equal("测试600003，封涨停板，回封连板，封单增厚", item);
        Assert.DoesNotContain("涨幅", item);
    }
}
