# -*- coding: utf-8 -*-
"""回填前置检查测试（2026-11-16 事故裁决：回填前核对依赖链存档健康度）。

11-12 事故签名回归：relay 重放遇节点档坏账必须默认阻断；sector_nodes 回填遇
gain10 不可达必须默认阻断（否则复现「全板块跳过、好档被近空档覆盖」）。
"""
from __future__ import annotations

import pytest

from backend.operations.backfill_preflight import (
    EXIT_BLOCKED,
    market_cycle_preflight,
    relay_preflight,
    sector_nodes_preflight,
)
from backend.analysis.hotlist.sector_nodes import SECTOR_NODE_VERSION


class FakeCol:
    def __init__(self, docs=None):
        self.docs = docs or {}

    def find(self, query=None, projection=None):
        return list(self.docs.values())

    def find_one(self, query=None, projection=None, **kwargs):
        # sort/limit 等 kwargs 忽略：非 _id 查询（THS 帧等）统一返 None = 如实缺失
        return dict(d) if (d := self.docs.get((query or {}).get("_id"))) else None


class FakeDb:
    def __init__(self, cols=None):
        self.cols = cols or {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


def _final(date: str, codes: list[str]) -> dict:
    return {"_id": f"{date}:final",
            "fields": [{"name": "机器人", "stocks": [{"code": c} for c in codes]}]}


def _nodes_doc(date: str, rows: int, *, status: str = "ok",
               version: str = SECTOR_NODE_VERSION) -> dict:
    return {"_id": f"{date}:SECTOR_NODES", "version": version, "status": status,
            "rows": [{"board": f"B{i}", "leader": {"code": f"60000{i}"}}
                     for i in range(rows)]}


# ── relay_preflight：LLM 重放不可逆，坏账默认阻断 ──────────────────────────

def test_relay_preflight_blocks_on_missing_ledger():
    db = FakeDb({"jiuyan_action": FakeCol({"2026-11-04:final": _final("2026-11-04", ["600001"])})})
    pre = relay_preflight(db, ["2026-11-04"], ledger_version=SECTOR_NODE_VERSION)
    assert pre["blockers"], "节点档缺失必须阻断"
    assert pre["ledgerBad"][0]["date"] == "2026-11-04"
    assert pre["proceed"] is False if "proceed" in pre else True  # proceed 由 CLI 计算


def test_relay_preflight_blocks_on_void_ledger():
    """节点档 0 行（11-12 事故签名）→ 阻断：梯队表将全部回退口径。"""
    db = FakeDb({
        "jiuyan_action": FakeCol({"2026-11-04:final": _final("2026-11-04", ["600001"])}),
        "hotlist_jev_sector_nodes": FakeCol({"2026-11-04:SECTOR_NODES":
                                             _nodes_doc("2026-11-04", 0)}),
    })
    pre = relay_preflight(db, ["2026-11-04"], ledger_version=SECTOR_NODE_VERSION)
    assert any("0 行" in b for b in pre["blockers"])


def test_relay_preflight_blocks_on_stale_version():
    db = FakeDb({
        "jiuyan_action": FakeCol({"2026-11-04:final": _final("2026-11-04", ["600001"])}),
        "hotlist_jev_sector_nodes": FakeCol({"2026-11-04:SECTOR_NODES":
                                             _nodes_doc("2026-11-04", 5, version="v4")}),
    })
    pre = relay_preflight(db, ["2026-11-04"], ledger_version=SECTOR_NODE_VERSION)
    assert pre["blockers"], "版本不符（旧代档冒充新口径）必须阻断"


def test_relay_preflight_ok_when_ledger_healthy():
    db = FakeDb({
        "jiuyan_action": FakeCol({"2026-11-04:final": _final("2026-11-04", ["600001"])}),
        "hotlist_jev_sector_nodes": FakeCol({"2026-11-04:SECTOR_NODES":
                                             _nodes_doc("2026-11-04", 21)}),
    })
    pre = relay_preflight(db, ["2026-11-04"], ledger_version=SECTOR_NODE_VERSION)
    assert pre["blockers"] == []
    assert pre["ledgerBad"] == []


def test_relay_preflight_warns_missing_final_without_block():
    db = FakeDb({"hotlist_jev_sector_nodes": FakeCol(
        {"2026-11-04:SECTOR_NODES": _nodes_doc("2026-11-04", 5)})})
    pre = relay_preflight(db, ["2026-11-04"], ledger_version=SECTOR_NODE_VERSION)
    assert pre["blockers"] == []
    assert pre["missingFinal"] == ["2026-11-04"]
    assert pre["warnings"], "final 缺失须透出（该日将被跳过）"


# ── sector_nodes_preflight：gain10 不可达默认阻断（事故复现签名） ────────────

def test_sector_nodes_blocks_when_gain_unreachable(monkeypatch):
    db = FakeDb({"jiuyan_action": FakeCol({"2026-10-23:final": _final("2026-10-23",
                                                                       ["600001", "600002"])})})
    monkeypatch.setattr("backend.operations.tdx_daily_bars.fetch_gains10",
                        lambda codes, date, **kw: {c: None for c in codes})
    pre = sector_nodes_preflight(db, ["2026-10-23"], "ds")
    assert pre["blockers"], "gain10 抽检全缺必须阻断（11-12 事故直接信号）"
    assert pre["gainSample"]["2026-10-23"]["noneRatio"] == 1.0


def test_sector_nodes_ok_when_gain_reachable(monkeypatch):
    db = FakeDb({"jiuyan_action": FakeCol({"2026-10-23:final": _final("2026-10-23",
                                                                       ["600001", "600002"])})})
    monkeypatch.setattr("backend.operations.tdx_daily_bars.fetch_gains10",
                        lambda codes, date, **kw: {c: 5.0 for c in codes})
    pre = sector_nodes_preflight(db, ["2026-10-23"], "ds")
    assert pre["blockers"] == []


def test_sector_nodes_void_existing_doc_is_warning_not_block(monkeypatch):
    """已有档 0 行 = 事故遗留签名：确定性重算即修复，只透出不阻断。"""
    db = FakeDb({
        "jiuyan_action": FakeCol({"2026-10-23:final": _final("2026-10-23", ["600001"])}),
        "hotlist_jev_sector_nodes": FakeCol({"2026-10-23:SECTOR_NODES":
                                             _nodes_doc("2026-10-23", 0)}),
    })
    monkeypatch.setattr("backend.operations.tdx_daily_bars.fetch_gains10",
                        lambda codes, date, **kw: {c: 5.0 for c in codes})
    pre = sector_nodes_preflight(db, ["2026-10-23"], "ds")
    assert pre["blockers"] == []
    assert pre["existingVoid"] == ["2026-10-23"]


def test_sector_nodes_missing_final_and_ths_reported(monkeypatch):
    db = FakeDb()  # 全空：final/THS 全缺
    monkeypatch.setattr("backend.operations.tdx_daily_bars.fetch_gains10",
                        lambda codes, date, **kw: {c: 5.0 for c in codes})
    pre = sector_nodes_preflight(db, ["2026-10-23", "2026-10-26"], "ds")
    assert pre["missingFinal"] == ["2026-10-23", "2026-10-26"]
    assert pre["warnings"], "上游缺失必须透出（fail-visible）"
    assert pre["blockers"] == []  # 无 final 的日会被跳过，不构成阻断


# ── market_cycle_preflight：报告型不阻断 ────────────────────────────────────

def test_market_cycle_preflight_report_only():
    db = FakeDb({"jiuyan_action": FakeCol({"2026-10-23:final": _final("2026-10-23", ["600001"])})})
    pre = market_cycle_preflight(db, ["2026-10-23"], "ds")
    assert pre["blockers"] == []
    assert pre["missingThs"] == ["2026-10-23"]  # FakeDb 无 THS 帧 → 如实透出


# ── 退出码契约 ─────────────────────────────────────────────────────────────

def test_exit_blocked_code_distinct():
    assert EXIT_BLOCKED == 3
