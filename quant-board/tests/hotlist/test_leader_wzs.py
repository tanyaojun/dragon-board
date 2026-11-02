# -*- coding: utf-8 -*-
"""题材周期·龙头弱转强 纯计算层测试（v5 预登记 P1，2026-11-01）。

口径锚：严格 3 日回溯窗位 k=T−S−1；height≥2 才入池（裁决 5）；断板日跌停不入池
（裁决 8）；新龙只认当日分轨空间龙一（裁决 5）；完成态=收盘封板（裁决 6）。
"""
from __future__ import annotations

import pytest

from backend.analysis.hotlist.leader_wzs import build_leader_wzs


def segment_fn(code):
    c = str(code)
    return "growth" if c[:2] in ("30", "68") else "main"


def _bars(closes: dict[str, float]) -> dict[str, dict]:
    return {d: {"close": c} for d, c in closes.items()}


POOL_DAYS = ["2026-10-27", "2026-10-28", "2026-10-29"]   # T=2026-10-30
TODAY = "2026-10-30"


def _bars_window():
    """10-26..10-29 收盘序列（供 D0/窗内涨跌幅）：断板日跌幅均未触跌停阈值。"""
    return _bars({"2026-10-26": 10.0, "2026-10-27": 11.0, "2026-10-28": 10.0,
                  "2026-10-29": 9.2, "2026-10-30": 9.5})


def _call(**over):
    kw = dict(
        date=TODAY, pool_days=list(POOL_DAYS),
        today_sealed={"600111"},
        pool_members={
            "2026-10-27": {"机器人": {"600222": "太龙"}},
            "2026-10-28": {"机器人": {"600999": "中马"}},
            "2026-10-29": {"机器人": {"600111": "上海沪工", "600555": "海工"}},
        },
        streaks_by_day={
            "2026-10-27": {"600222": 3},
            "2026-10-28": {"600999": 5},
            "2026-10-29": {"600111": 3, "600555": 2},
        },
        streaks_today={"600111": 3},
        leader_rows=[
            {"date": TODAY, "board": "机器人", "segment": "main",
             "code": "600111", "name": "上海沪工", "streak": 3, "time": "09:31",
             "boardN": 3, "othersN": 2, "ladderFollowers": 1,
             "prevPeers": 2, "prevBoardN": 2, "prevTotal": 3, "prevStill": 2,
             "zhabanN": 0, "prevZhabanN": 1, "ladderShape": {},
             "secondStreak": 1, "peerCodes": ["600555"], "boardCodes": ["600111"],
             "gain10": 44.4, "leaderSealedToday": True, "poolDay": None},
        ],
        bars_by_code={
            "600222": _bars_window(), "600999": _bars_window(),
            "600111": _bars_window(), "600555": _bars_window(),
        },
        segment_fn=segment_fn,
    )
    kw.update(over)
    return build_leader_wzs(**kw)


def test_window_k_and_pool_membership():
    """窗位口径（严格 3 日回溯）：S=T-1→k0 今日断板提示；S=T-2→k1 可反包；S=T-3→k2 末窗。"""
    rows, events, meta = _call()
    assert meta["status"] == "ok"
    by_code = {r["code"]: r for r in rows}
    # 600222：S=10-27（k=2 末窗），未再封板 → broken
    r = by_code["600222"]
    assert r["windowK"] == 2 and r["reboundState"] == "none"
    assert r["height"] == 3 and r["leaderSealedToday"] is False
    # 600999：S=10-28（k=1），未再封板 → broken
    assert by_code["600999"]["windowK"] == 1
    # 600555：S=10-29（k=0），今日断板候选提示（height2 入池；height1 在剔除测覆盖）
    assert by_code["600555"]["windowK"] == 0 and by_code["600555"]["height"] == 2
    # 600111：S=10-29 且今日续板 → 只在龙一行呈现（标杆晋级候选）
    r = by_code["600111"]
    assert r["isLeader"] and r["leaderSealedToday"] and r["streak"] == 3
    assert events == [], "无反包/晋级事件（沪工连续封板非反包；streak4→昨日3 达标杆门槛，见下测）"


