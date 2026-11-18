# -*- coding: utf-8 -*-
"""连板情绪指数轨道（relay sentiment index，2026-10-10 Phase 1）。

- 叙事结构（§3 设计 + 2026-10-11 StepB 炸板面段 + 2026-10-16 v4 高位股多日轨迹段
  + 2026-10-19 v6 板块接力链/龙头结构段 + 2026-10-20 v7 全语料盘点
  + 2026-11-17 v10 精简，预注册 relay-v10-corpus-slim-preregistration-20261117.md
  + 2026-11-17 v11 匹配度修复，预注册 relay-v11-match-fix-preregistration-20261117.md）：
  总账（不含 THS 交叉分布）→ 大盘指数 → 今日炸板面 → 反包修复 → 弱转强参照（仅昨日分区+结构预检）
  → 晋级断板（含钱效 20 日分位）→ 梯队量化（含昨日分层）→ 三日链 → 题材演化
  → 题材事件（仅命中，v10）→ 板块接力链（三日；主线结论/同桶基线 v10 撤出，struct 保留）
  → 高位股多日轨迹 → 题材梯队表（仅龙一，v10）→ 龙头结构（含标签）→ 龙头档案（位置/板序/板型）
  → 近10日轨迹（无摆动锚，v10）→ 近20日参照锚（含分位刻度）→ 市场情绪周期 → 昨日相位
- 题目集：analysis/hotlist/jev_relay_ammo.QUESTIONS_RELAY（7 题一 call，questionSetVersion v11）
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
import json
import os
import time
from collections import Counter
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import THS_KEYS, percentile_fraction
from backend.analysis.hotlist.jev_relay_ammo import QUESTIONS_RELAY, QUESTION_SET_VERSION_RELAY
from backend.analysis.hotlist.theme_event_digest import (
    build_theme_evidence_block,
    corpus_state,
)
from backend.analysis.hotlist.theme_leader_ammo import rank_board_stocks
from backend.core.limit_rules import is_limit_down_pct
from backend.operations.jev_label_jiuyan import (
    DEFAULT_DATASET_ID,
    _adj_prev_series,
    _daily_bars,
    bars_need_upto,
    bars_source_provenance,
    _dispatch_jev,
    _jiuyan_board_count,
    _jiuyan_days_boards,
    _jiuyan_ladder,
    _prev_close_of_date,
    _range_height_text,
    _sealed_codes as _label_sealed_codes,
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


# 标记表：(名字, 行首作用域 | None, 针字符串表)。带行首作用域时可区分同字符串的两种语义——
# 如「韭研 final 缺失」在「题材梯队表：」（整表缺 → 主锚）与「三日晋级链：」（链上某日缺
# → 子项）下含义不同（2026-10-18 实测：首两日被误标为主锚缺位）。
# 主锚缺位（**整根锚不可用**：对应判据当日无原料）→ 定量：锚缺位×N（琥珀）
_MARKER = tuple[str, str | None, tuple[str, ...]]
_PRIMARY_ANCHOR_GAPS: tuple[_MARKER, ...] = (
    ("盘面事实", "盘面事实", ("盘面指标缺失",)),
    ("炸板面", "今日炸板面", ("今日炸板面：不可算",)),
    ("梯队", "梯队结构量化", ("梯队数据缺失",)),
    ("题材梯队表", "题材梯队表", ("韭研 final 缺失",)),
)
# 子项缺位（**主锚在、其子统计/对比/样本不可算**）→ 定量：子项缺×N（灰）
# 2026-10-18 分层动因（用户报「全部显示锚缺位」）：旧单列把派生项与主锚混在一起，
# 108 天里 67 天非空、其中 45 天只命中「断板钱效」（早期 TDX 60 棒窗够不到钱效样本）——
# 主锚其实齐备，徽标却漫天飞，例外标记退化成背景噪声。
_DERIVED_ANCHOR_GAPS: tuple[_MARKER, ...] = (
    ("炸板面个股级", "今日炸板面", ("反复开板/昨日池股炸板/炸板股大面/代表股/归因打标 不可算",)),
    ("炸板面对比", "今日炸板面", ("较昨日：不可算",)),
    ("断板钱效", None, ("样本不足（TDX 覆盖", "今日表现不可算",
     "较昨日断板：不可算", "隔日溢价不可算")),
    ("晋级链前池", "三日晋级链", ("韭研 final 缺失",)),
    # v6（2026-10-19）：板块接力链/龙头结构是主锚（梯队/题材/晋级链）的同源派生段，
    # 缺位归子项层——不得再抬主锚徽标（108 天噪声教训，预注册 §五）。
    (
        "板块接力链", None, ("板块接力链（三日）：不可算",
                            "三日存活 不可算")),
    ("龙头结构", "龙头结构", ("龙头结构：不可算",)),
    # v10：题材证据块改仅事件命中；主语料未采集时针（历史日恒缺 → 子项缺位）
    ("题材事件", "题材事件", ("语料未采集",)),
)


def _scan_markers(narrative: str, markers: tuple[_MARKER, ...]) -> list[str]:
    """按标记表扫叙事→命中名列表（纯函数）；带行首作用域时只在该前缀行内匹配。"""
    lines = narrative.splitlines()
    found: list[str] = []
    for name, scope, needles in markers:
        for line in lines:
            if scope and not line.startswith(scope):
                continue
            if any(needle in line for needle in needles):
                found.append(name)
                break
    return found


def anchor_gaps(narrative: str) -> list[str]:
    """叙事中「**主锚**缺位」标记（F2，2026-10-17 预注册 §2.4）：纯函数，**不改打分**。

    落库为 relay 文档 `anchorGaps` 字段，供前端琥珀徽标呈现「本日哪根主锚整根不可用」——
    避免把 IE 读成模型能力问题（诊断文档四批 IE 全在原料/读口径层，非模型/判据）。
    子统计级缺位另走 `anchor_gaps_derived`（不占主锚徽标，防例外标记退化成噪声）。
    """
    return _scan_markers(narrative, _PRIMARY_ANCHOR_GAPS)


def anchor_gaps_derived(narrative: str) -> list[str]:
    """叙事中「子项缺位」标记（主锚在，但子统计/对比/样本不可算）：纯函数，不改打分。

    落库为 `anchorGapsDerived`，供前端灰色徽标（区分于主锚缺位的琥珀）与细节展示。
    """
    return _scan_markers(narrative, _DERIVED_ANCHOR_GAPS)


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


def _money_hist_series(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                       n: int = 20) -> list[dict[str, Any]]:
    """近 n 个交易日（**严格早于当日**，零未来函数）的接力生态逐日序列：
    晋级率 / 炸板家数 / 断板中位+大面 / 隔日溢价中位（v7 D3/D4 分位与刻度的原料）。

    口径与今日主行 relay_flow_line **单源同规**（`_promotion_stats`：二分封板 +
    v4 停牌/不可验同剔分子分母——评审修复第二刀，旧手搓 |prev_zt∩cur_zt|/|prev_zt|
    把停牌股算成「未晋级」，分位刻度被系统性压低）；premium 基数同改
    promoted∪broken（与主行 elig 一致）。断板/溢价中位走 `_close_pct`（TDX 日线，
    F4 门槛不足该日不入样本，None 缺席）。每日一项不可算 → None（调用方按有效
    样本数披露，不补 0）。韭研 final 缺失日**整日不入序列**（评审修复第一刀：
    旧实现 cur 池缺失时 promo 落 0 + 断板=昨日全池，伪造数据污染分位刻度，§4.0）。
    """
    hist = trading_dates_before(db, date, n, dataset_id=dataset_id)
    rows: list[dict[str, Any]] = []
    for i, d in enumerate(hist):
        prev = hist[i - 1] if i > 0 else (
            trading_dates_before(db, d, 1, dataset_id=dataset_id) or [None])[-1]
        if not prev or not _pool_of(db, d):
            continue
        stats = _promotion_stats(db, prev, d, dataset_id)
        if not stats.get("ok"):
            continue
        promoted, broken = set(stats["promoted"]), set(stats["broken"])
        row: dict[str, Any] = {"date": d, "promo": None, "zhaban": None,
                               "broken_median": None, "big": None, "premium_median": None}
        row["promo"] = stats["rate"]
        items, found = _ths_failed_items(db, d, dataset_id)
        if found:
            row["zhaban"] = len(items)
        if broken:
            pcts = [p for p in (_close_pct(c, prev, d) for c in sorted(broken)) if p is not None]
            if _tdx_sample_ok(len(pcts), len(broken)):
                row["broken_median"] = _median(pcts)
                row["big"] = sum(1 for p in pcts if p <= -5)
        elig = sorted(promoted | broken)
        prem = [p for p in (_close_pct(c, prev, d) for c in elig) if p is not None]
        if _tdx_sample_ok(len(prem), len(elig)):
            row["premium_median"] = _median(prem)
        rows.append(row)
    return rows


def relay_flow_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                    money_hist: list[dict[str, Any]] | None = None) -> str:
    """晋级率 + 断板亏钱 + 隔日溢价（D-1 池 × D0；v4 停牌跳过续算）。

    停牌/不可验股既不进晋级也不进断板（分母同剔，文案披露）；断板亏钱带较昨日对比
    （2026-10-16 二级审计补供 relay_phase.divergence 判据）；分层顶层 cap=_LAYER_CAP。
    v7 D3：断板中位/大面/隔日溢价各带近 20 日分位——此前钱效只有「较昨日」单对照点，
    昨日恰为极差日（如 10-19 大面 17）会把今日衬成收敛；分位算法单源
    jev_driver_ammo.percentile_fraction（样本 <10 返 None → 不输出，不伪刻度）。
    `money_hist` 由叙事组装一次算齐传入（与锚段刻度共用，防双算）；缺省自算。
    """
    prev_dates = trading_dates_before(db, date, 1)
    if not prev_dates:
        return "晋级与断板：无昨日交易日"
    prev_date = prev_dates[-1]
    stats = _promotion_stats(db, prev_date, date, dataset_id)
    if not stats.get("ok"):
        return f"晋级与断板：{stats['reason']}"
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
    calib = ""   # 2026-10-30g+：口径注删（用户裁决）
    rate_txt = f"{rate}%" if rate is not None else "不可算"
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
            # v11 M4：大面占断板比预算好（money strong/losing、phase relay_heat/collapse 四处判据
            # 消费占比阈值，与「数据已算好勿自行心算」指令一致；反复开板占比同款口径）
            big_share = round(cur_stats["big"] / len(broken) * 100)
            broken_txt = (f"断板 {len(broken)} 只：今日收盘中位 {cur_stats['median']:+}%，"
                          f"大面(≤-5%) {cur_stats['big']} 只（占断板 {big_share}%）{dt_txt}"
                          f"（TDX 覆盖 {cur_stats['covered']}/{len(broken)}）")
        elif cur_stats:
            broken_txt = _sample_short_txt("断板", len(broken), cur_stats["covered"])
        else:
            broken_txt = f"断板 {len(broken)} 只：今日表现不可算"
    else:
        broken_txt = "断板 0 只"
    # 较昨日断板：前日池昨日断板（同 _promotion_stats 停牌口径，剔停牌/不可验）。判据「断板
    # 亏钱扩散（中位转负或大面增多）」需要昨日可比数，此前只给今日绝对值（2026-10-16 补供）。
    window2 = trading_dates_before(db, date, 2)
    if len(window2) < 2:
        prev_broken_txt = "较昨日断板：不可算"
    else:
        d2 = window2[-2]
        stats2 = _promotion_stats(db, d2, prev_date, dataset_id)
        if not stats2.get("ok"):
            prev_broken_txt = "较昨日断板：不可算"
        else:
            pb = set(stats2["broken"])
            ps = _broken_stats(pb, d2, prev_date)
            calib2 = ""   # 2026-10-30g+：口径注删
            if not pb:
                prev_broken_txt = "较昨日断板：昨日 0 只"
            elif ps is None:
                prev_broken_txt = "较昨日断板：不可算"
            elif not _tdx_sample_ok(ps["covered"], len(pb)):
                prev_broken_txt = ("较昨日断板：" + _sample_short_txt("昨日断板", len(pb), ps["covered"]))
            elif not broken:
                prev_broken_txt = (f"较昨日断板：昨日中位 {ps['median']:+}%、"
                                   f"大面 {ps['big']} 只 → 今日断板 0 只{calib2}")
            elif cur_stats is None:
                # `_broken_stats` 返 None = 当日**无任何日线**（非「覆盖 0」）。2026-10-18
                # review P1-1：旧式 `covered if cur_stats else 0` 会把「日线源整体不可用」
                # 渲染成「TDX 覆盖 0/N」这个并不存在的读数（伪 0，§4.0），且归因词也从
                # 「日线缺失」误成「样本不足」——同函数今日段（broken_txt）早就写作
                # 「不可算（TDX 日线缺失）」，此处与之对齐。
                prev_broken_txt = "较昨日断板：不可算"
            elif not cur_stats_ok:
                prev_broken_txt = ("较昨日断板：今日断板样本不足"
                                   f"（TDX 覆盖 {cur_stats['covered']}/{len(broken)}），不可比")
            else:
                prev_broken_txt = (f"较昨日断板：中位 {ps['median']:+}%→{cur_stats['median']:+}%、"
                                   f"大面 {ps['big']}→{cur_stats['big']} 只{calib2}")
    # 隔日溢价（昨日可交易涨停股今日收盘中位；停牌/不可验不入基数）
    elig = sorted(promoted_set | broken_set)
    prem = [p for p in (_close_pct(c, prev_date, date) for c in elig) if p is not None]
    if not prem:
        prem_txt = "隔日溢价不可算"
    elif _tdx_sample_ok(len(prem), len(elig)):
        prem_txt = f"隔日收盘溢价中位 {_median(prem):+}%（覆盖 {len(prem)}/{len(elig)}）"
    else:
        prem_txt = _sample_short_txt("隔日溢价样本", len(elig), len(prem))
    # 涨停家数口径对账（2026-10-16）：同花顺涨停池参照，差集=触板未封/新股，防两口径数字打架
    caliber = _zt_caliber_note(db, prev_date, dataset_id, set(base), prev_pool)
    # 钱效近20日分位（v7 D3）：今日值 vs 严格早于当日的近 20 日序列（zero 前视）。
    # 今日断板中位/大面须过 F4 样本门（cur_stats_ok）才参与，防 n=1 伪精度进分位。
    if money_hist is None:
        money_hist = _money_hist_series(db, date, dataset_id)
    pct_items = []
    if cur_stats_ok:
        for label, cur, key in (("断板中位", cur_stats["median"], "broken_median"),
                                ("大面", cur_stats["big"], "big")):
            p = percentile_fraction([r.get(key) for r in money_hist], cur)
            pct_items.append(f"{label} P{round(p * 100)}" if p is not None
                             else f"{label} 分位不可算")
    if prem and _tdx_sample_ok(len(prem), len(elig)):
        p = percentile_fraction([r.get("premium_median") for r in money_hist], _median(prem))
        pct_items.append(f"隔日溢价 P{round(p * 100)}" if p is not None else "隔日溢价 分位不可算")
    pct_txt = (f" · 钱效近20日分位（{len(money_hist)} 日）：{' · '.join(pct_items)}"
               if pct_items else "")
    return (f"晋级与断板：昨日 {len(base)} 只涨停 → "
            f"今日仍涨停 {len(promoted)} 只"
            f"（晋级率 {rate_txt}）{skip_txt}[{layer_txt}] · {broken_txt} · {prev_broken_txt} · {prem_txt}"
            f"{pct_txt}")


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
        return "梯队结构量化：梯队数据缺失"
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
        src_txt = ""   # 2026-10-30g+：口径注删
    elif src and src != "jiuyan":
        src_txt = ""   # 2026-10-30g+：来源注删
    else:
        src_txt = ""
    # v7 D6：昨日分层家数入语料——ladder fracture 判据「二板较昨日腰斩」自此可验
    # （判据引用什么语料给什么；昨日梯队缺失 → 不输出，不伪 0）
    prev_layer_txt = (f" · 昨日梯队：一板 {prev_one}/二板 {prev_two}/三板+ {prev_tp}"
                      if prev_total else "")
    return (f"梯队结构量化：{first_txt} · 二板 {two} 只 · "
            f"三板+ {three_plus} 只 · {ratio_txt}{src_txt}{prev_layer_txt}")


def three_day_chain_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """D-2 池 → D-1 → D0 存活链 + 高位股逐日点名（relay_momentum/relay_phase 主锚；二分口径）。

    v4（2026-10-16）：停牌分辨——停牌股既不计晋级也不计断板（跳过续算），fate 增
    「今日停牌跳过/昨日停牌今日回封」档；边际对比与 relay_flow_line 共用 _promotion_stats，
    两处晋级率数字必然一致（禁漂移）。
    """
    window = trading_dates_before(db, date, 2)
    if len(window) < 2:
        return "三日晋级链：历史不足"
    d2, d1 = window[-2], window[-1]
    p2, p1, p0 = _pool_of(db, d2), _pool_of(db, d1), _pool_of(db, date)
    if not p2 or not p1:
        return f"三日晋级链：{d2}/{d1} 韭研 final 缺失"
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
    calib = ""   # 2026-10-30g+：口径注删
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
            fate.append(f"{name} {rng}→今日状态不可验")
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
        cmp_txt = "边际对比：不可算"
    elif d1_rate is None or r1 is None:
        cmp_txt = "边际对比：不可算"
    else:
        cmp_txt = (f"边际对比：昨日池今日晋级率 {d1_rate}%"
                   f"（{stats_b['denom']}→{len(stats_b['promoted'])}）"
                   f" vs 前日池昨日 {r1}%（{den_a}→{len(s1)}），{round(d1_rate - r1, 1):+.1f}pct")
    # 涨停家数口径对账（2026-10-16，同 relay_flow_line）：D-2 家数给同花顺池参照+差集
    d2_caliber = _zt_caliber_note(db, d2, dataset_id, base2, p2)
    return (f"三日晋级链：{d2} 涨停 {len(base2)} 只 → "
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


def _sector_top3_streaks(db: Any, date: str, names: list[str], limit: int = 10
                         ) -> dict[str, int]:
    """各板块「连续位居题材家数 top3」天数（自今日向回，中断即止；0=今日不在 top3）。

    2026-10-19 v6 单源抽取（原为 `theme_evolution_line` 内联闭包）：题材演化段与
    板块接力链段共用同一算法，一次取数供多板块共用（原实现每板块重复 10 次查库）。
    """
    if not names:
        return {}
    prev = trading_dates_before(db, date, limit - 1) if limit > 1 else []
    dates = prev + [date]
    tops: dict[str, list[str]] = {}
    for d in dates:
        b = _boards_of(db, d)
        tops[d] = sorted(b, key=lambda k: -len(b[k]))[:3] if b else []
    out: dict[str, int] = {}
    for name in names:
        n = 0
        for d in reversed(dates):
            if name in tops[d]:
                n += 1
            else:
                break
        out[name] = n
    return out


def theme_evolution_line(db: Any, date: str, lookback: int = 5) -> str:
    """昨日 top3 题材今日地位 + 近5日题材榜（主线持续天数证据；v9 删 theme_pulse 后保留作
    relay_index/relay_phase 的题材结构参照，删题不删叙事）。"""
    prev_dates = trading_dates_before(db, date, 1)
    if not prev_dates:
        return "题材演化：无昨日交易日"
    cur_b, prev_b = _boards_of(db, date), _boards_of(db, prev_dates[-1])
    if not cur_b or not prev_b:
        return "题材演化：韭研 final 缺失"
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
    # 连续在榜天数（自今日向回数，中断即止）——单源 `_sector_top3_streaks`
    top3_streaks = _sector_top3_streaks(db, date, cur_top)
    streaks = [f"{name} 连续{top3_streaks.get(name, 0)}日top3" for name in cur_top]
    streak_txt = "；".join(streaks)
    hist_txt = f"\n近5日题材榜：{' ； '.join(history)}" if history else ""
    return (f"题材演化：今日 top3 [{' / '.join(rows)}]；与昨日 top3 重合 {overlap}/3；连续性：{streak_txt}"
            f"（{'top3 延续' if overlap >= 2 else '轮动换线' if overlap == 1 else '全面换血'}）{hist_txt}")


# ── 段 2b'：题材证据块（v7 D5，韭研产业树+投资日历确定性拼装）─────────────────


def theme_evidence_lines(db: Any, date: str, top: int = 3) -> list[str]:
    """top3 板块题材事件命中行（v10 精简：仅渲染事件/日历命中）。

    v7 D5 原完整证据块（催化原文/未映射/无匹配）为 theme_pulse 供给；v9 删题后
    8 题判据零引用，v10 用户裁决撤出孤儿证据：只有当日题材事件与未来 3 日既定
    事件的**命中**进叙事（增量信息），无命中整块缺席（AGENTS §1.2-8）；语料未
    采集保留例外事实行。匹配单源 = theme_event_digest.build_theme_evidence_block
    （结构化 events/calendar 字段），本函数只做 relay 侧命中投影，禁二次匹配实现。
    """
    cur_b = _boards_of(db, date)
    if not cur_b:
        return []   # 韭研 final 缺失已由题材梯队表主锚标记披露，不重复
    state = corpus_state(db, date=date)
    if not state.get("ok"):
        return ["题材事件：语料未采集"]
    names = sorted(cur_b, key=lambda k: -len(cur_b[k]))[:top]
    rows: list[str] = []
    for name in names:
        block = build_theme_evidence_block(db, board_name=name, date=date,
                                           include_l2=False)
        hits: list[str] = []
        for ev in block.get("events") or []:
            hot = f"（热度 {ev.get('hotVal')}）" if ev.get("hotVal") is not None else ""
            hits.append(f"当日 {ev.get('day')} {ev.get('title')}{hot}")
        for ev in block.get("calendar") or []:
            tag = f"[{ev.get('tagName')}]" if ev.get("tagName") else ""
            hits.append(f"既定 {ev.get('date')}{tag} {ev.get('brief')}")
        if hits:
            rows.append(f"· {name}：{'；'.join(hits)}")
    if not rows:
        return []   # 全 top3 无命中 → 整块缺席，不留「无匹配」占位
    return ["题材事件（top3 板块）："] + rows


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
        return ["高位股多日轨迹：韭研 final 缺失"]
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
        return ["高位股多日轨迹：日线不可用"]
    marks_of = {"sealed": "●", "broken": "○", "suspended": "·", "unknown": "?"}
    lines = [f"高位股多日轨迹（近 {len(axis)} 个交易日逐日；"
             f"●封板/○断板/·停牌跳过/?不可验）："]
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


def theme_ladder_lines(db: Any, date: str, top: int = 5,
                       mainline: str | None = None) -> list[str]:
    """top5 题材：龙一（day desc, time asc；v10 只留龙一，龙二/三与板内标签聚合撤出）。

    2026-10-16 口径修正（用户报「其他板块龙一语料写成10板，应写14天10板」）：龙序仍按
    区间高度 M 排（14天10板 本就是该板块最显高位股），但文案补「N天M板」+ 真连板数——
    「连板」语义不再拿区间 M 冒充（澳弘电子 19天11板真连板=1 之教训）。

    2026-10-19 v6：增 `mainline` 参数——主线板块可能不在家数 top5（家数多但无高位股的
    板块会遮住它），故强制纳入并置顶（预注册 §三）；个股标签聚合口径不变。
    """
    prev_dates = trading_dates_before(db, date, 1)
    cur_b = _boards_of(db, date)
    if not cur_b:
        return ["题材梯队表：韭研 final 缺失"]
    prev_b = _boards_of(db, prev_dates[-1]) if prev_dates else {}
    streaks = jiuyan_streak_map(db, date)
    failed_items, failed_found = _ths_failed_items(db, date, DEFAULT_DATASET_ID)
    zhaban_codes = set(failed_items) if failed_found else set()
    lines = ["题材梯队表："]
    # 龙一重锚（2026-11-09 三链合一）：龙一槽位=板块节点空间龙一档；档缺失/非 v5 →
    # 回退 dragon_rows 原口径，只留缺位事实（v10：口径图例删，定义见预注册文档）
    from backend.operations.sector_nodes import ledger_leaders, reanchor_dragons
    ledger = ledger_leaders(db, date)
    ledger_anchored = ledger is not None
    if ledger is None:
        lines.append("·龙一档缺失")
    ranked_names = sorted(cur_b, key=lambda k: -len(cur_b[k]))
    # 主线板块强制纳入 top5（家数多≠主线；用户 2026-10-19 裁决口径）
    if mainline and mainline in cur_b and mainline not in ranked_names[:top]:
        ranked_names = [mainline] + ranked_names[:top - 1]
    else:
        ranked_names = ranked_names[:top]
    for name in ranked_names:
        # 龙序：龙一=空间龙一档（三链合一）；龙二/三=dragon_rows 补位；档缺失回退原口径
        dragons_rows = dragon_rows(cur_b[name], streaks=streaks)
        board_fallback_note = ""
        if ledger_anchored:
            if name in (ledger or {}):
                dragons_rows = reanchor_dragons({name: dragons_rows}, ledger or {})[name]
            else:
                # 锚定日个别板块不在龙一台账（无龙头行/空间缺料跳过）：逐板块注记回退，
                # 不吃掉表头的全局锚定声明（P2-11 评审）
                board_fallback_note = "·龙一档缺该板块"
        # v10：relay 侧只留龙一（8 题判据不消费龙二/三；题材链自有完整龙序供给）
        dragons = []
        for i, d in enumerate(dragons_rows[:1], 1):
            code = d.get("code")
            st = d.get("streak")
            if d.get("ledgerUnsealed"):
                # 断板反包龙一（今日未封）：区间高度如实缺位，不伪装「首板」
                height_txt = "断板反包·今日未封"
                st_txt = ""
            else:
                height_txt = _range_num_txt(d)
                if code in zhaban_codes:
                    st_txt = "·今日炸板"
                elif isinstance(st, int):
                    st_txt = f"·连板{st}板"
                elif d.get("boards"):
                    st_txt = "·连板不可算"
                else:
                    st_txt = ""
            dragons.append(f"{d.get('role') or '龙' + '一二三'[i-1]} {d['name']}({height_txt} "
                           f"{d['time'] or '?'}{st_txt})")
        # v10：新鲜/延续/驱动主类打标聚合撤出（theme_pulse 孤儿字段，题材链自有供给）
        prev_n = len(prev_b.get(name) or [])
        tag = "（主线）" if mainline == name else ""
        lines.append(f"· {name}{tag}：{' / '.join(dragons)}｜昨日 {prev_n} 只"
                     f"{board_fallback_note}")
    return lines


# ── 段 4：龙头档案 ──────────────────────────────────────────────────────────


def leader_profile_lines(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                         *, total_leader: dict[str, Any] | None = None) -> list[str]:
    """龙头档案（个股位置/板序/当日板型；v10 头行并入龙头结构·总龙头行）。

    v10（2026-11-17 C1）：头行与龙头结构·总龙头行逐字重复，已并入总龙头行（含标签）；
    本段只留个股位置/板序/板型三行（v9 保留裁决不变）。板序图例经 legend=False 去除，
    一次性进 relay_index instructions（A5）。

    2026-10-19 v6：`total_leader` 由 `relay_structure` 传入（单一选股事实源，防龙头结构段与
    本段选出两只不同股）；缺省时内部自算（直调兼容，口径与本段原实现完全一致）。
    """
    pool = _pool_of(db, date)
    if not pool:
        return ["龙头档案：韭研 final 缺失"]
    if total_leader is None:
        code0, entry0 = sorted(pool.items(), key=lambda kv: (
            -_day_eff(kv[1]), str(kv[1].get("time") or "99:99")))[0]
        total_leader = {"code": code0, "name": entry0.get("name") or code0}
    code, name = total_leader.get("code"), total_leader.get("name")
    lines = [stock_position_line(date, code)]
    lines.append(limitup_sequence_line(date, code, name, legend=False))
    lines.append(stock_board_shape_line(date, code, name, _prev_close_of_date(date, code)))
    return lines


# ── 段 3.5 / 4.5：板块接力链 + 龙头结构（v6，2026-10-19）───────────────────
# 预注册：docs/hotlist-jev/jev-relay-sector-leader-preregistration.md
# 口径（用户 2026-10-19 裁决，不得漂移）：
#   · 总龙头 = 区间高度 M 最高（并列封板早）——与龙头档案同源；
#   · 情绪龙头 = 当前真连板最高（并列 M→封板早）；
#   · 板块龙头 = dragon_rows 龙一（与涨停复盘「领涨」列同源）；
#   · 主线板块 = 三日链存活股归属最多，逐级降级可数（存活→晋级→家数→最高板）；
#   · 首板日 = 韭研「N天M板」的 N 推算 + 池史单点校验（缺失才回退 60 日池史回溯），
#     **全程不读 TDX**：回放历史日不受「日线取现在」缺口影响。
_SECTOR_BASIS_CN = {
    "three_day_survivors": "三日链存活股归属最多",
    "promoted": "存活是真零（三日链可算），改用今日晋级股归属",
    "d0_count": "存活与晋级均为真零（三日链可算），改用今日板块涨停家数",
    "chain_na": "三日链不可算，改用今日板块涨停家数",
}
# 韭研泛板块（非题材口径）：家数天然最大，若不过滤，主线永远被“其他/公告/新股”吃掉
# （2026-10-19 生产干跑实测：10-16 三日链存活最多的是“其他”，龙一却是真题材股）。
# 只在**主线选择**里降权（真题材优先），展示与统计仍如实列出并标「泛板块」。
_PSEUDO_BOARDS = {"其他", "公告", "新股"}
_STATUS_CN = {"sealed": "封板", "broken": "断板", "suspended": "停牌跳过", "unknown": "不可验"}


def _streak_txt(v: Any) -> str:
    """真连板文案（不可验不回落区间 M）。"""
    return f"{v}" if isinstance(v, int) else "不可算"


def _sector_day_stat(stocks: list[dict[str, Any]],
                     streaks: dict[str, int | None] | None = None) -> dict[str, Any]:
    """单板块单日结构：家数 + 区间最高（龙序首名）+ 真连板。空列表 = 合法 0 家。"""
    if not stocks:
        return {"count": 0, "maxBoard": None, "maxBoardText": None,
                "streak": None, "top": None}
    top = dragon_rows(stocks, streaks=streaks, top=1)
    t = top[0] if top else None
    if not t:
        return {"count": len(stocks), "maxBoard": None, "maxBoardText": None,
                "streak": None, "top": None}
    return {"count": len(stocks),
            "maxBoard": t.get("boards"),
            "maxBoardText": _range_num_txt({"boards": t.get("boards"),
                                            "days": t.get("days")}),
            "streak": t.get("streak"),
            "top": t}


def _pool_history_first_date(db: Any) -> str | None:
    """韭研 final 池史最早交易日（原料边界；`_pool_of` 同源，按 `_id` 尾「:final」取）。

    2026-10-19 §14.6：原实现把「首板日早于韭研池史起点」也写成「口径不一致」，
    违反 §1.2.6 归因顺序（先查原料再查题目/口径）。仅在降级路径调用（≤1 次/日）。
    """
    dates = []
    for r in db["jiuyan_action"].find({"_id": {"$regex": ":final"}}, {"tradingDate": 1, "_id": 1}):
        d = r.get("tradingDate") or str(r.get("_id") or "").split(":")[0]
        if d:
            dates.append(str(d))
    return min(dates) if dates else None


def _leader_genesis(db: Any, date: str, code: str, entry: dict[str, Any],
                    streak: int | None) -> dict[str, Any]:
    """总龙头诞生轨迹：首板日 / 距今交易日数 / 区间内断板次数 / 当前真连板。

    首板日推算 = 韭研「N天M板」的 N（N 天窗口的首日）；随后**单点校验**该日是否真在
    韭研池，不可核时按原料→口径的顺序给原因（三种，见下，均 fail-visible、不静默）。
    N 缺失时才回退 60 日池史回溯（需 60 次查库，仅罕见路径）。全程只用韭研池史，
    不读 TDX（回放历史日不受「日线取现在」缺陷影响）。
    """
    boards, days = entry.get("boards"), entry.get("days")
    out: dict[str, Any] = {"firstBoardDate": None, "tradingDaysAgo": None,
                           "breaks": None, "streak": streak, "degraded": None}
    if not boards or boards <= 1:
        out.update(firstBoardDate=date, tradingDaysAgo=0, breaks=0)
        return out
    span = days if isinstance(days, int) and days > 1 else None
    if span is None:
        hist = trading_dates_before(db, date, 60)
        for i, d in enumerate(hist):
            if code in _pool_of(db, d):
                out.update(firstBoardDate=d, tradingDaysAgo=len(hist) - i)
                edge = "；首板日已在 60 日窗沿，实际可能更早" if i == 0 else ""
                out["degraded"] = (f"韭研区间天数缺失，断板次数不可算{edge}")
                return out
        out["degraded"] = "首板日超出 60 日回溯窗"
        return out
    # 韭研「N天M板」的 N 是**区间跨度（含今日）**，故首板日 = N-1 个交易日前（
    # 2026-10-19 review P1：旧写 N 与同时打印的日期相差一天，段内自相矛盾）。
    out["tradingDaysAgo"] = span - 1
    out["breaks"] = max(span - boards, 0)
    hist = trading_dates_before(db, date, span - 1)
    if not hist or len(hist) < span - 1:
        out["degraded"] = f"首板日超出可取交易日史（需回溯 {span} 个交易日）"
        return out
    first = hist[0]
    out["firstBoardDate"] = first
    pool = _pool_of(db, first)
    if code in pool:
        return out
    # 归因顺序（§1.2.6）：①原料边界（早于韭研池史起点 / 该日池缺失）→ ②题目/口径（首板日推算）。
    edge = _pool_history_first_date(db)
    if edge and first < edge:
        out["degraded"] = f"首板日 {first} 早于韭研池史起点"
    elif not pool:
        out["degraded"] = f"首板日 {first} 韭研池缺失"
    else:
        out["degraded"] = f"首板日 {first} 不在韭研池"
    return out


def _mainline_sustain(db: Any, date: str, board_name: str,
                      pool: dict[str, dict[str, Any]],
                      boards_today: dict[str, list[dict[str, Any]]],
                      streaks: dict[str, int | None],
                      dataset_id: str) -> dict[str, Any] | None:
    """主线板块的同桶基线桶键（封板口径；v7 D5 评审修复）。

    与 SUSTAIN 表构建口径（theme_leader_baseline.day_leader_rows）逐项对齐：
    家数=板块内真实封板股（触板池 − THS 炸板池）；龙一=rank_board_stocks 真连板
    序（非区间 M 序）。THS 池缺失日二分不可用 → 按触板口径并打 `touchCaliber`
    （调用方披露，不静默混口径）；板块无成员 → None（fail-visible，不猜桶）。
    """
    sealed, found = _sealed_codes(db, date, set(pool), dataset_id)
    members = [s for s in boards_today.get(board_name) or []
               if (str(s.get("code") or "")[-6:]) in sealed]
    if not members:
        return None
    ranked = rank_board_stocks([
        {"code": str(s.get("code") or "")[-6:], "name": s.get("name"),
         "time": s.get("time"),
         "streak": streaks.get(str(s.get("code") or "")[-6:])}
        for s in members])
    leader = ranked[0]
    return {"code": leader["code"], "name": leader.get("name"),
            "streak": leader.get("streak"), "time": leader.get("time"),
            "boardN": len(members), "touchCaliber": not found}


def relay_structure(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, Any]:
    """板块接力链 + 龙头结构：v6 **唯一计算入口**（叙事渲染与文档落库共用，防三处漂移）。

    结构见预注册 §二；fail-visible：任一段不可算落 `degraded` 并写明原因，不伪造 0。
    """
    axis_prev = trading_dates_before(db, date, 2, dataset_id=dataset_id)
    axis = list(axis_prev) + [date]
    dates = {"d2": axis[-3] if len(axis) >= 3 else None,
             "d1": axis[-2] if len(axis) >= 2 else None,
             "d0": date}
    out: dict[str, Any] = {"dates": dates, "sectors": [], "mainline": None,
                           "mainlineDragon": None, "totalLeader": None,
                           "sentimentLeader": None, "sameStock": None,
                           "leaderIsMainlineDragon": None, "genesis": None,
                           "succession": None, "chain": {"ok": False, "reason": None},
                           "degraded": []}
    pools: dict[str, dict[str, dict[str, Any]]] = {}
    boards: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for d in axis:
        pools[d] = _pool_of(db, d)
        boards[d] = _boards_of(db, d)
        if not pools[d]:
            out["degraded"].append(f"{d} 韭研 final 缺失")
    if not pools[date]:
        return out
    streaks = jiuyan_streak_map(db, date, dataset_id)
    pool = pools[date]

    # ── 三日链存活 / 今日晋级（口径同 three_day_chain_line：_promotion_stats 单源）
    # chain.ok=False（链日无韭研 final / 历史不足）时 survivors/promoted 一律 None——
    # 缺料绝不得渲染成「0 只」（AGENTS §4.0；2026-10-19 review P1 伪 0）。
    survivors: set[str] = set()
    promoted_today: set[str] = set()
    chain_reason: str | None = None
    if not dates["d2"]:
        chain_reason = "历史不足（<3 交易日）"
    else:
        missing_chain = [d for d in (dates["d2"], dates["d1"]) if not pools[d]]
        if missing_chain:
            chain_reason = f"{'/'.join(missing_chain)} 韭研 final 缺失"
    if chain_reason is None:
        stats_a = _promotion_stats(db, dates["d2"], dates["d1"], dataset_id)
        stats_b = _promotion_stats(db, dates["d1"], date, dataset_id)
        if stats_a.get("ok") and stats_b.get("ok"):
            survivors = set(stats_a["promoted"]) & set(stats_b["promoted"])
            promoted_today = set(stats_b["promoted"])
        else:
            chain_reason = f"{dates['d2']}/{dates['d1']} 晋级率不可算"
    chain_ok = chain_reason is None
    out["chain"] = {"ok": chain_ok, "reason": chain_reason}
    if chain_reason:
        out["degraded"].append(f"三日链不可算（{chain_reason}）")
    else:
        for c in sorted(survivors | promoted_today):
            if c not in pool:
                out["degraded"].append(f"{c} 不在今日韭研池")

    names: list[str] = []
    for d in axis:
        for n in boards[d]:
            if n not in names:
                names.append(n)
    if not names:
        out["degraded"].append("韭研板块结构为空")
        return out
    # 个股归属（存活/晋级/龙头）取 _pool_of 首个板块；家数/最高板按韭研全部归属不去重
    surv_by = Counter(pool[c].get("board") for c in survivors if c in pool and pool[c].get("board"))
    prom_by = Counter(pool[c].get("board") for c in promoted_today
                      if c in pool and pool[c].get("board"))
    rows: list[dict[str, Any]] = []
    for n in names:
        d0 = _sector_day_stat(boards[date].get(n) or [], streaks)
        # 韭研 final 缺失日 → stat=None（渲染写「缺失」），不得落成「0 只」（AGENTS §4.0 伪 0）
        rows.append({
            "name": n,
            "d2": (_sector_day_stat(boards[dates["d2"]].get(n) or [])
                   if dates["d2"] and pools[dates["d2"]] else None),
            "d1": (_sector_day_stat(boards[dates["d1"]].get(n) or [])
                   if dates["d1"] and pools[dates["d1"]] else None),
            "d0": d0,
            "survivors": surv_by.get(n, 0) if chain_ok else None,
            "survivorNames": (sorted(pool[c].get("name") or c for c in survivors
                                     if c in pool and pool[c].get("board") == n)
                              if chain_ok else []),
            "promoted": prom_by.get(n, 0) if chain_ok else None,
            "top3Streak": 0,
            "dragon": d0.get("top"),
        })

    def _rank_key(r: dict[str, Any]) -> tuple:
        d0 = r.get("d0") or {}
        return (-(r.get("survivors") or 0), -(r.get("promoted") or 0),
                -(d0.get("count") or 0), -(d0.get("maxBoard") or 0), r["name"])

    def _basis_of(row: dict[str, Any]) -> str | None:
        """主线依据键；三日链不可算时只会落到「今日家数」档（文案与真零区分）。"""
        d0 = row.get("d0") or {}
        if chain_ok:
            if row.get("survivors"):
                return "three_day_survivors"
            if row.get("promoted"):
                return "promoted"
        if d0.get("count"):
            return "d0_count" if chain_ok else "chain_na"
        return None

    ranked = sorted(rows, key=_rank_key)
    # 主线优先选真题材，泛板块只在真题材全无证据时傅底（均显式披露）
    real_rows = [r for r in ranked if r["name"] not in _PSEUDO_BOARDS]
    main_row: dict[str, Any] | None = None
    basis: str | None = None
    for cand in [*real_rows, *ranked]:
        b = _basis_of(cand)
        if b:
            main_row, basis = cand, b
            break
    pseudo_top: str | None = None
    if main_row and main_row["name"] not in _PSEUDO_BOARDS and ranked:
        if ranked[0]["name"] in _PSEUDO_BOARDS and ranked[0]["name"] != main_row["name"]:
            pseudo_top = ranked[0]["name"]
    display_names = [r["name"] for r in ranked[:5]]
    if main_row and main_row["name"] not in display_names:
        display_names = [main_row["name"]] + display_names[:4]
    st = _sector_top3_streaks(db, date, display_names)
    for r in rows:
        r["top3Streak"] = st.get(r["name"], 0)
    if main_row:
        out["mainline"] = {
            "name": main_row["name"],
            "basis": basis,
            "survivors": main_row.get("survivors"),
            "holdings": main_row.get("survivorNames") or [],
            "d0Count": (main_row.get("d0") or {}).get("count") or 0,
            "d0MaxBoard": (main_row.get("d0") or {}).get("maxBoard"),
            "d0MaxBoardText": (main_row.get("d0") or {}).get("maxBoardText"),
            "top3Streak": main_row.get("top3Streak") or 0,
            "dragon": main_row.get("dragon"),
            # v7 D5 评审修复：同桶基线桶键（封板二分 + 真连板序，与 SUSTAIN 表构建口径
            # 一致）。dragon/d0Count 是区间 M 序/触板池口径——炸板股会算进「板块家数」、
            # M 序龙一的 streak/time 不必然是真连板龙一的，直接入桶 = 同桶不同桶。
            # 龙序单源 rank_board_stocks（theme_leader_baseline 同款，禁第二套）。
            "sustain": _mainline_sustain(db, date, main_row["name"], pool, boards[date],
                                         streaks, dataset_id),
            "pseudoExcluded": pseudo_top,
            "chainOk": chain_ok,
        }
        order = {n: i for i, n in enumerate(display_names)}
        out["sectors"] = sorted([r for r in ranked if r["name"] in display_names],
                                key=lambda r: order.get(r["name"], 99))
    else:
        out["sectors"] = ranked[:5]
        out["degraded"].append("主线板块不可算")

    # ── 龙头结构（总/情绪/板块龙一）
    total_code, total_entry = sorted(pool.items(), key=lambda kv: (
        -_day_eff(kv[1]), str(kv[1].get("time") or "99:99")))[0]
    total_streak = streaks.get(total_code)
    label_doc = db["hotlist_jev_driver_labels"].find_one({"_id": f"{date}:{total_code}"}) or {}
    out["totalLeader"] = {
        "code": total_code, "name": total_entry.get("name") or total_code,
        "boards": total_entry.get("boards"), "days": total_entry.get("days"),
        "rangeText": _range_num_txt(total_entry),
        "streak": total_streak if isinstance(total_streak, int) else None,
        "sector": total_entry.get("board"),
        "time": (total_entry.get("time") or None),
        "pull": sum(1 for e in pool.values() if e.get("board") == total_entry.get("board")),
        "rank": hotlist_ranks(db, date, [total_code], dataset_id).get(total_code),
        "label": label_doc.get("label"), "freshness": label_doc.get("freshness"),
    }
    cand = [(c, e) for c, e in pool.items() if isinstance(streaks.get(c), int)]
    if cand:
        sent_code, sent_entry = sorted(cand, key=lambda kv: (
            -streaks[kv[0]], -_day_eff(kv[1]), str(kv[1].get("time") or "99:99")))[0]
        out["sentimentLeader"] = {
            "code": sent_code, "name": sent_entry.get("name") or sent_code,
            "boards": sent_entry.get("boards"), "days": sent_entry.get("days"),
            "rangeText": _range_num_txt(sent_entry),
            "streak": streaks[sent_code], "sector": sent_entry.get("board"),
            "time": (sent_entry.get("time") or None),
        }
        out["sameStock"] = sent_code == total_code
    else:
        out["degraded"].append("情绪龙头不可算")

    if main_row:
        dragons = dragon_rows(boards[date].get(main_row["name"]) or [],
                              streaks=streaks, top=3)
        out["mainlineDragon"] = dragons[0] if dragons else None
        out["leaderIsMainlineDragon"] = bool(dragons) and dragons[0].get("code") == total_code

    out["genesis"] = _leader_genesis(
        db, date, total_code, total_entry,
        total_streak if isinstance(total_streak, int) else None)

    prev_dates = trading_dates_before(db, date, 1, dataset_id=dataset_id)
    if prev_dates:
        prev_date = prev_dates[-1]
        prev_pool = pools.get(prev_date) or _pool_of(db, prev_date)
        succ: dict[str, Any] = {"prevDate": prev_date, "prevLeader": None,
                                "changed": False, "prevStatus": None}
        if prev_pool:
            prev_code, prev_entry = sorted(prev_pool.items(), key=lambda kv: (
                -_day_eff(kv[1]), str(kv[1].get("time") or "99:99")))[0]
            succ["prevLeader"] = {
                "code": prev_code, "name": prev_entry.get("name") or prev_code,
                "rangeText": _range_num_txt(prev_entry),
                "sector": prev_entry.get("board"),
            }
            succ["changed"] = prev_code != total_code
            if succ["changed"]:
                status, _ = _status_map(db, date, pool, {prev_code}, dataset_id)
                succ["prevStatus"] = status.get(prev_code)
        else:
            succ["degraded"] = f"{prev_date} 韭研 final 缺失"
        out["succession"] = succ
    else:
        out["degraded"].append("龙头更替不可算")
    return out


def sector_relay_lines(struct: dict[str, Any]) -> list[str]:
    """段 A：板块接力链（三日）（消费 relay_structure，不重复计算；v10 主线结论行/同桶基线撤出）。"""
    dates = struct.get("dates") or {}
    sectors = struct.get("sectors") or []
    if not sectors:
        reason = "；".join(struct.get("degraded") or []) or "韭研 final 缺失"
        return ["板块接力链（三日）：不可算"]
    main = struct.get("mainline") or {}
    chain = struct.get("chain") or {}
    chain_ok = bool(chain.get("ok"))
    chain_reason = chain.get("reason") or "链日数据缺失"
    lines = ["板块接力链（三日 D-2→D0）："]
    for s in sectors:
        cols = []
        for key in ("d2", "d1"):
            d = dates.get(key)
            if not d:
                cols.append("历史不足")
                continue
            stat = s.get(key)
            if stat is None:
                cols.append(f"{d[5:]} 缺失")
            elif not stat.get("count"):
                cols.append(f"{d[5:]} 0只（未上榜）")
            else:
                cols.append(f"{d[5:]} {stat.get('count')}只/最高"
                            f"{stat.get('maxBoardText') or '?'}")
        d0 = s.get("d0") or {}
        cols.append(f"{dates.get('d0', '')[5:]} {d0.get('count') or 0}只"
                    + (f"/最高{d0.get('maxBoardText')}" if d0.get("count") else "（未上榜）"))
        surv = s.get("survivors")
        if not chain_ok:
            surv_txt = f"三日存活 不可算（{chain_reason}）"
        else:
            surv_txt = f"三日存活 {surv or 0} 只" + (
                f"（{'、'.join(s.get('survivorNames') or [])}）" if surv else "")
        prom_txt = (f"今日晋级 不可算（{chain_reason}）" if not chain_ok
                    else f"今日晋级 {s.get('promoted') or 0} 只")
        dragon = s.get("dragon") or {}
        drg_txt = (f"龙一 {dragon.get('name') or dragon.get('code')}"
                   f"({d0.get('maxBoardText') or '首板'}"
                   f"·连板{_streak_txt(dragon.get('streak'))})" if dragon else "龙一 不可算")
        if main.get("name") == s.get("name"):
            tag = "（主线·泛板块）" if s.get("name") in _PSEUDO_BOARDS else "（主线）"
        else:
            tag = "（泛板块）" if s.get("name") in _PSEUDO_BOARDS else ""
        # 「连续top3 0日」不渲染：0 不携带信息（今日不在家数 top3 的板块本就不该占位），
        # 今日 top3 及其连续天数已由「题材演化」段给出，此处只作补充证据。
        streak_txt = (f"｜连续top3 {s.get('top3Streak')}日"
                      if s.get("top3Streak") else "")
        lines.append(f"· {s.get('name')}{tag}：{' → '.join(cols)}｜{surv_txt}"
                     f"｜{prom_txt}{streak_txt}｜{drg_txt}")
    # v10（2026-11-17 B1/C2）：主线板块结论行与同桶隔日连板基线行撤出叙事——
    # 前者被本段主线行+龙头结构升位关系全覆盖；后者为 v9 已删 theme_pulse 的孤儿
    # 证据（8 题判据零引用，题材龙头链自有同桶供给）。结构化事实源不变：
    # relayStructure.mainline（含 sustain 桶键）照常落库供前端/审计；主线不可算
    # 披露走 struct.degraded + 龙头结构升位关系行（fail-visible 不静默）。
    return lines


def leader_structure_lines(struct: dict[str, Any]) -> list[str]:
    """段 B：龙头结构（总/情绪/板块龙头 + 一致性 + 升位关系 + 诞生轨迹 + 更替）。"""
    total = struct.get("totalLeader")
    if not total:
        reason = "；".join(struct.get("degraded") or []) or "韭研 final 缺失"
        return [f"龙头结构：不可算（{reason}）"]
    lines = ["龙头结构："]
    # v10 C1：标签并入总龙头行（原龙头档案头行与本行逐字重复，头行已删）
    label_txt = (f"·标签 {total.get('label')}/{total.get('freshness')}"
                 if total.get("label") else "")
    lines.append(
        f"· 总龙头 {total.get('name')}({total.get('code')}) {total.get('rangeText')}"
        f"·真连板{_streak_txt(total.get('streak'))}·{total.get('sector') or '?'}板块"
        f"·封板{total.get('time') or '?'}·板内带动{total.get('pull') or 0}只"
        f"·热榜{('第' + str(total.get('rank')) + '名') if total.get('rank') else '未上榜'}"
        f"{label_txt}")
    sent = struct.get("sentimentLeader")
    if sent:
        lines.append(
            f"· 情绪龙头 {sent.get('name')}({sent.get('code')}) 真连板{sent.get('streak')}"
            f"·{sent.get('rangeText')}·{sent.get('sector') or '?'}板块"
            f"·封板{sent.get('time') or '?'}")
        if struct.get("sameStock"):
            lines.append("· 一致性：总龙头与情绪龙头为同一只")
        else:
            lines.append("· 一致性：总龙头与情绪龙头不同")
    else:
        lines.append("· 情绪龙头 不可算")
        lines.append("· 一致性：不可判")
    main = struct.get("mainline") or {}
    if main:
        if struct.get("leaderIsMainlineDragon"):
            lines.append(f"· 升位关系：总龙头是主线板块「{main.get('name')}」的龙一"
                         f" → 由主线板块龙头升位")
        else:
            dragon = main.get("dragon") or {}
            lines.append(f"· 升位关系：总龙头不是主线板块「{main.get('name')}」的龙一"
                         f"（该板块龙一为 {dragon.get('name') or '不可算'}）→ 龙头与主线分离")
    else:
        lines.append("· 升位关系：主线板块不可算，升位关系不可判")
    genesis = struct.get("genesis") or {}
    if genesis.get("firstBoardDate"):
        breaks = ("断板次数不可算" if genesis.get("breaks") is None
                  else f"区间内断板 {genesis.get('breaks')} 次")
        ago = genesis.get("tradingDaysAgo")
        ago_txt = "当日" if ago == 0 else f"{ago} 个交易日前"
        lines.append(
            f"· 诞生轨迹：首板 {genesis['firstBoardDate'][5:]}"
            f"（{ago_txt}）→ 区间 {total.get('rangeText')}"
            f"（{breaks}）→ 当前真连板{_streak_txt(genesis.get('streak'))}")
        if genesis.get("degraded"):
            lines.append(f"  （{genesis['degraded']}）")
    else:
        lines.append("· 诞生轨迹：不可算")
    succ = struct.get("succession") or {}
    prev_leader = succ.get("prevLeader")
    if prev_leader:
        if succ.get("changed"):
            if succ.get("prevStatus") == "sealed":
                why = "旧龙头今日仍封板、龙头位次被超越"
            else:
                why = f"旧龙头今日{_STATUS_CN.get(succ.get('prevStatus') or '', '不可验')}"
            lines.append(f"· 更替：{succ.get('prevDate', '')[5:]} 总龙头 {prev_leader.get('name')}"
                         f" → 今日换龙头（{why}）")
        else:
            lines.append(f"· 更替：{succ.get('prevDate', '')[5:]} 总龙头 {prev_leader.get('name')}"
                         f" → 今日延续")
    else:
        lines.append("· 更替：不可算")
    return lines


# ── 段 5：近 10 日连板轨迹 ──────────────────────────────────────────────────


def relay_trajectory_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                          n: int = 10) -> str:
    """家数/最高板/晋级率逐日（v10 删摆动锚：峰/谷可从本表读出，判据零引用）。

    v7 D6：段名对齐判据引用名【近10日连板轨迹】——「近 n 日」= 今日+近 n-1 日
    （与高位股多日轨迹段「近10个交易日」同规；旧实现 10 前+今日=11 行、段名写
    「近11日」与题干字面检索对不上）。
    """
    hist = trading_dates_before(db, date, n - 1, dataset_id=dataset_id)
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
    # v10 D1：摆动锚撤出（峰/谷/距峰值可从轨迹表读出，8 题判据零引用）
    return (f"近{len(rows)}日连板轨迹（含今日；日期|涨停|最高板|晋级率）："
            f"{' ； '.join(rows)}")


# ── 段 5.5：今日炸板面（2026-10-11 预登记 StepB）─────────────────────────────


def _sealed_codes(db: Any, date: str, touch: set[str], dataset_id: str) -> tuple[set[str], bool]:
    """触板 − THS 15:00 炸板池 + 尾盘回封补证 = 收盘涨停池（与 jiuyan_board_info 同口径）。

    2026-10-10 review C2 口径修正：韭研 final fields.stocks 是触板名单（封板+炸板），
    直接当「涨停/晋级」会把昨日封板今日炸板股计成晋级、低估断板亏钱面。
    返回 (codes, ths_found)：ths_found=False = 池缺失/降级，回退触板口径，
    调用方必须在叙述中注记降级（不得静默混用两种口径）。
    2026-10-16：本体委托 jev_label_jiuyan 同名单源（原双实现，消漂移）。
    2026-11-12 真正落实委托：旧实现仍就地 touch-failed、漏尾盘回封补证，与 label 侧
    漂移（闽发铝业 002578 11-09 15:00 回封被错杀同款，relay 晋级/断板同样误判）。改委托
    label `_sealed_codes`（含同一 `_reseal_verdict` 回封补证单源）；label None（final/THS
    池缺失）→ 回退触板口径 + found=False。touch 参数仅作降级回退集（正常路径 label 同源重算）。
    """
    sealed = _label_sealed_codes(db, date, dataset_id)
    if sealed is None:
        return set(touch), False
    return sealed, True


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
    return ""   # 2026-10-30g+：口径对账注整行删（用户裁决，叙事只留行情数字）


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


def _zhaban_face_count_fallback(db: Any, date: str, dataset_id: str) -> str:
    """旧采集 schema（仅家数）日的炸板面降级行（F1，2026-10-17 预注册 §2.1）。

    2026-07-30..09-23 共 16 天的 15:00 帧只有 `poolCounts`（failed/rushing/drawdown 家数）
    + `maxDrawdown/avgDrawdown`，没有 `pools.*.items`（个股）。旧实现整段写「不可算」把同帧
    已有家数一并丢弃（AGENTS §4.0）。本函数只输出**同源可算部分**，个股级子项与分位
    均标不可算（分位历史序列含旧 schema 日，混算属口径混用）。

    对比口径（预注册 D1）：新旧 schema 的炸板**家数**同义（`poolCounts.failed` ≙
    `len(pools.failed.items)`），允许家数级对比但必须带标注；个股级子项绝不跨 schema 编造。
    禁用 `snapshot_records.payload.limitSummary.zhaban.count`（前端口径）冒充 THS failed。

    v11 O3 只删主行冲刺尾段（与盘面事实行重复）；旧 schema 日盘面事实行不渲染冲刺段
    （rushingCount 需 ths_ok 且 rush_pool.ok，旧帧无 items → None），本行是冲刺家数唯一
    披露点，保留（评审 P2-2，AGENTS §4.0 不得静默丢同帧已有数据）。
    """
    counts, found = _ths_pool_counts(db, date, dataset_id)
    if not found or not isinstance(counts, dict):
        return "今日炸板面：不可算"
    n = counts.get("failed")
    r = counts.get("rushing")
    d = counts.get("drawdown")
    mx, av = counts.get("maxDrawdown"), counts.get("avgDrawdown")
    zb_txt = f"炸板 {n} 家" if isinstance(n, (int, float)) else "炸板家数不可算"
    # 冲刺段保留：旧 schema 日唯一披露点（评审 P2-2，见 docstring）
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
    return (f"今日炸板面：{zb_txt}；{rush_txt}；{dd_txt}；较昨日：{cmp_txt}；"
            f"反复开板/昨日池股炸板/炸板股大面/代表股/归因打标 不可算；分位 不可算")


def zhaban_face_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """今日炸板面：THS 15:00 炸板池结构化证据（家数分位/反复开板/昨日池股炸板/大面/代表股/
    较昨日增减——2026-10-15 诊断补供 relay_momentum 主锚的昨日可比数）。

    预登记：docs/hotlist-jev/jev-relay-zhaban-preregistration.md（StepB，用户 2026-10-11 裁决）。
    炸板 0 家是合法强信号（正常呈现）；帧缺失/降级才写「不可算」。

    v11（2026-11-17 匹配度审计，用户裁决全部修复）：主行冲刺未封尾段删（与盘面事实行
    逐字重复，O3；F1 降级行保留——旧 schema 日盘面事实行不渲染冲刺段，该处是唯一
    披露点，评审 P2-2）；烂板段删（判据零消费孤儿，sealQuality 结构化仍在帧，O4）；
    炸板股收盘涨幅中位删（判据零消费，保留大面——instructions 显式消费，O4）；
    较昨日行补高位分歧家数+占炸板比对照（divergence「高位分歧炸占比较昨日升高」
    原无昨日归因可比数，M2+评审 P2-1，单源同集合昨日档）。
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
    pct_txt = "（样本不足）"
    if len(hist) >= 5:
        pct = round(sum(1 for x in hist if x[0] < n) / len(hist) * 100)
        pct_txt = f"（近{len(hist)}日分位 P{pct}，均值 {_median([x[0] for x in hist]) or 0:.0f} 家）"
    # 反复开板
    hi = [i for i in by_code.values() if isinstance(i.get("open_num"), (int, float)) and i.get("open_num") >= 2]
    hi_pct_txt = "（样本不足）"
    if len(hist) >= 5:
        hpct = round(sum(1 for x in hist if x[1] < len(hi)) / len(hist) * 100)
        hi_pct_txt = f"（近{len(hist)}日分位 P{hpct}）"
    hi_txt = f"反复开板(≥2次) {len(hi)} 家（占 {round(len(hi) / n * 100) if n else 0}%）{hi_pct_txt}"
    # 昨日池分层：昨日池股今日炸 = 连板断层前导
    prev_dates = trading_dates_before(db, date, 1)
    layer_txt = "昨日池股炸板：不可算"
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
    # 炸板股大面（v11 O4：收盘涨幅中位判据零消费删；大面保留——instructions 显式消费「炸板股大面」）
    rates = [i.get("change_rate") for i in by_code.values()
             if isinstance(i.get("change_rate"), (int, float))]
    if rates:
        big = sum(1 for r in rates if r <= -5)
        rate_txt = f"炸板股大面(≤-5%) {big} 家"
    else:
        rate_txt = "炸板股大面不可算"
    # 代表股（开板次数降序前 3）
    reps = sorted(by_code.values(), key=lambda i: (i.get("open_num") or 0), reverse=True)[:3]
    rep_txt = "、".join(
        f"{i.get('name')}({i.get('open_num')}次,{i.get('change_rate'):+.1f}%)"
        if isinstance(i.get("change_rate"), (int, float)) else f"{i.get('name')}({i.get('open_num')}次)"
        for i in reps if i.get("name"))
    # 炸板归因打标分布（StepA：hotlist_jev_zhaban_labels 当日聚合；覆盖不足如实注记）
    labeled = list(db["hotlist_jev_zhaban_labels"].find(
        {"tradingDate": date, "status": "ok"}, {"zhabanCause": 1, "name": 1}))
    hd_n = 0
    if labeled:
        from collections import Counter
        dist = Counter(l.get("zhabanCause") or "unknown" for l in labeled)
        hd = [l for l in labeled if l.get("zhabanCause") == "high_divergence"]
        hd_n = len(hd)
        # v10 C3：开板次数单源=反复开板代表行，归因分布只留股名不重复次数
        hd_names = "、".join(str(l.get("name")) for l in hd[:3] if l.get("name"))
        dist_txt = (f"炸板归因打标（覆盖 {len(labeled)}/{n}）：高位分歧 {dist.get('high_divergence', 0)} 家"
                    + (f"（{hd_names}）" if hd_names else "")
                    + f"、板块退潮 {dist.get('sector_collapse', 0)} 家、追高被砸 {dist.get('chase_fail', 0)} 家、"
                    f"大盘拖累 {dist.get('broad_market', 0)} 家")
    else:
        dist_txt = f"炸板归因打标：未覆盖（0/{n}）"
    # 较昨日增减（relay_momentum 主锚之二，2026-10-15 诊断补供）：criteria 判「炸板面收敛/
    # 恶化（炸板与反复开板较昨日减少/增多）」需昨日可比数，而分位/均值只给绝对位置——
    # 全库叙事此前从未组装昨日炸板家数，模型无从判方向，是 insufficient_evidence 逃生的
    # 结构性口子（10-15 P0/09-21 P62 两日均缺此锚）。昨日帧数据现成（分位回溯同源）。
    # v11 M2：补高位分歧家数对照——divergence「高位分歧炸占比较昨日升高」原无昨日归因
    # 可比数；单源同集合昨日档（hotlist_jev_zhaban_labels），零重算。今日未覆盖时不出
    # 数值对照（防伪 0：3→0 会被读成真实零分歧）。
    if not prev_dates:
        cmp_txt = "较昨日：不可算"
    else:
        prev_items, prev_found = _ths_failed_items(db, prev_dates[-1], dataset_id)
        prev_items = list(prev_items.values())
        if not prev_found:
            # F1 兼容：昨日是旧 schema 日（只有家数）→ 家数级对比（同源同义字段，带标注；预注册 D1）
            prev_counts, prev_cfound = _ths_pool_counts(db, prev_dates[-1], dataset_id)
            prev_n2 = (prev_counts or {}).get("failed") if prev_cfound else None
            cmp_txt = (f"较昨日：炸板 {prev_n2}→{n} 家（{n - prev_n2:+d}）· 反复开板 不可算"
                       " · 高位分歧较昨日不可算"
                       if isinstance(prev_n2, int) and isinstance(n, int) else
                       "较昨日：不可算")
        else:
            prev_by = {str(i.get("code") or "")[-6:]: i for i in prev_items if i.get("code")}
            p_n = len(prev_by)
            p_hi = sum(1 for i in prev_by.values()
                       if isinstance(i.get("open_num"), (int, float)) and i.get("open_num") >= 2)
            p_labeled = list(db["hotlist_jev_zhaban_labels"].find(
                {"tradingDate": prev_dates[-1], "status": "ok"}, {"zhabanCause": 1}))
            if p_labeled and labeled:
                p_hd = sum(1 for l in p_labeled if l.get("zhabanCause") == "high_divergence")
                hd_cmp = f"· 高位分歧 {p_hd}→{hd_n} 家"
                # 评审 P2-1：判据消费占比方向，只给家数在分母变动时会读反——占比直给
                # （同帧分母 p_n/n，零新原料，与 M4「勿心算」同款）
                if p_n > 0 and n > 0:
                    hd_cmp += f"（占炸板 {round(p_hd / p_n * 100)}%→{round(hd_n / n * 100)}%）"
            else:
                hd_cmp = "· 高位分歧较昨日不可算"
            cmp_txt = (f"较昨日：炸板 {p_n}→{n} 家（{n - p_n:+d}）· "
                       f"反复开板 {p_hi}→{len(hi)} 家（{len(hi) - p_hi:+d}）{hd_cmp}")
    return (f"今日炸板面：炸板 {n} 家{pct_txt}；{hi_txt}；{layer_txt}；{rate_txt}；"
            f"反复开板代表：{rep_txt or '无'}；{dist_txt}；{cmp_txt}")


