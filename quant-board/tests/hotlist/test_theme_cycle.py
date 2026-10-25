# -*- coding: utf-8 -*-
"""题材周期 v1 测试：逐档规则 fixture + fail-visible + 周期成链 + 回填幂等。

预登记：docs/hotlist-jev/theme-cycle-v1-preregistration.md（判据表 §四）。
核心案例基准：大业股份 10-23 题材=人形机器人 6 板续板（mainTheme 治理后语义）。
"""
from __future__ import annotations

import pytest

from backend.analysis.hotlist.theme_cycle import (
    EMERGING_MIN_ZT,
    NEW_BENCHMARK_STREAK,
    TERMINATOR_WINDOW,
    THEME_CYCLE_VERSION,
    append_notes_and_events,
    assemble_rows,
    classify_theme_day,
)


def _leader(streak=2, name="大业股份", time="13:09:00", code="603278"):
    return {"code": code, "name": name, "streak": streak, "time": time,
            "boardHeight": streak}


def _rw(name="反包股", code="000001", streak=2, time="10:00:00"):
    return {"code": code, "name": name, "streak": streak, "time": time}


# ── 逐档规则 ────────────────────────────────────────────────────────

def test_unknown_when_n0_missing():
    """fail-visible：名单不可考 → unknown，不伪 0。"""
    res = classify_theme_day(n0=None, n1=None, count_hist=[], n5_hist=[], n10_hist=[],
                             leader=None, leader_state=None, max_streak=None,
                             rewrap_codes=[], benchmark_codes=[],
                             prev_stage="weakening", prev_weak_days=1, panic=None)
    assert res["stage"] == "unknown"
    assert "不可考" in res["notes"][0]


def test_wzs_requires_prev_weakening_and_two_paths():
    """弱转强：昨日=转弱 且 反包/新标杆两路之一；昨日档不可考不贴标。"""
    base = dict(n0=3, n1=2, count_hist=[], n5_hist=[], n10_hist=[],
                leader=_leader(streak=2), leader_state="sealed", max_streak=2,
                prev_weak_days=1, panic=None)
    res = classify_theme_day(**base, rewrap_codes=[_rw()], benchmark_codes=[],
                             prev_stage="weakening")
    assert res["stage"] == "wzs"
    assert res["weakDays"] == 0

    # 新标杆路径（≥3 板）
    res2 = classify_theme_day(**base, rewrap_codes=[],
                              benchmark_codes=[_rw("标杆股", streak=3)],
                              prev_stage="weakening")
    assert res2["stage"] == "wzs"

    # 昨日非转弱（主升中反包不算 wzs）→ 落主升
    res3 = classify_theme_day(**base, rewrap_codes=[_rw()], benchmark_codes=[],
                              prev_stage="mainline")
    assert res3["stage"] == "mainline"

    # 昨日档不可考（prevStage=None）→ 不贴 wzs 标
    res4 = classify_theme_day(**base, rewrap_codes=[_rw()], benchmark_codes=[],
                              prev_stage=None)
    assert res4["stage"] != "wzs"


def test_terminator_after_window_without_revival():
    """终结者：转弱第 N=3 日无反包/新标杆/新启动；复活则新周期。"""
    base = dict(n0=1, n1=2, count_hist=[], n5_hist=[], n10_hist=[],
                leader=_leader(streak=2), leader_state="broken", max_streak=1,
                rewrap_codes=[], benchmark_codes=[], panic=None)
    # 转弱第 1-2 天：仍 weakening（weakDays 递增）
    r1 = classify_theme_day(**base, prev_stage="weakening", prev_weak_days=0)
    assert r1["stage"] == "weakening" and r1["weakDays"] == 1
    r2 = classify_theme_day(**base, prev_stage="weakening", prev_weak_days=1)
    assert r2["stage"] == "weakening" and r2["weakDays"] == 2
    # 第 3 天（prevWeakDays=N-1=2）：终结
    r3 = classify_theme_day(**base, prev_stage="weakening", prev_weak_days=2)
    assert r3["stage"] == "terminator"
    # 第 3 天但今日新启动（n0≥4）→ 不终结
    r4 = classify_theme_day(**{**base, "n0": EMERGING_MIN_ZT},
                            prev_stage="weakening", prev_weak_days=2)
    assert r4["stage"] != "terminator"


