# -*- coding: utf-8 -*-
"""连板情绪指数轨道（relay sentiment index，2026-10-10 Phase 1）。

- 叙事结构（§3 设计 + 2026-10-11 StepB 炸板面段 + 2026-10-16 v4 高位股多日轨迹段）：
  总账 → 今日炸板面 → 晋级断板 → 梯队量化 → 三日链 → 题材演化 → **高位股多日轨迹**
  → 题材梯队表 → 龙头档案 → 近10日轨迹 → 热榜叙事参照段
- 题目集：analysis/hotlist/jev_relay_ammo.QUESTIONS_RELAY（7 题一 call，questionSetVersion v4）
- 存储：hotlist_jev_relay_index，_id={date}:RELAY；幂等跳过 status=ok
- 通道：_dispatch_jev 分流（官方直连优先，CF 回退）
- 口径：涨停/晋级 = 触板 − THS 炸板池（方案A 二分，_sealed_codes）；THS 缺失日回退触板口径并注记
- **停牌跳过续算（v4，预注册 jev-relay-ammo-v4-preregistration.md）**：三日链/晋级断板/
  高位轨迹均走 day_status_of 单一事实源，停牌股既不计晋级也不计断板（分母同剔）；
  分层顶层 cap=_LAYER_CAP（6板+）
- fail-visible：任一段原料缺失写「不可算」，不伪造不阻断
"""
from __future__ import annotations

import argparse
import os
import time
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import THS_KEYS
from backend.analysis.hotlist.jev_relay_ammo import QUESTIONS_RELAY, QUESTION_SET_VERSION_RELAY
from backend.core.limit_rules import is_limit_down_pct
from backend.operations.jev_label_jiuyan import (
    DEFAULT_DATASET_ID,
    _adj_prev_series,
    _daily_bars,
    _dispatch_jev,
    _jiuyan_board_count,
    _jiuyan_days_boards,
    _jiuyan_ladder,
    _prev_close_of_date,
    _range_height_text,
    _ths_failed_items,
    _ths_pool_counts,
    day_status_of,
    dragon_rows,
    hotlist_ranks,
    jiuyan_streak_map,
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

# 分层晋级顶层 cap（v4，2026-10-16 口径）：1..5 板精确、第 6 层语义=「6板+」。
# 旧 min(s,5) 把 5/6/10/11 板混成一层，11 连板时代高位层分化（divergence 判据核心
# 证据）不可见；分层样本小，只做一次切分避免过度切层。
_LAYER_CAP = 6


# ── 池工具 ─────────────────────────────────────────────────────────────────


def _pool_of(db: Any, date: str) -> dict[str, dict[str, Any]]:
    """韭研 final 池：code → {boards,name,time,board,days}；跨板块首个出现为准，无重复。
    boards/days = num「N天M板」的 M/N（day 字段是跨度天数，不可用作板数，2026-10-10 口径修正）；
    2026-10-16 补 days 透传：区间文案「N天M板」用（连板语义另取 jiuyan_streak_map）。"""
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"})
    out: dict[str, dict[str, Any]] = {}
    for field in (doc or {}).get("fields") or []:
        board = field.get("name") or ""
        for stock in field.get("stocks") or []:
            code = str(stock.get("code") or "")[-6:]
            if code and code not in out:
                days, boards = _jiuyan_days_boards(stock)
                out[code] = {"boards": boards,
                             "name": stock.get("name"),
                             "time": stock.get("time"), "board": board, "days": days}
    return out


def _range_num_txt(entry: dict[str, Any]) -> str:
    """区间高度数字文案「N天M板」（days 缺失回落 M板；boards≤1/缺失=首板，不伪造天数）。

    与涨停复盘页 heightText（relay_page:805）同规；名+高度合版用 _range_height_text。
    """
    boards, days = entry.get("boards"), entry.get("days")
    if not boards or boards <= 1:
        return "首板"
    return f"{days}天{boards}板" if days else f"{boards}板"


def _day_eff(entry: dict[str, Any]) -> int:
    """有效区间板数：num 解析的板数（M）；num 缺失=韭研首板口径（不标 num）记 1。

    注意（2026-10-16 口径修正）：这是**区间高度**，只用于龙序/龙头选择与区间标注；
    「连板」语义（最高板/梯队/连板中）一律取 jiuyan_streak_map 真连板。
    """
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


_ANCHOR_GAP_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("炸板面", ("今日炸板面：不可算",)),
    ("炸板面个股级", ("个股级子项不可算", "反复开板/昨日池股炸板/炸板股收盘涨幅 不可算")),
    ("炸板面对比", ("较昨日：不可算",)),
    ("韭研池", ("韭研 final 缺失",)),
    ("梯队", ("梯队结构量化：梯队数据缺失",)),
    ("断板钱效", ("TDX 日线缺失", "样本不足（TDX 覆盖")),
    ("盘面事实", ("盘面指标缺失",)),
)


def anchor_gaps(narrative: str) -> list[str]:
    """叙事中「主锚缺位」标记（F2，2026-10-17 预注册 §2.4）：纯函数，**不改打分**。

    落库为 relay 文档 `anchorGaps` 字段，供前端显式呈现「本日哪根主锚缺位」——
    避免把 IE 读成模型能力问题（诊断文档四批 IE 全在原料/读口径层，非模型/判据）。
    """
    gaps: list[str] = []
    for name, markers in _ANCHOR_GAP_MARKERS:
        if any(m in narrative for m in markers):
            gaps.append(name)
    return gaps


# 断板/溢价 TDX 统计的最小样本门槛（2026-10-17 IE 修复 F4，预注册 §2.3）。
# 动因（诊断 §7）：回放窗界附近有 8 天覆盖仅 1–2 只却未 IE，模型拿 n=1 中位判 strong/losing
# （07-16 唯一依据 = 000016 一只票 +3.46%；而该样本恒为「已停止交易（停牌/退市）」股，
# 方向偏差不可假定）——属伪精度，比 IE 更危险。绝对门槛不可省：07-06 的 1/1=100% 会漏过纯比例规则。
_MIN_TDX_COVER = 5
_MIN_TDX_RATIO = 0.2


def _tdx_sample_ok(covered: int, total: int) -> bool:
    """覆盖是否足以支撑中位/大面类结论（F4 门槛）。total<=0 → False（无可算基数）。"""
    if total <= 0:
        return False
    return covered >= _MIN_TDX_COVER and covered / total >= _MIN_TDX_RATIO


def _sample_short_txt(noun: str, total: int, covered: int) -> str:
    """样本不足话术（不输出伪精度中位；缺失位置与门槛均结构化披露，AGENTS §4.0）。"""
    return (f"{noun} {total} 只：样本不足（TDX 覆盖 {covered}/{total}，"
            f"门槛 ≥{_MIN_TDX_COVER} 只且 ≥{int(_MIN_TDX_RATIO * 100)}%），不可作钱效依据")


