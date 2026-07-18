using System;
using System.Collections.Generic;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Newtonsoft.Json.Linq;
using THSBigOrder;
using THSBigOrder.Controls;
using THSBigOrder.DataSources;
using THSBigOrder.Models;
using THSBigOrder.Parsing;

internal static class LonghuFeatureTests
{
    internal static void TestHotlistSelectionMessage()
    {
        HotlistSelectionMessage message;
        AssertTrue(HotlistSelectionMessage.TryParse(
            "{\"code\":\"SZ000001\",\"name\":\"平安银行\"}", out message),
            "valid hotlist selection parses");
        AssertEqual("000001", message.Code, "hotlist code normalized");
        AssertEqual("平安银行", message.Name, "hotlist name retained");
        AssertTrue(!HotlistSelectionMessage.TryParse("{\"code\":\"123\"}", out message),
            "short hotlist code rejected");
        AssertTrue(!HotlistSelectionMessage.TryParse("not-json", out message),
            "invalid hotlist message rejected");
        AssertTrue(HotlistSelectionListener.IsAllowedOrigin("http://127.0.0.1:5173"),
            "Dragon Board loopback origin allowed");
        AssertTrue(HotlistSelectionListener.IsAllowedOrigin("http://localhost:5173"),
            "Dragon Board localhost origin allowed");
        AssertTrue(HotlistSelectionListener.IsAllowedOrigin("http://127.0.0.1:3000"),
            "proxy loopback origin allowed");
        AssertTrue(HotlistSelectionListener.IsAllowedOrigin("http://localhost:3000"),
            "proxy localhost origin allowed");
        AssertTrue(!HotlistSelectionListener.IsAllowedOrigin("https://evil.example"),
            "untrusted origin rejected");
        AssertTrue(HotlistSelectionListener.IsAllowedOrigin(null),
            "non-browser local request allowed");
    }

    internal static async Task TestMainFormHotlistFollow()
    {
        var provider = new FollowProvider();
        var voice = new RecordingVoice();
        using (var form = new MainForm(provider, false, voice))
        {
            var followHotlist = (CheckBox)typeof(MainForm)
                .GetField("chkFollowHotlist", BindingFlags.Instance | BindingFlags.NonPublic)
                .GetValue(form);
            var followTdx = (CheckBox)typeof(MainForm)
                .GetField("chkFollowTdx", BindingFlags.Instance | BindingFlags.NonPublic)
                .GetValue(form);

            followHotlist.Checked = true;
            AssertTrue(!followTdx.Checked, "hotlist follow disables TDX follow");
            form.ApplyHotlistSelection("600519", "贵州茅台");
            await WaitUntil(() => form.BoundStockCode == "600519", "hotlist selection refresh");
            AssertEqual(1, voice.CancelCount, "hotlist switch cancels prior voice queue");
            AssertEqual("600519", form.InputStockCodeText, "hotlist code input");
            form.ApplyHotlistSelection("600519", "测试超长股票名称");
            AssertTrue(form.StockNameCodeGap >= 8, "long stock name does not overlap code input");
            form.ApplyHotlistSelection("000001", "平安银行");
            await WaitUntil(() => form.BoundStockCode == "000001", "second hotlist selection refresh");
            AssertEqual(2, voice.CancelCount, "second hotlist switch cancels prior voice queue");
            var dataSource = (ComboBox)typeof(MainForm)
                .GetField("cboDataSource", BindingFlags.Instance | BindingFlags.NonPublic)
                .GetValue(form);
            AssertEqual(5, dataSource.Left, "data source selector stays left aligned");

            followTdx.Checked = true;
            AssertTrue(!followHotlist.Checked, "TDX follow disables hotlist follow");
        }
    }

    internal static void TestLastGoodMaxAgeWindows()
    {
        AssertEqual(TimeSpan.FromHours(12),
            THSBigOrderDataProvider.BigOrderLastGoodMaxAge(new DateTime(2026, 7, 17, 9, 15, 0)),
            "pre-open window allows 12 hours");
        AssertEqual(TimeSpan.FromMinutes(5),
            THSBigOrderDataProvider.BigOrderLastGoodMaxAge(new DateTime(2026, 7, 17, 10, 0, 0)),
            "trading window keeps 5 minute bound");
        AssertEqual(TimeSpan.FromHours(12),
            THSBigOrderDataProvider.BigOrderLastGoodMaxAge(new DateTime(2026, 7, 17, 12, 0, 0)),
            "lunch window allows 12 hours");
        AssertEqual(TimeSpan.FromHours(12),
            THSBigOrderDataProvider.BigOrderLastGoodMaxAge(new DateTime(2026, 7, 17, 15, 10, 0)),
            "post-close window allows 12 hours");
        AssertEqual(TimeSpan.FromHours(12),
            THSBigOrderDataProvider.BigOrderLastGoodMaxAge(new DateTime(2026, 7, 17, 20, 0, 0)),
            "evening window allows 12 hours");
        AssertEqual(TimeSpan.FromHours(12),
            THSBigOrderDataProvider.BigOrderLastGoodMaxAge(new DateTime(2026, 7, 18, 10, 0, 0)),
            "weekend window allows 12 hours");
    }

    internal static void TestAnnouncementTracker()
    {
        var tracker = new BigOrderAnnouncementTracker();
        var day = new DateTime(2026, 7, 17);
        var ordinary = Signal(day.AddHours(9).AddMinutes(30), "", "");
        var confirmed = Signal(day.AddHours(9).AddMinutes(30), "点火", "买活跃");
        AssertEqual(0, tracker.Observe("002297", BigOrderDataSource.Ths, day,
            new[] { ordinary }).Count, "first snapshot marker baseline");
        var added = tracker.Observe("002297", BigOrderDataSource.Ths, day.AddHours(12),
            new[] { confirmed });
        AssertEqual(1, added.Count, "delayed marker confirmation");
        AssertEqual("点火", added[0].FundMarker, "confirmed marker returned");
        AssertEqual(0, tracker.Observe("002297", BigOrderDataSource.Ths, day,
            new[] { ordinary }).Count, "marker disappearance does not replay");
        AssertEqual(0, tracker.Observe("002297", BigOrderDataSource.Ths, day,
            new[] { confirmed }).Count, "restored marker does not replay");
        AssertEqual(1, tracker.Observe("002297", BigOrderDataSource.Ths, day,
            new[] { confirmed, confirmed }).Count, "duplicate marker occurrence increment");

        var later = Signal(day.AddHours(9).AddMinutes(31), "砸盘", "");
        var earlier = Signal(day.AddHours(9).AddMinutes(29), "点火", "");
        var ordered = tracker.Observe("002297", BigOrderDataSource.Ths, day,
            new[] { later, confirmed, confirmed, earlier });
        AssertEqual(2, ordered.Count, "two new rows");
        AssertTrue(ordered[0].Time < ordered[1].Time, "new rows sorted oldest first");
        AssertEqual(0, tracker.Observe("600519", BigOrderDataSource.Ths, day,
            new[] { later }).Count, "stock switch baseline");

        var kindTracker = new BigOrderAnnouncementTracker();
        var utcDay = DateTime.SpecifyKind(day.AddHours(9), DateTimeKind.Utc);
        var localDay = DateTime.SpecifyKind(day.AddHours(15), DateTimeKind.Local);
        AssertEqual(0, kindTracker.Observe("002297", BigOrderDataSource.Ths, utcDay,
            new[] { confirmed }).Count, "kind baseline");
        AssertEqual(1, kindTracker.Observe("002297", BigOrderDataSource.Ths, localDay,
            new[] { confirmed, later }).Count, "same date ignores time and Kind");
        AssertEqual(0, kindTracker.Observe("002297", BigOrderDataSource.Longhu, day,
            new[] { confirmed, later }).Count, "source switch baseline");
        AssertEqual(0, kindTracker.Observe("002297", BigOrderDataSource.Longhu, day.AddDays(1),
            new[] { confirmed, later }).Count, "day switch baseline");
    }

