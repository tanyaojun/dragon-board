# -*- coding: utf-8 -*-
"""个股相位分线试点（run_stock_phase_pilot）测试——全 monkeypatch，禁触真实 jev 调用（AGENTS.md §1.2-7）。

合同点：只 $set stockPhase* 不碰四题标签（upsert=False）/缺文档跳过披露/同判据幂等跳过/降级 fail-visible 落错误字段。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.operations.jev_label_jiuyan import QUESTIONS_STOCK_PHASE, run_stock_phase_pilot


def test_question_structure_frozen_design():
    # 设计稿冻结合同（jev-driver-label-v3-questionset.md 尾部）：key 与五档选项逐字对齐
    assert list(QUESTIONS_STOCK_PHASE.keys()) == ["stock_phase_position"]
    q = QUESTIONS_STOCK_PHASE["stock_phase_position"]
    assert q["type"] == "choice"
    assert list(q["criteria"].keys()) == ["start", "ferment", "climax", "divergence", "insufficient"]
    assert "不预测后市" in q["instructions"]
    assert "质量修正优先于高度归层" in q["criteria"]["divergence"]


class _FakeCol:
    def __init__(self, docs):
        self.docs = docs  # _id → doc
        self.updates = []

    def find_one(self, query, *_a, **_k):
        return self.docs.get(query.get("_id"))

    def update_one(self, query, update, upsert=False):
        assert upsert is False, "补跑路径禁止 upsert（不造新文档）"
        self.updates.append((query, update))
        matched = 1 if query.get("_id") in self.docs else 0
        return type("R", (), {"matched_count": matched})()


class _FakeDb(dict):
    def __init__(self, col):
        super().__init__()
        self["hotlist_jev_driver_labels"] = col


def _patch_population(monkeypatch, codes):
    monkeypatch.setattr(runner, "day_population", lambda db, date: [
        {"stock": {"code": f"sh{c}", "name": c}, "board": "公告"} for c in codes])
    monkeypatch.setattr(runner, "hotlist_ranks", lambda db, date, cs: {c: 3 for c in cs})
    monkeypatch.setattr(runner, "build_pilot_narrative",
                        lambda db, date, code, stock, board, rank: f"叙事:{code}")


def _parse_ok(choice):
    return {"ok": True, "answers": {"stock_phase_position": {
        "choice": choice, "probabilities": {choice: 0.7}}},
        "model": "m", "usage": {"input_tokens": 100, "output_tokens": 10},
        "errorCode": None, "errorDetail": None}


def test_ok_path_updates_fields_without_touching_labels(monkeypatch):
    col = _FakeCol({"2026-09-30:600825": {"_id": "2026-09-30:600825", "label": "ma_restructure",
                                          "catalystDepth": "equity_or_affiliate"}})
    _patch_population(monkeypatch, ["600825"])
    monkeypatch.setattr(runner, "call_jev", lambda acc, tok, narrative, qs:
                        ("env", 123))
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms: _parse_ok("ferment"))
    run_stock_phase_pilot(_FakeDb(col), ["2026-09-30"], "tok", "acc")
    assert len(col.updates) == 1
    query, update = col.updates[0]
    assert query == {"_id": "2026-09-30:600825", "status": "ok"}
    payload = update["$set"]
    assert payload["stockPhasePosition"] == "ferment"
    assert payload["stockPhaseProbabilities"] == {"ferment": 0.7}
    assert payload["stockPhaseQuestionsRaw"] == QUESTIONS_STOCK_PHASE
    assert payload["stockPhaseErrorCode"] is None and payload["stockPhaseLatencyMs"] == 123
    # 四题标签字段不在 $set 里（不碰已定版标签）
    assert "label" not in payload and "catalystDepth" not in payload


def test_degraded_fail_visible(monkeypatch):
    col = _FakeCol({"2026-09-30:600825": {"_id": "2026-09-30:600825"}})
    _patch_population(monkeypatch, ["600825"])
    monkeypatch.setattr(runner, "call_jev", lambda acc, tok, narrative, qs: ("env", 5))
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms: {
        "ok": False, "answers": {}, "model": None, "usage": None,
        "errorCode": "E1", "errorDetail": "boom"})
    run_stock_phase_pilot(_FakeDb(col), ["2026-09-30"], "tok", "acc")
    payload = col.updates[0][1]["$set"]
    assert payload["stockPhasePosition"] is None  # 失败不伪造档位
    assert payload["stockPhaseErrorCode"] == "E1" and payload["stockPhaseErrorDetail"] == "boom"


def test_missing_doc_skipped_no_upsert(monkeypatch):
    col = _FakeCol({})  # 生产集合无该股文档
    _patch_population(monkeypatch, ["600825"])
    monkeypatch.setattr(runner, "call_jev", lambda acc, tok, narrative, qs: ("env", 5))
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms: _parse_ok("start"))
    run_stock_phase_pilot(_FakeDb(col), ["2026-09-30"], "tok", "acc")
    assert col.updates and col.updates[0][0]["_id"] == "2026-09-30:600825"
    # 无 upsert：缺文档不补造（跳过披露由 FINAL 计数体现）


def test_idempotent_skip_same_criteria(monkeypatch):
    col = _FakeCol({"2026-09-30:600825": {
        "_id": "2026-09-30:600825", "stockPhasePosition": "climax",
        "stockPhaseQuestionsRaw": QUESTIONS_STOCK_PHASE}})
    _patch_population(monkeypatch, ["600825"])
    called = []

    def _no_call(acc, tok, narrative, qs):
        called.append(1)
        return ("env", 0)

    monkeypatch.setattr(runner, "call_jev", _no_call)
    run_stock_phase_pilot(_FakeDb(col), ["2026-09-30"], "tok", "acc")
    assert not called  # 同判据已判，幂等跳过零调用
    assert not col.updates


def test_criteria_change_triggers_rerun(monkeypatch):
    col = _FakeCol({"2026-09-30:600825": {
        "_id": "2026-09-30:600825", "stockPhasePosition": "climax",
        "stockPhaseQuestionsRaw": {"stock_phase_position": {"criteria": {"旧判据": "x"}}}}})
    _patch_population(monkeypatch, ["600825"])
    monkeypatch.setattr(runner, "call_jev", lambda acc, tok, narrative, qs: ("env", 7))
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms: _parse_ok("divergence"))
    run_stock_phase_pilot(_FakeDb(col), ["2026-09-30"], "tok", "acc")
    assert col.updates  # 判据变更（改门）后允许重跑
    assert col.updates[0][1]["$set"]["stockPhasePosition"] == "divergence"


def test_dry_run_zero_call(monkeypatch, capsys):
    _patch_population(monkeypatch, ["600825", "000504"])
    monkeypatch.setattr(runner, "call_jev", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("dry-run 禁止真实调用")))
    run_stock_phase_pilot(_FakeDb(_FakeCol({})), ["2026-09-30"], "tok", "acc", dry_run=True)
    out = capsys.readouterr().out
    assert "[dry][stock-phase] 2026-09-30 population=2" in out
