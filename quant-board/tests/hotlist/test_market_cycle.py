# -*- coding: utf-8 -*-
"""第4课·市场情绪周期 纯计算层测试（P1，2026-11-12）。

口径锚：N=20 天花板回看；大面 ≤-5%；跌停 is_limit_down_pct（权威）；E1 严格大于；
E2 昨有今无；E3 1日跌停/2日双大面无承接；E4 反包（昨断今封）/企稳（断板后2日干净）。
"""
from __future__ import annotations

from backend.analysis.hotlist import market_cycle as mc
from backend.analysis.hotlist.theme_leader_ammo import segment_of

T = "2026-11-12"


# ── 天花板 ──
def test_ceiling_from_streaks_basic():
    cb = mc.ceiling_from_streaks({"600111": 5, "600222": 3, "600333": 1, "600444": 2})
    assert cb["maxBoard"] == 5 and cb["threePlusN"] == 2 and cb["counted"] == 4


def test_ceiling_from_streaks_empty_and_bool():
    assert mc.ceiling_from_streaks({})["maxBoard"] is None
    assert mc.ceiling_from_streaks({})["threePlusN"] == 0
    # bool 显式排除（True 不混进高度）；None 不计
    cb = mc.ceiling_from_streaks({"600111": True, "600222": None, "600333": 3})
    assert cb["maxBoard"] == 3 and cb["counted"] == 1


# ── 候选 enrichment ──
def _cands():
    return [
        {"code": "600111", "name": "封板股", "streak": 3, "time": "09:31"},
        {"code": "600222", "name": "断板高位", "streak": None, "histStreak": 4,
         "poolDay": "2026-11-10"},
        {"code": "600333", "name": "断板首板", "streak": None, "histStreak": 1,
         "poolDay": "2026-11-11"},
    ]


def test_prepare_height_and_low_height_exclusion():
    kept, meta = mc.prepare_market_candidates(_cands(), {"600111"},
                                              {"600222": -2.0, "600333": -1.0})
    codes = {c["code"] for c in kept}
    assert codes == {"600111", "600222"}            # 首板断板（高度1）剔除
    by = {c["code"]: c for c in kept}
    assert by["600111"]["height"] == 3              # 封板股=当日 streak
    assert by["600222"]["height"] == 4              # 断板股=历史高度
    assert "断板首板" in meta["lowHeightBrokenExcluded"][0]


def test_prepare_limit_down_exclusion_authoritative():
    # 主板 -10% ≤ -9.8（is_limit_down_pct 权威线）→ 剔除
    kept, meta = mc.prepare_market_candidates(_cands(), {"600111"},
                                              {"600222": -10.0, "600333": -1.0})
    assert {c["code"] for c in kept} == {"600111"}
    assert "断板高位" in meta["limitDownExcluded"][0]


def test_prepare_pct_none_kept_not_guess():
    # 涨跌幅不可考 → 不剔除（不猜，fail-visible）；高度4≥2 保留
    kept, _ = mc.prepare_market_candidates(_cands(), {"600111"},
                                           {"600222": None, "600333": None})
    assert "600222" in {c["code"] for c in kept}


def test_prepare_height_takes_max_today_vs_hist():
    cands = [{"code": "600111", "name": "X", "streak": 2, "histStreak": 5}]
    kept, _ = mc.prepare_market_candidates(cands, {"600111"}, {})
    assert kept[0]["height"] == 5                   # 当日2 与 历史5 取大


# ── 分轨龙一（排序键单源）──
def test_pick_market_leaders_segment_and_gain10():
    cands = [
        {"code": "600111", "name": "主板A", "height": 3, "gain10": 30.0, "time": "09:40"},
        {"code": "600222", "name": "主板B", "height": 4, "gain10": 45.0, "time": "10:00"},
        {"code": "300111", "name": "双创A", "height": 3, "gain10": 50.0, "time": "09:35"},
    ]
    leaders = mc.pick_market_leaders(cands)
    assert leaders["main"]["code"] == "600222"      # 空间板组内 gain10 最高
    assert leaders["growth"]["code"] == "300111"
    assert segment_of("600222") == "main" and segment_of("300111") == "growth"


# ── E1 空间突破 ──
def _window(maxes):
    return [{"date": f"2026-10-{i+1:02d}", "maxBoard": m} for i, m in enumerate(maxes)]


def test_breakthrough_positive():
    e = mc.detect_breakthrough(T, 5, _window([3, 4, 4]),
                               [{"code": "600111", "streak": 5}])
    assert e["type"] == "spaceBreakthrough" and e["maxBoard"] == 5
    assert e["prevCeiling"] == 4 and e["windowDays"] == 3


def test_breakthrough_equal_not_break():
    assert mc.detect_breakthrough(T, 4, _window([3, 4]), []) is None   # 持平=未突破