def _broken_stats(codes: set[str], from_date: str, to_date: str) -> dict[str, Any] | None:
    """断板股在 [from_date, to_date] 的收盘亏钱统计（中位/大面家数/收盘跌停家数/TDX 覆盖）。
    无任何日线 → None（fail-visible，调用方写不可算，不得伪 0）。

    2026-10-16 补 dt（收盘跌停家数）：判定走 core/limit_rules.is_limit_down_pct（与
    dieban_count 同一条权威线，不写第二份阈值）——「断板反杀直通跌停」是退潮核心证据
    （10-15 实证：30 只断板里 7 只收盘跌停），旧口径只给中位/大面，模型看不到这条链。
    """
    rows = [(c, p) for c, p in ((c, _close_pct(c, from_date, to_date)) for c in sorted(codes))
            if p is not None]
    if not rows:
        return None
    pcts = [p for _, p in rows]
    return {"median": _median(pcts), "big": sum(1 for p in pcts if p <= -5),
            "dt": sum(1 for c, p in rows if is_limit_down_pct(p, c)),
            "covered": len(pcts)}


def _status_map(db: Any, date: str, pool: dict[str, Any], codes: set[str],
                dataset_id: str) -> tuple[dict[str, str], bool]:
    """codes 在 date 日的接力状态映射（池权威 + 日线补洞，唯一入口 day_status_of）。

    返回 ({code: sealed|broken|suspended|unknown}, ths_found)：ths_found=False =
    该日 THS 炸板池缺失 → 二分不可用，sealed 传 None 交由日线补证（不把触板当封板，
    与真连板回溯同规）。停牌/数据洞分辨即「停牌不算断板」的实现层（v4）。
    """
    sealed, found = _sealed_codes(db, date, set(pool), dataset_id)
    sealed_bin = sealed if found else None
    touch = set(pool) if pool else None
    bars_cache: dict[str, list[dict]] = {}
    out: dict[str, str] = {}
    for c in codes:
        if c not in bars_cache:
            bars_cache[c] = _daily_bars(c)
        bars = bars_cache[c]
        adj = _adj_prev_series(date, c, bars) if bars else {}
        out[c] = day_status_of(c, date, sealed=sealed_bin, touch=touch, bars=bars, adj=adj)
    return out, found


def _promotion_stats(db: Any, prev_date: str, date: str,
                     dataset_id: str) -> dict[str, Any]:
    """昨日封板池 → 今日状态分区（v4 停牌跳过续算；relay_flow 与三日链边际对比唯一算式）。

    - base = 昨日二分封板集合（THS 炸板池缺失日回退触板口径，calib 披露）；
    - 逐股 day_status_of → promoted / broken / suspended / unknown；
    - 晋级率分母 = |base| − suspended − unknown（停牌/不可验既不进分子也不进分母，
      与用户裁决「停牌不算断板、跳过续算」同源）；分母为 0 → rate=None（不伪 0）。
    """
    prev_pool, cur_pool = _pool_of(db, prev_date), _pool_of(db, date)
    if not prev_pool:
        return {"ok": False, "reason": f"{prev_date} 韭研 final 缺失"}
    base, prev_found = _sealed_codes(db, prev_date, set(prev_pool), dataset_id)
    status, cur_found = _status_map(db, date, cur_pool, set(base), dataset_id)
    promoted = sorted(c for c in base if status.get(c) == "sealed")
    broken = sorted(c for c in base if status.get(c) == "broken")
    suspended = sorted(c for c in base if status.get(c) == "suspended")
    unknown = sorted(c for c in base if status.get(c) == "unknown")
    denom = len(base) - len(suspended) - len(unknown)
    rate = round(len(promoted) / denom * 100, 1) if denom else None
    return {"ok": True, "prev_date": prev_date, "base": sorted(base),
            "promoted": promoted, "broken": broken, "suspended": suspended,
            "unknown": unknown, "denom": denom, "rate": rate, "status": status,
            "prev_found": prev_found, "cur_found": cur_found,
            "prev_pool": prev_pool, "cur_pool": cur_pool}