    internal static void TestMarkerRejections()
    {
        var day = new DateTime(2026, 7, 17, 9, 30, 0);
        var single = new List<BigOrderItem>
        {
            Trade(day, 0, 1, 1000000, 10),
            Trade(day, 1, 2, 10000000, 10.10),
            Trade(day, 9, 1, 1000000, 10.10),
        };
        var flat = new List<BigOrderItem>
        {
            Trade(day.AddMinutes(1), 0, 1, 1000000, 10),
            Trade(day.AddMinutes(1), 1, 2, 5000000, 10),
            Trade(day.AddMinutes(1), 2, 2, 5000000, 10),
            Trade(day.AddMinutes(1), 3, 2, 5000000, 10),
            Trade(day.AddMinutes(1), 11, 1, 1000000, 10),
        };
        var impure = new List<BigOrderItem>
        {
            Trade(day.AddMinutes(2), 0, 1, 1000000, 10),
            Trade(day.AddMinutes(2), 1, 2, 5000000, 10.01),
            Trade(day.AddMinutes(2), 2, 4, 10000000, 10.02),
            Trade(day.AddMinutes(2), 3, 2, 5000000, 10.03),
            Trade(day.AddMinutes(2), 4, 2, 5000000, 10.04),
            Trade(day.AddMinutes(2), 12, 1, 1000000, 10.03),
        };

        using (var provider = new THSBigOrderDataProvider())
        {
            provider.CalculateMarkers(single);
            provider.CalculateMarkers(flat);
            provider.CalculateMarkers(impure);
        }

        AssertTrue(single.All(row => row.FundMarker == ""), "single order rejected");
        AssertTrue(flat.All(row => row.FundMarker != "点火" && row.FundMarker != "砸盘"), "flat price response rejected");
        AssertTrue(impure.All(row => row.FundMarker != "点火" && row.FundMarker != "砸盘"), "impure active flow rejected");
    }

    internal static void TestMarkerAttribution()
    {
        var day = new DateTime(2026, 7, 17, 9, 30, 0);
        var ignition = new List<BigOrderItem>
        {
            Trade(day, 0, 1, 1000000, 100),
            Trade(day, 1, 2, 5000000, 100.01),
            Trade(day, 2, 2, 6000000, 100.02),
            Trade(day, 3, 2, 5000000, 100.04),
            Trade(day, 4, 2, 3000000, 100.05),
            Trade(day, 5, 2, 3000000, 100.05),
            Trade(day, 11, 1, 1000000, 100.03),
            Trade(day, 30, 1, 1000000, 100.03),
            Trade(day, 31, 2, 5000000, 100.04),
            Trade(day, 32, 2, 5000000, 100.06),
            Trade(day, 33, 2, 5000000, 100.08),
            Trade(day, 41, 1, 1000000, 100.07),
            Trade(day, 44, 1, 1000000, 100.07),
        };
        var support = new List<BigOrderItem>
        {
            Trade(day.AddMinutes(10), 0, 2, 1000000, 100),
            Trade(day.AddMinutes(10), 1, 3, 1000000, 99.99),
            Trade(day.AddMinutes(10), 1, 3, 1000000, 99.99),
            Trade(day.AddMinutes(10), 2, 4, 5000000, 99.98),
            Trade(day.AddMinutes(10), 3, 4, 5000000, 99.96),
            Trade(day.AddMinutes(10), 4, 4, 5000000, 99.95),
            Trade(day.AddMinutes(10), 5, 4, 1000000, 99.94),
            Trade(day.AddMinutes(10), 6, 2, 10000000, 99.97),
            Trade(day.AddMinutes(10), 12, 1, 1000000, 99.97),
            Trade(day.AddMinutes(10), 15, 1, 1000000, 99.97),
        };

        using (var provider = new THSBigOrderDataProvider())
        {
            provider.CalculateMarkers(ignition);
            provider.CalculateMarkers(support);
        }

        AssertEqual("点火", ignition[3].FundMarker, "confirmed ignition marker");
        AssertEqual("买活跃", ignition[3].BuyMarker, "follow-through belongs to ignition");
        AssertEqual("点火", ignition[10].FundMarker, "second confirmed ignition after cooldown");
        AssertEqual("", ignition[10].BuyMarker, "ignition without follow-through stays plain");
        AssertEqual(2, ignition.Count(row => row.FundMarker == "点火"), "one marker per event");
        AssertEqual("砸盘", support[5].FundMarker, "confirmed smash marker");
        AssertEqual("承接好", support[5].BuyMarker, "recovery belongs to smash");
        AssertEqual("", support[6].BuyMarker, "pressure low row has no detached marker");
    }

    internal static void TestAdaptiveMarkerThreshold()
    {
        var day = new DateTime(2026, 7, 17, 9, 40, 0);
        var rows = new List<BigOrderItem>();
        for (var index = 0; index < 30; index++)
        {
            rows.Add(Trade(day.AddSeconds(index * 15), 0, 2, 6000000, 100));
        }
        var candidate = day.AddMinutes(10);
        rows.Add(Trade(candidate, 0, 1, 1000000, 100));
        rows.Add(Trade(candidate, 1, 2, 5000000, 100.01));
        rows.Add(Trade(candidate, 2, 2, 5000000, 100.02));
        rows.Add(Trade(candidate, 3, 2, 5000000, 100.04));
        rows.Add(Trade(candidate, 11, 1, 1000000, 100.03));

        using (var provider = new THSBigOrderDataProvider())
            provider.CalculateMarkers(rows);

        AssertTrue(rows.All(row => row.FundMarker != "点火" && row.FundMarker != "砸盘"), "P90 raises threshold above 500w");
    }

