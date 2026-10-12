# -*- coding: utf-8 -*-
"""连板情绪指数轨道（relay sentiment index，2026-10-10 Phase 1）。

- 叙事七段（§3 设计 + 2026-10-11 StepB 炸板面段，预登记 docs/hotlist-jev/jev-relay-zhaban-preregistration.md）：
  总账+今日炸板面/晋级断板 → 三日链与题材演化 → 题材梯队表 → 龙头档案 → 近10日轨迹 → 热榜叙事参照段
- 题目集：analysis/hotlist/jev_relay_ammo.QUESTIONS_RELAY（7 题一 call，questionSetVersion v3 已落生产）
- 存储：hotlist_jev_relay_index，_id={date}:RELAY；幂等跳过 status=ok
- 通道：_dispatch_jev 分流（官方直连优先，CF 回退）
- 口径：涨停/晋级 = 触板 − THS 炸板池（方案A 二分，_sealed_codes）；THS 缺失日回退触板口径并注记
- fail-visible：任一段原料缺失写「不可算」，不伪造不阻断
"""
from __future__ import annotations

import argparse
import os
import time
from typing import Any

from backend.analysis.hotlist.jev_relay_ammo import QUESTIONS_RELAY, QUESTION_SET_VERSION_RELAY
from backend.operations.jev_label_jiuyan import (
    DEFAULT_DATASET_ID,
    _daily_bars,
    _dispatch_jev,
    _jiuyan_board_count,
    _prev_close_of_date,
    dragon_rows,
    hotlist_ranks,
    limitup_sequence_line,
    market_facts_line,
    market_metrics,
    parse_jev_response,
    stock_board_shape_line,
    stock_position_line,
    swing_summary_line,
    trading_dates_before,
)

COLLECTION = "hotlist_jev_relay_index"


# ── 池工具 ─────────────────────────────────────────────────────────────────


def _pool_of(db: Any, date: str) -> dict[str, dict[str, Any]]:
    """韭研 final 池：code → {boards,name,time,board}；跨板块首个出现为准，无重复。
    boards = num「N天M板」的 M（day 字段是跨度天数，不可用作板数，2026-10-10 口径修正）。"""
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"})
    out: dict[str, dict[str, Any]] = {}
    for field in (doc or {}).get("fields") or []:
        board = field.get("name") or ""
        for stock in field.get("stocks") or []:
            code = str(stock.get("code") or "")[-6:]
            if code and code not in out:
                out[code] = {"boards": _jiuyan_board_count(stock),
                             "name": stock.get("name"),
                             "time": stock.get("time"), "board": board}
    return out


def _day_eff(entry: dict[str, Any]) -> int:
    """有效板数：num 解析的板数（M）；num 缺失=韭研首板口径（不标 num）记 1。"""
    boards = entry.get("boards")
    return int(boards) if boards else 1


# ── 段 1b：晋级与断板（D-1 池今日表现）──────────────────────────────────────


def _close_pct(code: str, prev_date: str, cur_date: str) -> float | None:
    """TDX 日线收盘涨跌（cur vs prev）；bars 缺任一日返回 None（fail-visible）。"""
    bars = {b["date"]: b for b in _daily_bars(code) if isinstance(b, dict)}
    a, b = bars.get(prev_date), bars.get(cur_date)
    if not a or not b or not a.get("close") or not b.get("close"):
        return None
    return round((b["close"] / a["close"] - 1) * 100, 2)


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    mid = len(s) // 2
    return round((s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2), 2)


