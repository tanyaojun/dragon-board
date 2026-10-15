# -*- coding: utf-8 -*-
"""jev 共振维独立判读弹药纯函数层（2026-10-14 试点：synergy 四维拆开独立判读的第一维）。

定位（用户裁决 2026-10-14「先以共振为试点，把题目集先做出来」）：
把引擎 synergy 四维里的【共振】单独拎出来，让 jev 在**同源原始语料**上独立判读
「注意力共振方向 + 强度」，与引擎读数机械对照（agree/diverge 台账）。
并列观察者边界不变（2026-10-08 裁决）：不回写引擎、不进 synergy 投票、不进交易路径。

**口径警告（本题集第一铁律）**：引擎共振的 buy/sell/hold 是「注意力相对全池的动能方向」
（10-14 实测 244 只里引擎给 buy 125 只），**不是「这只票能不能买」**。可买入性判断是
VOTE/LC 线的事，本题集不碰。判据若混进「值不值得买」语义，对照即刻失真。

同源合同（本层零 IO；取数与编排在 operations/jev_resonance_recheck.py）：
- 分位序列 = 引擎同一实现（attention_rank_lookup + percentile_rank，engine/primitives.py）
  **且同一窗口语义**：该股「最近 ≤50 次进榜出现」的前缀（**跨日**，末项=判读帧），
  与引擎 _build_code_attention_series + prefix=bars[:pos+1] 逐位同源——不是「当日 10 槽」；
- 市场基准 = 引擎同一实现（frame_market_median / frame_market_median_percentile，engine/runtime.py，
  4 帧窗口，判读帧索引 = 滚动帧列表末位）；
- 跳变标记 = 引擎 detect_rank_jumps 同口径（可复现算术衍生，非判定产物）；
- 预检线 = 引擎 insufficient 条件同口径（resonanceMidWindowBars+1 / resonanceMinMarketSampleCount）；
- 帧窗口 = 最近 280 个 half_hour 帧（ANALYZE_FULL_MARKET_LOAD_LIMIT 同值）。

黑名单（叙事零出现，机验+人工双查）：引擎四维档位/synergy 投票/finalSignal/compScore/compRank/
lifecycle 阶段/VOTE 方向/温度拥挤答案/价格量价结论——判定产物一律不喂，只喂原始事实与
可复现算术衍生（v4-material 同规，docs/hotlist-jev/jev-direction-v4-preregistration.md §三）。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.analysis.hotlist.jev_state import SCORE_ANCHORS_10
from backend.analysis.ranktrend.engine.config import RankTrendConfig

# ── 版本戳（独立戳：判据/语料任何一字变更即换代，旧代留档不回写）──
# v2（2026-10-14 首日 48.6% 一致率归因后改门）：判据①改显式两步算式（叙事直接给超额值）、
# 反转惩罚降级为「只可否决 buy、不得单独制造 sell」、持续性只改置信不改方向。
QUESTION_SET_VERSION_RESONANCE_RECHECK = "v2"
RESONANCE_AMMO_VERSION = "2026-10-14b"
# ── 与引擎同源的窗口/预检阈值（单一事实源=引擎实现；runner 侧同款常量见其模块头）──
_CFG = RankTrendConfig()
RESONANCE_MIN_BARS = _CFG.resonanceMidWindowBars + 1                 # 引擎 percentiles < mid+1 → insufficient
RESONANCE_MIN_MARKET_SAMPLE = _CFG.resonanceMinMarketSampleCount    # 引擎横截面有效样本线
RESONANCE_JUMP_DELTA_PCT = 10.0                                     # 引擎 detect_rank_jumps 默认 delta_pct

RESONANCE_DIRECTIONS = ("buy", "sell", "hold", "insufficient")

# 强度标尺（与引擎 _resonance_label 阈值同口径 85/67/50/27）：判据参照尺 + 台账分桶共用
STRENGTH_BANDS: tuple[tuple[float, str], ...] = ((85.0, "非常强"), (67.0, "强"),
                                                 (50.0, "中等"), (27.0, "较弱"), (0.0, "非常弱"))


def strength_band(score: Any) -> str | None:
    """score → 强度标尺名（与引擎 label 阈值同口径；非有限数 → None，不伪造）。"""
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    v = float(score)
    if v != v:  # NaN
        return None
    for floor, name in STRENGTH_BANDS:
        if v >= floor:
            return name
    return None


def short_window_excess(series: list[dict], market: dict | None) -> float | None:
    """短窗超额（判据第一步输入；可复现算术衍生，非判定产物）：
    短窗（最后 3 次出现）分位变化 − 市场基准中位数。序列 <9 次出现或基准缺失 → None（不猜）。

    v2 改门核心：**减法由runner 现算后直接喂进叙事**，不让模型自己做——v1 的 93 例
    「原料说走强、jev 判走弱」归因即模型未执行该减法（或只看绝对升降）。
    """
    pcts = [s.get("percentile") for s in series
            if isinstance(s.get("percentile"), (int, float))
            and not isinstance(s.get("percentile"), bool)]
    if len(pcts) < RESONANCE_MIN_BARS or not market:
        return None
    base = market.get("medianShortChange")
    if isinstance(base, bool) or not isinstance(base, (int, float)):
        return None
    b = float(base)
    if b != b:  # NaN
        return None
    return float(pcts[-1]) - float(pcts[-3]) - b


# ── 题集（判据冻结件候选：逐字=将来代码文本；改一字=改门，须走预登记+用户点头）──

_DIR_INSTR = (
    "以下是某只股票在判读帧的【注意力共振】判读原料——只含注意力（热榜排名）维度的原始事实"
    "与可复现算术衍生，不含任何价格/量价/四维档位/周期阶段/方向票结论。原料五块："
    "[注意力出现序列] 该股最近 ≤50 次进榜出现的注意力分位（0-100，越高越靠前；由池内 "
    "attention rank 现算，跨日逐次出现按时间升序列出，未进榜不插值），含相邻两次出现的分位差与"
    "排名跳变标记（累计分位变化 >10pt 触发，surge=跳升/collapse=崩塌，与引擎 detect_rank_jumps "
    "同口径），头部标注出现次数（序列深度）；[市场基准] 判读帧前 4 帧窗口内全池注意力分位变化"
    "中位数（该股相对强弱的标尺）、池内分位中位数、池子大小、有效样本数，**以及已替你算好的"
    "短窗超额值**；[入榜状态] 是否本次序列首个出现（新入榜）、当前注意力分位；[质量自标] "
    "缺出现/缺字段如实列出。"
    "请判断：该股当前的注意力共振方向读作 buy、sell、hold 还是 insufficient，附 0-1 置信度。"
    "**口径铁律：buy/sell 只表示「该股注意力相对全池的动能方向」，绝不表示「这只票值不值得买」**——"
    "可买入性是另一条线的事，本材料里也没有价格与量价证据。"
    "**判读必须按下面三步走，顺序不可调、不可跳步**："
    "第一步·算超额：短窗（最后 3 次出现）分位变化 = 序列末项分位 − 倒数第 3 项分位；"
    "短窗超额 X = 该短窗变化 − 全池分位变化中位数（[市场基准] 已直接给出 X，"
    "**请以该值为准，不得自行改算；也不得只看绝对升降而忘记减基准**——绝对升降含大盘成分，"
    "不是相对强弱）。"
    "第二步·定方向：X ≥ +5 → 只能读 buy 或 hold；X ≤ −5 → 只能读 sell 或 hold；"
    "|X| < 5 → 只能读 hold（与池子同步）；数据不可用 → insufficient。"
    "第三步·修正（只改置信度、只把 buy 降为 hold，**不得反向制造方向**）：持续性差（相邻出现差"
    "来回翻转）、逆向跳变、反转惩罚（自序列内近期峰值回撤 ≥10pt）——这些只降低置信度，或把"
    "buy 降级为 hold；**任何修正都不得把方向改成 sell，除非 X ≤ −5 或末项附近有 collapse 跳变**；"
    "同理不得把方向改成 buy，除非 X ≥ +5。跳变标记 surge 且靠近末项加强 buy，collapse 加强 sell；"
    "与基准方向相反的逆向跳变以跳变为准。序列深度 <9 次出现时序列不作主证据，只依市场基准与"
    "入榜状态给方向并降置信；insufficient 仅限数据不可用（序列 <9 次出现且市场基准缺失、"
    "或市场基准有效样本 <20、或时间轴不完整）；证据冲突=hold，不是 insufficient。"
    "只依据所给信息判断，不预测后市。"
)

_STRENGTH_INSTR = (
    "同一份原料，该股注意力共振的强度落点（0=完全无共振/纯噪声，100=极强且干净的相对注意力动能）。"
    "正贡献=相对动量幅度（短窗超额分位变化）、加速度（短窗较中窗趋势加快的程度）、路径持续性、"
    "跳变新鲜度（跳变点靠近末项）；负贡献=反转惩罚（自峰值回撤 + 方向翻转）。"
    "参照尺（与引擎 score 标尺同口径）：0-26 非常弱 / 27-49 较弱 / 50-66 中等 / 67-84 强 / 85-100 非常强。"
    "方向读作 sell 时按「衰竭/反向的强度」落点——自峰值回撤越深、翻转越频繁越强。"
    "**强度不得与第一步的方向互相矛盾**：方向 buy 需 X ≥ +5，方向 sell 需 X ≤ −5 或 collapse 跳变；"
    "方向与 X 符号相反时强度不得超过 30（证据不足的弱读数）。"
    "数据不可用时给 0，并在 direction 题选 insufficient。只依据所给信息判断，不预测后市。"
)

QUESTIONS_RESONANCE_RECHECK: dict[str, dict] = {
    "resonance_direction": {
        "type": "choice",
        "instructions": _DIR_INSTR,
        "criteria": {
            "buy": ("第一步算出的短窗超额 X ≥ +5（相对走强），且无反转惩罚强证据"
                    "（未自序列内近期峰值回撤 ≥10pt、无频繁方向翻转）；新入榜且当前分位明显高于"
                    "池内分位中位数、或末项附近 surge 跳变，可加强"),
            "sell": ("第一步算出的短窗超额 X ≤ −5（相对走弱）；或末项附近 collapse 跳变"
                     "（逆向跳变以跳变为准）。**仅凭反转惩罚/持续性差/绝对下跌不得判 sell**"),
            "hold": ("|X| < 5（与市场基准相当）；或 X ≥ +5 但被反转惩罚/持续性差降级；"
                     "或 buy 与 sell 证据互相抵消；或序列深度 <9 只依基准与入榜状态给的中性读数"),
            "insufficient": ("仅数据不可用：序列 <9 次出现且市场基准缺失、或市场基准有效样本 <20、"
                             "或时间轴不完整；永不因证据冲突选此项"),
        },
    },
    "resonance_strength": {
        "type": "score",
        "instructions": _STRENGTH_INSTR,
        "criteria": list(SCORE_ANCHORS_10),
    },
}


# ── 预检 riskFlag（runner 侧数据完备度；与引擎 insufficient 条件同口径）──

def resonance_risk_flag(bars: int, market_sample_count: int,
                        timeline_valid: bool = True, missing_slots: int = 0) -> dict:
    """数据完备度预检：出现次数<9 / 市场基准样本<20 / 时间轴不完整 → data_insufficient
    （不进人口不调用，落留痕文档——防模型瞎猜）；缺出现但有基准 → partial（仍判，缺出现如实标缺）。"""
    reasons: list[str] = []
    if not timeline_valid:
        reasons.append("时间轴不完整")
    if bars < RESONANCE_MIN_BARS:
        reasons.append(f"序列出现次数={bars}(<{RESONANCE_MIN_BARS})")
    if market_sample_count < RESONANCE_MIN_MARKET_SAMPLE:
        reasons.append(f"市场基准样本={market_sample_count}(<{RESONANCE_MIN_MARKET_SAMPLE})")
    if reasons:
        return {"level": "data_insufficient", "reasons": reasons}
    if missing_slots:
        reasons.append(f"缺出现{missing_slots}个（序列行如实标缺）")
    return {"level": "ok" if not reasons else "partial", "reasons": reasons}


# ── 叙事组装（纯函数；fail-visible 缺口如实注记，禁伪装）──

def _f(v: Any, nd: int = 1) -> str:
    """有限数透传（缺/NaN → "缺"）；不伪造 0。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "缺"
    x = float(v)
    if x != x:
        return "缺"
    return f"{round(x, nd)}"