def relay_flow_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """晋级率 + 断板亏钱 + 隔日溢价（D-1 池 × D0；v4 停牌跳过续算）。

    停牌/不可验股既不进晋级也不进断板（分母同剔，文案披露）；断板亏钱带较昨日对比
    （2026-10-16 二级审计补供 relay_phase.divergence 判据）；分层顶层 cap=_LAYER_CAP。
    """
    prev_dates = trading_dates_before(db, date, 1)
    if not prev_dates:
        return "晋级与断板：无昨日交易日（fail-visible）"
    prev_date = prev_dates[-1]
    stats = _promotion_stats(db, prev_date, date, dataset_id)
    if not stats.get("ok"):
        return f"晋级与断板：{stats['reason']}（fail-visible）"
    base, rate = stats["base"], stats["rate"]
    promoted, broken = stats["promoted"], stats["broken"]
    suspended, unknown = stats["suspended"], stats["unknown"]
    prev_pool = stats["prev_pool"]
    promoted_set, broken_set = set(promoted), set(broken)
    # 停牌跳过披露（v4）：停牌与不可验均不入分子/分母，必须显式可见（fail-visible）
    skip_parts = []
    if suspended:
        skip_parts.append(f"停牌跳过 {len(suspended)} 只")
    if unknown:
        skip_parts.append(f"状态不可验 {len(unknown)} 只")
    skip_txt = f"（{'、'.join(skip_parts)}，不计入晋级率）" if skip_parts else ""
    calib = "" if (stats["prev_found"] and stats["cur_found"]) else "（THS炸板池缺失日按日线补证/触板口径）"
    rate_txt = f"{rate}%" if rate is not None else "不可算（分母为空）"
    # 分层晋级：昨日各板层今日连板成功率。板层=昨日真连板；顶层 cap=_LAYER_CAP（6板+）。
    prev_streaks = jiuyan_streak_map(db, prev_date, dataset_id)
    layers: dict[int, list[bool]] = {}
    unlayered = 0
    for c in base:
        if c not in promoted_set and c not in broken_set:
            continue  # 停牌/不可验 → 不入层（已在上方披露，不伪 0）
        s = prev_streaks.get(c)
        if not isinstance(s, int):
            # 不可算 → 不入层。旧代码此处回退区间 M，19天11板真连板1板又被算进 5 板层，
            # 正是口径修正要除的污染；宁缺毋猜，单独披露只数
            unlayered += 1
            continue
        layers.setdefault(min(s, _LAYER_CAP), []).append(c in promoted_set)
    layer_txt = "；".join(
        f"{k}板+→{'%.0f%%' % (sum(v) / len(v) * 100)}({sum(v)}/{len(v)})" if k == _LAYER_CAP
        else f"{k}板→{'%.0f%%' % (sum(v) / len(v) * 100)}({sum(v)}/{len(v)})"
        for k, v in sorted(layers.items()))
    if unlayered:
        layer_txt += f"；{unlayered}只连板高度不可算未分层"
    # 断板亏钱（TDX）：broken 已剔除停牌/不可验；覆盖不足 → 不输出中位（F4 门槛）
    cur_stats = _broken_stats(set(broken), prev_date, date)
    cur_stats_ok = bool(cur_stats) and _tdx_sample_ok(cur_stats["covered"], len(broken))
    if broken:
        if cur_stats_ok:
            dt_txt = f"、收盘跌停 {cur_stats['dt']} 只" if cur_stats.get("dt") else ""
            broken_txt = (f"断板 {len(broken)} 只：今日收盘中位 {cur_stats['median']:+}%，"
                          f"大面(≤-5%) {cur_stats['big']} 只{dt_txt}"
                          f"（TDX 覆盖 {cur_stats['covered']}/{len(broken)}）")
        elif cur_stats:
            broken_txt = _sample_short_txt("断板", len(broken), cur_stats["covered"])
        else:
            broken_txt = f"断板 {len(broken)} 只：今日表现不可算（TDX 日线缺失）"
    else:
        broken_txt = "断板 0 只"
    # 较昨日断板：前日池昨日断板（同 _promotion_stats 停牌口径，剔停牌/不可验）。判据「断板
    # 亏钱扩散（中位转负或大面增多）」需要昨日可比数，此前只给今日绝对值（2026-10-16 补供）。
    window2 = trading_dates_before(db, date, 2)
    if len(window2) < 2:
        prev_broken_txt = "较昨日断板：不可算（无前日交易日）"
    else:
        d2 = window2[-2]
        stats2 = _promotion_stats(db, d2, prev_date, dataset_id)
        if not stats2.get("ok"):
            prev_broken_txt = f"较昨日断板：不可算（{stats2.get('reason', d2 + ' 数据缺失')}）"
        else:
            pb = set(stats2["broken"])
            ps = _broken_stats(pb, d2, prev_date)
            calib2 = "" if stats2["prev_found"] else "（前日触板口径）"
            if not pb:
                prev_broken_txt = "较昨日断板：昨日 0 只"
            elif ps is None:
                prev_broken_txt = "较昨日断板：不可算（昨日 TDX 日线缺失）"
            elif not _tdx_sample_ok(ps["covered"], len(pb)):
                prev_broken_txt = ("较昨日断板：" + _sample_short_txt("昨日断板", len(pb), ps["covered"]))
            elif not broken:
                prev_broken_txt = (f"较昨日断板：昨日中位 {ps['median']:+}%、"
                                   f"大面 {ps['big']} 只 → 今日断板 0 只{calib2}")
            elif not cur_stats_ok:
                prev_broken_txt = ("较昨日断板：今日断板样本不足"
                                   f"（TDX 覆盖 {cur_stats['covered'] if cur_stats else 0}/{len(broken)}），不可比")
            else:
                prev_broken_txt = (f"较昨日断板：中位 {ps['median']:+}%→{cur_stats['median']:+}%、"
                                   f"大面 {ps['big']}→{cur_stats['big']} 只{calib2}")
    # 隔日溢价（昨日可交易涨停股今日收盘中位；停牌/不可验不入基数）
    elig = sorted(promoted_set | broken_set)
    prem = [p for p in (_close_pct(c, prev_date, date) for c in elig) if p is not None]
    if not prem:
        prem_txt = "隔日溢价不可算（TDX 日线缺失）"
    elif _tdx_sample_ok(len(prem), len(elig)):
        prem_txt = f"隔日收盘溢价中位 {_median(prem):+}%（覆盖 {len(prem)}/{len(elig)}）"
    else:
        prem_txt = _sample_short_txt("隔日溢价样本", len(elig), len(prem))
    # 涨停家数口径对账（2026-10-16）：同花顺涨停池参照，差集=触板未封/新股，防两口径数字打架
    caliber = _zt_caliber_note(db, prev_date, dataset_id, set(base), prev_pool)
    return (f"晋级与断板：昨日 {len(base)} 只涨停（触板二分口径）{calib}{caliber} → "
            f"今日仍涨停 {len(promoted)} 只"
            f"（晋级率 {rate_txt}）{skip_txt}[{layer_txt}] · {broken_txt} · {prev_broken_txt} · {prem_txt}")


# ── 段 2a：三日晋级链 ───────────────────────────────────────────────────────


def ladder_structure_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """梯队结构量化行（ladder_health 判据直读，消除模型心算）：占比/比率/较昨日变化。

    2026-10-16 口径修正：消费的 ladder 已改真连板分桶（market_metrics/_jiuyan_ladder），
    首板占比/二板/三板+/比率全部是真连板语义；THS 炸板池缺失日按触板口径并显式披露。
    """
    def _ladder_of(d: str) -> tuple[dict[str, int], str | None]:
        """梯队桶 + 来源；帧缺失日回退韭研主源（F3：梯队不依赖 15:00 帧）。

        2026-10-17 IE 修复：3 天（07-06/07/07/07-09）无 15:00 帧使 `market_metrics` 整段 None，
        旧代码把已可算的韭研梯队（韭研 final 96/48/88 只）一并丢弃 → 梯队 IE；
        这里同源回退并沿用既有来源披露（AGENTS §4.0）。
        """
        m = market_metrics(db, d, dataset_id) or {}
        buckets, source = m.get("ladder") or {}, m.get("ladderSource")
        if not any(buckets.get(k) for k in THS_KEYS):
            jl = _jiuyan_ladder(db, d, dataset_id) or {}
            if any(jl.get(k) for k in THS_KEYS):
                return ({k: jl.get(k) or 0 for k in THS_KEYS},
                        "jiuyan_touch" if jl.get("_caliber") == "touch_range" else "jiuyan")
        return buckets, source

    lad, src = _ladder_of(date)
    one, two = lad.get("one") or 0, lad.get("two") or 0
    three_plus = (lad.get("three") or 0) + (lad.get("four") or 0) + (lad.get("high") or 0)
    total = one + two + three_plus
    if not total:
        return "梯队结构量化：梯队数据缺失（fail-visible）"
    ratio = round(two / three_plus, 2) if three_plus else None
    prev_dates = trading_dates_before(db, date, 1)
    prev_lad = _ladder_of(prev_dates[-1])[0] if prev_dates else {}
    prev_two = prev_lad.get("two") or 0
    prev_tp = (prev_lad.get("three") or 0) + (prev_lad.get("four") or 0) + (prev_lad.get("high") or 0)
    prev_ratio = round(prev_two / prev_tp, 2) if prev_tp else None
    ratio_txt = (f"二板/三板+比率 {ratio}" + (f"（昨日 {prev_ratio}）" if prev_ratio is not None else "")) \
        if ratio is not None else "二板/三板+比率 不可算"
    # 首板占比较昨日（2026-10-16 二级审计补供 relay_phase.launch 判据「首板占比明显升高」；
    # 原只有比率挂昨日值，首板占比无可比数）。昨日梯队缺失 → 不挂后缀，不伪 0%。
    prev_one = prev_lad.get("one") or 0
    prev_total = prev_one + prev_two + prev_tp
    first_txt = f"首板占比 {round(one/total*100)}%（{one}/{total}）" + \
        (f"（昨日 {round(prev_one/prev_total*100)}%）" if prev_total else "")
    src_txt = ""
    if src == "jiuyan_touch":
        src_txt = "（THS炸板池缺失，梯队按触板口径）"  # 旧口径回退日显式披露
    elif src and src != "jiuyan":
        src_txt = f"（梯队来源 {src}）"  # THS 回退日叙事披露来源（review M4）
    else:
        src_txt = ""
    return (f"梯队结构量化：{first_txt} · 二板 {two} 只 · "
            f"三板+ {three_plus} 只 · {ratio_txt}{src_txt}")


