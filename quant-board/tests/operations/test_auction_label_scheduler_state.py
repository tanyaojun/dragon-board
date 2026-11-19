# -*- coding: utf-8 -*-
"""竞价龙头调度器三缺陷修复测试（A+B+C，2026-11-19 用户裁决，方案
docs/hotlist-jev/auction-leader-label-scheduler-fix-plan-20261119.md）。

A：日级 run 状态持久化（hotlist_jev_label_run_state）——重启后不再 first_run 补跑；
   失败后依持久化 attempts/lastOk/lastAt 判重试；status attempt 跨重启不回退。
B：窗上界 09:35——窗外一律不跑（含重启 first_run），一次性 abandoned_window 终态；
   09:30:20 重试在窗内可执行。
C：当日人群冻结（hotlist_jev_auction_leader_selections）——首跑成功写冻结档；
   重试人群不变不加新股；dry_run 不写；force 绕过并披露 forcedOutsideSelection。
零真实 jev / 零网络（AGENTS §1.2-7），全 monkeypatch/假库。
"""
from __future__ import annotations

import asyncio
import datetime
import importlib.util
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import auction_leader_label as L
from backend.snapshot_collector import scheduler as S

# 复用既有全假 harness（FakeDb/_push/env fixture），避免双份假件漂移
_spec = importlib.util.spec_from_file_location(
    "_auction_label_harness", Path(__file__).with_name("test_auction_leader_label.py"))
_T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_T)
DATE = _T.DATE

RUN_STATE_COL = "hotlist_jev_label_run_state"
FREEZE_COL = "hotlist_jev_auction_leader_selections"
KEY = "auction_leader_label"


def _now(h: int, m: int, s: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, 11, 20, h, m, s, tzinfo=S.TZ_SHANGHAI)


def _no_run(date: str) -> dict:
    raise AssertionError("run_once 不得被调用")


def _retry_kwargs(now: datetime.datetime) -> dict:
    return {"max_attempts": S._AUCTION_LEADER_MAX_ATTEMPTS,
            "retry_after_s": S._AUCTION_LEADER_RETRY_AFTER.total_seconds(),
            "now": now}


@pytest.fixture()
def state_db(monkeypatch):
    db = _T.FakeDb()
    monkeypatch.setattr(S, "_label_run_state_db", lambda: db)
    return db


def _fake_sched() -> types.SimpleNamespace:
    return types.SimpleNamespace(_auction_leader_last=None)


# ── A：日级 run 状态持久化 ────────────────────────────────────────────────────

def test_a_persisted_ok_blocks_first_run_after_restart(state_db):
    # 重启前：首跑成功落账
    S._label_state_mark_result(KEY, DATE, attempts=1, ok=True,
                               result={"ok": True, "leaders": 2}, now=_now(9, 26))
    # 重启后：内存 state 全清（模拟重启），first_run 不再为 True（D1 根治）
    first, doc = S._persisted_first_run(KEY, DATE, in_memory_done=False)
    assert first is False and doc is not None
    assert doc["lastOk"] is True and doc["attempts"] == 1
    # lastOk=True 终态 → retry_due 也不满足（不补跑、不烧 jev token）
    assert S._persisted_retry_due(KEY, DATE, **_retry_kwargs(_now(12, 33))) is False


def test_a_failed_attempt_retries_by_persisted_interval_only(state_db):
    # 执行前预写（崩溃也留痕）：attempts=1、lastAt=09:25:20
    S._label_state_mark_attempt(KEY, DATE, now=_now(9, 25, 20))
    S._label_state_mark_result(KEY, DATE, attempts=1, ok=False,
                               result={"ok": False}, now=_now(9, 25, 20))
    # 重启后（内存全清）：已跑标记在场 → 非 first_run
    first, doc = S._persisted_first_run(KEY, DATE, in_memory_done=False)
    assert first is False and doc["attempts"] == 1
    # 重试间隔未满足 → 不重试；满足 → 重试
    assert S._persisted_retry_due(KEY, DATE, **_retry_kwargs(_now(9, 28))) is False
    assert S._persisted_retry_due(KEY, DATE, **_retry_kwargs(_now(9, 30, 20))) is True
    # 3 次用尽 → 当日不再重试
    S._label_state_mark_attempt(KEY, DATE, now=_now(9, 30, 20))
    S._label_state_mark_attempt(KEY, DATE, now=_now(9, 35, 30))
    doc = state_db[RUN_STATE_COL].docs[f"{KEY}:{DATE}"]
    assert doc["attempts"] == 3
    assert S._persisted_retry_due(KEY, DATE, **_retry_kwargs(_now(9, 45))) is False