def test_benchmark_advance_event():
    """形式②：昨日 streak≥3 的龙一今日续板 → benchmarkAdvance（标杆晋级）。"""
    rows, events, _ = _call(
        streaks_today={"600111": 4},
        leader_rows=[
            {"date": TODAY, "board": "机器人", "segment": "main",
             "code": "600111", "name": "上海沪工", "streak": 4, "time": "09:31",
             "boardN": 3, "othersN": 2, "ladderFollowers": 1,
             "prevPeers": 2, "prevBoardN": 2, "prevTotal": 3, "prevStill": 2,
             "zhabanN": 0, "prevZhabanN": 1, "ladderShape": {},
             "secondStreak": 1, "peerCodes": ["600555"], "boardCodes": ["600111"],
             "gain10": 44.4, "leaderSealedToday": True, "poolDay": None},
        ])
    # 沪工今日 streak=4（昨日 3=标杆门槛）→ 晋级事件必须出
    ev = [e for e in events if e["type"] == "benchmarkAdvance"]
    assert len(ev) == 1 and ev[0]["code"] == "600111" and ev[0]["prevStreak"] == 3


def test_leader_rebound_vs_follower():
    """形式①：断板股今日回封——龙一 → leaderRebound 事件；非龙一 → 跟风披露不出事件。"""
    # 600999（k=1，height5）今日回封且被 gain10 选为龙一
    rows, events, _ = _call(
        today_sealed={"600111", "600999", "600222"},
        streaks_today={"600111": 4, "600999": 1, "600222": 1},
        leader_rows=[
            {"date": TODAY, "board": "机器人", "segment": "main",
             "code": "600999", "name": "中马", "streak": 1, "time": "09:25",
             "boardN": 3, "othersN": 2, "ladderFollowers": None,
             "prevPeers": 0, "prevBoardN": 1, "prevTotal": 3, "prevStill": 0,
             "zhabanN": 0, "prevZhabanN": 0, "ladderShape": {},
             "secondStreak": None, "peerCodes": [], "boardCodes": ["600999"],
             "gain10": 77.7, "leaderSealedToday": True, "poolDay": "2026-10-28"},
        ])
    by_code = {r["code"]: r for r in rows}
    assert by_code["600999"]["reboundState"] == "leader"
    rb = [e for e in events if e["type"] == "leaderRebound"]
    assert len(rb) == 1 and rb[0]["code"] == "600999" and rb[0]["windowK"] == 1
    # 600222 也回封但非龙一 → follower 披露、无事件
    assert by_code["600222"]["reboundState"] == "follower"
    assert not any(e["code"] == "600222" for e in events)


def test_low_height_and_limit_down_excluded():
    """裁决 5/8：height<2 不入池（披露）；断板日跌停不入池（披露）。"""
    bars = dict(_bars_window())
    bars["2026-10-30"] = {"close": 6.5}   # 对 10-29 收 9.2 → -29.3%（主板阈值 -9.9 触发）
    rows, events, meta = _call(
        today_sealed=set(),
        streaks_by_day={
            "2026-10-27": {"600222": 3}, "2026-10-28": {"600999": 5},
            "2026-10-29": {"600111": 3, "600555": 1},
        },
        leader_rows=[],
        bars_by_code={"600222": _bars_window(), "600999": _bars_window(),
                      "600111": bars, "600555": _bars_window()})
    codes = {r["code"] for r in rows}
    assert "600555" not in codes, "height1（首板断板）不入池"
    assert "600111" not in codes, "断板日（10-30）跌停不入池（裁决 8）"
    assert any("600555" in x for x in meta["lowHeightExcluded"])
    assert any("600111" in x for x in meta["limitDownExcluded"])
    assert events == []
    # 600111 断板跌停同时是龙一池成员缺席 → fail-visible 语义：龙一身份仍在 leader_rows
    # （本测 leader_rows=[] 模拟 THS 全无封板的极端面，仅验证剔除分支）


