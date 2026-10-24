# -*- coding: utf-8 -*-
"""板块节点 v1（sector-nodes，2026-10-24）：板块-日情绪节点的确定性判定。

预登记：docs/hotlist-jev/sector-nodes-v1-preregistration.md（判据表 §三；改门=新代际+用户批准）。
定位：大盘级「节点」列（analysis/hotlist/weak_to_strong，relayIndex≤40→≥50+结构确认）
下沉到板块-日粒度，同为确定性口径（零 token、可全历史回填）；本模块为纯函数层，
零 DB 零 IO，原料由 operations/sector_nodes.py 从单源取齐传入（day_leader_rows /
_promotion_stats / day_status_of / board_count_history，见预登记 §二）。

哲学（照搬大盘弱转强）：转折强才是真强——昨日非弱势（转弱/退潮）不贴弱转强标，
延续强归主升/发酵（防标签通胀）；全部判据只用池内可数证据；fail-visible 不伪 0：
参照日池缺失/板块改名 → 家数 None 不可考，涉判据不命中并注记，绝不拿 0 冒充。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import percentile_fraction

SECTOR_NODE_VERSION = "v1"

# 节点枚举与优先级（预登记 §三：从高到低，命中即定档；改动须新代际）
NODE_ORDER = ("wzs", "collapse", "ice", "weakening",
              "mainline", "fermenting", "brewing", "normal", "unknown")
NODE_LABELS_CN = {
    "wzs": "弱转强", "collapse": "退潮", "ice": "冰点", "weakening": "转弱",
    "mainline": "主升", "fermenting": "发酵", "brewing": "冒头", "normal": "平淡",
    "unknown": "不可判",
}
# 弱势节点（弱转强的合法昨日端点；与大盘 weak_to_strong「昨日 idx≤40」同哲学）
WEAK_NODES = ("weakening", "collapse")

# 分位锚参数（预登记 §三：样本<10 不可算 → 主升判据降级绝对阈 ≥5 家）
_PCT_MIN_SAMPLES = 10
_PCT_MAINLINE = 0.8
_MAINLINE_ABS_FLOOR = 5


def _leader_desc(leader: dict[str, Any] | None) -> str:
    if not leader:
        return "无"
    streak = leader.get("streak")
    name = leader.get("name") or leader.get("code") or "?"
    return f"{name}" + (f"（{streak} 板）" if isinstance(streak, int) else "（板数不可考）")


def _shape_first(shape: Any) -> int:
    if isinstance(shape, dict) and isinstance(shape.get("first"), int):
        return int(shape["first"])
    return 0


def classify_board_day(*, n0: int | None, n1: int | None, n2: int | None,
                       hist_values: list[int], leader: dict[str, Any] | None,
                       leader_state: str | None, prom_n: int | None,
                       prom_ge2: int | None, shape: Any,
                       prev_shape_first: int | None,
                       prev_node: str | None) -> dict[str, Any]:
    """单板块-日节点判定（预登记 §三判据表逐字实现）。

    返回 {node, basis, notes, countPct, prevCountPct, pctDegraded}。
    可考性约定：n0=None=今日封板集合不可二分（THS 池缺失）→ 节点不可判（unknown），
    绝不把缺料伪装成「0 家冰点」；n1/n2=None=参照日不可考（板块改名/池缺失），
    涉判据不命中；leader_state=None=龙头续断不可考（停牌/数据洞），不算断板也
    不算续板（停牌不算断板，v4 用户裁决）；prom_n=None=晋级链不可算，不伪 0。
    """
    basis: list[str] = []
    notes: list[str] = []
    pct0 = percentile_fraction(hist_values, n0)
    pct1 = percentile_fraction(hist_values, n1)
    pct_degraded = pct0 is None or pct1 is None
    first = _shape_first(shape)
    state_txt = {"sealed": "续板", "broken": "断板", "suspended": "停牌",
                 "unknown": "状态不可考", "none": "昨日无龙头"}.get(leader_state, "不可考")

    if n0 is None:
        notes.append("今日封板集合不可考，节点不可判（不伪装成冰点）")
        return {"node": "unknown", "basis": basis, "notes": notes,
                "countPct": None, "prevCountPct": None, "pctDegraded": True}

    # 1 弱转强：昨日∈{转弱,退潮} 且 家数回升 且 晋级>0 且（龙头续板 或 首板≥昨日×2）
    if (prev_node in WEAK_NODES and n1 is not None and n0 >= n1
            and prom_n is not None and prom_n >= 1):
        leader_ok = leader_state == "sealed"
        first_ok = prev_shape_first is not None and first >= 2 * prev_shape_first
        if leader_ok or first_ok:
            basis.append(f"昨日节点={NODE_LABELS_CN[prev_node]}")
            basis.append(f"家数 {n1}→{n0} 回升")
            basis.append(f"晋级 {prom_n} 家")
            basis.append(f"龙头续板（{_leader_desc(leader)}）" if leader_ok
                         else f"首板 {first} 家 ≥ 昨日 {prev_shape_first} 家×2")
            return {"node": "wzs", "basis": basis, "notes": notes,
                    "countPct": pct0, "prevCountPct": pct1, "pctDegraded": pct_degraded}

    # 2 退潮：腰斩 且 龙头断板 且 晋级=0
    if (n1 is not None and n1 >= 2 and n0 * 2 <= n1
            and leader_state == "broken" and prom_n is not None and prom_n == 0):
        basis.append(f"家数 {n1}→{n0} 腰斩")
        basis.append(f"龙头断板（{_leader_desc(leader)}）")
        basis.append("晋级 0 家")
        return {"node": "collapse", "basis": basis, "notes": notes,
                "countPct": pct0, "prevCountPct": pct1, "pctDegraded": pct_degraded}

    # 3 冰点：今日 0 家，或 ≤1 家且龙头断板且晋级 0
    if n0 == 0:
        basis.append("今日封板 0 家")
        return {"node": "ice", "basis": basis, "notes": notes,
                "countPct": pct0, "prevCountPct": pct1, "pctDegraded": pct_degraded}
    if n0 <= 1 and leader_state == "broken" and prom_n is not None and prom_n == 0:
        basis.append(f"仅封 {n0} 家且龙头断板、晋级 0")
        return {"node": "ice", "basis": basis, "notes": notes,
                "countPct": pct0, "prevCountPct": pct1, "pctDegraded": pct_degraded}

    # 4 转弱：昨日 ≥3 家 且（龙头断板 或 家数回落）
    if n1 is not None and n1 >= 3 and (leader_state == "broken" or n0 < n1):
        basis.append(f"龙头断板（{_leader_desc(leader)}）" if leader_state == "broken"
                     else f"家数 {n1}→{n0} 回落")
        return {"node": "weakening", "basis": basis, "notes": notes,
                "countPct": pct0, "prevCountPct": pct1, "pctDegraded": pct_degraded}

    # 5 主升：连续两日家数处近20日 P80↑ 且 龙头续板 且 二板以上晋级 ≥1
    core = (leader_state == "sealed" and prom_ge2 is not None and prom_ge2 >= 1)
    if core and pct0 is not None and pct1 is not None \
            and pct0 >= _PCT_MAINLINE and pct1 >= _PCT_MAINLINE:
        basis.append(f"家数 {n0}（{pct0:.0%} 分位）、昨日 {n1}（{pct1:.0%} 分位）连续两日 ≥P80")
        basis.append(f"龙头续板（{_leader_desc(leader)}）")
        basis.append(f"二板以上晋级 {prom_ge2} 家")
        return {"node": "mainline", "basis": basis, "notes": notes,
                "countPct": pct0, "prevCountPct": pct1, "pctDegraded": pct_degraded}
    if core and (pct0 is None or pct1 is None) and n1 is not None \
            and n0 >= _MAINLINE_ABS_FLOOR and n1 >= _MAINLINE_ABS_FLOOR:
        notes.append(f"家数分位样本不足（<{_PCT_MIN_SAMPLES}），主升判据降级绝对阈 "
                     f"≥{_MAINLINE_ABS_FLOOR} 家")
        basis.append(f"家数 {n1}→{n0} 高位（分位样本不足，绝对阈降级）")
        basis.append(f"龙头续板（{_leader_desc(leader)}）")
        basis.append(f"二板以上晋级 {prom_ge2} 家")
        return {"node": "mainline", "basis": basis, "notes": notes,
                "countPct": pct0, "prevCountPct": pct1, "pctDegraded": pct_degraded}

    # 6 发酵：连续两日家数递增
    if n2 is not None and n1 is not None and n0 > n1 > n2 and n0 >= 2:
        basis.append(f"家数 {n2}→{n1}→{n0} 连续两日递增")
        return {"node": "fermenting", "basis": basis, "notes": notes,
                "countPct": pct0, "prevCountPct": pct1, "pctDegraded": pct_degraded}

    # 7 冒头：前日 ≤1 家 且 今日 ≥3 家
    if n2 is not None and n2 <= 1 and n0 >= 3:
        basis.append(f"前日 {n2} 家 → 今日 {n0} 家放量首现")
        return {"node": "brewing", "basis": basis, "notes": notes,
                "countPct": pct0, "prevCountPct": pct1, "pctDegraded": pct_degraded}

    # 8 平淡
    basis.append(f"家数 {('不可考' if n1 is None else n1)}→{n0}、龙头{state_txt}，"
                 f"未命中节点判据")
    return {"node": "normal", "basis": basis, "notes": notes,
            "countPct": pct0, "prevCountPct": pct1, "pctDegraded": pct_degraded}


def assemble_rows(*, date: str, today_rows: list[dict[str, Any]] | None,
                  prev_rows: list[dict[str, Any]] | None, prev_date: str | None,
                  prev2_rows: list[dict[str, Any]] | None, prev2_date: str | None,
                  count_hist: dict[str, list[tuple[str, int]]],
                  prom: dict[str, Any], leader_status: dict[str, str],
                  prev_nodes: dict[str, str] | None,
                  today_unavailable_reason: str | None = None) -> dict[str, Any]:
    """组装当日全部板块-日行（预登记 §三/§四）。

    输入均为 operations 层从单源取齐的快照，本函数无 IO。板块覆盖=三日窗口并集
    （今日/昨日/前日 rows；「昨日有今日无」的退潮冰点板块必须在此）。
    count_hist：{board: [(date, n), ...]} 严格早于今日（board_count_history 原样）。
    n1/n2：参照日池 ok → 键缺=合法 0 家；参照日池缺失 → None 不可考（fail-visible）。
    today_rows=None=今日封板集合不可考，today_unavailable_reason 给根因（THS 池缺失
    或韭研 final 缺失——审计 P2-2：final 缺失但 THS ok 时 day_leader_rows 返回空列表
    且不报 None，operations 层须查 meta.jiuyanFinalFound 后置 None，否则窗口内全板块
    伪装成冰点）。
    """
    today_by = {str(r["board"]): r for r in (today_rows or [])}
    prev_by = {str(r["board"]): r for r in (prev_rows or [])}
    prev2_by = {str(r["board"]): r for r in (prev2_rows or [])}
    hist_by: dict[str, dict[str, int]] = {}
    for b, entries in (count_hist or {}).items():
        hist_by[str(b)] = {str(d): int(n) for d, n in entries}

    boards: list[str] = []
    for src in (today_by, prev_by, prev2_by):
        for b in src:
            if b not in boards:
                boards.append(b)
    rows: list[dict[str, Any]] = []
    degraded: list[str] = []
    for b in sorted(boards):
        trow = today_by.get(b)
        prow = prev_by.get(b)
        # 今日 THS 池缺失（today_rows=None）→ n0=None 不可考，不落「0 家」伪数
        n0: int | None = int(trow["boardN"]) if trow else (None if today_rows is None else 0)
        n1: int | None
        if prev_rows is None or prev_date is None:
            n1 = None
        else:
            n1 = hist_by.get(b, {}).get(prev_date, 0)
        n2: int | None
        if prev2_rows is None or prev2_date is None:
            n2 = None
        else:
            n2 = hist_by.get(b, {}).get(prev2_date, 0)
        hist_values = [n for _d, n in (count_hist or {}).get(b, [])]
        # day_leader_rows 行形状=平铺 code/name/streak/time（非嵌套 leader），此处组装成
        # leader dict 供展示与判定；code 缺失视为无龙头行
        def _leader_of(row: dict[str, Any] | None) -> dict[str, Any] | None:
            if row and row.get("code"):
                return {"code": str(row["code"]), "name": row.get("name"),
                        "streak": row.get("streak"), "time": row.get("time")}
            return None
        leader = _leader_of(trow)
        prev_leader = _leader_of(prow)
        shape = (trow or {}).get("ladderShape") if trow else (
            None if today_rows is None else {"first": 0, "two": 0, "threePlus": 0,
                                             "unknown": 0})
        prev_shape_first = _shape_first((prow or {}).get("ladderShape")) \
            if prow else None
        # 晋级链 ok 时缺键=合法 0 家（昨日该板块无封板股自然无晋级；板块改名归属错位
        # 是预登记 §六登记的已知局限，不在此伪装成「不可考」）
        prom_n = prom.get("byBoard", {}).get(b, 0) if prom.get("ok") else None
        prom_ge2 = prom.get("ge2ByBoard", {}).get(b, 0) if prom.get("ok") else None
        leader_state = leader_status.get(b)
        prev_node = (prev_nodes or {}).get(b)

        notes: list[str] = []
        if prev_rows is None and prev_date is not None:
            notes.append("昨日 THS 池缺失，昨日家数不可考")
        elif prev2_rows is None and prev2_date is not None:
            notes.append("前日 THS 池缺失，前日家数不可考")
        if leader_state is None:
            if prev_rows is None:
                notes.append("龙头续断不可考（昨日池缺失）")
            elif prev_leader is None:
                leader_state = "none"
            else:
                notes.append("龙头续断不可考（停牌/日线数据洞，不算断板）")
        if not prom.get("ok"):
            notes.append(f"晋级链不可算（{prom.get('reason') or '昨日池缺失'}），涉晋级判据未命中")
        if prev_nodes is None:
            notes.append("昨日节点不可考（昨日文档缺失），弱转强不贴标")
        if trow is None:
            notes.append("今日该板块无封板（行由三日窗口并集保留）")

        cls = classify_board_day(
            n0=n0, n1=n1, n2=n2, hist_values=hist_values, leader=leader,
            leader_state=leader_state, prom_n=prom_n, prom_ge2=prom_ge2,
            shape=shape, prev_shape_first=prev_shape_first, prev_node=prev_node)
        notes.extend(cls["notes"])

        broken_n = None
        if trow is not None:
            pt, ps = trow.get("prevTotal"), trow.get("prevStill")
            if isinstance(pt, int) and isinstance(ps, int) and pt - ps >= 0:
                broken_n = pt - ps
        rows.append({
            "board": b,
            "count": n0, "prevCount": n1, "prev2Count": n2,
            "countSeries": [[d, n] for d, n in (count_hist or {}).get(b, [])]
                           + ([[date, n0]] if n0 is not None else []),
            "countPct": round(cls["countPct"], 3) if cls["countPct"] is not None else None,
            "prevCountPct": round(cls["prevCountPct"], 3) if cls["prevCountPct"] is not None else None,
            "pctDegraded": cls["pctDegraded"],
            "leader": leader, "prevLeader": prev_leader, "leaderState": leader_state,
            "promN": prom_n, "promGe2": prom_ge2,
            "ladderShape": shape,
            "secondStreak": (trow or {}).get("secondStreak"),
            "zhabanN": (trow or {}).get("zhabanN") if trow else (
                None if today_rows is None else 0),
            "prevZhabanN": (trow or {}).get("prevZhabanN") if trow else None,
            "brokenN": broken_n,
            "indexAnchor": None,  # 板块指数锚未接入（二期）；恒 null，不伪装
            "node": cls["node"], "prevNode": prev_node,
            "basis": cls["basis"], "notes": notes,
        })
    if today_rows is None:
        reason = today_unavailable_reason or "THS 池缺失，封板集合不可二分"
        degraded.append(f"{date} {reason}（整日降级）")
        for r in rows:
            r["notes"].append(f"今日不可考根因：{reason}")
    if not boards:
        degraded.append("三日窗口内无任何板块封板记录")
    return {"rows": rows, "degraded": degraded}