def test_weakening_on_leader_broken():
    res = classify_theme_day(n0=1, n1=4, count_hist=[], n5_hist=[], n10_hist=[],
                             leader=_leader(streak=3), leader_state="broken",
                             max_streak=1, rewrap_codes=[], benchmark_codes=[],
                             prev_stage="mainline", prev_weak_days=0, panic=None)
    assert res["stage"] == "weakening" and res["weakDays"] == 1
    assert any("断板" in b for b in res["basis"])


def test_weakening_high_volume_note_not_stage_change():
    """高量换血注记：龙头断板但 n0≥4 → 仍转弱档+注记。"""
    res = classify_theme_day(n0=5, n1=4, count_hist=[], n5_hist=[], n10_hist=[],
                             leader=_leader(streak=3), leader_state="broken",
                             max_streak=1, rewrap_codes=[], benchmark_codes=[],
                             prev_stage="mainline", prev_weak_days=0, panic=None)
    assert res["stage"] == "weakening"
    assert any("换血" in n for n in res["notes"])


def test_mainline_leader_sealed_streak_ge2():
    res = classify_theme_day(n0=6, n1=5, count_hist=[], n5_hist=[1, 2, 3, 4, 5],
                             n10_hist=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
                             leader=_leader(streak=3), leader_state="sealed",
                             max_streak=3, rewrap_codes=[], benchmark_codes=[],
                             prev_stage="mainline", prev_weak_days=0, panic=None)
    assert res["stage"] == "mainline"
    # N5/N10 对照列（只落列不进门）
    assert res["n5Pct"] is not None and res["n10Pct"] is not None
    assert any("对照" in b for b in res["basis"])


def test_mainline_requires_streak_ge2_not_sealed_alone():
    """龙头 sealed 但 streak=1（昨日首板今日首板? streak 不可考/为 1）→ 不归主升。"""
    res = classify_theme_day(n0=5, n1=4, count_hist=[], n5_hist=[], n10_hist=[],
                             leader=_leader(streak=1), leader_state="sealed",
                             max_streak=1, rewrap_codes=[], benchmark_codes=[],
                             prev_stage="emerging", prev_weak_days=0, panic=None)
    assert res["stage"] == "emerging"


def test_emerging_all_first_boards():
    """启动：n0≥4 且全是首板（用户裁定：全是首板也算启动）。"""
    res = classify_theme_day(n0=4, n1=0, count_hist=[], n5_hist=[], n10_hist=[],
                             leader=_leader(streak=1, time="09:25:00"),
                             leader_state="none", max_streak=1,
                             rewrap_codes=[], benchmark_codes=[],
                             prev_stage=None, prev_weak_days=0, panic=None)
    assert res["stage"] == "emerging"
    assert any("首板潮" in b for b in res["basis"])


def test_emerging_threshold_is_gt3():
    """n0=3（未超 3 只）不启动；n0=4 启动（用户裁定「超过 3 只」）。"""
    kw = dict(count_hist=[], n5_hist=[], n10_hist=[], leader=None,
              leader_state="none", max_streak=1, rewrap_codes=[],
              benchmark_codes=[], prev_stage=None, prev_weak_days=0, panic=None)
    assert classify_theme_day(n0=3, n1=0, **kw)["stage"] == "normal"
    assert classify_theme_day(n0=4, n1=0, **kw)["stage"] == "emerging"


def test_normal_fallback_and_terminator_continuation():
    kw = dict(count_hist=[], n5_hist=[], n10_hist=[], leader=None,
              leader_state="none", max_streak=None, rewrap_codes=[],
              benchmark_codes=[], panic=None)
    assert classify_theme_day(n0=1, n1=1, prev_stage="mainline",
                              prev_weak_days=0, **kw)["stage"] == "normal"
    r = classify_theme_day(n0=1, n1=0, prev_stage="terminator",
                           prev_weak_days=0, **kw)
    assert r["stage"] == "normal" and any("终结延续" in b for b in r["basis"])


# ── 注记（不改档） ─────────────────────────────────────────────────