def relay_flow_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """晋级率 + 断板亏钱 + 隔日溢价（D-1 池 × D0 池/TDX 日线；涨停/晋级按方案A 二分口径）。"""
    prev_dates = trading_dates_before(db, date, 1)
    if not prev_dates:
        return "晋级与断板：无昨日交易日（fail-visible）"
    prev_date = prev_dates[-1]
    prev_pool, cur_pool = _pool_of(db, prev_date), _pool_of(db, date)
    if not prev_pool:
        return f"晋级与断板：{prev_date} 韭研 final 缺失（fail-visible）"
    prev_zt, prev_found = _sealed_codes(db, prev_date, set(prev_pool), dataset_id)
    cur_zt, cur_found = _sealed_codes(db, date, set(cur_pool), dataset_id)
    calib = "" if (prev_found and cur_found) else "（THS炸板池缺失，触板口径降级）"
    promoted = [c for c in prev_zt if c in cur_zt]
    broken = sorted(prev_zt - cur_zt)
    rate = round(len(promoted) / len(prev_zt) * 100, 1) if prev_zt else 0.0
    # 分层晋级：昨日各板层今日连板成功率
    layers: dict[int, list[bool]] = {}
    for c in prev_zt:
        layers.setdefault(min(_day_eff(prev_pool[c]), 5), []).append(c in cur_zt)
    layer_txt = "；".join(
        f"{k}板→{'%.0f%%' % (sum(v) / len(v) * 100)}({sum(v)}/{len(v)})"
        for k, v in sorted(layers.items()))
    # 断板亏钱（TDX）
    broken_pcts = [p for p in (_close_pct(c, prev_date, date) for c in broken) if p is not None]
    if broken:
        if broken_pcts:
            big_face = sum(1 for p in broken_pcts if p <= -5)
            broken_txt = (f"断板 {len(broken)} 只：今日收盘中位 {_median(broken_pcts):+}%，"
                          f"大面(≤-5%) {big_face} 只（TDX 覆盖 {len(broken_pcts)}/{len(broken)}）")
        else:
            broken_txt = f"断板 {len(broken)} 只：今日表现不可算（TDX 日线缺失）"
    else:
        broken_txt = "断板 0 只"
    # 隔日溢价（昨日全部涨停股今日收盘中位）
    prem = [p for p in (_close_pct(c, prev_date, date) for c in prev_zt) if p is not None]
    prem_txt = f"隔日收盘溢价中位 {_median(prem):+}%（覆盖 {len(prem)}/{len(prev_zt)}）" if prem \
        else "隔日溢价不可算（TDX 日线缺失）"
    return (f"晋级与断板：昨日 {len(prev_zt)} 只涨停 → 今日仍涨停 {len(promoted)} 只"
            f"（晋级率 {rate}%）{calib}[{layer_txt}] · {broken_txt} · {prem_txt}")


# ── 段 2a：三日晋级链 ───────────────────────────────────────────────────────


def ladder_structure_line(db: Any, date: str) -> str:
    """梯队结构量化行（ladder_health 判据直读，消除模型心算）：占比/比率/较昨日变化。"""
    cur = market_metrics(db, date) or {}
    lad = cur.get("ladder") or {}
    one, two = lad.get("one") or 0, lad.get("two") or 0
    three_plus = (lad.get("three") or 0) + (lad.get("four") or 0) + (lad.get("high") or 0)
    total = one + two + three_plus
    if not total:
        return "梯队结构量化：梯队数据缺失（fail-visible）"
    ratio = round(two / three_plus, 2) if three_plus else None
    prev_dates = trading_dates_before(db, date, 1)
    prev_lad = (market_metrics(db, prev_dates[-1]) or {}).get("ladder") or {} if prev_dates else {}
    prev_two = prev_lad.get("two") or 0
    prev_tp = (prev_lad.get("three") or 0) + (prev_lad.get("four") or 0) + (prev_lad.get("high") or 0)
    prev_ratio = round(prev_two / prev_tp, 2) if prev_tp else None
    ratio_txt = (f"二板/三板+比率 {ratio}" + (f"（昨日 {prev_ratio}）" if prev_ratio is not None else "")) \
        if ratio is not None else "二板/三板+比率 不可算"
    src = cur.get("ladderSource")
    src_txt = f"（梯队来源 {src}）" if src and src != "jiuyan" else ""  # THS 回退日叙事披露来源（review M4）
    return (f"梯队结构量化：首板占比 {round(one/total*100)}%（{one}/{total}）· 二板 {two} 只 · "
            f"三板+ {three_plus} 只 · {ratio_txt}{src_txt}")