    internal static void TestCapacityAwarePreviewAndConfirmation()
    {
        var day = new DateTime(2026, 7, 17, 9, 32, 0);
        var preview = new List<BigOrderItem>
        {
            new BigOrderItem { Time = day, Type = 1, Amount = 100000, Volume = 300, Price = 3.05 },
            new BigOrderItem { Time = day.AddSeconds(1), Type = 2, Amount = 1000000, Volume = 3268, Price = 3.06 },
            new BigOrderItem { Time = day.AddSeconds(2), Type = 2, Amount = 1100000, Volume = 3594, Price = 3.07 },
            new BigOrderItem { Time = day.AddSeconds(3), Type = 2, Amount = 1050000, Volume = 3423, Price = 3.08 },
        };
        using (var provider = new THSBigOrderDataProvider())
            provider.CalculateMarkers(preview, "600227");

        AssertEqual("点火预警", preview[3].FundMarker,
            "six-series 100w continuous orders trigger preview below 500w");

        var confirmed = preview.Select(row => new BigOrderItem
        {
            Time = row.Time, Type = row.Type, Amount = row.Amount,
            Volume = row.Volume, Price = row.Price,
        }).Concat(new[]
        {
            new BigOrderItem { Time = day.AddSeconds(12), Type = 1, Amount = 100000, Volume = 300, Price = 3.08 },
            new BigOrderItem { Time = day.AddSeconds(14), Type = 1, Amount = 100000, Volume = 300, Price = 3.08 },
        }).ToList();
        using (var provider = new THSBigOrderDataProvider())
            provider.CalculateMarkers(confirmed, "600227");

        AssertEqual("点火", confirmed[3].FundMarker,
            "same event upgrades preview after price confirmation window");
    }

    internal static void TestConfirmationWindowClosure()
    {
        var day = new DateTime(2026, 7, 17, 10, 30, 0);
        var partial = new List<BigOrderItem>
        {
            Trade(day, 0, 1, 1000000, 100),
            Trade(day, 1, 2, 5000000, 100.01),
            Trade(day, 2, 2, 5000000, 100.02),
            Trade(day, 3, 2, 5000000, 100.04),
            Trade(day, 11, 1, 1000000, 100.03),
        };
        var complete = partial.Select(row => Trade(
            row.Time, 0, row.Type, row.Amount, row.Price)).Concat(new[]
        {
            Trade(day, 14, 1, 1000000, 100.03),
        }).ToList();
        var exactBoundary = partial.Select(row => Trade(
            row.Time, 0, row.Type, row.Amount, row.Price)).Concat(new[]
        {
            Trade(day, 13, 1, 1000000, 100.03),
        }).ToList();

        using (var provider = new THSBigOrderDataProvider())
        {
            provider.CalculateMarkers(partial);
            provider.CalculateMarkers(exactBoundary);
            provider.CalculateMarkers(complete);
        }

        AssertTrue(partial.All(row => row.FundMarker != "点火" && row.FundMarker != "砸盘"),
            "open confirmation window stays unmarked");
        AssertTrue(exactBoundary.All(row => row.FundMarker != "点火" && row.FundMarker != "砸盘"),
            "confirmation at exact ten seconds stays unmarked");
        AssertEqual("点火", complete[3].FundMarker,
            "closed confirmation window freezes marker");
    }

    private static BigOrderItem Trade(
        DateTime start, int seconds, int type, double amount, double price)
    {
        return new BigOrderItem
        {
            Time = start.AddSeconds(seconds),
            Type = type,
            Amount = amount,
            Volume = amount / Math.Max(price, 0.01),
            Price = price,
        };
    }

    internal static void TestVoiceBatch()
    {
        var queue = new RecordingSpeechQueue();
        using (var voice = new VoiceService(queue))
        {
            voice.AnnounceBatch(new[]
            {
                new BigOrderAnnouncement
                {
                    StockName = "华工科技",
                    Time = new DateTime(2026, 7, 17, 9, 32, 12),
                    Type = BigOrderAnnouncementType.Ignite,
                    Amount = 10000000,
                    AdditionalTypes = new[] { BigOrderAnnouncementType.BuyActive },
                },
                new BigOrderAnnouncement
                {
                    StockName = "华工科技",
                    Time = new DateTime(2026, 7, 17, 9, 32, 20),
                    Type = BigOrderAnnouncementType.Ignite,
                    Amount = 5000000,
                },
                new BigOrderAnnouncement
                {
                    StockName = "华工科技",
                    Time = new DateTime(2026, 7, 17, 9, 32, 20),
                    Type = BigOrderAnnouncementType.Smash,
                    Amount = 5000000,
                    AdditionalTypes = new[] { BigOrderAnnouncementType.GoodSupport },
                },
            });
            voice.AnnounceBatch(new[]
            {
                new BigOrderAnnouncement
                {
                    StockName = "华工科技",
                    Time = new DateTime(2026, 7, 17, 9, 32, 30),
                    Type = BigOrderAnnouncementType.BuyActive,
                },
            });
            AssertEqual(2, queue.Texts.Count, "FIFO batches");
            AssertEqual(
                "华工科技 9点32分12秒 点火1000万 买活跃，华工科技 9点32分20秒 点火500万，华工科技 9点32分20秒 砸盘500万 承接好",
                queue.Texts[0],
                "full announcement text");
            AssertEqual("华工科技 9点32分30秒 买活跃", queue.Texts[1], "marker-only text");
            AssertEqual(0, queue.CancelCount, "ordinary batches do not cancel");
            voice.CancelPending();
            AssertEqual(1, queue.CancelCount, "explicit cancel");
        }
        AssertEqual(2, queue.CancelCount, "dispose cancels");
        AssertTrue(queue.Disposed, "dispose releases queue");
    }

    internal static async Task TestMainFormAnnouncementBatch()
    {
        var day = new DateTime(2026, 7, 17);
        var baseline = Signal(day.AddHours(9).AddMinutes(30), "点火", "");
        var added = new[]
        {
            Signal(day.AddHours(9).AddMinutes(31), "点火", "买活跃"),
            Signal(day.AddHours(9).AddMinutes(32), "点火", ""),
            Signal(day.AddHours(9).AddMinutes(33), "砸盘", "承接好"),
            Signal(day.AddHours(9).AddMinutes(34), "", "买活跃"),
        };
        var provider = new SequenceProvider(
            Snapshot(day, new[] { baseline }),
            Snapshot(day, new[] { baseline }.Concat(added).ToArray()));
        var voice = new RecordingVoice();
        using (var form = new MainForm(provider, false, voice))
        {
            AssertTrue(!voice.Enabled, "unchecked voice control disables the service by default");
            voice.Enabled = true;
            await form.RefreshStockAsync("002297", true);
            AssertEqual(0, voice.Batches.Count, "first snapshot only establishes baseline");
            await form.RefreshStockAsync("002297", false);
            AssertEqual(1, voice.Batches.Count, "one voice batch");
            AssertEqual(4, voice.Batches[0].Count, "all new signals announced");
            AssertEqual(BigOrderAnnouncementType.Ignite, voice.Batches[0][0].Type, "first signal");
            AssertEqual(BigOrderAnnouncementType.Ignite, voice.Batches[0][1].Type, "second signal");
            AssertEqual(BigOrderAnnouncementType.Smash, voice.Batches[0][2].Type, "third signal");
            AssertEqual(BigOrderAnnouncementType.BuyActive, voice.Batches[0][3].Type, "fourth signal");
            AssertEqual("测试", voice.Batches[0][0].StockName, "stock name");
            AssertEqual(day.AddHours(9).AddMinutes(31), voice.Batches[0][0].Time, "signal time");
            AssertTrue(
                voice.Batches[0][0].AdditionalTypes.Contains(BigOrderAnnouncementType.BuyActive),
                "same order marker is preserved");
            AssertTrue(
                voice.Batches[0][2].AdditionalTypes.Contains(BigOrderAnnouncementType.GoodSupport),
                "same order support marker is preserved");
        }
    }

