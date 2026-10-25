# -*- coding: utf-8 -*-
"""题材周期 v2（theme-cycle，2026-10-25）：题材级、以龙头为锚的四阶段炒作周期状态机。

预登记：docs/hotlist-jev/theme-cycle-v1-preregistration.md（判据表 §三；改门=新代际+用户
批准，冻结件与 classify_board_cycle 逐字对齐）。方法论来源：《第3课 题材周期》——
题材的锚点是龙头；主升浪（龙头角逐）→转弱势（真金的考验）→弱转强（新龙再崛起，
只有人气股反包与连板标杆≥3板两条路）→终结者（再无新龙崛起）。

**对象定义（v2 代际，用户裁定题材≠板块）**：题材=外部事件驱动（新闻/小作文/流量热度）
的炒作主题，对象载体=`themes` 集合概念标签（longhuvip 245+ 题材，行情总览「题材」列
同源）+ `theme_stock_mappings` 成分映射（一股可映射多题材，题材独立聚合重叠计入）；
**板块=产业链内部驱动（龙头带动板块跟风），由板块节点（sector_nodes 家数锚）覆盖，
两对象不同维度不互为对照**（v1 曾误用韭研 action 当日分组名为对象，与板块节点重叠，
已归档 data/backups/theme-cycle-v1-jiuyan-group-archive-20261025 后重建）。题材与板块
长期标签下承载多轮炒作，cycleN 跨终结递增区分（同题材名≠同题材周期）。

本模块纯函数零 IO：classify_board_cycle 接收抽象分组（题材/板块皆可）的当日状态与
昨日 cycleState，判据对象无关；题材维度的取数与题材归属在 operations/theme_cycle.py
（单源 themes/theme_stock_mappings/jiuyan_streak_map/day_status_of/snapshot_stock_rows）。

fail-visible：今日封板集合不可考 → 全题材 unknown、周期状态透传且终结窗计时暂停
（停牌哲学同款：不可判日不算推进）；绝不把缺料伪装成 normal/终结。
"""
from __future__ import annotations

from typing import Any

THEME_CYCLE_VERSION = "v2"

# 阶段枚举与优先级（预登记 §三.1/§三.3：从高到低，命中即定档；改动须新代际）
STAGE_ORDER = ("unknown", "wzs", "terminator", "weakening",
               "main_surge", "emerging", "normal")
STAGE_LABELS_CN = {
    "unknown": "不可判", "wzs": "弱转强", "terminator": "终结者",
    "weakening": "转弱势", "main_surge": "主升浪", "emerging": "启动",
    "normal": "平淡",
}

# 终结窗（预登记 §三.3 条 3：自进入转弱起 3 个可判交易日无精英反包无新标杆）
TERMINATOR_WINDOW_DAYS = 3
# 新连板标杆门槛（方法论原文：新龙必须是 3 连板或以上；1-2 板可能只是补涨）
NEW_BENCHMARK_MIN_STREAK = 3
# 妖股注记阈值（预登记 §三.4 草案值，盘感校准候选）
YAOGU_MIN_STREAK = 5
YAOGU_MAX_BOARD_N = 3
# 恐慌崩塌注记阈值（预登记 §三.4 草案值；-9.9% 判跌停不含 20cm/ST，局限 §六.6）
PANIC_MEDIAN_PCT = -5.0
PANIC_LIMIT_PCT = -9.9
PANIC_LIMIT_MIN_N = 2
# 精英判定的「曾真连板≥2」（辨识度高度代理，方法论：人气股=有号召力的高位股）
ELITE_MIN_PEAK_STREAK = 2


def _stock(code: str, name: str | None = None, streak: Any = None) -> dict[str, Any]:
    return {"code": str(code), "name": name, "streak": streak}


def _leader_txt(leader: dict[str, Any] | None) -> str:
    if not leader:
        return "无"
    name = leader.get("name") or leader.get("code") or "?"
    streak = leader.get("streak")
    return f"{name}" + (f"（{streak} 板）" if isinstance(streak, int) else "")


