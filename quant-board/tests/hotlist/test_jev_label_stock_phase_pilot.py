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
    # 设计稿 v0.4 冻结合同（jev-driver-label-v3-questionset.md）：key 与五档选项逐字对齐；
    # v0.4（2026-10-04 用户盘感三判例校准）：示警收窄（单次回封不示警）+形态分界（低点新鲜度）+判例锚定
    assert list(QUESTIONS_STOCK_PHASE.keys()) == ["stock_phase_position"]
    q = QUESTIONS_STOCK_PHASE["stock_phase_position"]
    assert q["type"] == "choice"
    # 五档齐全；键序=优先级排列（示警分歧位在首）
    assert sorted(q["criteria"].keys()) == ["climax", "divergence", "ferment", "insufficient", "start"]
    assert list(q["criteria"].keys())[0] == "divergence"
    assert "不预测后市" in q["instructions"]
    # 三轴点名 + 优先级 + 四条注意（距高点退化/形态分界/回封不示警/量能语义分化）
    for axis in ["价格位置轴", "结构轴", "质量轴"]:
        assert axis in q["instructions"]
    assert "优先级" in q["instructions"] and "距高点≈0 不能单独当高位证据" in q["instructions"]
    assert "≤8 日=低位新鲜" in q["instructions"] and "≥15 日=趋势已久" in q["instructions"]
    assert "单次炸板回封" in q["instructions"] and "不是分歧示警" in q["instructions"]
    assert "④量能语义看封板质量" in q["instructions"] and "缩量板=一致锁定惜售" in q["instructions"]
    # 阈值/判例硬锚（v0.5：量能对比前 3 日均量+缩量反包判例）
    assert "炸板≥2 次回封" in q["criteria"]["divergence"] and "炸板收盘" in q["criteria"]["divergence"]
    assert "量比 ≥1.5 倍但封不住" in q["criteria"]["divergence"]
    assert "缩量加速或缩量反包" in q["criteria"]["climax"] and "判例②" in q["criteria"]["climax"]
    assert "低点距今 9-14 日" in q["criteria"]["ferment"]
    assert "≤8 个交易日" in q["criteria"]["start"] and "低位放量换手板" in q["criteria"]["start"]


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
    assert "距今" in line and "近 5 日贡献" in line  # v0.4 形态锚
    assert "前 3 日均量" in line and "0.95 倍（平量）" in line  # v0.5 量能锚
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
    # 前 3 日量能全缺（数据缺口不伪造倍数）
    bars2 = [{"date": "2026-09-29", "high": 17.0, "close": 15.0, "vol": 0.0},
             {"date": "2026-09-30", "high": 17.66, "close": 16.28, "vol": 950.0}]
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars2)
    assert "前 3 日量能缺失" in runner.stock_position_line("2026-09-30", "605577")


# ---- 弹药 7 板序（涨停序列）/弹药 8 板型（5 分钟机械判定）----

def _bars_with_closes(closes_by_date):
    # 由 close 序列反推 high=close（板序只依赖收盘口径；首日无涨停判定基准）
    return [{"date": d, "high": c, "close": c, "vol": 1000.0}
            for d, c in closes_by_date]


def test_limitup_sequence_streak_and_rewrap(monkeypatch):
    # 10 日序列：3 连板 → 断 2 日 → 今日涨停=断板反包（隔日弱转强）
    dates = ["2026-09-17", "2026-09-18", "2026-09-21", "2026-09-22", "2026-09-23",
             "2026-09-24", "2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30"]
    closes = [10.0, 11.0, 12.1, 13.31, 13.2, 13.0, 13.1, 13.2, 13.0, 14.3]
    bars = _bars_with_closes(list(zip(dates, closes)))
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars)
    line = runner.limitup_sequence_line("2026-09-30", "605577", None)
    assert "●" in line and "○" in line and "末位今日" in line
    assert "当前连板 1" in line
    assert "断板反包" in line  # 昨日 13.0 未板、今日 14.3=+10%、前 5 日内有板


def test_limitup_sequence_fail_visible(monkeypatch):
    monkeypatch.setattr(runner, "_daily_bars", lambda code: [])
    assert "fail-visible" in runner.limitup_sequence_line("2026-09-30", "605577", None)
    bars = [{"date": "2026-09-29", "high": 15.0, "close": 15.0, "vol": 1.0}]
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars)
    assert "当日日线棒缺失" in runner.limitup_sequence_line("2026-09-30", "605577", None)


