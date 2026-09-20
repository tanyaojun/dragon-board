from __future__ import annotations

import math
import sys
from collections import defaultdict, deque

from typing import Any, Callable

from .config import RankTrendConfig, _validate_tier_constraints
from .primitives import clamp, _is_finite_number, average, normalize_signed, signal_confidence, weighted_share

from .config import RankTrendConfig, _validate_tier_constraints

from .primitives import get_macd_min_samples, get_momentum_min_samples, get_technical_min_computable_samples, get_technical_min_samples, percentile_rank, attention_rank_lookup

def median_of(values: list[float]) -> float | None:
    """中位数（无依赖实现）；空列表返回 None（fail-visible：不伪造 0）。"""
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def frame_cross_section(frame: dict[str, Any]) -> dict[str, float]:
    """旧 TS buildFrameCrossSections 合同（阶段 3 修复方向 1 下沉自 routes）：过滤 avgRankNum > 0，
    按 (avgRankNum, code) 升序，百分位 = ((n - idx) / n) * 100（idx 从 0 开始）。

    2026-09-12 口径合一：重排与百分位统一委托 attention_rank_lookup + percentile_rank
    （与趋势 replay / routes rank-series 同一实现，avgRankNum→序号/百分位唯一权威口径）；
    rank=idx+1（1-based）代入 percentile_rank 得 ((total-idx)/total)*100，与原实现逐位一致
    （回归护栏 tests/test_avg_ranknum_percentile_unification.py）。"""
    ranks, total = attention_rank_lookup(frame.get("stocks") or [])
    return {code: percentile_rank(rank, total) for code, rank in ranks.items()}


def frame_market_median(frames: list[dict[str, Any]], index: int) -> tuple[float | None, int]:
    """旧 TS calculateMarketMedian 合同（阶段 3 修复方向 1 下沉自 routes）：当前帧与前第 3 个
    市场帧公共股票的 attention 百分位变化中位数；sampleCount = 当前帧横截面股票数。
    窗口不足 4 帧 / 公共样本 <20 → 返回 None（横截面不可算，fail-visible）。"""
    start = max(0, index - 3)
    window = frames[start : index + 1]
    current = frame_cross_section(window[-1])
    sample_count = len(current)
    if len(window) < 4 or not current:
        return None, sample_count
    first = frame_cross_section(window[0])
    changes: list[float] = []
    for code, current_pct in current.items():
        first_pct = first.get(code)
        if first_pct is not None:
            changes.append(current_pct - first_pct)
    if len(changes) < 20:
        return None, sample_count
    return median_of(changes), sample_count


def frame_market_median_percentile(frame: dict[str, Any]) -> float | None:
    """该帧市场横截面 attention 百分位中位数（与 marketMedianShortChange 同口径）。"""
    return median_of(list(frame_cross_section(frame).values()))


def _percentile_sorted(sorted_values: list[float], ratio: float) -> float:
    """已升序 list 的线性插值分位（ratio∈(0,1]），等价于 numpy.percentile 的 linear 模式。"""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * ratio
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return sorted_values[low]
    frac = pos - low
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac


def frame_market_percentiles(
    frame: dict[str, Any],
    ratios: tuple[float, ...] = (0.5, 0.7, 0.85),
) -> dict[str, float]:
    """G3 全市场量能分位（2026-08-23 前后端分离）：对 frame.stocks 全市场计算
    turnover/volumeRatio/turnoverRate 的 P50/70/85（扁平字段 turnoverP50...）。
    过滤无效/非正值；某维度有效样本 < 20 则该维度整组不产出（fail-visible，不伪造 0）。
    供后端 golden 生产市场分位、前端 statusClassifier 消费（替代前端当前视图自算分位）。"""
    stocks = frame.get("stocks") or []
    out: dict[str, float] = {}
    for field in ("turnover", "volumeRatio", "turnoverRate"):
        values: list[float] = []
        for stock in stocks:
            if not isinstance(stock, dict):
                continue
            try:
                value = float(stock.get(field))
            except (TypeError, ValueError):
                continue
            if math.isfinite(value) and value > 0:
                values.append(value)
        if len(values) < 20:
            continue
        values.sort()
        for ratio in ratios:
            out[f"{field}P{int(round(ratio * 100))}"] = _percentile_sorted(values, ratio)
    return out



from ..trend.technical import period_momentum, prev_period_momentum, moving_average, ema_series, calculate_macd, momentum_profile, rank_shock, cycle_rank_shock, rank_path_commitment, momentum_data, analyze_momentum_signals, analyze_technical, fallback_signals

def detect_rank_jumps(
    percentiles: list[float],
    ranks: list[float] | None = None,
    delta_pct: float = 10.0,
    reset_lookback: int = 3,
    sustain_count: int = 2,
) -> dict[str, Any]:
    """内生阈值排名跳跃检测。

    持续追踪累计排名百分位变化，当 |累计变化| > delta 时触发事件。
    核心原理：波动爆发（来回震荡）的累计变化互相抵消，达不到阈值；
    只有不可逆的趋势性移动才会触发。

    Args:
        percentiles: 排序百分位序列 (0-100)
        ranks: 原始排名序列，用于计算实际排名变化幅度
        delta_pct: 百分位变化阈值，默认 10 个百分点
        reset_lookback: 事件触发后重置参考价的近期窗口（默认 3，原硬编码）
        sustain_count: sustained 判定阈值（surge/collapse 事件数，默认 2，原硬编码）

    Returns:
        event: "jump" | "none"
        direction: "buy" (排名跳跃式上升) | "sell" (排名崩塌式下降) | "hold"
        confidence: 0-100, 基于幅度、过冲量和持续性
    """
    if len(percentiles) < 3:
        return {
            "event": "none", "direction": "hold", "signal": "hold",
            "magnitude": 0, "overshoot": 0, "delta": delta_pct,
            "sustained": False, "confidence": 50, "eventCount": 0,
            "surgeCount": 0, "collapseCount": 0, "events": [],
        }

    ref = percentiles[0]
    events: list[dict[str, Any]] = []

    for i, p in enumerate(percentiles):
        cum_change = p - ref
        if abs(cum_change) > delta_pct:
            events.append({
                "index": i,
                "direction": "surge" if cum_change > 0 else "collapse",
                "magnitude": round(abs(cum_change), 2),
                "overshoot": round(abs(cum_change) - delta_pct, 2),
                "percentile": round(p, 2),
            })
            # 重置到近期均价而非当前极值，防止极端值误触反向事件
            lookback = min(reset_lookback, i + 1)
            ref = sum(percentiles[i - lookback + 1 : i + 1]) / lookback

    if not events:
        cum = percentiles[-1] - percentiles[0]
        return {
            "event": "none", "direction": "hold", "signal": "hold",
            "magnitude": round(abs(cum), 2), "overshoot": 0, "delta": delta_pct,
            "sustained": False, "confidence": 50, "eventCount": 0,
            "surgeCount": 0, "collapseCount": 0, "events": [],
            "cumulativeChange": round(cum, 2),
        }

    latest = events[-1]
    surge_count = sum(1 for e in events if e["direction"] == "surge")
    collapse_count = sum(1 for e in events if e["direction"] == "collapse")
    sustained = surge_count >= sustain_count or collapse_count >= sustain_count
    direction = "buy" if latest["direction"] == "surge" else "sell"

    mag = latest["magnitude"]
    overshoot = latest["overshoot"]
    mag_factor = min(1.0, mag / max(delta_pct * 2, 1))
    overshoot_factor = min(1.0, overshoot / max(delta_pct, 1))
    sustain_bonus = 0.20 if sustained else 0
    confidence = clamp(55 + 25 * mag_factor + 15 * overshoot_factor + 20 * sustain_bonus, 50, 95)

    # 排名幅度：如果提供了原始排名，计算实际排名变化
    rank_magnitude = 0
    if ranks and len(ranks) >= 2:
        rank_magnitude = abs(ranks[-1] - ranks[0])

    return {
        "event": "jump",
        "direction": direction,
        "signal": direction,
        "magnitude": round(mag, 2),
        "overshoot": round(overshoot, 2),
        "delta": delta_pct,
        "sustained": sustained,
        "confidence": round(confidence, 1),
        "eventCount": len(events),
        "surgeCount": surge_count,
        "collapseCount": collapse_count,
        "rankMagnitude": rank_magnitude,
        "events": [{"index": e["index"], "direction": e["direction"],
                     "magnitude": e["magnitude"]} for e in events],
    }


