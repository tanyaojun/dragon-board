# -*- coding: utf-8 -*-
"""题材周期 v1（theme-cycle，2026-10-25）：题材-日炒作周期的确定性判定。

预登记：docs/hotlist-jev/theme-cycle-v1-preregistration.md（判据表 §四逐字冻结；
改门=新代际 v2+用户批准）。本模块为纯函数层，零 DB 零 IO；原料由
operations/theme_cycle.py 从单源取齐传入（mainTheme∧leadStatus 涨停名单 /
jiuyan_streak_map / day_status_of / 治理层 familyLinks 经 mainTheme 自动生效）。

定位（预登记 §一）：KPL 题材=外部事件驱动视角，与板块节点（产业链内部驱动，
家数锚八档）并存互为对照，两套语言不合并不互写判据（题材≠板块，用户裁定）。
方法论锚=龙头轨迹：启动→主升浪（龙头角逐）→转弱势（龙头断板）→弱转强
（人气股反包/新标杆）| 终结者（再无新龙崛起）。

哲学（板块节点/大盘弱转强同款）：转折强才是真强——昨日非转弱不贴弱转强标；
全部判据只用可数证据；fail-visible 不伪 0（n0=None=不可判，绝不拿 0 冒充冰点）。
状态机跨日成链：cycleState {cycleN, weakDays} 逐日递归（回填升序天然成链，
单日重算读昨日落库行——同板块节点 prev_node 范式）。
"""
from __future__ import annotations

from typing import Any

THEME_CYCLE_VERSION = "v1"

# 阶段枚举与优先级（预登记 §四：从高到低，命中即定档；改动须新代际）
STAGE_ORDER = ("wzs", "terminator", "weakening", "mainline", "emerging",
               "normal", "unknown")
STAGE_LABELS_CN = {
    "wzs": "弱转强", "terminator": "终结者", "weakening": "转弱",
    "mainline": "主升浪", "emerging": "启动", "normal": "平淡", "unknown": "不可判",
}

# 阈值（预登记 §四冻结；2026-10-25 用户按推荐批准）
TERMINATOR_WINDOW = 3        # 转弱后第 N 个交易日无复活判终结（prevWeakDays≥N-1）
EMERGING_MIN_ZT = 4          # 启动门=题材内涨停 >3 只（用户裁定「超过 3 只」）
NEW_BENCHMARK_STREAK = 3     # 新连板标杆=真连板 ≥3（低位首板不触发，方法论）
POPULAR_STREAK_MIN = 2       # 人气股池=曾真连板 ≥2（boardHeight≥2 窗口池）
PANIC_DT_MIN = 2             # 恐慌注记：人气股跌停 ≥2 只
PANIC_MEDIAN_PCT = -5.0      # 或中位跌幅 ≤ -5%
DEMON_STREAK_MIN = 5         # 妖股注记：龙头真连板 ≥5
DEMON_BOARD_MAX = 3          # 且当日题材内封板 ≤3（摆脱板块独走）
N5_N10_HIGH_PCT = 0.8        # N5/N10 对照列高位标记（不进门，用户裁定③）


def _leader_desc(leader: dict[str, Any] | None) -> str:
    if not leader:
        return "无"
    name = leader.get("name") or leader.get("code") or "?"
    streak = leader.get("streak")
    return f"{name}" + (f"（{streak} 板）" if isinstance(streak, int) else "（板数不可考）")