def three_day_chain_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """D-2 池 → D-1 → D0 存活链 + 高位股逐日点名（relay_momentum 主锚；二分涨停口径）。"""
    window = trading_dates_before(db, date, 2)
    if len(window) < 2:
        return "三日晋级链：历史不足（fail-visible）"
    d2, d1 = window[-2], window[-1]
    p2, p1, p0 = _pool_of(db, d2), _pool_of(db, d1), _pool_of(db, date)
    if not p2 or not p1:
        return f"三日晋级链：{d2}/{d1} 韭研 final 缺失（fail-visible）"
    p2z, f2 = _sealed_codes(db, d2, set(p2), dataset_id)
    p1z, f1 = _sealed_codes(db, d1, set(p1), dataset_id)
    p0z, f0 = _sealed_codes(db, date, set(p0), dataset_id)
    calib = "" if (f2 and f1 and f0) else "（THS炸板池缺失日按触板口径）"
    s1 = p2z & p1z
    s0 = s1 & p0z
    r1 = round(len(s1) / len(p2z) * 100, 1) if p2z else 0.0
    r0 = round(len(s0) / len(p2z) * 100, 1) if p2z else 0.0
    r_step = round(len(s0) / len(s1) * 100, 1) if s1 else None
    # 高位股逐日点名：D-2 按 day 降序 top3（连板/断板按二分涨停池判定——今日炸板 ≠ 连板）
    tops = sorted(p2.items(), key=lambda kv: (-_day_eff(kv[1]), str(kv[1].get("time") or "99:99")))[:3]
    fate = []
    for code, entry in tops:
        day1 = _day_eff(p1[code]) if code in p1z else None
        day0 = _day_eff(p0[code]) if code in p0z else None
        name = entry.get("name") or code
        if day0 is not None:
            fate.append(f"{name} {_day_eff(entry)}板→{day0}板连板中")
        elif day1 is not None:
            fate.append(f"{name} {_day_eff(entry)}板→昨日{day1}板今日断板")
        else:
            fate.append(f"{name} {_day_eff(entry)}板→次日即断")
    step_txt = f"→ D0 再存活 {len(s0)} 只（链率 {r0}%，段率 {r_step}%）" if r_step is not None else ""
    return (f"三日晋级链：{d2} 涨停 {len(p2z)} 只 → {d1} 仍涨停 {len(s1)} 只（{r1}%）"
            f"{step_txt} · 高位股轨迹：{'；'.join(fate) if fate else '无'}{calib}")


# ── 段 2b：题材演化 ─────────────────────────────────────────────────────────


def _boards_of(db: Any, date: str) -> dict[str, list[dict[str, Any]]]:
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"})
    out: dict[str, list[dict[str, Any]]] = {}
    for field in (doc or {}).get("fields") or []:
        name = field.get("name") or ""
        if name:
            out.setdefault(name, []).extend(field.get("stocks") or [])
    return out


def theme_evolution_line(db: Any, date: str, lookback: int = 5) -> str:
    """昨日 top3 题材今日地位 + 近5日题材榜（主线持续天数证据，theme_pulse 主锚）。"""
    prev_dates = trading_dates_before(db, date, 1)
    if not prev_dates:
        return "题材演化：无昨日交易日（fail-visible）"
    cur_b, prev_b = _boards_of(db, date), _boards_of(db, prev_dates[-1])
    if not cur_b or not prev_b:
        return "题材演化：韭研 final 缺失（fail-visible）"
    cur_top = sorted(cur_b, key=lambda k: -len(cur_b[k]))[:3]
    prev_top = sorted(prev_b, key=lambda k: -len(prev_b[k]))[:3]
    overlap = len(set(cur_top) & set(prev_top))
    rows = []
    for name in cur_top:
        prev_n = len(prev_b.get(name) or [])
        cur_max = max((_jiuyan_board_count(s) or 0 for s in cur_b[name]), default=0)
        delta = f"（昨日 {prev_n} 只{'↑扩容' if len(cur_b[name]) > prev_n else '↓缩容' if len(cur_b[name]) < prev_n else '持平'}）" if prev_n else "（新题材）"
        rows.append(f"{name} {len(cur_b[name])}只·最高{cur_max}板{delta}")
    # 近5日题材榜：主线持续天数证据（D-4..D0 各日 top3）
    hist_dates = trading_dates_before(db, date, lookback - 1) if lookback > 1 else []
    history = []
    for hd in hist_dates:
        hb = _boards_of(db, hd)
        if hb:
            top = sorted(hb, key=lambda k: -len(hb[k]))[:3]
            history.append(f"{hd[5:]}: {'/'.join(f'{t}({len(hb[t])})' for t in top)}")
    # 连续在榜天数（自今日向回数，中断即止）
    def _streak(name: str) -> int:
        n, d = 1, date
        while n < 10:
            pd_ = trading_dates_before(db, d, 1)
            if not pd_:
                break
            pb = _boards_of(db, pd_[-1])
            if not pb or name not in sorted(pb, key=lambda k: -len(pb[k]))[:3]:
                break
            n += 1
            d = pd_[-1]
        return n
    streaks = [f"{name} 连续{_streak(name)}日top3" for name in cur_top]
    streak_txt = "；".join(streaks)
    hist_txt = f"\n近5日题材榜：{' ； '.join(history)}" if history else ""
    return (f"题材演化：今日 top3 [{' / '.join(rows)}]；与昨日 top3 重合 {overlap}/3；连续性：{streak_txt}"
            f"（{'主线延续' if overlap >= 2 else '轮动换线' if overlap == 1 else '全面换血'}）{hist_txt}")


