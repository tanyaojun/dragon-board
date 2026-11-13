# -*- coding: utf-8 -*-
"""竞价龙头板块映射测试（2026-11-13 用户裁决二次修订：T−1 涨停分组；零网络零 jev）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import auction_board_map as ABM

DATE = "2026-11-13"
PREV = "2026-11-12"


class FakeCol:
    def __init__(self, docs=None):
        self.docs = docs or {}

    def find(self, query=None, projection=None):
        return list(self.docs.values())

    def find_one(self, query=None, projection=None):
        d = self.docs.get((query or {}).get("_id"))
        return dict(d) if d else None


class FakeDb:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())

    def __setitem__(self, name, col):
        self.cols[name] = col


def _ctx(groups, prev=PREV):
    """groups: {组名: [codes]}；prev=None 模拟 T−1 final 缺席。"""
    db = FakeDb()
    if prev is not None:
        db["jiuyan_action"] = FakeCol({
            f"{prev}:final": {"_id": f"{prev}:final",
                              "fields": [{"name": n, "stocks": [{"code": c} for c in cs]}
                                         for n, cs in groups.items()]}})
    return ABM.load_board_context(db, prev)


def test_single_t1_group_wins():
    ctx = _ctx({"光伏": ["603366"], "机器人": ["603135"]})
    r = ABM.resolve_leader_board(ctx, "603366", "光伏")
    assert r["board"] == "光伏" and r["boardSource"] == "jiuyan_action_t1"
    assert r["pickedBy"] == "t1_group" and r["t1Final"] is True
    assert r["candidates"] == [{"name": "光伏", "n": 1}]


def test_push_bridge_beats_group_size():
    ctx = _ctx({"大消费": ["601188", "600327", "002086"], "冰雪经济": ["601188"]})
    r = ABM.resolve_leader_board(ctx, "601188", "冰雪产业")
    assert r["board"] == "冰雪经济" and r["pickedBy"] == "push_bridge"


def test_group_size_desc_then_name_tiebreak():
    ctx = _ctx({"大消费": ["002086", "600327", "601188"], "医疗医药": ["002086"]})
    r = ABM.resolve_leader_board(ctx, "002086", "羊年")
    assert r["board"] == "大消费" and r["pickedBy"] == "group_size"
    ctx2 = _ctx({"B组": ["002086"], "A组": ["002086"]})
    r2 = ABM.resolve_leader_board(ctx2, "002086", None)
    assert r2["board"] == "A组" and r2["pickedBy"] == "group_size"   # 组名升序兜底


def test_no_hit_falls_back_push_concept():
    ctx = _ctx({"光伏": ["603366"]})
    r = ABM.resolve_leader_board(ctx, "002172", "羊年")
    assert r["board"] == "羊年" and r["boardSource"] == "push_concept"
    assert r["pickedBy"] == "push_fallback" and r["candidates"] == []
    r2 = ABM.resolve_leader_board(ctx, "002172", None)
    assert r2["board"] is None and r2["boardSource"] == "push_concept"


def test_t1_final_missing_fail_visible():
    ctx = _ctx({"光伏": ["603366"]}, prev=None)
    assert ctx["t1Final"] is False
    r = ABM.resolve_leader_board(ctx, "603366", "光伏")
    assert r["board"] == "光伏" and r["boardSource"] == "push_concept"
    assert r["pickedBy"] == "t1_final_missing" and r["t1Final"] is False