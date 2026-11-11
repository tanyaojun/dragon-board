# -*- coding: utf-8 -*-
"""龙虎榜补齐链测试（B，2026-11-11 用户裁决；21:30 当日 + 07:10 次晨两时点）。

零网络零模型：collect_lhb_facts 探针 / subprocess / 日历全程打桩（AGENTS §1.2-7）。
覆盖：pending 检测（lhbState / legacy 双形状）、探针缺席跳过（零 token）、主榜到达
定向重跑、legacy doc 席位兜底重跑、lhbState doc 席位-only 不重跑（防双烧）、板块 doc
独立板别定向、开关 / dry-run / 子进程失败结构化。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.schedule as S
import backend.operations.theme_leader_baseline as TLB
import backend.analysis.hotlist.jev_lhb_ammo as LHB_AMMO

COL = "hotlist_jev_theme_leader_labels"


class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find(self, query=None, projection=None):
        return [dict(d) for d in self.docs.values()
                if all(d.get(k) == v for k, v in (query or {}).items())]


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


def _doc(date, code, *, board="机器人", kind="leader", main=None, narrative=""):
    d = {"_id": f"{date}:board:{board}" if kind == "sector" else f"{date}:{code}",
         "tradingDate": date, "docKind": kind, "status": "ok",
         "code": None if kind == "sector" else code, "board": board,
         "narrative": narrative}
    if main is not None:
        d["lhbState"] = {"mainAvailable": main, "lineRendered": bool(main)}
    return d


def _facts(*, main=False, seat=False, empty_structured=True):
    return {"ok": bool(main), "list_ok": True, "stock_ok": True,
            "empty_structured": bool(empty_structured and not main),
            "order_sign_count": 11 if empty_structured else 0,
            "groups": ([{"reason": "日涨幅偏离", "stocks": [{"code": "603278"}]}]
                       if main else []),
            "stocks": [],
            "stock_board": ({"603278": {"name": "大业股份", "buy_in": 1e8}}
                            if seat else {}),
            "agency": {}}


RESULT_LINE = S._THEME_LEADER_RESULT_MARKER + json.dumps(
    {"ok": True, "labeled": 2, "tokensUsed": 4321})


@pytest.fixture
def env(monkeypatch):
    db = FakeDb()
    procs: list[list[str]] = []
    monkeypatch.setattr(S.repository_factory, "get_runtime_mongodb_database",
                        lambda: db)
    monkeypatch.setattr(S, "theme_leader_label_enabled", lambda: True)
    monkeypatch.setattr(S, "theme_leader_lhb_backfill_enabled", lambda: True)
    monkeypatch.setattr(S, "is_trading_day_cached", lambda d: (True, "test"))
    monkeypatch.setattr(TLB, "trading_dates",
                        lambda db, a, b: ["2026-11-10", "2026-11-11"])
    monkeypatch.setattr(S, "_LHB_BACKFILL_PROBE_GAP_S", 0.0)

    def fake_run(cmd, **kw):
        procs.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=RESULT_LINE + "\n", stderr="")

    monkeypatch.setattr(S.subprocess, "run", fake_run)
    return db, procs


def _probe(monkeypatch, facts_by_day):
    calls: list[str] = []

    def fake_collect(day, **kw):
        calls.append(day)
        return facts_by_day.get(day, _facts())

    monkeypatch.setattr(LHB_AMMO, "collect_lhb_facts", fake_collect)
    return calls


def test_no_pending_no_probe_no_rerun(env, monkeypatch):
    db, procs = env
    db[COL].docs["a"] = _doc("2026-11-11", "603278", main=True)
    calls = _probe(monkeypatch, {})
    out = S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert out["ok"] and not procs and not calls, "无 pending 不探针不重跑（零 HTTP 零 token）"
    assert all(d["action"] == "skip" and d["pending"] == 0 for d in out["days"])


def test_main_arrives_targeted_rerun(env, monkeypatch):
    db, procs = env
    col = db[COL]
    col.docs["a"] = _doc("2026-11-11", "603278", main=False)
    col.docs["b"] = _doc("2026-11-11", "600000", board="化工", main=True)
    calls = _probe(monkeypatch, {"2026-11-11": _facts(main=True)})
    out = S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert len(procs) == 1, "只重跑 pending doc（定向 --codes），不全日盲重跑"
    cmd = procs[0]
    assert "--force" in cmd and "--confirm-budget" in cmd
    assert cmd[cmd.index("--date") + 1] == "2026-11-11"
    assert cmd[cmd.index("--codes") + 1] == "603278"
    day = next(d for d in out["days"] if d["date"] == "2026-11-11")
    assert day["action"] == "rerun" and day["runs"][0]["tokensUsed"] == 4321
    assert out["tokensUsed"] == 4321
    assert calls == ["2026-11-11"], "无 pending 日不探针"


def test_probe_absent_skips_without_tokens(env, monkeypatch):
    db, procs = env
    db[COL].docs["a"] = _doc("2026-11-11", "603278", main=False)
    _probe(monkeypatch, {})   # 默认 = 结构化空态（榜单未生成）
    out = S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert not procs, "探针缺席 → 零 token 跳过（等下一时点）"
    day = out["days"][-1]
    assert day["action"] == "skip" and day["skipReason"] == "lhb_data_not_available"
    assert day["probe"]["emptyStructured"] is True
    assert out["ok"]


def test_legacy_doc_seat_only_reruns(env, monkeypatch):
    """legacy doc（无 lhbState、无龙虎榜行）：席位/机构榜到达也是新语料（C 兜底行）→ 重跑。"""
    db, procs = env
    db[COL].docs["a"] = _doc("2026-11-10", "603278", narrative="涨停 46 家\n结构：…")
    _probe(monkeypatch, {"2026-11-10": _facts(seat=True)})
    out = S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert len(procs) == 1 and "--codes" in procs[0]
    day = next(d for d in out["days"] if d["date"] == "2026-11-10")
    assert day["action"] == "rerun" and day["pendingLegacy"] == 1


def test_state_doc_seat_only_waits_for_main(env, monkeypatch):
    """已有 lhbState 的 doc（C 兜底行可能已出）：席位-only 增量不触发重跑，
    等主榜到达一次补齐——防双烧 token。"""
    db, procs = env
    db[COL].docs["a"] = _doc("2026-11-11", "603278", main=False)
    _probe(monkeypatch, {"2026-11-11": _facts(seat=True)})
    out = S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert not procs
    assert out["days"][-1]["skipReason"] == "lhb_data_not_available"


def test_legacy_doc_with_lhb_line_not_pending(env, monkeypatch):
    db, procs = env
    db[COL].docs["a"] = _doc(
        "2026-11-10", "603278",
        narrative="龙虎榜：当日全市场上榜 96 只，本叙事相关个股 0 只上榜")
    calls = _probe(monkeypatch, {})
    S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert not procs and not calls


def test_sector_only_pending_targets_boards(env, monkeypatch):
    db, procs = env
    db[COL].docs["s"] = _doc("2026-11-11", None, board="机器人", kind="sector",
                             main=False)
    _probe(monkeypatch, {"2026-11-11": _facts(main=True)})
    S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert len(procs) == 1
    assert procs[0][procs[0].index("--boards") + 1] == "机器人"
    assert "--codes" not in procs[0]


def test_mixed_pending_two_targeted_runs(env, monkeypatch):
    """pending 龙头 + 独立板别 pending 板块 doc → 两次定向子进程（codes/boards 不交叠）。"""
    db, procs = env
    col = db[COL]
    col.docs["l"] = _doc("2026-11-11", "603278", board="机器人", main=False)
    col.docs["s"] = _doc("2026-11-11", None, board="化工", kind="sector", main=False)
    _probe(monkeypatch, {"2026-11-11": _facts(main=True)})
    S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert len(procs) == 2
    assert procs[0][procs[0].index("--codes") + 1] == "603278"
    assert procs[1][procs[1].index("--boards") + 1] == "化工"


def test_disabled_and_dry_run(env, monkeypatch):
    db, procs = env
    db[COL].docs["a"] = _doc("2026-11-11", "603278", main=False)
    _probe(monkeypatch, {"2026-11-11": _facts(main=True)})
    out = S.run_theme_leader_lhb_backfill_once("2026-11-11", dry_run=True)
    assert not procs and out["days"][-1]["action"] == "would_rerun"
    monkeypatch.setattr(S, "theme_leader_lhb_backfill_enabled", lambda: False)
    out2 = S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert out2["skipped"] and out2["reason"] == "disabled"


def test_rerun_failure_structured(env, monkeypatch):
    db, procs = env
    db[COL].docs["a"] = _doc("2026-11-11", "603278", main=False)
    _probe(monkeypatch, {"2026-11-11": _facts(main=True)})
    monkeypatch.setattr(S.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=1, stdout="", stderr="boom"))
    out = S.run_theme_leader_lhb_backfill_once("2026-11-11")
    day = out["days"][-1]
    assert day["runs"][0]["ok"] is False and "boom" in day["runs"][0]["error"]
    assert out["ok"] is False, "重跑失败要让调度感知（下一时点自愈）"


def test_today_appended_when_calendar_lags(env, monkeypatch):
    """韭研日轴滞后（今日 final 未落）：今日是交易日则并入扫描窗，当日 pending 不漏。"""
    db, procs = env
    monkeypatch.setattr(TLB, "trading_dates", lambda db, a, b: ["2026-11-10"])
    db[COL].docs["a"] = _doc("2026-11-11", "603278", main=False)
    _probe(monkeypatch, {"2026-11-11": _facts(main=True)})
    out = S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert any(d["date"] == "2026-11-11" for d in out["days"])
    assert len(procs) == 1


def test_degraded_doc_pending_unconditional(env, monkeypatch):
    """degraded 档无条件 pending（修复路径）：补齐自身失败把 ok 档写成 degraded 后
    不得永久搁浅——不受 LHB 探针门控，下一时点通道恢复即重标。"""
    db, procs = env
    d = _doc("2026-11-11", "603278", main=True)
    d["status"] = "degraded"
    db[COL].docs["a"] = d
    _probe(monkeypatch, {})   # 探针缺席（主榜未生成）
    out = S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert len(procs) == 1, "degraded 档修复不受 LHB 探针门控"
    day = out["days"][-1]
    assert day["action"] == "rerun" and day["pending"] == 1


def test_channel_abort_stops_remaining_days(env, monkeypatch):
    """通道中止（零 usage 快速中止已把首 2 档写 degraded）→ 本次调用不再发后续
    子进程（避免逐日扩散降级），剩余日结构化跳过，下一时点自愈。"""
    db, procs = env
    col = db[COL]
    col.docs["a"] = _doc("2026-11-10", "603278", main=False)
    col.docs["b"] = _doc("2026-11-11", "600000", main=False)
    _probe(monkeypatch, {"2026-11-10": _facts(main=True),
                         "2026-11-11": _facts(main=True)})
    abort_line = S._THEME_LEADER_RESULT_MARKER + json.dumps(
        {"ok": False, "labeled": 2, "tokensUsed": 0, "aborted": "channel_unreachable"})

    def abort_run(cmd, **kw):
        procs.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=abort_line + "\n", stderr="")

    monkeypatch.setattr(S.subprocess, "run", abort_run)
    out = S.run_theme_leader_lhb_backfill_once("2026-11-11")
    assert len(procs) == 1, "通道中止后不发后续子进程"
    assert out["ok"] is False
    d10 = next(d for d in out["days"] if d["date"] == "2026-11-10")
    assert d10["runs"][0]["aborted"] == "channel_unreachable"
    d11 = next(d for d in out["days"] if d["date"] == "2026-11-11")
    assert d11["action"] == "skip" and d11["skipReason"] == "channel_unreachable_abort"
