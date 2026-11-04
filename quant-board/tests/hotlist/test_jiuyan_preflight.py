# -*- coding: utf-8 -*-
"""盘后链预检测试（2026-11-04 用户裁决）：jiuyan 远端名单数 vs 落库一致性。

背景：韭研异动解析盘后持续补名单，15:35 采集版可能不完整（当日实测 44 只、
晚间 136）——名单不完整不得打标。17:00 链首 run_jiuyan_preflight：
远端探针（count-pc，零 jev token）对账落库 counts.all；不一致先幂等重采补齐，
补齐仍失败 → ok=False（链 stoppedAt=jiuyanPreflight 拦停）。

锁定口径（全 monkeypatch/fake，零真实 jev/韭研调用，AGENTS §1.2-7）：
- 一致（stored >= remote）→ checked=True、零重采；
- 落库缺失/偏少 → 重采 1 次 + 复核通过 → ok=True、repairs 有账；
- 补齐后仍偏少 → ok=False、jiuyan_preflight_inconsistent（重试上限 2 次）；
- 探针失败 → ok=True + checked=False 结构化 warning（不拦备份链）；
- 重采失败 → ok=False，repairs 留 error 账。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import schedule as sched

DATE = "2026-11-04"


class _FakeActionCol:
    """落库行数从 state['dbAll'] 实时读：重采成功后由 fake_collect 推进状态。"""

    def __init__(self, state):
        self.state = state

    def find_one(self, query, projection=None):
        if self.state["dbAll"] is None:
            return None
        return {"_id": f"{DATE}:final", "counts": {"all": self.state["dbAll"]}}


class _FakeDb:
    def __init__(self, state):
        self.state = state

    def __getitem__(self, name):
        assert name == "jiuyan_action", name
        return _FakeActionCol(self.state)


@pytest.fixture()
def patch_env(monkeypatch):
    """可变状态注入：测试体内用 install(...) 调整场景。"""
    state: dict = {"dbAll": 136, "probe": {"ok": True, "all": 136},
                   "recollect": {"ok": True, "stocks": 136}, "probe_fail": False,
                   "recollect_calls": 0}

    def install(**kw):
        state.update(kw)

    def fake_resolve_auth(date=None):
        if state["probe_fail"]:
            return {"ok": False, "error": "auth down"}
        return {"ok": True, "session": "s", "token": "t", "timestamp": "x"}

    def fake_fetch_count(date, **kw):
        return dict(state["probe"])

    def fake_collect(date, kind, db=None):
        state["recollect_calls"] += 1
        if state["recollect"].get("ok"):
            # collect_and_store 成功 → 落库行数推进到重采结果
            state["dbAll"] = state["recollect"].get("stocks")
        return dict(state["recollect"])

    monkeypatch.setattr(sched.repository_factory, "get_runtime_mongodb_database",
                        lambda: _FakeDb(state))
    monkeypatch.setattr("backend.operations.jiuyan_auth.resolve_auth", fake_resolve_auth)
    monkeypatch.setattr("backend.operations.jiuyan_fetch.fetch_count", fake_fetch_count)
    monkeypatch.setattr("backend.operations.jiuyan_collect.collect_and_store", fake_collect)
    return install, state


def test_preflight_passes_when_stored_matches_remote(patch_env):
    install, state = patch_env
    install(dbAll=136, probe={"ok": True, "all": 136})
    out = sched.run_jiuyan_preflight(DATE)
    assert out["ok"] is True and out["checked"] is True
    assert out["repairs"] == [] and out["remoteCountsAll"] == 136
    assert state["recollect_calls"] == 0


def test_preflight_repairs_when_stored_behind_remote(patch_env):
    """11-04 事故形态：落库 44、远端 136 → 重采补齐后复核通过。"""
    install, state = patch_env
    install(dbAll=44, probe={"ok": True, "all": 136}, recollect={"ok": True, "stocks": 136})
    out = sched.run_jiuyan_preflight(DATE)
    assert out["ok"] is True and out["checked"] is True
    assert state["recollect_calls"] == 1
    assert len(out["repairs"]) == 1 and out["repairs"][0]["before"] == 44
    assert out["storedCountsAll"] == 136 and out["remoteCountsAll"] == 136


def test_preflight_stops_when_repair_cannot_close_gap(patch_env):
    """重采后仍偏少（源端/解析层问题）→ ok=False 拦停，两次尝试都有账。"""
    install, state = patch_env
    install(dbAll=44, probe={"ok": True, "all": 136}, recollect={"ok": True, "stocks": 90})
    out = sched.run_jiuyan_preflight(DATE)
    assert out["ok"] is False
    assert out["error"]["code"] == "jiuyan_preflight_inconsistent"
    assert state["recollect_calls"] == 2  # 重试上限
    assert all(r["ok"] for r in out["repairs"])  # 重采本身成功但对不齐


def test_preflight_fails_when_recollect_errors(patch_env):
    install, _ = patch_env
    install(dbAll=None, probe={"ok": True, "all": 136},
            recollect={"ok": False, "error": {"code": "quota", "message": "errCode=9"}})
    out = sched.run_jiuyan_preflight(DATE)
    assert out["ok"] is False
    assert out["repairs"][0]["error"]["code"] == "quota"


def test_preflight_continues_with_warning_when_probe_fails(patch_env):
    """远端不可知 ≠ 确认不一致：不拦备份链，但 checked=False 结构化暴露。"""
    install, state = patch_env
    install(dbAll=44, probe_fail=True)
    out = sched.run_jiuyan_preflight(DATE)
    assert out["ok"] is True and out["checked"] is False
    assert out["warning"]["code"] == "jiuyan_preflight_probe_failed"
    assert state["recollect_calls"] == 0


def test_preflight_missing_doc_counts_as_inconsistent(patch_env):
    """final 文档缺失（old=None）→ 视为不一致，重采补齐。"""
    install, state = patch_env
    install(dbAll=None, probe={"ok": True, "all": 136})
    out = sched.run_jiuyan_preflight(DATE)
    assert out["ok"] is True and state["recollect_calls"] == 1


def test_preflight_probe_self_heals_on_auth_failed(patch_env, monkeypatch):
    """登录失效（authFailed）→ 强制重登重铸自愈重试一次（同调度支线口径），不拦链。"""
    import backend.operations.jiuyan_auth as ja
    calls = {"resolve": 0, "fetch": 0}

    def fake_resolve(*, date=None, force_refresh=False):
        calls["resolve"] += 1
        return {"ok": True, "session": f"s{calls['resolve']}", "token": "t", "timestamp": "x"}

    def fake_fetch(date, **kw):
        calls["fetch"] += 1
        if calls["fetch"] == 1:
            return {"ok": False, "authFailed": True, "error": "登录失效(登录失效)"}
        return {"ok": True, "all": 136}

    monkeypatch.setattr(ja, "resolve_auth", fake_resolve)
    monkeypatch.setattr("backend.operations.jiuyan_fetch.fetch_count", fake_fetch)
    out = sched.run_jiuyan_preflight(DATE)
    assert out["ok"] is True and out["checked"] is True
    assert calls["resolve"] == 2 and calls["fetch"] == 2  # 首试失败 → 自愈重试
    assert out["repairs"] == []


def test_preflight_probe_payload_missing_all_does_not_repair(patch_env):
    """review P1-①：探针 ok 但载荷缺 all（parse 层不伪造 0）→ 远端不可知，
    不空转重采、不误拦停（同探针失败口径 ok=True+warning）。"""
    install, state = patch_env
    install(dbAll=44, probe={"ok": True, "all": None})
    out = sched.run_jiuyan_preflight(DATE)
    assert out["ok"] is True and out["checked"] is False
    assert out["warning"]["code"] == "jiuyan_preflight_probe_incomplete"
    assert state["recollect_calls"] == 0


def test_preflight_repair_verify_unknown_continues_with_warning(patch_env, monkeypatch):
    """review P1-②：补齐后复核探针失败 ≠ 确认不一致 → ok=True 不拦链，
    warning 独立 code，repairs 留账（重采本身已按当时源端数据落库）。"""
    install, state = patch_env
    install(dbAll=44, probe={"ok": True, "all": 136}, recollect={"ok": True, "stocks": 136})
    import backend.operations.jiuyan_auth as ja

    calls = {"fetch": 0}

    def fake_resolve(*, date=None, force_refresh=False):
        return {"ok": True, "session": "s", "token": "t", "timestamp": "x"}

    def fake_fetch(date, **kw):
        calls["fetch"] += 1
        if calls["fetch"] >= 2:  # 首探通过、补齐后复核失败（errCode=9 配额耗尽等）
            return {"ok": False, "error": {"code": 9, "message": "查阅配额耗尽"}}
        return {"ok": True, "all": 136}

    monkeypatch.setattr(ja, "resolve_auth", fake_resolve)
    monkeypatch.setattr("backend.operations.jiuyan_fetch.fetch_count", fake_fetch)
    out = sched.run_jiuyan_preflight(DATE)
    assert out["ok"] is True
    assert out["warning"]["code"] == "jiuyan_preflight_repair_verify_unknown"
    assert state["recollect_calls"] == 1 and len(out["repairs"]) == 1