# ── 段 3：题材梯队表 top5 ───────────────────────────────────────────────────


def theme_ladder_lines(db: Any, date: str, top: int = 5) -> list[str]:
    """top5 题材：龙一/二/三（day desc, time asc）+ 板内标签聚合（driver labels）。"""
    prev_dates = trading_dates_before(db, date, 1)
    cur_b = _boards_of(db, date)
    if not cur_b:
        return ["题材梯队表：韭研 final 缺失（fail-visible）"]
    prev_b = _boards_of(db, prev_dates[-1]) if prev_dates else {}
    label_docs = {str(d.get("code") or "")[-6:]: d for d in db["hotlist_jev_driver_labels"].find(
        {"tradingDate": date, "status": "ok"}, {"code": 1, "label": 1, "freshness": 1})}
    lines = ["题材梯队表（top5，龙序=高度优先/封板时间次之）："]
    for name in sorted(cur_b, key=lambda k: -len(cur_b[k]))[:top]:
        # 龙序规则单源 dragon_rows（jev_label_jiuyan，与 limitup 读口「领涨」列同规）
        dragons = []
        for i, d in enumerate(dragon_rows(cur_b[name]), 1):
            day_txt = f"{d['boards']}板" if d["boards"] else "首板"
            dragons.append(f"龙{'一二三'[i-1]} {d['name']}({day_txt} {d['time'] or '?'})")
        inner = [str(s.get("code") or "")[-6:] for s in cur_b[name]]
        fresh = [label_docs[c].get("freshness") for c in inner if c in label_docs]
        drivers = [label_docs[c].get("label") for c in inner if c in label_docs]
        fresh_txt = (f"新鲜{sum(1 for f in fresh if f == 'fresh_catalyst')}/延续"
                     f"{sum(1 for f in fresh if f == 'continuing')}/{len(fresh)}标") if fresh else "无标签"
        drv_main = max(set(drivers), key=drivers.count) if drivers else None
        drv_txt = f"驱动主类 {drv_main}" if drv_main else ""
        prev_n = len(prev_b.get(name) or [])
        lines.append(f"· {name}：{' / '.join(dragons)}｜{fresh_txt}{('·' + drv_txt) if drv_txt else ''}"
                     f"｜昨日 {prev_n} 只")
    return lines


# ── 段 4：龙头档案 ──────────────────────────────────────────────────────────


