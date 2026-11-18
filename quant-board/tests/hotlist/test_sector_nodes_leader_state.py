# -*- coding: utf-8 -*-
"""今日龙一自身接力状态 dayStatus（2026-11-12 用户修复龙头列续/断徽章）。

根因：leaderState=「昨日龙一今日状态」（节点判据口径），v5 空间龙一下今/昨龙一
常不同股，贴在今日龙一名旁误标（日出东方 4 板封板被贴昨龙一断板徽章）。
修复：settle 时用 day_status_of 单源算今日龙一自身状态落台账 leader.dayStatus
（停牌不算断板 v4）；_leader_states 与今日状态共用 _leader_day_states 禁双实现。
零 DB 零 jev（硬红线 §1.2-7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.operations import sector_nodes as ops

D0, D1 = "2026-11-11", "2026-11-10"


def test_leader_day_states_pool_authority_and_suspension(monkeypatch):
    """池权威 sealed；有棒未封=broken；已覆段内无棒且不在触板名单=suspended（不算断板）。"""
    monkeypatch.setattr(ops, "sealed_and_info",
                        lambda db, date, ds=None: ({"600001"},
                                                   {"600001": {}, "600003": {}},
                                                   {}))
    bars = {
        "600002": [{"date": D1, "close": 10.0}, {"date": D0, "close": 10.5}],
        # 600004：已覆段内缺 D0 棒=停牌；600003 同形但在触板名单=数据洞 unknown
        "600004": [{"date": "2026-11-09", "close": 10.0},
                   {"date": "2026-11-12", "close": 10.0}],
        "600003": [{"date": "2026-11-09", "close": 10.0},
                   {"date": "2026-11-12", "close": 10.0}],
    }
    monkeypatch.setattr(ops, "_daily_bars", lambda code: bars.get(code, []))
    monkeypatch.setattr(ops, "_adj_prev_series", lambda date, code, b: {})
    rows = [{"board": "A", "code": "600001"}, {"board": "B", "code": "600002"},
            {"board": "C", "code": "600004"}, {"board": "D", "code": "600003"}]
    out = ops._leader_day_states(None, D0, rows, "ds")
    assert out == {"A": "sealed", "B": "broken", "C": "suspended", "D": "unknown"}
    assert ops._leader_states(None, D0, rows, "ds") == out, "昨龙一状态共用同一实现"
    assert ops._leader_day_states(None, D0, None, "ds") == {}


def _row(**over):
    row = {"board": "AI算力", "code": "600001", "name": "龙头股",
           "streak": 2, "time": "09:31:00", "boardN": 3, "othersN": 2,
           "ladderShape": {"first": 1, "two": 1, "threePlus": 0, "unknown": 0},
           "secondStreak": 1, "zhabanN": 0, "prevZhabanN": 0,
           "prevTotal": 3, "prevStill": 2, "boardCodes": ["600001"],
           "leaderSealedToday": True, "segment": "main", "gain10": 10.0,
           "poolDay": None, "days": 8, "boards": 5}
    row.update(over)
    return row


@pytest.mark.parametrize("status,sealed_today,streak", [
    ("sealed", True, 2),
    ("broken", False, None),
    # 2026-11-18 天普案：停牌/数据洞三态 None（不伪装断板 False）
    ("suspended", None, None),
    ("unknown", None, None),
])
def test_settle_injects_leader_own_day_status(monkeypatch, status, sealed_today, streak):
    """settle 落库 leader.dayStatus=今日龙一自身状态；区间高度 days/boards 同档透传。"""
    monkeypatch.setattr(ops, "_promotion_by_board",
                        lambda db, pd, d, ds: {"ok": True, "byBoard": {},
                                               "ge2ByBoard": {}, "outByBoard": {},
                                               "outGe2ByBoard": {}, "unattributed": []})
    monkeypatch.setattr(ops, "_leader_day_states",
                        lambda db, d, rows, ds: {"AI算力": status})
    monkeypatch.setattr(ops, "board_count_history",
                        lambda db, d, days, dataset_id=None: {})
    monkeypatch.setattr(ops, "_member_ratio_history",
                        lambda db, d, days=21, dataset_id=None: {})
    monkeypatch.setattr(ops, "_prev_nodes_of", lambda db, d: None)
    monkeypatch.setattr(ops, "_agg_rows_compute", lambda db, d, ds: [])
    monkeypatch.setattr(ops, "_static_rows_compute", lambda db, d, boards: {})
    monkeypatch.setattr(ops, "trading_dates_before",
                        lambda db, d, n, dataset_id=None: [D1])
    monkeypatch.setattr(
        ops, "day_leader_rows",
        lambda db, date, dataset_id=None, prev_date=None, *, space_mode=False,
        pool_dates=None: ([_row(streak=streak, leaderSealedToday=sealed_today,
                                days=None if not sealed_today else 8,
                                boards=None if not sealed_today else 5)],
                          {"jiuyanFinalFound": True}))

    class _Coll:
        saved = None

        def replace_one(self, q, doc, upsert=False):
            _Coll.saved = doc

    ops.settle_day({ops.COLLECTION: _Coll()}, D0, "ds")
    r = _Coll.saved["rows"][0]
    assert r["leader"]["dayStatus"] == status
    assert r["leader"].get("leaderSealedToday") is sealed_today, "续断三态单源 dayStatus 映射"
    assert r["leaderState"] == status, "昨龙一=同股时判据口径与自身状态一致"
    if sealed_today:
        assert r["leader"]["days"] == 8 and r["leader"]["boards"] == 5
    else:
        assert "days" not in r["leader"] and "boards" not in r["leader"]
