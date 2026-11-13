# -*- coding: utf-8 -*-
"""竞价龙头板块映射测试（2026-11-13 用户裁决：推送概念→韭研板块名；零网络零 jev）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import auction_board_map as ABM

DATE = "2026-11-13"


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


def _ctx(stocks_map, nodes=None, groups=()):
    db = FakeDb()
    db["jiuyan_industry_stocks"] = FakeCol({
        code: {"_id": code, "name": name, "stocks": [{"code": c} for c in codes]}
        for code, (name, codes) in stocks_map.items()})
    db["jiuyan_ai_industry"] = FakeCol({
        code: {"_id": code, "code": code, "name": name, "hot": hot}
        for code, (name, hot) in (nodes or {}).items()})
    db["jiuyan_action"] = FakeCol({
        f"{DATE}:final": {"_id": f"{DATE}:final",
                          "fields": [{"name": g} for g in groups]}})
    return ABM.load_board_context(db, DATE)


def test_single_candidate_wins():
    ctx = _ctx({"0106": ("寒潮", ["603366"])}, {"0106": ("寒潮", 0.29)})
    r = ABM.resolve_leader_board(ctx, "603366", "光伏")
    assert r["board"] == "寒潮" and r["boardSource"] == "jiuyan_industry"
    assert r["pickedBy"] == "single" and r["pushBoard"] == "光伏"


def test_push_bridge_beats_hot():
    """冰雪产业（推送）↔冰雪经济（韭研）后缀桥优先于 hot 更高的无人驾驶场景。"""
    ctx = _ctx({"0091": ("冰雪经济", ["601188"]), "0099": ("无人驾驶场景", ["601188"])},
               {"0091": ("冰雪经济", -0.6), "0099": ("无人驾驶场景", 0.65)})
    r = ABM.resolve_leader_board(ctx, "601188", "冰雪产业")
    assert r["board"] == "冰雪经济" and r["pickedBy"] == "push_bridge"


def test_action_group_when_no_bridge():
    ctx = _ctx({"0067": ("海洋经济", ["002086"]), "0102": ("水产养殖", ["002086"])},
               {"0067": ("海洋经济", -0.74), "0102": ("水产养殖", -1.21)},
               groups=("水产养殖",))
    r = ABM.resolve_leader_board(ctx, "002086", "羊年")
    assert r["board"] == "水产养殖" and r["pickedBy"] == "action_group"


def test_hot_desc_then_code_tiebreak():
    ctx = _ctx({"0067": ("海洋经济", ["002086"]), "0102": ("水产养殖", ["002086"])},
               {"0067": ("海洋经济", -0.74), "0102": ("水产养殖", -1.21)})
    r = ABM.resolve_leader_board(ctx, "002086", "羊年")
    assert r["board"] == "海洋经济" and r["pickedBy"] == "hot"
    ctx2 = _ctx({"0067": ("海洋经济", ["002086"]), "0102": ("水产养殖", ["002086"])},
                {"0067": ("海洋经济", None), "0102": ("水产养殖", None)})
    r2 = ABM.resolve_leader_board(ctx2, "002086", None)
    assert r2["board"] == "海洋经济" and r2["pickedBy"] == "hot"   # code 升序兜底


def test_no_membership_falls_back_push_concept():
    ctx = _ctx({"0106": ("寒潮", ["603366"])})
    r = ABM.resolve_leader_board(ctx, "002172", "羊年")
    assert r["board"] == "羊年" and r["boardSource"] == "push_concept"
    assert r["pickedBy"] == "push_fallback" and r["candidates"] == []
    r2 = ABM.resolve_leader_board(ctx, "002172", None)
    assert r2["board"] is None and r2["boardSource"] == "push_concept"