# ── 段 0a-2：反包修复行（2026-10-21 立项，jev-rewrap-factor-preregistration.md R1）───

def weak_to_strong_line(db: Any, date: str, slot: str = "15:00",
                        dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """弱转强形态参照行（2026-10-21 立项，用户裁决 A 路线：语料增补、题目集零改动）。

    规则/基线单源 = `analysis/hotlist/weak_to_strong`（与 jev-weak-to-strong-day-study.md 同链）。
    设计纪律：形态判定不用当日 relayIndex（循环依赖），只用「昨日 idx≤40 + 今日结构确认」；
    昨日非弱势区不贴标（防标签通胀）。
    v10（2026-11-17 D2/A1/A6）：静态历史基线（反包率均值/T-1 跌停中位/T+1 延续率及
    「一日游」解读句）与今日反包率 vs 基线对比撤出叙事——反包率+20日分位已在反包
    修复行，wzs 分类器是确定性代码不读叙事；首判「待落库」流程注删，只留结构预检。
    保留昨日 relayIndex 分区 + 结构预检/确认行（relay_momentum.reversing 证据）。
    午盘档：跌停家数由盘后链写入，午盘只做涨停侧确认并显式注记（不伪判），形态盘后定档。
    """
    from backend.analysis.hotlist.weak_to_strong import (
        classify_day, zt_series, limit_down_series,
        relay_idx_series, STRONG_IDX_MIN, WEAK_IDX_MAX)
    cls = classify_day(db, date, dataset_id)
    dt = limit_down_series(db)
    zt = zt_series(db, dataset_id)
    parts: list[str] = []
    prev_date = _prev_relay_date(db, date)
    # 首判路径（审查 MF-1）：当日 doc 未落库时 classify_day 走 no_relay_doc fallback，
    # prevIdx 需从昨日序列现算（与 settle_day 同源），否则每个新交易日的首算必然误报「昨日缺失」
    if cls.get("prevIdx") is None and prev_date is not None:
        _p = relay_idx_series(db).get(prev_date)
        if _p is not None:
            cls = dict(cls, prevIdx=_p)
    first_run = db[COLLECTION].find_one({"_id": f"{date}:RELAY"}) is None
    if cls.get("prevIdx") is None or prev_date is None:
        parts.append("昨日 relayIndex 缺失，形态不可判")
    else:
        prev_i = cls["prevIdx"]
        zone_txt = "弱势区" if prev_i <= WEAK_IDX_MAX else (
            "中强区" if prev_i >= STRONG_IDX_MIN else "中性区")
        from backend.analysis.hotlist.market_facts import frame_market_facts
        conf: list[str] = []
        p_dt, c_dt = dt.get(prev_date), dt.get(date)
        p_zt = zt.get(prev_date)
        c_zt = (frame_market_facts(db, date, slot, dataset_id) or {}).get("ztCount") \
            if slot != "15:00" else zt.get(date)
        if c_dt is not None and p_dt is not None:
            conf.append(f"跌停 {p_dt}→{c_dt}" + ("↓" if c_dt < p_dt else ""))
        elif slot != "15:00":
            conf.append("跌停盘后写入（午盘不可判）")
        if c_zt is not None and p_zt is not None:
            conf.append(f"涨停 {p_zt}→{int(c_zt)}" + ("↑" if c_zt > p_zt else ""))
        parts.append(f"昨日 relayIndex {prev_i}（{zone_txt}）")
        weak_zone = prev_i <= WEAK_IDX_MAX
        if slot != "15:00":
            # 午盘档：形态不落地，只给预检参照（分类器确认基于收盘序列，不伪判）
            parts.append(f"午盘预检：{'、'.join(conf) if conf else '无确认项'}（形态盘后定档）")
        elif first_run:
            # 首判（审查 MF-1）：今日评分未落库，形态不可判，只给结构预检；不冒充未命中
            # v10 A1：「待落库」流程注删（AGENTS §1.2-8），只留结构预检事实
            parts.append(f"结构预检：{'、'.join(conf) if conf else '原料缺失'}")
        elif weak_zone:
            if cls.get("hit"):
                parts.append(f"结构确认命中：{'、'.join(conf) if conf else '无'} → 符合历史弱转强形态")
            elif cls.get("reason") in ("idx_below_strong", "delta_below_threshold"):
                # 未达标的是指数侧（idx/Δ），结构侧状态单独表述（2026-10-22 措辞修复：
                # 10-20 重跑后 idx 47.8<50 但 dt↓+zt↑ 均确认，旧文案误写「结构确认未命中」自相矛盾）
                parts.append(f"指数未达强势区（{cls.get('idx')}）"
                             + (f" · 结构确认已满足：{'、'.join(conf)}" if conf else " · 结构确认未满足")
                             + "，不贴形态标")
            else:
                parts.append(f"结构确认未命中（{'、'.join(conf)}），不贴形态标" if conf
                         else "结构确认未命中，不贴形态标")
        else:
            parts.append(f"今日结构：{'、'.join(conf)}，昨日非弱势区，不贴形态标"
                         if conf else "今日结构：无确认项，不贴形态标")
    # 定格 vs 重评分歧注记（fail-visible，不静默）：重跑改了评分但节点已定格
    if slot == "15:00" and cls.get("idx") is not None:
        _d = (db[COLLECTION].find_one({"_id": f"{date}:RELAY"}) or {}).get("relayIndex")
        if isinstance(_d, (int, float)) and not isinstance(_d, bool) \
                and abs(float(_d) - float(cls["idx"])) > 1e-9:
            parts.append(f"重跑重评 {round(float(_d), 1)}，以收盘定档 {cls['idx']} 为准")
    # v10 D2：静态历史基线与今日反包率 vs 基线对比已撤出（见 docstring）；
    # 基线单源仍在 weak_to_strong_baseline（wzs 读口/研究链消费，不随叙事删）。
    return "弱转强参照：" + " · ".join(parts)


def _prev_relay_date(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str | None:
    """relayIndex 序列里严格早于 date 的最近一日（分类器同源轴）。"""
    from backend.analysis.hotlist.weak_to_strong import relay_idx_series
    prevs = [d for d in sorted(relay_idx_series(db)) if d < date]
    return prevs[-1] if prevs else None


def rewrap_face_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """反包修复行：昨日断板候选池 × 今日回封（断板反包）+ 昨日炸板池今日回封。

    判据对接（预注册 §5）：`relay_momentum.reversing`「昨日弱今日明确修复」与
    `relay_phase.launch/divergence` 的「断板亏钱可控/恶化」首次有了直接计数锚。
    口径纪律：跨日比较一律用**率**（裸计数与当日涨停家数 corr=0.684 共线，预注册 §4）；
    候选池未分辨停牌复牌（与断板同形）→ v10 移结构化 poolCaveat（池快照落库），不进叙事；
    池空/昨日炸板池缺失 → 对应段 fail-visible，不补 0。
    计算单源 = `analysis/hotlist/rewrap_pool.build_rewrap_pool`（池快照集合仅审计存档）。
    """
    from backend.analysis.hotlist.rewrap_pool import (
        build_rewrap_pool, rewrap_rate_series, percentile_of)
    pool = build_rewrap_pool(db, date, "final", dataset_id)
    miss = pool.get("missing") or {}
    if miss.get("axis_short") or miss.get("today_list_empty"):
        return "反包修复：不可算"
    if miss.get("prev_final_missing"):
        return "反包修复：不可算"
    # 近 20 日分位：优先读池快照已算好的 ratePct20d（relay 链在打标步之后，快照已落库），
    # 缺失再现算序列（审查 nit13：避免每次叙事构建 20 日 × 全池重算）
    rate_pct = None
    try:
        from backend.operations.rewrap_pool import get_rewrap_pool
        rate_pct = (get_rewrap_pool(db, date, "final") or {}).get("ratePct20d")
    except Exception:
        rate_pct = None
    if rate_pct is None:
        rate_pct = percentile_of([r for _, r in rewrap_rate_series(db, date, 20, dataset_id)],
                                 pool.get("rewrapRate"))
    head = (f"反包修复：昨日断板候选 {pool['candidateN']} 只 · 今日反包 {pool['rewrapN']} 只"
            f"（反包率 {_pct_txt(pool.get('rewrapRate'))}"
            + (f"，近20日 {rate_pct} 分位" if rate_pct is not None else "，近20日分位不可算") + "）")
    if pool.get("prevFailedFound"):
        head += f" · 昨日炸板回封 {pool['resealN']}/{pool['prevFailedN']}（{_pct_txt(pool.get('resealRate'))}）"
    else:
        head += " · 昨日炸板池缺失，回封率不可算"
    # v10 D3/A4：代表股删（判据消费率/计数不消费股名，明细在池快照 stocks 字段）；
    # 停牌复牌口径注移结构化 poolCaveat（build_rewrap_pool 输出，随快照落库）。
    return head


def _pct_txt(rate: float | None) -> str:
    return f"{rate * 100:.1f}%" if isinstance(rate, (int, float)) and not isinstance(rate, bool) else "不可算"


# ── 段 0b：大盘指数行（v7 D2）───────────────────────────────────────────────

# 顶层 4 指数（frame.indices 浏览器原键位）+ indexExtra 三指数（v7 D2a 采集层新增）
_INDEX_MAIN_DISPLAY = (("sh", "上证"), ("hs300", "沪深300"),
                       ("zz500", "中证500"), ("zz1000", "中证1000"))
_INDEX_EXTRA_DISPLAY = (("szcz", "深证成指"), ("cybz", "创业板指"), ("kc50", "科创50"))


def market_index_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """大盘指数行（7 指数收盘涨跌，15:00 帧客观事实）。

    v7 D2 前的空白支票：zhaban 归因判据写「大盘拖累…叙事若给大盘时段参照」、
    relay_index 写「与大盘热度不必同幅」——relay 叙事从未有过任何指数行，两处判据
    引用自上线起悬空。本行补位（① broad_market 归因语料供给；② 接力 vs 大盘的
    对照锚；③ 深成/创业板指对深市与 20cm 情绪敏感股的板块偏向坐标）。
    changePct 优先；缺失降级点位口径并显式标注（不拿点位冒充百分比）。
    历史帧无 indexExtra（2026-10-20 前采集）→ 4 指数 + 「该日未采集」注（fail-visible）。
    """
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"indices": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    idx = (f or {}).get("indices")
    if not isinstance(idx, dict) or not idx:
        return "大盘指数：不可算"
    extra = idx.get("indexExtra")
    extra = extra if isinstance(extra, dict) else {}

    def _one(name: str, entry: Any) -> str:
        if not isinstance(entry, dict):
            return f"{name} 缺失"
        pct = entry.get("changePct")
        if isinstance(pct, (int, float)) and not isinstance(pct, bool):
            # 历史回填口径标注（backfill_frame_indices）：回填值非 15:00 实采，不伪装成帧值
            tag = ""   # 2026-10-30g+：来源注删
            return f"{name} {pct:+.2f}%{tag}"
        ch = entry.get("change")
        if isinstance(ch, (int, float)) and not isinstance(ch, bool):
            return f"{name} {ch:+.2f}点"
        return f"{name} 缺失"

    parts = ([_one(name, idx.get(key)) for key, name in _INDEX_MAIN_DISPLAY]
             + [_one(name, extra.get(key)) for key, name in _INDEX_EXTRA_DISPLAY])
    note = "" if extra else "（该日未采集）"
    return f"大盘指数：{' · '.join(parts)}{note}"


# ── 段 6：近20日参照锚（v7 D1 瘦身 + D4 分位刻度）──────────────────────────


def _quantile(vals: list, q: float):
    """近邻秩分位数（P20/P50/P80 刻度用）——percentile_fraction 的逆形状（值→秩）。
    样本 <10 返 None（与 percentile_fraction 同门槛，fail-visible 不伪刻度）。"""
    vs = sorted(v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool))
    if len(vs) < 10:
        return None
    return vs[min(len(vs) - 1, int(round(q * (len(vs) - 1))))]


def _percentile_scale_line(money_hist: list[dict[str, Any]]) -> str:
    """D4：锚段分位刻度行——晋级率/炸板家数/断板中位/隔日溢价的 P20/P50/P80。

    样本=严格早于当日的近 20 个交易日（与今日炸板面分位同窗规，零未来函数）；
    各轴独立披露有效样本数（TDX 覆盖不足日不入样本，不补 0）。
    """
    if not money_hist:
        return "近20日分位刻度：不可算"
    total = len(money_hist)
    axes = (("晋级率", "promo", False), ("炸板家数", "zhaban", False),
            ("断板中位", "broken_median", True), ("隔日溢价", "premium_median", True))
    parts = []
    for label, key, signed in axes:
        vals = [r.get(key) for r in money_hist]
        valid = [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
        q20, q50, q80 = (_quantile(vals, q) for q in (0.2, 0.5, 0.8))
        if q20 is None:
            parts.append(f"{label} 不可算（有效 {len(valid)}/{total} 日）")
            continue
        fmt = (lambda v: f"{v:+.1f}%") if signed else (lambda v: f"{round(v)}")
        parts.append(f"{label} P20/P50/P80={fmt(q20)}/{fmt(q50)}/{fmt(q80)}"
                     f"（有效 {len(valid)}/{total} 日）")
    return ("近20日分位刻度：" + " · ".join(parts))


def anchor_lines(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                 money_hist: list[dict[str, Any]] | None = None) -> list[str]:
    """近20日参照锚（客观事实，打分坐标系）。

    v7 D1：删「今日热榜叙事轨迹」「近5日 EOD 叙事」两行——全叙事 13 段中唯一的
    「另一模型结论」混入点（七题判据零引用，grep 实证；热榜 ferment t5.6 与接力
    客观证据反向时即误判温床）。防锚定提示随之简化：本段已全是客观事实。
    保留近20日极值锚（relay_index/phase/ladder 三题显式引用的坐标系）。
    v7 D4：补分位刻度行（`money_hist` 由叙事组装一次算齐传入，缺省自算）。
    """
    lines = ["【近20日参照锚】"]
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
            board_anchor = "；最高板峰值 不可算"
        lines.append(f"近20日锚：涨停峰值 {z_peak[1]} 家（{z_peak[0][5:]}）/谷值 {z_low[1]} 家"
                     f"（{z_low[0][5:]}）{board_anchor}")
    else:
        lines.append("近20日锚：历史数据不足")
    lines.append(_percentile_scale_line(
        money_hist if money_hist is not None else _money_hist_series(db, date, dataset_id)))
    return lines


# ── v8 市场周期融合语料段（2026-11-12，预登记 market-cycle-p3-narrative-preregistration）──
# 单源 hotlist_jev_market_cycle；只放数据事实（态/事件/天花板/两轨龙一命运），供融合题
# （turn_quality/risk_ahead；v10 删 cycle_intensity）消费。缺档整段缺席（fail-visible），
# 题落 insufficient_evidence；状态机是离散态+事件唯一权威，本段不改判、不重算。
_MC_STATE_CN = {"loss": "亏钱效应", "gain": "赚钱效应", "ice": "冰点", "wzs": "弱转强修复"}
_MC_EVENT_CN = {"spaceBreakthrough": "空间突破↑", "spaceCompress": "空间压缩↓",
                "highCollapse": "高位崩塌✗", "highTolerance": "高位宽容✓"}
# v9 相位中文映射（昨日相位软参照行用）
_PHASE_CN = {"launch": "启动", "relay_heat": "接力顺畅", "divergence": "高位分歧",
             "collapse": "退潮崩塌", "bottoming": "冰点出清", "insufficient_evidence": "证据不足"}


def _mc_event_text(e: dict) -> str:
    t = e.get("type")
    label = _MC_EVENT_CN.get(t, t or "未知事件")
    if t == "spaceBreakthrough":
        names = "、".join(s.get("name") or s.get("code") or "?"
                          for s in (e.get("stocks") or []))
        txt = f"{label} {e.get('prevCeiling')}→{e.get('maxBoard')}板"
        return txt + (f"（{names}）" if names else "")
    if t == "spaceCompress":
        return (f"{label} 最高{e.get('maxBoard')}板 "
                f"连续{e.get('lowStreak')}日≤{e.get('maxBoardThreshold')}板")
    name = e.get("name") or e.get("code") or ""
    sub = e.get("subtype")
    tail = f"（{name}{'·' + sub if sub else ''}）" if name else ""
    return label + tail


def market_cycle_lines(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> list[str]:
    """【市场情绪周期】语料段（v8，单源 hotlist_jev_market_cycle）。缺档→[]（整段缺席）。"""
    doc = db["hotlist_jev_market_cycle"].find_one({"_id": f"{date}:MARKET_CYCLE"})
    if not doc:
        return []
    lines = ["【市场情绪周期】"]
    state = doc.get("state")
    head = f"当前态：{_MC_STATE_CN.get(state, state or '未知')} · 已持续 {doc.get('daysInState')} 日"
    tr = doc.get("transition")
    if isinstance(tr, dict) and tr.get("from") and tr.get("to"):
        head += (f" · 今日由 {_MC_STATE_CN.get(tr['from'], tr['from'])} "
                 f"转入 {_MC_STATE_CN.get(tr['to'], tr['to'])}")
    lines.append(head)
    evs = doc.get("events") or []
    lines.append("当日事件：" + ("、".join(_mc_event_text(e) for e in evs) if evs else "无"))
    ceil = doc.get("ceiling") or {}
    mb = ceil.get("maxBoard")
    lines.append(f"空间天花板：最高 {mb if mb is not None else '不可算'} 板 · "
                 f"≥3板 {ceil.get('threePlusN')} 家 · 近20日最高 {ceil.get('prevCeiling20')} 板")
    anchor = doc.get("anchor") or {}
    for seg, seg_cn in (("main", "主板"), ("growth", "创业板")):
        a = anchor.get(seg)
        if not a:
            continue
        sealed = "今日封板" if a.get("leaderSealedToday") else "今日未封板"
        pool_day = a.get("poolDay")
        pool_txt = f"最近封板日 {pool_day} · " if pool_day else ""
        lines.append(f"空间龙一·{seg_cn}：{a.get('name')}({a.get('code')}) 高度{a.get('height')}板 · "
                     f"{pool_txt}{sealed}")
    return lines


def _prev_phase_line(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str | None:
    """v9 昨日相位软参照行（预登记 relay-v9 §五）：读前一 RELAY 档 relayPhase+daysInPhase。

    缺昨日档/缺相位 → None（整行缺席 fail-visible，不伪占位）。供 relay_phase 判读作惯性参照，
    非硬约束（jev 可背离）。daysInPhase 由判后后验计算落库，此处只读昨日已落库值。
    """
    prev = _prev_relay_date(db, date, dataset_id)
    if prev is None:
        return None
    d = db[COLLECTION].find_one({"_id": f"{prev}:RELAY"}) or {}
    ph = d.get("relayPhase")
    if not ph:
        return None
    cn = _PHASE_CN.get(ph, ph)
    dip = d.get("daysInPhase")
    if isinstance(dip, int) and dip >= 1:
        return f"昨日相位：{cn} · 已持续 {dip} 日"
    return f"昨日相位：{cn}"


# ── 组装与 run ──────────────────────────────────────────────────────────────


def build_relay_narrative(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                          struct: dict[str, Any] | None = None) -> str:
    # 日线上下文：本地 vipdoc 末棒落后于 date 时按需线上补尾（2026-10-20：闭市后未跑通达信
    # 盘后下载 → 断板钱效/隔日溢价/位置/板序/板型全不可算，现自动补当日棒）
    with bars_need_upto(date):
        return _build_relay_narrative_inner(db, date, dataset_id, struct)


def _build_relay_narrative_inner(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                                 struct: dict[str, Any] | None = None) -> str:
    # v6：板块/龙头结构先算一次（单一事实源）——叙事渲染与文档落库共用同一 struct，
    # 防「叙事说 A、前端说 B」三处漂移（预注册 §二/§十）。
    struct = struct if struct is not None else relay_structure(db, date, dataset_id)
    # v7 D3/D4：钱效/晋级 20 日历史序列一次算齐（钱效分位行与锚段刻度行共用，防双算）
    money_hist = _money_hist_series(db, date, dataset_id)
    lines: list[str] = [f"{date} 交易日 · 连板情绪指数判定"]
    # 段1 总账（v10 C4：ths_cross=False 去 THS×韭研交叉分布，判据零消费；其他链缺省不变）
    # + 大盘指数（v7 D2）+ 今日炸板面（2026-10-11 StepB）
    lines.append(market_facts_line(db, date, dataset_id, ths_cross=False))
    lines.append(market_index_line(db, date, dataset_id))
    lines.append(zhaban_face_line(db, date, dataset_id))
    # 段 0a-2 反包修复行（2026-10-21 立项 R1）：分歧证据（炸板面）×修复证据（反包）相邻对读
    lines.append(rewrap_face_line(db, date, dataset_id))
    # 段 0a-3 弱转强形态参照行（2026-10-21 立项，用户裁决 A 路线）：修复证据 × 历史基率对读
    lines.append(weak_to_strong_line(db, date, slot="15:00", dataset_id=dataset_id))
    lines.append(relay_flow_line(db, date, dataset_id, money_hist=money_hist))
    lines.append(ladder_structure_line(db, date))
    # 段2 记忆
    lines.append(three_day_chain_line(db, date, dataset_id))
    lines.append(theme_evolution_line(db, date))
    # 段2b' 题材事件（v10 B2：仅事件/日历命中，无命中整块缺席；原 v7 D5 完整证据块撤出）
    lines.extend(theme_evidence_lines(db, date))
    # 段2a' 板块接力链（v6）：三日链板块归属（v10：主线结论行/同桶基线撤出，struct 保留）
    lines.extend(sector_relay_lines(struct))
    # 段2c 高位股多日轨迹（v4，2026-10-16 预注册 §2.3；有帽，非打分依据）
    lines.extend(high_position_trajectory_lines(db, date, dataset_id))
    # 段3 题材梯队（主线板块强制纳入，家数多≠主线）
    lines.extend(theme_ladder_lines(db, date, mainline=(struct.get("mainline") or {}).get("name")))
    # 段4a 龙头结构（v6）：总/情绪/板块龙头 + 一致性 + 升位 + 诞生轨迹 + 更替
    lines.extend(leader_structure_lines(struct))
    # 段4b 龙头档案（v10 C1：头行并入总龙头行；仅位置/板序/板型，选股 struct 单源）
    lines.extend(leader_profile_lines(db, date, dataset_id,
                                     total_leader=struct.get("totalLeader")))
    # 段5 轨迹
    lines.append(relay_trajectory_line(db, date, dataset_id))
    # 段6 近20日参照锚（v7 D1 删热榜叙事两行；D4 扩分位刻度）
    lines.extend(anchor_lines(db, date, dataset_id, money_hist=money_hist))
    # 段7 市场情绪周期（v8 融合）：状态机态/事件/天花板/两轨龙一命运，供 turn_quality/risk_ahead
    lines.extend(market_cycle_lines(db, date, dataset_id))
    # v9 昨日相位软参照行（相位惯性，jev 可背离；缺档整行缺席）
    _pp = _prev_phase_line(db, date, dataset_id)
    if _pp:
        lines.append(_pp)
    return "\n".join(lines)


def _apply_settlement(prev_doc: dict | None, doc: dict, db: Any, dataset_id: str) -> None:
    """节点定格（2026-10-22 §6.3，用户裁决：判定标准必须稳定）：
    已定档日原样随档（重跑只更新叙事/评分，不改写节点）；未定档日以本次落库值首次定档。

    审查 MF-2：degraded/失败判定（status≠ok 或 relayIndex 非数值）不是有效收盘定档，
    不得定格——否则「当日暂无评分」被 first-write-wins 永久锁死；下轮成功后自然定档。"""
    pw = (prev_doc or {}).get("wzs")
    if isinstance(pw, dict) and "state" in pw:
        doc["wzs"] = pw
        return
    if doc.get("status") != "ok":
        return
    from backend.analysis.hotlist.weak_to_strong import settle_day
    entry = settle_day(db, doc["tradingDate"], dataset_id,
                       idx_override=doc.get("relayIndex"))
    if entry is not None:
        doc["wzs"] = entry


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
        struct = relay_structure(db, date, dataset_id)
        narrative = build_relay_narrative(db, date, dataset_id, struct=struct)
        if dry_run:
            print(f"[dry] {date} narrative_chars={len(narrative)}")
            print(narrative)
            continue
        env, ms = _dispatch_jev(narrative, QUESTIONS_RELAY)
        parsed = parse_jev_response(env, ms, expected_keys=set(QUESTIONS_RELAY))
        answers = parsed.get("answers") or {}
        scores = parsed.get("scores") or {}
        usage = parsed.get("usage") or {}
        # v9 daysInPhase 后验确定性计算（预登记 relay-v9 §五）：今日相位==昨日相位→昨日+1，否则 1。
        # 零 token；首日/缺昨日档/相位变更→1。供次日叙事软参照行读取（不上前端）。
        _today_phase = (answers.get("relay_phase") or {}).get("choice")
        _prev_d = _prev_relay_date(db, date, dataset_id)
        _prev_doc = db[COLLECTION].find_one({"_id": f"{_prev_d}:RELAY"}) if _prev_d else None
        _prev_phase = (_prev_doc or {}).get("relayPhase")
        _prev_dip = (_prev_doc or {}).get("daysInPhase")
        days_in_phase = (_prev_dip + 1) if (_today_phase and _today_phase == _prev_phase
                                           and isinstance(_prev_dip, int) and _prev_dip >= 1) else 1
        doc = {"_id": f"{date}:RELAY", "origin": "relay_index_daily", "tradingDate": date,
               "status": "ok" if parsed["ok"] else "degraded",
               "questionSetVersion": QUESTION_SET_VERSION_RELAY,
               "narrative": narrative, "questionsRaw": QUESTIONS_RELAY,
               # v6（2026-10-19）：板块接力链 + 龙头结构派生体（叙事/前端同一事实源，
               # 历史 v5 文档无此字段 → 读口 null，前端显「旧代未采集」，不补 0）
               "relayStructure": struct,
               # 主锚缺位标记（F2）：数据质量事实，不改打分（前端徽标/README 说明消费）
               # 2026-10-18 分层：anchorGaps=整根主锚不可用（琥珀）；anchorGapsDerived=子项级缺位（灰）
               # 日线原料溯源（2026-10-18 开长窗）：本地 vipdoc / 线上回退各供了多少只股——
               # 数据层事实，不入 prompt；供日后核对某日叙事拿的是全历史本地棒还是回退窗
               "barsSource": bars_source_provenance(),
               "anchorGaps": anchor_gaps(narrative),
               "anchorGapsDerived": anchor_gaps_derived(narrative),
               # answers 原样落库（P0-2/P0-3）：七题 confidence/momentum 等四题 probabilities/
               # 两个 score 题直方图此前未落库，自此保全（历史文档不可回补）
               "answers": parsed.get("answers"),
               "relayIndex": scores.get("relay_index"),
               "relayPhase": (answers.get("relay_phase") or {}).get("choice"),
               "relayPhaseProbabilities": (answers.get("relay_phase") or {}).get("probabilities"),
               "relayMomentum": (answers.get("relay_momentum") or {}).get("choice"),
               "ladderHealth": (answers.get("ladder_health") or {}).get("choice"),
               "moneyEffect": (answers.get("money_effect") or {}).get("choice"),
               # v9：删 leaderStrength/themePulse（删题）；daysInPhase 相位持续（后验，进语料不上前端）
               "daysInPhase": days_in_phase,
               # v8 市场周期融合题（2026-11-12）：补维度，状态机仍唯一权威；缺语料→insufficient_evidence
               # v10：删 cycleIntensity（删题，同 v9 删 leaderStrength/themePulse 口径；历史档字段不回改）
               "turnQuality": (answers.get("turn_quality") or {}).get("choice"),
               "riskAhead": (answers.get("risk_ahead") or {}).get("choice"),
               "cycleCorpusMissing": db["hotlist_jev_market_cycle"].find_one(
                   {"_id": f"{date}:MARKET_CYCLE"}) is None,
               "model": parsed.get("model"), "usage": usage, "latencyMs": ms,
               "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
               "responseRaw": None if parsed["ok"] else env,
               "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
        # 节点定格：已定档随档不改写；未定档以本次落库值首次定档（重跑≠改写历史节点）
        _apply_settlement(col.find_one({"_id": doc["_id"]}), doc, db, dataset_id)
        col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        print(f"[relay] {date} → index={doc['relayIndex']} phase={doc['relayPhase']} "
              f"momentum={doc['relayMomentum']} ladder={doc['ladderHealth']} "
              f"money={doc['moneyEffect']} daysInPhase={doc['daysInPhase']} ok={parsed['ok']} "
              f"tokens={(usage.get('input_tokens') or 0) + (usage.get('output_tokens') or 0)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--relay-day", dest="relay_day", action="append", default=[],
                    help="指定交易日判连板情绪指数（可多次传参；缺省=最近一个交易日）")
    ap.add_argument("--dry-run", action="store_true", help="只打印叙事，不调用模型")
    ap.add_argument("--force", action="store_true",
                    help="判据代际升级重放：已 ok 的日期也重新判定（replace_one 幂等覆盖）")
    ap.add_argument("--allow-unhealthy", dest="allow_unhealthy", action="store_true",
                    help="前置检查发现依赖档坏账仍强制重放（知情决策，报告照常透出）")
    ap.add_argument("--dataset-id", dest="dataset_id", default=DEFAULT_DATASET_ID)
    args = ap.parse_args()
    if not (os.environ.get("JEV_TYPESAFE_KEY") or "").strip() and not os.environ.get("JEV_CF_TOKEN"):
        raise SystemExit("需要 JEV_TYPESAFE_KEY 或 JEV_CF_TOKEN 环境变量")
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    # 回填前置检查（2026-11-16 事故裁决）：--force 多日重放前核对依赖链存档健康度。
    # LLM 重放不可逆：节点档坏账 → 梯队表龙一回退、叙事语料降级，烧 token 也只能
    # 产出降级答案并覆盖原档 → 默认阻断（--allow-unhealthy 显式越过）。单日日常
    # 判定（schedule 盘后链）不走此门，健康度由档内 fail-visible 字段披露。
    from backend.operations.backfill_preflight import EXIT_BLOCKED, relay_preflight
    from backend.operations.sector_nodes import SECTOR_NODE_VERSION
    if args.force and args.relay_day:
        pre = relay_preflight(db, args.relay_day, ledger_version=SECTOR_NODE_VERSION,
                              allow_unhealthy=args.allow_unhealthy)
        pre["proceed"] = not (pre["blockers"] and not args.allow_unhealthy)
        print(json.dumps({"preflight": pre}, ensure_ascii=False))
        if not pre["proceed"]:
            raise SystemExit(EXIT_BLOCKED)
    days = args.relay_day
    if not days:
        latest = db["jiuyan_action"].find_one(
            {"kind": "jiuyan_action"}, sort=[("tradingDate", -1)])
        days = [str(latest["tradingDate"])] if latest else []
    run_relay_index_day(db, days, dry_run=args.dry_run, dataset_id=args.dataset_id,
                        force=args.force)