def _updated_members_peak(prev_state: dict[str, Any] | None,
                          today_codes: list[str],
                          streaks: dict[str, int | None]) -> dict[str, int]:
    """周期成员峰值表更新：今日封板股并入，peak=max(旧, 今日真连板)；streak 不可算不抬峰值。"""
    members = dict((prev_state or {}).get("membersPeak") or {})
    for c in today_codes:
        sv = streaks.get(c)
        cur = members.get(str(c), 0)
        members[str(c)] = max(cur, sv) if isinstance(sv, int) else cur
    return members


def classify_board_cycle(*, prev_state: dict[str, Any] | None,
                         today_codes: list[str] | None,
                         leader: dict[str, Any] | None,
                         cycle_leader_state: str | None,
                         streaks: dict[str, int | None],
                         prev_sealed: set[str] | None,
                         hotlist_codes: set[str] | None,
                         in_rewrap_pool: set[str],
                         bars_pct: dict[str, float | None] | None = None,
                         unavailable_reason: str | None = None) -> dict[str, Any]:
    """单板块-日周期判定（预登记 §三判据表逐字实现）。

    参数（operations 层从单源取齐）：
    - prev_state：昨日 cycleState（昨日文档行读出；None=无周期）。
    - today_codes：今日板块封板 code 列表；None=今日整日不可考（unknown 路径）。
    - leader：当日龙一（day_leader_rows 行龙一：真连板最高→封板最早）。
    - cycle_leader_state：周期现任龙一（prev_state.leaderCode）今日 day_status_of。
    - streaks：今日板块封板股真连板 {code: streak|None}（jiuyan_streak_map）。
    - prev_sealed：昨日板块封板集（None=昨日不可考，反包判定降级注记）。
    - hotlist_codes：今日热榜在榜 code 集（None=不可考，精英降级高度代理）。
    - in_rewrap_pool：今日该板块全市场反包池 code 集（仅徽标）。
    - bars_pct：brokenElite 各股今日涨跌幅（崩塌注记；None=缺 bars 不判）。

    返回 {stage, cycleN, prevStage, leader, leaderState, events, rewrapElite,
    rewrapPlain, newBenchmark, basis, notes, cycleState}。
    """
    basis: list[str] = []
    notes: list[str] = []
    events: list[dict[str, Any]] = []
    prev_stage = (prev_state or {}).get("stage")
    cycle_n_prev = (prev_state or {}).get("cycleN")

    # 条 0 unknown：今日封板集合不可考 → 状态透传、终结窗计时暂停（不推进 weakDays）
    if today_codes is None:
        note = unavailable_reason or "今日封板集合不可考，周期不可判（状态透传、计时暂停）"
        notes.append(note)
        if prev_state:
            return {"stage": "unknown", "cycleN": cycle_n_prev, "prevStage": prev_stage,
                    "leader": (prev_state or {}).get("leader") if prev_state else None,
                    "leaderState": None, "events": events, "rewrapElite": [],
                    "rewrapPlain": [], "newBenchmark": [], "basis": basis,
                    "notes": notes, "cycleState": dict(prev_state)}
        return {"stage": "unknown", "cycleN": None, "prevStage": None, "leader": None,
                "leaderState": None, "events": events, "rewrapElite": [],
                "rewrapPlain": [], "newBenchmark": [], "basis": basis, "notes": notes,
                "cycleState": None}

    today_set = {str(c) for c in today_codes}
    members_prev: dict[str, int] = dict((prev_state or {}).get("membersPeak") or {})

    # §三.2 机械反包（周期成员状态转移）与精英细分
    rewrap_elite: list[dict[str, Any]] = []
    rewrap_plain: list[dict[str, Any]] = []
    if prev_sealed is None and members_prev:
        notes.append("昨日封板集合不可考，反包判定降级（按昨日未封处理并注记）")
    for c in today_codes:
        code = str(c)
        if code not in members_prev:
            continue
        if prev_sealed is not None and code in prev_sealed:
            continue          # 昨日仍封 → 连续，非反包
        peak = members_prev.get(code, 0)
        sv = streaks.get(code)
        stock = _stock(code, None, sv if isinstance(sv, int) else None)
        stock["inMarketRewrapPool"] = code in in_rewrap_pool
        if peak >= ELITE_MIN_PEAK_STREAK:
            if hotlist_codes is None:
                stock["eliteDegraded"] = True
                rewrap_elite.append(stock)
            elif code in hotlist_codes:
                rewrap_elite.append(stock)
            else:
                rewrap_plain.append(stock)   # 曾≥2板但今日未在热榜：普通反包
        else:
            rewrap_plain.append(stock)       # 周期内仅首板：普通反包
    if any(s.get("eliteDegraded") for s in rewrap_elite):
        notes.append("热榜不可考（帧缺失），精英判定降级高度代理")
    elite_hit = bool(rewrap_elite)

    # §三.2 新连板标杆：今日封板股真连板≥3 且非周期现任龙一续板
    cycle_leader_code = str((prev_state or {}).get("leaderCode") or "")
    benchmark: list[dict[str, Any]] = []
    for c in today_codes:
        code = str(c)
        sv = streaks.get(code)
        if not isinstance(sv, int) or sv < NEW_BENCHMARK_MIN_STREAK:
            continue
        if cycle_leader_code and code == cycle_leader_code:
            continue          # 现任龙一续板是 main_surge continue，非新标杆
        benchmark.append(_stock(code, None, sv))
    benchmark_hit = bool(benchmark)
    elite_or_benchmark = elite_hit or benchmark_hit

    # 条 1 新周期开启（relaunch/burst）：无周期或 terminator + 今日有封板 + 精英或标杆
    no_cycle = prev_state is None or prev_stage == "terminator"
    if no_cycle and today_set and elite_or_benchmark:
        trigger = ([_stock(s["code"], s.get("name"), s.get("streak")) for s in rewrap_elite]
                   if elite_hit else
                   [_stock(s["code"], s.get("name"), s.get("streak")) for s in benchmark])
        # terminator relaunch：新周期成员重置（同板块名≠同题材周期）；无周期本就无旧成员
        members_new = (_updated_members_peak(None, today_codes, streaks)
                       if prev_stage == "terminator"
                       else _updated_members_peak(prev_state, today_codes, streaks))
        new_state = {"cycleN": (cycle_n_prev or 0) + 1, "stage": "main_surge",
                     "leaderCode": trigger[0]["code"], "leaderName": trigger[0].get("name"),
                     "peakStreak": max(members_new.values(), default=0),
                     "membersPeak": members_new,
                     "brokenElite": [], "weakDays": 0}
        events.append({"type": "burst", "stocks": trigger, "note": "周期开启"})
        if prev_stage == "terminator":
            events.append({"type": "relaunch", "stocks": trigger,
                           "note": "终结后新周期（源起弱转强）"})
        basis.append(f"精英反包 {len(rewrap_elite)} 只" if elite_hit
                     else f"新连板标杆 {len(benchmark)} 只（≥{NEW_BENCHMARK_MIN_STREAK} 板）")
        return {"stage": "main_surge", "cycleN": new_state["cycleN"],
                "prevStage": prev_stage, "leader": trigger[0], "leaderState": "sealed",
                "events": events, "rewrapElite": rewrap_elite, "rewrapPlain": rewrap_plain,
                "newBenchmark": benchmark, "basis": basis, "notes": notes,
                "cycleState": new_state}

    # 条 2 弱转强：昨日 weakening + 精英反包或新标杆
    if prev_stage == "weakening" and elite_or_benchmark:
        trigger = rewrap_elite if elite_hit else benchmark
        path = "rewrap_elite" if elite_hit else "new_benchmark"
        leader_pick = _stock(trigger[0]["code"], trigger[0].get("name"), trigger[0].get("streak"))
        new_state = {"cycleN": cycle_n_prev, "stage": "wzs",
                     "leaderCode": leader_pick["code"], "leaderName": leader_pick.get("name"),
                     "peakStreak": max((v for v in _updated_members_peak(
                         prev_state, today_codes, streaks).values()), default=0),
                     "membersPeak": _updated_members_peak(prev_state, today_codes, streaks),
                     "brokenElite": list((prev_state or {}).get("brokenElite") or []),
                     "weakDays": 0}
        events.append({"type": "wzs", "stocks": [_stock(s["code"], s.get("name"), s.get("streak"))
                                                   for s in trigger],
                       "note": "弱转强（" + ("人气股反包" if elite_hit else "新连板标杆") + "）"})
        basis.append("精英反包触发" if elite_hit else
                     f"新连板标杆触发（≥{NEW_BENCHMARK_MIN_STREAK} 板）")
        basis.append(f"昨日档=转弱势（weakDays {(prev_state or {}).get('weakDays')}）")
        return {"stage": "wzs", "cycleN": cycle_n_prev, "prevStage": prev_stage,
                "leader": leader_pick, "leaderState": "sealed", "events": events,
                "rewrapElite": rewrap_elite, "rewrapPlain": rewrap_plain,
                "newBenchmark": benchmark, "basis": basis, "notes": notes,
                "cycleState": new_state}

    # 条 3 终结者：weakening 且终结窗计满且无精英无标杆
    weak_days_prev = int((prev_state or {}).get("weakDays") or 0)
    if prev_stage == "weakening" and weak_days_prev + 1 >= TERMINATOR_WINDOW_DAYS \
            and not elite_or_benchmark:
        new_state = dict(prev_state or {})
        new_state.update({"stage": "terminator"})
        events.append({"type": "end", "stocks": [],
                       "note": f"周期终结（转弱 {weak_days_prev + 1} 个可判交易日无新龙）"})
        basis.append(f"转弱 {weak_days_prev + 1} 日无精英反包、无 ≥{NEW_BENCHMARK_MIN_STREAK} 板新标杆")
        return {"stage": "terminator", "cycleN": cycle_n_prev, "prevStage": prev_stage,
                "leader": (prev_state or {}).get("leader"), "leaderState": "broken",
                "events": events, "rewrapElite": rewrap_elite, "rewrapPlain": rewrap_plain,
                "newBenchmark": benchmark, "basis": basis, "notes": notes,
                "cycleState": new_state}

    # 条 4 转弱势：周期龙一断板（停牌/不可考不算断板；终态下 broken 是常态不再转弱）
    if cycle_leader_state == "broken" and prev_stage != "terminator":
        members_new = _updated_members_peak(prev_state, today_codes, streaks)
        broken_elite = list((prev_state or {}).get("brokenElite") or [])
        if members_prev.get(cycle_leader_code, 0) >= ELITE_MIN_PEAK_STREAK \
                and cycle_leader_code not in broken_elite:
            broken_elite.append(cycle_leader_code)
        weak_days = weak_days_prev + 1 if prev_stage == "weakening" else 1
        new_state = {"cycleN": cycle_n_prev, "stage": "weakening",
                     "leaderCode": (prev_state or {}).get("leaderCode"),
                     "leaderName": (prev_state or {}).get("leaderName"),
                     "peakStreak": max(members_new.values(), default=0),
                     "membersPeak": members_new, "brokenElite": broken_elite,
                     "weakDays": weak_days}
        events.append({"type": "leader_break",
                       "stocks": [_stock(cycle_leader_code,
                                         (prev_state or {}).get("leaderName"), None)],
                       "note": "龙一断板，题材转弱（真金的考验）"})
        basis.append(f"龙一断板（{_leader_txt((prev_state or {}).get('leader'))}）")
        basis.append(f"转弱第 {weak_days} 个可判交易日")
        row = {"stage": "weakening", "cycleN": cycle_n_prev, "prevStage": prev_stage,
               "leader": (prev_state or {}).get("leader"), "leaderState": "broken",
               "events": events, "rewrapElite": rewrap_elite, "rewrapPlain": rewrap_plain,
               "newBenchmark": benchmark, "basis": basis, "notes": notes,
               "cycleState": new_state}
        # 今日封板但仅 1-2 板（非精英非标杆）= 补涨尝试，记事件不改档
        if today_set:
            plain_attempt = [_stock(str(c), None, streaks.get(c))
                             for c in today_codes
                             if isinstance(streaks.get(c), int)
                             and streaks.get(c) < NEW_BENCHMARK_MIN_STREAK
                             and str(c) not in {s["code"] for s in rewrap_plain}
                             and str(c) not in {s["code"] for s in rewrap_elite}]
            if plain_attempt:
                events.append({"type": "plain_attempt", "stocks": plain_attempt,
                               "note": f"1-2 板补涨尝试（不足 {NEW_BENCHMARK_MIN_STREAK} 板标杆门槛，不改档）"})
        return row

    # 条 5 主升浪：周期龙一今日 sealed 且真连板 ≥2
    if cycle_leader_state == "sealed":
        leader_streak = streaks.get(cycle_leader_code)
        if isinstance(leader_streak, int) and leader_streak >= 2:
            members_new = _updated_members_peak(prev_state, today_codes, streaks)
            # 龙一接位：当日龙一 sealed 且更高 → 周期锚跟随当日龙一
            cur_leader = dict(leader) if (leader and leader.get("code")) else \
                _stock(cycle_leader_code, (prev_state or {}).get("leaderName"), leader_streak)
            # terminator 终态下龙一复活（≥2 板）：开新周期（relaunch，cycleN+1）
            relaunched = prev_stage == "terminator"
            new_state = {"cycleN": (cycle_n_prev or 0) + 1 if relaunched else cycle_n_prev,
                         "stage": "main_surge",
                         "leaderCode": str(cur_leader.get("code") or ""),
                         "leaderName": cur_leader.get("name"),
                         "peakStreak": max(members_new.values(), default=0),
                         "membersPeak": members_new if not relaunched else
                         _updated_members_peak(None, today_codes, streaks),
                         "brokenElite": [] if relaunched else
                         list((prev_state or {}).get("brokenElite") or []),
                         "weakDays": 0}
            events.append({"type": "continue",
                           "stocks": [_stock(cycle_leader_code,
                                             (prev_state or {}).get("leaderName"),
                                             leader_streak)],
                           "note": "龙一续板"})
            if relaunched:
                events.append({"type": "relaunch", "stocks": [], "note": "终态下龙一复活，新周期开启"})
            if prev_stage == "wzs":
                notes.append("新龙续板，弱转强确认")
            if prev_stage == "emerging":
                events.append({"type": "burst", "stocks": [], "note": "周期开启"})
            basis.append(f"龙一续板（{_leader_txt(cur_leader)}）")
            row = {"stage": "main_surge", "cycleN": new_state["cycleN"],
                   "prevStage": prev_stage,
                   "leader": cur_leader, "leaderState": "sealed", "events": events,
                   "rewrapElite": rewrap_elite, "rewrapPlain": rewrap_plain,
                   "newBenchmark": benchmark, "basis": basis, "notes": notes,
                   "cycleState": new_state}
            # 妖股注记（预登记 §三.4）
            if leader_streak >= YAOGU_MIN_STREAK and len(today_codes) <= YAOGU_MAX_BOARD_N:
                row["notes"].append(f"妖股形态：龙一 {leader_streak} 板独走"
                                    f"（板块封板仅 {len(today_codes)} 家），脱离板块效应")
            return row
        # 龙一 sealed 但真连板 <2（断板后普通反包/停牌回封）：1-2 板补涨语义不改档
        if prev_stage in ("weakening", "terminator"):
            events.append({"type": "plain_attempt",
                           "stocks": [_stock(cycle_leader_code,
                                             (prev_state or {}).get("leaderName"),
                                             leader_streak)],
                           "note": "龙一反包仅 1 板（补涨语义，不足标杆门槛）"})
            new_state = dict(prev_state or {})
            if prev_stage == "weakening":
                new_state["weakDays"] = weak_days_prev + 1
                basis.append("龙一反包 1 板，未达弱转强门槛（1-2 板只算补涨）")
            else:
                basis.append("终态下龙一反包 1 板，不足新周期门槛（记事件不改档）")
            return {"stage": prev_stage, "cycleN": cycle_n_prev, "prevStage": prev_stage,
                    "leader": (prev_state or {}).get("leader"), "leaderState": "sealed",
                    "events": events, "rewrapElite": rewrap_elite,
                    "rewrapPlain": rewrap_plain, "newBenchmark": benchmark,
                    "basis": basis, "notes": notes, "cycleState": new_state}
        # 周期进行中（main_surge/emerging/wzs）龙一 sealed 但高度<2：维持原档
        # （停牌回封/停牌不算断板哲学，注记不推进终结窗）
        notes.append("龙一续板但真连板高度 1（停牌回封等），周期档维持")
        return {"stage": prev_stage, "cycleN": cycle_n_prev, "prevStage": prev_stage,
                "leader": (prev_state or {}).get("leader"), "leaderState": "sealed",
                "events": events, "rewrapElite": rewrap_elite, "rewrapPlain": rewrap_plain,
                "newBenchmark": benchmark, "basis": basis, "notes": notes,
                "cycleState": dict(prev_state or {})}

    # 条 6 启动/常规开周期：今日有封板、prev 无周期或 terminator（未达条 1 精英/标杆门槛）
    if today_set and no_cycle:
        if prev_stage == "terminator":
            # 终态下封板但未达精英/标杆门槛（能到这里的都 <3 板且非精英反包）：
            # 记事件不改档（§三.3 条 3：1-2 板只是补涨）
            events.append({"type": "plain_attempt",
                           "stocks": [_stock(str(c), None, streaks.get(c))
                                      for c in today_codes],
                           "note": f"终态下封板不足 {NEW_BENCHMARK_MIN_STREAK} 板新周期门槛（补涨），维持终态"})
            basis.append("终态下封板未达新周期门槛，维持终态")
            return {"stage": "terminator", "cycleN": cycle_n_prev, "prevStage": prev_stage,
                    "leader": (prev_state or {}).get("leader"), "leaderState": "broken",
                    "events": events, "rewrapElite": rewrap_elite,
                    "rewrapPlain": rewrap_plain, "newBenchmark": benchmark,
                    "basis": basis, "notes": notes, "cycleState": dict(prev_state)}
        members_new = _updated_members_peak(prev_state, today_codes, streaks)
        cur_leader = dict(leader) if (leader and leader.get("code")) else None
        leader_streak = cur_leader.get("streak") if cur_leader else None
        if isinstance(leader_streak, int) and leader_streak >= 2:
            # 无周期今日龙一直接 2 板（跳过可见的 emerging）：常规开周期进主升浪
            new_state = {"cycleN": (cycle_n_prev or 0) + 1, "stage": "main_surge",
                         "leaderCode": str(cur_leader["code"]),
                         "leaderName": cur_leader.get("name"),
                         "peakStreak": max(members_new.values(), default=0),
                         "membersPeak": members_new, "brokenElite": [], "weakDays": 0}
            events.append({"type": "burst", "stocks": [], "note": "周期开启（龙一 2 板角逐成形）"})
            basis.append(f"龙一 {leader_streak} 板（{_leader_txt(cur_leader)}），周期开启")
            return {"stage": "main_surge", "cycleN": new_state["cycleN"],
                    "prevStage": prev_stage, "leader": cur_leader, "leaderState": "sealed",
                    "events": events, "rewrapElite": rewrap_elite,
                    "rewrapPlain": rewrap_plain, "newBenchmark": benchmark,
                    "basis": basis, "notes": notes, "cycleState": new_state}
        new_state = {"cycleN": (cycle_n_prev or 0) + 1, "stage": "emerging",
                     "leaderCode": str(cur_leader["code"]) if cur_leader else "",
                     "leaderName": cur_leader.get("name") if cur_leader else None,
                     "peakStreak": max(members_new.values(), default=0),
                     "membersPeak": members_new, "brokenElite": [], "weakDays": 0}
        events.append({"type": "burst", "stocks": [], "note": "周期开启（角逐未成形）"})
        basis.append(f"龙一首板（{_leader_txt(leader)}），龙头角逐未成形")
        return {"stage": "emerging", "cycleN": new_state["cycleN"], "prevStage": prev_stage,
                "leader": cur_leader, "leaderState": "sealed" if cur_leader else None,
                "events": events, "rewrapElite": rewrap_elite, "rewrapPlain": rewrap_plain,
                "newBenchmark": benchmark, "basis": basis, "notes": notes,
                "cycleState": new_state}

    # 条 7 平淡 / 周期中无封板兜底
    if prev_state is not None and not today_set:
        if prev_stage == "weakening":
            new_state = dict(prev_state)
            new_state["weakDays"] = weak_days_prev + 1
            basis.append(f"今日无封板，转弱第 {weak_days_prev + 1} 个可判交易日")
            return {"stage": "weakening", "cycleN": cycle_n_prev, "prevStage": prev_stage,
                    "leader": (prev_state or {}).get("leader"), "leaderState": "broken",
                    "events": events, "rewrapElite": [], "rewrapPlain": [],
                    "newBenchmark": [], "basis": basis, "notes": notes,
                    "cycleState": new_state}
        if prev_stage == "terminator":
            basis.append("终态维持（无封板；题材个股退出自选过程中）")
            return {"stage": "terminator", "cycleN": cycle_n_prev, "prevStage": prev_stage,
                    "leader": (prev_state or {}).get("leader"), "leaderState": "broken",
                    "events": events, "rewrapElite": [], "rewrapPlain": [],
                    "newBenchmark": [], "basis": basis, "notes": notes,
                    "cycleState": dict(prev_state)}
        # main_surge/emerging/wzs 中龙一停牌/不可考且板块无封板：维持原档（停牌不算断板）
        notes.append(f"龙一状态 {cycle_leader_state or '不可考'}（停牌/数据洞，不算断板），周期档维持")
        return {"stage": prev_stage, "cycleN": cycle_n_prev, "prevStage": prev_stage,
                "leader": (prev_state or {}).get("leader"),
                "leaderState": cycle_leader_state, "events": events,
                "rewrapElite": [], "rewrapPlain": [], "newBenchmark": [],
                "basis": basis, "notes": notes, "cycleState": dict(prev_state)}
    basis.append(f"无周期、今日封板 {len(today_codes)} 家" if today_set else "无周期、今日无封板")
    return {"stage": "normal", "cycleN": None, "prevStage": prev_stage, "leader": None,
            "leaderState": None, "events": events, "rewrapElite": [],
            "rewrapPlain": [], "newBenchmark": [], "basis": basis, "notes": notes,
            "cycleState": None}


def panic_note(broken_elite: list[str], bars_pct: dict[str, float | None]) -> str | None:
    """人气股崩塌注记（预登记 §三.4）：brokenElite 中位涨跌幅 ≤−5% 或 ≤−9.9% 家数≥2。"""
    pcts = [bars_pct[c] for c in broken_elite
            if isinstance(bars_pct.get(c), (int, float))]
    if len(pcts) < 2:
        return None
    pcts_sorted = sorted(pcts)
    median = pcts_sorted[len(pcts_sorted) // 2] if len(pcts_sorted) % 2 else \
        (pcts_sorted[len(pcts_sorted) // 2 - 1] + pcts_sorted[len(pcts_sorted) // 2]) / 2
    limit_n = sum(1 for p in pcts if p <= PANIC_LIMIT_PCT)
    if median <= PANIC_MEDIAN_PCT or limit_n >= PANIC_LIMIT_MIN_N:
        return (f"人气股崩塌（中位 {median:+.1f}%，收盘≤{PANIC_LIMIT_PCT}% 共 {limit_n} 只），"
                f"恐慌蔓延警示")
    return None
