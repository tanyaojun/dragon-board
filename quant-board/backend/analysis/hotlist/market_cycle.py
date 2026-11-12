# -*- coding: utf-8 -*-
"""第4课·市场情绪周期：事件流纯计算层（P1，零 DB 零 token）。

预登记：`docs/hotlist-jev/market-cycle-preregistration-20261112.md`（2026-11-12 用户
七项裁决 + Q1–Q7 全批准冻结）。本模块只做确定性口径：市场空间龙一候选 enrichment、
分轨龙一选取、空间天花板、四大特征事件检测（E1 突破 / E2 压缩 / E3 崩塌 / E4 宽容），
以及 P2 市场级状态机（loss/ice/wzs/gain，`step_day`/`replay`，输入=事件流 only，零 token
全历史可重放）。

锚点（裁决 2）：市场空间龙一 = v12 复合口径作用于**全市场**候选池（今日封板 ∪ 近 3 日
封板，断板龙一在锚内）。排序键单源 = `theme_leader_ammo.rank_board_stocks_seal` /
`space_leaders_by_segment`（本模块只调用，不新造排序）；候选 enrichment 镜像
`theme_leader_baseline.day_leader_rows(space_mode=True)` 的构建步骤（height/跌停剔除/
低高度断板剔除），作用域从板块扩到全市场。

口径单源（裁决 3）：
- 跌停 = `core.limit_rules.is_limit_down_pct`（权威，含 0.2pp 容差；与题材链内联
  -9.9/-19.9 略有容差差，本模块统一用权威源，预登记 §3.3 冻结）。
- 大面 = 收盘较昨收 ≤ -5%（`jev_relay_index._broken_stats` 同源算式，BIG_FACE_PCT）。
- 空间天花板 = 全市场最高**真连板** maxBoard（`jiuyan_streak_map` 口径，板数跨轨可比）；
  回看窗 N=20 交易日（CEILING_WINDOW，裁决 3 冻结）。
- 连板语义一律 streak（2026-10-16 口径修正不复活）；区间高度 N天M板 仅展示。

fail-visible：原料缺失 → 事件不命中 + 结构化 reason（不伪 0、不静默、不阻断）。
事件主体（Q2=A）：v1 仅市场空间龙一（两轨各判，事件带 track）；≥4板高位群体命运
仅进监控表展示（P2），不入判据。两轨聚合（Q1=A）：任一轨命中即计入。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist.theme_leader_ammo import space_leaders_by_segment
from backend.core.limit_rules import is_limit_down_pct, limit_up_price

# ── 冻结口径常量（预登记 §三/§四，裁决 3）──
MARKET_CYCLE_VERSION = "v1"
CEILING_WINDOW = 20          # 空间天花板回看交易日数（N=20 冻结）
BIG_FACE_PCT = -5.0          # 大面口径：收盘较昨收 ≤-5%（_broken_stats 同源）
TOLERANCE_WINDOW = 2         # 企稳型观察窗：断板后 2 个交易日（原文「震荡两天」）


def ceiling_from_streaks(streaks: dict[str, Any]) -> dict[str, Any]:
    """真连板映射 → 空间天花板事实（maxBoard/≥3板家数）。

    只数 int（bool 显式排除）；无可用值 → maxBoard=None（fail-visible，不伪 0）。
    """
    vals = [v for v in streaks.values()
            if isinstance(v, int) and not isinstance(v, bool)]
    return {"maxBoard": max(vals) if vals else None,
            "threePlusN": sum(1 for v in vals if v >= 3),
            "counted": len(vals)}


def prepare_market_candidates(cands: list[dict], today_codes: set[str],
                              changes: dict[str, float | None]) -> tuple[list[dict], dict]:
    """全市场空间龙一候选 enrichment（镜像 day_leader_rows space_mode，纯函数）。

    入参 cands 每股已带 code/name/time/streak/days/boards/histStreak/poolDay（operations
    单源取齐）；today_codes=今日封板集；changes={code: 当日涨跌幅%|None}（断板候选用）。
    步骤（与题材链同序）：①断板不反包且今日跌停剔除（is_limit_down_pct 权威）；
    ②height=当日 streak 与近 3 日历史高度取大；③断板候选高度<2/不可考剔除（v12 龙头
    弱转强口径，首板断板=跟风不入锚）。返回 (kept, meta)；meta 披露剔除清单。
    涨跌幅不可考（None）→ 不剔除（不猜，fail-visible）。
    """
    meta: dict[str, Any] = {}
    hist_by_code: dict[str, int] = {}
    for c in cands:
        h = c.get("histStreak")
        if isinstance(h, int) and not isinstance(h, bool):
            hist_by_code[c["code"]] = max(h, hist_by_code.get(c["code"], h))

    limit_down: list[str] = []
    kept: list[dict] = []
    for c in cands:
        if c["code"] in today_codes:
            kept.append(c)
            continue
        pct = changes.get(c["code"])
        if is_limit_down_pct(pct, c["code"]):
            limit_down.append(f"{c.get('name') or c['code']}({pct:+.1f}%)")
        else:
            kept.append(c)
    if limit_down:
        meta["limitDownExcluded"] = limit_down

    for c in kept:
        hs = [h for h in (c.get("streak") if c["code"] in today_codes else None,
                          hist_by_code.get(c["code"]))
              if isinstance(h, int) and not isinstance(h, bool)]
        c["height"] = max(hs) if hs else None

    low_height: list[str] = []
    final: list[dict] = []
    for c in kept:
        if c["code"] in today_codes:
            final.append(c)
            continue
        h = c.get("height")
        if isinstance(h, int) and h >= 2:
            final.append(c)
        else:
            low_height.append(
                f"{c.get('name') or c['code']}(高度{h if h is not None else '不可考'})")
    if low_height:
        meta["lowHeightBrokenExcluded"] = low_height
    return final, meta


def pick_market_leaders(cands: list[dict]) -> dict[str, dict]:
    """分轨市场空间龙一（v12 排序键单源 space_leaders_by_segment）。

    返回 {segment: leader}（main/growth，某轨无候选则不出）。gain10 全缺的轨由
    operations 层披露降级（按首封时间选出），本函数只排序不降级。
    """
    return {seg: ld for seg, ld in space_leaders_by_segment(cands)}


def detect_breakthrough(date: str, today_max: int | None,
                        window: list[dict], stocks: list[dict]) -> dict | None:
    """E1 空间突破：今日 maxBoard > 近 N 日天花板（严格大于；持平=未突破）。

    window=[{date,maxBoard}] 回看窗（升序，不含今日）；无可用参照 → None（fail-visible）。
    stocks=今日最高板股（突破主体，operations 附 boardShape/一字注记）。稀缺事件，
    为 0 如实不产出（预登记 §四 E1）。
    """
    if not isinstance(today_max, int) or isinstance(today_max, bool):
        return None
    refs = [w["maxBoard"] for w in window
            if isinstance(w.get("maxBoard"), int) and not isinstance(w.get("maxBoard"), bool)]
    if not refs:
        return None
    ceiling = max(refs)
    if today_max <= ceiling:
        return None
    return {"type": "spaceBreakthrough", "date": date, "maxBoard": today_max,
            "prevCeiling": ceiling, "windowDays": len(refs), "stocks": stocks}


def detect_compress(date: str, today_3plus: int | None,
                    prev_3plus: int | None) -> dict | None:
    """E2 空间压缩：今日 ≥3板家数=0 且昨日 ≥1（3板以上归零转折，原文明确判据）。

    天花板下移不作事件（不发明阈值，预登记 §四 E2）；任一读数缺失 → None。
    """
    if not isinstance(today_3plus, int) or not isinstance(prev_3plus, int):
        return None
    if today_3plus == 0 and prev_3plus >= 1:
        return {"type": "spaceCompress", "date": date,
                "threePlusN": 0, "prevThreePlusN": prev_3plus}
    return None


def detect_collapse(date: str, track: str, anchor: dict | None,
                    fate_today: dict | None, fate_yesterday: dict | None) -> dict | None:
    """E3 高位崩塌（主体=昨日市场空间龙一，两轨各判）。

    1日型：昨日龙一今日跌停（is_limit_down_pct）。
    2日型：今日+昨日均大面（≤-5%）且两日均未跌停、均未封板（无承接）——封板日涨幅
    为正不可能大面，故 2日型主体天然为已断板高位股（原文「没有跌停但连续大跌」）。
    anchor={code,name}；fate={pct,status}；缺料 → None（fail-visible）。
    """
    if not anchor:
        return None
    code = anchor["code"]
    pt = (fate_today or {}).get("pct")
    st = (fate_today or {}).get("status")
    py = (fate_yesterday or {}).get("pct")
    sy = (fate_yesterday or {}).get("status")
    if is_limit_down_pct(pt, code):
        return {"type": "highCollapse", "date": date, "track": track, "code": code,
                "name": anchor.get("name"), "subtype": "1day", "todayPct": pt}
    if (isinstance(pt, (int, float)) and not isinstance(pt, bool) and pt <= BIG_FACE_PCT
            and isinstance(py, (int, float)) and not isinstance(py, bool) and py <= BIG_FACE_PCT
            and not is_limit_down_pct(py, code)
            and st != "sealed" and sy != "sealed"):
        return {"type": "highCollapse", "date": date, "track": track, "code": code,
                "name": anchor.get("name"), "subtype": "2day",
                "todayPct": pt, "yesterdayPct": py}
    return None


def detect_tolerance(date: str, track: str, anchor: dict | None,
                     fate_today: dict | None,
                     stabilize_window: list[dict] | None) -> dict | None:
    """E4 高位宽容（主体=昨日市场空间龙一中断板状态者）。

    反包型：昨日龙一昨日断板（statusYesterday=broken）且今日封板 → 即时事件（最强形式）。
    企稳型：断板日=day0，其后连续 2 交易日（day1/day2）每日「未跌停 且 未大面 且 未封板」
    → day2 收盘出事件（原文「震荡两天不崩塌」）。stabilize_window=[{date,pct,status}]
    （day1,day2，末日==date）；「稳住高位」=未跌停+未大面（冻结口径，Q4=A，不新增阈值）。
    窗内再断板由 operations 以最近封板日重置 day0；窗内封板走反包型。缺料 → None。
    """
    if not anchor:
        return None
    code = anchor["code"]
    st = (fate_today or {}).get("status")
    if anchor.get("statusYesterday") == "broken" and st == "sealed":
        return {"type": "highTolerance", "date": date, "track": track, "code": code,
                "name": anchor.get("name"), "subtype": "rebound",
                "poolDay": anchor.get("poolDay")}
    w = stabilize_window or []
    if len(w) == TOLERANCE_WINDOW and w[-1].get("date") == date:
        clean = all(
            isinstance(x.get("pct"), (int, float)) and not isinstance(x.get("pct"), bool)
            and x["pct"] > BIG_FACE_PCT
            and not is_limit_down_pct(x["pct"], code)
            and x.get("status") != "sealed"
            for x in w)
        if clean:
            return {"type": "highTolerance", "date": date, "track": track, "code": code,
                    "name": anchor.get("name"), "subtype": "stabilize",
                    "poolDay": anchor.get("poolDay"),
                    "window": [{"date": x["date"], "pct": x["pct"]} for x in w]}
    return None


def one_word_from_shape(shape: str | None) -> bool | None:
    """板型叙事行 → 一字板三态（True/False/None 不可验）。板型单源 stock_board_shape_line。

    不可验（None）：行以「板型：」起头（昨收缺失/5 分钟棒缺失/未触板）或含「不可算」——
    历史日 5 分钟线不可得时不得伪 False（预登记 §四 E1「不可考→注，不猜」）。
    确定非一字（False）：秒板/硬板/炸板回封/烂板/触板未封等明确板型。
    """
    if not shape or shape.startswith("板型：") or "不可算" in shape:
        return None
    return "板型=一字板" in shape


def is_one_word_bar(bar: dict | None, code: str, prev_close: float | None) -> bool | None:
    """一字板机械判定（日线 OHLC 全等且收在涨停价）；缺高低价/前收 → None（不可验，不猜）。

    注：`fetch_daily_bars` 仅回 open/close，无 high/low → 通常返回 None；operations 层
    对突破股另走板型单源（stock_board_shape_line，5 分钟线）取「板型=一字板」注记。
    本函数供有完整 OHLC 的场景（如测试/未来数据源）复用，涨停价单源 limit_up_price。
    """
    if not bar or not prev_close or prev_close <= 0:
        return None
    o, h, l, c = bar.get("open"), bar.get("high"), bar.get("low"), bar.get("close")
    if not all(isinstance(x, (int, float)) for x in (o, h, l, c)):
        return None
    if not (o == h == l == c):
        return False
    return abs(c - limit_up_price(code, prev_close)) < 0.001


# ── P2 市场级状态机（预登记 §五；裁决 1A 输入=事件流 only / Q5=B 优先级 / Q6=A 首日）──
# 四态无吸收态（市场周期永续轮回，全态可逆，与 theme_cycle terminal 不同）。
STATES = ("loss", "ice", "wzs", "gain")
STATE_LABELS_CN = {"loss": "亏钱", "ice": "冰点", "wzs": "弱转强", "gain": "赚钱"}

# 迁移触发词（落痕用，预登记 §5.2）
TRIG_BREAKTHROUGH = "space_breakthrough"   # E1 → gain（赚钱效应标杆诞生）
TRIG_COLLAPSE = "high_collapse"            # E3 → loss（亏钱效应）
TRIG_COMPRESS = "space_compress"           # E2 → loss→ice / gain·wzs→loss / ice 自持
TRIG_TOLERANCE = "high_tolerance"          # E4 → loss·ice→wzs / gain·wzs 自持
TRIG_INIT = "init_default"                 # 首日无事件保守默认 loss（Q6=A）

# 事件优先级序（Q5=B 冻结：E1 > E3 > E2 > E4；同日 E3+E1 龙头更替判 gain）
_EVENT_PRIORITY = ("spaceBreakthrough", "highCollapse", "spaceCompress", "highTolerance")


def initial_state() -> str:
    """Q6=A：回填首日无事件 → loss（保守默认，非判据判定）+ warmup 披露。"""
    return "loss"


def step_day(prev_state: str | None, *, events: list[dict] | None,
             date: str | None = None, warmup: bool = False) -> tuple[str, dict | None]:
    """单日市场级状态迁移（纯函数）。输入=事件流 E1–E4 only（裁决 1A，参照不进判据）。

    优先级 E1>E3>E2>E4（Q5=B）；取当日最高优先级命中。无吸收态全态可逆；wzs 无超时
    （Q3=A）无事件自持。prev_state=None=首日（Q6 默认 loss 基底再套事件）。两轨聚合
    Q1=A：任一轨命中即计入（events 已含两轨，类型去重即可）。返回 (new_state, transition)；
    transition=None=自持（含 E2 ice 自持 / E4 gain·wzs 自持 / 无事件）。迁移落痕
    {from,to,trigger,evidence,date}（theme_cycle 同构）。
    """
    events = events or []
    types = {e.get("type") for e in events if e.get("type")}
    is_init = prev_state is None
    base = initial_state() if is_init else prev_state

    target, trigger, trig_event = base, None, None
    if "spaceBreakthrough" in types:
        target, trigger = "gain", TRIG_BREAKTHROUGH
        trig_event = next(e for e in events if e.get("type") == "spaceBreakthrough")
    elif "highCollapse" in types:
        target, trigger = "loss", TRIG_COLLAPSE
        trig_event = next(e for e in events if e.get("type") == "highCollapse")
    elif "spaceCompress" in types:
        trigger = TRIG_COMPRESS
        trig_event = next(e for e in events if e.get("type") == "spaceCompress")
        target = "ice" if base == "loss" else ("loss" if base in ("gain", "wzs") else "ice")
    elif "highTolerance" in types:
        trigger = TRIG_TOLERANCE
        trig_event = next(e for e in events if e.get("type") == "highTolerance")
        target = "wzs" if base in ("loss", "ice") else base

    evidence = {"eventTypes": sorted(types), "triggerEvent": trig_event}
    if is_init:
        return target, {"from": None, "to": target, "trigger": trigger or TRIG_INIT,
                        "evidence": {**evidence, "warmup": warmup}, "date": date}
    if target != base:
        return target, {"from": base, "to": target, "trigger": trigger,
                        "evidence": evidence, "date": date}
    return base, None


def replay(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """全历史重放（升序日期）。days 每元素 {"date", "events": [...], "warmup": bool}。

    单一市场级状态（非逐板块×轨，与 theme_cycle 不同）。返回逐日记录：
    {date,state,prev,migrated,transition,daysInState,warmup}。daysInState 自持累加、
    迁移/首日重置 1（Q3=A wzs 无超时，days-in-state 披露供后续裁决是否加窗）。
    """
    state: str | None = None
    days_in_state = 0
    out: list[dict[str, Any]] = []
    for day in days:
        new_state, transition = step_day(state, events=day.get("events") or [],
                                         date=day.get("date"),
                                         warmup=bool(day.get("warmup")))
        days_in_state = 1 if transition is not None else days_in_state + 1
        out.append({"date": day.get("date"), "state": new_state,
                    "prev": transition["from"] if transition else state,
                    "migrated": transition is not None, "transition": transition,
                    "daysInState": days_in_state, "warmup": bool(day.get("warmup"))})
        state = new_state
    return out