def three_day_chain_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """D-2 池 → D-1 → D0 存活链 + 高位股逐日点名（relay_momentum/relay_phase 主锚；二分口径）。

    v4（2026-10-16）：停牌分辨——停牌股既不计晋级也不计断板（跳过续算），fate 增
    「今日停牌跳过/昨日停牌今日回封」档；边际对比与 relay_flow_line 共用 _promotion_stats，
    两处晋级率数字必然一致（禁漂移）。
    """
    window = trading_dates_before(db, date, 2)
    if len(window) < 2:
        return "三日晋级链：历史不足（fail-visible）"
    d2, d1 = window[-2], window[-1]
    p2, p1, p0 = _pool_of(db, d2), _pool_of(db, d1), _pool_of(db, date)
    if not p2 or not p1:
        return f"三日晋级链：{d2}/{d1} 韭研 final 缺失（fail-visible）"
    # 逐日状态（覆盖 p2 全体：既供存活链也供高位股 fate）；池权威 + 日线补洞（唯一入口）
    st1, f1 = _status_map(db, d1, p1, set(p2), dataset_id)
    st0, f0 = _status_map(db, date, p0, set(p2), dataset_id)
    stats_a = _promotion_stats(db, d2, d1, dataset_id)     # D-2 封板池 → D-1（r1）
    stats_b = _promotion_stats(db, d1, date, dataset_id)   # D-1 封板池 → D0（边际对比）
    base2 = set(stats_a["base"]) if stats_a.get("ok") else set()
    den_a = stats_a["denom"] if stats_a.get("ok") else 0
    r1 = stats_a["rate"] if stats_a.get("ok") else None
    # 存活链：D-2 封板 → D-1 封板 → D0 封板；停牌跳过但不计入存活（预注册 §2.1）
    s1 = {c for c in base2 if st1.get(c) == "sealed"}
    s0 = {c for c in s1 if st0.get(c) == "sealed"}
    r0 = round(len(s0) / den_a * 100, 1) if den_a else None
    r_step = round(len(s0) / len(s1) * 100, 1) if s1 else None
    calib = "" if (stats_a.get("prev_found") and f1 and f0) else "（THS炸板池缺失日按日线补证/触板口径）"
    # 高位股逐日点名：D-2 按区间高度降序 top3（连板/断板/停牌按 day_status_of 判定）
    tops = sorted(p2.items(), key=lambda kv: (-_day_eff(kv[1]), str(kv[1].get("time") or "99:99")))[:3]
    streaks0 = jiuyan_streak_map(db, date, dataset_id)
    fate = []
    for code, entry in tops:
        name = entry.get("name") or code
        rng = _range_num_txt(entry)          # D-2 日区间高度「N天M板」
        y, t = st1.get(code), st0.get(code)
        st0c = streaks0.get(code)
        s0_txt = f"连板{st0c}板" if isinstance(st0c, int) else "连板不可算"
        today_rng = _range_num_txt(p0[code]) if code in p0 else "封板"
        if t == "sealed":
            if y == "sealed":
                # 今日封板且昨日也封板 → 真连板中（2026-10-16 修：旧逻辑只看今日封板，
                # 把「昨日炸板今日回封」误判成连板中——澳弘电子 10-14 炸板、10-15 回封）
                fate.append(f"{name} {rng}→连板中（今日{today_rng}·{s0_txt}）")
            elif y == "suspended":
                fate.append(f"{name} {rng}→昨日停牌今日回封（{s0_txt}）")
            elif y == "unknown":
                fate.append(f"{name} {rng}→今日回封（昨日不可验，{s0_txt}）")
            else:
                fate.append(f"{name} {rng}→昨日断板今日回封（{s0_txt}）")
        elif t == "suspended":
            fate.append(f"{name} {rng}→今日停牌跳过")
        elif t == "unknown":
            fate.append(f"{name} {rng}→今日状态不可验（TDX 数据洞）")
        else:  # 今日断板
            if y == "sealed":
                # 区间高度 M 必须带跨度写成「N天M板」：裸「昨日10板」会被读成昨日 10 连板，
                # 而同篇段1 说最高 5 板（真连板）——同族自相矛盾（审计问题 #2/#3）
                ybase = _range_num_txt(p1[code]) if code in p1 else "涨停"
                fate.append(f"{name} {rng}→昨日{ybase}今日断板")
            elif y == "suspended":
                fate.append(f"{name} {rng}→昨日停牌今日断板")
            elif y == "unknown":
                fate.append(f"{name} {rng}→今日断板（昨日不可验）")
            else:
                fate.append(f"{name} {rng}→次日即断")
    step_txt = (f"→ D0 再存活 {len(s0)} 只（链率 {r0}%，段率 {r_step}%）"
                if r_step is not None else "")
    r1_txt = f"{r1}%" if r1 is not None else "不可算"
    # 昨日池今日晋级率 vs 前日池昨日晋级率（relay_momentum 主锚直供对比；与 relay_flow_line
    # 同源同式 _promotion_stats，两行数字必然一致，消除模型跨段心算）
    d1_rate = stats_b["rate"] if stats_b.get("ok") else None
    if stats_b.get("ok") and not stats_b["base"]:
        cmp_txt = "边际对比：不可算（昨日涨停池为空）"
    elif d1_rate is None or r1 is None:
        cmp_txt = "边际对比：不可算（分母为空）"
    else:
        cmp_txt = (f"边际对比：昨日池今日晋级率 {d1_rate}%"
                   f"（{stats_b['denom']}→{len(stats_b['promoted'])}）"
                   f" vs 前日池昨日 {r1}%（{den_a}→{len(s1)}），{round(d1_rate - r1, 1):+.1f}pct")
    # 涨停家数口径对账（2026-10-16，同 relay_flow_line）：D-2 家数给同花顺池参照+差集
    d2_caliber = _zt_caliber_note(db, d2, dataset_id, base2, p2)
    return (f"三日晋级链：{d2} 涨停 {len(base2)} 只（触板二分口径）{d2_caliber} → "
            f"{d1} 仍涨停 {len(s1)} 只（{r1_txt}）"
            f"{step_txt} · 高位股轨迹：{'；'.join(fate) if fate else '无'}{calib} · {cmp_txt}")


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
    # 真连板随行（2026-10-16 review 补）：本行原只渲染区间高度 M，同篇段1 却写「最高 5 板
    # （真连板）」——模型在同一份语料里读到两个「最高板」（5 vs 11），正是审计问题 #2/#3。
    # streak_map 按 (dataset, date) 缓存，段3/段4 同一天已算过，这里基本是缓存命中。
    streaks = jiuyan_streak_map(db, date)
    rows = []
    for name in cur_top:
        prev_n = len(prev_b.get(name) or [])
        top_stock = dragon_rows(cur_b[name], streaks=streaks, top=1)
        cur_max = _range_num_txt(top_stock[0]) if top_stock else "首板"
        if top_stock:
            st = top_stock[0].get("streak")
            if isinstance(st, int):
                cur_max += f"（连板{st}板）"
            elif top_stock[0].get("boards"):
                cur_max += "（连板不可算）"
        delta = f"（昨日 {prev_n} 只{'↑扩容' if len(cur_b[name]) > prev_n else '↓缩容' if len(cur_b[name]) < prev_n else '持平'}）" if prev_n else "（新题材）"
        rows.append(f"{name} {len(cur_b[name])}只·最高{cur_max}{delta}")
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