def leader_profile_lines(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> list[str]:
    """最高板个股档案（身位/板序/板型/带动/热榜/标签）。"""
    pool = _pool_of(db, date)
    if not pool:
        return ["龙头档案：韭研 final 缺失（fail-visible）"]
    code, entry = sorted(pool.items(), key=lambda kv: (
        -_day_eff(kv[1]), str(kv[1].get("time") or "99:99")))[0]
    name = entry.get("name") or code
    board = entry.get("board") or "?"
    board_pull = sum(1 for e in pool.values() if e.get("board") == board)
    rank = hotlist_ranks(db, date, [code], dataset_id).get(code)
    label = db["hotlist_jev_driver_labels"].find_one({"_id": f"{date}:{code}"}) or {}
    lines = [f"龙头档案：{name}({code}) {_day_eff(entry)}板 · {board}板块 · 封板 {entry.get('time') or '?'}"
             f" · 板内带动 {board_pull} 只 · 热榜最高第 {rank if rank else '未上榜'}名"
             + (f" · 标签 {label.get('label')}/{label.get('freshness')}" if label.get("label") else "")]
    lines.append(stock_position_line(date, code))
    lines.append(limitup_sequence_line(date, code, name))
    lines.append(stock_board_shape_line(date, code, name, _prev_close_of_date(date, code)))
    return lines


# ── 段 5：近 10 日连板轨迹 ──────────────────────────────────────────────────


def relay_trajectory_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                          n: int = 10) -> str:
    """家数/最高板/晋级率逐日 + 涨停摆动锚（swing_summary_line 复用）。"""
    hist = trading_dates_before(db, date, n, dataset_id=dataset_id)
    axis = hist + [date]
    rows = []
    degrade = False
    for i, d in enumerate(axis):
        prev = axis[i - 1] if i > 0 else (trading_dates_before(db, d, 1, dataset_id=dataset_id) or [None])[-1]
        m = market_metrics(db, d, dataset_id) or {}
        pool = _pool_of(db, d)
        if prev:
            prev_pool = _pool_of(db, prev)
            prev_zt, f1 = _sealed_codes(db, prev, set(prev_pool), dataset_id) if prev_pool else (set(), True)
            cur_zt, f2 = _sealed_codes(db, d, set(pool), dataset_id) if pool else (set(), True)
            degrade = degrade or not (f1 and f2)
            promo = f"{round(len(prev_zt & cur_zt) / len(prev_zt) * 100):.0f}%" if prev_zt else "?"
        else:
            promo = "?"
        zt = m.get("ztCount") if isinstance(m.get("ztCount"), (int, float)) else "?"
        mb = m.get("maxBoard") if isinstance(m.get("maxBoard"), (int, float)) else "?"
        rows.append(f"{d[5:]}|涨停{zt}|最高{mb}板|晋级{promo}")
    calib = "（THS炸板池缺失日晋级按触板口径）" if degrade else ""
    return (f"近{len(rows)}日连板轨迹（日期|涨停|最高板|晋级率）：{' ； '.join(rows)}{calib}\n"
            + swing_summary_line(db, date, n, dataset_id=dataset_id))


# ── 段 5.5：今日炸板面（2026-10-11 预登记 StepB）─────────────────────────────


def _ths_failed_snapshot(db: Any, date: str, dataset_id: str) -> tuple[list[dict], bool]:
    """THS 15:00 帧炸板池 items；(items, found)。found=False = 帧缺失/池降级（fail-visible）。"""
    fr = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"limitSummary.thsPools": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    tp = ((fr or {}).get("limitSummary") or {}).get("thsPools") or {}
    if not tp or not tp.get("ok") or tp.get("degraded"):
        return [], False
    return list((((tp.get("pools") or {}).get("failed") or {}).get("items")) or []), True


def _sealed_codes(db: Any, date: str, touch: set[str], dataset_id: str) -> tuple[set[str], bool]:
    """触板 − THS 15:00 炸板池 = 收盘涨停池（方案A 二分，与 jiuyan_board_info 同口径）。

    2026-10-10 review C2 口径修正：韭研 final fields.stocks 是触板名单（封板+炸板），
    直接当「涨停/晋级」会把昨日封板今日炸板股计成晋级、低估断板亏钱面。
    返回 (codes, ths_found)：ths_found=False = 池缺失/降级，回退触板口径，
    调用方必须在叙述中注记降级（不得静默混用两种口径）。
    """
    items, found = _ths_failed_snapshot(db, date, dataset_id)
    if not found:
        return set(touch), False
    failed = {str(i.get("code") or "")[-6:] for i in items if i.get("code")}
    return set(touch) - failed, True


