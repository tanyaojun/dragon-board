# -*- coding: utf-8 -*-
"""涨停打标读数聚合测试：个股/哨兵分流 + no_data fail-visible + 分布小结。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.jev.jev_limitup_labels import collect_limitup_labels


class FakeCol:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, query, projection=None):
        for d in self.docs:
            if d.get("_id") == query.get("_id") and d.get("status") == query.get("status"):
                return d
        return None

    def find(self, query, projection=None):
        excluded = (query.get("origin") or {}).get("$ne")
        return [d for d in self.docs
                if d.get("tradingDate") == query.get("tradingDate")
                and d.get("status") == query.get("status")
                and d.get("origin") != excluded]


class FakeDb:
    def __init__(self, docs):
        self._col = FakeCol(docs)

    def __getitem__(self, name):
        return self._col


def _stock(code, rank=None, label="ma_restructure"):
    return {"_id": f"2026-09-30:{code}", "tradingDate": "2026-09-30", "status": "ok",
            "origin": "driver_label_jiuyan_v3_pilot", "code": code, "name": "X",
            "label": label, "catalystDepth": "core_main_business", "freshness": "continuing",
            "buySideLogic": "sector_follow",
            "jiuyanContext": {"inHotlist": rank is not None, "rank": rank}}


def test_collect_splits_phase_and_stocks():
    docs = [{"_id": "2026-09-30:PHASE", "tradingDate": "2026-09-30", "status": "ok",
             "origin": "phase_band_daily", "phaseBand": "strong_ge60",
             "phaseBandProbabilities": {"strong_ge60": 0.7}, "computedAt": "t"},
            _stock("600000", 5), _stock("000001")]
    out = collect_limitup_labels(FakeDb(docs), "2026-09-30")
    assert out["ok"] is True and out["noData"] is False
    assert out["phase"]["band"] == "strong_ge60"
    assert len(out["stocks"]) == 2  # PHASE 哨兵不混入个股列表
    assert out["summary"]["total"] == 2
    assert out["summary"]["label"]["ma_restructure"] == 2
    # 无排名沉底：有排名在前
    assert out["stocks"][0]["rank"] == 5


def test_collect_no_data_fail_visible():
    out = collect_limitup_labels(FakeDb([]), "2026-10-11")
    assert out["ok"] is True and out["noData"] is True
    assert out["stocks"] == [] and out["phase"] is None
    assert "无涨停打标" in out["reason"]