def test_breakthrough_missing_inputs():
    assert mc.detect_breakthrough(T, None, _window([4]), []) is None
    assert mc.detect_breakthrough(T, 5, [], []) is None                # 无参照


# ── E2 空间压缩 ──
def test_compress_positive():
    e = mc.detect_compress(T, 0, 3)
    assert e["type"] == "spaceCompress" and e["prevThreePlusN"] == 3


def test_compress_negatives():
    assert mc.detect_compress(T, 0, 0) is None      # 昨亦无=非转折
    assert mc.detect_compress(T, 2, 3) is None      # 今仍有3板+
    assert mc.detect_compress(T, None, 3) is None
    assert mc.detect_compress(T, 0, None) is None


# ── E3 高位崩塌 ──
def test_collapse_1day_limit_down():
    e = mc.detect_collapse(T, "main", {"code": "600111", "name": "龙"},
                           {"pct": -10.0, "status": "broken"},
                           {"pct": 10.0, "status": "sealed"})
    assert e["subtype"] == "1day" and e["track"] == "main"


def test_collapse_1day_growth_threshold():
    e = mc.detect_collapse(T, "growth", {"code": "300111", "name": "龙"},
                           {"pct": -20.0, "status": "broken"}, None)
    assert e["subtype"] == "1day"                   # 双创 -20% ≤ -19.8


def test_collapse_2day_big_face_no_support():
    e = mc.detect_collapse(T, "main", {"code": "600111", "name": "龙"},
                           {"pct": -6.0, "status": "broken"},
                           {"pct": -7.0, "status": "broken"})
    assert e["subtype"] == "2day" and e["todayPct"] == -6.0


def test_collapse_2day_sealed_has_support():
    assert mc.detect_collapse(T, "main", {"code": "600111"},
                              {"pct": -6.0, "status": "sealed"},
                              {"pct": -7.0, "status": "broken"}) is None


def test_collapse_not_big_face():
    assert mc.detect_collapse(T, "main", {"code": "600111"},
                              {"pct": -3.0, "status": "broken"},
                              {"pct": -7.0, "status": "broken"}) is None
    assert mc.detect_collapse(T, "main", None, {"pct": -10.0}, None) is None


# ── E4 高位宽容 ──
def test_tolerance_rebound():
    e = mc.detect_tolerance(T, "main",
                            {"code": "600111", "name": "龙", "poolDay": "2026-11-10",
                             "statusYesterday": "broken"},
                            {"pct": 10.0, "status": "sealed"}, None)
    assert e["subtype"] == "rebound" and e["poolDay"] == "2026-11-10"


def test_tolerance_rebound_requires_broken_yesterday():
    # 昨日封板（续板）今日封板 ≠ 反包
    assert mc.detect_tolerance(T, "main",
                               {"code": "600111", "statusYesterday": "sealed"},
                               {"pct": 10.0, "status": "sealed"}, None) is None


def test_tolerance_stabilize_positive():
    win = [{"date": "2026-11-11", "pct": -1.0, "status": "broken"},
           {"date": T, "pct": 1.5, "status": "broken"}]
    e = mc.detect_tolerance(T, "main",
                            {"code": "600111", "name": "龙", "poolDay": "2026-11-09",
                             "statusYesterday": "broken"},
                            {"pct": 1.5, "status": "broken"}, win)
    assert e["subtype"] == "stabilize" and len(e["window"]) == 2


def test_tolerance_stabilize_big_face_breaks():
    win = [{"date": "2026-11-11", "pct": -6.0, "status": "broken"},
           {"date": T, "pct": 1.0, "status": "broken"}]
    assert mc.detect_tolerance(T, "main", {"code": "600111", "statusYesterday": "broken"},
                               {"pct": 1.0, "status": "broken"}, win) is None


def test_tolerance_stabilize_window_not_ending_today():
    win = [{"date": "2026-11-10", "pct": -1.0, "status": "broken"},
           {"date": "2026-11-11", "pct": 1.0, "status": "broken"}]   # 末日≠T
    assert mc.detect_tolerance(T, "main", {"code": "600111", "statusYesterday": "broken"},
                               {"pct": 1.0, "status": "broken"}, win) is None
    assert mc.detect_tolerance(T, "main", {"code": "600111"}, None, None) is None


# ── 一字板机械判定 ──
def test_is_one_word_bar():
    bar = {"open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0}
    assert mc.is_one_word_bar(bar, "600111", 10.0) is True    # 涨停价=11.0
    assert mc.is_one_word_bar({"open": 10.5, "high": 11.0, "low": 10.2, "close": 11.0},
                              "600111", 10.0) is False
    assert mc.is_one_word_bar({"open": 11.0, "close": 11.0}, "600111", 10.0) is None  # 缺高低价
    assert mc.is_one_word_bar(bar, "600111", None) is None
