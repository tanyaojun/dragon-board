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
                        lambda db, d, ds=None: ([{"date": "2026-10-01", "maxBoard": 4}], 3))
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
    assert "spaceCompress" not in types        # 今日 ≥3板=2 ≠ 0
    assert doc["ceiling"]["maxBoard"] == 5 and doc["ceiling"]["prevCeiling20"] == 4
    assert doc["anchor"]["main"]["code"] == "600111"
    assert doc["version"] == "v1"
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
    monkeypatch.setattr(omc, "_ceiling_window", lambda db, d, ds=None: ([], None))
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
                        lambda db, d, ds=None: ([{"date": "2026-10-01", "maxBoard": 10}], 3))


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
        "_id": f"{Y}:MARKET_CYCLE", "state": "ice", "daysInState": 2}
    doc = omc.settle_day(db, T)                  # prev_state=None → 读前一日库态
    assert doc["state"] == "ice" and doc["daysInState"] == 3


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
                        lambda db, d, ds=None: ([{"date": "x", "maxBoard": 4}], 3))
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [Y])
    monkeypatch.setattr(omc, "_anchor_fates", lambda db, d, ap, axis, ds=None: {})
    monkeypatch.setattr(omc, "_breakthrough_stocks", lambda db, d, st, mx: [])
    doc = omc.settle_day(FakeDb(), T)
    assert doc["status"] == "degraded"
    assert "spaceBreakthrough" in {e["type"] for e in doc["events"]}   # E1 仍产出
    assert any("E3/E4" in g for g in doc["meta"].get("dataGaps", []))


def test_jiuyan_missing_no_false_compress(monkeypatch):
    # major#2：韭研缺（streaks={}）但 THS 在场 → today_3plus 不可信→None，E2 不伪 0 误命中
    monkeypatch.setattr(omc, "compute_anchor",
                        lambda db, d, ds=None, **kw: ({"main": {"code": "600111"}},
                                                      {"status": "ok"}))
    monkeypatch.setattr(omc, "jiuyan_streak_map", lambda db, d, ds=None: {})
    monkeypatch.setattr(omc, "_ceiling_window",
                        lambda db, d, ds=None: ([{"date": "x", "maxBoard": 4}], 3))
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [Y])
    monkeypatch.setattr(omc, "_anchor_fates", lambda db, d, ap, axis, ds=None: {})
    doc = omc.settle_day(FakeDb(), T)
    assert "spaceCompress" not in {e["type"] for e in doc["events"]}   # 不伪 0
    assert doc["ceiling"]["maxBoard"] is None


def test_compress_real_zero_fires(monkeypatch):
    # E2 真实命中：今日 maxBoard 在场但 ≥3板=0（真零）且昨日≥1 → 命中
    monkeypatch.setattr(omc, "compute_anchor",
                        lambda db, d, ds=None, **kw: ({"main": {"code": "600111"}},
                                                      {"status": "ok"}))
    monkeypatch.setattr(omc, "jiuyan_streak_map", lambda db, d, ds=None: {"600111": 2})
    monkeypatch.setattr(omc, "_ceiling_window",
                        lambda db, d, ds=None: ([{"date": "x", "maxBoard": 4}], 3))
    monkeypatch.setattr(omc, "trading_dates_before", lambda db, d, n, ds=None: [Y])
    monkeypatch.setattr(omc, "_anchor_fates", lambda db, d, ap, axis, ds=None: {})
    doc = omc.settle_day(FakeDb(), T)
    assert "spaceCompress" in {e["type"] for e in doc["events"]}


def test_warmup_keyed_on_valid_refs(monkeypatch):
    # minor#4：日历窗 20 但有效参照不足 → 暖机旗标按有效 refs，落库 prevWindowValidDays
    _patch_gather(monkeypatch, fates={})
    win = [{"date": f"d{i}", "maxBoard": (4 if i < 3 else None)} for i in range(20)]
    monkeypatch.setattr(omc, "_ceiling_window", lambda db, d, ds=None: (win, 3))
    doc = omc.settle_day(FakeDb(), T)
    assert doc["ceiling"]["windowDays"] == 20
    assert doc["ceiling"]["prevWindowValidDays"] == 3
    assert doc["transition"]["evidence"]["warmup"] is True   # 有效 refs<20 → 暖机
