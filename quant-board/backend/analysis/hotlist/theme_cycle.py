# -*- coding: utf-8 -*-
"""题材周期显式状态机（v5 预登记 §五，P2 立项 v2 裁决 2026-11-02，纯计算零 DB）。

四态词表（每板块×轨一个当前态）：主升 mainrise / 转弱 weakening / 弱转强 wzs /
终结 terminal。输入=sector_nodes 节点 + P1 事件流（hotlist_jev_leader_wzs）+
龙一结构事实（day_leader_rows space_mode，`rank_board_stocks_seal` v12 复合键，
与【题材龙头】打标链同源——P2 立项 §三.1 零新增口径）+ P1 观察池在位（Q4:A
窗满复用 P1 池窗）。确定性、零 token、全历史可重放。

九条裁决锚（2026-11-02 用户逐条闭合，docs/.../theme-cycle-leader-wzs-p2-plan-20261102.md）：
- Q1=B 初始态按首日节点直接定态（映射见 `initial_state`；ice 首日归转弱——终态
  只能由「窗满+ice」迁移产生，Q3:A 终态吸收性约束下首日定终态=死锁）；
- Q2=A 创高度新高=个股 10 日 gain10 创近 20 日新高（由操作层以日线计算传入，
  本层只消费布尔）；
- Q3=A 终结=终态（吸收态，本期不可迁出）；
- Q4=A 观察窗满复用 P1 池窗：板块×轨当日观察池无 k∈{0,1,2} 行即窗满；
- 迁移优先级：弱转强事件 > 终结（窗满+ice）> 转弱 > 主升（事件=新龙再崛起，
  语义最具体优先；同日事件与转弱不可能并存——事件要求龙一今日封板）。

fail-visible：每次迁移落痕（from/to/trigger/evidence）；无证据不得迁移；
节点/龙一/事件缺位如实记 evidence，不伪 0 不静默。
"""
from __future__ import annotations

from typing import Any

STATES = ("mainrise", "weakening", "wzs", "terminal")
STATE_LABELS_CN = {"mainrise": "主升", "weakening": "转弱",
                   "wzs": "弱转强", "terminal": "终结"}

# 预登记 §五触发词表（节点语系沿用 sector_nodes v4）
UPTREND_NODES = ("brewing", "fermenting", "mainline")
WEAKEN_NODES = ("weakening", "collapse")
TERMINAL_NODE = "ice"

# 迁移触发词（落痕用）
TRIG_EVENT = "wzs_event"                # §4.4 事件命中（①人气股反包/②标杆晋级）
TRIG_WINDOW_ICE = "window_full_ice"     # 窗满 + 当日节点=ice（裁决 7：N=1 即终结）
TRIG_NODE_WEAK = "node_weakening"       # 节点∈{weakening, collapse}
TRIG_LEADER_BROKEN = "leader_broken"    # 空间龙一断板（开启 3 日观察窗）
TRIG_NODE_UPTREND = "node_uptrend"      # 节点∈{brewing, fermenting, mainline}
TRIG_LEADER_ADVANCE = "leader_advance"  # 空间龙一续板晋级（streak≥2 续板）
TRIG_GAIN10_HIGH = "gain10_new_high"    # 龙一 10 日涨幅创近 20 日新高（Q2:A）


def initial_state(node: str | None) -> str:
    """Q1=B：板块×轨首次出现时按当日节点直接定态。

    mainrise←{brewing,fermenting,mainline}；wzs←{wzs}（字面直定）；其余
    （weakening/collapse/normal/unknown/ice）→weakening——ice 不直定终态
    （Q3:A 吸收性下即死锁），终态只能经「窗满+ice」迁移产生。"""
    if node in UPTREND_NODES:
        return "mainrise"
    if node == "wzs":
        return "wzs"
    return "weakening"


def step_day(prev_state: str | None, *, node: str | None,
             event_types: list[str], leader_broken: bool,
             leader_advanced: bool, gain10_new_high: bool,
             window_open: bool, window_full: bool) -> tuple[str, dict | None]:
    """单日单板块×轨状态迁移（纯函数）。

    prev_state=None 表示首见（Q1=B 按节点定态，transition 记 init）。
    返回 (new_state, transition)；transition=None 表示未迁移。
    """
    event_hit = bool(event_types) and prev_state != "terminal"

    if prev_state is None:
        st = initial_state(node)
        return st, {"from": None, "to": st, "trigger": "init",
                    "evidence": {"node": node}}

    if prev_state == "terminal":
        return prev_state, None   # Q3:A：终态吸收，本期不可迁出

    # 1) 弱转强事件（优先级最高：新龙再崛起=本阶段使命完成）
    if event_hit:
        return "wzs", {"from": prev_state, "to": "wzs",
                       "trigger": TRIG_EVENT,
                       "evidence": {"events": list(event_types), "node": node}}

    # 2) 终结：观察窗满且当日节点=ice（仅转弱态；裁决 7 N=1 即终结）
    if prev_state == "weakening" and window_open and window_full \
            and node == TERMINAL_NODE:
        return "terminal", {"from": prev_state, "to": "terminal",
                            "trigger": TRIG_WINDOW_ICE,
                            "evidence": {"node": node, "windowFull": True}}

    # 3) 转弱：空间龙一断板（开窗）或节点∈{weakening, collapse}
    if prev_state in ("mainrise", "wzs"):
        triggers: list[str] = []
        if node in WEAKEN_NODES:
            triggers.append(TRIG_NODE_WEAK)
        if leader_broken:
            triggers.append(TRIG_LEADER_BROKEN)
        if triggers:
            return "weakening", {"from": prev_state, "to": "weakening",
                                 "trigger": "+".join(triggers),
                                 "evidence": {"node": node,
                                              "leaderBroken": leader_broken}}

    # 4) 主升：节点回暖 / 龙一续板晋级 / gain10 创新高（转弱、弱转强两态可迁入）
    if prev_state in ("weakening", "wzs"):
        triggers = []
        if node in UPTREND_NODES:
            triggers.append(TRIG_NODE_UPTREND)
        if leader_advanced:
            triggers.append(TRIG_LEADER_ADVANCE)
        if gain10_new_high:
            triggers.append(TRIG_GAIN10_HIGH)
        if triggers:
            return "mainrise", {"from": prev_state, "to": "mainrise",
                                "trigger": "+".join(triggers),
                                "evidence": {"node": node,
                                             "leaderAdvanced": leader_advanced,
                                             "gain10NewHigh": gain10_new_high}}

    return prev_state, None


