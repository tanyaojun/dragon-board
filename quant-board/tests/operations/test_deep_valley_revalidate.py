# -*- coding: utf-8 -*-
"""C9 月度复验测试：深谷样本筛选/代理收益/无深谷日 fail-visible。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.deep_valley_revalidate import revalidate_month


class FakeCol:
    def __init__(self, eod):
        self.eod = eod

    def find(self, query, projection=None):
        rng = query.get("tradingDate")
        if isinstance(rng, dict) and "$regex" in rng:
            return [{"tradingDate": d, "emotionScore": {"score": s}}
                    for d, s in sorted(self.eod.items()) if d.startswith(rng["$regex"])]
        if query.get("slotTime") == "EOD":  # _eod_scores：全量 EOD 序列
            return [{"tradingDate": d, "emotionScore": {"score": s}}
                    for d, s in sorted(self.eod.items())]
        return []

    def find_one(self, query, projection=None):
        return None


class FakeDb:
    def __init__(self, eod):
        self._e = eod
        self._frames = {}

    def __getitem__(self, name):
        if name == "hotlist_sentiment":
            return FakeCol(self._e)
        return _FrameCol(self._frames)


class _FrameCol:
    def __init__(self, store):
        self._store = store

    def find(self, query, projection=None):
        d = query.get("tradingDate")
        if not isinstance(d, str):
            return []
        slots = (query.get("slotTime") or {})
        allowed = slots.get("$in") if isinstance(slots, dict) else None
        return [r for r in self._store.get(d, []) if allowed is None or r["slotTime"] in allowed]


def _mk_db(scores):
    db = FakeDb(scores)
    frames = {}
    for d in sorted(scores):
        for slot, pct in (("09:35", 1.0), ("15:00", 2.0)):
            for k in range(40):  # 池 ≥30 才计代理收益
                frames.setdefault(d, []).append({"code": f"C{k:03d}", "slotTime": slot, "pctChange": pct})
    db._frames = frames
    return db


def test_revalidate_samples_and_baseline():
    scores = {f"2026-09-{d:02d}": v for d, v in zip((1, 2, 3, 4, 5, 8, 9), (50, 50, 20, 50, 50, 50, 50))}
    db = _mk_db(scores)
    out = revalidate_month(db, "2026-09")
    assert out["ok"] is True and out["noData"] is False
    assert out["samples"][0]["date"] == "2026-09-03"
    assert out["samples"][0]["eodScore"] == 20
    # 代理收益 = 15:00 pct 2.0 - 09:35 pct 1.0 = +1.0
    assert out["samples"][0]["poolRetPct"] == 1.0
    assert out["summary"]["deepSamples"] == 1


def test_revalidate_no_deep_day_fail_visible():
    scores = {f"2026-09-{d:02d}": 45 for d in range(1, 6)}
    out = revalidate_month(_mk_db(scores), "2026-09")
    assert out["noData"] is True and out["samples"] == []
    assert "无深谷状态日" in out["reason"]