def test_a_first_run_prewrite_marks_attempt_before_run(state_db):
    state = {"date": DATE, "done": set()}
    ran: list[str] = []

    def run_once(date: str) -> dict:   # 同步可调用（生产为 run_auction_leader_label_once，to_thread）
        # run 执行时预写必须已落库（崩溃窗口内 attempts 可见）
        doc = state_db[RUN_STATE_COL].docs[f"{KEY}:{date}"]
        assert doc["attempts"] == 1 and doc["lastOk"] is False
        ran.append(date)
        return {"ok": True, "leaders": 1}

    sched = _fake_sched()
    asyncio.run(S._auction_leader_slot_tick(sched, state, _now(9, 25, 20), DATE, run_once))
    assert ran == [DATE]
    doc = state_db[RUN_STATE_COL].docs[f"{KEY}:{DATE}"]
    assert doc["attempts"] == 1 and doc["lastOk"] is True and doc["firstRunAt"]
    assert state["done"] == {KEY}
    assert sched._auction_leader_last["attempt"] == 1


# ── A（review 补）：读失败与无档严格区分 ─────────────────────────────

def test_a_load_failed_is_undecidable_never_runs(monkeypatch):
    """review 修复（2026-11-19）：读失败与无档严格区分——无档才允许 first_run；
    不可判定（DB 故障叠加重启）本 tick 跳过，防 theme 链（≈112k tokens/次）
    经此侧门误跑（D1 复发向量）。"""
    def boom():
        raise RuntimeError("mongo down")
    monkeypatch.setattr(S, "_label_run_state_db", boom)
    state = {"date": DATE, "done": set()}
    asyncio.run(S._auction_leader_slot_tick(_fake_sched(), state, _now(9, 25, 20),
                                            DATE, _no_run))
    # 未执行、未预写、内存 done 不置位（下一 tick DB 恢复后自然续上）
    assert state["done"] == set()
    assert "auction_leader_attempts" not in state


def test_a_status_seed_restores_attempt_across_restart(state_db):
    # 重启前尝试失败（间隔未到即重启）
    S._label_state_mark_attempt(KEY, DATE, now=_now(9, 25, 20))
    S._label_state_mark_result(KEY, DATE, attempts=1, ok=False,
                               result={"ok": False}, now=_now(9, 25, 21))
    state = {"date": DATE, "done": set()}
    sched = _fake_sched()

    async def run_once(date: str) -> dict:
        raise AssertionError("重试间隔未到不得执行")

    asyncio.run(S._auction_leader_slot_tick(sched, state, _now(9, 27), DATE,
                                            lambda d: (_ for _ in ()).throw(AssertionError("重试间隔未到不得执行"))))
    # status 端点 attempt 跨重启不回退（§4 实弹判据）：持久化 attempt 种子回填
    assert sched._auction_leader_last["attempt"] == 1
    assert sched._auction_leader_last["restoredFromRunState"] is True
    assert sched._auction_leader_last["ok"] is False


# ── B：窗上界 09:35 ──────────────────────────────────────────────────────────