def zhaban_face_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """今日炸板面：THS 15:00 炸板池结构化证据（家数分位/反复开板/昨日池股炸板/大面/代表股）。

    预登记：docs/hotlist-jev/jev-relay-zhaban-preregistration.md（StepB，用户 2026-10-11 裁决）。
    炸板 0 家是合法强信号（正常呈现）；帧缺失/降级才写「不可算」。
    """
    items, found = _ths_failed_snapshot(db, date, dataset_id)
    if not found:
        return "今日炸板面：不可算（THS 炸板池缺失/降级，fail-visible）"
    by_code = {str(i.get("code") or "")[-6:]: i for i in items if i.get("code")}
    n = len(by_code)
    # 近 20 日炸板家数分位（无帧历史日跳过，只取有数据的日）
    hist = []
    for d in trading_dates_before(db, date, 20):
        its2, f2 = _ths_failed_snapshot(db, d, dataset_id)
        if f2:
            hist.append(len({str(i.get("code") or "")[-6:] for i in its2 if i.get("code")}))
    pct_txt = "（历史炸板数据不足 5 日，无分位参照）"
    if len(hist) >= 5:
        pct = round(sum(1 for x in hist if x < n) / len(hist) * 100)
        pct_txt = f"（近{len(hist)}日分位 P{pct}，均值 {_median(hist) or 0:.0f} 家）"
    # 反复开板
    hi = [i for i in by_code.values() if isinstance(i.get("open_num"), (int, float)) and i.get("open_num") >= 2]
    hi_txt = f"反复开板(≥2次) {len(hi)} 家（占 {round(len(hi) / n * 100) if n else 0}%）"
    # 昨日池分层：昨日池股今日炸 = 连板断层前导
    prev_dates = trading_dates_before(db, date, 1)
    layer_txt = "昨日池股炸板：不可算（昨日韭研池缺失）"
    if prev_dates:
        prev_pool = _pool_of(db, prev_dates[-1])
        if not prev_pool:  # review C1：_pool_of 缺档返回 {} 永非 None，原 is None 判断是死分支（伪 0）
            layer_txt = "昨日池股炸板：不可算（昨日韭研池缺失）"
        else:
            hit = [(c, prev_pool[c]) for c in by_code if c in prev_pool]
            hi_layer = [(c, p) for c, p in hit if (p.get("boards") or 0) >= 2]
            names = "、".join(f"{p.get('name') or c}({p.get('boards')}板)" for c, p in hi_layer[:3])
            layer_txt = (f"昨日池股今日炸 {len(hit)} 家（其中昨日2板以上 {len(hi_layer)} 家"
                         + (f"：{names}" if names else "") + "）")
    # 炸板股收盘表现
    rates = [i.get("change_rate") for i in by_code.values()
             if isinstance(i.get("change_rate"), (int, float))]
    if rates:
        big = sum(1 for r in rates if r <= -5)
        rate_txt = f"炸板股收盘涨幅中位 {_median(rates):+.1f}%、大面(≤-5%) {big} 家"
    else:
        rate_txt = "炸板股收盘表现不可算（change_rate 缺失）"
    # 代表股（开板次数降序前 3）
    reps = sorted(by_code.values(), key=lambda i: (i.get("open_num") or 0), reverse=True)[:3]
    rep_txt = "、".join(
        f"{i.get('name')}({i.get('open_num')}次,{i.get('change_rate'):+.1f}%)"
        if isinstance(i.get("change_rate"), (int, float)) else f"{i.get('name')}({i.get('open_num')}次)"
        for i in reps if i.get("name"))
    # 炸板归因打标分布（StepA：hotlist_jev_zhaban_labels 当日聚合；覆盖不足如实注记）
    labeled = list(db["hotlist_jev_zhaban_labels"].find(
        {"tradingDate": date, "status": "ok"}, {"zhabanCause": 1, "name": 1, "openNum": 1}))
    if labeled:
        from collections import Counter
        dist = Counter(l.get("zhabanCause") or "unknown" for l in labeled)
        hd = [l for l in labeled if l.get("zhabanCause") == "high_divergence"]
        hd_names = "、".join(f"{l.get('name')}({l.get('openNum')}次)" for l in hd[:3])
        dist_txt = (f"炸板归因打标（覆盖 {len(labeled)}/{n}）：高位分歧 {dist.get('high_divergence', 0)} 家"
                    + (f"（{hd_names}）" if hd_names else "")
                    + f"、板块退潮 {dist.get('sector_collapse', 0)} 家、追高被砸 {dist.get('chase_fail', 0)} 家、"
                    f"大盘拖累 {dist.get('broad_market', 0)} 家")
    else:
        dist_txt = f"炸板归因打标：未覆盖（0/{n}，归因证据缺失）"
    return (f"今日炸板面：炸板 {n} 家{pct_txt}；{hi_txt}；{layer_txt}；{rate_txt}；"
            f"反复开板代表：{rep_txt or '无'}；{dist_txt}")


