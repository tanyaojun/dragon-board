# -*- coding: utf-8 -*-
"""竞价推送解析器测试（vA1；零网络零 jev）。

锁定口径（预登记 auction-leader-vA1 §4）：
- 09:15「竞价看龙头」条目筛选（窗 09:15~09:25、当日、前缀）；
- 板块归属=条目自身 stocks 全名最长优先消耗式匹配（防「日出东方/大东方」子串误配）；
- 未匹配段/未归属股 → board=None 披露（不丢弃）；
- 多条目 union 同 code 最新 ts 优先；零条目 → stocks=[]（不伪造名单）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import auction_push as P

DATE = "2026-11-13"


def _ts(hhmm: str) -> int:
    return int(time.mktime(time.strptime(f"{DATE} {hhmm}", "%Y-%m-%d %H:%M")))


def _entry(hhmm: str, comment: str, stocks: list) -> dict:
    return {"id": f"zb:{hhmm}", "ts": _ts(hhmm), "time": hhmm, "comment": comment,
            "stocks": stocks}


SCREENSHOT = _entry(
    "09:15",
    "竞价看龙头：机器人中重科技；羊年概念东方海洋、澳洋健康；芯片天普股份；"
    "冰雪产业龙江交通；光伏日出东方；大消费大东方",
    [{"code": "603135", "name": "中重科技", "pct": -10.02},
     {"code": "002086", "name": "东方海洋", "pct": -9.50},
     {"code": "002086", "name": "东方海洋", "pct": -9.50},
     {"code": "002379", "name": "澳洋健康", "pct": -10.06},
     {"code": "603179", "name": "天普股份", "pct": 10.00},
     {"code": "600853", "name": "龙江交通", "pct": -9.11},
     {"code": "600551", "name": "日出东方", "pct": 4.78},
     {"code": "600327", "name": "大东方", "pct": -8.64}])


def test_select_window_and_prefix():
    items = [SCREENSHOT,
             _entry("09:26", "竞价看龙头：修订条", [{"code": "600327", "name": "大东方", "pct": 1.0}]),
             _entry("09:10", "竞价看龙头：早于窗", []),
             _entry("09:20", "华为昇腾竞价异动", []),
             _entry("09:20", "竞价看龙头：昨日条", [])]
    items[-1]["ts"] = _ts("09:20") - 86400
    got = P.select_push_entries(items, DATE)
    assert [g["time"] for g in got] == ["09:15"]


def test_parse_screenshot_boards():
    roster = P.parse_auction_push([SCREENSHOT])
    by = {s["code"]: s for s in roster["stocks"]}
    assert by["603135"]["board"] == "机器人"
    assert by["002086"]["board"] == "羊年"      # normalize_name 剥「概念」尾缀
    assert by["002379"]["board"] == "羊年"
    assert by["002086"]["boardRaw"] == "羊年概念"
    assert by["603179"]["board"] == "芯片"
    assert by["600853"]["board"] == "冰雪产业"
    # 子串碰撞：「光伏日出东方」段必须先消耗「日出东方」，「大东方」归「大消费」
    assert by["600551"]["board"] == "光伏"
    assert by["600327"]["board"] == "大消费"
    assert roster["parseState"]["unmatchedSegments"] == []
    assert roster["parseState"]["unassignedCodes"] == []


def test_unmatched_segment_and_unassigned_stock_disclosed():
    e = _entry("09:15", "竞价看龙头：机器人中重科技；神秘板块无名股",
               [{"code": "603135", "name": "中重科技", "pct": 1.0},
                {"code": "000001", "name": "平安银行", "pct": 0.5}])
    roster = P.parse_auction_push([e])
    by = {s["code"]: s for s in roster["stocks"]}
    assert by["603135"]["board"] == "机器人"
    assert by["000001"]["board"] is None          # 未出现在任何段 → 披露不丢弃
    assert roster["parseState"]["unmatchedSegments"] == ["神秘板块无名股"]
    assert roster["parseState"]["unassignedCodes"] == ["000001"]


def test_multi_entry_union_latest_wins():
    e2 = _entry("09:20", "竞价看龙头：机器人中重科技",
                [{"code": "603135", "name": "中重科技", "pct": 2.5}])
    roster = P.parse_auction_push([SCREENSHOT, e2])
    by = {s["code"]: s for s in roster["stocks"]}
    assert by["603135"]["pct"] == 2.5
    assert by["603135"]["board"] == "机器人"
    assert len(roster["entries"]) == 2


def test_empty_entries_no_fabrication():
    roster = P.parse_auction_push([])
    assert roster["stocks"] == []
    assert roster["parseState"]["entryN"] == 0

def test_later_entry_missing_pct_keeps_known():
    """review nit：后到修订条 pct=None 不抹已知值（与 board 有新才更新同语义）。"""
    from backend.analysis.hotlist.auction_push import parse_auction_push
    e1 = {"time": "09:15", "comment": "竞价看龙头：机器人中重科技",
          "stocks": [{"code": "603135", "name": "中重科技", "pct": 3.0}]}
    e2 = {"time": "09:20", "comment": "竞价看龙头：机器人中重科技",
          "stocks": [{"code": "603135", "name": "中重科技", "pct": None}]}
    out = parse_auction_push([e1, e2])
    assert out["stocks"][0]["pct"] == 3.0
