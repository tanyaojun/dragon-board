# -*- coding: utf-8 -*-
"""C10 高峰兑现月度复验（peak_revalidate）纯函数测试——全 mock，禁触真实 jev 调用（AGENTS.md §1.2-7）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.peak_revalidate import PEAK, compute_peak_summary, revalidate_month


def test_peak_threshold_frozen():
    """主锚=用户裁决 ≥75（ranktrend-c10-peak-exit-plan.md §2.1）。"""
    assert PEAK == 75.0


def test_compute_peak_summary_gap_groups():
    """缺口三分组聚合（V3 强单调口径）+ 基线与 edge；insufficient（缺缺口/缺收益）不入组只计数。"""
    samples = [
        {"date": "2026-05-07", "eodScore": 77.0, "n": 10, "gapLt1": [1.0, 2.0], "gap1to3": [0.5], "gapGe3": [-2.0, -4.0]},
        {"date": "2026-09-16", "eodScore": 80.3, "n": 5, "gapLt1": [3.0], "gap1to3": [], "gapGe3": [-1.0]},
    ]
    out = compute_peak_summary("2026-09", samples, baseline_mean=-0.26)
    assert out["month"] == "2026-09" and out["peakDays"] == 2 and out["samples"] == 15
    assert out["gapLt1"]["n"] == 3 and round(out["gapLt1"]["mean"], 2) == 2.0 and out["gapLt1"]["win"] == 3
    assert out["gapGe3"]["n"] == 3 and round(out["gapGe3"]["mean"], 2) == -2.33 and out["gapGe3"]["win"] == 0
    # 兑现 edge = 基线 - 大高开组均值（兑现换入基线资产避免的回撤，pp）
    assert out["edgeGe3VsBaseline"] == round(-0.26 - (-2.33), 2)


def test_compute_peak_summary_empty_fail_visible():
    """无高峰日 → noData+reason（fail-visible 不伪造）。"""
    out = compute_peak_summary("2026-07", [], baseline_mean=None)
    assert out["peakDays"] == 0 and out["noData"] is True and "无高峰状态日" in out["reason"]
    assert out["gapGe3"]["n"] == 0 and out["gapGe3"]["mean"] is None


class _FakeCol:
    """最小桩：按 (collection, 查询键) 返回预置行；find 忽略过滤器语义由测试构造保证。"""

    def __init__(self, eod_docs, frames_rows, stock_rows, jiuyan_docs):
        self._eod, self._frames, self._rows, self._jiuyan = eod_docs, frames_rows, stock_rows, jiuyan_docs

    def find(self, query, projection=None):
        name = query.get("slotTime")
        if "emotionScore" in str(projection):
            return [{"tradingDate": d, "emotionScore": {"score": s}} for d, s in self._eod.items()]
        if name == "EOD" or (isinstance(query.get("slotTime"), str) and query.get("slotTime") == "EOD"):
            return []
        if isinstance(query.get("tradingDate"), dict) and "tradingDate" in str(projection):
            d0 = query["tradingDate"]
            return [{"_id": f"{d0}:final", "tradingDate": d0}] if self._jiuyan.get(d0) else []
        if "_id" in (projection or {}):
            return []
        rows = self._rows.get((query.get("tradingDate"), tuple(sorted(query["slotTime"]["$in"]))) if isinstance(query.get("slotTime"), dict) else None, [])
        return rows

    def find_one(self, query, projection=None):
        d = str(query.get("_id") or "")
        return self._jiuyan.get(d.replace(":final", "")) and {"fields": [{"stocks": [{"code": c} for c in self._jiuyan[d.replace(':final', '')]]}]}


class _FakeDb:
    def __init__(self, eod_docs, rows_by_slot_day, jiuyan_days):
        self._eod = eod_docs
        self._rows = rows_by_slot_day
        self._jiuyan = jiuyan_days

    def __getitem__(self, name):
        if name == "hotlist_sentiment":
            return _EodCol(self._eod)
        if name == "snapshot_stock_rows":
            return _RowsCol(self._rows)
        return _JiuyanCol(self._jiuyan)


class _EodCol:
    def __init__(self, eod):
        self._eod = eod

    def find(self, _q, _p=None):
        return [{"tradingDate": d, "emotionScore": {"score": s}} for d, s in self._eod.items()]


class _RowsCol:
    def __init__(self, rows):
        self._rows = rows  # {(date, slot): {code: pct}}

    def find(self, q, _p=None):
        d = q["tradingDate"]
        slot = q["slotTime"]["$in"][0] if isinstance(q["slotTime"], dict) else q["slotTime"]
        day = self._rows.get((d, slot), {})
        return [{"code": c, "pctChange": p} for c, p in day.items()]


class _JiuyanCol:
    def __init__(self, days):
        self._days = days  # {date: [codes]}

    def find_one(self, q, _p=None):
        d = str(q.get("_id") or "").replace(":final", "")
        codes = self._days.get(d)
        return {"fields": [{"stocks": [{"code": f"sh{c}"} for c in codes]}]} if codes else None


def test_revalidate_month_full_pipeline(monkeypatch):
    """端到端回归（锁两个自伤 bug）：月过滤只收当月高峰日；T+1/T+3 用全期轴下标；
    入场价 09:35 优先回退 09:30；gapMissing/人口缺失显式披露；基线=全期池等权。"""
    import backend.operations.peak_revalidate as pr

    monkeypatch.setattr(pr, "POOL_MIN", 1)  # 夹具池远小于生产 30，放行基线门
    revalidate_month = pr.revalidate_month

    eod = {"2026-09-15": 60.0, "2026-09-16": 80.3, "2026-09-17": 55.0, "2026-09-18": 50.0, "2026-09-21": 40.0, "2026-09-22": 30.0}
    rows = {}
    def put(d, slot, code, pct):
        rows.setdefault((d, slot), {})[code] = pct
    # T+1=09-17：600825 两槽都有（09:35 优先），000001 只有 09:30
    put("2026-09-17", "09:35", "600825", 3.5)
    put("2026-09-17", "09:30", "600825", 4.0)
    put("2026-09-17", "09:30", "000001", -0.5)
    put("2026-09-17", "10:30", "600825", 2.0)
    put("2026-09-18", "09:35", "600825", 1.0)  # 09-18 是 09-17 的 T+1（基线循环用）
    put("2026-09-21", "15:00", "600825", -1.0)  # T+3=09-21
    put("2026-09-21", "15:00", "000001", 0.5)
    db = _FakeDb(eod, rows, {"2026-09-16": ["600825", "000001", "999999"]})
    out = revalidate_month(db, "2026-09")
    s = out["summary"]
    assert s["peakDays"] == 1 and s["peakDays"] != 6  # 月过滤：全期仅 09-16 一个高峰日
    assert out["samples"][0]["date"] == "2026-09-16"
    assert out["samples"][0]["n"] == 2  # 999999 无行情不计数
    assert out["samples"][0]["gapMissing"] == 0
    g = out["samples"][0]
    # 600825 入场=09:35 的 3.5（非 09:30 的 4.0），T+3 15:00=-1.0 → ret=-4.5 → ≥3% 组
    assert g["gapGe3"] == [-4.5]
    # 000001 缺口 -0.5 → <1% 组，ret=0.5-(-0.5)=1.0
    assert g["gapLt1"] == [1.0]
    assert s["baselineMean"] is not None and s["truncatedPeakDays"] == []
    assert s["populationMissing"] == []


def test_revalidate_month_truncation_and_population_missing():
    """月末高峰日（T+3 出窗）进 truncatedPeakDays 不进样本；jiuyan final 缺失日 populationMissing。"""
    from backend.operations.peak_revalidate import revalidate_month

    eod = {"2026-09-16": 80.3, "2026-09-17": 55.0, "2026-09-18": 50.0, "2026-09-21": 40.0, "2026-09-22": 75.5}
    db = _FakeDb(eod, {}, {})  # 09-16 与 09-22 均无 jiuyan final → populationMissing
    out = revalidate_month(db, "2026-09")
    s = out["summary"]
    assert s["truncatedPeakDays"] == ["2026-09-22"]  # T+3 出窗
    assert s["populationMissing"] == ["2026-09-16"]  # final 缺失
    # 人口缺失日落 n=0 样本（账本在案）+ populationMissing 清单双披露，noData=False（与「无高峰日」可区分）
    assert len(out["samples"]) == 1 and out["samples"][0]["n"] == 0
    assert out["noData"] is False and s["samples"] == 0