# ── 段 6：热榜叙事参照段 ────────────────────────────────────────────────────


def narrative_context_lines(db: Any, date: str) -> list[str]:
    """今日 slot 叙事轨迹 + 近5日 EOD 叙事 + 近20日极值锚（防锚定：显式标注参照）。"""
    lines = ["【周期定位参照，非今日证据——防锚定段，打分锚以客观事实+分位为准】"]
    slots = sorted(db["hotlist_jev_sentiment"].find(
        {"tradingDate": date, "kind": "slot", "status": "ok"},
        {"slotTime": 1, "answers": 1, "scores": 1}), key=lambda s: str(s.get("slotTime") or ""))
    if slots:
        seg = []
        for s in slots:
            a = s.get("answers") or {}
            stage = (a.get("frame_stage") or {}).get("choice") or "?"
            temp = (a.get("temperature") or {}).get("score")
            crowd = (a.get("crowding") or {}).get("choice") or "?"
            seg.append(f"{s.get('slotTime')} {stage}(t{temp if temp is not None else '?'}·{crowd})")
        lines.append(f"今日热榜叙事轨迹（{len(seg)}槽）：{' → '.join(seg)}")
    else:
        lines.append("今日热榜叙事轨迹：无 ok 槽文档（fail-visible）")
    eods = sorted(db["hotlist_jev_sentiment"].find(
        {"tradingDate": {"$lt": date}, "kind": "eod", "status": "ok"},
        {"tradingDate": 1, "answers": 1, "scores": 1}),
        key=lambda e: str(e.get("tradingDate") or ""), reverse=True)[:5]
    if eods:
        seg = []
        for e in reversed(eods):
            a = e.get("answers") or {}
            stage = (a.get("day_stage") or {}).get("choice") or "?"
            pattern = (a.get("day_pattern") or {}).get("choice") or "?"
            temp = (e.get("scores") or {}).get("day_temperature")
            seg.append(f"{e.get('tradingDate')[5:]} {stage}(T{round(temp) if temp is not None else '?'}/{pattern})")
        lines.append(f"近{len(seg)}日 EOD 叙事：{' → '.join(seg)}")
    else:
        lines.append("近5日 EOD 叙事：无（fail-visible）")
    # 近20日极值锚（涨停家数/最高板）；market_metrics None（帧缺失日）跳过——数据不足由下方分支兜底
    hist = trading_dates_before(db, date, 20)
    ms = [(d, m) for d, m in ((d, market_metrics(db, d)) for d in hist) if isinstance(m, dict)]
    zs = [(d, m.get("ztCount")) for d, m in ms if isinstance(m.get("ztCount"), (int, float))]
    mb = [(d, m.get("maxBoard")) for d, m in ms if isinstance(m.get("maxBoard"), (int, float))]
    if len(zs) >= 5:
        z_peak = max(zs, key=lambda x: x[1])
        z_low = min(zs, key=lambda x: x[1])
        m_peak = max(mb, key=lambda x: x[1])
        lines.append(f"近20日锚：涨停峰值 {z_peak[1]} 家（{z_peak[0][5:]}）/谷值 {z_low[1]} 家（{z_low[0][5:]}）"
                     f"；最高板峰值 {m_peak[1]} 板（{m_peak[0][5:]}）")
    else:
        lines.append("近20日锚：历史数据不足（fail-visible）")
    return lines


# ── 组装与 run ──────────────────────────────────────────────────────────────