def test_b_out_of_window_abandons_once_and_never_runs(state_db):
    ran: list[str] = []

    def run_once(date: str) -> dict:
        ran.append(date)
        return {"ok": True}

    state = {"date": DATE, "done": set()}
    sched = _fake_sched()
    # 重启后 09:36（首跑场景）→ 不执行 + abandoned_window 终态落库（D2 根治）
    asyncio.run(S._auction_leader_slot_tick(sched, state, _now(9, 36), DATE, run_once))
    assert ran == []
    doc = state_db[RUN_STATE_COL].docs[f"{KEY}:{DATE}"]
    assert doc["abandonedWindow"] is True
    assert doc["lastResult"]["state"] == "abandoned_window"
    assert doc["lastOk"] is False
    # 终态在场 → 再次 tick（12:33）不重复写、不执行
    asyncio.run(S._auction_leader_slot_tick(sched, state, _now(12, 33), DATE, run_once))
    assert ran == []
    assert len(state_db[RUN_STATE_COL].docs) == 1


def test_b_retry_inside_window_runs(state_db):
    # 首跑 09:25:20 失败 → 09:30:20 重试在窗内可执行
    S._label_state_mark_attempt(KEY, DATE, now=_now(9, 25, 20))
    S._label_state_mark_result(KEY, DATE, attempts=1, ok=False,
                               result={"ok": False}, now=_now(9, 25, 20))
    ran: list[str] = []

    def run_once(date: str) -> dict:
        ran.append(date)
        return {"ok": True}

    state = {"date": DATE, "done": set()}
    sched = _fake_sched()
    asyncio.run(S._auction_leader_slot_tick(sched, state, _now(9, 30, 20), DATE, run_once))
    assert ran == [DATE]
    doc = state_db[RUN_STATE_COL].docs[f"{KEY}:{DATE}"]
    assert doc["attempts"] == 2 and doc["lastOk"] is True


def test_b_window_boundary_0935_exactly_abandons(state_db):
    ran: list[str] = []

    def run_once(date: str) -> dict:
        ran.append(date)
        return {"ok": True}

    state = {"date": DATE, "done": set()}
    asyncio.run(S._auction_leader_slot_tick(_fake_sched(), state, _now(9, 35, 0),
                                            DATE, run_once))
    assert ran == []
    assert state_db[RUN_STATE_COL].docs[f"{KEY}:{DATE}"]["abandonedWindow"] is True


def test_b_abandoned_terminal_guard_survives_restart(state_db):
    # 第一次 tick：窗外放弃落终态
    asyncio.run(S._auction_leader_slot_tick(_fake_sched(), {"date": DATE, "done": set()},
                                            _now(9, 36), DATE, _no_run))
    assert state_db[RUN_STATE_COL].docs[f"{KEY}:{DATE}"]["abandonedWindow"] is True
    # 重启：全新 state dict（内存 abandoned 标记丢失），持久层终态守卫仍挡住
    # （不重复写、不执行）——直测 _label_state_terminal，不依赖内存守卫
    fresh = {"date": DATE, "done": set()}
    asyncio.run(S._auction_leader_slot_tick(_fake_sched(), fresh, _now(12, 33),
                                            DATE, _no_run))
    assert len(state_db[RUN_STATE_COL].docs) == 1


def test_b_window_constants_contract():
    assert S._AUCTION_LEADER_LABEL_AT == datetime.time(9, 25, 20)
    assert S._AUCTION_LEADER_WINDOW_END == datetime.time(9, 35)
    assert S._AUCTION_LEADER_MAX_ATTEMPTS == 3
    assert S._AUCTION_LEADER_RETRY_AFTER == datetime.timedelta(minutes=5)


# ── C：当日人群冻结 ──────────────────────────────────────────────────────────

@pytest.fixture()
def env(monkeypatch):
    db, calls = _T.env.__wrapped__(monkeypatch)
    return db, calls


def test_c_first_run_writes_freeze_doc(env):
    db, calls = env
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"], res
    assert res["selectionFrozen"] is True
    assert res["freezeState"]["state"] == "ok"
    doc = db[FREEZE_COL].docs[DATE]
    assert doc["slot"] == "s0925" and doc["frozenAt"] and doc["unionN"] >= 1
    assert [r["code"] for r in doc["rows"]] == ["603135"]
    assert doc["rows"][0]["selectionSources"] == ["auction_push"]