# ── 段 2c：高位股多日轨迹（v4，2026-10-16 预注册 §2.3）───────────────────────


def high_position_trajectory_lines(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                                   top: int = 5, n: int = 10) -> list[str]:
    """今日真连板 ≥4 的个股 top5 × 近 n 个交易日的逐日接力状态（有帽新段）。

    逐日状态取 day_status_of（池权威 + 日线补洞，与三日链/真连板回溯同一事实源）：
    ● 封板 / ○ 断板 / · 停牌跳过 / ? 不可验；停牌日与不可验日按区间合写（省 token）。
    定位：给 relay_phase/relay_index 一个**梯队健康度的多日坐标**，与三日晋级链、
    近10日聚合轨迹并列参照，**不得单独据其打分**（判据纪律）。
    fail-visible：韭研 final 缺失 / TDX 日线整体不可用 / 无真连板≥4 样本 均如实披露。
    """
    pool = _pool_of(db, date)
    if not pool:
        return ["高位股多日轨迹：韭研 final 缺失（fail-visible）"]
    streaks = jiuyan_streak_map(db, date, dataset_id)
    high = [(c, e) for c, e in pool.items()
            if isinstance(streaks.get(c), int) and streaks[c] >= 4]
    m = market_metrics(db, date, dataset_id) or {}
    mb = m.get("maxBoard")
    if not high:
        mb_txt = mb if isinstance(mb, int) and not isinstance(mb, bool) else "不可算"
        return [f"高位股多日轨迹：无真连板≥4 的个股（今日最高 {mb_txt} 板）"]
    high.sort(key=lambda kv: (-streaks[kv[0]], str(kv[1].get("time") or "99:99")))
    high = high[:top]
    axis = (trading_dates_before(db, date, n - 1, dataset_id=dataset_id) + [date]
            if n > 1 else [date])
    pools = {d: _pool_of(db, d) for d in axis}
    sealed_found = {d: _sealed_codes(db, d, set(pools[d]), dataset_id) for d in axis}
    bars_map = {c: _daily_bars(c) for c, _ in high}
    if all(not b for b in bars_map.values()):
        return ["高位股多日轨迹：TDX 日线不可用（fail-visible）"]
    marks_of = {"sealed": "●", "broken": "○", "suspended": "·", "unknown": "?"}
    lines = [f"高位股多日轨迹（真连板≥4 top{top}，近 {len(axis)} 个交易日逐日；"
             f"●封板/○断板/·停牌跳过/?不可验；有帽，非打分依据）："]
    today_cnt = {"sealed": 0, "broken": 0, "suspended": 0, "unknown": 0}
    for code, entry in high:
        bars = bars_map[code]
        adj = _adj_prev_series(date, code, bars) if bars else {}
        marks, susp_days, unk_days = [], [], []
        last = None
        for d in axis:
            sealed, found = sealed_found[d]
            st = day_status_of(code, d, sealed=(sealed if found else None),
                               touch=set(pools[d]) if pools[d] else None,
                               bars=bars, adj=adj)
            marks.append(marks_of[st])
            last = st
            if st == "suspended":
                susp_days.append(d[5:])
            elif st == "unknown":
                unk_days.append(d[5:])
        today_cnt[last] += 1
        tags = []
        if susp_days:
            tags.append(f"停牌跳过 {len(susp_days)} 日（{'/'.join(susp_days)}）")
        if unk_days:
            tags.append(f"不可验 {len(unk_days)} 日（{'/'.join(unk_days)}）")
        tag_txt = " · " + "；".join(tags) if tags else ""
        lines.append(f"· {entry.get('name') or code}({code}) 当前连板{streaks[code]}："
                     f"{''.join(marks)}{tag_txt} · 区间 {_range_num_txt(entry)}")
    lines.append(f"高位股今日状态：连板中 {today_cnt['sealed']} 只 / 停牌跳过 "
                 f"{today_cnt['suspended']} 只 / 断板 {today_cnt['broken']} 只 / "
                 f"不可验 {today_cnt['unknown']} 只")
    return lines


# ── 段 3：题材梯队表 top5 ───────────────────────────────────────────────────


def theme_ladder_lines(db: Any, date: str, top: int = 5) -> list[str]:
    """top5 题材：龙一/二/三（day desc, time asc）+ 板内标签聚合（driver labels）。

    2026-10-16 口径修正（用户报「其他板块龙一语料写成10板，应写14天10板」）：龙序仍按
    区间高度 M 排（14天10板 本就是该板块最显高位股），但文案补「N天M板」+ 真连板数——
    「连板」语义不再拿区间 M 冒充（澳弘电子 19天11板真连板=1 之教训）。
    """
    prev_dates = trading_dates_before(db, date, 1)
    cur_b = _boards_of(db, date)
    if not cur_b:
        return ["题材梯队表：韭研 final 缺失（fail-visible）"]
    prev_b = _boards_of(db, prev_dates[-1]) if prev_dates else {}
    label_docs = {str(d.get("code") or "")[-6:]: d for d in db["hotlist_jev_driver_labels"].find(
        {"tradingDate": date, "status": "ok"}, {"code": 1, "label": 1, "freshness": 1})}
    streaks = jiuyan_streak_map(db, date)
    failed_items, failed_found = _ths_failed_items(db, date, DEFAULT_DATASET_ID)
    zhaban_codes = set(failed_items) if failed_found else set()
    lines = ["题材梯队表（top5，龙序=高度优先/封板时间次之）："]
    for name in sorted(cur_b, key=lambda k: -len(cur_b[k]))[:top]:
        # 龙序规则单源 dragon_rows（jev_label_jiuyan，与 limitup 读口「领涨」列同规）
        dragons = []
        for i, d in enumerate(dragon_rows(cur_b[name], streaks=streaks), 1):
            code = d.get("code")
            st = d.get("streak")
            if code in zhaban_codes:
                st_txt = "·今日炸板"
            elif isinstance(st, int):
                st_txt = f"·连板{st}板"
            elif d.get("boards"):
                st_txt = "·连板不可算"
            else:
                st_txt = ""
            dragons.append(f"龙{'一二三'[i-1]} {d['name']}({_range_num_txt(d)} "
                           f"{d['time'] or '?'}{st_txt})")
        inner = [str(s.get("code") or "")[-6:] for s in cur_b[name]]
        fresh = [label_docs[c].get("freshness") for c in inner if c in label_docs]
        drivers = [label_docs[c].get("label") for c in inner if c in label_docs]
        fresh_txt = (f"新鲜{sum(1 for f in fresh if f == 'fresh_catalyst')}/延续"
                     f"{sum(1 for f in fresh if f == 'continuing')}/{len(fresh)}标") if fresh else "无标签"
        # 驱动主类：计数降序 + **同数按名称升序**（禁 `max(set(...), key=count)`——set 迭代序
        # 受 PYTHONHASHSEED 影响，并列时跨进程结果漂移：2026-10-17 实测同数据两次
        # 独立构建 09-07 叙事 hash 不同（383b870a vs 46367a66），使回放/重判输入不可复现）
        drv_main = sorted(set(drivers), key=lambda x: (-drivers.count(x), x))[0] if drivers else None
        drv_txt = f"驱动主类 {drv_main}" if drv_main else ""
        prev_n = len(prev_b.get(name) or [])
        lines.append(f"· {name}：{' / '.join(dragons)}｜{fresh_txt}{('·' + drv_txt) if drv_txt else ''}"
                     f"｜昨日 {prev_n} 只")
    return lines


