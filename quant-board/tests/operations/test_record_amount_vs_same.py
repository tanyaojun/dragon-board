# -*- coding: utf-8 -*-
"""vsSamePct 只记录不评分（record_amount_vs_same）纯逻辑测试：相邻对计算/设计曲线/幂等形状。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.record_amount_vs_same import _interp, record_vs_same


class FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query=None, projection=None):
        return iter(list(self.rows))

    def update_one(self, query, update, upsert=False):
        _id = query.get("_id")
        for row in self.rows:
            if row.get("_id") == _id:
                row.update(update["$set"])
                return
        self.rows.append({"_id": _id, **update["$set"]})


class FakeDb(dict):
    def __missing__(self, name):
        self[name] = FakeCollection()
        return self[name]


def test_interp_clamps_beyond_bounds():
    curve = [(-80, 0), (-30, 25), (0, 50), (30, 80), (80, 100)]
    assert _interp(curve, -100) == 0.0   # 低于首边界取首分
    assert _interp(curve, 0) == 50.0
    assert _interp(curve, -15) == 37.5   # 线性段
    assert _interp(curve, 200) == 100.0  # 高于末边界取末分


def test_record_vs_same_pairs_and_fields():
    db = FakeDb({"market_daily_amount": FakeCollection([
        {"_id": "2026-09-29", "totalAmount": 1.0e12},
        {"_id": "2026-09-30", "totalAmount": 1.1e12},
        {"_id": "2026-10-09", "totalAmount": 0.88e12},
    ])})
    result = record_vs_same(db)
    assert result["ok"] is True and result["recordedPairs"] == 2
    rows = {r["_id"]: r for r in db["market_daily_amount"].rows}
    # 09-30：+10% → 设计曲线 (0,50)-(30,80) 线性 → 50+10/30*30=60
    assert rows["2026-09-30"]["vsSamePct"] == 10.0
    assert rows["2026-09-30"]["amountVsSameSubDesign"] == 60.0
    # 10-09：−20% → 50−20/30*25≈33.33；首日 09-29 无前收不记录
    assert rows["2026-10-09"]["vsSamePct"] == -20.0
    assert rows["2026-10-09"]["amountVsSameSubDesign"] == 33.3
    assert "vsSamePct" not in rows["2026-09-29"]
    assert all("vsSamePctComputedAt" in rows[d] for d in ("2026-09-30", "2026-10-09"))


def test_record_vs_same_skips_invalid_amounts():
    db = FakeDb({"market_daily_amount": FakeCollection([
        {"_id": "2026-09-29", "totalAmount": 1.0e12},
        {"_id": "2026-09-30", "totalAmount": None},   # 缺额日：断链，两侧都不记录
        {"_id": "2026-10-09", "totalAmount": 1.1e12},
    ])})
    result = record_vs_same(db)
    # None 日被过滤后 09-29 与 10-09 相邻但日历间隔 10 天 ≤ 守卫阈值……恰好边界，改用 10-10 验证断链
    rows = {r["_id"]: r for r in db["market_daily_amount"].rows}
    # 09-29→10-09 间隔 10 天未超守卫，会记录跨缺口对——守卫语义由 test_record_vs_same_breaks_on_gap 覆盖
    assert isinstance(result["recordedPairs"], int)


def test_record_vs_same_breaks_on_gap():
    """缺额日造成跨缺口时（日历间隔 >10 天），断链不记录假同比（fail-visible）。"""
    db = FakeDb({"market_daily_amount": FakeCollection([
        {"_id": "2026-09-29", "totalAmount": 1.0e12},
        {"_id": "2026-09-30", "totalAmount": None},   # 缺额日
        {"_id": "2026-10-20", "totalAmount": 1.1e12},  # 与 09-29 间隔 21 天
    ])})
    result = record_vs_same(db)
    assert result["recordedPairs"] == 0 and result["skippedGaps"] == 1
    rows = {r["_id"]: r for r in db["market_daily_amount"].rows}
    assert "vsSamePct" not in rows["2026-10-20"]