def test_panic_and_demon_notes():
    row = {"notes": [], "events": []}
    append_notes_and_events(row, pool_codes={"a", "b"},
                            panic={"dtN": 2, "medianPct": -6.1, "n": 5},
                            leader=_leader(streak=5), n0=2)
    assert any("恐慌" in n for n in row["notes"])
    assert any("妖股" in n for n in row["notes"])
    assert {e["type"] for e in row["events"]} >= {"panic", "demon"}


def test_panic_below_threshold_no_note():
    row = {"notes": [], "events": []}
    append_notes_and_events(row, pool_codes={"a"}, panic={"dtN": 1, "medianPct": -2.0},
                            leader=_leader(streak=2), n0=5)
    assert not row["notes"]


# ── assemble_rows：成链/新周期/fail-visible ────────────────────────

def _theme_row(codes, streak=2, time="09:30:00"):
    return {"codes": codes,
            "names": [{"code": c, "name": f"股{c}", "streak": streak, "time": time,
                       "boardHeight": streak} for c in codes],
            "leader": _leader(streak=streak, time=time, code=codes[0] if codes else ""),
            "maxStreak": streak, "popularN": 0, "poolCodes": set(),
            "rewrapCodes": [], "benchmarkCodes": [], "kplZtCount": None}


def test_assemble_new_cycle_after_terminator():
    """终结后复活 → cycleN+1 + 新周期事件。"""
    today_by = {"机器人": _theme_row(["600001", "600002", "600003", "600004"], streak=3)}
    prev_state = {"机器人": {"stage": "terminator", "weakDays": 0, "cycleN": 2}}
    built = assemble_rows(date="2026-10-23", today_by=today_by, prev_by=None,
                          prev_date="2026-10-22", count_hist={},
                          prev_stage_map=prev_state, prev_state_map=prev_state,
                          leader_states={}, panic_by={})
    row = built["rows"][0]
    assert row["cycleN"] == 3
    assert any(e["type"] == "newCycle" for e in row["events"])


def test_assemble_prev_doc_missing_no_wzs_tag():
    """昨日文档缺失：prevStage=None → 弱转强不贴标（防标签通胀）。"""
    today_by = {"机器人": _theme_row(["600001", "600002"], streak=2)}
    built = assemble_rows(date="2026-10-23", today_by=today_by, prev_by=None,
                          prev_date="2026-10-22", count_hist={},
                          prev_stage_map=None, prev_state_map=None,
                          leader_states={}, panic_by={})
    row = built["rows"][0]
    assert row["prevStage"] is None
    assert any("不可考" in n for n in row["notes"])


def test_assemble_three_day_window_keeps_departed_theme():
    """三日窗口：昨日有今日无的题材必须在场（退潮/终结正是它们）。"""
    prev_by = {"冰雪经济": _theme_row(["900001"], streak=1)}
    built = assemble_rows(date="2026-10-23", today_by={}, prev_by=prev_by,
                          prev_date="2026-10-22", count_hist={},
                          prev_stage_map={"冰雪经济": {"stage": "weakening",
                                                       "weakDays": 2, "cycleN": 1}},
                          prev_state_map={"冰雪经济": {"stage": "weakening",
                                                       "weakDays": 2, "cycleN": 1}},
                          leader_states={"冰雪经济": "broken"}, panic_by={})
    themes = [r["theme"] for r in built["rows"]]
    assert "冰雪经济" in themes
    row = next(r for r in built["rows"] if r["theme"] == "冰雪经济")
    assert row["count"] == 0 and row["stage"] == "terminator"


def test_assemble_today_missing_degrades_all():
    """今日原料缺失：整日 unknown + 根因注记（不伪 0）。"""
    built = assemble_rows(date="2026-10-23", today_by=None,
                          prev_by={"机器人": _theme_row(["600001"])},
                          prev_date="2026-10-22", count_hist={},
                          prev_stage_map=None, prev_state_map=None,
                          leader_states={}, panic_by={},
                          today_missing_reason="当日 stock rows 缺失")
    assert all(r["stage"] == "unknown" for r in built["rows"])
    assert built["degraded"]


def test_version_registered():
    assert THEME_CYCLE_VERSION == "v1"