def test_board_shape_rotten_reseal_and_one_word(monkeypatch):
    lp = 11.0  # 昨收 10 × 1.1
    # 烂板回封：封→炸（1）→回封→炸（2）→回封封至收盘
    intraday = [
        {"date": "2026-09-30", "hm": "09:35", "open": 10.5, "high": 11.0, "close": 11.0},
        {"date": "2026-09-30", "hm": "09:40", "open": 11.0, "high": 11.02, "close": 10.6},
        {"date": "2026-09-30", "hm": "09:45", "open": 10.6, "high": 11.0, "close": 11.0},
        {"date": "2026-09-30", "hm": "09:50", "open": 11.0, "high": 11.0, "close": 10.7},
        {"date": "2026-09-30", "hm": "09:55", "open": 10.7, "high": 11.0, "close": 11.0},
        {"date": "2026-09-30", "hm": "10:00", "open": 11.0, "high": 11.0, "close": 11.0},
        {"date": "2026-09-30", "hm": "10:05", "open": 11.0, "high": 11.0, "close": 11.0},
    ]
    monkeypatch.setattr(runner, "_intraday_bars", lambda code: intraday)
    line = runner.stock_board_shape_line("2026-09-30", "605577", None, 10.0)
    assert "炸板 2 次" in line and "烂板（炸板≥2 次回封）" in line and "封板至收盘" in line
    # 一字板：开盘即涨停且全天封死
    one_word = [{"date": "2026-09-30", "hm": "09:35", "open": 11.0, "high": 11.0, "close": 11.0},
                {"date": "2026-09-30", "hm": "09:40", "open": 11.0, "high": 11.0, "close": 11.0}]
    monkeypatch.setattr(runner, "_intraday_bars", lambda code: one_word)
    assert "一字板" in runner.stock_board_shape_line("2026-09-30", "605577", None, 10.0)
    # 炸板回封（当日弱转强）：一波炸板后回封
    reseal = [{"date": "2026-09-30", "hm": "09:35", "open": 10.6, "high": 11.0, "close": 11.0},
              {"date": "2026-09-30", "hm": "09:40", "open": 11.0, "high": 11.0, "close": 10.8},
              {"date": "2026-09-30", "hm": "09:45", "open": 10.8, "high": 11.0, "close": 11.0},
              {"date": "2026-09-30", "hm": "09:50", "open": 11.0, "high": 11.0, "close": 11.0}]
    monkeypatch.setattr(runner, "_intraday_bars", lambda code: reseal)
    assert "炸板回封（当日弱转强）" in runner.stock_board_shape_line("2026-09-30", "605577", None, 10.0)


def test_board_shape_fail_visible(monkeypatch):
    monkeypatch.setattr(runner, "_intraday_bars", lambda code: [])
    assert "fail-visible" in runner.stock_board_shape_line("2026-09-30", "605577", None, 10.0)
    assert "昨收缺失" in runner.stock_board_shape_line("2026-09-30", "605577", None, None)


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

    def __getitem__(self, name):
        # 批次C I10：runner 现会读一次整日韭研文档（jiuyan_doc 直传叙事），测试桩缺集合 → 空文档
        if name not in self:
            self[name] = _FakeCol({})
        return super().__getitem__(name)


def _patch_population(monkeypatch, codes):
    monkeypatch.setattr(runner, "day_population", lambda db, date: [
        {"stock": {"code": f"sh{c}", "name": c}, "board": "公告"} for c in codes])
    monkeypatch.setattr(runner, "hotlist_ranks", lambda db, date, cs, *a, **k: {c: 3 for c in cs})
    monkeypatch.setattr(runner, "build_pilot_narrative",
                        lambda db, date, code, stock, board, rank, *a, **k: f"叙事:{code}")


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
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms, **_kw: _parse_ok("ferment"))
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
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms, **_kw: {
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
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms, **_kw: _parse_ok("start"))
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
    monkeypatch.setattr(runner, "parse_jev_response", lambda env, ms, **_kw: _parse_ok("divergence"))
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
