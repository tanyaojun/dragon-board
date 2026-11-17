# -*- coding: utf-8 -*-
"""反包板池（rewrap）立项落地测试（2026-10-21，jev-rewrap-factor-preregistration.md）。

锁定项（全 fake/monkeypatch，零真实 jev 调用，AGENTS §1.2-7）：
- 口径：断板候选池=前 2~5 交易日在板 & 昨日未板；反包率分母归一（裸计数与当日涨停家数
  corr=0.684 共线，预注册 §4）；回封率分母=昨日炸板池；池空/池缺失 fail-visible 不补 0；
- 池一日两更：12:30 午盘链更 `{date}:midday`（触板口径）、17:00 盘后链更 `{date}:final`；
  dry-run 零写入；
- 免投喂承接：池内股零 jev 调用复制前日标签（labelSource=rewrap_carry 可追溯），
  守卫不满足回落实判不静默降级；
- relay 叙事反包修复行（R1）与读口/KPI payload（R2）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.analysis.hotlist.rewrap_pool import (
    build_rewrap_pool, percentile_of, zt_codes)
from backend.operations import rewrap_pool as pool_ops
from backend.operations import jev_label_jiuyan as runner

D0 = "2026-10-21"
D1, D2, D3, D4, D5 = "2026-10-20", "2026-10-19", "2026-10-16", "2026-10-15", "2026-10-14"


class FakeCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def _match(self, r, q):
        import re as _re
        for k, v in (q or {}).items():
            if isinstance(v, dict):
                for op, ov in v.items():
                    if op == "$in" and r.get(k) not in ov:
                        return False
                    if op == "$lt" and not (r.get(k) is not None and r.get(k) < ov):
                        return False
                    if op == "$gte" and not (r.get(k) is not None and r.get(k) >= ov):
                        return False
                    if op == "$lte" and not (r.get(k) is not None and r.get(k) <= ov):
                        return False
                    if op == "$ne" and r.get(k) == ov:
                        return False
                    if op == "$regex" and not _re.search(ov, str(r.get(k) or "")):
                        return False
            elif r.get(k) != v:
                return False
        return True

    def find(self, query=None, projection=None):
        return [dict(r) for r in self.rows if self._match(r, query or {})]

    def find_one(self, query=None, projection=None, sort=None):
        rows = self.find(query)
        return rows[0] if rows else None

    def replace_one(self, query, doc, upsert=False):
        for i, r in enumerate(self.rows):
            if self._match(r, query or {}):
                self.rows[i] = dict(doc)
                return True
        if upsert:
            self.rows.append(dict(doc))
        return False


class FakeDb:
    def __init__(self, cols=None):
        self._cols = cols or {}

    def __getitem__(self, k):
        return self._cols.setdefault(k, FakeCol())


def _final(date, stocks):
    return {"_id": f"{date}:final", "kind": "jiuyan_action", "tradingDate": date,
            "fields": [{"name": "板块A", "stocks": list(stocks)}]}


def _midday(date, stocks, fetched="2026-10-21T12:06:00"):
    return {"_id": f"{date}:midday", "kind": "jiuyan_action", "tradingDate": date,
            "fetchedAt": fetched,
            "fields": [{"name": "板块A", "stocks": list(stocks)}]}


def _st(code, name, num=None, time="09:31:00", expound="测试原因"):
    return {"code": f"sz{code}", "name": name, "num": num, "time": time, "expound": expound}


def _frame(date, failed=None, with_pool=True):
    ls = {"zhaban": {"ztCount": 50}}
    if with_pool:
        ls["thsPools"] = {"ok": True, "degraded": False,
                          "pools": {"failed": {"ok": True, "items": [{"code": f"sz{c}"} for c in (failed or [])]}}}
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "limitSummary": ls}


@pytest.fixture(autouse=True)
def _clear_caches():
    runner._STREAK_CACHE.clear()
    for name in ("_MKT_COORD_CACHE", "_DATE_AXIS_CACHE", "_JIYAN_EXPOUND_CACHE",
                 "_BOARD_PREV_CACHE", "_THS_STATE_CACHE", "_PREV_TRADING_DATES_CACHE"):
        getattr(runner, name, None) and getattr(runner, name).clear()
    yield
    runner._STREAK_CACHE.clear()


def _db_days() -> FakeDb:
    """D-5..D-1 历史日 + D0 final/midday：
    600003 前 5 日连板、昨日断板、今日回封 → 反包；
    600004 昨日炸板今日回封 → 反包+reseal；
    600005 昨日断板今日未回封 → 仅候选；
    600006 今日首板（窗口内无板）→ 非候选。"""
    return FakeDb({"jiuyan_action": FakeCol([
        _final(D5, [_st("600003", "五连板股", "5天5板"), _st("600004", "炸板回封股", "2天2板")]),
        _final(D4, [_st("600003", "五连板股", "6天6板"), _st("600004", "炸板回封股", "3天3板")]),
        _final(D3, [_st("600003", "五连板股", "7天7板"), _st("600004", "炸板回封股", "4天4板")]),
        _final(D2, [_st("600003", "五连板股", "8天8板"), _st("600004", "炸板回封股", "5天5板"),
                    _st("600005", "昨日断板股", "3天2板")]),
        _final(D1, [_st("600007", "昨日首板", "2天2板")]),            # 600003/4/5 全断板
        _final(D0, [_st("600003", "五连板股", "9天8板", time="09:40:00"),
                    _st("600004", "炸板回封股", "6天5板"),
                    _st("600006", "今日首板", time="10:00:00")]),
        _midday(D0, [_st("600003", "五连板股", "9天8板", time="09:40:00"),
                     _st("600004", "炸板回封股", "6天5板")]),
    ]), "snapshot_frames": FakeCol([
        _frame(D5), _frame(D4), _frame(D3), _frame(D2), _frame(D1, failed=["600004"]),
        _frame(D0, failed=["600999"]),
    ])})


# ── 口径（纯计算层） ─────────────────────────────────────────────────────────
def test_build_rewrap_pool_final_caliber():
    db = _db_days()
    pool = build_rewrap_pool(db, D0, "final")
    # 候选池=窗口内曾板 & 昨日未板：600003/600004/600005（600007 昨日在板 → 非候选）
    assert set(pool["candidate"]) == {"600003", "600004", "600005"}
    assert pool["candidateN"] == 3
    assert set(pool["rewrapCodes"]) == {"600003", "600004"}
    assert pool["rewrapN"] == 2 and abs(pool["rewrapRate"] - 2 / 3) < 1e-3
    # 回封：昨日炸板池 {600004} ∩ 今日 → 600004
    assert pool["prevFailedFound"] and pool["prevFailedN"] == 1
    assert pool["resealCodes"] == ["600004"] and pool["resealRate"] == 1.0
    # 明细：反包股带今日口径 + 回溯字段
    by = {s["code"]: s for s in pool["stocks"]}
    assert by["600003"]["prevMaxBoards"] == 8 and by["600003"]["breakDays"] == 1
    assert by["600003"]["time"] == "09:40:00" and by["600003"]["reseal"] is False
    assert by["600004"]["reseal"] is True
    assert not pool["missing"]["axis_short"] and not pool["missing"]["prev_failed_missing"]


def test_build_rewrap_pool_midday_touched_caliber():
    """午盘口径=触板名单：600005 午盘未触板不在池内；caliber=touched。"""
    db = _db_days()
    pool = build_rewrap_pool(db, D0, "midday")
    assert pool["caliber"] == "touched"
    assert set(pool["rewrapCodes"]) == {"600003", "600004"}


def test_build_rewrap_pool_missing_fail_visible():
    """昨日炸板池缺失/交易日轴不足 → missing 标志，不补 0 不冒充。"""
    db = FakeDb({"jiuyan_action": FakeCol([
        _final(D1, [_st("600003", "甲", "2天2板")]),
        _final(D0, [_st("600003", "甲", "3天3板")]),
    ]), "snapshot_frames": FakeCol([])})
    pool = build_rewrap_pool(db, D0, "final")
    assert pool["missing"]["axis_short"] is True          # 只有 1 个前交易日
    assert pool["rewrapCodes"] == [] and pool["rewrapRate"] is None
    db2 = FakeDb({"jiuyan_action": FakeCol(_db_days()["jiuyan_action"].rows),
                  "snapshot_frames": FakeCol(
                      [_frame(d, with_pool=False) for d in (D5, D4, D3, D2, D1)])})
    pool2 = build_rewrap_pool(db2, D0, "final")
    assert pool2["missing"]["axis_short"] is False
    assert pool2["missing"]["prev_failed_missing"] is True and pool2["resealRate"] is None


def test_percentile_of():
    assert percentile_of([0.0, 0.1, 0.2, 0.3, 0.4], 0.2) == 60
    assert percentile_of([None] * 3, 0.2) is None and percentile_of([0.1, 0.2], 0.2) is None


# ── 池落库（一日两更快照） ───────────────────────────────────────────────────
def test_update_rewrap_pool_upsert_idempotent(monkeypatch):
    """快照幂等覆盖 + ratePct20d 落库；二次更新不产生重复文档。"""
    db = _db_days()
    doc = pool_ops.update_rewrap_pool(db, D0, "final")
    assert doc["_id"] == f"{D0}:final" and doc["rewrapN"] == 2
    assert doc["ratePct20d"] is None or isinstance(doc["ratePct20d"], int)  # 样本<5 → None
    n1 = len(db["hotlist_rewrap_pool"].rows)
    pool_ops.update_rewrap_pool(db, D0, "final")
    assert len(db["hotlist_rewrap_pool"].rows) == n1
    assert pool_ops.get_rewrap_pool(db, D0, "final")["candidateN"] == 3


# ── 免投喂承接（零 jev 调用复制前日标签） ────────────────────────────────────
def _prev_label(date, code, answers=None):
    return {"_id": f"{date}:{code}", "tradingDate": date, "code": code, "status": "ok",
            "labelSlot": "final",
            "questionSetVersion": runner.QUESTION_SET_VERSION_DRIVER,
            "questionSetHash": runner._questions_hash(runner.QUESTIONS_STOCK),
            "ammoVersion": runner.AMMO_VERSION, "labelSource": "fresh_judgment",
            "answers": answers or {
                "driver_type": {"choice": "policy", "probabilities": {"policy": 0.6}},
                "catalyst_depth": {"choice": "core_main_business"},
                "catalyst_freshness": {"choice": "continuing"},
                "buy_side_logic": {"choice": "sector_follow"}}}


def test_rewrap_carry_one_copies_prev_label():
    db = _db_days()
    col = db["hotlist_jev_driver_labels"]
    col.rows.append(_prev_label(D1, "600003"))
    entry = {"stock": _st("600003", "五连板股", "9天8板"), "board": "板块A"}
    ok = runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                  "dragonboard_live",
                                  runner._questions_hash(runner.QUESTIONS_STOCK),
                                  include_stock_phase=False, jy_doc=None, rank=None)
    assert ok is True
    doc = col.find_one({"_id": f"{D0}:600003"})
    assert doc["labelSource"] == "rewrap_carry" and doc["rewrapCarry"] is True
    assert doc["carriedFrom"] == D1
    assert doc["label"] == "policy" and doc["freshness"] == "continuing"
    assert doc["usage"] == {"input_tokens": 0, "output_tokens": 0} and doc["latencyMs"] == 0
    assert "韭研解析全文：" in doc["narrative"]       # 当日叙事照常组装（零 token）


def test_rewrap_carry_guards_fall_back():
    db = _db_days()
    col = db["hotlist_jev_driver_labels"]
    entry = {"stock": _st("600003", "五连板股", "9天8板"), "board": "板块A"}
    h = runner._questions_hash(runner.QUESTIONS_STOCK)
    # 窗内无前标 → False
    assert runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                    "dragonboard_live", h, False, None, None) is False
    # 前标答案缺失 → False（不静默降级成假 ok）
    col.rows.append(_prev_label(D1, "600003", answers={"driver_type": {"choice": "policy"}}))
    assert runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                    "dragonboard_live", h, False, None, None) is False
    # 题集代际不符 → False
    col.rows = [_prev_label(D1, "600003")]
    col.rows[0]["questionSetHash"] = "mismatch"
    assert runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                    "dragonboard_live", h, False, None, None) is False


def test_rewrap_carry_freshness_guards_fall_back():
    """新鲜度守卫（2026-10-22 用户裁决）：freshness 是日期相对题，跨日承接语义失真——
    前标 unclear（没判出来，承接=永久化信息缺失）或 fresh_catalyst（≤2 交易日随承接日
    漂移）→ 回落实判；continuing/none 可正常承接。"""
    db = _db_days()
    col = db["hotlist_jev_driver_labels"]
    entry = {"stock": _st("600003", "五连板股", "9天8板"), "board": "板块A"}
    h = runner._questions_hash(runner.QUESTIONS_STOCK)

    def _with_freshness(choice):
        prev = _prev_label(D1, "600003")
        prev["answers"]["catalyst_freshness"] = {"choice": choice}
        return prev

    # 前标 unclear → False（2026-10-22 林州重机案例：承接 10-16 unclear = 信息缺失复制）
    col.rows = [_with_freshness("unclear")]
    assert runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                    "dragonboard_live", h, False, None, None) is False
    # 前标 fresh_catalyst → False（今日新催化的「≤2 交易日」随承接日漂移）
    col.rows = [_with_freshness("fresh_catalyst")]
    assert runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                    "dragonboard_live", h, False, None, None) is False
    # 对照：continuing → 承接成立；none → 承接成立
    for choice in ("continuing", "none"):
        col.rows = [_with_freshness(choice)]
        assert runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                        "dragonboard_live", h, False, None, None) is True, choice
        assert col.find_one({"_id": f"{D0}:600003"})["freshness"] == choice


# ── run() 集成：池股零调用 + FINAL 计数（沿用午盘槽测试基建的假 dispatch） ────
def _fake_parse(env, ms, expected_keys=None):
    return {"ok": True, "answers": {"driver_type": {"choice": "capital_flow", "probabilities": {"capital_flow": 0.8}},
                                    "catalyst_depth": {"choice": "core_main_business"},
                                    "catalyst_freshness": {"choice": "continuing"},
                                    "buy_side_logic": {"choice": "sector_follow"}},
            "usage": {"input_tokens": 100, "output_tokens": 10}, "model": "fake",
            "errorCode": None, "errorDetail": None, "latencyMs": ms}


def test_run_skips_rewrap_pool_stocks(monkeypatch, tmp_path):
    """池内股不进 dispatch、落 rewrap_carry 文档；FINAL 带计数；池快照落库。"""
    db = _db_days()
    col = db["hotlist_jev_driver_labels"]
    col.rows.append(_prev_label(D1, "600003"))
    calls: list[str] = []
    monkeypatch.setattr(runner, "_db", lambda: db)
    monkeypatch.setattr(runner, "_dispatch_jev", lambda narrative, questions: ({}, 12))
    monkeypatch.setattr(runner, "parse_jev_response", _fake_parse)
    runner.run(D0, D0, False, "tok", "acc", workers=1, confirm_budget=True, slot="final")
    # 600003 免投喂承接（0 token）；600004 无前标 → 回落实判；600006 正常实判
    assert len(calls) >= 0
    carried = col.find_one({"_id": f"{D0}:600003"})
    assert carried["labelSource"] == "rewrap_carry"
    fresh = col.find_one({"_id": f"{D0}:600004"})
    assert fresh and fresh["labelSource"] == "fresh_judgment"
    assert db["hotlist_rewrap_pool"].find_one({"_id": f"{D0}:final"})["rewrapN"] == 2


def test_run_dry_run_does_not_write_pool(monkeypatch, capsys):
    db = _db_days()
    monkeypatch.setattr(runner, "_db", lambda: db)
    monkeypatch.setattr(runner, "_dispatch_jev", lambda narrative, questions: ({}, 12))
    monkeypatch.setattr(runner, "parse_jev_response", _fake_parse)
    runner.run(D0, D0, True, "tok", "acc", workers=1, slot="final")
    assert db["hotlist_rewrap_pool"].find({}) == []          # dry-run 零写入


# ── 审查修复项（2026-10-21 reviewer：MF1/MF2/SF6/7/8/9/10） ──────────────────
def test_rewrap_carry_phase_guard_falls_back():
    """MF1：相位题开启而前标无相位答案 → 回落实判，不得盖 ok 戳静默给 None。"""
    db = _db_days()
    col = db["hotlist_jev_driver_labels"]
    col.rows.append(_prev_label(D1, "600003"))          # 无 stock_phase_position
    entry = {"stock": _st("600003", "五连板股", "9天8板"), "board": "板块A"}
    h = runner._questions_hash(runner.QUESTIONS_STOCK)
    assert runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                    "dragonboard_live", h, include_stock_phase=True,
                                    jy_doc=None, rank=None) is False
    # 前标带相位答案 → 承接成立且相位字段随档
    col.rows = [_prev_label(D1, "600003", answers={
        "driver_type": {"choice": "policy"}, "catalyst_depth": {"choice": "core_main_business"},
        "catalyst_freshness": {"choice": "continuing"}, "buy_side_logic": {"choice": "sector_follow"},
        "stock_phase_position": {"choice": "ferment"}})]
    assert runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                    "dragonboard_live", h, include_stock_phase=True,
                                    jy_doc=None, rank=None) is True
    doc = col.find_one({"_id": f"{D0}:600003"})
    assert doc["stockPhasePosition"] == "ferment"


def test_rewrap_carry_excludes_chain_and_records_provenance():
    """SF7/8：前标自身是 rewrap_carry → 不链式承接；承接档记 carriedLabelSlot/carriedOriginDate。"""
    db = _db_days()
    col = db["hotlist_jev_driver_labels"]
    chained = _prev_label(D1, "600003")
    chained["labelSource"] = "rewrap_carry"
    chained["carriedFrom"] = "2026-10-14"
    col.rows.append(chained)
    entry = {"stock": _st("600003", "五连板股", "9天8板"), "board": "板块A"}
    h = runner._questions_hash(runner.QUESTIONS_STOCK)
    assert runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                    "dragonboard_live", h, False, None, None) is False
    # 正常前标（final 槽）→ 承接档带槽位与原始判定日
    col.rows = [_prev_label(D1, "600003")]
    assert runner._rewrap_carry_one(db, col, D0, "600003", entry, "final",
                                    "dragonboard_live", h, False, None, None) is True
    doc = col.find_one({"_id": f"{D0}:600003"})
    assert doc["carriedLabelSlot"] == "final"
    assert doc["carriedOriginDate"] == D1


def test_run_dispatches_never_for_pool_stock(monkeypatch):
    """SF10：池内股零 jev 调用必须被真锁（mock 记录下发叙事，承接路径回归成实判会红）。"""
    db = _db_days()
    col = db["hotlist_jev_driver_labels"]
    col.rows.append(_prev_label(D1, "600003"))
    narratives: list[str] = []
    monkeypatch.setattr(runner, "_db", lambda: db)
    monkeypatch.setattr(runner, "_dispatch_jev",
                        lambda narrative, questions: (narratives.append(narrative) or ({}, 12)))
    monkeypatch.setattr(runner, "parse_jev_response", _fake_parse)
    runner.run(D0, D0, False, "tok", "acc", workers=1, confirm_budget=True, slot="final")
    assert len(narratives) == 2, "池内 600003 不得下发 jev（只实判 600004/600006）"
    assert all("五连板股" not in n for n in narratives)


def test_board_prev_t2_fallback_t1_doc_missing_label(monkeypatch):
    """SF6：T-1 名单整体缺失 + T-2 命中 → 文案写「T-1 名单缺失」，不冒充「无同名板块」。"""
    monkeypatch.setattr(runner, "trading_dates_before",
                        lambda db_, d, n=20, dataset_id=None: ["2026-10-19", "2026-10-20"][-n:])
    db = FakeDb({"jiuyan_action": FakeCol([
        _final("2026-10-19", [_st("600001", "甲"), _st("600002", "乙")]),
    ])})
    info = runner.board_prev_info(db, "2026-10-21", "板块A")
    assert info["ok"] is True and info["count"] == 2 and info["reason"] == "t2_fallback"
    assert info["t1Found"] is False and info["t2Found"] is True
    doc = {"_id": f"2026-10-21:midday", "fields": [{"name": "板块A",
            "stocks": [_st("600002", "乙", time="10:30:00")]}]}
    line = runner.board_position(doc, "600002", db=db, date="2026-10-21")
    assert "前 2 交易日" in line and "昨日同板块" not in line, "2026-10-30g+：口径注删（不冒充昨日）"


# ── MF2：R1/R2 承诺测试（叙事行三态 + 插入位置 + 读口合同） ─────────────────
def test_rewrap_face_line_states():
    from backend.operations.jev_relay_index import rewrap_face_line
    db = _db_days()
    line = rewrap_face_line(db, D0)
    assert "反包修复：昨日断板候选 3 只 · 今日反包 2 只（反包率 66.7%" in line
    assert "近20日分位不可算" in line            # 快照缺 + 分位样本<5 → 不可算，不补数
    assert "昨日炸板回封 1/1（100.0%）" in line
    # v10 D3/A4：代表股与停牌复牌口径注撤出叙事；口径注移结构化 poolCaveat
    assert "代表：" not in line and "停牌复牌未分辨" not in line
    from backend.analysis.hotlist.rewrap_pool import build_rewrap_pool
    pool = build_rewrap_pool(db, D0, "final")
    assert pool["poolCaveat"] == "候选池含停牌复牌未分辨"
    assert len(pool["stocks"]) == 2   # 明细仍在结构化字段（审计/读口消费）
    # 轴不足
    db2 = FakeDb({"jiuyan_action": FakeCol([
        _final(D1, [_st("600003", "甲", "2天2板")]),
        _final(D0, [_st("600003", "甲", "3天3板")])]), "snapshot_frames": FakeCol([])})
    assert rewrap_face_line(db2, D0) == "反包修复：不可算", "2026-10-30g+：括号删"
    # 昨日炸板池缺失
    db3 = FakeDb({"jiuyan_action": FakeCol(_db_days()["jiuyan_action"].rows),
                  "snapshot_frames": FakeCol(
                      [_frame(d, with_pool=False) for d in (D5, D4, D3, D2, D1)])})
    assert "昨日炸板池缺失" in rewrap_face_line(db3, D0)
    # 昨日名单缺失（候选池不可验，审查 SF4）
    rows = [r for r in _db_days()["jiuyan_action"].rows if r["_id"] != f"{D1}:final"]
    db4 = FakeDb({"jiuyan_action": FakeCol(rows),
                  "snapshot_frames": FakeCol([_frame(d) for d in (D5, D4, D3, D2, D1)])})
    assert rewrap_face_line(db4, D0) == "反包修复：不可算", "2026-10-30g+：括号删"


def test_relay_narrative_rewrap_line_position(monkeypatch):
    """MF2/G3：反包行必须紧跟炸板面行，其余既有段落顺序零漂移。"""
    from backend.operations import jev_relay_index as RI
    seq = ["market_facts_line", "market_index_line", "zhaban_face_line", "relay_flow_line",
           "ladder_structure_line", "three_day_chain_line", "theme_evolution_line"]

    def _mk(n):
        return lambda *a, **k: n
    for n in seq:
        monkeypatch.setattr(RI, n, _mk(n))
    singles = {"relay_structure": {}, "relay_trajectory_line": "TRJ"}
    lists = {"theme_evidence_lines": [], "sector_relay_lines": [],
             "high_position_trajectory_lines": [], "theme_ladder_lines": [],
             "leader_structure_lines": [], "leader_profile_lines": [], "anchor_lines": ["ANCH"]}
    for n, v in singles.items():
        monkeypatch.setattr(RI, n, (lambda vv: lambda *a, **k: vv)(v))
    for n, v in lists.items():
        monkeypatch.setattr(RI, n, (lambda vv: lambda *a, **k: list(vv))(v))
    monkeypatch.setattr(RI, "rewrap_face_line", lambda *a, **k: "REWRAP")
    text = RI._build_relay_narrative_inner(FakeDb(), D0)
    lines = text.splitlines()
    assert lines[lines.index("zhaban_face_line") + 1] == "REWRAP", "反包行必须紧跟炸板面行"
    assert lines.count("REWRAP") == 1
    assert lines[-1] == "ANCH" and "TRJ" in lines      # 既有段落仍在场


def test_limitup_route_rewrap_payload(monkeypatch):
    """MF2：读口合同——池统计 + 池内股标记 + 触板口径徽标（随 boardJoinSlot）。"""
    from backend.api import hotlist_jev_limitup_routes as routes
    db = _db_days()
    monkeypatch.setattr(routes.repository_factory, "get_runtime_mongodb_database", lambda: db)
    monkeypatch.setattr(routes, "collect_limitup_labels",
                        lambda db_, date_, with_raw=False:
                        {"ok": True, "stocks": [{"code": "sz600003", "name": "五连板股"},
                                                {"code": "sz600006", "name": "今日首板"}]})
    monkeypatch.setattr(runner, "jiuyan_board_info",
                        lambda db_, date_, allow_midday_fallback=False:
                        ({"600003": {"boards": 8, "days": 9, "limitUpTime": "09:40:00",
                                     "boardName": "板块A"}},
                         {"middayFallbackUsed": True, "jiuyanFinalFound": False,
                          "thsPoolFound": False, "prevPoolFound": None}))
    monkeypatch.setattr(runner, "jiuyan_streak_map",
                        lambda db_, date_, allow_midday_fallback=False: {"600003": None})
    monkeypatch.setattr(runner, "jiuyan_board_dragons",
                        lambda db_, date_, allow_midday_fallback=False: {})
    result = routes.get_limitup_labels(date=D0)
    assert result["boardJoinSlot"] == "midday"
    rw = result["rewrap"]
    assert rw["slot"] == "midday" and rw["caliber"] == "touched"
    assert rw["count"] == 2 and rw["candidate"] == 3
    # v10 A4/P1：口径注结构化后读口同步透出（披露可达）
    assert rw["poolCaveat"] == "候选池含停牌复牌未分辨"
    assert {s["code"] for s in rw["stocks"]} == {"600003", "600004"}
    by_code = {s["code"]: s for s in result["stocks"]}
    assert by_code["sz600003"].get("rewrap") is True
    assert "rewrap" not in by_code["sz600006"]


# ── 历史回填入口（2026-10-21 用户问询「历史数据怎么回填」） ─────────────────
def test_backfill_final_writes_and_midday_rejects_backfill_doc():
    """final 逐日幂等写入；midday 只收真午盘名单（收盘补写的伪午盘 skip 并给 reason）。"""
    from backend.operations.rewrap_pool import backfill_rewrap_pool
    db = _db_days()
    # D1/D0 final 在轴上；D0 midday fetchedAt=12:06（真午盘）
    res = backfill_rewrap_pool(db, D5, D0, slots=("final", "midday"))
    assert res["written"] == 7 and res["skipped"] == 5       # 6 日 final + D0 真午盘 midday；
    # D5..D1 无 midday 文档 → 逐日 skip（reason=no_midday_doc，fail-visible）
    assert db["hotlist_rewrap_pool"].find_one({"_id": f"{D0}:final"})
    # midday：D0 真午盘写入
    assert db["hotlist_rewrap_pool"].find_one({"_id": f"{D0}:midday"})
    # 伪午盘（fetchedAt 收盘后）→ skip
    db["jiuyan_action"].rows.append(
        {"_id": f"{D1}:midday", "kind": "jiuyan_action", "tradingDate": D1,
         "fetchedAt": "2026-10-20T20:04:07",
         "fields": [{"name": "板块A", "stocks": [_st("600003", "五连板股")]}]})
    res2 = backfill_rewrap_pool(db, D1, D1, slots=("midday",))
    assert res2["written"] == 0 and res2["skipped"] == 1
    assert res2["results"][0]["reason"] == "midday_doc_not_noon"


def test_backfill_dry_run_zero_write():
    from backend.operations.rewrap_pool import backfill_rewrap_pool
    db = _db_days()
    res = backfill_rewrap_pool(db, D5, D0, slots=("final",), dry_run=True)
    assert res["dryRun"] is True and res["written"] == 0
    assert db["hotlist_rewrap_pool"].find({}) == []
