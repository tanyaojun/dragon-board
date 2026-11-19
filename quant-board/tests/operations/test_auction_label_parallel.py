# -*- coding: utf-8 -*-
"""竞价龙头并行取数相测试（2026-11-19 用户裁决 1+2，预登记增补三）。

锁定口径：槽位 09:25:20；MBL 审计线程/T-1 DB bundle 线程入口即启动（先于 roster）；
dry-run 零 MBL 线程零外呼；MBL join 受 40s 预算约束，超时 parallel_pending 披露；
worker 失败 fail-visible 不阻断；timings 逐相耗时进返回态。零真实 jev/零网络。
"""
from __future__ import annotations

import datetime
import importlib.util
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import auction_leader_label as L

# 复用既有全假 harness（FakeDb/_push/env fixture），避免双份假件漂移
_spec = importlib.util.spec_from_file_location(
    "_auction_label_harness", Path(__file__).with_name("test_auction_leader_label.py"))
_T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_T)
DATE = _T.DATE


@pytest.fixture()
def env(monkeypatch):
    db, calls = _T.env.__wrapped__(monkeypatch)
    # 并行相专项：窗内 + MBL/腾讯假件（防墙钟真连上游）
    monkeypatch.setattr(L, "_in_auction_window", lambda: True)
    monkeypatch.setattr(L, "_sleep_until_mbl_floor", lambda: None)
    monkeypatch.setattr(L, "collect_auction_bidding_direct",
                        lambda db, date: {"state": "ok", "n_rows": 1})
    monkeypatch.setattr(L, "get_auction_snapshot_tencent",
                        lambda codes: {"ok": True, "items": {}, "missing": list(codes)})
    return db, calls


def test_slot_moved_to_092520():
    from backend.snapshot_collector import scheduler as S
    assert S._AUCTION_LEADER_LABEL_AT == datetime.time(9, 25, 20)
    assert S._AUCTION_LEADER_MAX_ATTEMPTS == 3


def test_mbl_worker_ok_and_fail_visible(monkeypatch):
    monkeypatch.setattr(L, "_sleep_until_mbl_floor", lambda: None)
    holder: dict = {}
    monkeypatch.setattr(L, "collect_auction_bidding_direct",
                        lambda db, date: {"state": "ok", "n_rows": 2})
    L._mbl_audit_worker(None, DATE, holder)
    assert holder["state"] == {"state": "ok", "n_rows": 2}

    def boom(db, date):
        raise ValueError("upstream down")
    monkeypatch.setattr(L, "collect_auction_bidding_direct", boom)
    holder = {}
    L._mbl_audit_worker(None, DATE, holder)
    assert holder["state"]["state"].startswith("fetch_failed:")


def test_basis_worker_ok_and_fail_visible(monkeypatch):
    holder: dict = {}
    monkeypatch.setattr(L, "get_daban_prev_day_basis",
                        lambda date, codes: {"basis": {"600000": {"prev_close": 1.0}}})
    L._basis_worker(DATE, ["600000"], holder)
    assert holder["state"] == "ok" and holder["basis"]["600000"]["prev_close"] == 1.0

    def boom(date, codes):
        raise RuntimeError("tencent down")
    monkeypatch.setattr(L, "get_daban_prev_day_basis", boom)
    holder = {}
    L._basis_worker(DATE, ["600000"], holder)
    assert holder["state"].startswith("fetch_failed:")


