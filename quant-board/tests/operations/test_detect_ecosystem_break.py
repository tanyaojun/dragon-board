# -*- coding: utf-8 -*-
"""断层检测三特征测试：冰点命中/杀跌排除/常态日排除。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.detect_ecosystem_break import detect_month


class FakeCol:
    """最小桩：zt/量能序列 + 涨跌家数按 (date) 映射。"""

    def __init__(self, zt, amount, adv):
        self.zt, self.amount, self.adv = zt, amount, adv

    def find_one(self, query, projection=None):
        d = query.get("tradingDate")
        proj = str(sorted((projection or {}).keys()))
        if "limitSummary" in proj:
            zt = self.zt.get(d)
            return {"limitSummary": {"zhaban": {"ztCount": zt}}} if zt else None
        if "evidenceRaw" in proj:
            a = self.amount.get(d)
            return {"evidenceRaw": {"totalAmount": {"amount": a * 1e8}}} if a else None
        if "indices" in proj:
            a = self.amount.get(d)
            return {"indices": {"totalAmount": {"amount": a * 1e8}}} if a else None
        return None

    def find(self, query, projection=None):
        rng = query.get("tradingDate")
        if isinstance(rng, dict) and "$gte" in rng:
            days = sorted(set(self.zt) | set(self.amount))
            return [{"tradingDate": x} for x in days if rng["$gte"] <= x <= rng["$lte"]]
        d = rng if isinstance(rng, str) else ""
        return self.adv.get(d, []) if query.get("pctChange") else []


class FakeDb:
    def __init__(self):
        days = ["2026-09-%02d" % x for x in (1, 2, 3, 4, 5)]
        self.zt = dict(zip(days, [80, 54, 45, 38, 92]))
        self.amount = dict(zip(days, [20334.0, 17911.8, 17589.2, 20306.7, 19460.2]))
        self.adv = {
            "2026-09-02": [{"pctChange": 1.0}] * 77 + [{"pctChange": -1.0}] * 100,
            "2026-09-04": [{"pctChange": 1.0}] * 110 + [{"pctChange": -1.0}] * 118,
        }
        self._cols = {"snapshot_stock_rows": FakeCol.__new__(FakeCol),
                      "snapshot_frames": FakeCol.__new__(FakeCol),
                      "hotlist_jev_sentiment": FakeCol.__new__(FakeCol)}

    def __getitem__(self, name):
        c = self._cols[name]
        c.zt, c.amount, c.adv = self.zt, self.amount, self.adv
        return c


def test_break_day_hit_and_selloff_excluded():
    rows = {r["date"]: r for r in detect_month(FakeDb(), "2026-09")}
    # 9/4：断层+均衡(0.93)+放量 → 命中
    r4 = rows["2026-09-04"]
    assert r4["ecosystemBreak"] is True and r4["breakout"] and r4["balanced"] and r4["amountUp"]
    # 9/2：断层但单边偏弱(0.77)+缩量 → 排除（杀跌日）
    r2 = rows["2026-09-02"]
    assert r2["ecosystemBreak"] is False and r2["breakout"] is True
    assert "非均衡" in r2["reason"] and "量能缩" in r2["reason"]
    # 9/5：未断层（92 高位）→ 排除
    assert rows["2026-09-05"]["ecosystemBreak"] is False