def _delta(v: Any) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "缺"
    x = float(v)
    if x != x:
        return "缺"
    return f"{x:+.1f}"


def _i(v: Any) -> str:
    """整数透传（rank/total/样本数/池大小；缺/NaN → "缺"）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "缺"
    x = float(v)
    if x != x:
        return "缺"
    return str(int(round(x)))


def build_resonance_narrative(*, trading_date: str, slot: str, code: str, name: Any,
                              series: list[dict], market: dict | None,
                              entry: dict, jump_events: list[dict] | None,
                              quality: dict) -> str:
    """共振维叙事（五块：出现序列/跳变/市场基准/入榜/质量自标）。

    series: [{tradingDate, slot, rank, total, percentile, delta}]（delta=本次出现分位 − 上次
    出现分位；缺出现 percentile=None）；跨日逐次出现按时间升序，末项=判读帧。
    market: {medianShortChange, sampleCount, medianPercentile, poolSize}（None=横截面不可算）；
    entry: {isNew, currentPercentile}；
    jump_events: 引擎 detect_rank_jumps 的 events（[{index, direction, magnitude}]；None=未算）；
    quality: {missingAppearances: [...], missingFields: [...]}。

    v2 起市场基准块**首行直接给短窗超额值**（判据第一步输入，runner 同款纯函数现算）——
    不让模型自己做减法（v1 归因：93 例「原料说走强、jev 判走弱」即模型未执行减法）。
    """
    bars = sum(1 for s in series if isinstance(s.get("percentile"), (int, float)))
    head = f"{trading_date} {slot} (judgment frame) · {code} {name or ''}".rstrip()
    lines = [
        "[Attention Appearance Series · cross-day; 0-100 = attention percentile within pool; "
        "LAST = judgment frame; Δ = change vs previous appearance]",
        f"history depth: {bars} appearances"
        + (f" · SHORT: <{RESONANCE_MIN_BARS} appearances, series NOT usable as primary "
           "evidence; lower confidence" if bars < RESONANCE_MIN_BARS else ""),
    ]
    for s in series:
        pct = s.get("percentile")
        when = f"{s.get('tradingDate') or '?'} {s.get('slot') or '?'}"
        if isinstance(pct, (int, float)):
            lines.append(f"{when}: pct {_f(pct)} "
                         f"(rank {_i(s.get('rank'))}/{_i(s.get('total'))}, Δ{_delta(s.get('delta'))})")
        else:
            lines.append(f"{when}: 缺（该次无有效出现，fail-visible）")
    if jump_events:
        marks = []
        for e in jump_events:
            idx = int(e.get("index", -1))
            when = (f"{series[idx].get('tradingDate')} {series[idx].get('slot')}"
                    if 0 <= idx < len(series) else "?")
            sign = "+" if e.get("direction") == "surge" else "-"
            marks.append(f"{'surge' if e.get('direction') == 'surge' else 'collapse'}@{when}"
                         f"({sign}{_f(e.get('magnitude'))}pt)")
        lines.append(f"jump marks (|cumulative Δ| > {RESONANCE_JUMP_DELTA_PCT:g}pt, "
                     f"engine detect_rank_jumps caliber): {' · '.join(marks)}")
    else:
        lines.append(f"jump marks: none（<3 次出现不检测，fail-visible）")
    lines.append(f"[Market Baseline · 4-frame window ending at {trading_date} {slot}]")
    excess = short_window_excess(series, market)
    lines.append(f"short-window excess X (last-3-appearance change − pool median change): "
                 f"{_delta(excess)}"
                 + ("  ← step-1 input, USE AS-IS (do not recompute, do not read absolute moves)"
                    if excess is not None else "  ← 不可算（序列 <9 次出现或基准缺失），方向题选 insufficient"))
    if market:
        lines.append(f"pool median attention percentile change: "
                     f"{_f(market.get('medianShortChange'))} (valid sample {_i(market.get('sampleCount'))})"
                     " ← the ruler for relative strength")
        lines.append(f"pool median percentile: {_f(market.get('medianPercentile'))} · "
                     f"pool size: {_i(market.get('poolSize'))}")
    else:
        lines.append("pool median attention percentile change: 缺（窗口不足 4 帧或公共样本 "
                     f"<{RESONANCE_MIN_MARKET_SAMPLE}，横截面不可算，fail-visible）")
    lines.append("[Entry]")
    lines.append(f"first appearance in series (new entry): {'yes' if entry.get('isNew') else 'no'} · "
                 f"current attention percentile: {_f(entry.get('currentPercentile'))}")
    lines.append("[Data Quality · self-reported]")
    q = quality or {}
    miss = q.get("missingAppearances") or []
    miss_fields = q.get("missingFields") or []
    lines.append(f"missing appearances: {miss if miss else 'none'} · "
                 f"missing fields: {miss_fields if miss_fields else 'none'}")
    return "\n".join([head, *lines])
