# -*- coding: utf-8 -*-
"""合并同 call（四题+个股相位一次调用）测试——全 monkeypatch，禁触真实 jev 调用（AGENTS.md §1.2-7）。

背景（2026-10-04 用户裁决「真合并后再跑」）：原 --with-stock-phase 是「四题跑完附带单题」假合并
（相位仍独立调用付全叙事 ≈2,420 tokens/只）；真合并=相位题并入主 call 题目集，同一 narrative
输入喂五题，增量边际成本≈题干+答案（数百 tokens/只）。判据原文逐字不变（题目语义零变更，
仅打包方式变化），存量老文档补齐仍走单题 CLI（run_stock_phase_pilot 保留）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.operations.jev_label_jiuyan import (
    QUESTIONS_STOCK,
    QUESTIONS_STOCK_PHASE,
    QUESTIONS_STOCK_WITH_PHASE,
    _label_one,
    run,
)


class _FakeCol:
    def __init__(self, docs: dict | None = None):
        self.docs = docs or {}
        self.replaced: list[tuple[dict, dict]] = []

    def find(self, _query, _projection=None):
        # 忽略查询过滤（fake 不实现查询语义）；过滤条件由消费方在 docs 构造时保证
        return list(self.docs.values())

    def find_one(self, query, _projection=None, sort=None):
        # 批次B I8：runner 帧查询带 sort 取最新帧；fake 无时间语义直接命中 _id/首条
        return self.docs.get(query.get("_id"))

    def replace_one(self, query, doc, upsert=False):
        self.replaced.append((query, doc))


class _FakeDb:
    """按集合名分流：jiuyan_action 返回含 tradingDate 的日历文档（run 的日期轴），其余回主集合。"""

    def __init__(self, col: _FakeCol):
        self._col = col

    def __getitem__(self, name):
        if name == "jiuyan_action":
            return _FakeCol({"d1": {"_id": "d1", "tradingDate": "2026-10-09"}})
        return self._col


def _parse_ok() -> dict:
    return {"ok": True,
            "answers": {"driver_type": {"choice": "policy", "probabilities": {"policy": 0.6}},
                        "catalyst_depth": {"choice": "core_business", "probabilities": {}},
                        "catalyst_freshness": {"choice": "early", "probabilities": {}},
                        "buy_side_logic": {"choice": "ladder", "probabilities": {}},
                        "stock_phase_position": {"choice": "start", "probabilities": {"start": 0.7}}},
            "model": "m", "usage": {"input_tokens": 1000, "output_tokens": 100},
            "errorCode": None, "errorDetail": None}


def test_merged_question_set_is_four_plus_phase_verbatim():
    """五题集=四题原样 + 相位题原文（判据逐字不变，仅打包；题干漂移=改门）。"""
    assert set(QUESTIONS_STOCK_WITH_PHASE.keys()) == set(QUESTIONS_STOCK.keys()) | {"stock_phase_position"}
    assert QUESTIONS_STOCK_WITH_PHASE["stock_phase_position"] == QUESTIONS_STOCK_PHASE["stock_phase_position"]
    for k, q in QUESTIONS_STOCK.items():
        assert QUESTIONS_STOCK_WITH_PHASE[k] == q


def test_label_one_merged_writes_stock_phase_fields(monkeypatch):
    """合并模式：_dispatch_jev 收五题集；doc 四题字段照常 + stockPhase* 全部落档。"""
    monkeypatch.setattr(runner, "build_pilot_narrative", lambda *a, **k: "NARRATIVE")
    captured: dict = {}

    def fake_call(state, qs):
        captured["narrative"] = state
        captured["questions"] = qs
        return ("env", 88)

    monkeypatch.setattr(runner, "_dispatch_jev", fake_call)
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms, **_kw: _parse_ok())
    col = _FakeCol()
    _label_one(_FakeDb(col), col, "acc", "tok", "2026-10-09", "600825",
               {"name": "X"}, "板块", 3, include_stock_phase=True)
    assert captured["narrative"] == "NARRATIVE"
    assert captured["questions"] == QUESTIONS_STOCK_WITH_PHASE
    assert len(col.replaced) == 1
    doc = col.replaced[0][1]
    assert doc["label"] == "policy" and doc["catalystDepth"] == "core_business"
    assert doc["stockPhasePosition"] == "start"
    assert doc["stockPhaseProbabilities"] == {"start": 0.7}
    assert doc["stockPhaseQuestionsRaw"] == QUESTIONS_STOCK_PHASE  # 判据代际锚（聚合层消费不变）
    assert doc["stockPhaseLatencyMs"] == 88 and doc["stockPhaseModel"] == "m"
    assert doc["questionsRaw"] == QUESTIONS_STOCK_WITH_PHASE  # 实际下发题集


def test_label_one_default_keeps_four_questions(monkeypatch):
    """默认（旗标关）：四题同 call 行为逐位不变，doc 无 stockPhase 键。"""
    monkeypatch.setattr(runner, "build_pilot_narrative", lambda *a, **k: "N")
    captured: dict = {}

    def fake_call(state, qs):
        captured["questions"] = qs
        return ("env", 10)

    monkeypatch.setattr(runner, "_dispatch_jev", fake_call)
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms, **_kw: _parse_ok())
    col = _FakeCol()
    _label_one(_FakeDb(col), col, "acc", "tok", "2026-10-09", "600825", {"name": "X"}, "b", None)
    assert captured["questions"] == QUESTIONS_STOCK
    assert not any(k.startswith("stockPhase") for k in col.replaced[0][1])


def test_run_flag_reaches_label_call(monkeypatch):
    """run(with_stock_phase=True) 传穿到每次 _label_one 的题目集（端到端合同）。"""
    db = _FakeDb(_FakeCol())
    monkeypatch.setattr(runner, "_db", lambda: db)
    monkeypatch.setattr(runner, "day_population", lambda db_, date, slot="final": [
        {"stock": {"code": "600825", "name": "X"}, "board": "b"}])
    monkeypatch.setattr(runner, "_strip", lambda c: c)
    monkeypatch.setattr(runner, "hotlist_ranks", lambda db_, date, codes, *a, **k: {})
    captured: dict = {}

    def fake_call(state, qs):
        captured["questions"] = qs
        return ("env", 1)

    monkeypatch.setattr(runner, "_dispatch_jev", fake_call)
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms, **_kw: _parse_ok())
    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc", workers=1,
        with_stock_phase=True, confirm_budget=True)
    assert captured["questions"] == QUESTIONS_STOCK_WITH_PHASE


def test_run_default_no_phase_questions(monkeypatch):
    """默认 run（旗标关）：题目集=四题，行为与历史逐位一致。"""
    db = _FakeDb(_FakeCol())
    monkeypatch.setattr(runner, "_db", lambda: db)
    monkeypatch.setattr(runner, "day_population", lambda db_, date, slot="final": [
        {"stock": {"code": "600825", "name": "X"}, "board": "b"}])
    monkeypatch.setattr(runner, "_strip", lambda c: c)
    monkeypatch.setattr(runner, "hotlist_ranks", lambda db_, date, codes, *a, **k: {})
    captured: dict = {}

    def fake_call(state, qs):
        captured["questions"] = qs
        return ("env", 1)

    monkeypatch.setattr(runner, "_dispatch_jev", fake_call)
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms, **_kw: _parse_ok())
    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc", workers=1,
        confirm_budget=True)
    assert captured["questions"] == QUESTIONS_STOCK


def test_run_budget_guard_aborts_without_confirm(monkeypatch, capsys):
    """批次C I13：未确认预算拒绝开火（零真实调用，fail-visible）。"""
    import pytest

    db = _FakeDb(_FakeCol())
    monkeypatch.setattr(runner, "_db", lambda: db)
    monkeypatch.setattr(runner, "day_population", lambda db_, date, slot="final": [
        {"stock": {"code": "600825", "name": "X"}, "board": "b"}])
    monkeypatch.setattr(runner, "_strip", lambda c: c)
    fired: list = []
    monkeypatch.setattr(runner, "_dispatch_jev", lambda *a, **k: fired.append(1) or ("env", 1))

    with pytest.raises(SystemExit, match="预算护栏") as excinfo:
        run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc", workers=1)
    assert fired == []  # 拒绝开火 = 零调用
    assert "预算护栏" in str(excinfo.value)  # SystemExit 消息在异常对象，不进 stdout