    internal static async Task TestMainFormAnnouncementBoundaries()
    {
        var day = new DateTime(2026, 7, 17);
        var baseline = Signal(day.AddHours(9).AddMinutes(30), "", "");
        var markerChanged = Signal(day.AddHours(9).AddMinutes(30), "点火", "买活跃");
        var added = Signal(day.AddHours(9).AddMinutes(31), "点火", "买活跃");
        var afterBarrier = Signal(day.AddHours(9).AddMinutes(32), "点火", "买活跃");
        var whileDisabled = Signal(day.AddHours(9).AddMinutes(33), "点火", "买活跃");
        var afterReenable = Signal(day.AddHours(9).AddMinutes(34), "点火", "买活跃");
        var provider = new SequenceProvider(
            Snapshot(day, new[] { baseline }),
            Snapshot(day, new[] { markerChanged }),
            Snapshot(day, new[] { markerChanged, added }),
            Snapshot(day, new[] { markerChanged, added }),
            Snapshot(day, new[] { markerChanged, added }, false),
            Snapshot(day, new[] { markerChanged, added }),
            Snapshot(day, new[] { markerChanged, added, afterBarrier }),
            Snapshot(day, new[] { markerChanged, added, afterBarrier, whileDisabled }),
            Snapshot(day, new[] { markerChanged, added, afterBarrier, whileDisabled }),
            Snapshot(day, new[] { markerChanged, added, afterBarrier, whileDisabled, afterReenable }));
        var voice = new RecordingVoice();
        using (var form = new MainForm(provider, false, voice))
        {
            voice.Enabled = true;
            await form.RefreshStockAsync("002297", true);
            await form.RefreshStockAsync("002297", false);
            AssertEqual(1, voice.Batches.Count, "delayed marker confirmation is announced once");

            typeof(MainForm).GetField("_specialFilter", BindingFlags.Instance | BindingFlags.NonPublic)
                .SetValue(form, "买活跃");
            await form.RefreshStockAsync("002297", false);
            AssertEqual(BigOrderAnnouncementType.BuyActive, voice.Batches[1].Single().Type,
                "special marker overrides default ignite priority");

            typeof(MainForm).GetField("_currentMoney", BindingFlags.Instance | BindingFlags.NonPublic)
                .SetValue(form, 30);
            await form.RefreshStockAsync("002297", false);
            AssertEqual(2, voice.Batches.Count, "filter change does not replay history");

            typeof(MainForm).GetField("_voiceReenableBarrier", BindingFlags.Instance | BindingFlags.NonPublic)
                .SetValue(form, true);
            await form.RefreshStockAsync("002297", false);
            AssertEqual(2, voice.Batches.Count, "null session date keeps re-enable barrier");
            await form.RefreshStockAsync("002297", false);
            AssertEqual(2, voice.Batches.Count, "first trusted snapshot only rebuilds baseline");
            await form.RefreshStockAsync("002297", false);
            AssertEqual(3, voice.Batches.Count, "new row after barrier is announced");

            voice.Enabled = false;
            await form.RefreshStockAsync("002297", false);
            AssertEqual(3, voice.Batches.Count, "disabled voice still advances tracker without speaking");
            voice.Enabled = true;
            typeof(MainForm).GetField("_voiceReenableBarrier", BindingFlags.Instance | BindingFlags.NonPublic)
                .SetValue(form, true);
            await form.RefreshStockAsync("002297", false);
            AssertEqual(3, voice.Batches.Count, "re-enable snapshot only rebuilds baseline");
            await form.RefreshStockAsync("002297", false);
            AssertEqual(4, voice.Batches.Count, "post re-enable increment is announced");
        }
    }