def classify_theme_day(*, n0: int | None, n1: int | None,
                       count_hist: list[int], n5_hist: list[int], n10_hist: list[int],
                       leader: dict[str, Any] | None, leader_state: str | None,
                       max_streak: int | None,
                       rewrap_codes: list[dict[str, Any]],
                       benchmark_codes: list[dict[str, Any]],
                       prev_stage: str | None, prev_weak_days: int,
                       panic: dict[str, Any] | None,
                       kpl_zt_count: int | None = None) -> dict[str, Any]:
    """单题材-日周期判定（预登记 §四判据表逐字实现）。

    返回 {stage, basis, notes, events, n5Pct, n10Pct, weakDays}。
    可考性约定：n0=None=今日名单不可考→unknown 不伪 0；n1=None=昨日不可考；
    leader_state=None=龙头续断不可考（停牌/数据洞，不算断板也不算续板）；
    prevStage=None=昨日文档缺失（弱转强/终结不贴标，注记）。
    rewrap_codes/benchmark_codes：operations 层已算好的反包/新标杆明细
    [{code,name,streak,time}]（判定与事件流共用一份，不双算）。
    """
    basis: list[str] = []
    notes: list[str] = []
    events: list[dict[str, Any]] = []
    weak_days = 0
    n5_pct = _pct_of(n5_hist, n0)
    n10_pct = _pct_of(n10_hist, n0)

    if n0 is None:
        notes.append("今日题材涨停名单不可考，周期不可判（不伪装平淡）")
        return {"stage": "unknown", "basis": basis, "notes": notes, "events": events,
                "n5Pct": n5_pct, "n10Pct": n10_pct, "weakDays": None}

    has_rewrap = bool(rewrap_codes)
    has_benchmark = bool(benchmark_codes)
    has_new_start = n0 >= EMERGING_MIN_ZT
    state_txt = {"sealed": "续板", "broken": "断板", "suspended": "停牌",
                 "unknown": "状态不可考", "none": "昨日无龙头"}.get(leader_state, "不可考")

    # 1 弱转强：昨日=转弱 且今日反包/新标杆（昨日档不可考不贴标，防标签通胀）
    if prev_stage == "weakening" and (has_rewrap or has_benchmark):
        basis.append("昨日节点=转弱")
        if has_rewrap:
            basis.append(f"人气股反包 {len(rewrap_codes)} 只"
                         f"（{rewrap_codes[0].get('name')} 等）")
        if has_benchmark:
            basis.append(f"新连板标杆 ≥{NEW_BENCHMARK_STREAK} 板 {len(benchmark_codes)} 只"
                         f"（{benchmark_codes[0].get('name')} 等）")
        events.append({"type": "wzs", "cn": "弱转强",
                       "detail": (f"反包{len(rewrap_codes)}只" if has_rewrap else "")
                                  + ("；" if has_rewrap and has_benchmark else "")
                                  + (f"新标杆{len(benchmark_codes)}只" if has_benchmark else "")})
        return {"stage": "wzs", "basis": basis, "notes": notes, "events": events,
                "n5Pct": n5_pct, "n10Pct": n10_pct, "weakDays": 0}

    # 2 终结者：转弱后第 N 个交易日无任何复活（prevWeakDays 链上累积）
    if prev_stage == "weakening" and prev_weak_days >= TERMINATOR_WINDOW - 1 \
            and not (has_rewrap or has_benchmark or has_new_start):
        basis.append(f"转弱后第 {TERMINATOR_WINDOW} 个交易日无反包/新标杆/新启动"
                     f"（涨停 {n0} 家）")
        events.append({"type": "terminator", "cn": "终结者", "detail": "再无新龙崛起"})
        return {"stage": "terminator", "basis": basis, "notes": notes, "events": events,
                "n5Pct": n5_pct, "n10Pct": n10_pct, "weakDays": None}

    # 3 转弱：龙头断板（真金考验；停牌不算断板）
    if leader_state == "broken":
        basis.append(f"龙头断板（{_leader_desc(leader)}）")
        events.append({"type": "broken", "cn": "龙头断板",
                       "detail": _leader_desc(leader)})
        if n0 >= EMERGING_MIN_ZT:
            notes.append(f"高量换血：龙头断板但今日涨停 {n0} 家，换血观察")
        return {"stage": "weakening", "basis": basis, "notes": notes, "events": events,
                "n5Pct": n5_pct, "n10Pct": n10_pct,
                "weakDays": (prev_weak_days + 1) if prev_stage == "weakening" else 1}

    # 4 主升浪：昨日龙头今日续板且真连板≥2（龙头角逐进行中）
    if leader_state == "sealed" and isinstance(_streak_of(leader), int) \
            and _streak_of(leader) >= 2:
        basis.append(f"龙头续板（{_leader_desc(leader)}，角逐进行中）")
        events.append({"type": "extend", "cn": "龙头续板",
                       "detail": f"{_leader_desc(leader)}",
                       "time": leader.get("time")})
        _append_n5n10(basis, n5_pct, n10_pct)
        return {"stage": "mainline", "basis": basis, "notes": notes, "events": events,
                "n5Pct": n5_pct, "n10Pct": n10_pct, "weakDays": 0}

    # 5 启动：涨停 >3 只且龙头未成形/换血（全是首板也算启动——用户裁定）
    if n0 >= EMERGING_MIN_ZT:
        if max_streak == 1:
            basis.append(f"今日涨停 {n0} 家全是首板（首板潮启动）")
        else:
            basis.append(f"今日涨停 {n0} 家（龙头未成形/换血，最高 {max_streak} 板）")
        events.append({"type": "emerging", "cn": "题材启动",
                       "detail": f"涨停 {n0} 家"})
        return {"stage": "emerging", "basis": basis, "notes": notes, "events": events,
                "n5Pct": n5_pct, "n10Pct": n10_pct, "weakDays": 0}

    # 6 平淡（含 terminator 后未复活的延续：终结是周期终态，出行域退出自然沉没）
    if prev_stage == "terminator":
        basis.append(f"终结延续（涨停 {n0} 家，未复活）")
    else:
        basis.append(f"涨停 {n0} 家、龙头{state_txt}，未命中周期判据")
    return {"stage": "normal", "basis": basis, "notes": notes, "events": events,
            "n5Pct": n5_pct, "n10Pct": n10_pct, "weakDays": 0}


