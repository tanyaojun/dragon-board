# -*- coding: utf-8 -*-
"""龙一台账读口与锚定（2026-11-09 三链合一 v5.1，评审 P1-2 覆盖缺口）。

钉住四件事：
1. `ledger_leaders` 三态门：档缺失 / 非 ok / 版本不符 → None（消费方 fail-visible）；
2. `reanchor_dragons`：龙一重锚（同行复用保区间高度 / 断板反包合成行 ledgerUnsealed /
   龙二三补位重编 role）；节点档缺板块原样；
3. `anchor_rows_to_ledger`：dropped（无档板块行 + 同板块 code 不一致行逐行留痕）/
   missing（档龙头无事实行）/ 未锚定（ledger=None）；
4. `_collapse_segment_rows`：main 轨优先折叠单龙。

全部零 DB 零 jev（硬红线 §1.2-7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist.sector_nodes import SECTOR_NODE_VERSION
from backend.operations.sector_nodes import (
    _collapse_segment_rows,
    anchor_rows_to_ledger,
    ledger_leaders,
    reanchor_dragons,
)


class _FakeCol:
    def __init__(self, docs):
        self._docs = docs

    def find_one(self, query, projection=None):
        want = query.get("_id")
        for d in self._docs:
            if d.get("_id") == want:
                return d
        return None

    def find(self, query, projection=None):
        return list(self._docs)


class _FakeDb:
    def __init__(self, docs):
        self._col = _FakeCol(docs)

    def __getitem__(self, name):
        if name == "hotlist_jev_sector_nodes":
            return self._col
        raise KeyError(name)


def _node_doc(date="2026-11-09", *, version=SECTOR_NODE_VERSION, status="ok",
              rows=None):
    return {"_id": f"{date}:SECTOR_NODES", "tradingDate": date,
            "version": version, "status": status,
            "rows": rows if rows is not None else _ledger_rows()}


def _ledger_rows():
    return [
        {"board": "商业航天", "node": "mainline",
         "leader": {"code": "002565", "name": "顺灏股份", "streak": 1,
                    "time": "09:30:06", "gain10": 39.42,
                    "leaderSealedToday": True, "segment": "main"},
         "count": 11, "prevCount": 0},
        {"board": "冰雪经济", "node": "brewing",
         "leader": {"code": "601188", "name": "龙江交通", "streak": 2,
                    "time": "10:05:36", "gain10": 39.2,
                    "leaderSealedToday": True, "segment": "main"},
         "count": 5, "prevCount": 0},
    ]


# ── 1. ledger_leaders 三态门 ──

def test_ledger_leaders_missing_doc_returns_none():
    assert ledger_leaders(_FakeDb([]), "2026-11-09") is None


def test_ledger_leaders_degraded_status_returns_none():
    db = _FakeDb([_node_doc(status="degraded")])
    assert ledger_leaders(db, "2026-11-09") is None


def test_ledger_leaders_version_mismatch_returns_none():
    db = _FakeDb([_node_doc(version="v4")])
    assert ledger_leaders(db, "2026-11-09") is None


def test_ledger_leaders_ok_returns_board_map_with_facts():
    out = ledger_leaders(_FakeDb([_node_doc()]), "2026-11-09")
    assert set(out) == {"商业航天", "冰雪经济"}
    lead = out["商业航天"]
    assert lead["code"] == "002565"
    assert lead["gain10"] == 39.42 and lead["segment"] == "main"
    assert lead["leaderSealedToday"] is True


def test_ledger_leaders_skips_rows_without_leader():
    rows = _ledger_rows() + [{"board": "光伏", "node": "ice", "leader": None}]
    out = ledger_leaders(_FakeDb([_node_doc(rows=rows)]), "2026-11-09")
    assert "光伏" not in out


# ── 2. reanchor_dragons ──

def _dragon_row(code, name, boards=2, days=2, streak=2, time="09:41:00", role=None):
    return {"role": role or "龙一", "code": code, "name": name,
            "boards": boards, "days": days, "streak": streak, "time": time}


def test_reanchor_moves_same_row_to_leader_slot_and_keeps_height():
    rows = [_dragon_row("001316", "润贝航科", boards=2, days=2),
            _dragon_row("002565", "顺灏股份", boards=4, days=8, streak=1),
            _dragon_row("300001", "西部材料", boards=1)]
    out = reanchor_dragons({"商业航天": rows}, {"商业航天": {
        "code": "002565", "name": "顺灏股份", "streak": 1,
        "leaderSealedToday": True}})
    anchored = out["商业航天"]
    assert [r["role"] for r in anchored] == ["龙一", "龙二", "龙三"]
    assert anchored[0]["code"] == "002565"
    assert anchored[0]["boards"] == 4   # 原行复用，区间高度展示保留
    assert [r["code"] for r in anchored[1:]] == ["001316", "300001"]


def test_reanchor_synthesizes_unsealed_leader_row():
    rows = [_dragon_row("001316", "润贝航科", boards=2, days=2)]
    out = reanchor_dragons({"商业航天": rows}, {"商业航天": {
        "code": "002565", "name": "顺灏股份", "streak": None,
        "time": None, "leaderSealedToday": False}})
    anchored = out["商业航天"]
    assert anchored[0]["code"] == "002565"
    assert anchored[0]["ledgerUnsealed"] is True
    assert anchored[0]["boards"] is None   # 如实缺位，不伪装首板
    assert [r["role"] for r in anchored] == ["龙一", "龙二"]


def test_reanchor_marks_unsealed_when_same_row_has_no_height():
    rows = [{"role": "龙一", "code": "002565", "name": "顺灏股份",
             "boards": None, "days": None, "streak": None, "time": "09:30"}]
    out = reanchor_dragons({"商业航天": rows}, {"商业航天": {
        "code": "002565", "name": "顺灏股份", "streak": None,
        "leaderSealedToday": False}})
    assert out["商业航天"][0]["ledgerUnsealed"] is True


def test_reanchor_leaves_unknown_board_as_is():
    rows = [_dragon_row("001316", "润贝航科")]
    out = reanchor_dragons({"其他": rows}, {"商业航天": {"code": "002565"}})
    assert out["其他"][0]["code"] == "001316"
    assert out["其他"][0]["role"] == "龙一"


# ── 3. anchor_rows_to_ledger ──

def _fact_row(board, code):
    return {"board": board, "code": code, "streak": 1, "gain10": 10.0}


def test_anchor_unanchored_when_ledger_missing():
    rows = [_fact_row("商业航天", "002565")]
    out, info = anchor_rows_to_ledger(rows, None)
    assert out is rows and info == {"anchored": False}


def test_anchor_keeps_ledger_leader_and_drops_others_with_trace():
    rows = [_fact_row("商业航天", "002565"),
            _fact_row("商业航天", "301226"),   # growth 轨推导行
            _fact_row("冰雪经济", "601188"),
            _fact_row("公告", "002827")]        # 节点档无该板块
    ledger = {"商业航天": {"code": "002565"}, "冰雪经济": {"code": "601188"}}
    out, info = anchor_rows_to_ledger(rows, ledger)
    assert info["anchored"] is True
    assert [r["code"] for r in out] == ["002565", "601188"]
    assert info["dropped"] == ["商业航天:301226!=002565", "公告:002827"]
    assert info["missing"] == []


def test_anchor_reports_missing_when_ledger_leader_has_no_fact_row():
    ledger = {"商业航天": {"code": "002565"}, "冰雪经济": {"code": "601188"}}
    out, info = anchor_rows_to_ledger([_fact_row("冰雪经济", "601188")], ledger)
    assert [r["code"] for r in out] == ["601188"]
    assert info["missing"] == ["商业航天"]


# ── 4. _collapse_segment_rows ──

def test_collapse_prefers_main_segment_row():
    rows = [{"board": "商业航天", "segment": "growth", "code": "301226"},
            {"board": "商业航天", "segment": "main", "code": "002565"}]
    out = _collapse_segment_rows(rows)
    assert len(out) == 1 and out[0]["code"] == "002565"


def test_collapse_keeps_growth_only_board_and_non_segment_rows():
    rows = [{"board": "冰雪经济", "segment": "growth", "code": "301010"},
            {"board": "寒潮", "code": "603366"}]   # 无 segment（旧调用方）
    out = _collapse_segment_rows(rows)
    assert {r["board"] for r in out} == {"冰雪经济", "寒潮"}


def test_collapse_handles_none_and_empty():
    assert _collapse_segment_rows(None) is None
    assert _collapse_segment_rows([]) == []
