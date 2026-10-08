# -*- coding: utf-8 -*-
"""校准漂移监控测试（D 项）：纯函数 + 假库 run + 排程步门控（零 jev/零真库写）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist.emotion_score import _CALIB
from backend.operations import emotion_score_calib_monitor as cm
from backend.operations import schedule


class _FakeCollection:
    def __init__(self) -> None:
        self.docs: dict = {}
        self.find_results: list = []

    def find(self, query, projection=None):
        return self.find_results

    def find_one(self, query, projection=None):
        return self.docs.get(query.get("_id"))

    def count_documents(self, query):
        return len(self.find_results)

    def replace_one(self, query, doc, upsert=False):
        self.docs[query["_id"]] = doc


class _FakeDb:
    def __init__(self) -> None:
        self._colls: dict = {}

    def __getitem__(self, name):
        return self._colls.setdefault(name, _FakeCollection())


def _slot_doc(raws: dict, date="2026-10-08", slot="10:00") -> dict:
    return {"tradingDate": date, "slotTime": slot,
            "emotionScore": {"dims": {k: {"raw": v, "sub": None} for k, v in raws.items()}}}


# ---------------------------------------------------------------- 纯函数

def test_percentile_linear_interpolation():
    assert cm.percentile([10.0], 50) == 10.0
    assert cm.percentile([0.0, 10.0], 50) == 5.0
    assert cm.percentile([0.0, 10.0], 10) == 1.0
    assert cm.percentile([0.0, 10.0], 90) == 9.0
    assert cm.percentile([0.0, 1.0, 2.0, 3.0, 4.0], 50) == 2.0


def test_drifts_zero_when_window_matches_anchor():
    # 主维（upRatio）：各分位 raw 恰落在锚上 → 漂移≈0
    anchors = [(0.4334, "P10"), (0.5062, "P25"), (0.5921, "P50"), (0.6988, "P75"), (0.8437, "P95")]
    raws = []
    for _ in range(10):
        for v, _p in anchors:
            raws.append(v)
    drifts = cm.drifts_of(raws, _CALIB["upRatio"])
    assert drifts is not None
    assert all(abs(v) <= 1.0 for v in drifts.values())


def test_drifts_reversed_dim_mirrored_expectation():
    # 反向维（riskShare）锚定网格（权威源=.tmp/emotion-score-calibration.json 对照确认）：
    # P10→90（0.8253=P10 实测）/P25→75/P50→50（0.9254）/P75→25/P90→10（0.9777=P90 实测，非 P95）
    curve = _CALIB["riskShare"]
    assert cm._expected_sub(curve, 10.0) == 90.0
    assert cm._expected_sub(curve, 50.0) == 50.0
    assert cm._expected_sub(curve, 90.0) == 10.0
    assert cm._expected_sub(curve, 95.0) == 95.0  # 未锚定分位退化镜像外推（不应到达）
    # 窗口分位恰落锚（五锚：P10/P25/P50/P75/P90 → 0.8253/0.8628/0.9254/0.9581/0.9777）→ 漂移≈0
    raws = []
    for _ in range(14):
        for v in (0.8253, 0.8628, 0.9254, 0.9581, 0.9777):
            raws.append(v)
    drifts = cm.drifts_of(raws, curve)
    assert drifts is not None
    assert set(drifts) == {"P10", "P25", "P50", "P75", "P90"}  # 反向维用 P90 锚，无 P95
    assert all(abs(v) <= 1.5 for v in drifts.values())


def test_drifts_alert_when_window_shifted():
    # 窗口整体上移：raws 0.65~0.689 → P50≈0.67 → sub≈68 → drift≈+18（锚 P50=0.5921→50）
    raws = [0.65 + i * 0.001 for i in range(40)]
    drifts = cm.drifts_of(raws, _CALIB["upRatio"])
    assert drifts is not None
    assert drifts["P50"] > 10  # 分布整体上移 → 各分位 raw 均落在锚之上 → 正向大漂移


def test_drifts_insufficient_sample_returns_none():
    assert cm.drifts_of([0.5] * 29, _CALIB["upRatio"]) is None  # 29<30
    assert cm.drifts_of([0.5] * 30, _CALIB["upRatio"]) is not None


def test_build_report_alert_and_skip_and_exclusion():
    docs = []
    for i in range(40):
        raws = {"upRatio": 0.45, "attackShare": 0.08, "riskShare": 0.88, "trin": 1.7,
                "yhPositive": 0.55, "riskRowsPct": 85.0}
        docs.append(_slot_doc(raws, slot=f"1{i % 10}:00"))
    # trin 只给 5 份有效 → skip；攻击维 raw 压到校准下界外 → sub=30 恒定 drift 大
    for i, d in enumerate(docs):
        if i >= 5:
            d["emotionScore"]["dims"]["trin"]["raw"] = None
    report = cm.build_calib_drift_report(docs, trading_dates=["2026-10-01", "2026-10-08"],
                                         amount_recorded_days=25)
    assert report["month"] == "2026-10"
    assert "trin" in report["skipped"] and "insufficient_sample" in report["skipped"]["trin"]
    assert "upRatio" in report["dims"]
    # 排除维登记（非静默）
    assert report["excluded"]["limitStruct"] == "composite_dim_raw_null"
    assert report["excluded"]["amountVsSame"] == "frozen_gate_a1"
    # 就绪通知
    assert report["amountVsSame"]["recordedDays"] == 25 and report["amountVsSame"]["ready"] is True
    # 单值窗口（全同 raw）分位=该值：attackShare 0.08 恰在锚上（0.0826→50）drift≈0
    assert abs(report["dims"]["attackShare"]["drifts"]["P50"]) <= 5


# ---------------------------------------------------------------- run（假库）

def test_run_monitor_persists_with_apply(monkeypatch):
    fake = _FakeDb()
    coll = _FakeCollection()
    coll.find_results = [_slot_doc({"upRatio": 0.59, "attackShare": 0.08, "riskShare": 0.88,
                                    "trin": 1.3, "yhPositive": 0.64, "riskRowsPct": 90.0},
                                   date=f"2026-09-{i:02d}", slot="10:00") for i in range(1, 25)]
    fake._colls["hotlist_sentiment"] = coll
    amount_coll = _FakeCollection()
    amount_coll.find_results = [object() for _ in range(30)]  # count_documents 走 find_results
    fake._colls["market_daily_amount"] = amount_coll
    monkeypatch.setattr(cm, "_get_db", lambda: fake)
    captured: dict = {}

    def _persist(report):
        captured["report"] = report
        return f"calib_drift:{report['month']}"

    import backend.operations.phase_monitor_persistence as persist_mod
    monkeypatch.setattr(persist_mod, "persist_calib_drift", _persist)
    # run 内部是函数体 import persist_calib_drift → patch 模块属性生效
    result = cm.run_calib_drift_monitor("2026-10-08", apply=True)
    assert result["ok"] is True
    assert result["report"]["window"]["slots"] == 24
    assert captured["report"]["amountVsSame"]["recordedDays"] == 30


def test_run_monitor_no_docs_structured_failure(monkeypatch):
    fake = _FakeDb()
    monkeypatch.setattr(cm, "_get_db", lambda: fake)
    result = cm.run_calib_drift_monitor("2026-10-08", apply=True)
    assert result["ok"] is False and result["errorCode"] == "no_window_docs"


def test_persist_calib_drift_monthly_upsert(monkeypatch):
    from backend.data.repositories import repository_factory
    fake = _FakeDb()
    monkeypatch.setattr(repository_factory, "get_runtime_mongodb_database", lambda: fake)
    doc_id = persist_id = None
    from backend.operations.phase_monitor_persistence import persist_calib_drift
    doc_id = persist_calib_drift({"month": "2026-10", "alerts": []})
    assert doc_id == "calib_drift:2026-10"
    stored = fake["phase_monitor"].docs["calib_drift:2026-10"]
    assert stored["kind"] == "calib_drift"
    persist_calib_drift({"month": "2026-10", "alerts": [{"dim": "trin", "percentile": "P50", "drift": -11.0}]})
    assert fake["phase_monitor"].docs["calib_drift:2026-10"]["report"]["alerts"][0]["dim"] == "trin"


# ---------------------------------------------------------------- 排程步

def test_schedule_calib_step_dry_run_and_gate(monkeypatch):
    assert schedule._run_calib_drift_step("2026-10-08", dry_run=True)["skipped"] is True
    monkeypatch.setattr(schedule, "_should_run_phase_pulse", lambda db, t, d, s: (False, "no EOD"))
    result = schedule._run_calib_drift_step("2026-10-08", dry_run=False)
    assert result == {"ok": True, "skipped": True, "reason": "no EOD"}


def test_schedule_calib_step_success_path(monkeypatch):
    fake = _FakeDb()
    fake["phase_monitor"].docs["calib_drift:2026-10"] = {
        "_id": "calib_drift:2026-10", "updatedAt": "2099-01-01T00:00:00",
        "report": {"alerts": [{"dim": "trin", "percentile": "P50", "drift": -11.0}]}}

    class _Proc:
        returncode = 0
        stdout = "{}"
        stderr = ""

    monkeypatch.setattr(schedule, "_should_run_phase_pulse", lambda db, t, d, s: (True, ""))
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(schedule.repository_factory, "get_runtime_mongodb_database", lambda: fake)
    result = schedule._run_calib_drift_step("2026-10-08", dry_run=False)
    assert result["ok"] is True and result["mongoFresh"] is True
    assert result["alertCount"] == 1


def test_schedule_calib_step_failure_structured(monkeypatch):
    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(schedule, "_should_run_phase_pulse", lambda db, t, d, s: (True, ""))
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: _Proc())
    result = schedule._run_calib_drift_step("2026-10-08", dry_run=False)
    assert result["ok"] is False and result["error"]["code"] == "calib_drift_failed"