    internal static void TestParser()
    {
        var parser = new ThsPayloadParser();
        var compact = parser.ParseLonghuOrder(JArray.Parse(
            "['order-1','1784168251','2026-07-16 10:17:31','17.19','623','2','002297']"));
        AssertEqual(2, compact.Type, "compact type");
        AssertEqual(623d, compact.Volume, "compact volume");
        AssertNear(10709.37d, compact.Amount, 0.001d, "compact amount");
        AssertEqual(17.19d, compact.Price, "compact price");
        AssertEqual(new DateTime(2026, 7, 16, 10, 17, 31), compact.Time, "compact time");

        var upstream = parser.ParseLonghuOrder(JArray.Parse(
            "['2','1784168251','623','1070937','17.19','2026-07-16 10:17:31']"));
        AssertEqual(1070937d, upstream.Amount, "upstream money");

        var parsed = parser.ParseLonghuOrders(JArray.Parse(
            "[['order-1','1784168251','2026-07-16 10:17:31','17.19','623','2','002297'],['bad']]"));
        AssertEqual(1, parsed.Count, "invalid rows skipped");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse("['bad']")), "invalid row");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse(
                "['order-2','1784168251','2026-07-16 10:17:31','17.19','623','1.5','002297']")),
            "fractional tradetype");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse(
                "['order-3','0','2026-07-16 10:17:31','17.19','623','2','002297']")),
            "zero unix seconds");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse(
                "['order-4','1784168251','2026-07-16 10:17:31','0','623','2','002297']")),
            "zero price");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse(
                "['order-5','1784168251','2026-07-16 10:17:31','17.19','0','2','002297']")),
            "zero volume");
        AssertThrows<PayloadParseException>(
            () => parser.ParseLonghuOrder(JArray.Parse(
                "['2','1784168251','623','-1','17.19','2026-07-16 10:17:31']")),
            "negative money");
    }

    private sealed class RecordingSpeechQueue : ISpeechQueue
    {
        public List<string> Texts { get; } = new List<string>();
        public int CancelCount { get; private set; }
        public bool Disposed { get; private set; }
        public void SpeakAsync(string text) { Texts.Add(text); }
        public void CancelAll() { CancelCount++; }
        public void Dispose() { Disposed = true; }
    }

    private static BigOrderItem Signal(DateTime time, string fund, string buy)
    {
        return new BigOrderItem
        {
            Time = time,
            Type = fund == "砸盘" ? 4 : 2,
            Volume = 500000,
            Amount = 5000000,
            Price = 10,
            FundMarker = fund,
            BuyMarker = buy,
        };
    }

    private static MarketSnapshot Snapshot(
        DateTime day,
        IReadOnlyList<BigOrderItem> orders,
        bool hasSessionDate = true)
    {
        return new MarketSnapshot(
            "002297",
            new StockSummary { Code = "002297", Name = "测试", Price = 10 },
            new MainFundSummary(),
            new LimitUpContext(),
            orders,
            new PricePoint[0],
            new MinuteTurnoverPoint[0],
            DataFreshness.Fresh,
            DataFreshness.Fresh,
            DataFreshness.Missing,
            DataFreshness.Missing,
            day,
            day,
            bigOrderSessionDate: hasSessionDate ? (DateTime?)day : null);
    }

    private sealed class SequenceProvider : IMarketSnapshotProvider
    {
        private readonly Queue<MarketSnapshot> _snapshots;
        public SequenceProvider(params MarketSnapshot[] snapshots)
        {
            _snapshots = new Queue<MarketSnapshot>(snapshots);
        }
        public Task<MarketSnapshot> LoadSnapshotAsync(
            string stockCode, CancellationToken cancellationToken)
        {
            return Task.FromResult(_snapshots.Dequeue());
        }
        public void CalculateMarkers(List<BigOrderItem> data) { }
    }

    private sealed class FollowProvider : IMarketSnapshotProvider
    {
        public Task<MarketSnapshot> LoadSnapshotAsync(string stockCode, CancellationToken cancellationToken)
        {
            return Task.FromResult(new MarketSnapshot(
                stockCode,
                new StockSummary { Code = stockCode, Name = "测试" },
                new MainFundSummary(),
                new LimitUpContext(),
                new BigOrderItem[0],
                new PricePoint[0],
                DataFreshness.Fresh,
                DataFreshness.Fresh,
                DataFreshness.Missing,
                DateTime.Now,
                DateTime.Now));
        }

        public void CalculateMarkers(List<BigOrderItem> data) { }
    }

    private sealed class RecordingVoice : IBigOrderVoice
    {
        public bool Enabled { get; set; } = true;
        public List<IReadOnlyList<BigOrderAnnouncement>> Batches { get; } =
            new List<IReadOnlyList<BigOrderAnnouncement>>();
        public int CancelCount { get; private set; }
        public void AnnounceBatch(IReadOnlyList<BigOrderAnnouncement> announcements)
        {
            if (announcements.Count > 0) Batches.Add(announcements.ToArray());
        }
        public void CancelPending() { CancelCount++; }
        public void Dispose() { }
    }

    internal static async Task TestDirectSuccess()
    {
        var handler = new LonghuHandler { DirectMode = LonghuMode.OneValid };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(1, snapshot.Orders.Count, "direct order count");
            AssertEqual(DataTransport.Direct, snapshot.Transports.BigOrder, "direct transport");
            AssertEqual(0, handler.ProxyCalls, "proxy not called");
            var form = handler.DirectForms.Single();
            AssertEqual("0", form["Order"], "direct Order");
            AssertEqual("GetMainMonitor_w30", form["a"], "direct operation");
            AssertEqual("200", form["st"], "direct page size");
            AssertEqual("StockYiDongKanPan", form["c"], "direct controller");
            AssertEqual("1", form["PhoneOSNew"], "direct PhoneOSNew");
            AssertEqual("5.17.0.4", form["VerSion"], "direct version");
            AssertEqual("002297", form["StockID"], "direct stock");
            AssertEqual("w36", form["apiv"], "direct api version");
            AssertEqual("0", form["IsBS"], "direct IsBS");
            AssertTrue(!form.ContainsKey("PageSize"), "legacy PageSize removed");
            AssertTrue(!form.ContainsKey("Type"), "legacy Type removed");
        }
    }

    internal static async Task TestDirectFailureProxyFallback()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.HttpFailure,
            ProxyMode = LonghuMode.OneValid,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(1, snapshot.Orders.Count, "proxy order count");
            AssertEqual(DataTransport.ProxyPrimary, snapshot.Transports.BigOrder, "proxy transport");
            AssertEqual(1, handler.ProxyCalls, "proxy called");
            AssertEqual(
                "/api/big-order/longhu/all-day?stockCode=002297&money=0",
                handler.ProxyUris.Single().PathAndQuery,
                "proxy contract");
        }
    }

    internal static async Task TestPagination()
    {
        var handler = new LonghuHandler { DirectMode = LonghuMode.Paginated201 };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(201, snapshot.Orders.Count, "all pages");
            AssertSequence(new[] { 0, 200 }, handler.DirectIndexes, "direct indexes");
            AssertEqual(1, handler.DeviceIds.Distinct().Count(), "DeviceID reused");
        }
    }

    internal static async Task TestMidPageFailure()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.FailAfterFirstFullPage,
            ProxyMode = LonghuMode.OneValid,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(1, snapshot.Orders.Count, "no partial direct rows");
            AssertEqual(DataTransport.ProxyPrimary, snapshot.Transports.BigOrder, "whole request falls back");
        }
    }

    internal static async Task TestProxyPagination()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.HttpFailure,
            ProxyMode = LonghuMode.Paginated201,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(201, snapshot.Orders.Count, "proxy full snapshot");
            AssertEqual(1, handler.ProxyCalls, "proxy aggregate called once");
        }
    }

    internal static async Task TestMissingTotalPageGuard()
    {
        var handler = new LonghuHandler { DirectMode = LonghuMode.FullPagesWithoutTotal };
        using (var http = new HttpClient(handler))
        {
            var client = new LonghuBigOrderSourceClient(
                http, "http://127.0.0.1:3000", new ThsPayloadParser());
            try
            {
                await client.LoadDirectAsync("002297", CancellationToken.None);
            }
            catch (PayloadParseException)
            {
                AssertEqual(1, handler.DirectIndexes.Count, "missing Total rejected immediately");
                return;
            }
        }
        throw new InvalidOperationException("missing Total full pages expected PayloadParseException");
    }

    internal static async Task TestTotalOverrun()
    {
        var handler = new LonghuHandler { DirectMode = LonghuMode.TotalOverrun };
        using (var http = new HttpClient(handler))
        {
            var client = new LonghuBigOrderSourceClient(
                http, "http://127.0.0.1:3000", new ThsPayloadParser());
            try
            {
                await client.LoadDirectAsync("002297", CancellationToken.None);
            }
            catch (PayloadParseException)
            {
                return;
            }
        }
        throw new InvalidOperationException("rows beyond Total expected PayloadParseException");
    }

    internal static async Task TestTruncatedResponse()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.Truncated,
            ProxyMode = LonghuMode.OneValid,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(1, snapshot.Orders.Count, "proxy rows after truncation");
            AssertEqual(DataTransport.ProxyPrimary, snapshot.Transports.BigOrder, "truncation fallback");
        }
    }

    internal static async Task TestProxyUiStaleStatus()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.HttpFailure,
            ProxyMode = LonghuMode.OneValid,
            ProxyUiStale = true,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(DataFreshness.Stale, snapshot.BigOrderFreshness, "Longhu ui stale freshness");
            AssertEqual(DataTransport.Stale, snapshot.Transports.BigOrder, "Longhu ui stale transport");
            AssertTrue(snapshot.Transports.Summary.Contains("大单"), "Longhu stale transport remains identifiable");
        }
    }

    internal static async Task TestValidEmptyList()
    {
        var handler = new LonghuHandler { DirectMode = LonghuMode.Empty };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(0, snapshot.Orders.Count, "empty rows");
            AssertEqual(DataTransport.Direct, snapshot.Transports.BigOrder, "empty direct transport");
            AssertEqual(0, handler.ProxyCalls, "empty does not fallback");
        }
    }

    internal static async Task TestAllInvalidFallback()
    {
        var handler = new LonghuHandler
        {
            DirectMode = LonghuMode.AllInvalid,
            ProxyMode = LonghuMode.OneValid,
        };
        using (var provider = CreateHttpProvider(handler))
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var snapshot = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(1, snapshot.Orders.Count, "valid proxy row");
            AssertEqual(DataTransport.ProxyPrimary, snapshot.Transports.BigOrder, "invalid direct fallback");
        }
    }

    internal static async Task TestProviderRouting()
    {
        var sources = SourceSet.Create();
        using (var provider = sources.CreateProvider())
        {
            var ths = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(BigOrderDataSource.Ths, provider.DataSource, "default source");
            AssertEqual(2, ths.Orders.Single().Type, "THS order");
            AssertEqual(0, sources.Longhu.DirectCalls, "default skips Longhu");

            provider.DataSource = BigOrderDataSource.Longhu;
            var longhu = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(4, longhu.Orders.Single().Type, "Longhu order");
            AssertEqual(123d, longhu.MainFunds.MainBuy.Value, "THS summary retained");
            AssertEqual(1, longhu.Prices.Count, "THS prices retained");
            AssertEqual(DataTransport.Direct, longhu.Transports.BigOrder, "Longhu transport");

            sources.Ths.Direct = _ => Task.FromResult(SourceSet.BigResult(2, true, 456));
            await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            sources.Ths.Direct = _ => throw new HttpRequestException("THS direct failed");
            provider.DataSource = BigOrderDataSource.Ths;
            var staleThs = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(2, staleThs.Orders.Single().Type, "THS stale orders retained");
            AssertEqual(456d, staleThs.MainFunds.MainBuy.Value, "shared THS summary cache retained");
        }
    }

    internal static async Task TestProviderCacheIsolation()
    {
        var sources = SourceSet.Create();
        using (var provider = sources.CreateProvider())
        {
            await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            sources.Longhu.Direct = _ => throw new HttpRequestException("longhu direct failed");
            sources.Longhu.Proxy = _ => throw new HttpRequestException("longhu proxy failed");
            provider.DataSource = BigOrderDataSource.Longhu;
            var missingLonghu = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(0, missingLonghu.Orders.Count, "THS orders not reused for Longhu");
            AssertEqual(DataTransport.Failed, missingLonghu.Transports.BigOrder, "Longhu initially failed");

            sources.Longhu.Direct = _ => Task.FromResult(SourceSet.BigResult(4));
            var longhu = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(4, longhu.Orders.Single().Type, "Longhu cached");
            sources.Longhu.Direct = _ => throw new HttpRequestException("longhu direct failed");
            var staleLonghu = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(4, staleLonghu.Orders.Single().Type, "Longhu stale reused");
            AssertEqual(DataTransport.Stale, staleLonghu.Transports.BigOrder, "Longhu stale transport");
        }
    }

    internal static async Task TestProviderRejectsCrossDayLastGood()
    {
        var sources = SourceSet.Create();
        using (var provider = sources.CreateProvider())
        {
            provider.DataSource = BigOrderDataSource.Longhu;
            var first = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(new DateTime(2026, 7, 16), first.BigOrderSessionDate.Value,
                "first authoritative session date");

            var nextDay = new DateTime(2026, 7, 17);
            sources.Ths.Direct = _ => Task.FromResult(SourceSet.BigResult(2, true, 123, nextDay));
            sources.Minute.Direct = _ => Task.FromResult(Result<IReadOnlyList<MinuteTurnoverPoint>>(
                new[] { new MinuteTurnoverPoint { Time = nextDay.AddHours(9).AddMinutes(30), Price = 10 } }));
            sources.Longhu.Direct = _ => throw new HttpRequestException("longhu direct failed");
            sources.Longhu.Proxy = _ => throw new HttpRequestException("longhu proxy failed");

            var failed = await provider.LoadSnapshotAsync("002297", CancellationToken.None);
            AssertEqual(0, failed.Orders.Count, "previous-session orders are not reused");
            AssertEqual(DataTransport.Failed, failed.Transports.BigOrder,
                "cross-day failure remains failed");
            AssertTrue(!failed.BigOrderSessionDate.HasValue,
                "failed cross-day snapshot has no borrowed session date");
        }
    }

    internal static async Task TestMainFormDataSourceSwitch()
    {
        var sources = SourceSet.Create();
        using (var provider = sources.CreateProvider())
        using (var form = new MainForm(provider, false))
        {
            var combo = (ComboBox)typeof(MainForm)
                .GetField("cboDataSource", BindingFlags.Instance | BindingFlags.NonPublic)
                ?.GetValue(form);
            AssertTrue(combo != null, "ComboBox exists");
            AssertSequence(new[] { "龙虎大单", "THS大单" },
                combo.Items.Cast<object>().Select(value => value.ToString()), "options");
            AssertEqual(0, combo.SelectedIndex, "Longhu default selection");
            AssertEqual(BigOrderDataSource.Longhu, provider.DataSource, "Longhu default provider");

            await form.RefreshStockAsync("002963", true);
            var ordersField = typeof(MainForm)
                .GetField("_allData", BindingFlags.Instance | BindingFlags.NonPublic);
            var grid = (DataGridView)typeof(MainForm)
                .GetField("dataGridView1", BindingFlags.Instance | BindingFlags.NonPublic)
                ?.GetValue(form);
            var chart = (BigOrderChartControl)typeof(MainForm)
                .GetField("bigOrderChart", BindingFlags.Instance | BindingFlags.NonPublic)
                ?.GetValue(form);
            AssertEqual(4, ((List<BigOrderItem>)ordersField.GetValue(form)).Single().Type,
                "initial Longhu list");
            AssertEqual(1, form.VisibleChartOrderEvents.Count, "initial Longhu point");
            AssertEqual(1, grid.Rows.Count, "initial Longhu grid");
            AssertEqual(1, chart.BigOrderLinePercents.Count, "initial Longhu blue line");
            AssertEqual(2, chart.MinutePriceLinePercents.Count, "initial white line");
            AssertEqual(2, chart.MarketLinePercents.Count, "initial yellow line");

            var pendingThs =
                new TaskCompletionSource<SourceLoadResult<BigOrderSourceData>>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
            var previousThsCalls = sources.Ths.DirectCalls;
            sources.Ths.Direct = _ => pendingThs.Task;
            combo.SelectedIndex = 1;
            await WaitUntil(() => sources.Ths.DirectCalls > previousThsCalls, "THS refresh");
            AssertEqual(BigOrderDataSource.Ths, provider.DataSource, "provider switched");
            AssertEqual(0, ((List<BigOrderItem>)ordersField.GetValue(form)).Count,
                "old source list cleared while loading");
            AssertEqual(0, form.VisibleChartOrderEvents.Count,
                "old source points cleared while loading");
            AssertEqual(0, grid.Rows.Count, "old source grid cleared while loading");
            AssertEqual(0, chart.BigOrderLinePercents.Count,
                "old source blue line cleared while loading");
            AssertEqual(2, chart.MinutePriceLinePercents.Count,
                "white line retained while loading");
            AssertEqual(2, chart.MarketLinePercents.Count,
                "yellow line retained while loading");

            pendingThs.SetResult(SourceSet.BigResult(2));
            WaitUntilWithMessages(
                () => ((List<BigOrderItem>)ordersField.GetValue(form))
                    .Any(order => order.Type == 2),
                "THS list rebound");
            AssertEqual(2, ((List<BigOrderItem>)ordersField.GetValue(form)).Single().Type,
                "THS list rebound");
            AssertEqual(2, form.VisibleChartOrderEvents.Single().Type,
                "THS point rebound");
            AssertEqual(1, grid.Rows.Count, "Longhu grid rebound");
            AssertEqual("002963", form.BoundStockCode, "full refresh bound current code");
        }
    }

    internal static async Task TestMainFormDataSourceSwitchRace()
    {
        var sources = SourceSet.Create();
        using (var provider = sources.CreateProvider())
        using (var form = new MainForm(provider, false))
        {
            var ordersField = typeof(MainForm)
                .GetField("_allData", BindingFlags.Instance | BindingFlags.NonPublic);

            var pendingThs =
                new TaskCompletionSource<SourceLoadResult<BigOrderSourceData>>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
            sources.Ths.Direct = _ => pendingThs.Task;
            provider.DataSource = BigOrderDataSource.Ths;
            var oldRequest = form.RefreshStockAsync("002963", true);
            await WaitUntil(() => sources.Ths.DirectCalls > 0, "first THS request");

            var pendingLonghu =
                new TaskCompletionSource<SourceLoadResult<BigOrderSourceData>>(
                    TaskCreationOptions.RunContinuationsAsynchronously);
            sources.Longhu.Direct = _ => pendingLonghu.Task;
            provider.DataSource = BigOrderDataSource.Longhu;
            var latestRequest = form.RefreshStockAsync("600519", true);
            await WaitUntil(() => sources.Longhu.DirectCalls > 0, "latest Longhu request");

            pendingLonghu.SetResult(SourceSet.BigResult(4, true));
            pendingThs.SetResult(SourceSet.BigResult(2, true));
            WaitUntilWithMessages(
                () => ((List<BigOrderItem>)ordersField.GetValue(form))
                    .Any(order => order.Type == 4), "latest Longhu result");
            await Task.WhenAll(oldRequest, latestRequest);
            AssertEqual(4, ((List<BigOrderItem>)ordersField.GetValue(form)).Single().Type,
                "late THS result ignored");
            AssertEqual(BigOrderDataSource.Longhu, provider.DataSource,
                "latest selected source retained");
        }
    }

    private static THSBigOrderDataProvider CreateHttpProvider(LonghuHandler handler)
    {
        var http = new HttpClient(handler);
        var parser = new ThsPayloadParser();
        return new THSBigOrderDataProvider(
            new ThsBigOrderSourceClient(http, "http://127.0.0.1:3000", parser),
            new LonghuBigOrderSourceClient(http, "http://127.0.0.1:3000", parser),
            new FixedSource<StockSummary>(new StockSummary { Code = "002297", Name = "测试", Price = 10 }),
            new FixedSource<IReadOnlyList<MinuteTurnoverPoint>>(new MinuteTurnoverPoint[0]),
            new FixedSource<LimitUpSourceData>(new LimitUpSourceData()));
    }

    private enum LonghuMode
    {
        OneValid,
        Paginated201,
        FullPagesWithoutTotal,
        TotalOverrun,
        FailAfterFirstFullPage,
        Truncated,
        Empty,
        AllInvalid,
        HttpFailure,
    }

    private sealed class LonghuHandler : HttpMessageHandler
    {
        public LonghuMode DirectMode { get; set; } = LonghuMode.OneValid;
        public LonghuMode ProxyMode { get; set; } = LonghuMode.OneValid;
        public bool ProxyUiStale { get; set; }
        public int ProxyCalls { get; private set; }
        public List<int> DirectIndexes { get; } = new List<int>();
        public List<int> ProxyIndexes { get; } = new List<int>();
        public List<string> DeviceIds { get; } = new List<string>();
        public List<Dictionary<string, string>> DirectForms { get; } =
            new List<Dictionary<string, string>>();
        public List<Uri> ProxyUris { get; } = new List<Uri>();

        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var direct = request.RequestUri.Host == "apphwhq.longhuvip.com";
            var proxy = request.RequestUri.AbsolutePath == "/api/big-order/longhu/all-day";
            if (!direct && !proxy)
            {
                var thsJson = request.RequestUri.Host == "vaserviece.10jqka.com.cn"
                    ? "{'errorcode':0,'title':{'stockname':'测试','price':10,'mainbuy':'1万','mainsell':'0万'},'list':[],'pricechange':[]}"
                    : "{'ok':true,'data':{'title':{'stockname':'测试','price':10,'mainbuy':'1万','mainsell':'0万'},'list':[],'pricechange':[]}}";
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(thsJson, Encoding.UTF8, "application/json"),
                };
            }
            var values = direct
                ? ParsePairs(await request.Content.ReadAsStringAsync())
                : ParsePairs(request.RequestUri.Query.TrimStart('?'));
            var index = direct ? int.Parse(values["Index"]) : 0;
            var mode = direct ? DirectMode : ProxyMode;
            if (direct)
            {
                DirectIndexes.Add(index);
                DeviceIds.Add(values["DeviceID"]);
                DirectForms.Add(values);
            }
            else
            {
                ProxyCalls++;
                ProxyIndexes.Add(index);
                ProxyUris.Add(request.RequestUri);
            }

            if (mode == LonghuMode.HttpFailure ||
                mode == LonghuMode.FailAfterFirstFullPage && index >= 200)
            {
                return new HttpResponseMessage(HttpStatusCode.BadGateway)
                {
                    Content = new StringContent("upstream failed"),
                };
            }

            var rows = new JArray();
            var total = 1;
            if (mode == LonghuMode.Paginated201)
            {
                total = 201;
                AddRows(rows, proxy ? 201 : index == 0 ? 200 : 1);
            }
            else if (mode == LonghuMode.FullPagesWithoutTotal)
            {
                AddRows(rows, 200);
            }
            else if (mode == LonghuMode.TotalOverrun)
            {
                total = 1;
                AddRows(rows, 2);
            }
            else if (mode == LonghuMode.FailAfterFirstFullPage)
            {
                total = 201;
                AddRows(rows, 200);
            }
            else if (mode == LonghuMode.Truncated)
            {
                total = 201;
                AddRows(rows, 1);
            }
            else if (mode == LonghuMode.Empty)
            {
                total = 0;
            }
            else if (mode == LonghuMode.AllInvalid)
            {
                rows.Add(new JArray("bad"));
            }
            else
            {
                AddRows(rows, 1);
            }

            var payload = new JObject
            {
                ["List"] = rows,
                ["errcode"] = "0",
            };
            if (mode != LonghuMode.FullPagesWithoutTotal) payload["Total"] = total;
            if (proxy)
            {
                payload = new JObject
                {
                    ["ok"] = true,
                    ["sessionDate"] = "2026-07-16",
                    ["fetchedAt"] = 1784168251000,
                    ["data"] = new JObject
                    {
                        ["List"] = rows,
                        ["Total"] = total,
                        ["errcode"] = "0",
                        ["dragonMeta"] = new JObject
                        {
                            ["cache"] = new JObject { ["uiStale"] = ProxyUiStale },
                        },
                    },
                };
            }
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(payload.ToString(), Encoding.UTF8, "application/json"),
            };
        }

        private static void AddRows(JArray rows, int count)
        {
            for (var index = 0; index < count; index++)
            {
                rows.Add(new JArray(
                    "order-" + index, "1784168251", "2026-07-16 10:17:31",
                    "17.19", "623", "2", "002297"));
            }
        }
    }

    private sealed class SourceSet
    {
        public StubSource<BigOrderSourceData> Ths { get; private set; }
        public StubSource<BigOrderSourceData> Longhu { get; private set; }
        public StubSource<StockSummary> Quote { get; private set; }
        public StubSource<IReadOnlyList<MinuteTurnoverPoint>> Minute { get; private set; }
        public StubSource<LimitUpSourceData> Limit { get; private set; }

        public static SourceSet Create()
        {
            return new SourceSet
            {
                Ths = new StubSource<BigOrderSourceData> { Direct = _ => Task.FromResult(BigResult(2, true)) },
                Longhu = new StubSource<BigOrderSourceData> { Direct = _ => Task.FromResult(BigResult(4)) },
                Quote = new StubSource<StockSummary>
                {
                    Direct = _ => Task.FromResult(Result(new StockSummary
                    {
                        Code = "002297", Name = "测试", Price = 10, ChangePercent = 0,
                    })),
                },
                Minute = new StubSource<IReadOnlyList<MinuteTurnoverPoint>>
                {
                    Direct = _ => Task.FromResult(Result<IReadOnlyList<MinuteTurnoverPoint>>(
                        new[]
                        {
                            new MinuteTurnoverPoint
                            {
                                Time = new DateTime(2026, 7, 16, 9, 30, 0),
                                Price = 10,
                                CumulativeVolume = 100,
                                CumulativeAmount = 100000,
                            },
                            new MinuteTurnoverPoint
                            {
                                Time = new DateTime(2026, 7, 16, 9, 31, 0),
                                Price = 10.1,
                                CumulativeVolume = 200,
                                CumulativeAmount = 202000,
                            },
                        })),
                },
                Limit = new StubSource<LimitUpSourceData>
                {
                    Direct = _ => Task.FromResult(Result(new LimitUpSourceData())),
                },
            };
        }

        public THSBigOrderDataProvider CreateProvider()
        {
            return new THSBigOrderDataProvider(Ths, Longhu, Quote, Minute, Limit);
        }

        public static SourceLoadResult<BigOrderSourceData> BigResult(
            int type, bool summary = false, double mainBuy = 123, DateTime? sessionDate = null)
        {
            var day = (sessionDate ?? new DateTime(2026, 7, 16)).Date;
            return Result(new BigOrderSourceData
            {
                StockFallback = new StockSummary { Code = "002297", Name = "摘要", Price = 10 },
                MainFunds = summary
                    ? new MainFundSummary
                    {
                        MainBuy = mainBuy,
                        MainSell = 23,
                        NetAmount = mainBuy - 23,
                    }
                    : new MainFundSummary(),
                Orders = new[]
                {
                    new BigOrderItem
                    {
                        Type = type, Price = 10, Volume = 500000, Amount = 5000000,
                        Time = day.AddHours(10),
                    },
                },
                Prices = summary
                    ? new[] { new PricePoint { Time = day.AddHours(10), ChangePercent = 1 } }
                    : new PricePoint[0],
                SessionDate = day,
            });
        }
    }

    private sealed class FixedSource<T> : IMarketSourceClient<T>
    {
        private readonly T _data;
        public FixedSource(T data) { _data = data; }
        public Task<SourceLoadResult<T>> LoadDirectAsync(string stockCode, CancellationToken cancellationToken)
        {
            return Task.FromResult(Result(_data));
        }
        public Task<SourceLoadResult<T>> LoadProxyAsync(string stockCode, CancellationToken cancellationToken)
        {
            throw new InvalidOperationException("unexpected proxy call");
        }
    }

    private sealed class StubSource<T> : IMarketSourceClient<T>
    {
        public Func<CancellationToken, Task<SourceLoadResult<T>>> Direct { get; set; }
        public Func<CancellationToken, Task<SourceLoadResult<T>>> Proxy { get; set; }
        public int DirectCalls { get; private set; }

        public Task<SourceLoadResult<T>> LoadDirectAsync(string stockCode, CancellationToken cancellationToken)
        {
            DirectCalls++;
            return Direct(cancellationToken);
        }

        public Task<SourceLoadResult<T>> LoadProxyAsync(string stockCode, CancellationToken cancellationToken)
        {
            if (Proxy == null) throw new InvalidOperationException("unexpected proxy call");
            return Proxy(cancellationToken);
        }
    }

    private static SourceLoadResult<T> Result<T>(T data)
    {
        return new SourceLoadResult<T>
        {
            Data = data,
            Freshness = DataFreshness.Fresh,
            Transport = DataTransport.Direct,
            FetchedAt = DateTime.Now,
        };
    }

    private static Dictionary<string, string> ParsePairs(string value)
    {
        return value.Split(new[] { '&' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(part => part.Split(new[] { '=' }, 2))
            .ToDictionary(
                pair => Uri.UnescapeDataString(pair[0]),
                pair => pair.Length == 1 ? "" : Uri.UnescapeDataString(pair[1]));
    }

    private static async Task WaitUntil(Func<bool> condition, string label)
    {
        for (var attempt = 0; attempt < 80; attempt++)
        {
            if (condition()) return;
            await Task.Delay(25);
        }
        throw new InvalidOperationException(label + " timed out");
    }

    private static void WaitUntilWithMessages(Func<bool> condition, string label)
    {
        for (var attempt = 0; attempt < 80; attempt++)
        {
            Application.DoEvents();
            if (condition()) return;
            Thread.Sleep(25);
        }
        throw new InvalidOperationException(label + " timed out");
    }

    private static void AssertEqual<T>(T expected, T actual, string label)
    {
        if (!Equals(expected, actual))
            throw new InvalidOperationException(label + " expected " + expected + ", actual " + actual);
    }

    private static void AssertNear(double expected, double actual, double tolerance, string label)
    {
        if (Math.Abs(expected - actual) > tolerance)
            throw new InvalidOperationException(label + " expected " + expected + ", actual " + actual);
    }

    private static void AssertTrue(bool value, string label)
    {
        if (!value) throw new InvalidOperationException(label);
    }

    private static void AssertSequence<T>(IEnumerable<T> expected, IEnumerable<T> actual, string label)
    {
        if (!expected.SequenceEqual(actual))
            throw new InvalidOperationException(label + " sequence mismatch");
    }

    private static void AssertThrows<T>(Action action, string label) where T : Exception
    {
        try { action(); }
        catch (T) { return; }
        throw new InvalidOperationException(label + " expected " + typeof(T).Name);
    }
}
