# -*- coding: utf-8 -*-
"""题材周期·龙头弱转强：观察池与事件流（v5 预登记 P1，纯计算零 DB）。

预登记：`docs/hotlist-jev/theme-cycle-leader-wzs-preregistration-20261101.md`
（2026-11-01 用户八条裁决 + 窗位裁决「严格 3 日回溯」）。本模块只做确定性口径：
观察池成员、窗位、形式①人气股反包 / 形式②标杆晋级事件、跟风口径披露。盘后
THS 池确认收盘封板为唯一完成态（裁决 6）；盘中疑似态属 P2 日内层，本层不涉及。

窗位口径（严格 3 日回溯）：S=最近封板日，k=T−S−1（交易日数）——k=0 今日断板
（候选提示、今日不可反包）；k=1/2 断板后第 1/2 日（可反包，k=2 末窗）；k≥3 出池。
候选池=3 个封板日回溯（S∈{T-3,T-2,T-1}）。

数据源声明：TDX 日线为**未复权原始价**——断板日 D0 跌停判定按轨设除权哨兵
（main <−12% / growth <−25% 的更极端跌幅判「疑似除权失真」：不剔除、不入
limitDownExcluded，落 dataGaps 注记如实声明）；窗内逐日涨跌幅与报告次日溢价
同样未复权，除权日失真不伪装精确。

裁决锚：断板候选须真连板高度≥2（裁决 2/5，首板断板=跟风口径不入池）；断板日
未跌停（裁决 8）；新龙只认当日分轨空间龙一（裁决 5，非龙一反封=reboundState
"follower" 披露，不出事件）。fail-visible：原料缺失逐项披露，不伪 0 不静默。
"""
from __future__ import annotations

from typing import Any, Callable

# 断板日跌停阈值（沿用 v12「未跌停」条件，按轨）；除权哨兵见模块 docstring
LIMIT_DOWN_THRESHOLD = {"main": -9.9, "growth": -19.9}
EX_RIGHTS_SENTINEL = {"main": -12.0, "growth": -25.0}


def _pct_from_bars(bars: dict[str, dict] | None, date: str) -> float | None:
    """`date` 收盘涨跌幅（%）：C(date)/C(前一交易日)−1；缺料如实 None（不猜）。"""
    if not bars or date not in bars:
        return None
    dates = sorted(bars)
    i = dates.index(date)
    if i == 0:
        return None
    prev_close = bars[dates[i - 1]].get("close")
    close = bars[date].get("close")
    if not prev_close or not close:
        return None
    return round((close / prev_close - 1) * 100, 2)


def _next_bar_day(bars: dict[str, dict] | None, after: str) -> str | None:
    """bars 内严格晚于 `after` 的最早交易日（=断板日 D0 的逐股近似）。"""
    if not bars:
        return None
    later = [d for d in sorted(bars) if d > after]
    return later[0] if later else None


