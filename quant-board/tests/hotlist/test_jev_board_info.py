# -*- coding: utf-8 -*-
"""jiuyan_board_info 单测：漏标连板标记口径（与 _jiuyan_ladder 同源）+ meta 降级旗标。

2026-10-10 涨停复盘 KPI 口径修复的核心判定：
- num=null 且在昨日涨停池 → boardUnmarked=True（真连板漏标，不猜高度不归首板）；
- num=null 且不在昨日池 → 韭研首板口径（无标记）；
- 韭研 final 缺失 / 昨日池轴缺失 → meta 旗标结构化降级（调用方必须可见）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_label_jiuyan import jiuyan_board_info


class FinalCol:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, query, projection=None):
        for d in self.docs:
            if d.get("_id") == query.get("_id"):
                return d
        return None


class FramesCol:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query, projection=None):
        lt = (query.get("tradingDate") or {}).get("$lt")
        return [dict(r) for r in self.rows if lt is None or str(r.get("tradingDate")) < lt]


class MultiFakeDb:
    def __init__(self, cols):
        self._cols = cols

    def __getitem__(self, name):
        return self._cols[name]


def _cols(prev_codes, today_stocks, frames=("2026-10-08",)):
    return {
        "jiuyan_action": FinalCol([
            {"_id": "2026-10-09:final",
             "fields": [{"name": "大农业", "stocks": list(today_stocks)}]},
            {"_id": "2026-10-08:final",
             "fields": [{"name": "X", "stocks": [{"code": c} for c in prev_codes]}]},
        ]),
        "snapshot_frames": FramesCol([{"tradingDate": d} for d in frames]),
    }


def test_board_info_marks_unmarked_prev_pool():
    """num=null 且在昨日池 → boardUnmarked；不在昨日池 → 韭研首板口径无标记。"""
    cols = _cols(
        prev_codes=["600127", "605303"],
        today_stocks=[
            {"code": "600127", "num": None, "time": "10:05"},
            {"code": "002709", "num": None, "time": ""},
            {"code": "600825", "num": "9天9板", "time": "09:25"},
        ])
    info, meta = jiuyan_board_info(MultiFakeDb(cols), "2026-10-09")
    assert meta == {"jiuyanFinalFound": True, "prevPoolFound": True}
    assert info["600127"]["boardUnmarked"] is True
    assert info["600127"]["boards"] is None  # 宁缺毋猜
    assert "boardUnmarked" not in info["002709"]
    assert info["600825"]["boards"] == 9
    assert info["600825"]["boardName"] == "大农业"  # 投影含 fields.name
    assert info["600825"]["limitUpTime"] == "09:25"


def test_board_info_prev_pool_missing_degrades():
    """昨日池轴缺失 → prevPoolFound=False 且不误标（漏标股落回首板口径必须对调用方可见）。"""
    cols = _cols(prev_codes=[], today_stocks=[{"code": "600127", "num": None}], frames=())
    info, meta = jiuyan_board_info(MultiFakeDb(cols), "2026-10-09")
    assert meta["prevPoolFound"] is False
    assert "boardUnmarked" not in info["600127"]


def test_board_info_final_missing():
    cols = {"jiuyan_action": FinalCol([]),
            "snapshot_frames": FramesCol([{"tradingDate": "2026-10-08"}])}
    info, meta = jiuyan_board_info(MultiFakeDb(cols), "2026-10-09")
    assert info == {} and meta["jiuyanFinalFound"] is False


def test_board_info_dedup_first_field_wins():
    """同 code 出现在多个板块取首现（与 join 展示口径一致）。"""
    cols = {
        "jiuyan_action": FinalCol([
            {"_id": "2026-10-09:final", "fields": [
                {"name": "首现板块", "stocks": [{"code": "600825", "num": "2天2板"}]},
                {"name": "后续板块", "stocks": [{"code": "600825", "num": "3天3板"}]},
            ]},
        ]),
        "snapshot_frames": FramesCol([{"tradingDate": "2026-10-08"}]),
    }
    info, meta = jiuyan_board_info(MultiFakeDb(cols), "2026-10-09")
    assert info["600825"]["boards"] == 2 and info["600825"]["boardName"] == "首现板块"
