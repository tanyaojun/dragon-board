# -*- coding: utf-8 -*-
"""jev 趋势维独立判读弹药纯函数层（2026-10-14 试点第二维；参照共振 pilot 同构）。

定位（用户裁决 2026-10-14「参照共振步骤改趋势」）：把引擎 synergy 四维里的【趋势】单独拎出来，
让 jev 在**同源原始语料**上独立判读「注意力趋势方向 + 强度」，与引擎读数机械对照。
并列观察者边界不变（2026-10-08 裁决）：不回写引擎、不进 synergy 投票、不进交易路径。

**原料自足性（开工前已核实）**：引擎趋势维 `analyze_technical(percentiles, config, fallback)`
吃的**不是 TDX 日线**，而是与共振维完全相同的那条「跨日最近 ≤50 次进榜出现」分位序列
（MA5/MA10、MACD 13/21/8、MA 快慢线、momentum 全算在这条序列上）；序列不足
（< get_technical_min_computable_samples = macdSlow+1 = 22 次出现）时，引擎自身降级到
`fallback_signals`，主证据换成判读帧行字段（displayChange/stockChange/volumeRatio/zlje/zljzb）。
两个模式的原料都在 snapshot_frames/stock_rows 里，**零外部依赖、零第二实现**。

**对照锚的干净度（已核实）**：`observation.rankTrend.direction` 取的是 `compose_decision` 的
**base.signal**（技术面五分量加权和的信号），不含 cycle/risk 对 final 的改写——所以锚就是
纯技术面读数，与本题集语义严格对齐（分歧不来自锚污染）。

同源合同（本层零 IO；取数与编排在 operations/jev_trend_recheck.py）：
- 分位序列 = 引擎同一实现（attention_rank_lookup + percentile_rank，engine/primitives.py）
  **且同一窗口语义**：该股最近 ≤50 次进榜出现的前缀（跨日，末项=判读帧）；
- MA/MACD/MA交叉/momentum = 引擎同一实现（trend/technical.py 的 moving_average /
  calculate_macd / calculate_ma_cross / momentum_profile）——**可复现算术衍生，非判定产物**；
- fallback 五字段 = 引擎 fallback_signals 的同一输入（判读帧行，displayChange=末项−前项分位差）；
- 预检线 = 引擎技术面可算线同口径（22 次出现）；
- 帧窗口 = 最近 280 个 half_hour 帧（ANALYZE_FULL_MARKET_LOAD_LIMIT 同值）。

黑名单（叙事零出现，机验+人工双查）：引擎五维档位/synergy 投票/finalSignal/compScore/compRank/
lifecycle 阶段/VOTE 方向/温度拥挤答案/共振维读数/价格量价结论——判定产物一律不喂，只喂原始
事实与可复现算术衍生（v4-material 同规）。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.analysis.hotlist.jev_state import SCORE_ANCHORS_10
from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.engine.primitives import (
    get_macd_min_samples,
    get_momentum_min_samples,
    get_technical_min_computable_samples,
)
from backend.analysis.ranktrend.trend.technical import (
    calculate_macd,
    calculate_ma_cross,
    momentum_profile,
    moving_average,
)

# ── 版本戳（独立戳：判据/语料任何一字变更即换代，旧代留档不回写）──
QUESTION_SET_VERSION_TREND_RECHECK = "v1"
TREND_AMMO_VERSION = "2026-10-15a"

_CFG = RankTrendConfig()
TREND_MIN_BARS = get_technical_min_computable_samples(_CFG)   # 引擎技术面可算线（22）
TREND_MACD_MIN_BARS = get_macd_min_samples(_CFG)              # MACD 最少样本（macdSlow=21）
TREND_MOMENTUM_MIN_BARS = get_momentum_min_samples(_CFG)      # momentum 最少样本（max period+1）

TREND_DIRECTIONS = ("buy", "sell", "hold", "insufficient")
TREND_MODES = ("series", "fallback")   # series=序列可算（≥22 次出现）；fallback=引擎同款降级

# 强度标尺（与引擎 label 阈值同口径 85/67/50/27）：判据参照尺 + 台账分桶共用
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


# ── 引擎同源衍生（纯函数；runner 只负责把序列/帧行喂进来）──

def derived_indicators(percentiles: list[float]) -> dict[str, Any]:
    """引擎同源的派生读数（moving_average/calculate_macd/calculate_ma_cross/momentum_profile）。

    返回叙事可直接引用的dict；任一分量在引擎口径下不可算时如实 None（fail-visible，不伪造 0）。
    """
    pcts = [p for p in percentiles if isinstance(p, (int, float)) and not isinstance(p, bool)]
    ma5 = moving_average(pcts, 5) if pcts else None
    ma10 = moving_average(pcts, 10) if pcts else None
    macd = calculate_macd(pcts, _CFG)
    ma_cross = calculate_ma_cross(pcts, _CFG)
    momentum = momentum_profile(pcts) if pcts else {}
    return {
        "ma5": ma5, "ma10": ma10,
        "maTrend": ("up" if ma5 is not None and ma10 is not None and ma5 > ma10
                    else "down" if ma5 is not None and ma10 is not None and ma5 < ma10
                    else "steady" if ma5 is not None and ma10 is not None else None),
        "macd": {"dif": macd.get("dif"), "dea": macd.get("dea"),
                 "histogram": macd.get("histogram"), "cross": macd.get("cross"),
                 "confirmed": macd.get("confirmed")},
        "maCross": {"fast": ma_cross.get("fast"), "slow": ma_cross.get("slow"),
                    "state": ma_cross.get("state"), "cross": ma_cross.get("cross")},
        "momentum": {k: momentum.get(k) for k in
                     ("short", "mid", "long", "acceleration", "shock", "composite")},
    }


def trend_risk_flag(bars: int, fallback_fields: dict[str, Any] | None = None) -> dict:
    """预检 riskFlag（与引擎两条模式同口径）：

    - bars ≥ 22 → 序列模式（ok）：技术面可算，主证据=序列+派生读数；
    - 2 ≤ bars < 22 → fallback 模式（partial）：引擎同款降级，主证据=判读帧行字段
      （displayChange/stockChange/volumeRatio/zlje/zljzb），派生读数多数不可算、如实标注；
    - bars < 2 → data_insufficient：连「末项−前项」都算不出，两条模式都无证据。
    """
    if bars < 2:
        return {"level": "data_insufficient", "mode": None,
                "reasons": [f"序列出现次数={bars}(<2，末项−前项都不可算)"]}
    if bars >= TREND_MIN_BARS:
        return {"level": "ok", "mode": "series", "reasons": []}
    return {"level": "partial", "mode": "fallback",
            "reasons": [f"序列出现次数={bars}(<{TREND_MIN_BARS})，引擎同款降级到帧行字段"]}


# ── 题集（判据冻结件候选：逐字=将来代码文本；改一字=改门，须走预登记+用户点头）──

_DIR_INSTR = (
    "以下是某只股票在判读帧的【注意力趋势】判读原料——只含注意力（热榜排名）维度的原始事实"
    "与可复现算术衍生，不含任何价格结论/量价结论/四维档位/周期阶段/方向票结论。原料五块："
    "[注意力出现序列] 该股最近 ≤50 次进榜出现的注意力分位（0-100，越高越靠前；池内 attention "
    "rank 现算，跨日逐次出现按时间升序，未进榜不插值），头部标注出现次数（序列深度）；"
    "[派生读数]（由上面这条序列用与引擎完全相同的算法现算：MA5/MA10 及快慢关系、"
    "MACD 13/21/8 的 DIF/DEA/柱值/金叉死叉、MA 快慢线 10/20 的多空状态与交叉、"
    "momentum 短/中/长/加速度）；[判读帧行字段] 该股在判读帧的涨幅、量比、主力净额与占比"
    "（序列不足时这是主证据）；[入榜状态] 是否本次序列首个出现；[质量自标] 缺出现/缺字段如实列出。"
    "请判断：该股当前的注意力趋势方向读作 buy、sell、hold 还是 insufficient，附 0-1 置信度。"
    "**口径铁律：buy/sell 只表示「该股注意力在序列上的技术面方向」，绝不表示「这只票值不值得买」**——"
    "可买入性是另一条线的事，本材料里也没有价格与量价证据。"
    "**判读按两步走**："
    "第一步·数分量共识（五个分量：①MA 快慢关系 ma5 vs ma10；②MACD 交叉与柱值符号；"
    "③MA 快慢线 10/20 多空状态与交叉；④momentum 短中期符号（short/mid 为正=向上）；"
    "⑤判读帧行字段方向（涨幅/量比/主力净额的同向性））。"
    "第二步·定方向：**同一方向的分量 ≥2 个、且反方向分量 ≤1 个 → 该方向**；"
    "反方向分量 ≥2 个、且正方向分量 ≤1 个 → sell；分量互相抵消、或同向分量不足 2 个 → hold；"
    "数据不可用 → insufficient。"
    "注意：分量本身要按「序列末期」读——序列深度 <22 次出现时 MA/MACD/MA交叉 多数不可算"
    "（原料块已如实标注），此时⑤帧行字段是主证据，①②③不参与计票；"
    "insufficient 仅限数据不可用（出现次数 <2、或序列模式但派生读数全缺、或时间轴不完整）；"
    "证据冲突=hold，不是 insufficient。只依据所给信息判断，不预测后市。"
)

_STRENGTH_INSTR = (
    "同一份原料，该股注意力趋势的强度落点（0=无趋势/纯噪声，100=极强且干净的单向趋势）。"
    "正贡献=同向分量的数量与幅度（分位偏离均线的距离、MACD 柱值厚度、momentum 短中期幅度、"
    "帧行字段同向程度）；负贡献=反向分量牵制、序列反复翻转（shock 大）、临近交叉的临界状态。"
    "参照尺（与引擎 score 标尺同口径）：0-26 非常弱 / 27-49 较弱 / 50-66 中等 / 67-84 强 / 85-100 非常强。"
    "方向读作 sell 时按「下行趋势的强度」落点——偏离越深、同向分量越多越强。"
    "**强度不得与方向矛盾**：方向 buy 但同向分量不足、或方向 sell 而分量多头上行时，"
    "强度不得超过 30。数据不可用时给 0，并在 direction 题选 insufficient。"
    "只依据所给信息判断，不预测后市。"
)

QUESTIONS_TREND_RECHECK: dict[str, dict] = {
    "trend_direction": {
        "type": "choice",
        "instructions": _DIR_INSTR,
        "criteria": {
            "buy": ("第一步数出的同向（向上）分量 ≥2 个，且向下分量 ≤1 个：MA5>MA10、"
                    "MACD 金叉或柱值为正且放大、MA10>MA20（或多头交叉）、"
                    "momentum short/mid 为正、帧行字段（涨幅/量比/主力净额）同向为正"),
            "sell": ("同向（向下）分量 ≥2 个，且向上分量 ≤1 个：MA5<MA10、"
                     "MACD 死叉或柱值为负且放大、MA10<MA20（或空头交叉）、"
                     "momentum short/mid 为负、帧行字段同向为负"),
            "hold": ("同向分量不足 2 个；或上下分量互相抵消；或序列末期临近交叉的临界状态；"
                     "或序列深度 <22 次出现而帧行字段本身方向不一致"),
            "insufficient": ("仅数据不可用：出现次数 <2；或序列模式（≥22 次出现）但派生读数全缺；"
                             "或时间轴不完整；永不因证据冲突选此项"),
        },
    },
    "trend_strength": {
        "type": "score",
        "instructions": _STRENGTH_INSTR,
        "criteria": list(SCORE_ANCHORS_10),
    },
}


# ── 叙事组装（纯函数；fail-visible 缺口如实注记，禁伪装）──

def _f(v: Any, nd: int = 1) -> str:
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
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "缺"
    x = float(v)
    if x != x:
        return "缺"
    return str(int(round(x)))


def _cn_cross(v: Any) -> str:
    return {"golden": "金叉", "death": "死叉", "none": "无"}.get(str(v or "none"), "无")


def _cn_state(v: Any) -> str:
    return {"bull": "多头(fast>slow)", "bear": "空头(fast<slow)",
            "flat": "走平", "unknown": "不可算(样本不足)"}.get(str(v or ""), "不可算")


def build_trend_narrative(*, trading_date: str, slot: str, code: str, name: Any,
                          series: list[dict], derived: dict[str, Any],
                          frame_fields: dict[str, Any], entry: dict,
                          quality: dict) -> str:
    """趋势维叙事（五块：出现序列/派生读数/帧行字段/入榜/质量自标）。

    series: [{tradingDate, slot, rank, total, percentile, delta}]（跨日逐次出现，末项=判读帧）；
    derived: derived_indicators() 的输出（引擎同源算法现算）；
    frame_fields: {displayChange, stockChange, volumeRatio, zlje, zljzb}
                  （引擎 fallback_signals 的同一输入，序列不足时是主证据）；
    entry: {isNew, currentPercentile}；quality: {missingAppearances, missingFields}。
    """
    bars = sum(1 for s in series if isinstance(s.get("percentile"), (int, float)))
    head = f"{trading_date} {slot} (judgment frame) · {code} {name or ''}".rstrip()
    mode = "series" if bars >= TREND_MIN_BARS else "fallback"
    lines = [
        "[Attention Appearance Series · cross-day; 0-100 = attention percentile within pool; "
        "LAST = judgment frame; Δ = change vs previous appearance]",
        f"history depth: {bars} appearances · mode: {mode}"
        + (f"（<{TREND_MIN_BARS} 次出现：MA/MACD/MA交叉多数不可算，帧行字段是主证据）"
           if mode == "fallback" else "（序列可算：主证据=序列+派生读数）"),
    ]
    for s in series:
        pct = s.get("percentile")
        when = f"{s.get('tradingDate') or '?'} {s.get('slot') or '?'}"
        if isinstance(pct, (int, float)):
            lines.append(f"{when}: pct {_f(pct)} "
                         f"(rank {_i(s.get('rank'))}/{_i(s.get('total'))}, Δ{_delta(s.get('delta'))})")
        else:
            lines.append(f"{when}: 缺（该次无有效出现，fail-visible）")
    d = derived or {}
    ma5, ma10 = d.get("ma5"), d.get("ma10")
    macd = d.get("macd") or {}
    ma_cross = d.get("maCross") or {}
    mom = d.get("momentum") or {}
    lines.append("[Derived Readings · same algorithm as engine trend/technical.py, "
                 "computed on the series above]")
    lines.append(f"MA5={_f(ma5)} · MA10={_f(ma10)} · fast/slow: {d.get('maTrend') or '不可算'}")
    lines.append(f"MACD(13/21/8): DIF={_f(macd.get('dif'))} · DEA={_f(macd.get('dea'))} · "
                 f"histogram={_f(macd.get('histogram'))} · cross={_cn_cross(macd.get('cross'))}"
                 f"（confirmed={'yes' if macd.get('confirmed') else 'no'}）")
    lines.append(f"MA fast/slow(10/20): fast={_f(ma_cross.get('fast'))} · slow={_f(ma_cross.get('slow'))} · "
                 f"state={_cn_state(ma_cross.get('state'))} · cross={_cn_cross(ma_cross.get('cross'))}")
    lines.append(f"momentum: short={_f(mom.get('short'))} · mid={_f(mom.get('mid'))} · "
                 f"long={_f(mom.get('long'))} · acceleration={_f(mom.get('acceleration'))} · "
                 f"shock={_f(mom.get('shock'))}")
    lines.append("[Judgment Frame Row Fields · engine fallback_signals input; "
                 "PRIMARY evidence when series <"
                 f"{TREND_MIN_BARS} appearances]")
    lines.append(f"displayChange (last-appearance percentile delta) = {_delta(frame_fields.get('displayChange'))} · "
                 f"stockChange = {_delta(frame_fields.get('stockChange'))}% · "
                 f"volumeRatio = {_f(frame_fields.get('volumeRatio'), 2)} · "
                 f"zlje = {_f(frame_fields.get('zlje'), 2)} · zljzb = {_f(frame_fields.get('zljzb'), 2)}%")
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