def build_leader_wzs(
    date: str,
    *,
    pool_days: list[str],
    today_sealed: set[str] | None,
    pool_members: dict[str, dict[str, dict[str, str | None]]],
    streaks_by_day: dict[str, dict[str, int]],
    streaks_today: dict[str, int],
    leader_rows: list[dict] | None,
    bars_by_code: dict[str, dict[str, dict] | None],
    segment_fn: Callable[[Any], str | None],
    member_states: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """观察池 + 形式①/②事件流（盘后口径）。

    入参（全部由 operations 层单源取齐）：
      pool_days      封板回溯日**升序** [T-3, T-2, T-1]（不足 3 日=早期历史，如实降窗）
      today_sealed   当日全市场封板集合（6 位码）；None → 整日降级
      pool_members   {S: {board: {code6: name}}}——各回溯日封板成员（韭研 final ∩ THS）
      streaks_by_day {S: {code6: streak}}——回溯日真连板高度（最近封板日口径）
      streaks_today  {code6: streak}——当日真连板
      leader_rows    day_leader_rows(T, space_mode, pool_dates=pool_days) 事实行
      bars_by_code   {code6: bars|None}——覆盖窗内逐日收盘（逆势表现 + D0 跌停判定）
      segment_fn     轨别纯函数（main/growth）

    返回 (pool_rows, events, meta)；meta.status="degraded" 时前两者为空。
    """
    if today_sealed is None:
        return [], [], {"status": "degraded",
                        "reason": "当日 THS 池缺失，封板不可二分（fail-visible）"}
    if leader_rows is None:
        return [], [], {"status": "degraded",
                        "reason": "龙一结构行缺失（THS 池缺失，fail-visible）"}

    meta: dict[str, Any] = {"status": "ok", "poolDays": list(pool_days)}
    gaps: list[str] = []
    if len(pool_days) < 3:
        gaps.append(f"封板回溯日不足 3 日（实得 {len(pool_days)}）：早期历史窗口如实缩短")
    if not streaks_today:
        gaps.append("当日真连板映射缺失：续板/标杆高度不可考（fail-visible）")

    leader_by_code = {str(r["code"]): r for r in leader_rows}
    low_height: list[str] = []
    limit_down: list[str] = []
    no_bars = 0

    def _k_of(s: str) -> int:
        return (len(pool_days) - 1) - pool_days.index(s)

    def _window_changes(code6: str, s: str) -> list[dict]:
        bars = bars_by_code.get(code6)
        if not bars:
            return []
        return [{"date": d, "pct": _pct_from_bars(bars, d)}
                for d in sorted(bars) if s < d < date]

    pool_by_code: dict[str, dict] = {}

    # 1) 回溯池（新→旧遍历：最近封板日优先，同股只留最近 S）
    for s in reversed(pool_days):
        for board, stocks in (pool_members.get(s) or {}).items():
            for code6, name in stocks.items():
                if code6 in pool_by_code:
                    continue
                k = _k_of(s)
                height = (streaks_by_day.get(s) or {}).get(code6)
                seg = segment_fn(code6)
                bars = bars_by_code.get(code6)
                if not bars:
                    no_bars += 1
                # 裁决 8：断板日（D0=S 次一交易日）跌停不入池（真金已崩），披露；
                # 未复权价除权哨兵（main<−12/growth<−25）：疑似除权失真不剔除，如实注记
                d0 = _next_bar_day(bars, s) if bars else None
                d0_pct = _pct_from_bars(bars, d0) if d0 else None
                thr = LIMIT_DOWN_THRESHOLD.get(seg or "main", -9.9)
                sent = EX_RIGHTS_SENTINEL.get(seg or "main", -12.0)
                if isinstance(d0_pct, (int, float)) and d0_pct <= sent:
                    gaps.append(f"{code6} {name or ''}(D0 {d0_pct:+.1f}%): "
                                "疑似除权/停牌复牌失真，跌停判定不可考，保留观察")
                elif isinstance(d0_pct, (int, float)) and d0_pct <= thr:
                    limit_down.append(
                        f"{code6} {name or ''}(D0 {d0_pct:+.1f}%)")
                    continue
                sealed_now = code6 in today_sealed
                ld = leader_by_code.get(code6)
                # 2026-11-18 天普案遗留：成员三态单源 day_status_of（ops 层取齐）——
                # 停牌/数据洞≠未封板（None 不伪装断板反包）；无 member_states（旧调用/
                # 池缺失日）保持旧二分口径。
                if height is None or (isinstance(height, int) and height < 2):
                    # 裁决 5：首板断板（高度<2/不可考）=跟风口径不入池；披露
                    low_height.append(
                        f"{code6} {name or ''}(高度{height if height is not None else '不可考'})")
                    continue
                mstate = (member_states or {}).get(code6)
                if mstate in ("suspended", "unknown"):
                    pool_by_code[code6] = {
                        "code": code6, "name": name, "board": board,
                        "segment": (ld or {}).get("segment") or seg,
                        "poolDay": s, "windowK": None, "height": height,
                        "streak": None, "gain10": (ld or {}).get("gain10"),
                        "isLeader": code6 in leader_by_code,
                        "leaderSealedToday": None,
                        "dayStatus": mstate,
                        "reboundState": "none",
                        "windowChanges": [],
                    }
                    continue
                if sealed_now:
                    if s == pool_days[-1]:
                        # 连续封板（未断板）：只在龙一行呈现（标杆晋级候选），此处跳过
                        continue
                    was_leader = code6 in leader_by_code
                    pool_by_code[code6] = {
                        "code": code6, "name": name, "board": board,
                        "segment": (ld or {}).get("segment") or seg,
                        "poolDay": s, "windowK": k, "height": height,
                        "streak": streaks_today.get(code6),
                        "gain10": (ld or {}).get("gain10"),
                        "isLeader": was_leader,
                        "leaderSealedToday": True,
                        **({"dayStatus": mstate} if mstate else {}),
                        "reboundState": ("leader" if was_leader else "follower"),
                        "windowChanges": _window_changes(code6, s),
                    }
                else:
                    pool_by_code[code6] = {
                        "code": code6, "name": name, "board": board,
                        "segment": (ld or {}).get("segment") or seg,
                        "poolDay": s, "windowK": k, "height": height,
                        "streak": None, "gain10": (ld or {}).get("gain10"),
                        "isLeader": code6 in leader_by_code,
                        "leaderSealedToday": False,
                        **({"dayStatus": mstate} if mstate else {}),
                        "reboundState": "none",
                        "windowChanges": _window_changes(code6, s),
                    }

    # 2) 龙一行并入（含回溯池未覆盖的续板龙一/断板龙一去重）
    for r in leader_rows:
        code6 = str(r["code"])
        if code6 in pool_by_code:
            continue
        # 2026-11-18：保留三态（suspended/unknown=None 不 coerce 成 False 伪装断板）
        sealed_now = r.get("leaderSealedToday")
        pd_ = r.get("poolDay")
        # review M1（2026-11-18）：反包窗只对**确判断板**（is False）开——停牌/数据洞
        # （None）无交易不算断板，与成员分支「停牌不开反包窗」同口径；旧档 bool 行为不变。
        row = {
            "code": code6, "name": r.get("name"), "board": r.get("board"),
            "segment": r.get("segment"),
            "poolDay": pd_,
            "windowK": (_k_of(pd_) if (sealed_now is False and pd_ in pool_days) else None),
            "height": (r.get("streak") if sealed_now
                       else (streaks_by_day.get(pd_ or "") or {}).get(code6)),
            "streak": (r.get("streak") if sealed_now else None),
            "gain10": r.get("gain10"),
            "isLeader": True,
            "leaderSealedToday": sealed_now,
            "dayStatus": r.get("dayStatus"),
            "reboundState": "none",
            "windowChanges": (_window_changes(code6, pd_)
                              if (sealed_now is False and pd_) else []),
        }
        pool_by_code[code6] = row

    # 3) 事件（裁决 5/6：完成态=收盘封板；新龙只认当日分轨空间龙一）
    events: list[dict] = []
    for row in pool_by_code.values():
        if row["isLeader"] and row["leaderSealedToday"]:
            if row["reboundState"] == "leader":
                events.append({
                    "type": "leaderRebound", "date": date,
                    "board": row["board"], "segment": row["segment"],
                    "code": row["code"], "name": row["name"],
                    "windowK": row["windowK"], "height": row["height"],
                    "gain10": row["gain10"]})
            ystreak = (row.get("streak") or 0) - 1
            if isinstance(row.get("streak"), int) and ystreak >= 3:
                # 裁决 2：标杆=真连板≥3；晋级=标杆续板（昨日≥3 → 今日 streak+1）
                events.append({
                    "type": "benchmarkAdvance", "date": date,
                    "board": row["board"], "segment": row["segment"],
                    "code": row["code"], "name": row["name"],
                    "streak": row["streak"], "prevStreak": ystreak,
                    "gain10": row["gain10"]})

    if gaps:
        meta["dataGaps"] = gaps
    if no_bars:
        meta.setdefault("dataGaps", []).append(
            f"{no_bars} 只回溯股日线不可考：窗内逆势表现缺失（fail-visible）")
    if low_height:
        meta["lowHeightExcluded"] = low_height
    if limit_down:
        meta["limitDownExcluded"] = limit_down
    if (streaks_today
            and not any(isinstance(st, int) and st - 1 >= 3
                        for st in streaks_today.values())):
        # 预登记 §4.3：全场无可考标杆（当日封板股中无昨日真连板≥3 者）如实注记，不伪 0
        meta.setdefault("notes", []).append(
            "今日无可考标杆：封板股中无昨日真连板≥3 者，benchmarkAdvance 无产出")

    rows = sorted(pool_by_code.values(),
                  key=lambda r: (r["board"], (r["windowK"] if r["windowK"]
                                              is not None else 99), r["code"]))
    return rows, events, meta
