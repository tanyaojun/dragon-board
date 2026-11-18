# -*- coding: utf-8 -*-
"""第4课·市场情绪周期 操作层测试（P1，2026-11-12）。

零 DB 零 jev（硬红线 §1.2-7）：取料 helper 全 monkeypatch，FakeDb 只验证落库编排
（事件汇集 / doc 结构 / 幂等 generatedAt / 降级落痕）。纯检测器正反例见
tests/hotlist/test_market_cycle.py。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.market_cycle as omc

T, Y = "2026-11-12", "2026-11-11"


class _Col:
    def __init__(self):
        self.docs = {}

    def replace_one(self, q, doc, upsert=False):
        self.docs[q["_id"]] = doc

    def find_one(self, q=None, projection=None):
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in (q or {}).items()):
                return dict(d)
        return None

    def find(self, q=None, projection=None):
        import re
        out = []
        for d in self.docs.values():
            ok = True
            for k, v in (q or {}).items():
                if isinstance(v, dict) and "$regex" in v:
                    if not re.search(v["$regex"], str(d.get(k, ""))):
                        ok = False
                        break
                elif d.get(k) != v:
                    ok = False
                    break
            if ok:
                out.append(dict(d))
        return out

    def update_one(self, q, update, upsert=False):
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in q.items()):
                d.update(update.get("$set", {}))
                return


class FakeDb:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, _Col())


def test_compute_anchor_degraded_when_ths_missing(monkeypatch):
    monkeypatch.setattr(omc, "sealed_and_info",
                        lambda db, d, ds=None: (None, {}, {"thsPoolFound": False}))
    anchors, meta = omc.compute_anchor(FakeDb(), T)
    assert anchors is None and meta["status"] == "degraded"
    assert "THS" in meta["reason"]


def test_compute_anchor_histstreak_newest_seal_day(monkeypatch):
    # v13(甲)：断板候选 histStreak=最近封板日真连板，非近3日峰值。
    # 600222 三日封板 streak 5/6/3 → 取最近封板日 P_NEW 的 3（乙会误取峰值6）。
    P_OLD, P_MID, P_NEW = "2026-11-06", "2026-11-09", "2026-11-10"
    sealed = {T: {"600111"}, P_OLD: {"600222"}, P_MID: {"600222"}, P_NEW: {"600222"}}
    streaks = {T: {"600111": 2}, P_OLD: {"600222": 5},
               P_MID: {"600222": 6}, P_NEW: {"600222": 3}}
    stocks = {T: [{"code": "600111", "name": "今封", "time": "09:30"}],
              P_OLD: [{"code": "600222", "name": "断板龙头"}],
              P_MID: [{"code": "600222", "name": "断板龙头"}],
              P_NEW: [{"code": "600222", "name": "断板龙头"}]}
    monkeypatch.setattr(omc, "sealed_and_info",
                        lambda db, d, ds=None: (sealed.get(d, set()), {}, {}))
    monkeypatch.setattr(omc, "jiuyan_streak_map", lambda db, d, ds=None: streaks.get(d, {}))
    monkeypatch.setattr(omc, "_final_stocks", lambda db, d: stocks.get(d, []))
    monkeypatch.setattr(omc, "_jiuyan_days_boards", lambda st: (12, 8))
    # 锚三态单源 day_status_of 需 bars（零外呼：monkeypatch 覆盖式日线）
    monkeypatch.setattr(omc, "bars_covering", lambda c, d: {
        P_NEW: {"close": 10.0, "amount": 1e8},
        T: {"close": 9.5, "amount": 1e8}})
    anchors, meta = omc.compute_anchor(
        FakeDb(), T, pool_dates=[P_OLD, P_MID, P_NEW],
        gain_fetcher=lambda codes, d: {},
        day_change_fetcher=lambda codes, d: {c: None for c in codes})
    a = anchors["main"]
    assert a["code"] == "600222"                 # 最近封板日3板龙头，非今封2板股
    assert a["height"] == 3                      # 最近封板日 streak，非峰值6
    assert a["poolDay"] == P_NEW                 # E4 窗起点=最近封板日
    assert a["leaderSealedToday"] is False and a["streak"] is None


def _patch_gather(monkeypatch, *, fates):
    def fake_anchor(db, d, ds=None, **kw):
        if d == T:
            return ({"main": {"code": "600111", "name": "今龙", "segment": "main",
                              "streak": 5, "leaderSealedToday": True, "poolDay": None}},
                    {"status": "ok"})
        return ({"main": {"code": "600999", "name": "昨龙", "segment": "main",
                          "streak": None, "leaderSealedToday": False,
                          "poolDay": "2026-11-09"}}, {"status": "ok"})

    monkeypatch.setattr(omc, "compute_anchor", fake_anchor)
    monkeypatch.setattr(omc, "jiuyan_streak_map",
                        lambda db, d, ds=None: {"600111": 5, "600222": 3})
    monkeypatch.setattr(omc, "_ceiling_window",
                        lambda db, d, ds=None: [{"date": "2026-10-01", "maxBoard": 4}])
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [Y])
    monkeypatch.setattr(omc, "_anchor_fates", lambda db, d, ap, axis, ds=None: fates)
    monkeypatch.setattr(omc, "_breakthrough_stocks",
                        lambda db, d, st, mx: [{"code": "600111", "streak": 5,
                                                "oneWord": True}])


def test_settle_day_collects_events_and_idempotent(monkeypatch):
    fates = {"main": {
        "anchor": {"code": "600999", "name": "昨龙", "statusYesterday": "broken",
                   "poolDay": "2026-11-09"},
        "fate_today": {"pct": -10.0, "status": "broken"},
        "fate_yesterday": {"pct": 10.0, "status": "sealed"},
        "stabilize_window": None}}
    _patch_gather(monkeypatch, fates=fates)
    db = FakeDb()
    doc = omc.settle_day(db, T)
    assert doc["status"] == "ok"
    types = {e["type"] for e in doc["events"]}
    assert "spaceBreakthrough" in types        # maxBoard 5 > 天花板 4
    assert "highCollapse" in types             # 昨龙今日跌停（1日型）
    assert "spaceCompress" not in types        # 今日 maxBoard=5>4，空间已打开不压缩
    assert doc["ceiling"]["maxBoard"] == 5 and doc["ceiling"]["prevCeiling20"] == 4
    assert doc["anchor"]["main"]["code"] == "600111"
    assert doc["version"] == "v3"
    # 幂等：重跑保留首次 generatedAt，落库可查
    g1 = doc["generatedAt"]
    doc2 = omc.settle_day(db, T)
    assert doc2["generatedAt"] == g1
    assert db[omc.COLLECTION].find_one({"_id": f"{T}:MARKET_CYCLE"}) is not None


def test_settle_day_degraded_lands_with_reason(monkeypatch):
    monkeypatch.setattr(omc, "compute_anchor",
                        lambda db, d, ds=None, **kw: (None, {"status": "degraded",
                                                             "reason": "THS 池缺失"}))
    monkeypatch.setattr(omc, "jiuyan_streak_map", lambda db, d, ds=None: {})
    monkeypatch.setattr(omc, "_ceiling_window", lambda db, d, ds=None: [])
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [])
    db = FakeDb()
    doc = omc.settle_day(db, T)
    assert doc["status"] == "degraded" and doc["events"] == []
    assert "reason" in doc["meta"]
    assert db[omc.COLLECTION].find_one({"_id": f"{T}:MARKET_CYCLE"})["status"] == "degraded"


def test_settle_day_tolerance_rebound_event(monkeypatch):
    fates = {"main": {
        "anchor": {"code": "600999", "name": "昨龙", "statusYesterday": "broken",
                   "poolDay": "2026-11-10"},
        "fate_today": {"pct": 10.0, "status": "sealed"},
        "fate_yesterday": {"pct": -2.0, "status": "broken"},
        "stabilize_window": None}}
    _patch_gather(monkeypatch, fates=fates)
    doc = omc.settle_day(FakeDb(), T)
    tol = [e for e in doc["events"] if e["type"] == "highTolerance"]
    assert len(tol) == 1 and tol[0]["subtype"] == "rebound"


# ══ P2 状态机集成（state/transition/daysInState/reference）══
def _no_bt(monkeypatch):
    # 抬高天花板 → 无突破，隔离 E3/E4/无事件场景
    monkeypatch.setattr(omc, "_ceiling_window",
                        lambda db, d, ds=None: [{"date": "2026-10-01", "maxBoard": 10}])


def test_settle_day_state_fields_present(monkeypatch):
    _patch_gather(monkeypatch, fates={})
    _no_bt(monkeypatch)
    doc = omc.settle_day(FakeDb(), T)
    assert doc["state"] == "loss"                 # 首日无事件 init（Q6=A）
    assert doc["transition"]["from"] is None and doc["daysInState"] == 1
    assert "reference" in doc and doc["reference"]["relayPhase"] is None  # 缺→None


def test_settle_day_state_migration_with_prev(monkeypatch):
    fates = {"main": {
        "anchor": {"code": "600999", "name": "昨龙", "statusYesterday": "broken",
                   "poolDay": "2026-11-10"},
        "fate_today": {"pct": 10.0, "status": "sealed"},
        "fate_yesterday": {"pct": -2.0, "status": "broken"},
        "stabilize_window": None}}
    _patch_gather(monkeypatch, fates=fates)
    _no_bt(monkeypatch)
    doc = omc.settle_day(FakeDb(), T, prev_state="loss", prev_days_in_state=3)
    assert {e["type"] for e in doc["events"]} == {"highTolerance"}
    assert doc["state"] == "wzs" and doc["transition"]["from"] == "loss"
    assert doc["daysInState"] == 1               # 迁移重置


def test_settle_day_no_event_self_hold_days(monkeypatch):
    _patch_gather(monkeypatch, fates={})
    _no_bt(monkeypatch)
    doc = omc.settle_day(FakeDb(), T, prev_state="gain", prev_days_in_state=4)
    assert doc["events"] == [] and doc["state"] == "gain" and doc["transition"] is None
    assert doc["daysInState"] == 5               # 自持累加


def test_settle_day_single_day_reads_prev_doc(monkeypatch):
    _patch_gather(monkeypatch, fates={})
    _no_bt(monkeypatch)
    db = FakeDb()
    db[omc.COLLECTION].docs[f"{Y}:MARKET_CYCLE"] = {
        "_id": f"{Y}:MARKET_CYCLE", "state": "gain", "daysInState": 2}
    doc = omc.settle_day(db, T)                  # prev_state=None → 读前一日库态
    assert doc["state"] == "gain" and doc["daysInState"] == 3


def test_reference_snapshot_reads_relay_and_rule():
    db = FakeDb()
    db["hotlist_jev_relay_index"].docs[f"{T}:RELAY"] = {
        "_id": f"{T}:RELAY", "relayPhase": "divergence", "relayIndex": 52.6,
        "wzs": {"hit": False, "state": "strong"}}
    db["hotlist_sentiment"].docs["r1"] = {
        "datasetId": omc.DEFAULT_DATASET_ID, "snapshotType": "half_hour",
        "slotTime": "EOD", "tradingDate": T, "stage": "高潮",
        "emotionScore": {"score": 76.5}}
    ref = omc._reference_snapshot(db, T, omc.DEFAULT_DATASET_ID)
    assert ref["relayPhase"] == "divergence" and ref["relayIndex"] == 52.6
    assert ref["marketWzs"]["state"] == "strong"
    assert ref["ruleStage"] == "高潮" and ref["ruleScore"] == 76.5


# ── v8 解环（Option A，2026-11-12）：确定性步在 relay 前，reference 后置补刷 ──────────


_V8_FATES = {"main": {
    "anchor": {"code": "600999", "name": "昨龙", "statusYesterday": "broken",
               "poolDay": "2026-11-09"},
    "fate_today": {"pct": 2.0, "status": "sealed"},
    "fate_yesterday": {"pct": 10.0, "status": "sealed"},
    "stabilize_window": None}}


def test_settle_day_defer_reference_leaves_relay_none(monkeypatch):
    """defer_reference=True（确定性步在 relay 前）→ relay 参照留 None，事件/态照常产出。"""
    _patch_gather(monkeypatch, fates=_V8_FATES)
    db = FakeDb()
    doc = omc.settle_day(db, T, defer_reference=True)   # relay 档尚未落库
    assert doc["status"] == "ok" and doc["state"]
    assert doc["reference"]["relayIndex"] is None
    assert doc["reference"]["relayPhase"] is None
    assert doc["reference"]["marketWzs"] is None


def test_refresh_reference_fills_relay_after(monkeypatch):
    """relay 落库后 refresh_reference 补刷并列参照（事件/锚/态不动）；doc 缺→None 不阻断。"""
    _patch_gather(monkeypatch, fates=_V8_FATES)
    db = FakeDb()
    doc = omc.settle_day(db, T, defer_reference=True)
    assert doc["reference"]["relayIndex"] is None
    db["hotlist_jev_relay_index"].docs[f"{T}:RELAY"] = {
        "_id": f"{T}:RELAY", "relayPhase": "relay_heat", "relayIndex": 67.3,
        "wzs": {"hit": False, "state": "strong"}}
    ref = omc.refresh_reference(db, T)
    assert ref["relayIndex"] == 67.3 and ref["relayPhase"] == "relay_heat"
    stored = db[omc.COLLECTION].find_one({"_id": f"{T}:MARKET_CYCLE"})
    assert stored["reference"]["relayIndex"] == 67.3
    assert stored["state"] == doc["state"]              # 态不动（只补参照）
    assert omc.refresh_reference(db, "2026-01-01") is None


def test_backfill_carries_state(monkeypatch):
    calls = []
    states = {"d1": ("loss", 1), "d2": ("wzs", 1), "d3": ("gain", 1)}

    def fake_settle(db, d, ds=None, **kw):
        calls.append((d, kw.get("prev_state"), kw.get("prev_days_in_state")))
        st, dy = states[d]
        return {"anchor": {}, "state": st, "daysInState": dy, "events": [],
                "status": "ok", "ceiling": {}}

    monkeypatch.setattr(omc, "settle_day", fake_settle)
    db = FakeDb()
    for d in ("d1", "d2", "d3"):
        db["jiuyan_action"].docs[f"{d}:final"] = {"_id": f"{d}:final", "tradingDate": d}
    omc.backfill(db, "d1", "d3")
    assert [c[1] for c in calls] == [None, "loss", "wzs"]   # prev_state 逐日携带
    assert [c[2] for c in calls] == [0, 1, 1]


def test_replay_state_over_stored_events():
    db = FakeDb()
    # 已落库事件流：d1 无事件 / d2 宽容 / d3 突破（不重取 TDX）
    seed = [("d1", [], 20), ("d2", [{"type": "highTolerance"}], 20),
            ("d3", [{"type": "spaceBreakthrough"}], 20)]
    for d, ev, wd in seed:
        db[omc.COLLECTION].docs[f"{d}:MARKET_CYCLE"] = {
            "_id": f"{d}:MARKET_CYCLE", "tradingDate": d, "events": ev,
            "ceiling": {"windowDays": wd}}
    rows = omc.replay_state(db, "d1", "d3")
    assert [r["state"] for r in rows] == ["loss", "wzs", "gain"]
    # 补写进既有 doc（事件不动）
    d2 = db[omc.COLLECTION].find_one({"_id": "d2:MARKET_CYCLE"})
    assert d2["state"] == "wzs" and d2["daysInState"] == 1
    assert d2["events"] == [{"type": "highTolerance"}]
    assert "reference" in d2


# ══ 评审 fail-visible 边界（major#1/#2）══
def test_ths_degraded_still_produces_e1_e2(monkeypatch):
    # major#1：THS 池缺（锚不可算）但韭研在场 → E1/E2 独立可算仍产出，不连带阻断
    monkeypatch.setattr(omc, "compute_anchor",
                        lambda db, d, ds=None, **kw: (None, {"status": "degraded",
                                                             "reason": "THS 池缺失"}))
    monkeypatch.setattr(omc, "jiuyan_streak_map",
                        lambda db, d, ds=None: {"600111": 5, "600222": 3})
    monkeypatch.setattr(omc, "_ceiling_window",
                        lambda db, d, ds=None: [{"date": "x", "maxBoard": 4}])
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [Y])
    monkeypatch.setattr(omc, "_anchor_fates", lambda db, d, ap, axis, ds=None: {})
    monkeypatch.setattr(omc, "_breakthrough_stocks", lambda db, d, st, mx: [])
    doc = omc.settle_day(FakeDb(), T)
    assert doc["status"] == "degraded"
    assert "spaceBreakthrough" in {e["type"] for e in doc["events"]}   # E1 仍产出
    assert any("E3/E4" in g for g in doc["meta"].get("dataGaps", []))


def test_jiuyan_missing_no_false_compress(monkeypatch):
    # major#2：韭研缺（streaks={}）→ maxBoard None → 持续段断链，E2 v2 不伪压缩
    monkeypatch.setattr(omc, "compute_anchor",
                        lambda db, d, ds=None, **kw: ({"main": {"code": "600111"}},
                                                      {"status": "ok"}))
    monkeypatch.setattr(omc, "jiuyan_streak_map", lambda db, d, ds=None: {})
    monkeypatch.setattr(omc, "_ceiling_window",
                        lambda db, d, ds=None: [{"date": "x", "maxBoard": 4}])
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [Y])
    monkeypatch.setattr(omc, "_anchor_fates", lambda db, d, ap, axis, ds=None: {})
    doc = omc.settle_day(FakeDb(), T)
    assert "spaceCompress" not in {e["type"] for e in doc["events"]}   # 不伪压缩
    assert doc["ceiling"]["maxBoard"] is None


def test_compress_v2_persistence_fires(monkeypatch):
    # E2 v2：今日 maxBoard=2 + 昨日窗 maxBoard=4 → 连续2日≤4 → 压缩命中（regime）
    monkeypatch.setattr(omc, "compute_anchor",
                        lambda db, d, ds=None, **kw: ({"main": {"code": "600111"}},
                                                      {"status": "ok"}))
    monkeypatch.setattr(omc, "jiuyan_streak_map", lambda db, d, ds=None: {"600111": 2})
    monkeypatch.setattr(omc, "_ceiling_window",
                        lambda db, d, ds=None: [{"date": "x", "maxBoard": 4}])
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [Y])
    monkeypatch.setattr(omc, "_anchor_fates", lambda db, d, ap, axis, ds=None: {})
    doc = omc.settle_day(FakeDb(), T)
    e2 = [e for e in doc["events"] if e["type"] == "spaceCompress"]
    assert e2 and e2[0]["lowStreak"] == 2 and e2[0]["maxBoard"] == 2


def test_compress_v2_single_low_day_no_fire(monkeypatch):
    # E2 v2：仅今日低位（昨日窗 maxBoard=5>4）→ 持续段=1 → 不命中（regime 需≥2日）
    monkeypatch.setattr(omc, "compute_anchor",
                        lambda db, d, ds=None, **kw: ({"main": {"code": "600111"}},
                                                      {"status": "ok"}))
    monkeypatch.setattr(omc, "jiuyan_streak_map", lambda db, d, ds=None: {"600111": 2})
    monkeypatch.setattr(omc, "_ceiling_window",
                        lambda db, d, ds=None: [{"date": "x", "maxBoard": 5}])
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [Y])
    monkeypatch.setattr(omc, "_anchor_fates", lambda db, d, ap, axis, ds=None: {})
    doc = omc.settle_day(FakeDb(), T)
    assert "spaceCompress" not in {e["type"] for e in doc["events"]}


def test_warmup_keyed_on_valid_refs(monkeypatch):
    # minor#4：日历窗 20 但有效参照不足 → 暖机旗标按有效 refs，落库 prevWindowValidDays
    _patch_gather(monkeypatch, fates={})
    win = [{"date": f"d{i}", "maxBoard": (4 if i < 3 else None)} for i in range(20)]
    monkeypatch.setattr(omc, "_ceiling_window", lambda db, d, ds=None: win)
    doc = omc.settle_day(FakeDb(), T)
    assert doc["ceiling"]["windowDays"] == 20
    assert doc["ceiling"]["prevWindowValidDays"] == 3
    assert doc["transition"]["evidence"]["warmup"] is True   # 有效 refs<20 → 暖机


def test_settle_day_ice_lift_on_compress_release(monkeypatch):
    # v2：prev=ice，今日空间打开（maxBoard=5>4）无其他事件 → 压缩解除 ice 退 loss
    _patch_gather(monkeypatch, fates={})
    _no_bt(monkeypatch)
    doc = omc.settle_day(FakeDb(), T, prev_state="ice", prev_days_in_state=3)
    assert doc["state"] == "loss"
    assert doc["transition"]["trigger"] == omc.mc.TRIG_COMPRESS_LIFT


def test_compress_v2_fires_under_ths_degraded(monkeypatch):
    # major#1 v2：THS 缺（锚不可判）但韭研在场 + 天花板持续低位 → E2 v2 仍产出
    monkeypatch.setattr(omc, "compute_anchor",
                        lambda db, d, ds=None, **kw: (None, {"status": "degraded",
                                                             "reason": "THS 池缺失"}))
    monkeypatch.setattr(omc, "jiuyan_streak_map", lambda db, d, ds=None: {"600111": 3})
    monkeypatch.setattr(omc, "_ceiling_window",
                        lambda db, d, ds=None: [{"date": "x", "maxBoard": 4}])
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [Y])
    monkeypatch.setattr(omc, "_anchor_fates", lambda db, d, ap, axis, ds=None: {})
    doc = omc.settle_day(FakeDb(), T)
    assert doc["status"] == "degraded"
    assert "spaceCompress" in {e["type"] for e in doc["events"]}   # E2 独立韭研仍产出


def test_recompress_and_replay_from_stored_ceiling():
    # 改门历史重算：从已落库 ceiling.maxBoard 重算 E2 v2 + 重放态（不重取 TDX）
    db = FakeDb()
    # d1..d4 天花板 5,4,4,5 → d3 起持续≥2 → d3 压缩入 ice，d4 解除退 loss
    for d, mb in [("d1", 5), ("d2", 4), ("d3", 4), ("d4", 5)]:
        db[omc.COLLECTION].docs[f"{d}:MARKET_CYCLE"] = {
            "_id": f"{d}:MARKET_CYCLE", "tradingDate": d, "events": [],
            "ceiling": {"maxBoard": mb, "windowDays": 20, "prevWindowValidDays": 20}}
    rows = omc.recompress_and_replay(db, "d1", "d4")
    assert [r["state"] for r in rows] == ["loss", "loss", "ice", "loss"]
    assert [r["e2"] for r in rows] == [False, False, True, False]
    d3 = db[omc.COLLECTION].find_one({"_id": "d3:MARKET_CYCLE"})
    assert d3["state"] == "ice" and d3["version"] == "v3"
    assert any(e["type"] == "spaceCompress" for e in d3["events"])


def test_compute_anchor_suspension_three_state(monkeypatch):
    """2026-11-18 天普案同源：市场锚三态 day_status_of（停牌≠未封板）。"""
    pseudo = {Y: {"close": 73.82, "high": 73.82, "amount": 1.79e8},
              T: {"close": 73.82, "high": 73.82, "amount": 5.877e-39}}
    monkeypatch.setattr(omc, "sealed_and_info",
                        lambda db, d, ds=None: (({"605255"}, {}, {}) if d == Y
                                                else (set(), {}, {"thsPoolFound": True})))
    monkeypatch.setattr(omc, "_final_stocks",
                        lambda db, d: ([{"code": "605255", "name": "天普股份",
                                         "days": 4, "boards": 4}] if d == Y else []))
    monkeypatch.setattr(omc, "jiuyan_streak_map",
                        lambda db, d, ds=None: ({"605255": 4} if d == Y else {}))
    monkeypatch.setattr(omc, "_jiuyan_days_boards", lambda st: (4, 4))
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [Y])
    monkeypatch.setattr(omc, "bars_covering", lambda c, d: pseudo)
    anchors, _meta = omc.compute_anchor(None, T, gain_fetcher=lambda cs, d: {},
                                        day_change_fetcher=lambda cs, d: {})
    a = anchors["main"]
    assert a["dayStatus"] == "suspended" and a["leaderSealedToday"] is None
    assert a["streak"] is None and a["poolDay"] == Y and a["boards"] == 4
    real = {Y: {"close": 73.82, "amount": 1.79e8},
            T: {"close": 70.0, "amount": 2e8}}
    monkeypatch.setattr(omc, "bars_covering", lambda c, d: real)
    anchors2, _m2 = omc.compute_anchor(None, T, gain_fetcher=lambda cs, d: {},
                                       day_change_fetcher=lambda cs, d: {})
    assert anchors2["main"]["dayStatus"] == "broken"
    assert anchors2["main"]["leaderSealedToday"] is False
