# -*- coding: utf-8 -*-
"""竞价试盘强度第三源（预登记 auction-leader-trial-strength-source-preregistration-20261115）。

选龙合同（2026-11-15 用户裁决；三档 + 公共前置门禁，生产默认严格）：
  root 粗桶板块竞价强度 board_amt = 每日每板 Σjj_amount（全板试盘股，缺值按 0）
  公共门禁 = 板块竞价涨幅均值（板内成员 jj_percent 均值）> 0（三档共用，情绪门）
  严格 = 中热 2-5亿 ∧ mid50_95 ∧ 撤减；中等 = 中热 ∧ mid50_95（姿态不限）；
  宽松 = 中热（个股档/姿态不限）。每 root 板按 jj_ratio 降序取前 max_per_board=3。
  生产默认 tier=strict（暂不切中等）；run() 与读口共用单一实现。

单一事实源（AGENTS §1.2-1；2026-11-18 raw 退役 sweep：原 bre 评估脚本共享纯函数
limit_pct/row_basis/st_name_fix/tier_jj/posture 下沉本模块单源，脚本随退役删除，
历史口径存档 docs auction-leader-vA3-base-rate-60d-evaluation-20261114.md）：
- board_tier/BOARD_TIERS/jj_ratio/board_amt/fnum + 下沉五函数由本模块承载（禁第二套）；
- root 映射全链 = jiuyan_board.board_index > 板块名称桥 > 近 60 日打标分组兜底
  （assign_root_boards，与线上读口 get_auction_trial / 评估脚本同口径）；
  桥接 helpers 单源在 services/jev/jiuyan_board（2026-11-15 自 api 下沉）。

公式与量纲见评估文档 auction-trial-premium-100d-evaluation-20261115.md §2.1：
个股 jj_ratio 归一化强度比（%）vs 板块 Σjj_amount 绝对额（元）；板块和是试盘
子集代理量、缺 jj_amount 按 0 计（低估）、jj_* 为 end_time 时点快照三点口径取舍。

fail-visible：trial_rows 缺/空 → 整源缺席 + reason（双源不受影响，不兜底选龙）；
未映射股排除计 unmappedN；无合格股 → 0 候选 + reason=no_qualified（非错误）。
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

from backend.services.jev import jiuyan_board, jiuyan_industry_root


def limit_pct(code: str) -> float:
    """涨跌幅限制（按代码前缀；900=沪 B 10%，北交所 43/83/87/92→30，30/68→20，其余 10）。
    原 bre 评估脚本单源，2026-11-18 退役下沉。"""
    if code[:2] in ("43", "83", "87", "92"):
        return 30.0
    if code[:2] in ("30", "68"):
        return 20.0
    return 10.0


def row_basis(code: str, r: dict) -> dict:
    """limit/preseal 口径单源：ST 探测 pre_percent∈[4.9,5.1]→limit 5；
    preseal = pre_percent ≥ limit×0.99（昨涨停）。"""
    lim = limit_pct(code)
    if 4.9 <= (r.get("pre_percent") or -1) <= 5.1:
        lim = 5.0
    return {"limit": lim, "preseal": (r.get("pre_percent") or 0) >= lim * 0.99}


def st_name_fix(rows: list[dict], names: dict[str, str]) -> int:
    """ST 名称补正：stock_names 名含 ST 且 limit≠5 → limit=5 + 重算 preseal/sealed。"""
    n = 0
    for r in rows:
        if "ST" in str(names.get(r["code"], "")).upper() and r["limit"] != 5.0:
            r["limit"] = 5.0
            r["preseal"] = (r.get("pre_percent") or 0) >= 5.0 * 0.99
            if "sealed" in r:
                r["sealed"] = (None if r.get("percent") is None
                               else r["percent"] >= 5.0 * 0.99)
            n += 1
    return n


def tier_jj(r: dict) -> str:
    """强度档：分母 PRESEAL 用 pre_percent 否则限价；top95/mid50_95/low_lt50/no_ratio。"""
    jp = r.get("jj_percent")
    denom = r.get("pre_percent") if r["preseal"] else r.get("limit")
    if jp is None or not denom:
        return "no_ratio"
    x = jp / denom * 100
    return "top95" if x >= 95 else ("mid50_95" if x >= 50 else "low_lt50")


def posture(r: dict) -> str:
    """姿态：末帧委买≥首帧=maintain 否则 decrease；缺值/NaN→no_data（不伪装）。"""
    f, l = r.get("first_amount"), r.get("last_amount")
    try:
        f, l = float(f), float(l)
    except (TypeError, ValueError):
        return "no_data"
    if not (math.isfinite(f) and math.isfinite(l)):
        return "no_data"
    return "maintain" if l >= f else "decrease"

# ── 板块竞价强度规则档（日 Σjj_amount，元；左闭右开）──
BOARD_TIERS = [("冷 <5000万", 5e7), ("温 5000万-2亿", 2e8), ("中热 2-5亿", 5e8),
               ("热 5-10亿", 1e9), ("过热 ≥10亿", float("inf"))]
TIER_MID_HOT = "中热 2-5亿"
# 三档（2026-11-15 用户裁决：公共均值门 + 生产默认严格暂不切中等）
TRIAL_TIER_STRICT = "strict"
TRIAL_TIER_MEDIUM = "medium"
TRIAL_TIER_LOOSE = "loose"
TRIAL_TIERS = (TRIAL_TIER_STRICT, TRIAL_TIER_MEDIUM, TRIAL_TIER_LOOSE)


def fnum(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    # 非有限值（NaN/±Inf）→ None（评审 2026-11-15：防 NaN 污染板 Σ 误档、
    # 防 NaN 透传 posture/比值；上游 json.loads 默许 NaN 字面量）
    return v if math.isfinite(v) else None


def board_tier(amt: float | None) -> str:
    """板块强度档；None（未分板块）→ 独立档，不进五档（fail-visible）。"""
    if amt is None:
        return "未分板块"
    for name, hi in BOARD_TIERS:
        if amt < hi:
            return name
    return BOARD_TIERS[-1][0]


def board_amt(rows: list[dict]) -> dict[str, float]:
    """每日每 root 板 Σjj_amount（全板试盘股）；缺值按 0 计（求和聚合取舍，
    评估文档 §2.1 口径警示 3）；board 空 → 不入和（未分板块不算强度）。"""
    out: dict[str, float] = {}
    for r in rows:
        b = r.get("board")
        if not b:
            continue
        out[b] = out.get(b, 0.0) + (fnum(r.get("jj_amount")) or 0.0)
    return out


def jj_ratio(jp: float | None, pre_percent: float | None,
             limit: float | None, preseal: bool) -> float | None:
    """竞价强度比（tier_jj 同锚）：PRESEAL 用 pre_percent，否则限价；缺值 → None。"""
    denom = pre_percent if preseal else limit
    if jp is None or not denom:
        return None
    return jp / denom * 100


def assign_root_boards(rows: list[dict], db: Any) -> dict:
    """root 板块全链（线上读口同口径单源）：direct > bridge > hist；primary 单值。

    就地写 r["board"]（未归属 None）；返回 jiuyan_board meta。rows 须含 code
    （6 位）与可选 bk_name。桥接原料 300s 进程内缓存（jiuyan_board 同规）。"""
    b_idx, b_meta = jiuyan_board.board_index(db)
    root_idx = jiuyan_industry_root.root_index(db)
    root_alias = jiuyan_industry_root.root_alias_map(db)
    bridge = jiuyan_board._bridge_maps(db)
    need: set[str] = set()
    for r in rows:
        c6 = r["code"]
        b = b_idx.get(c6)
        if b:
            r["board"] = b
            continue
        bb: list[str] = []
        for n in jiuyan_board._bridge_lookup(r.get("bk_name"), bridge["maps"], bridge["inds"]):
            rn = root_idx.get(n) or n
            if rn and rn not in bb:
                bb.append(rn)
        if bb:
            r["board"] = bb[0]
            continue
        r["board"] = None
        need.add(c6)
    if need and bridge["hist"]:
        hist = jiuyan_board._bridge_hist(bridge["hist"], need)
        for r in rows:
            # 仅兑底本行仍无归属的（need 是 code 级：同 code 跨日多行时，不得用
            # hist 覆盖其他日期已有 direct/bridge 归属的行——2026-11-15 第三源
            # 验收发现的跨日覆盖 bug，单日/全窗口径自此一致）
            if r["code"] in need and not r.get("board") and hist.get(r["code"]):
                seen: list[str] = []
                for n in hist[r["code"]]:
                    rn = root_alias.get(n, n)
                    if rn and rn not in seen:
                        seen.append(rn)
                if seen:
                    r["board"] = seen[0]
    return b_meta


def trial_strength_roster(db: Any, date: str, trial_rows: dict | None, *,
                          max_per_board: int = 3,
                          max_total: int | None = None,
                          tier: str = TRIAL_TIER_STRICT) -> tuple[list[dict], dict]:
    """第三源选龙（三档 + 公共均值门 + 每板前三）：run() 与读口共用单一实现（禁第二套）。

    公共前置门禁：板块竞价涨幅均值（jj_percent 均值）>0，三档共用；全缺→不满足。

    trial_rows = dict[code→试盘行具名字段]（run() 窗内采集 / kpl_bidding_series 派生日档）。
    返回 (rows, state)：rows = [{code, name, board, trialStrength:{boardAmt, btier,
    jjRatio, jjtier, posture, rank, boardTrialN}}]（板名升序→板内 rank 升序）；
    state = {state, date, mappedN, unmappedN, hotBoards:[{board,amt,n}], selectedN,
    reason?, cap?, truncatedN?}。max_total = 每日软上限（超限按全局 jj_ratio 降序
    截断并记账，fail-visible）。
    """
    state: dict = {"state": "ok", "date": date, "mappedN": 0, "unmappedN": 0,
                   "hotBoards": [], "selectedN": 0}
    if tier not in TRIAL_TIERS:
        raise ValueError(f"trial_strength_roster: 未知 tier {tier!r}")
    state["tier"] = tier
    state["meanGate"] = "board_jj_percent_mean>0"
    if max_total is not None:
        max_total = max(0, max_total)   # 负值钳 0（评审：截断记账不得虚增/负切片）
    if not trial_rows:
        return [], {**state, "state": "absent", "reason": "no_trial_rows"}
    rows: list[dict] = []
    for code, raw in trial_rows.items():
        c6 = str(code)[-6:]
        r = {"code": c6, **(raw or {})}
        r.update(row_basis(c6, r))   # limit/preseal 单源（含 ST 探测）
        rows.append(r)
    assign_root_boards(rows, db)
    bridge = jiuyan_board._bridge_maps(db)
    names = bridge.get("names") or {}
    # 桥原料降级留痕（评审 2026-11-15，§4.0）：stock_names 读失败 → ST 补正空转，
    # 名称类失败不像映射类有 unmappedN 可见——结构化透出，读口/run() 自然透传
    if bridge.get("sourceErrors"):
        state["bridgeDegraded"] = dict(bridge["sourceErrors"])
    # ST 名称修正（与评估脚本 main 同口径单源：非昨涨停 ST 行 pre_percent 探测
    # 不覆盖，靠 stock_names 名称补正 limit=5，防比值污染）
    st_name_fix(rows, names)
    mapped = [r for r in rows if r.get("board")]
    state["mappedN"] = len(mapped)
    state["unmappedN"] = len(rows) - len(mapped)
    amts = board_amt(rows)
    board_n = Counter(r["board"] for r in mapped)
    # 板块竞价涨幅均值（jj_percent，缺值跳过；全缺→None→门禁不满足，fail-visible）
    mean_vals: dict[str, list[float]] = {}
    for r in mapped:
        v = fnum(r.get("jj_percent"))
        if v is not None:
            mean_vals.setdefault(r["board"], []).append(v)
    board_mean = {b: sum(v) / len(v) for b, v in mean_vals.items()}
    state["hotBoards"] = [{"board": b, "amt": amts[b], "n": board_n[b]}
                          for b in sorted(amts) if board_tier(amts[b]) == TIER_MID_HOT]
    state["meanFilteredBoards"] = [b for b in sorted(amts)
                                   if board_tier(amts[b]) == TIER_MID_HOT
                                   and (board_mean.get(b) is None or board_mean[b] <= 0)]
    # 三档筛（公共均值门在前）：缺 jj_percent/first/last 自然排除，不伪装 0
    groups: dict[str, list[tuple[float, dict]]] = {}
    for r in mapped:
        b = r["board"]
        if board_tier(amts.get(b)) != TIER_MID_HOT:
            continue
        m = board_mean.get(b)
        if m is None or m <= 0:   # 公共前置门禁：板块竞价涨幅均值>0
            continue
        jt = tier_jj(r)
        po = posture(r)
        if tier == TRIAL_TIER_STRICT and not (jt == "mid50_95" and po == "decrease"):
            continue
        if tier == TRIAL_TIER_MEDIUM and jt != "mid50_95":
            continue
        ratio = jj_ratio(fnum(r.get("jj_percent")), r.get("pre_percent"),
                         r.get("limit"), r["preseal"])
        groups.setdefault(b, []).append((ratio, r))
    out: list[dict] = []
    for b in sorted(groups):
        gg = sorted(groups[b], key=lambda x: (-(x[0] or 0), x[1]["code"]))
        for rank, (ratio, r) in enumerate(gg[:max_per_board], 1):
            out.append({"code": r["code"], "name": names.get(r["code"]), "board": b,
                        "trialStrength": {"boardAmt": amts[b], "btier": TIER_MID_HOT,
                                          "jjRatio": round(ratio, 2),
                                          "jjtier": tier_jj(r), "posture": posture(r),
                                          "rank": rank, "boardTrialN": board_n[b]}})
    if max_total is not None and len(out) > max_total:
        out.sort(key=lambda r: (-r["trialStrength"]["jjRatio"], r["board"], r["code"]))
        state["cap"] = max_total
        state["truncatedN"] = len(out) - max_total
        out = out[:max_total]
        out.sort(key=lambda r: (r["board"], r["trialStrength"]["rank"]))
    state["selectedN"] = len(out)
    if not out:
        state["reason"] = "no_qualified"
    return out, state