def _streak_of(leader: dict[str, Any] | None) -> Any:
    return (leader or {}).get("streak")


def _pct_of(hist: list[int], cur: int | None) -> float | None:
    """cur 在 hist 中的分位（0-1）；样本 <5 不可算（对照列，None 如实）。"""
    vals = [v for v in hist if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(vals) < 5 or not isinstance(cur, (int, float)) or isinstance(cur, bool):
        return None
    return round(sum(1 for v in vals if v < cur) / len(vals), 3)


def _append_n5n10(basis: list[str], n5_pct: float | None, n10_pct: float | None) -> None:
    """N5/N10 对照列注记（只落列不进门——用户裁定③；高位时标注）。"""
    parts = []
    if n5_pct is not None:
        parts.append(f"N5 {n5_pct:.0%}" + ("↑高位" if n5_pct >= N5_N10_HIGH_PCT else ""))
    if n10_pct is not None:
        parts.append(f"N10 {n10_pct:.0%}" + ("↑高位" if n10_pct >= N5_N10_HIGH_PCT else ""))
    if parts:
        basis.append("家数分位对照（不进门）：" + "、".join(parts))


def append_notes_and_events(row: dict[str, Any], *, pool_codes: set[str],
                            panic: dict[str, Any] | None,
                            leader: dict[str, Any] | None, n0: int | None) -> None:
    """恐慌/妖股注记（不改档）——纯行内加工，判档后调用。"""
    if panic and (panic.get("dtN", 0) >= PANIC_DT_MIN
                  or (panic.get("medianPct") is not None
                      and panic["medianPct"] <= PANIC_MEDIAN_PCT)):
        row["notes"].append(
            f"恐慌蔓延：人气股跌停 {panic.get('dtN', 0)} 只、中位跌幅 "
            f"{panic.get('medianPct')}%")
        row["events"].append({"type": "panic", "cn": "恐慌蔓延",
                              "detail": f"人气股跌停 {panic.get('dtN', 0)} 只"})
    streak = _streak_of(leader)
    if (isinstance(streak, int) and streak >= DEMON_STREAK_MIN
            and n0 is not None and n0 <= DEMON_BOARD_MAX):
        row["notes"].append(f"妖股形态：龙头 {streak} 板独走（题材内仅封 {n0} 家）")
        row["events"].append({"type": "demon", "cn": "妖股独走",
                              "detail": f"龙头 {streak} 板、题材封板 {n0} 家"})


def assemble_rows(*, date: str, today_by: dict[str, dict[str, Any]],
                  prev_by: dict[str, dict[str, Any]], prev_date: str | None,
                  count_hist: dict[str, list[tuple[str, int]]],
                  prev_stage_map: dict[str, str] | None,
                  prev_state_map: dict[str, dict[str, Any]] | None,
                  leader_states: dict[str, str],
                  panic_by: dict[str, dict[str, Any]] | None,
                  today_missing_reason: str | None = None) -> dict[str, Any]:
    """组装当日全部题材-日行（预登记 §四/§五）。

    today_by/prev_by：{题材: 名单行}（operations 层取齐：codes/names/leader/maxStreak/
    kplZtCount）；prev_by 缺题材键=昨日无涨停（合法 0）。prev_by=None=昨日原料缺失
    （n1/leaderState/prevStage 不可考）。count_hist：{题材: [(date, n)]} 严格早于今日。
    """
    themes: list[str] = []
    for src in (today_by or {}, prev_by or {}):
        for t in src:
            if t not in themes:
                themes.append(t)
    rows: list[dict[str, Any]] = []
    degraded: list[str] = []
    for theme in sorted(themes):
        trow = (today_by or {}).get(theme)
        prow = (prev_by or {}).get(theme)
        n0: int | None = len(trow["codes"]) if trow else (
            None if today_by is None else 0)
        n1: int | None = len(prow["codes"]) if prow else (
            None if prev_by is None else 0)
        hist_values = [n for _d, n in (count_hist or {}).get(theme, [])]
        leader = (trow or {}).get("leader")
        prev_leader = (prow or {}).get("leader")
        leader_state = leader_states.get(theme)
        if leader_state is None:
            if prev_by is None:
                leader_state = None           # 昨日原料缺失：不可考
            elif prev_leader is None:
                leader_state = "none"
            # else: operations 层 day_status_of 已给值（sealed/broken/suspended/unknown）
        prev_entry = (prev_state_map or {}).get(theme) or {}
        prev_stage = prev_entry.get("stage") if prev_state_map is not None else None
        prev_weak_days = int(prev_entry.get("weakDays") or 0)

        notes: list[str] = []
        if prev_by is None and prev_date is not None:
            notes.append("昨日名单不可考，弱转强/终结不贴标")
        if (prev_stage_map is not None and theme not in (prev_state_map or {})
                and prev_date is not None):
            notes.append("昨日周期档不可考（昨日文档缺失或题材不在场），弱转强不贴标")
        if trow is None:
            notes.append("今日题材无涨停（行由三日窗口并集保留）")

        cls = classify_theme_day(
            n0=n0, n1=n1, count_hist=hist_values,
            n5_hist=hist_values[-5:], n10_hist=hist_values[-10:],
            leader=leader, leader_state=leader_state,
            max_streak=(trow or {}).get("maxStreak"),
            rewrap_codes=(trow or {}).get("rewrapCodes") or [],
            benchmark_codes=(trow or {}).get("benchmarkCodes") or [],
            prev_stage=prev_stage, prev_weak_days=prev_weak_days,
            panic=(panic_by or {}).get(theme),
            kpl_zt_count=(trow or {}).get("kplZtCount"))
        notes.extend(cls["notes"])
        row = {
            "theme": theme,
            "stage": cls["stage"], "prevStage": prev_stage,
            "cycleN": int(prev_entry.get("cycleN") or 1) if prev_entry else 1,
            "weakDays": cls["weakDays"],
            "count": n0, "prevCount": n1,
            "countSeries": [[d, n] for d, n in (count_hist or {}).get(theme, [])]
                           + ([[date, n0]] if n0 is not None else []),
            "n5Pct": cls["n5Pct"], "n10Pct": cls["n10Pct"],
            "kplZtCount": (trow or {}).get("kplZtCount"),
            "leader": leader, "prevLeader": prev_leader,
            "leaderState": leader_state,
            "maxStreak": (trow or {}).get("maxStreak"),
            "popularN": (trow or {}).get("popularN"),
            "rewrapCodes": (trow or {}).get("rewrapCodes") or [],
            "benchmarkCodes": (trow or {}).get("benchmarkCodes") or [],
            "codes": (trow or {}).get("codes") or [],
            "events": cls["events"], "basis": cls["basis"], "notes": notes,
        }
        # 终结后再复活 → 新周期（cycleN+1，按龙头成形归 mainline/emerging 已在判据内）
        if prev_entry.get("stage") == "terminator" and row["stage"] in ("mainline", "emerging", "wzs"):
            row["cycleN"] = int(prev_entry.get("cycleN") or 1) + 1
            row["notes"].append(f"新周期开启（第 {row['cycleN']} 轮）")
            row["events"].append({"type": "newCycle", "cn": "新周期",
                                  "detail": f"终结后复活，第 {row['cycleN']} 轮"})
        append_notes_and_events(row, pool_codes=(trow or {}).get("poolCodes") or set(),
                                panic=(panic_by or {}).get(theme),
                                leader=leader, n0=n0)
        rows.append(row)
    if today_by is None:
        reason = today_missing_reason or "今日题材涨停名单不可考（整日降级）"
        degraded.append(f"{date} {reason}")
        for r in rows:
            r["notes"].append(f"今日不可考根因：{reason}")
            r["stage"] = "unknown"
    if not themes:
        degraded.append("三日窗口内无任何题材涨停记录")
    return {"rows": rows, "degraded": degraded}
