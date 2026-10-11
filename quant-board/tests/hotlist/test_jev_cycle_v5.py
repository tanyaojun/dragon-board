# -*- coding: utf-8 -*-
"""cycle_stage v5 测试（预登记 jev-cycle-v5-preregistration.md）：三行接线/判据冻结/独立戳。

全 fake 零 IO，禁触真实 jev 调用与网络（AGENTS.md §1.2-7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.analysis.hotlist.jev_driver_ammo import (
    QUESTION_SET_VERSION_CYCLE,
    QUESTIONS_CYCLE,
)


# ── 判据冻结件（§三）──

def test_v5_criteria_frozen_text():
    crit = QUESTIONS_CYCLE["cycle_stage"]["criteria"]
    assert set(crit) == {"ebb_early", "ice_end", "repair", "ferment",
                         "climax", "divergence", "insufficient"}
    # 冰点判据绑定三行读数 + 分位锚 + 亚型语义（校准回算两打脸的落地）
    assert "近 20 日分位 ≤20" in crit["ice_end"]
    assert "亚型" in crit["ice_end"] and "不单独定冰点" in crit["ice_end"]
    assert "大面未再放大" in crit["ice_end"]
    # insufficient 覆盖三行缺口（fail-visible 纪律）
    assert "fail-visible" in crit["insufficient"]
    # 版本戳独立（§四修旧债）
    assert QUESTION_SET_VERSION_CYCLE == "v5"
    assert QUESTION_SET_VERSION_CYCLE != runner.QUESTION_SET_VERSION_DRIVER


# ── 三行接线 ──

class _Col:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query, projection=None):
        def match(r):
            for k, v in query.items():
                if isinstance(v, dict):
                    if "$lte" in v and not (r.get(k) and r[k] <= v["$lte"]):
                        return False
                    continue
                if r.get(k) != v:
                    return False
            return True
        return iter([r for r in self.rows if match(r)])

    def find_one(self, query, projection=None, sort=None):
        best = None
        for r in self.find(query):
            if sort and best is not None:
                # 简化：sort=[(timestamp,-1)] 取 timestamp 最大
                if r.get("timestamp", 0) >= best.get("timestamp", 0):
                    best = r
            else:
                best = r if best is None or r.get("_id", "") >= best.get("_id", "") else best
        return best


class _Db:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, name):
        return self.cols.get(name, _Col([]))


def _amount_rows(*items):
    return [{"_id": d, "totalAmount": v} for d, v in items]


def test_energy_line_shanghai_and_percentile():
    rows = _amount_rows(("2026-09-01", 1.0e12), ("2026-09-02", 1.1e12), ("2026-09-03", 1.2e12))
    out = runner._cycle_energy_line(_Db({"market_daily_amount": _Col(rows)}), "2026-09-03")
    assert "两市成交额 12000 亿" in out and "+9.1%" in out and "放量" in out
    assert "量能分位" in out  # percentile_rank 有 ≥10 样本才出数字，此处 2 样本=不可算文本


def test_energy_line_flat_and_bool_guard():
    rows = _amount_rows(("2026-09-01", 1.0e12), ("2026-09-02", True), ("2026-09-03", 1.0e12))
    out = runner._cycle_energy_line(_Db({"market_daily_amount": _Col(rows)}), "2026-09-03")
    # bool 混入不作有效前值（防御对称，review B-P3）；与 09-01 持平→「持平」（review B-P3 三分支）
    assert "+0.0%" in out and "持平" in out


def test_energy_line_missing_fail_visible():
    rows = _amount_rows(("2026-09-01", 1.0e12))
    out = runner._cycle_energy_line(_Db({"market_daily_amount": _Col(rows)}), "2026-09-03")
    assert "数据缺口（fail-visible）" in out  # 当日缺失


def test_breadth_line_hit_and_gap():
    frame_ok = {"_id": "f", "datasetId": "dragonboard_live", "type": "half_hour",
                "tradingDate": "2026-10-09", "slotTime": "15:00", "timestamp": 2,
                "marketStats": {"upCount": 1491, "downCount": 3948, "dtCount": 16}}
    db = _Db({"snapshot_frames": _Col([frame_ok])})
    out = runner._cycle_breadth_line(db, "2026-10-09", "dragonboard_live")
    assert "上涨 1491 家／下跌 3948 家" in out and "跌停 16 家" in out
    db2 = _Db({"snapshot_frames": _Col([{"_id": "f", "tradingDate": "2026-10-09",
                                         "slotTime": "15:00", "timestamp": 2}])})
    assert "marketStats 缺口（fail-visible）" in runner._cycle_breadth_line(db2, "2026-10-09", "x")
    # 0 值与缺字段区分注记（7-9 月碎裂帧存 0 非缺字段，review A-P3）
    db3 = _Db({"snapshot_frames": _Col([{"_id": "f", "datasetId": "x", "type": "half_hour",
                                         "tradingDate": "2026-10-09",
                                         "slotTime": "15:00", "timestamp": 2,
                                         "marketStats": {"upCount": 0, "downCount": 0}}])})
    assert "读数为 0（历史碎裂，fail-visible）" in runner._cycle_breadth_line(db3, "2026-10-09", "x")


def test_drawdown_line_hit_and_gap():
    frame_ok = {"_id": "f", "datasetId": "dragonboard_live", "type": "half_hour",
                "tradingDate": "2026-09-17", "slotTime": "15:00", "timestamp": 2,
                "limitSummary": {"drawdown": {"count": 8, "avgDrawdownPct": 12.62,
                                              "deepestDrawdownPct": 18.15}}}
    db = _Db({"snapshot_frames": _Col([frame_ok])})
    out = runner._cycle_drawdown_line(db, "2026-09-17", "dragonboard_live")
    assert "回撤池 8 家" in out and "平均回撤 12.6%" in out and "最深 18.1%" in out  # 18.15 浮点实际 18.149…→:.1f=18.1
    assert "drawdown 缺口（fail-visible）" in runner._cycle_drawdown_line(
        _Db({}), "2026-09-17", "x")


def test_build_cycle_narrative_contains_three_lines(monkeypatch):
    rows = _amount_rows(("2026-09-01", 1.0e12), ("2026-09-02", 1.2e12))
    db = _Db({
        "market_daily_amount": _Col(rows),
        "snapshot_frames": _Col([{"_id": "f", "datasetId": "dragonboard_live", "type": "half_hour",
                                  "tradingDate": "2026-09-02", "slotTime": "15:00",
                                  "timestamp": 2,
                                  "marketStats": {"upCount": 1200, "downCount": 3600},
                                  "limitSummary": {"drawdown": {"count": 5,
                                                                "avgDrawdownPct": 9.0,
                                                                "deepestDrawdownPct": 14.0}}}]),
    })
    monkeypatch.setattr(runner, "market_facts_line", lambda db_, d, ds: "盘面事实（桩）")
    monkeypatch.setattr(runner, "swing_summary_line", lambda db_, d, dataset_id: "摆动锚（桩）")
    monkeypatch.setattr(runner, "trajectory_line", lambda db_, d, dataset_id: "轨迹（桩）")
    n = runner.build_cycle_narrative(db, "2026-09-02")
    for head in ("量能方向：", "全市场涨跌：", "大面规模："):
        assert head in n


def test_cycle_run_stamps_v5(monkeypatch):
    """独立版本戳：cycle 新文档盖 QUESTION_SET_VERSION_CYCLE=v5（§四修旧债）。"""
    captured = {}

    class _CycleCol:
        def find_one(self, query, projection=None):
            return None

        def replace_one(self, query, doc, upsert=False):
            captured["doc"] = doc

    db = _Db({"hotlist_jev_cycle_stage_pilot": _CycleCol(),
              "market_daily_amount": _Col(_amount_rows(("2026-09-01", 1.0e12),
                                                       ("2026-09-02", 1.1e12))),
              "snapshot_frames": _Col([]),
              "jiuyan_action": _Col([])})
    monkeypatch.setattr(runner, "market_facts_line", lambda db_, d, ds: "盘面事实（桩）")
    monkeypatch.setattr(runner, "swing_summary_line", lambda db_, d, dataset_id: "摆动锚（桩）")
    monkeypatch.setattr(runner, "trajectory_line", lambda db_, d, dataset_id: "轨迹（桩）")
    monkeypatch.setattr(runner, "_dispatch_jev", lambda narrative, questions: (
        {"result": {"state": "Completed",
                    "result": {"model": "m", "answers": {"cycle_stage": {
                        "type": "choice", "choice": "ice_end", "confidence": 0.6}},
                               "usage": {"input_tokens": 10, "output_tokens": 2}}}}, 100))
    runner.run_cycle_stage_day(db, ["2026-09-02"], "tok", "acc")
    doc = captured["doc"]
    assert doc["questionSetVersion"] == "v5"
    assert doc["cycleStage"] == "ice_end"
    assert "量能方向：" in doc["narrative"]