# ── 段 4：龙头档案 ──────────────────────────────────────────────────────────


def leader_profile_lines(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> list[str]:
    """龙头档案（身位/板序/板型/带动/热榜/标签）。

    2026-10-16 口径修正：龙头仍按区间高度 M 选（19天11板 就是市场总龙头），但头行改
    「N天M板·当前连板X板」——旧头行只写 M（「11板」）与自家板序行「当前连板 1」自相矛盾，
    模型拿到互相打架的身位证据（10-15 审计问题 #8）。
    """
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
    streak = jiuyan_streak_map(db, date).get(code)
    streak_txt = (f"·当前连板{streak}板" if isinstance(streak, int) else "·连板不可算")
    lines = [f"龙头档案：{name}({code}) {_range_num_txt(entry)}{streak_txt} · {board}板块 · "
             f"封板 {entry.get('time') or '?'}"
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


def _sealed_codes(db: Any, date: str, touch: set[str], dataset_id: str) -> tuple[set[str], bool]:
    """触板 − THS 15:00 炸板池 = 收盘涨停池（方案A 二分，与 jiuyan_board_info 同口径）。

    2026-10-10 review C2 口径修正：韭研 final fields.stocks 是触板名单（封板+炸板），
    直接当「涨停/晋级」会把昨日封板今日炸板股计成晋级、低估断板亏钱面。
    返回 (codes, ths_found)：ths_found=False = 池缺失/降级，回退触板口径，
    调用方必须在叙述中注记降级（不得静默混用两种口径）。
    2026-10-16：本体委托 jev_label_jiuyan 同名单源（原双实现，消漂移）。
    """
    items, found = _ths_failed_items(db, date, dataset_id)
    if not found:
        return set(touch), False
    failed = set(items)
    return set(touch) - failed, True


def _ths_sealed_codes(db: Any, date: str, dataset_id: str) -> set[str] | None:
    """THS 连板层五池的封板集合（EOD 15:00 帧才有，2026-10-08 起有）；缺失/池空 → None。

    该集合是真连板口径的「收盘涨停」参照，用于给二分家数做口径对账——两口径同日
    两个数不对账，模型只能自己猜（10-15 审计问题 #5：39 vs 36）。

    2026-10-16 review 补：**逐池判 ok**。THS 风控返 HTTP 200 + 空 info 时池级 ok 仍为
    True，只读顶层 ok/degraded 会把「首板池被限流返空」当成当日真无首板——30 只封板股
    一夜变成「触板未封」，整个涨停家数对账反向。任一池不可信 → 整套对账不可算。
    """
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        # 整块投影：thsPools.pools 的嵌套投影不带兄弟键 ok/degraded（Mongo 语义），
        # 而池级 ok 判定必须读它们——2026-10-16 实测踩过（market_metrics 同款修正）
        {"limitSummary.thsPools": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    tp = ((f or {}).get("limitSummary") or {}).get("thsPools") or {}
    if not tp.get("ok") or tp.get("degraded"):
        return None
    pools = tp.get("pools") or {}
    codes: set[str] = set()
    for k in THS_KEYS:
        pool = pools.get(k) or {}
        if not pool.get("ok"):
            return None      # 单池上游失败 → 整套对账不可算（不静默丢一池的股）
        codes |= {str(it.get("stock_code"))[-6:]
                  for it in pool.get("items") or [] if it.get("stock_code")}
    return codes or None


def _zt_caliber_note(db: Any, date: str, dataset_id: str,
                     bisect_codes: set[str], pool: dict[str, dict[str, Any]]) -> str:
    """涨停家数口径对账注（2026-10-16，relay_flow/three_day_chain 共用）。

    二分口径（韭研触板−炸板池）与 THS 连板层同日两个数，差集点名让模型自己核，不代断
    成因——10-15 实证那 3 只（*ST美丽/*ST中迪/*ST开元）是 THS 涨停池剔除 ST/北交所，
    不是「触板未封」，旧文案把单一成因写死会教给模型假状态。THS 池缺失日不附注
    （不伪造差值 0，fail-visible）。
    """
    ths = _ths_sealed_codes(db, date, dataset_id)
    if ths is None:
        return ""
    extra = sorted(set(bisect_codes) - ths)   # 二分有、THS 无
    lack = sorted(ths - set(bisect_codes))    # THS 有、二分无（韭研 final 漏收/名不匹配）
    if not extra and not lack:
        return f"（同花顺涨停池 {len(ths)} 只，两口径一致）"
    parts = [f"同花顺涨停池 {len(ths)} 只"]
    if extra:
        names = "、".join(f"{(pool.get(c) or {}).get('name') or c}" for c in extra[:3])
        more = f" 等{len(extra)}只" if len(extra) > 3 else ""
        parts.append(f"二分多出 {len(extra)} 只（{names}{more}，触板未封/新股/THS池剔除需个股核）")
    if lack:
        parts.append(f"THS 多出 {len(lack)} 只（韭研 final 漏收，二分口径漏计）")
    return f"（{'；'.join(parts)}）"


def _ths_pool_items(db: Any, date: str, dataset_id: str, key: str) -> tuple[list[dict], bool]:
    """THS 15:00 帧指定池 items（rushing 等）；(items, found)。

    found=False = 帧缺失/该池未拉取（非 EOD 槽）/该池自身上游失败（池级 ok=False，
    见 market_proxy.limitup.get_ths_pools：每池独立返回 ok）——调用方写「不可算」，
    不把「取不到」当 0 家；池 ok 且 items 空 = 当日该池无股，合法 0。
    """
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"limitSummary.thsPools": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    pool = (((f or {}).get("limitSummary") or {}).get("thsPools") or {}).get("pools", {}).get(key)
    if not isinstance(pool, dict) or not pool.get("ok"):
        return [], False
    return list(pool.get("items") or []), True


def _seal_quality(db: Any, date: str, dataset_id: str) -> dict:
    """帧 limitSummary.sealQuality（一字板/硬板/烂板家数+share+均封板成功率）；缺失 → {}。"""
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"limitSummary.sealQuality": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    return ((f or {}).get("limitSummary") or {}).get("sealQuality") or {}


def _zhaban_face_count_fallback(db: Any, date: str, dataset_id: str) -> str:
    """旧采集 schema（仅家数）日的炸板面降级行（F1，2026-10-17 预注册 §2.1）。

    2026-07-30..09-23 共 16 天的 15:00 帧只有 `poolCounts`（failed/rushing/drawdown 家数）
    + `maxDrawdown/avgDrawdown`，没有 `pools.*.items`（个股）。旧实现整段写「不可算」把同帧
    已有家数一并丢弃（AGENTS §4.0）。本函数只输出**同源可算部分**，个股级子项与分位
    均标不可算（分位历史序列含旧 schema 日，混算属口径混用）。

    对比口径（预注册 D1）：新旧 schema 的炸板**家数**同义（`poolCounts.failed` ≙
    `len(pools.failed.items)`），允许家数级对比但必须带标注；个股级子项绝不跨 schema 编造。
    禁用 `snapshot_records.payload.limitSummary.zhaban.count`（前端口径）冒充 THS failed。
    """
    counts, found = _ths_pool_counts(db, date, dataset_id)
    if not found or not isinstance(counts, dict):
        return "今日炸板面：不可算（THS 炸板池缺失/降级，fail-visible）"
    n = counts.get("failed")
    r = counts.get("rushing")
    d = counts.get("drawdown")
    mx, av = counts.get("maxDrawdown"), counts.get("avgDrawdown")
    zb_txt = f"炸板 {n} 家" if isinstance(n, (int, float)) else "炸板家数不可算"
    rush_txt = f"冲刺未封 {r} 家" if isinstance(r, (int, float)) else "冲刺未封不可算"
    if isinstance(d, (int, float)):
        dd = (f"（最大回撤 {mx:+.2f}%、均值 {av:+.2f}%）"
              if isinstance(mx, (int, float)) and isinstance(av, (int, float)) else "")
        dd_txt = f"涨停股回撤榜 {d} 家{dd}"
    else:
        dd_txt = "涨停股回撤榜不可算"
    prev_dates = trading_dates_before(db, date, 1)
    cmp_txt = "不可算（无昨日交易日）"
    if prev_dates:
        p_items, p_found = _ths_failed_items(db, prev_dates[-1], dataset_id)
        if p_found:
            p_n: int | None = len(p_items)
        else:
            p_counts, p_cfound = _ths_pool_counts(db, prev_dates[-1], dataset_id)
            p_n = (p_counts or {}).get("failed") if p_cfound else None
        if isinstance(p_n, int) and isinstance(n, int):
            cmp_txt = (f"炸板 {p_n}→{n} 家（{n - p_n:+d}）· 反复开板 不可算（个股级缺）")
        else:
            cmp_txt = "不可算（昨日 THS 炸板池家数缺失）"
    return (f"今日炸板面（家数口径·旧采集 schema：仅家数可算，个股级子项不可算）："
            f"{zb_txt}；{rush_txt}；{dd_txt}；较昨日：{cmp_txt}；"
            f"反复开板/昨日池股炸板/炸板股收盘涨幅/代表股/归因打标 不可算（个股级缺失）；"
            f"分位不可算（历史序列含旧 schema 日）")


def zhaban_face_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """今日炸板面：THS 15:00 炸板池结构化证据（家数分位/反复开板/昨日池股炸板/大面/代表股/
    较昨日增减——2026-10-15 诊断补供 relay_momentum 主锚的昨日可比数）。

    预登记：docs/hotlist-jev/jev-relay-zhaban-preregistration.md（StepB，用户 2026-10-11 裁决）。
    炸板 0 家是合法强信号（正常呈现）；帧缺失/降级才写「不可算」。

    2026-10-16 补两段（审计问题 #6）：**冲刺未封**（THS 冲刺池=盘中冲板未封，与炸板池并列
    第三池，采集层一直有但 relay 从不消费）与**烂板**（涨停池里开板≥2 次又回封的，帧
    sealQuality 现成）——「炸板面」只覆盖曾封后开板，漏掉触板未封与封板质量另一半。
    """
    items, found = _ths_failed_items(db, date, dataset_id)
    items = list(items.values())
    if not found:
        # F1：旧 schema 只有家数（AGENTS §4.0 有可用数据就必须展示可算部分，禁止整段丢弃）
        return _zhaban_face_count_fallback(db, date, dataset_id)
    by_code = {str(i.get("code") or "")[-6:]: i for i in items if i.get("code")}
    n = len(by_code)
    # 近 20 日炸板家数分位（无帧历史日跳过，只取有数据的日）；同回溯顺带算反复开板家数分位
    # （2026-10-16 二级审计补供：relay_phase 判据「反复开板处参照高位/低位」原只有绝对值）
    hist = []  # (炸板家数, 反复开板家数) 逐日
    for d in trading_dates_before(db, date, 20):
        its2, f2 = _ths_failed_items(db, d, dataset_id)
        its2 = list(its2.values())
        if f2:
            by2 = {str(i.get("code") or "")[-6:]: i for i in its2 if i.get("code")}
            hi2 = sum(1 for i in by2.values()
                      if isinstance(i.get("open_num"), (int, float)) and i.get("open_num") >= 2)
            hist.append((len(by2), hi2))
    pct_txt = "（历史炸板数据不足 5 日，无分位参照）"
    if len(hist) >= 5:
        pct = round(sum(1 for x in hist if x[0] < n) / len(hist) * 100)
        pct_txt = f"（近{len(hist)}日分位 P{pct}，均值 {_median([x[0] for x in hist]) or 0:.0f} 家）"
    # 反复开板
    hi = [i for i in by_code.values() if isinstance(i.get("open_num"), (int, float)) and i.get("open_num") >= 2]
    hi_pct_txt = "（历史反复开板数据不足 5 日，无分位参照）"
    if len(hist) >= 5:
        hpct = round(sum(1 for x in hist if x[1] < len(hi)) / len(hist) * 100)
        hi_pct_txt = f"（近{len(hist)}日分位 P{hpct}）"
    hi_txt = f"反复开板(≥2次) {len(hi)} 家（占 {round(len(hi) / n * 100) if n else 0}%）{hi_pct_txt}"
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
            # 「N天M板」而非裸 M：裸「(10板)」读起来是昨日 10 连板，会把区间高度当连板高度
            names = "、".join(f"{p.get('name') or c}({_range_num_txt(p)})" for c, p in hi_layer[:3])
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
    # 较昨日增减（relay_momentum 主锚之二，2026-10-15 诊断补供）：criteria 判「炸板面收敛/
    # 恶化（炸板与反复开板较昨日减少/增多）」需昨日可比数，而分位/均值只给绝对位置——
    # 全库叙事此前从未组装昨日炸板家数，模型无从判方向，是 insufficient_evidence 逃生的
    # 结构性口子（10-15 P0/09-21 P62 两日均缺此锚）。昨日帧数据现成（分位回溯同源）。
    if not prev_dates:
        cmp_txt = "较昨日：不可算（无昨日交易日）"
    else:
        prev_items, prev_found = _ths_failed_items(db, prev_dates[-1], dataset_id)
        prev_items = list(prev_items.values())
        if not prev_found:
            # F1 兼容：昨日是旧 schema 日（只有家数）→ 家数级对比（同源同义字段，带标注；预注册 D1）
            prev_counts, prev_cfound = _ths_pool_counts(db, prev_dates[-1], dataset_id)
            prev_n2 = (prev_counts or {}).get("failed") if prev_cfound else None
            cmp_txt = (f"较昨日：炸板 {prev_n2}→{n} 家（{n - prev_n2:+d}）· 反复开板 不可算（个股级缺）"
                       if isinstance(prev_n2, int) and isinstance(n, int) else
                       "较昨日：不可算（昨日 THS 炸板池缺失/降级）")
        else:
            prev_by = {str(i.get("code") or "")[-6:]: i for i in prev_items if i.get("code")}
            p_n = len(prev_by)
            p_hi = sum(1 for i in prev_by.values()
                       if isinstance(i.get("open_num"), (int, float)) and i.get("open_num") >= 2)
            cmp_txt = (f"较昨日：炸板 {p_n}→{n} 家（{n - p_n:+d}）· "
                       f"反复开板 {p_hi}→{len(hi)} 家（{len(hi) - p_hi:+d}）")
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
    # 冲刺未封（2026-10-16 补供）：THS 冲刺池=盘中冲板未封，代表股按收盘涨幅降序
    rush_items, rush_found = _ths_pool_items(db, date, dataset_id, "rushing")
    if rush_found:
        rush_sorted = sorted((i for i in rush_items if isinstance(i.get("change_rate"), (int, float))),
                             key=lambda i: i["change_rate"], reverse=True)
        rush_names = "、".join(f"{i.get('name')}({i.get('change_rate'):+.1f}%)"
                              for i in rush_sorted[:3] if i.get("name"))
        rush_txt = f"冲刺未封 {len(rush_items)} 家" + (f"（{rush_names}）" if rush_names else "")
    else:
        rush_txt = "冲刺未封 不可算（THS 冲刺池缺失/降级）"
    # 烂板（涨停池里开板≥2 次又回封）：帧 sealQuality 现成，语料此前不消费。
    # rottenShare 在 quality_n==0（info_items 空）时由上游置 None，而 rottenCount 仍给 0——
    # 不判型就 round(None*100) 会 TypeError 炸掉整个 relay 日（fail-visible 变崩溃）
    sq = _seal_quality(db, date, dataset_id)
    rotten, share = sq.get("rottenCount"), sq.get("rottenShare")
    if isinstance(rotten, int) and isinstance(share, (int, float)) and not isinstance(share, bool):
        rotten_txt = f"涨停池烂板（开板≥2次回封）{rotten} 家（占 {round(share * 100)}%）"
    elif isinstance(rotten, int):
        rotten_txt = (f"涨停池烂板（开板≥2次回封）{rotten} 家"
                      f"（占比不可算：sealQuality 样本为空，fail-visible）")
    else:
        rotten_txt = "涨停池烂板 不可算（sealQuality 缺失）"
    return (f"今日炸板面：炸板 {n} 家{pct_txt}；{hi_txt}；{layer_txt}；{rate_txt}；"
            f"反复开板代表：{rep_txt or '无'}；{dist_txt}；{cmp_txt}；{rush_txt}；{rotten_txt}")


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
    # 近20日极值锚（涨停家数/最高板）；market_metrics None（帧缺失日）跳过——数据不足由下方分支兜底。
    # 含今日：trading_dates_before 严格早于 date，今日创新高时锚会显示旧峰值，与事实行
    # 「最高 11 板（100 分位）」自相矛盾（2026-10-16 600825 停牌复牌实证）。
    hist = trading_dates_before(db, date, 19) + [date]
    ms = [(d, m) for d, m in ((d, market_metrics(db, d)) for d in hist) if isinstance(m, dict)]
    zs = [(d, m.get("ztCount")) for d, m in ms if isinstance(m.get("ztCount"), (int, float))]
    mb = [(d, m.get("maxBoard")) for d, m in ms if isinstance(m.get("maxBoard"), (int, float))]
    if len(zs) >= 5:
        z_peak = max(zs, key=lambda x: x[1])
        z_low = min(zs, key=lambda x: x[1])
        # mb 可能为空：窗口内每日都有 ztCount 但 maxBoard 全 None（THS 炸板池缺失或韭研
        # final 缺失，真连板口径下比帧字段时代常见得多）。max([]) 会 ValueError 炸掉整日
        if mb:
            m_peak = max(mb, key=lambda x: x[1])
            board_anchor = f"；最高板峰值 {m_peak[1]} 板（{m_peak[0][5:]}）"
        else:
            board_anchor = "；最高板峰值 不可算（窗口内无真连板高度，fail-visible）"
        lines.append(f"近20日锚：涨停峰值 {z_peak[1]} 家（{z_peak[0][5:]}）/谷值 {z_low[1]} 家"
                     f"（{z_low[0][5:]}）{board_anchor}")
    else:
        lines.append("近20日锚：历史数据不足（fail-visible）")
    return lines


# ── 组装与 run ──────────────────────────────────────────────────────────────


def build_relay_narrative(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    lines: list[str] = [f"{date} 交易日 · 连板情绪指数判定（叙事）"]
    # 段1 总账（market_facts_line 已含双源梯队/分位）+ 今日炸板面（2026-10-11 StepB）
    lines.append(market_facts_line(db, date, dataset_id))
    lines.append(zhaban_face_line(db, date, dataset_id))
    lines.append(relay_flow_line(db, date, dataset_id))
    lines.append(ladder_structure_line(db, date))
    # 段2 记忆
    lines.append(three_day_chain_line(db, date, dataset_id))
    lines.append(theme_evolution_line(db, date))
    # 段2c 高位股多日轨迹（v4，2026-10-16 预注册 §2.3；有帽，非打分依据）
    lines.extend(high_position_trajectory_lines(db, date, dataset_id))
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
               # 主锚缺位标记（F2）：数据质量事实，不改打分（前端徽标/README 说明消费）
               "anchorGaps": anchor_gaps(narrative),
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