def test_c_frozen_rows_survive_underlying_drift(env):
    db, calls = env
    db[FREEZE_COL].docs[DATE] = {
        "_id": DATE, "date": DATE, "unionN": 1, "slot": "s0925",
        "frozenAt": "2026-11-19T09:26:00+08:00",
        "selection": {"pushN": 1, "unionN": 1},
        "rows": [{"code": "603135", "name": "中重科技", "board": "机器人",
                  "boardSource": "auction_push", "pushBoard": "机器人",
                  "pct": 3.0, "selectionSources": ["auction_push"]}]}
    # 人为篡改底层选择原料（open_pct 修正/推送名单漂移场景替身）：top1 换股
    db["kpl_live_daily"].docs[DATE]["auctionPush"]["stocks"] = [
        {"code": "600000", "name": "浦发银行", "pct": 9.9, "board": "银行",
         "boardRaw": "银行"}]
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"], res
    assert res["selectionFrozen"] is True
    assert res["selection"]["selectionFrozen"] is True
    assert res["selection"]["frozenAt"] == "2026-11-19T09:26:00+08:00"
    # 重试人群=冻结档：不加新股、不随原料漂移（D3 根治）
    codes = {d.get("code") for d in db[L.COLLECTION].docs.values() if d.get("code")}
    assert codes == {"603135"}
    assert res["leaders"] == 1


def test_c_dry_run_never_reads_or_writes_freeze(env):
    db, calls = env
    res = L.run(DATE, dry_run=True)
    assert res["dryRun"] and res["selectionFrozen"] is False
    assert res["freezeState"]["state"] == "skipped_dry_run"
    assert FREEZE_COL not in db.cols, "dry_run 不得读写冻结档"


def test_c_load_failed_never_overwrites_freeze(env):
    """review 修复（2026-11-19）：冻结档读失败 ≠ 档缺席——读失败窗口内重算
    人群成功后不得覆写已有冻结档（D3 经「瞬时 Mongo 读失败」复发向量）。"""
    import copy
    db, calls = env
    frozen_doc = {
        "_id": DATE, "date": DATE, "unionN": 1, "slot": "s0925",
        "frozenAt": "2026-11-19T09:26:00+08:00",
        "selection": {"pushN": 1, "unionN": 1},
        "rows": [{"code": "603135", "name": "中重科技", "board": "机器人",
                  "boardSource": "auction_push", "pushBoard": "机器人",
                  "pct": 3.0, "selectionSources": ["auction_push"]}]}
    db[FREEZE_COL].docs[DATE] = copy.deepcopy(frozen_doc)
    col = db[FREEZE_COL]

    def boom(*a, **k):
        raise RuntimeError("transient mongo")
    col.find_one = boom   # 仅冻结集合读失败（load_frozen_selection 捕获 → load_failed）
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"], res
    # fail-visible：load_failed 原样透出，不伪装成缺席
    assert res["freezeState"]["state"].startswith("load_failed")
    assert res["selectionFrozen"] is False
    # 冻结档一字未动（含 frozenAt/rows/selection，防重算人群覆写）
    assert db[FREEZE_COL].docs[DATE] == frozen_doc


def test_c_force_bypasses_freeze_and_discloses_outside(env):
    db, calls = env
    db[FREEZE_COL].docs[DATE] = {
        "_id": DATE, "date": DATE, "unionN": 1, "slot": "s0925",
        "frozenAt": "2026-11-19T09:26:00+08:00",
        "selection": {"pushN": 1, "unionN": 1},
        "rows": [{"code": "603135", "name": "中重科技", "board": "机器人",
                  "boardSource": "auction_push", "pct": 3.0,
                  "selectionSources": ["auction_push"]}]}
    # force 单股重跑任意 code（不在冻结人群）→ 不受限（重算人群），如实披露
    res = L.run(DATE, confirm_budget=True, force=True, codes={"600000"})
    assert res["forcedOutsideSelection"] == ["600000"]
    assert res["selectionFrozen"] is False
    # force 不覆写冻结档（单写者=label run 全日跑）
    assert db[FREEZE_COL].docs[DATE]["rows"][0]["code"] == "603135"
    assert calls == []   # 600000 不在重算人群 → 零 jev 调用（skip no_leaders）
