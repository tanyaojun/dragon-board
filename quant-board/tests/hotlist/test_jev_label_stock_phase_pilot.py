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
    # 设计稿 v0.1 冻结合同（jev-driver-label-v3-questionset.md）：key 与五档选项逐字对齐；
    # v0.1（2026-10-04 用户令）：价格位置轴主锚——首板贴近 20 日高点属高位（龙版传媒教训）
    assert list(QUESTIONS_STOCK_PHASE.keys()) == ["stock_phase_position"]
    q = QUESTIONS_STOCK_PHASE["stock_phase_position"]
    assert q["type"] == "choice"
    assert list(q["criteria"].keys()) == ["start", "ferment", "climax", "divergence", "insufficient"]
    assert "不预测后市" in q["instructions"]
    assert "距 20 日最高价" in q["instructions"] and "不看单日连板数" in q["instructions"]
    assert "≤10%" in q["criteria"]["climax"] and "≥50%" in q["criteria"]["climax"]
    assert ">20%" in q["criteria"]["start"] and "<30%" in q["criteria"]["start"]
    assert "优先于价格位置" in q["criteria"]["divergence"]


def test_position_line_counts_from_daily_bars(monkeypatch):
    # 21 根日线：20 日前收盘 10 → 现价 16.28；20 日最高 17.66；昨量 1000 今量 950
    bars = [{"date": f"2026-09-{d:02d}", "high": 10.0 + i * 0.1, "close": 10.0 + i * 0.3,
             "vol": 1000.0} for i, d in enumerate(range(1, 19))]
    bars += [{"date": "2026-09-29", "high": 17.0, "close": 15.0, "vol": 1000.0},
             {"date": "2026-09-30", "high": 17.66, "close": 16.28, "vol": 950.0}]
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars)
    line = runner.stock_position_line("2026-09-30", "605577")
    assert "距 20 日最高 17.66 差 7.8%" in line
    assert "20 日窗口涨幅" in line and "最低收盘" in line
    assert "0.95 倍（平量）" in line
    # 阈值语义自检：龙版传媒形态（距高点 7.8%/窗口涨幅 62.5%）应同时满足 climax 两锚


def test_position_line_fail_visible(monkeypatch):
    monkeypatch.setattr(runner, "_daily_bars", lambda code: [])
    assert "fail-visible" in runner.stock_position_line("2026-09-30", "605577")
    # 缺今日棒（停牌/数据缺口）
    bars = [{"date": "2026-09-29", "high": 17.0, "close": 15.0, "vol": 1000.0},
            {"date": "2026-09-28", "high": 16.0, "close": 14.0, "vol": 900.0}]
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars)
    assert "无当日日线棒" in runner.stock_position_line("2026-09-30", "605577")
    # 新股窗口不足
    bars1 = [{"date": "2026-09-30", "high": 12.0, "close": 11.5, "vol": 500.0}]
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars1)
    assert "不足 2 根" in runner.stock_position_line("2026-09-30", "605577")
    # 昨量 0（数据缺口不伪造倍数）
    bars2 = [{"date": "2026-09-29", "high": 17.0, "close": 15.0, "vol": 0.0},
             {"date": "2026-09-30", "high": 17.66, "close": 16.28, "vol": 950.0}]
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars2)
    assert "昨量缺失" in runner.stock_position_line("2026-09-30", "605577")


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