def test_bundle_keys_and_error_path(monkeypatch):
    import backend.operations.jev_label_jiuyan as JJ
    monkeypatch.setattr(L.ABM, "load_board_context", lambda db, d: {"ctx": d})
    monkeypatch.setattr(JJ, "market_facts_line", lambda db, d, ds: "line")
    monkeypatch.setattr(L, "day_leader_rows", lambda *a, **k: ([{"code": "600000"}], {}))
    monkeypatch.setattr(L, "fetch_pool_quality", lambda db, d: {"items": {}})
    monkeypatch.setattr(L, "sealed_and_info", lambda db, d: ({"600000"}, {}, "m"))
    monkeypatch.setattr(L, "jiuyan_streak_map", lambda db, d: {"600000": 2})
    monkeypatch.setattr(L, "fetch_daban_lanes", lambda db, d: {"bid": {}})
    holder: dict = {}
    L._prev_context_bundle(None, DATE, ["2026-11-11", "2026-11-12"], "ds", holder)
    assert holder["bctx"] == {"ctx": "2026-11-12"}
    assert holder["market_line"] == "line"
    assert holder["t1_rows"] == {"600000": {"code": "600000"}}
    assert holder["prev_cross"]["state"] == "ok"
    assert holder["streak_map"] == {"600000": 2}
    assert holder["lanes"] == {"bid": {}}
    assert "error" not in holder

    def boom(db, d):
        raise RuntimeError("db down")
    monkeypatch.setattr(L.ABM, "load_board_context", boom)
    holder = {}
    L._prev_context_bundle(None, DATE, ["2026-11-12"], "ds", holder)
    assert holder["error"].startswith("prev_context_bundle_failed:")


def test_parallel_threads_start_before_roster(env, monkeypatch):
    db, calls = env
    import threading
    events: list[str] = []
    ev_mbl, ev_ctx = threading.Event(), threading.Event()
    real_mbl, real_ctx, real_roster = L._mbl_audit_worker, L._prev_context_bundle, L.roster_for

    def mbl(db_, date, holder):
        events.append("mbl_start")
        ev_mbl.set()
        real_mbl(db_, date, holder)

    def ctx(db_, date, prev_dates, ds, holder):
        events.append("ctx_start")
        ev_ctx.set()
        real_ctx(db_, date, prev_dates, ds, holder)

    def roster(db_, date, fetch_missing=True):
        # 线程启动不等于已运行：roster 前两线程必须已进入（Event 同步，防调度 race）
        assert ev_mbl.wait(3), "MBL 线程未先于 roster 进入"
        assert ev_ctx.wait(3), "bundle 线程未先于 roster 进入"
        events.append("roster")
        return real_roster(db_, date, fetch_missing=fetch_missing)

    monkeypatch.setattr(L, "_mbl_audit_worker", mbl)
    monkeypatch.setattr(L, "_prev_context_bundle", ctx)
    monkeypatch.setattr(L, "roster_for", roster)
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"], res
    assert events.index("mbl_start") < events.index("roster")
    assert events.index("ctx_start") < events.index("roster")
    for k in ("roster_s", "prev_ctx_wait_s", "tencent_s", "basis_wait_s",
              "mbl_wait_s", "derive_s", "total_s"):
        assert k in res["timings"], res["timings"]
    # MBL 审计态进 doc corpusState（窗内假件 ok）
    assert any(((d.get("corpusState") or {}).get("mblState") or {}).get("state") == "ok"
               for d in db[L.COLLECTION].docs.values())


def test_mbl_join_budget_parallel_pending(env, monkeypatch):
    db, calls = env
    monkeypatch.setattr(L, "_RUN_BUDGET_S", 0.0)

    def slow_mbl(db_, date, holder):
        time.sleep(0.3)
        holder["state"] = {"state": "ok", "n_rows": 1}
    monkeypatch.setattr(L, "_mbl_audit_worker", slow_mbl)
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"], res
    assert res["timings"]["mbl_wait_s"] < 0.2   # 预算 0 → 不等审计源
    assert any(((d.get("corpusState") or {}).get("mblState") or {}).get("state")
               == "parallel_pending"
               for d in db[L.COLLECTION].docs.values())


def test_push_missing_early_return_has_total_s(env):
    db, calls = env
    db["kpl_live_daily"].docs[DATE]["auctionPush"]["stocks"] = []
    res = L.run(DATE, confirm_budget=True)
    assert res["ok"] and res["skippedReason"] == "auction_push_missing"
    assert res["timings"]["total_s"] >= 0, "早退路径也报全程耗时（review nit）"


def test_dry_run_no_mbl_thread(env, monkeypatch):
    db, calls = env

    def forbidden(*a, **k):
        raise AssertionError("dry-run 不得启动 MBL 采集线程")
    monkeypatch.setattr(L, "_mbl_audit_worker", forbidden)
    res = L.run(DATE, dry_run=True)
    assert res["ok"] and res["dryRun"]
    assert calls == []
    assert db[L.COLLECTION].docs == {}
    assert "mbl_wait_s" not in res["timings"]