def replay(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """全历史重放（升序日期）。days 每元素：
    {"date": str,
     "nodes": {board: node},                       # sector_nodes 当日 rows
     "events": [{"board","segment","type"}],       # P1 事件流
     "leaders": [{"board","segment","code","name","leaderSealedToday","streak"}],
     "pool_boards": set[(board, segment)]}         # 当日观察池在位的板块×轨（k∈{0,1,2}）

    返回逐日记录列表（升序）：每元素 {"date", "rows": [逐板块×轨行]}。
    行含 state/prev/migrated/transition/evidence；窗口状态机内部维护。
    """
    states: dict[tuple[str, str], str] = {}
    windows: dict[tuple[str, str], bool] = {}   # 观察窗开启中（转弱因龙一断板开启）
    out: list[dict[str, Any]] = []

    for day in days:
        date = day["date"]
        nodes: dict[str, str | None] = day.get("nodes") or {}
        events = day.get("events") or []
        leaders = day.get("leaders") or []
        pool_boards = day.get("pool_boards") or set()

        ev_by_key: dict[tuple[str, str], list[str]] = {}
        for e in events:
            ev_by_key.setdefault((str(e["board"]), str(e.get("segment") or "main")),
                                 []).append(str(e["type"]))
        ld_by_key: dict[tuple[str, str], dict] = {}
        for r in leaders:
            ld_by_key[(str(r["board"]), str(r.get("segment") or "main"))] = r

        universe = (set(nodes)
                    | {b for (b, _s) in ld_by_key}
                    | {b for (b, _s) in ev_by_key})
        rows: list[dict[str, Any]] = []
        for board in sorted(universe):
            node = nodes.get(board)
            for segment in sorted({seg for (b, seg) in ev_by_key if b == board}
                                  | {seg for (b, seg) in ld_by_key if b == board}
                                  or {"main"}):
                key = (board, segment)
                ev_types = ev_by_key.get(key) or []
                ld = ld_by_key.get(key)
                leader_broken = bool(ld) and ld.get("leaderSealedToday") is False
                leader_advanced = bool(ld) and ld.get("leaderSealedToday") is True \
                    and isinstance(ld.get("streak"), int) and ld["streak"] >= 2
                gain10_high = bool(ld and ld.get("gain10NewHigh"))
                in_pool = key in pool_boards
                # Q4:A：窗满=转弱中且观察池无本板块×轨行（k≥3 出池即池空）
                window_full = bool(window_open := windows.get(key)) and not in_pool

                new_state, transition = step_day(
                    states.get(key), node=node, event_types=ev_types,
                    leader_broken=leader_broken, leader_advanced=leader_advanced,
                    gain10_new_high=gain10_high,
                    window_open=window_open, window_full=window_full)

                if transition and transition["trigger"] == TRIG_LEADER_BROKEN:
                    windows[key] = True      # 断板开窗
                if new_state == "weakening":
                    # 节点驱动入转弱（非断板）同样视为开窗：无断板则池本就空，
                    # 窗满即真（若连日无反包且节点冰点可终结），避免死锁
                    windows[key] = True
                if new_state in ("wzs", "mainrise"):
                    windows[key] = False     # 反包完成/证据回暖，窗使命结束
                states[key] = new_state

                rows.append({
                    "board": board, "segment": segment,
                    "state": new_state, "prev": transition["from"] if transition else None,
                    "migrated": transition is not None,
                    "transition": transition,
                    "evidence": {"node": node, "events": ev_types,
                                 "leaderSealedToday": (ld or {}).get("leaderSealedToday"),
                                 "streak": (ld or {}).get("streak"),
                                 "gain10NewHigh": gain10_high or None,
                                 "inPool": in_pool or None,
                                 "windowFull": window_full or None},
                })
        out.append({"date": date, "rows": rows})
    return out