def _confirm_jump(
    jump: dict[str, Any],
    stock: dict[str, Any],
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    """2026-08-17 G4：Jump 价格/量确认（默认生效）。

    排名 Jump 可能来自热榜噪声（无价格/成交配合的假 Jump）。生产枚举来自
    detect_rank_jumps：buy（排名跳跃式上升）需 change ≥ jumpConfirmChangeMin 且
    volumeRatio ≥ jumpConfirmVolumeRatioMin；sell（排名崩塌式下降）需 change ≤
    -jumpConfirmChangeMin 且 volumeRatio ≥ jumpConfirmVolumeRatioMin（放量配合）。
    不满足 → direction 降级 hold 并记录 unconfirmed（fail-visible，不阻断原始事件）。

    2026-09-15 断线修复：确认分支此前只匹配 "up"/"down"，生产枚举 buy/sell 全部落
    else 放行（G4 上线以来从未实际拦截，P6-c 消费面实证 10936 事件全放行）。现按
    生产枚举 buy/sell 匹配，"up"/"down" 保留为语义别名（防测试夹具/历史 fixture
    静默放行）。
    """
    c = config or RankTrendConfig()
    direction = jump.get("direction")
    if not direction or direction == "hold":
        jump = dict(jump)
        jump["confirmed"] = True  # 无方向视为无确认需求（统一输出结构，审计 2026-08-18）
        return jump
    chg = float(stock.get("change")) if _is_finite_number(stock.get("change")) else None
    vr = float(stock.get("volumeRatio")) if _is_finite_number(stock.get("volumeRatio")) else None
    confirm_change = float(getattr(c, "jumpConfirmChangeMin", 3.0))
    confirm_vr = float(getattr(c, "jumpConfirmVolumeRatioMin", 1.0))
    if direction in ("buy", "up"):
        ok = chg is not None and vr is not None and chg >= confirm_change and vr >= confirm_vr
    elif direction in ("sell", "down"):
        ok = chg is not None and vr is not None and chg <= -confirm_change and vr >= confirm_vr
    else:
        ok = True
    if ok:
        jump["confirmed"] = True
        return jump
    jump = dict(jump)
    jump["direction"] = "hold"
    jump["confirmed"] = False
    # 2026-08-19 P0-1：events 内 direction 同步降级——共振用 events 算 freshness、
    # 外层判方向，两处口径必须一致（否则 events 仍报 surge/collapse 与降级矛盾）
    jump["events"] = [
        {"index": e.get("index"), "direction": "hold", "magnitude": e.get("magnitude")}
        for e in jump.get("events", [])
    ]
    jump["unconfirmedReasons"] = [
        f"Jump {direction} 缺价格/量确认（change={chg}%，volumeRatio={vr} vs "
        f"需 ≥{confirm_change if direction in ('buy', 'up') else -confirm_change}% / ≥{confirm_vr}）"
    ]
    return jump


from ..trend.lifecycle import analyze_cycle, cycle_metrics, raw_stage, normalize_stage, cycle_confidence, entry_advice, lifecycle_decision

from ..trend.risk import REGIME_STRONG_SCORE, analyze_risk, market_regime
from ..trend.gate_confirm import GateConfirmState, gate_reason


def _compat_callable(name: str):
    """读取兼容入口上的函数，保留历史 monkeypatch/诊断注入行为。"""
    facade = sys.modules.get("backend.analysis.ranktrend.engine")
    if facade is not None and hasattr(facade, name):
        return getattr(facade, name)
    return globals()[name]

def compose_decision(technical: dict[str, Any], cycle: dict[str, Any], risk: dict[str, Any], config: RankTrendConfig) -> dict[str, Any]:
    def cross_signal(cross: str) -> str:
        return "buy" if cross == "golden" else "sell" if cross == "death" else "hold"

    components = [
        {"signal": technical["signals"]["direction"]["signal"], "rawScore": clamp(technical["signals"]["direction"]["score"], -1, 1), "weight": config.directionWeight},
        {"signal": technical["signals"]["acceleration"]["signal"], "rawScore": clamp(technical["signals"]["acceleration"]["score"], -1, 1), "weight": config.accelerationWeight},
        {"signal": technical["signals"]["zeroCross"]["signal"], "rawScore": clamp(technical["signals"]["zeroCross"]["score"], -1, 1), "weight": config.crossWeight},
        {"signal": cross_signal(technical["macd"]["cross"]), "rawScore": clamp(technical["macd"]["rawScore"], -1, 1), "weight": config.macdWeight},
    ]
    # 阶段 17 MA 交叉因子（观察接线）：maWeight>0 才进决策合成（2026-09-13 阶段 21.8 五因子落默认：
    # 默认 maWeight=0.2 参与，maWeight=0 显式关闭并按比例回填四因子口径）；
    # 旧调用方/测试夹具的 technical 缺 maCross 键按无信号处理（不抛错）。
    if config.maWeight > 0:
        ma_cross = technical.get("maCross") or {}
        components.append(
            {
                "signal": cross_signal(str(ma_cross.get("cross") or "none")),
                "rawScore": clamp(float(ma_cross.get("rawScore") or 0.0), -1, 1),
                "weight": config.maWeight,
            }
        )
    combined = sum(c["rawScore"] * c["weight"] for c in components)
    positive = sum(c["weight"] * max(c["rawScore"], 0) for c in components)
    negative = sum(c["weight"] * max(-c["rawScore"], 0) for c in components)
    buy_count = len([c for c in components if c["signal"] == "buy"])
    sell_count = len([c for c in components if c["signal"] == "sell"])
    base = "hold"
    macd_golden = technical["macd"]["cross"] == "golden"
    # 对齐旧 TS resultComposer：买/卖共识需要至少 2 个明确分量信号
    if buy_count >= config.decisionMinAgreement and sell_count <= config.decisionMaxOpposition and combined >= config.buyScoreThreshold:
        if config.requireMacdGoldenCross and not macd_golden:
            base = "hold"
        else:
            base = "buy"
    elif sell_count >= config.decisionMinAgreement and buy_count <= config.decisionMaxOpposition and combined <= config.sellScoreThreshold:
        base = "sell"
    signed_threshold = config.buyScoreThreshold if base == "buy" else config.sellScoreThreshold if base == "sell" else config.buyScoreThreshold if combined >= 0 else config.sellScoreThreshold
    threshold_scale = max(0.05, abs(signed_threshold))
    score_margin = combined - config.buyScoreThreshold if combined >= 0 else abs(combined) - abs(config.sellScoreThreshold)
    opposing = negative if base == "buy" else positive if base == "sell" else min(positive, negative)
    agreement = clamp(1 - opposing, 0, 1)
    confidence = clamp(config.decisionConfidenceBase + config.decisionConfidenceSlope * abs(combined) + config.decisionAgreementSlope * agreement + config.decisionMarginSlope * math.tanh(abs(combined - signed_threshold) / threshold_scale), config.decisionConfidenceMin, config.decisionConfidenceMax)
    final = base
    final_conf = clamp(confidence - config.decisionRiskPenaltyWeights[0] * risk["overheat"]["severity"] - config.decisionRiskPenaltyWeights[1] * risk["divergence"]["severity"] - config.decisionRiskPenaltyWeights[2] * risk["synergy"], config.decisionConfidenceMin, config.decisionConfidenceMax)
    if base == "buy" and cycle["stage"] == "reversal" and risk["pressure"] >= config.decisionReversalPressureMin and risk["overheat"]["severity"] >= config.decisionReversalOverheatMin and score_margin < config.decisionReversalMarginMax:
        final = "hold"
        final_conf = min(final_conf, config.decisionReversalFinalConfCap)
    return {"base": {"signal": base, "confidence": confidence, "combinedScore": combined, "scoreMargin": score_margin}, "final": {"signal": final, "confidence": final_conf}}


# 生命周期阶段适配度（2026-09-14 参数化：默认值迁移至 config.lifecycleStageFitness，
# expansion/ignition/crowded/cooling/reversal 顺序；本表保留为兼容 fallback，仅展示分面）
_STAGE_FITNESS_ORDER: tuple[str, ...] = ("expansion", "ignition", "crowded", "cooling", "reversal")
STAGE_FITNESS: dict[str, float] = {"expansion": 1.0, "ignition": 0.8, "crowded": 0.35, "cooling": 0.2, "reversal": 0.0}


def _stage_fitness(stage: str, config: RankTrendConfig | None = None) -> float:
    """阶段适配度读值：config.lifecycleStageFitness 优先，长度不符回退 STAGE_FITNESS。"""
    c = config or RankTrendConfig()
    values = list(getattr(c, "lifecycleStageFitness") or [])
    if stage in _STAGE_FITNESS_ORDER and len(values) == 5:
        return float(values[_STAGE_FITNESS_ORDER.index(stage)])
    return STAGE_FITNESS.get(stage, 0.0)


def _tier_as_dict(pair: tuple[str, list[str]]) -> dict[str, Any]:
    """把 (tier, reasons) 转成 signalTier/tierReasons dict，便于 ** 展开进输出。"""
    return {"signalTier": pair[0], "tierReasons": pair[1]}


def _rank_trend_tier_as_dict(base_signal: str, combined: float, config: RankTrendConfig | None = None) -> dict[str, Any]:
    return _tier_as_dict(_rank_trend_tier(base_signal, combined, config))


def _lifecycle_tier_as_dict(stage: str, action: str) -> dict[str, Any]:
    return _tier_as_dict(_lifecycle_tier(stage, action))


def _rank_trend_tier(base_signal: str, combined: float, config: RankTrendConfig | None = None) -> tuple[str, list[str]]:
    """趋势离散档位（signalTier）。规则见 docs §6.2。阈值读 config.tierRankTrend*。"""
    c = config or RankTrendConfig()
    if base_signal == "hold":
        return "C", ["中性"]
    if base_signal == "sell":
        return "D", ["趋势转弱/反向"]
    a = abs(combined)
    if a >= c.tierRankTrendStrongMin:
        return "S", ["强趋势，加权强度远超阈值"]
    if a >= c.tierRankTrendConfirmMin:
        return "A", ["趋势确认"]
    return "B", ["弱趋势，勉强越过阈值"]


def _lifecycle_tier(stage: str, action: str) -> tuple[str, list[str]]:
    """周期离散档位（signalTier）。规则见 docs §6.4。"""
    if action == "veto":
        return "E", ["生命周期一票否决"]
    if action == "allow" and stage in ("ignition", "expansion"):
        return "A", ["优选路径"]
    if action == "caution" and stage in ("ignition", "expansion"):
        return "B", ["低可见度点火/假突破，谨慎观察"]
    if action == "exit_watch":
        return "D", ["拥挤，退出观察"]
    if stage == "cooling":
        return "D", ["冷却，回避"]
    return "C", ["中性"]


def compose_observation_scores(input: dict[str, Any], config: RankTrendConfig | None = None) -> dict[str, Any]:
    """生命周期机会成熟度（对齐 TS observationScoreComposer）。

    score = 0.35 * stageFitness + 0.25 * pathCommitment + 0.2 * momentumConfirmation + 0.2 * riskSafety
    veto 不清零实际成熟度，只保留警示与原因。
    """
    c = config or RankTrendConfig()
    momentum = input["technical"]["momentumProfile"]
    cycle = input["cycle"]
    risk = input["risk"]
    base = input["decision"]["base"]
    signed_score = clamp(float(base.get("combinedScore") or 0), -1, 1)
    momentum_confirmation = (
        c.lifecycleMomentumWeights[0] * clamp(float(momentum.get("short") or 0) / c.lifecycleMomentumScales[0], 0, 1)
        + c.lifecycleMomentumWeights[1] * clamp(float(momentum.get("mid") or 0) / c.lifecycleMomentumScales[1], 0, 1)
        + c.lifecycleMomentumWeights[2] * clamp(float(momentum.get("acceleration") or 0) / c.lifecycleMomentumScales[2], 0, 1)
    )
    factors = {
        "stageFitness": _stage_fitness(str(cycle["stage"]), c),
        "pathCommitment": clamp(float(cycle.get("metrics", {}).get("rankPathCommitment") or 0), 0, 1),
        "momentumConfirmation": clamp(momentum_confirmation, 0, 1),
        "riskSafety": 1 - clamp(float(risk.get("pressure") or 0), 0, 1),
    }
    lifecycle_score = (
        c.lifecycleWeights[0] * factors["stageFitness"]
        + c.lifecycleWeights[1] * factors["pathCommitment"]
        + c.lifecycleWeights[2] * factors["momentumConfirmation"]
        + c.lifecycleWeights[3] * factors["riskSafety"]
    )
    lifecycle_reasons = cycle.get("decision", {}).get("reasons")
    return {
        "rankTrend": {
            "direction": str(base.get("signal") or "hold"),
            "score": round(abs(signed_score) * 100),
            "signedScore": signed_score,
            **_rank_trend_tier_as_dict(str(base.get("signal") or "hold"), signed_score, config),
        },
        "lifecycle": {
            "stage": cycle["stage"],
            "score": round(clamp(lifecycle_score, 0, 1) * 100),
            "veto": cycle.get("decision", {}).get("action") == "veto",
            "reasons": list(lifecycle_reasons) if isinstance(lifecycle_reasons, list) else [],
            "factors": factors,
            **_lifecycle_tier_as_dict(cycle["stage"], str(cycle.get("decision", {}).get("action") or "caution")),
        },
    }


def compose_strategy(
    technical: dict[str, Any],
    cycle: dict[str, Any],
    risk: dict[str, Any],
    hotlist: dict[str, Any] | None = None,
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    momentum = technical["momentumProfile"]
    stage = cycle["stage"]
    c = config or RankTrendConfig()
    # 阶段 17 MA 交叉因子：maCrossTrendBuy=True 时 MA 金叉进 trend_buy OR 链（默认 False=关闭）；
    # config 直接属性访问（与 compose_analysis_candidate_tier 的 c.maCrossTrendBuy 同风格），
    # config=None 由上一行兜底为默认配置。
    ma_golden = bool(c.maCrossTrendBuy) and (technical.get("maCross") or {}).get("cross") == "golden"
    trend_buy = technical["signals"]["direction"]["signal"] == "buy" or technical["signals"]["acceleration"]["signal"] == "buy" or technical["macd"]["cross"] == "golden" or ma_golden
    hotlist_missing = not isinstance(hotlist, dict)
    hotlist_stage = str((hotlist or {}).get("stage") or "") if not hotlist_missing else ""
    hotlist_risk = str((hotlist or {}).get("riskLevel") or "") if not hotlist_missing else ""
    hotlist_state = {
        "state": "missing" if hotlist_missing else "present",
        "stage": hotlist_stage or None,
        "riskLevel": hotlist_risk or None,
        "confidence": (hotlist or {}).get("confidence") if not hotlist_missing else None,
    }
    tier = "N_NEUTRAL"
    reasons: list[str] = []
    lifecycle_decision_data = cycle.get("decision") or {}
    lifecycle_action = str((lifecycle_decision_data.get("action") or ""))
    lifecycle_reasons = lifecycle_decision_data.get("reasons") if isinstance(lifecycle_decision_data.get("reasons"), list) else []
    lifecycle_low_visibility_ignition = lifecycle_action == "caution" and any(
        "低可见度" in str(reason) for reason in lifecycle_reasons
    )

    if hotlist_stage in ("退潮", "冰点"):
        if momentum["short"] <= c.tierExitRiskShortMomentumMax or momentum["acceleration"] <= c.tierExitRiskAccelMax or risk["pressure"] >= c.tierExitRiskPressureMin:
            tier = "D_EXIT_RISK"
            reasons.append(f"热榜{hotlist_stage}期，动量衰减触发退出风险")
        else:
            reasons.append(f"热榜{hotlist_stage}期，暂停入场")
        reasons.append(f"热榜情绪: {hotlist_stage}(风险{hotlist_risk or '未知'})")
        action = {"D_EXIT_RISK": "exit_watch"}.get(tier, "hold")
        return {"hotlist": hotlist_state, "momentum": momentum, "candidateTier": tier, "action": action, "reasons": reasons}

    allow_a_main = hotlist_missing or (hotlist_stage in ("高潮", "发酵") and hotlist_risk != "高")
    allow_b_ignition = hotlist_missing or hotlist_stage in ("高潮", "发酵", "启动")

    if lifecycle_action == "veto":
        reasons.append("生命周期辅助决策一票否决，阻止进入 A/B 候选池")
    elif stage in ("reversal", "cooling") and (momentum["short"] <= c.tierExitRiskShortMomentumMax or momentum["acceleration"] <= c.tierExitRiskAccelMax or risk["pressure"] >= c.tierExitRiskPressureMin):
        tier = "D_EXIT_RISK"
        reasons.append("生命周期进入反转/冷却，短周期动量或风险压力转弱")
    elif stage == "crowded" or (momentum["long"] >= c.tierCrowdedLongMomentumMin and (momentum["acceleration"] <= c.tierCrowdedAccelMax or risk["pressure"] >= c.tierCrowdedRiskPressureMin)):
        tier = "C_CROWDED"
        reasons.append("长周期热度高位停留，追高性价比下降")
    elif stage == "expansion" and momentum["mid"] >= c.tierAMainMidMomentumMin and momentum["short"] >= c.tierAMainShortMomentumMin and trend_buy and allow_a_main and risk["divergence"]["severity"] < c.tierAMainDivergenceSeverityMax:
        tier = "A_MAIN"
        reasons.append("扩散阶段中周期动量确认，热榜情绪支持A_MAIN入场")
    elif stage == "ignition" and momentum["short"] >= c.tierBIgnitionShortMomentumMin and momentum["acceleration"] >= c.tierBIgnitionAccelMin and allow_b_ignition and risk["pressure"] < c.tierBIgnitionRiskPressureMax:
        tier = "B_IGNITION"
        reasons.append("点火阶段短周期冲击增强，热榜情绪支持B_IGNITION")
        if lifecycle_low_visibility_ignition:
            reasons.append("生命周期B低可见度点火诊断生效，B_IGNITION保留候选但排序降权")
    elif hotlist_stage == "启动" and stage == "expansion" and trend_buy:
        reasons.append("热榜启动期，A_MAIN暂缓，等待扩散确认")
    elif hotlist_risk == "高" and trend_buy:
        reasons.append("热榜情绪高风险，买入信号降级为观察")
    else:
        reasons.append("动量、阶段与风险未形成明确候选池信号")
    if hotlist_missing:
        reasons.append("热榜情绪缺失，按中性处理")
    elif hotlist_stage:
        reasons.append(f"热榜情绪: {hotlist_stage}(风险{hotlist_risk or '未知'})")
    if risk["divergence"]["severity"] >= c.strategyDivergenceReasonMin:
        reasons.append("注意力与资金存在背离")
    if risk["overheat"]["severity"] >= c.strategyOverheatReasonMin:
        reasons.append("过热压力较高")
    reasons.append(f"动量结构 短{momentum['short']:+.1f} 中{momentum['mid']:+.1f} 长{momentum['long']:+.1f} 加速度{momentum['acceleration']:+.1f}")
    # 阶段6 业务口径（用户决策 2026-08-15）：A_MAIN 高位出货不作为买点，
    # 降级为观察档（action=watch，不参与默认策略入场投票）；对照组策略可显式启用。
    action = {"A_MAIN": "watch", "B_IGNITION": "watch", "C_CROWDED": "avoid", "D_EXIT_RISK": "exit_watch"}.get(tier, "hold")
    return {"hotlist": hotlist_state, "momentum": momentum, "candidateTier": tier, "action": action, "reasons": reasons}


RESONANCE_SHORT_WINDOW_BARS = 3
RESONANCE_MID_WINDOW_BARS = 8
RESONANCE_PATH_WINDOW_BARS = 8
RESONANCE_MIN_SERIES_POINTS = RESONANCE_MID_WINDOW_BARS + 1
RESONANCE_MIN_MARKET_SAMPLE_COUNT = 20


def _positive(value: float) -> float:
    return max(0.0, value)


def _resonance_label(score: float, config: RankTrendConfig | None = None) -> str:
    """共振分数标签（展示面）。阈值 2026-09-14 参数化（config.resonanceLabelThresholds）。"""
    c = config or RankTrendConfig()
    thresholds = list(getattr(c, "resonanceLabelThresholds") or [])
    if len(thresholds) == 4:
        if score >= thresholds[0]:
            return "非常强"
        if score >= thresholds[1]:
            return "强"
        if score >= thresholds[2]:
            return "中等"
        if score >= thresholds[3]:
            return "较弱"
        return "非常弱"
    if score >= 85:
        return "非常强"
    if score >= 67:
        return "强"
    if score >= 50:
        return "中等"
    if score >= 27:
        return "较弱"
    return "非常弱"


def _resonance_tier(
    direction: str,
    persistence: float,
    jump_event: str,
    jump_freshness: float,
    reversal_penalty: float,
    config: RankTrendConfig | None = None,
) -> tuple[str, list[str]]:
    """共振离散档位（signalTier）：S/A/B/C/D。规则见 docs/ranktrend-observation-discrete-tiers-design.md §6.1。阈值读 config.tierResonance*。"""
    c = config or RankTrendConfig()
    if reversal_penalty >= c.tierResonanceReversalPenaltyMin:
        return "D", [f"反转惩罚高 {round(reversal_penalty * 100)}%"]
    if jump_event == "jump" and direction == "buy" and jump_freshness >= c.tierResonanceJumpFreshnessMin:
        return "S", ["Jump 事件驱动，排名跳跃式上升"]
    if direction == "buy" and persistence >= c.tierResonancePersistenceMin:
        return "A", ["方向确认 + 路径持续"]
    if direction == "buy":
        return "B", ["方向确认但路径持续不足"]
    if direction == "hold":
        return "C", ["中性"]
    return "D", ["共振衰竭/反向"]


def _resonance_insufficient(
    reason: str,
    market_median_short_change: float,
    market_sample_count: int = 0,
    market_median_percentile: float | None = None,
) -> dict[str, Any]:
    return {
        "status": "insufficient",
        "direction": "hold",
        "score": 0,
        "label": "样本不足",
        "relativeMomentum": 0,
        "acceleration": 0,
        "persistence": 0,
        "jumpFreshness": 0,
        "reversalPenalty": 0,
        "historyState": "established",
        "marketMedianShortChange": (
            None
            if market_median_short_change is None or not math.isfinite(market_median_short_change)
            else market_median_short_change
        ),
        "marketSampleCount": market_sample_count,
        "marketMedianPercentile": market_median_percentile,
        "reasons": [reason],
        "signalTier": "unknown",
        "tierReasons": [reason],
    }


def analyze_rank_resonance(input: dict[str, Any], config: RankTrendConfig | None = None) -> dict[str, Any]:
    """共振强度（移植 TS resonanceAnalyzer）：相对动量/加速度/持续性/Jump 新鲜度/反转惩罚。"""
    c = config or RankTrendConfig()
    percentiles = [float(p) for p in (input.get("percentiles") or [])]
    market_median_short_change = float(input.get("marketMedianShortChange") or 0)
    # JSON 安全（fail-visible）：横截面无效（NaN）时输出 None，不序列化崩溃、不伪造 0；
    # 内部 isfinite 判断仍用原始 NaN。
    _short_change_json = None if not math.isfinite(market_median_short_change) else market_median_short_change
    market_sample_count = int(input.get("marketSampleCount") or 0)
    market_median_percentile = input.get("marketMedianPercentile")
    jump = input.get("jump") or {}
    entry = input.get("entry") or {}
    sample_quality = input.get("sampleQuality") or {}
    is_new_entry = entry.get("isNew") is True
    current_attention_percentile = float(entry.get("currentAttentionPercentile") or 0)

    if sample_quality.get("timelineValid") is False:
        return _resonance_insufficient(
            "快照时间轴不完整", market_median_short_change, market_sample_count, market_median_percentile
        )
    if is_new_entry:
        if not math.isfinite(current_attention_percentile):
            return _resonance_insufficient(
                "新入榜关注度无效", market_median_short_change, market_sample_count, market_median_percentile
            )
        if not math.isfinite(market_median_short_change) or market_sample_count < c.resonanceMinMarketSampleCount:
            return _resonance_insufficient(
                "横截面有效样本不足", market_median_short_change, market_sample_count, market_median_percentile
            )
        jump_events = jump.get("events") or []
        jump_freshness = 1.0 if jump_events else 0.0
        entry_strength = clamp((current_attention_percentile - 50) / c.resonanceEntryStrengthScale, 0, 1)
        score = round(100 * clamp(c.resonanceNewEntryWeights[0] * entry_strength + c.resonanceNewEntryWeights[1] * jump_freshness, 0, 1))
        if jump_freshness >= c.tierResonanceJumpFreshnessMin and entry_strength > 0:
            _tier, _tier_reasons = "S", ["Jump 事件驱动，排名跳跃式上升"]
        elif entry_strength >= c.tierResonanceEntryStrengthMin:
            _tier, _tier_reasons = "A", ["新入榜关注度较强"]
        elif entry_strength > 0:
            _tier, _tier_reasons = "B", ["新入榜关注度较弱"]
        else:
            _tier, _tier_reasons = "C", ["新入榜关注度中性"]
        return {
            "status": "ok",
            "direction": "buy" if entry_strength > 0 else "hold",
            "score": score,
            "label": _resonance_label(score, c),
            "relativeMomentum": entry_strength,
            "acceleration": 0,
            "persistence": 0,
            "jumpFreshness": jump_freshness,
            "reversalPenalty": 0,
            "historyState": "new_entry",
            "marketMedianShortChange": _short_change_json,
            "marketSampleCount": market_sample_count,
            "marketMedianPercentile": market_median_percentile,
            "reasons": [f"新入榜关注度 {round(current_attention_percentile)}"],
            "signalTier": _tier,
            "tierReasons": _tier_reasons,
        }
    if len(percentiles) < c.resonanceMidWindowBars + 1 or any(not math.isfinite(p) for p in percentiles):
        return _resonance_insufficient(
            "排名序列不足或无效", market_median_short_change, market_sample_count, market_median_percentile
        )
    if sample_quality.get("status") == "insufficient":
        return _resonance_insufficient(
            "快照样本不足", market_median_short_change, market_sample_count, market_median_percentile
        )
    if not math.isfinite(market_median_short_change) or market_sample_count < c.resonanceMinMarketSampleCount:
        return _resonance_insufficient(
            "横截面有效样本不足", market_median_short_change, market_sample_count, market_median_percentile
        )

    last_index = len(percentiles) - 1
    short_start_index = last_index - c.resonanceShortWindowBars
    mid_start_index = last_index - c.resonanceMidWindowBars
    short_bars = last_index - short_start_index
    mid_bars = last_index - mid_start_index
    short_change = percentiles[last_index] - percentiles[short_start_index]
    mid_change = percentiles[last_index] - percentiles[mid_start_index]
    relative_momentum = clamp((short_change - market_median_short_change) / c.resonanceMomentumScale, -1, 1)
    acceleration = clamp((short_change - (mid_change * short_bars) / mid_bars) / c.resonanceAccelerationScale, -1, 1)

    path_percentiles = percentiles[-(c.resonancePathWindowBars + 1):]
    changes = [path_percentiles[i + 1] - path_percentiles[i] for i in range(len(path_percentiles) - 1)]
    path_direction = 1 if (short_change or mid_change) > 0 else -1 if (short_change or mid_change) < 0 else 0
    directional_changes = [
        value for value in changes
        if path_direction != 0 and (1 if value > 0 else -1 if value < 0 else 0) == path_direction
    ]
    persistence = len(directional_changes) / len(changes) if changes else 0
    if len(changes) > 1:
        direction_switch_rate = sum(
            1 for i in range(1, len(changes))
            if math.copysign(1, changes[i]) != 0 and math.copysign(1, changes[i - 1]) != 0
            and math.copysign(1, changes[i]) != math.copysign(1, changes[i - 1])
        ) / (len(changes) - 1)
    else:
        direction_switch_rate = 0
    recent_peak = max(path_percentiles)
    percentile_drawdown = max(0, recent_peak - percentiles[last_index])
    reversal_penalty = clamp(c.resonanceReversalSwitchWeight * direction_switch_rate + c.resonanceReversalDrawdownWeight * percentile_drawdown / c.resonanceReversalDrawdownScale, 0, 1)

    jump_events = jump.get("events") or []
    latest_event = jump_events[-1] if jump_events else None
    jump_freshness = math.exp(-(last_index - int(latest_event["index"])) / c.resonanceJumpFreshnessDecay) if latest_event else 0
    direction_score = relative_momentum + acceleration + c.resonancePathDirectionWeight * path_direction * persistence
    base_direction = "buy" if direction_score > c.resonanceDirectionThreshold else "sell" if direction_score < -c.resonanceDirectionThreshold else "hold"
    has_reverse_jump = (
        (base_direction == "buy" and jump.get("direction") == "sell")
        or (base_direction == "sell" and jump.get("direction") == "buy")
    )
    direction = jump.get("direction") if jump.get("event") == "jump" and has_reverse_jump else base_direction

    directional_momentum = -relative_momentum if direction == "sell" else relative_momentum
    directional_acceleration = -acceleration if direction == "sell" else acceleration
    raw_score = (
        c.resonanceWeights[0] * _positive(directional_momentum)
        + c.resonanceWeights[1] * _positive(directional_acceleration)
        + c.resonanceWeights[2] * persistence
        + c.resonanceWeights[3] * jump_freshness
        - c.resonanceWeights[4] * reversal_penalty
    )
    score = round(100 * clamp(raw_score, 0, 1))
    _tier, _tier_reasons = _resonance_tier(direction, persistence, jump.get("event"), jump_freshness, reversal_penalty, config)
    return {
        "status": "ok",
        "direction": direction,
        "score": score,
        "label": _resonance_label(score, c),
        "relativeMomentum": round(relative_momentum, 6),
        "acceleration": round(acceleration, 6),
        "persistence": round(persistence, 6),
        "jumpFreshness": round(jump_freshness, 6),
        "reversalPenalty": round(reversal_penalty, 6),
        "historyState": "established",
        "marketMedianShortChange": _short_change_json,
        "marketSampleCount": market_sample_count,
        "marketMedianPercentile": market_median_percentile,
        "reasons": [
            f"相对动量 {round(relative_momentum * 100)}",
            f"加速度 {round(acceleration * 100)}",
            f"路径持续性 {round(persistence * 100)}%",
        ],
        "signalTier": _tier,
        "tierReasons": _tier_reasons,
    }


def analyze_cycle_with_risk(
    cycle: dict[str, Any],
    risk: dict[str, Any],
    momentum: dict[str, Any] | None = None,
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    updated_cycle = dict(cycle)
    updated_cycle["decision"] = lifecycle_decision(
        str(cycle.get("rawStage") or cycle.get("stage") or "cooling"),
        str(cycle.get("stage") or "cooling"),
        str(cycle.get("transition") or cycle.get("stage") or "cooling"),
        float(cycle.get("confidence") or 50),
        cycle.get("metrics") if isinstance(cycle.get("metrics"), dict) else {},
        risk,
        momentum,
        config=config,
    )
    return updated_cycle


def compose_analysis_candidate_tier(
    technical: dict[str, Any],
    cycle: dict[str, Any],
    risk: dict[str, Any],
    regime: dict[str, Any] | None = None,
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    c = config or RankTrendConfig()
    momentum = technical["momentumProfile"]
    stage = cycle["stage"]
    reasons: list[str] = []
    money_risk = risk["divergence"]["severity"]
    pressure = risk["pressure"]
    regime_data = regime or {"state": "normal", "score": 0, "reasons": []}
    # 2026-08-18 环境门数据修正（regime × candidateTier h1 验证）：
    # strong 市场 A_MAIN synA exAcc -0.0739 / B_IGNITION -0.0172（普涨无区分度+追高）→ 禁 A/B；
    # weak 市场 B_IGNITION +0.077（弱市点火更稀缺）→ 放开（原 not weak_market 规则与数据相反）；
    # retreat 样本少，风控保留禁入。regimeGateStrongBan=False 可回退旧规则（weak/retreat 禁）。
    strong_market = regime_data["state"] == "strong"
    retreat_market = regime_data["state"] == "retreat"
    gate_strong_ban = bool(getattr(c, "regimeGateStrongBan", True))
    # 2026-08-19 方向 C：A/B 分层禁（banStrongA/banStrongB），regimeGateStrongBan 兼容旧开关
    ban_a_main = (
        ((strong_market and bool(getattr(c, "banStrongA", True))) or retreat_market)
        if gate_strong_ban
        else retreat_market or regime_data["state"] == "weak"
    )
    ban_b_ignition = (
        ((strong_market and bool(getattr(c, "banStrongB", True))) or retreat_market)
        if gate_strong_ban
        else regime_data["state"] == "retreat"
    )
    # 阶段 17 MA 交叉因子：maCrossTrendBuy=True 时 MA 金叉进 trend_buy OR 链（默认 False=关闭）；
    # 旧调用方/测试夹具的 technical 缺 maCross 键按无信号处理（不抛错）。
    ma_golden = bool(c.maCrossTrendBuy) and (technical.get("maCross") or {}).get("cross") == "golden"
    trend_buy = (
        technical["signals"]["direction"]["signal"] == "buy"
        or technical["signals"]["acceleration"]["signal"] == "buy"
        or technical["macd"]["cross"] == "golden"
        or ma_golden
    )
    tier = "N_NEUTRAL"
    lifecycle_decision_data = cycle.get("decision") or {}

    if lifecycle_decision_data.get("action") == "veto":
        reasons.append("生命周期辅助决策一票否决，阻止进入 A/B 候选池")
    elif stage in ("reversal", "cooling") and (
        momentum["short"] <= c.tierExitRiskShortMomentumMax or momentum["acceleration"] <= c.tierExitRiskAccelMax or pressure >= c.tierExitRiskPressureMin
    ):
        tier = "D_EXIT_RISK"
        reasons.append("生命周期进入反转/冷却，短周期动量或风险压力转弱")
    elif stage == "crowded" or (
        momentum["long"] >= c.tierCrowdedLongMomentumMin and (momentum["acceleration"] <= c.tierCrowdedAccelMax or pressure >= c.tierCrowdedRiskPressureMin)
    ):
        tier = "C_CROWDED"
        reasons.append("长周期热度高位停留，追高性价比下降")
    elif (
        stage == "expansion"
        and momentum["mid"] >= c.tierAMainMidMomentumMin
        and momentum["short"] >= c.tierAMainShortMomentumMin
        and trend_buy
        and not ban_a_main
        and money_risk < c.tierAMainDivergenceSeverityMax
    ):
        tier = "A_MAIN"
        reasons.append("扩散阶段中周期动量确认，技术信号保持正向")
    elif (
        stage == "ignition"
        and momentum["short"] >= c.tierBIgnitionShortMomentumMin
        and momentum["acceleration"] >= c.tierBIgnitionAccelMin
        and not ban_b_ignition
        and pressure < c.tierBIgnitionRiskPressureMax
    ):
        tier = "B_IGNITION"
        reasons.append("点火阶段短周期冲击增强，仍需继续确认")
    elif (regime_data["state"] in ("strong", "retreat")) and trend_buy:
        reasons.append("市场强/退潮环境买入信号降级为观察（数据：strong 下 A/B 档负贡献）")
    else:
        reasons.append("动量、阶段与风险未形成明确候选池信号")

    if regime_data["state"] == "strong":
        reasons.append("市场环境强，允许跟踪点火/扩散机会")
    if regime_data["state"] == "retreat":
        reasons.append("市场退潮，优先控制回撤风险")
    if risk["divergence"]["severity"] >= c.strategyDivergenceReasonMin:
        reasons.append("注意力与资金存在背离")
    if risk["overheat"]["severity"] >= c.strategyOverheatReasonMin:
        reasons.append("过热压力较高")
    reasons.append(
        f"动量结构 短{momentum['short']:+.1f} 中{momentum['mid']:+.1f} 长{momentum['long']:+.1f} 加速度{momentum['acceleration']:+.1f}"
    )
    # 阶段6 业务口径（用户决策 2026-08-15）：A_MAIN 高位出货不作为买点，
    # 降级为观察档（action=watch，不参与默认策略入场投票）；对照组策略可显式启用。
    action = {"A_MAIN": "watch", "B_IGNITION": "watch", "C_CROWDED": "avoid", "D_EXIT_RISK": "exit_watch"}.get(tier, "hold")
    return {
        "regime": regime_data,
        "momentum": momentum,
        "candidateTier": tier,
        "action": action,
        "reasons": reasons,
    }


class RankTrendPythonEngine:
    def __init__(
        self,
        config: RankTrendConfig | None = None,
        sentiment_provider: Callable[[str], dict[str, Any] | None] | None = None,
    ):
        self.config = config or RankTrendConfig()
        self._stock_lookup: list[dict[str, dict[str, Any]]] = []
        # hotlist-sentiment 补全依赖注入：(trading_date) -> doc | None；None 时跳过补全
        self._sentiment_provider = sentiment_provider

    def replay(
        self,
        frames: list[dict[str, Any]],
        warmup_count: int | None = None,
        window_size: int = 50,
        meta: dict[str, Any] | None = None,
        codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        meta = meta or {}
        if self._candidate_tier_mode(meta) == "execution":
            self._ensure_hotlist_sentiment(frames, meta)
        self._stock_lookup = self._build_stock_lookup(frames)
        # 趋势反转层（阶段6）：snapshotId → 帧索引，供 trend_reversal_of 取历史 percentile
        self._index_by_snapshot = {str(frame.get("snapshotId")): i for i, frame in enumerate(frames)}
        # ATR 波动观察（2026-08-17）：个股跨帧 bar 累积（断档重置/截断，见 _build_signal assemble 分支）
        self._atr_meta_by_code: dict[str, dict[str, Any]] = {}
        # WP2a：本次 replay 独占确认状态（两次 replay 互不污染）；帧循环无提前 return，
        # 出口对称复位等价 try/finally（避免整段重排）
        self._gate_confirm_state = GateConfirmState(
            required_frames=int(getattr(self.config, "lifecycleConfirmFrames", 1))
        )
        self._gate_confirm_ctx = {"active": True}
        # WP2b：regime 平滑状态随 replay 重置（与确认状态同批；实例由 _smooth_regime 惰性创建）
        _smoother = getattr(self, "_regime_smoother", None)
        if _smoother is not None:
            _smoother.reset()
        min_count = warmup_count or get_technical_min_samples(self.config)
        start = min_count - 1 if len(frames) >= min_count else 0
        requested_codes = {str(code) for code in codes} if codes else None
        histories = defaultdict(deque)
        change_histories: dict[str, deque] = defaultdict(deque)
        amount_histories: dict[str, deque] = defaultdict(deque)
        prev_candidate_by_code: dict[str, str] = {}
        signals: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            history_start = max(0, index - window_size + 1)
            for history in histories.values():
                while history and history[0][0] < history_start:
                    history.popleft()
            for chg_history in change_histories.values():
                while chg_history and chg_history[0][0] < history_start:
                    chg_history.popleft()
            for amt_history in amount_histories.values():
                while amt_history and amt_history[0][0] < history_start:
                    amt_history.popleft()

            stocks = frame.get("stocks", [])
            # 池子大小 = 全池股票数（综合排名口径，用于 regime/展示）
            # 趋势因子百分位 = avgRankNum attention 重排后的序号（有效子集内）
            attention_ranks, attention_total = attention_rank_lookup(stocks)
            seen_codes: set[str] = set()
            for stock in stocks:
                code = str(stock.get("code") or "")
                if not code or code in seen_codes:
                    continue
                seen_codes.add(code)
                rank = attention_ranks.get(code)
                if rank is None:
                    continue
                histories[code].append((index, rank, percentile_rank(rank, attention_total)))
                chg = stock.get("change")
                change_histories[code].append((index, chg if chg is not None else None))
                amt = stock.get("amount")
                amount_histories[code].append((index, amt if amt is not None else None))

            if index < start:
                continue

            # WP2b：regime 输出经平滑包装（默认参数原样返回同一 dict，零行为变化）
            regime = self._smooth_regime(market_regime(frame, self.config))
            # 阶段 3 修复方向 1：每帧一次性计算横截面市场上下文（与 API 链路同口径），
            # 供 _build_signal 补共振维参与 synergy 投票；窗口不足/样本不足时如实为 None（fail-visible）。
            market_median, market_sample_count = frame_market_median(frames, index)
            market_ctx = {
                "marketMedianShortChange": market_median,
                "marketSampleCount": market_sample_count,
                "marketMedianPercentile": frame_market_median_percentile(frame),
            }
            for stock in stocks:
                code = str(stock.get("code") or "")
                if requested_codes is not None and code not in requested_codes:
                    continue
                series = histories.get(code)
                if not series:
                    continue
                signal = self._build_signal(
                    stock,
                    frame,
                    [item[1] for item in series],
                    [item[2] for item in series],
                    regime,
                    meta,
                    market_ctx=market_ctx,
                    price_changes=[item[1] for item in change_histories.get(code, [])],
                    amount_history=[item[1] for item in amount_histories.get(code, [])],
                )
                if signal:
                    # 阶段6 趋势反转层（RankTrend 分析方法本体，观察信号）：
                    # 默认 rank_cross：低分位 + 此前下行 + 当前回升 → 标记 trendReversal；
                    # reversalMode="tier_shift"（用户立项 2026-08-16）：前一帧 D_EXIT_RISK →
                    # 当前 B_IGNITION/A_MAIN 档位转向（研究实证 h8 winRate 0.53 > 排名拐点 0.49）。
                    # 延迟 import 避免 engine ↔ trend_reversal 循环依赖。
                    from backend.analysis.ranktrend.trend.trend_reversal import (
                        tier_shift_reversal_of,
                        trend_reversal_of,
                    )

                    reversal_mode = str(meta.get("reversalMode") or "rank_cross")
                    if reversal_mode == "tier_shift":
                        signal["rankTrend"]["trendReversal"] = tier_shift_reversal_of(
                            signal, prev_candidate_by_code.get(code)
                        )
                    else:
                        signal["rankTrend"]["trendReversal"] = trend_reversal_of(
                            signal, self._index_by_snapshot, self._stock_lookup
                        )
                    prev_candidate_by_code[code] = signal.get("candidateTier")
                    signals.append(signal)
        # WP2a：replay 出口对称复位（上下文不跨请求存活）
        self._gate_confirm_ctx = {"active": False}
        return signals

    @staticmethod
    def _candidate_tier_mode(meta: dict[str, Any]) -> str:
        return str(meta.get("candidateTierMode") or meta.get("candidate_tier_mode") or "analysis")

    def _ensure_hotlist_sentiment(self, frames: list[dict[str, Any]], meta: dict[str, Any]) -> None:
        missing_frames = [frame for frame in frames if "hotlistSentiment" not in frame]
        if not missing_frames:
            return

        provider = self._sentiment_provider
        if provider is None:
            # 未注入 provider 时跳过补全（不报错、不写字段）
            return
        try:
            # as-of 时点注入（WP1c）：逐帧按 (tradingDate, slotTime) 取 ≤ 帧时点的最新情绪，
            # 同日不同帧可注入不同文档；无当日文档回退前日 EOD（stale），不再按日共享同一 doc。
            for frame in missing_frames:
                trading_date = str(frame.get("tradingDate") or "")
                slot_time = str(frame.get("slotTime") or "") or None
                if not trading_date:
                    frame["hotlistSentiment"] = None
                    frame["hotlistSentimentStatus"] = "missing"
                    continue
                doc, status = provider(trading_date, slot_time)
                frame["hotlistSentiment"] = doc
                frame["hotlistSentimentStatus"] = status if doc else "missing"
        except Exception as exc:
            reason = f"MongoDB hotlist sentiment unavailable: {exc}"
            for frame in missing_frames:
                frame["hotlistSentiment"] = None
                frame["hotlistSentimentStatus"] = "missing"
                frame["hotlistSentimentReason"] = reason

    def _smooth_regime(self, regime: dict[str, Any]) -> dict[str, Any]:
        """WP2b：replay 帧循环的 regime 平滑挂载点（默认参数直通返回同一 dict，零行为变化）。

        仅 replay 帧循环挂载；单帧 replay_frame_at / API 单股链路保持 market_regime 直通
        （无确认上下文的轻量链路，与 WP2a 单股直通边界一致）。
        """
        smoother = getattr(self, "_regime_smoother", None)
        if smoother is None:
            from backend.analysis.ranktrend.trend.regime_smoother import RegimeSmoother

            smoother = RegimeSmoother(
                alpha=float(getattr(self.config, "regimeScoreEmaAlpha", 1.0)),
                hysteresis=bool(getattr(self.config, "regimeStateHysteresis", False)),
                strong_enter=float(getattr(self.config, "regimeStrongScore", REGIME_STRONG_SCORE)),
                strong_exit_band=float(getattr(self.config, "regimeStrongHysteresisBand", 5.0)),
            )
            self._regime_smoother = smoother
        return smoother.smooth(regime)

    def replay_frame_at(self, frames: list[dict[str, Any]], index: int, window_size: int = 50, meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        frame = frames[index]
        # ATR 流式路径（2026-08-17）：重建帧索引保证断档判断正确；_atr_meta_by_code 跨调用累积，
        # 由调用方保证 frames 序列一致（混用 replay/replay_frame_at 时需自行隔离状态）
        self._index_by_snapshot = {str(f.get("snapshotId")): i for i, f in enumerate(frames)}
        history_start = max(0, index - window_size + 1)
        history = frames[history_start: index + 1]
        regime = market_regime(frame, self.config)
        output = []
        for stock in frame.get("stocks", []):
            signal = self._replay_stock(stock, frame, history, history_start, regime, meta or {})
            if signal:
                output.append(signal)
        return output

    def _replay_stock(self, stock: dict[str, Any], frame: dict[str, Any], history: list[dict[str, Any]], history_start: int, regime: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any] | None:
        ranks: list[float] = []
        percentiles: list[float] = []
        price_changes: list[Any] = []
        amount_history: list[Any] = []
        code = str(stock.get("code") or "")
        for offset, historical in enumerate(history):
            lookup_index = history_start + offset
            row = self._stock_lookup[lookup_index].get(code) if lookup_index < len(self._stock_lookup) else self._find_stock(historical, code)
            if not row:
                continue
            attention_ranks, attention_total = attention_rank_lookup(historical.get("stocks") or [])
            rank = attention_ranks.get(code)
            if rank is None:
                continue
            ranks.append(rank)
            percentiles.append(percentile_rank(rank, attention_total))
            price_changes.append(row.get("change"))
            amount_history.append(row.get("amount"))
        return self._build_signal(
            stock,
            frame,
            ranks,
            percentiles,
            regime,
            meta,
            price_changes=price_changes,
            amount_history=amount_history,
        )

    def _build_signal(
        self,
        stock: dict[str, Any],
        frame: dict[str, Any],
        ranks: list[float],
        percentiles: list[float],
        regime: dict[str, Any],
        meta: dict[str, Any],
        assemble: bool = True,
        market_ctx: dict[str, Any] | None = None,
        price_changes: list[Any] | None = None,
        amount_history: list[Any] | None = None,
        atr_history: list[Any] | None = None,
        cross_section_percentiles: list[float] | None = None,
    ) -> dict[str, Any] | None:
        """cross_section_percentiles（2026-09-13 delta 复活）：crossSection 因子的独立输入。

        live 链路 current 帧的 percentiles 末项是权威 pct 复制尾（防漂移，见
        ranktrend_routes._load_frames_for_analysis），保留它 delta 恒 0、A/D 档不可达。
        调用方传去复制尾序列（level 不变、delta=权威帧差），None 回退 percentiles
        （replay/backtest/research 现行为，golden 不漂移）。"""
        if not ranks:
            return None
        code = str(stock.get("code") or "")
        current_rank = ranks[-1]
        current_percentile = percentiles[-1]
        previous = percentiles[-2] if len(percentiles) >= 2 else current_percentile
        display_change = current_percentile - previous
        required_market_fields = ("change", "volumeRatio", "zlje", "zljzb")
        missing_market_fields = [
            field for field in required_market_fields
            if stock.get(field) is None or not _is_finite_number(stock.get(field))
        ]
        fallback = {
            "displayChange": display_change,
            "stockChange": stock.get("change"),
            "volumeRatio": stock.get("volumeRatio"),
            "zlje": stock.get("zlje"),
            "zljzb": stock.get("zljzb"),
        }
        technical = _compat_callable("analyze_technical")(percentiles, self.config, fallback)
        cycle = _compat_callable("analyze_cycle")(ranks, percentiles, self.config)
        risk = _compat_callable("analyze_risk")(
            current_percentile,
            technical,
            cycle,
            fallback["zlje"],
            fallback["zljzb"],
            fallback["volumeRatio"],
            self.config,
        )
        cycle = _compat_callable("analyze_cycle_with_risk")(
            cycle, risk, technical.get("momentumProfile"), self.config
        )
        # WP2a：lifecycle veto（action）多帧确认（K>1 且帧序列上下文才生效；K=1 直通 = 现行为）。
        # 后端 decision 无 veto 布尔键，veto 恒以 action=="veto" 表达；抑制时改写 action，
        # 下游 _lifecycle_tier（不产 E）/E 连锁/compose_analysis_candidate_tier/compose_observation_scores/
        # compose_strategy/交易侧 _lifecycle_decision_action 全部自动跟随。
        # R-C2 裁决：active 且 K>1 时每帧无条件过 confirmed_value——非 veto 值走其非触发分支
        # （基线更新 + 原样返回），veto 值走连续计数；只对 veto 调用会让"维持上一帧已确认
        # action"无从成立（非 veto 帧基线永不更新）。
        self._gate_confirm_state = getattr(self, "_gate_confirm_state", None) or GateConfirmState(
            required_frames=int(getattr(self.config, "lifecycleConfirmFrames", 1))
        )
        self._gate_confirm_ctx = getattr(self, "_gate_confirm_ctx", None) or {"active": False}
        if self._gate_confirm_ctx.get("active") and self._gate_confirm_state.required_frames > 1:
            _decision = cycle.setdefault("decision", {})
            _action = str(_decision.get("action") or "")
            _confirmed_action = self._gate_confirm_state.confirmed_value(
                code, _action, when_in=("veto",), default="caution"
            )
            if _confirmed_action != _action:
                _decision["action"] = _confirmed_action
                _decision.setdefault("reasons", []).append(
                    gate_reason("周期 veto", self._gate_confirm_state.streak(code), self._gate_confirm_state.required_frames)
                )
        # 其余情况（未激活 / K=1）：直通，不触碰状态与决策。
        decision = _compat_callable("compose_decision")(technical, cycle, risk, self.config)
        strategy = _compat_callable("compose_analysis_candidate_tier")(
            technical, cycle, risk, regime, self.config
        )
        execution_strategy = compose_strategy(technical, cycle, risk, frame.get("hotlistSentiment"), config=self.config)
        observation = compose_observation_scores({
            "technical": technical,
            "cycle": cycle,
            "risk": risk,
            "decision": decision,
        }, config=self.config)
        # WP2a：B/D 环境降档连续确认（K>1 且激活时；E 连锁由上方 action 确认覆盖）。
        # 仅 override synergy 侧 lc_tier 判断，observation.lifecycle.signalTier 发布输出保持原始值。
        # R-C2 同源：active 且 K>1 时每帧无条件过 confirmed_value（非 B/D 帧更新基线/中断计数）。
        # R-C4：抑制标注在 assemble_observation 之后追加（assemble 会重写 synergy.tierReasons）。
        # R-C5：与 action 确认共用同一状态机实例，key 加 ":lc" 命名空间隔离
        # （两通道同 key 会互相污染 streak/confirmed——K2 集成测试实证）。
        _lc_tier_override = None
        _bd_suppression = None
        if self._gate_confirm_ctx.get("active") and self._gate_confirm_state.required_frames > 1:
            _bd_key = f"{code}:lc"
            _raw_lc = str((observation.get("lifecycle") or {}).get("signalTier") or "")
            _required = self._gate_confirm_state.required_frames
            if _raw_lc in ("B", "D"):
                _confirmed_lc = self._gate_confirm_state.confirmed_value(
                    _bd_key, _raw_lc, when_in=("B", "D"), default="C"
                )
                if _confirmed_lc != _raw_lc:
                    _lc_tier_override = _confirmed_lc
                    _bd_suppression = gate_reason(
                        f"周期 {_raw_lc} 环境降档", self._gate_confirm_state.streak(_bd_key), _required
                    )
            else:
                self._gate_confirm_state.confirmed_value(_bd_key, _raw_lc, when_in=("B", "D"), default="C")
        # 顶层 candidateTier/action 按 meta 模式选择，保持回测消费兼容；两个分层同时输出
        tier_source = execution_strategy if self._candidate_tier_mode(meta) == "execution" else strategy
        jump = _compat_callable("detect_rank_jumps")(
            percentiles,
            ranks,
            delta_pct=self.config.jumpDeltaPct,
            reset_lookback=self.config.jumpResetLookback,
            sustain_count=self.config.jumpSustainCount,
        )
        # 2026-08-17 G4：Jump 价格/量确认（审计缺口——排名 Jump 可能来自热榜噪声，无成交配合）。
        # 默认生效（jumpConfirmChangeMin=3.0 / jumpConfirmVolumeRatioMin=1.0）：buy 需
        # change ≥3% 且量比 ≥1，sell 需 change ≤-3% 且量比 ≥1（放量配合）；不满足 → 降级
        # direction=hold 并记录 unconfirmed（fail-visible），避免假 Jump 污染共振投票。
        # （2026-09-15 断线修复：此前分支只匹配 up/down，生产枚举 buy/sell 全放行。）
        jump = _confirm_jump(jump, stock, self.config)
        # 阶段 2 数据质量治理：ok 判定用动量可计算门槛（momentumPeriods.max+1），
        # 不再混入 MACD 预热需求。旧口径 get_technical_min_samples=34 帧在 50 帧滑动窗口
        # + 热榜轮动下把 ok 占比压到 ~46%（20 个历史回测全部 researchGrade=degraded）。
        # MACD 预热状态由 _macd_diagnostics.hasStableObservationBars 单独暴露（fail-visible）。
        sample_status = (
            "ok" if len(percentiles) >= get_momentum_min_samples(self.config)
            else "degraded" if len(percentiles) >= self.config.degradedSampleFloor
            else "insufficient"
        )
        if missing_market_fields and sample_status == "ok":
            sample_status = "degraded"
        rank_trend = {
            "meta": {
                "code": code,
                "currentRank": current_rank,
                "currentPercentile": current_percentile,
                "change": display_change,
                "rawChange": ranks[0] - current_rank,
                "updateTime": frame.get("timestamp"),
                "sampleQuality": {
                    "snapshotType": frame.get("type"),
                    "sampleCount": len(percentiles),
                    "requiredSampleCount": get_momentum_min_samples(self.config),
                    "status": sample_status,
                    "coverageWarning": (
                        None
                        if meta.get("sampleQuality") == "ok" and not missing_market_fields
                        else (meta.get("warnings") or ["市场字段缺失，相关观察降级"])[0]
                    ),
                    "latestTradingDate": frame.get("tradingDate"),
                    "latestSlotTime": frame.get("slotTime"),
                    "delayedCount": meta.get("delayedCount", 0),
                    "restoredCount": meta.get("restoredCount", 0),
                    "missingFields": missing_market_fields,
                    "qualityFlags": ["missing_market_fields"] if missing_market_fields else [],
                },
            },
            "technical": technical,
            "jump": jump,
            "cycle": cycle,
            "risk": risk,
            "decision": decision,
            "observation": observation,
            "strategy": strategy,
            "executionStrategy": execution_strategy,
        }
        # 回测方案 §3.2 组装下沉：observation.volumePrice / synergy + signalTier 与 API 单股链路同源。
        # 延迟 import 避免 engine ↔ volume_price 循环依赖。
        # 阶段 3 修复方向 1：replay（assemble=True + market_ctx）补共振维——与 API 单股链路
        # （routes _analyze_one_stock 的 analyze_rank_resonance 组装）同输入同源，恢复四维投票语义；
        # API 单股链路同样传 assemble=True；market_ctx 存在时在同一 builder 内重算共振，避免字段/状态漂移。
        if assemble:
            from backend.analysis.ranktrend.ranking.volume_price import assemble_observation
            from backend.analysis.ranktrend.atr.atr_mean_reversion import analyze_atr_mean_reversion, bar_of

            # _build_signal 可被直接调用（不经 replay），惰性初始化 ATR 累积状态与帧索引
            if not hasattr(self, "_atr_meta_by_code"):
                self._atr_meta_by_code = {}
            if not hasattr(self, "_index_by_snapshot"):
                self._index_by_snapshot = {}

            # ── ATR 波动观察（独立观察维度，不进 synergy 投票；设计 ranktrend-atr-signal-design.md v2）──
            # 跨帧累积 (high, low, close)；缺 bar 帧计数 missingBars；帧间隔 ≥ atrGapResetBars 重置
            # 序列（防缺席帧导致的跨时间连接 TR 膨胀）并计数 gapResets；截断 atrMaxHistoryBars。
            # 2026-08-17 修正：跨 tradingDate **不**恒重置——half_hour 每天仅 10-11 帧，
            # 跨日恒重置使序列永远达不到样本门槛（0 信号）；隔日跳空计入 TR 为真实日线 ATR 语义。
            atr_entry = self._atr_meta_by_code.setdefault(
                code, {"bars": [], "missing": 0, "resets": 0, "last_idx": None, "last_date": None}
            )
            frame_idx = self._index_by_snapshot.get(str(frame.get("snapshotId")))
            trading_date = str(frame.get("tradingDate") or "")
            bar = bar_of(stock)
            if atr_history is not None:
                # API worker 是无状态进程；使用调用方按时间顺序准备好的历史 bar，
                # 保持与 replay 的 ATR 输入同构，避免单帧 worker 将 ATR 退化为 1/20。
                bars = [item for item in atr_history if isinstance(item, tuple) and len(item) == 3]
                rank_trend["observation"]["atrMeanReversion"] = analyze_atr_mean_reversion(
                    bars,
                    self.config,
                    missing_bars=sum(1 for item in atr_history if not (isinstance(item, tuple) and len(item) == 3)),
                    gap_resets=0,
                )
                rank_trend["technical"]["atrMeanReversion"] = rank_trend["observation"]["atrMeanReversion"]
            elif bar is None:
                atr_entry["missing"] += 1
            else:
                prev_idx = atr_entry["last_idx"]
                gap = (frame_idx - prev_idx) if (frame_idx is not None and prev_idx is not None) else 0
                if prev_idx is not None and gap >= self.config.atrGapResetBars:
                    atr_entry["bars"] = []  # 缺席帧断档重置：只保留当前帧重新起算
                    atr_entry["resets"] += 1
                    atr_entry["missing"] = 0
                atr_entry["bars"].append(bar)
                if self.config.atrMaxHistoryBars > 0 and len(atr_entry["bars"]) > self.config.atrMaxHistoryBars:
                    atr_entry["bars"] = atr_entry["bars"][-self.config.atrMaxHistoryBars :]
                atr_entry["last_idx"] = frame_idx
                atr_entry["last_date"] = trading_date
            if atr_history is None:
                rank_trend["observation"]["atrMeanReversion"] = analyze_atr_mean_reversion(
                    atr_entry["bars"],
                    self.config,
                    missing_bars=atr_entry["missing"],
                    gap_resets=atr_entry["resets"],
                )
            # 设计文档 §4.2：同时挂载 technical.atrMeanReversion（供技术诊断层消费）
            rank_trend["technical"]["atrMeanReversion"] = rank_trend["observation"]["atrMeanReversion"]
            # 横截面相对强弱因子（2026-08-17 方向 A）：个股 percentile 序列（histories item[2]）
            # + 市场 median percentile（market_ctx）。第 5 维投票默认打开（tierSynergyCrossSectionVote=1.0）。
            # 2026-09-13 delta 复活：live current 帧复制尾场景用调用方供给的去尾序列
            # （level 不变、delta=权威帧差）；None 回退 percentiles（replay/backtest 现行为）。
            from backend.analysis.ranktrend.trend.cross_section import compute_cross_section

            rank_trend["observation"]["crossSection"] = compute_cross_section(
                cross_section_percentiles if cross_section_percentiles is not None else percentiles,
                (market_ctx or {}).get("marketMedianPercentile"),
                self.config,
            )
            rank_trend["technical"]["crossSection"] = rank_trend["observation"]["crossSection"]
            # 价格动量观察因子（2026-08-17 审计缺口 G1）：价格时序（change）均线/动量——
            # 排名时序独大、价格信息缺失的补齐。不进 synergy 投票，先验证区分度。
            from backend.analysis.ranktrend.trend.price_momentum import compute_price_momentum

            rank_trend["observation"]["priceMomentum"] = compute_price_momentum(
                price_changes or [],
                self.config,
            )
            rank_trend["technical"]["priceMomentum"] = rank_trend["observation"]["priceMomentum"]
            # 成交额量比（2026-08-18 G3）：跨帧 amount 均额基准——"价量资金"落地。
            # 历史不足/缺失 → None（fail-visible），assemble_observation 传入 compute_volume_price_score。
            from backend.analysis.ranktrend.ranking.volume_price import compute_amount_ratio

            rank_trend["observation"]["amountRatio"] = compute_amount_ratio(amount_history, self.config)
            rank_trend["technical"]["amountRatio"] = rank_trend["observation"]["amountRatio"]
            # 价格-排名背离观察因子（2026-08-18 G1 相位差方案）：价升排名跌（出货预警）/
            # 排名升价跌（关注度先行）——价格与排名 Jump 的背离信号。不进 synergy 投票，先验证区分度。
            from backend.analysis.ranktrend.trend.price_rank_divergence import compute_price_rank_divergence

            rank_trend["observation"]["priceRankDivergence"] = compute_price_rank_divergence(
                price_changes or [],
                percentiles,
                self.config,
            )
            rank_trend["technical"]["priceRankDivergence"] = rank_trend["observation"]["priceRankDivergence"]

            if market_ctx is not None:
                sample_quality = (rank_trend.get("meta") or {}).get("sampleQuality") or {}
                market_short_change = market_ctx.get("marketMedianShortChange")
                rank_trend["resonance"] = analyze_rank_resonance(
                    {
                        "percentiles": percentiles,
                        "sampleQuality": {
                            "status": sample_quality.get("status") or "insufficient",
                            "timelineValid": sample_quality.get("timelineValid", True),
                        },
                        "marketMedianShortChange": (
                            market_short_change if market_short_change is not None else float("nan")
                        ),
                        "marketSampleCount": market_ctx.get("marketSampleCount") or 0,
                        "marketMedianPercentile": market_ctx.get("marketMedianPercentile"),
                        "jump": {
                            "direction": jump.get("direction") or "hold",
                            "event": jump.get("event") or "none",
                            "events": jump.get("events") or [],
                        },
                        "entry": {
                            "isNew": len(percentiles) == 1,
                            "currentAttentionPercentile": percentiles[-1] if percentiles else 0,
                        },
                    },
                    self.config,
                )
            assemble_observation(rank_trend, stock, self.config, lc_tier_override=_lc_tier_override)
            # R-C4：assemble 重写 synergy.tierReasons，抑制标注在此追加才可见
            if _bd_suppression:
                rank_trend["observation"]["synergy"].setdefault("tierReasons", []).append(_bd_suppression)
        return {
            "snapshotId": frame.get("snapshotId"),
            "timestamp": frame.get("timestamp"),
            "tradingDate": frame.get("tradingDate"),
            "slotTime": frame.get("slotTime"),
            "code": code,
            "name": stock.get("name") or code,
            "rank": current_rank,
            "avgRankNum": stock.get("avgRankNum"),
            "zljzb": stock.get("zljzb"),
            "candidateTier": tier_source["candidateTier"],
            "action": tier_source["action"],
            "price": stock.get("price"),
            "change": stock.get("change"),
            "volume": stock.get("volume"),
            "turnover": stock.get("turnover"),
            "turnoverRate": stock.get("turnoverRate"),
            "volumeRatio": stock.get("volumeRatio"),
            "bid1Price": stock.get("bid1Price"),
            "bid1Volume": stock.get("bid1Volume"),
            "ask1Price": stock.get("ask1Price"),
            "ask1Volume": stock.get("ask1Volume"),
            "lastTradePrice": stock.get("lastTradePrice"),
            "lastTradeVolume": stock.get("lastTradeVolume"),
            "high": stock.get("high"),
            "low": stock.get("low"),
            "highPrice": stock.get("highPrice"),
            "lowPrice": stock.get("lowPrice"),
            "limitUpPrice": stock.get("limitUpPrice") or stock.get("ztPrice"),
            "limitDownPrice": stock.get("limitDownPrice") or stock.get("dtPrice"),
            "leadStatus": stock.get("leadStatus"),
            "fengdan": stock.get("fengdan"),
            "themes": stock.get("themes") or [],
            "mainTheme": stock.get("mainTheme"),
            "themeHeat": stock.get("themeHeat"),
            "themeContribution": stock.get("themeContribution"),
            "themeRole": stock.get("themeRole"),
            "themeRiskFlags": stock.get("themeRiskFlags") or [],
            "rankTrend": rank_trend,
            "stage": cycle["stage"],
            "regime": regime["state"],
            "confidence": decision["final"]["confidence"],
        }

    @staticmethod
    def _build_stock_lookup(frames: list[dict[str, Any]]) -> list[dict[str, dict[str, Any]]]:
        output: list[dict[str, dict[str, Any]]] = []
        for frame in frames:
            lookup: dict[str, dict[str, Any]] = {}
            for row in frame.get("stocks", []):
                code = str(row.get("code")) if row.get("code") is not None else ""
                if code and code not in lookup:
                    lookup[code] = row
            output.append(lookup)
        return output

    @staticmethod
    def _find_stock(frame: dict[str, Any], code: str) -> dict[str, Any] | None:
        return next((item for item in frame.get("stocks", []) if str(item.get("code")) == code), None)