def build_relay_narrative(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    lines: list[str] = [f"{date} 交易日 · 连板情绪指数判定（叙事七段）"]
    # 段1 总账（market_facts_line 已含双源梯队/分位）+ 今日炸板面（2026-10-11 StepB）
    lines.append(market_facts_line(db, date, dataset_id))
    lines.append(zhaban_face_line(db, date, dataset_id))
    lines.append(relay_flow_line(db, date, dataset_id))
    lines.append(ladder_structure_line(db, date))
    # 段2 记忆
    lines.append(three_day_chain_line(db, date, dataset_id))
    lines.append(theme_evolution_line(db, date))
    # 段3 题材梯队
    lines.extend(theme_ladder_lines(db, date))
    # 段4 龙头
    lines.extend(leader_profile_lines(db, date, dataset_id))
    # 段5 轨迹
    lines.append(relay_trajectory_line(db, date, dataset_id))
    # 段6 叙事参照
    lines.extend(narrative_context_lines(db, date))
    return "\n".join(lines)


def run_relay_index_day(db: Any, dates: list[str], *,
                        dry_run: bool = False,
                        dataset_id: str = DEFAULT_DATASET_ID,
                        force: bool = False) -> None:
    col = db[COLLECTION]
    for date in dates:
        done = col.find_one({"_id": f"{date}:RELAY", "status": "ok"})
        if done and not dry_run and not force:
            print(f"[relay] {date} 已判（index={done.get('relayIndex')} phase={done.get('relayPhase')}），跳过")
            continue
        if not _pool_of(db, date):
            print(f"[relay] {date} 韭研 final 缺失，跳过（fail-visible）")
            continue
        narrative = build_relay_narrative(db, date, dataset_id)
        if dry_run:
            print(f"[dry] {date} narrative_chars={len(narrative)}")
            print(narrative)
            continue
        env, ms = _dispatch_jev(narrative, QUESTIONS_RELAY)
        parsed = parse_jev_response(env, ms, expected_keys=set(QUESTIONS_RELAY))
        answers = parsed.get("answers") or {}
        scores = parsed.get("scores") or {}
        usage = parsed.get("usage") or {}
        doc = {"_id": f"{date}:RELAY", "origin": "relay_index_daily", "tradingDate": date,
               "status": "ok" if parsed["ok"] else "degraded",
               "questionSetVersion": QUESTION_SET_VERSION_RELAY,
               "narrative": narrative, "questionsRaw": QUESTIONS_RELAY,
               # answers 原样落库（P0-2/P0-3）：七题 confidence/momentum 等四题 probabilities/
               # 两个 score 题直方图此前未落库，自此保全（历史文档不可回补）
               "answers": parsed.get("answers"),
               "relayIndex": scores.get("relay_index"),
               "relayPhase": (answers.get("relay_phase") or {}).get("choice"),
               "relayPhaseProbabilities": (answers.get("relay_phase") or {}).get("probabilities"),
               "relayMomentum": (answers.get("relay_momentum") or {}).get("choice"),
               "ladderHealth": (answers.get("ladder_health") or {}).get("choice"),
               "leaderStrength": scores.get("leader_strength"),
               "moneyEffect": (answers.get("money_effect") or {}).get("choice"),
               "themePulse": (answers.get("theme_pulse") or {}).get("choice"),
               "model": parsed.get("model"), "usage": usage, "latencyMs": ms,
               "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
               "responseRaw": None if parsed["ok"] else env,
               "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
        col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        print(f"[relay] {date} → index={doc['relayIndex']} phase={doc['relayPhase']} "
              f"momentum={doc['relayMomentum']} ladder={doc['ladderHealth']} "
              f"money={doc['moneyEffect']} theme={doc['themePulse']} ok={parsed['ok']} "
              f"tokens={(usage.get('input_tokens') or 0) + (usage.get('output_tokens') or 0)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--relay-day", dest="relay_day", action="append", default=[],
                    help="指定交易日判连板情绪指数（可多次传参；缺省=最近一个交易日）")
    ap.add_argument("--dry-run", action="store_true", help="只打印叙事，不调用模型")
    ap.add_argument("--force", action="store_true",
                    help="判据代际升级重放：已 ok 的日期也重新判定（replace_one 幂等覆盖）")
    ap.add_argument("--dataset-id", dest="dataset_id", default=DEFAULT_DATASET_ID)
    args = ap.parse_args()
    if not (os.environ.get("JEV_TYPESAFE_KEY") or "").strip() and not os.environ.get("JEV_CF_TOKEN"):
        raise SystemExit("需要 JEV_TYPESAFE_KEY 或 JEV_CF_TOKEN 环境变量")
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    days = args.relay_day
    if not days:
        latest = db["jiuyan_action"].find_one(
            {"kind": "jiuyan_action"}, sort=[("tradingDate", -1)])
        days = [str(latest["tradingDate"])] if latest else []
    run_relay_index_day(db, days, dry_run=args.dry_run, dataset_id=args.dataset_id,
                        force=args.force)