def test_growth_threshold():
    """20cm 轨阈值独立：growth -12% 不算跌停（-19.9 才触发），不入剔除。"""
    def seg_growth(code):
        return "growth"
    rows, _e, meta = _call(
        today_sealed=set(),
        leader_rows=[],
        segment_fn=seg_growth,
        bars_by_code={"600222": _bars_window(), "600999": _bars_window(),
                      "600111": _bars_window(), "600555": _bars_window()})
    assert "limitDownExcluded" not in meta
    assert {r["code"] for r in rows} == {"600222", "600999", "600111", "600555"}


def test_window_changes_fail_visible():
    """窗内逆势表现：有 bars 给逐日环比；无 bars 缺失+披露，不伪 0。"""
    rows, _e, meta = _call(
        bars_by_code={"600222": _bars_window(), "600999": _bars_window(),
                      "600111": _bars_window(), "600555": None})
    by_code = {r["code"]: r for r in rows}
    # 600999：S=10-28，窗=10-29 一日：close 10→9.2 = -8.0%
    wc = by_code["600999"]["windowChanges"]
    assert wc == [{"date": "2026-10-29", "pct": -8.0}]
    # 600222：S=10-27，窗=10-28/10-29
    assert by_code["600222"]["windowChanges"] == [
        {"date": "2026-10-28", "pct": -9.09}, {"date": "2026-10-29", "pct": -8.0}]
    assert by_code["600555"]["windowChanges"] == []
    assert any("日线不可考" in g for g in meta["dataGaps"])


def test_degraded_paths():
    """THS 池缺失/龙一行缺失 → 整日降级（fail-visible），rows/events 空。"""
    rows, events, meta = _call(today_sealed=None)
    assert rows == [] and events == [] and meta["status"] == "degraded"
    rows, events, meta = _call(leader_rows=None)
    assert rows == [] and events == [] and meta["status"] == "degraded"


def test_short_pool_days_gap_disclosed():
    """早期历史回溯日不足 3 → 窗口如实缩短 + dataGaps 披露。"""
    rows, _e, meta = _call(pool_days=POOL_DAYS[1:])
    assert meta["status"] == "ok"
    assert any("不足 3 日" in g for g in meta["dataGaps"])
    by_code = {r["code"]: r for r in rows}
    assert "600222" not in by_code, "S=10-27 不在回溯窗（池只含可得回溯日）"
    assert by_code["600999"]["windowK"] == 1   # S=10-28 在 [10-28,10-29] 中 index0 → k=1


def test_broken_leader_row_window():
    """断板龙一（leaderSealedToday=False）带 poolDay → 龙一行并入时算窗位。"""
    rows, _e, _m = _call(
        today_sealed=set(),
        streaks_today={},
        leader_rows=[
            {"date": TODAY, "board": "机器人", "segment": "main",
             "code": "600111", "name": "上海沪工", "streak": None, "time": None,
             "boardN": 1, "othersN": 0, "ladderFollowers": None,
             "prevPeers": 0, "prevBoardN": None, "prevTotal": None,
             "prevStill": None, "zhabanN": 0, "prevZhabanN": None,
             "ladderShape": {}, "secondStreak": None, "peerCodes": [],
             "boardCodes": [], "gain10": 44.4, "leaderSealedToday": False,
             "poolDay": "2026-10-29"},
        ])
    by_code = {r["code"]: r for r in rows}
    r = by_code["600111"]
    assert r["isLeader"] and r["windowK"] == 0 and r["leaderSealedToday"] is False
    assert r["height"] == 3   # 断板龙一高度取最近封板日 streak 映射
