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
