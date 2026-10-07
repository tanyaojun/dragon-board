from __future__ import annotations

import math
from typing import Any
from ..engine.config import RankTrendConfig
from ..engine.primitives import clamp, average, signal_confidence
from .technical import cycle_rank_shock, rank_path_commitment

def analyze_cycle(
    ranks: list[float],
    percentiles: list[float],
    config: RankTrendConfig | None = None,
    *,
    time_keys: list[Any] | None = None,
    frame_indices: list[int] | None = None,
) -> dict[str, Any]:
    """5 态生命周期主流程。

    P3 时间正规化（2026-10-07 预登记合同 B5，默认 off=现行为零漂移）：
    strictness=cross_day/non_adjacent 且提供 time_keys（每元素 tradingDate 等日期键）/
    frame_indices（全局帧索引）时，相邻序列元素跨交易日（或同日帧距 ≥2）判 temporalGap——
    该步 velocity/acceleration/shock 置 NaN + metrics["temporalGap"]=True（不插值，fail-visible），
    raw 沿袭前帧 raw（NaN 布尔比较全 False 会静默滑 cooling，显式禁止），normalize 照常运行。
    G1/G2 不动 hot_streak/best/drawdown 的跨缺口累积（那是 G3 剂量，未预登记不实施）。
    """
    previous_stage = None
    current_stage = None
    current_raw = None
    previous_normalized = None
    metrics = {}
    # 性能契约（2026-09-23 引擎提速）：cycle_metrics 输出只依赖末 ≤8 档窗口，
    # 逐步传尾窗而非重建整个前缀切片（原 O(L²) 切片/逐差 → O(L)），逐位一致。
    c = config or RankTrendConfig()
    strictness = str(getattr(c, "lifecycleTimeGapStrictness", "off") or "off")
    use_dates = strictness != "off" and time_keys is not None and len(time_keys) == len(percentiles)
    use_frames = strictness == "non_adjacent" and frame_indices is not None and len(frame_indices) == len(percentiles)
    for index in range(len(percentiles)):
        window_start = index - 7 if index >= 7 else 0
        metrics = cycle_metrics_window(ranks[window_start : index + 1], percentiles[window_start : index + 1], config=config)
        is_gap = False
        if use_dates and index >= 1:
            is_gap = str(time_keys[index]) != str(time_keys[index - 1])
            if not is_gap and use_frames:
                is_gap = int(frame_indices[index]) - int(frame_indices[index - 1]) >= 2
        if is_gap:
            metrics = {
                **metrics,
                "rankVelocity": float("nan"),
                "rankAcceleration": float("nan"),
                "rankShock": float("nan"),
                "temporalGap": True,
            }
            # raw 沿袭前帧（NaN 比较全 False → raw_stage 恒 cooling 的静默路径被显式封死）
            raw = current_raw if current_raw is not None else "cooling"
        else:
            raw = raw_stage(index + 1, percentiles[index], metrics, config=config)
        normalized = normalize_stage(current_stage, raw, percentiles[index], metrics, config=config)
        previous_stage = current_raw
        previous_normalized = current_stage
        current_raw = raw
        current_stage = normalized
    stage = current_stage or "cooling"
    raw = current_raw or "cooling"
    transition = stage if not previous_normalized or previous_normalized == stage else f"{previous_normalized}->{stage}"
    confidence = cycle_confidence(stage, percentiles[-1] if percentiles else 0, metrics, config=config)
    metric_values = metrics or {"rankVelocity": 0, "rankAcceleration": 0, "rankShock": 0, "hotZoneStreak": 0, "bestRecentRank": ranks[-1] if ranks else 999, "drawdownFromPeak": 0, "rankPathCommitment": 0.5}
    return {
        "rawStage": raw,
        "stage": stage,
        "previousStage": previous_normalized,
        "transition": transition,
        "confidence": confidence,
        "metrics": metric_values,
        "entryAdvice": entry_advice(stage, transition),
        "decision": lifecycle_decision(raw, stage, transition, confidence, metric_values, config=config),
    }


def cycle_metrics(ranks: list[float], percentiles: list[float]) -> dict[str, Any]:
    return cycle_metrics_window(ranks[-8:], percentiles[-8:])


def cycle_metrics_window(
    rank_window: list[float], percentile_window: list[float], config: "RankTrendConfig | None" = None
) -> dict[str, Any]:
    """尾窗（≤8 档）版 cycle_metrics：与全量前缀输入逐位一致的前提是窗口取自同一序列尾部。

    前置条件：rank_window 与 percentile_window 必须是同一序列的**等长**尾切片（调用方保证；
    不等长输入下 hotZoneStreak 的配对语义与旧实现不可比）。语义等价依据：hot_streak/best/
    rankPathCommitment 本来就只用末 8 档；velocity 门槛 len>=2/3 与 rankShock 门槛 len>=6 在
    「窗口=min(长度,8)」下与全量门槛同真同假（长度 >=8 时两者恒真，<8 时窗口即全量）。

    P1 尺度模式（2026-10-07 预登记合同 A5，config.lifecycleRankScaleMode，默认 mixed=现行为）：
    - pct_full：名次类谓词整体换算 T=200 锚等价分位线——bestRecentRank=201−2·max(pct窗)、
      drawdownFromPeak=2·max(0, max−cur)（1 格=0.5 pct 点）、热区仅 pct≥88 臂（删 rank≤10 臂）；
      阈值常量不变（等价于阈值整体换算）。
    - hotzone_pct_only：仅热区删名次臂，best/drawdown 保持名次单位。
    velocity/acceleration/shock/pathCommitment 本就是分位单位，各模式相同。
    """
    c = config or RankTrendConfig()
    scale_mode = str(getattr(c, "lifecycleRankScaleMode", "mixed") or "mixed")
    current_rank = rank_window[-1] if rank_window else 999
    hot_streak = 0
    for rank, percentile in zip(reversed(rank_window), reversed(percentile_window)):
        hot = (rank <= 10 or percentile >= 88) if scale_mode == "mixed" else percentile >= 88
        if hot:
            hot_streak += 1
        else:
            break
    count = len(percentile_window)
    velocity = percentile_window[-1] - percentile_window[-2] if count >= 2 else 0
    previous_velocity = percentile_window[-2] - percentile_window[-3] if count >= 3 else 0
    if scale_mode == "pct_full":
        max_pct = max(percentile_window) if percentile_window else 0.0
        cur_pct = percentile_window[-1] if percentile_window else 0.0
        best = 201.0 - 2.0 * max_pct
        drawdown = 2.0 * max(0.0, max_pct - cur_pct)
    else:
        best = min(rank_window) if rank_window else current_rank
        drawdown = max(0, current_rank - best)
    return {
        "rankVelocity": velocity,
        "rankAcceleration": velocity - previous_velocity,
        "rankShock": cycle_rank_shock(percentile_window),
        "hotZoneStreak": hot_streak,
        "bestRecentRank": best,
        "drawdownFromPeak": drawdown,
        "rankPathCommitment": rank_path_commitment(percentile_window),
    }


def raw_stage(
    history_length: int, current_percentile: float, metrics: dict[str, Any], config: "RankTrendConfig | None" = None
) -> str:
    """5 态初判（阈值数据驱动优化设计 2026-08-16：全部阈值参数化，默认值=原硬编码，零行为变化）。"""
    c = config or RankTrendConfig()
    if history_length < 2:
        return "cooling"
    velocity = metrics["rankVelocity"]
    accel = metrics["rankAcceleration"]
    hot = metrics["hotZoneStreak"]
    best = metrics["bestRecentRank"]
    drawdown = metrics["drawdownFromPeak"]
    warm = current_percentile >= c.cycleRawWarmPercentileMin or best <= c.cycleRawWarmBestRankMax
    hot_zone = current_percentile >= c.cycleRawHotZonePercentileMin or best <= c.cycleRawHotZoneBestRankMax
    recovery = velocity > c.cycleRawRecoveryVelocityMin and accel >= c.cycleRawRecoveryAccelMin and (
        current_percentile >= c.cycleRawRecoveryPercentileMin or best <= c.cycleRawRecoveryBestRankMax or hot >= c.cycleRawRecoveryHotMin
    )
    expansion = velocity > c.cycleRawRecoveryVelocityMin and current_percentile >= c.cycleRawExpansionPercentileMin and (
        accel >= c.cycleRawExpansionAccelMin or hot >= c.cycleRawExpansionHotMin or best <= c.cycleRawExpansionBestRankMax
    )
    crowded = hot_zone and (hot >= c.cycleRawCrowdedHotMin or best <= c.cycleRawCrowdedBestRankMax) and (
        drawdown <= c.cycleRawCrowdedDrawdownMax and (velocity <= c.cycleRawCrowdedVelocityMax or accel < 0)
    )
    reversal = warm and drawdown >= c.cycleRawReversalDrawdownMin and (
        velocity < 0 or accel < c.cycleRawReversalAccelMax
    ) and (hot >= c.cycleRawReversalHotMin or best <= c.cycleRawReversalBestRankMax)
    if reversal:
        return "reversal"
    if crowded:
        return "crowded"
    if expansion and warm:
        return "expansion"
    if recovery:
        return "ignition"
    return "cooling"


def normalize_stage(
    previous: str | None, raw: str, current_percentile: float, metrics: dict[str, Any], config: "RankTrendConfig | None" = None
) -> str:
    """状态机平滑（阈值参数化，默认值=原硬编码，零行为变化）。"""
    c = config or RankTrendConfig()
    if not previous:
        return raw
    velocity = metrics["rankVelocity"]
    accel = metrics["rankAcceleration"]
    hot = metrics["hotZoneStreak"]
    best = metrics["bestRecentRank"]
    drawdown = metrics["drawdownFromPeak"]
    recovery = velocity > c.cycleRawRecoveryVelocityMin and accel >= c.cycleRawRecoveryAccelMin and (
        current_percentile >= c.cycleRawRecoveryPercentileMin or best <= c.cycleRawRecoveryBestRankMax or hot >= c.cycleRawRecoveryHotMin
    )
    weakening = velocity < 0 or accel < c.cycleNormWeakeningAccelMax or drawdown >= 2
    severe = velocity < -1 or accel < c.cycleNormSevereAccelMax or drawdown >= c.cycleNormSevereDrawdownMin
    cooling_ready = current_percentile < c.cycleNormCoolingReadyPercentileMax or hot <= 1
    crowded_carry = current_percentile >= c.cycleNormCrowdedCarryPercentileMin or best <= c.cycleNormCrowdedCarryBestRankMax or hot >= 2
    if previous == "ignition":
        if raw in ("expansion", "crowded"):
            return "expansion"
        if raw in ("reversal", "cooling"):
            return "cooling" if weakening else "ignition"
        return "ignition"
    if previous == "expansion":
        if raw == "crowded":
            return "crowded"
        if raw == "reversal":
            return "crowded" if crowded_carry and not severe else "reversal" if severe or weakening else "crowded"
        if raw == "cooling":
            return "reversal" if severe or weakening else "expansion"
        return "expansion"
    if previous == "crowded":
        if raw == "reversal":
            return "reversal"
        if raw == "cooling":
            return "cooling" if cooling_ready else "reversal"
        if raw in ("expansion", "ignition"):
            return "reversal" if weakening else "crowded"
        return "crowded"
    if previous == "reversal":
        if raw in ("cooling", "reversal"):
            return raw
        return "cooling" if recovery else "reversal"
    if previous == "cooling":
        if raw in ("cooling", "reversal") or not recovery:
            return "cooling"
        if raw == "expansion" and current_percentile < 72 and hot == 0:
            return "ignition"
        if raw == "crowded":
            return "expansion"
        return raw
    return raw


def cycle_confidence(
    stage: str, percentile: float, metrics: dict[str, Any], config: "RankTrendConfig | None" = None
) -> float:
    """阶段置信度（阈值参数化，默认值=原硬编码，零行为变化；每态区域/动量/持续性/回撤阈值）。"""
    c = config or RankTrendConfig()
    velocity = metrics.get("rankVelocity", 0)
    accel = metrics.get("rankAcceleration", 0)
    hot = metrics.get("hotZoneStreak", 0)
    best = metrics.get("bestRecentRank", 999)
    drawdown = metrics.get("drawdownFromPeak", 0)
    if stage == "cooling":
        region = percentile < c.cycleConfCoolingRegionPctMax
        momentum = velocity <= 0 or percentile < c.cycleConfCoolingMomentumPctMax
        persistence = hot <= c.cycleConfCoolingPersistenceHotMax
        draw = drawdown <= c.cycleConfCoolingDrawdownMax or percentile < c.cycleConfCoolingRegionPctMax
    elif stage == "ignition":
        region = percentile >= c.cycleConfIgnitionRegionPctMin and percentile < c.cycleConfIgnitionRegionPctMax
        momentum = velocity > 0 and accel >= c.cycleConfIgnitionMomentumAccelMin
        persistence = hot <= c.cycleConfIgnitionPersistenceHotMax
        draw = drawdown == 0
    elif stage == "expansion":
        region = percentile >= c.cycleConfExpansionRegionPctMin
        momentum = velocity > 0 and accel >= c.cycleConfExpansionMomentumAccelMin
        persistence = hot <= c.cycleConfExpansionPersistenceHotMax
        draw = drawdown <= c.cycleConfExpansionDrawdownMax
    elif stage == "crowded":
        region = percentile >= c.cycleConfCrowdedRegionPctMin or best <= c.cycleConfCrowdedRegionBestMax
        momentum = percentile >= c.cycleConfCrowdedMomentumPctMin and (velocity <= 0 or hot >= c.cycleConfCrowdedMomentumHotMin)
        persistence = hot >= c.cycleConfCrowdedPersistenceHotMin
        draw = drawdown <= c.cycleConfCrowdedDrawdownMax
    else:  # reversal
        region = percentile >= c.cycleConfReversalRegionPctMin or best <= c.cycleConfReversalRegionBestMax
        momentum = velocity <= 0 or accel < -1
        persistence = hot >= c.cycleConfReversalPersistenceHotMin or best <= c.cycleConfReversalPersistenceBestMax
        draw = drawdown >= c.cycleConfReversalDrawdownMin
    return clamp(50 + int(region) * 10 + int(momentum) * 10 + int(persistence) * 10 + int(draw) * 10, 50, 90)


def entry_advice(stage: str, transition: str) -> dict[str, Any]:
    if transition in ("cooling->ignition", "ignition->expansion"):
        bias = "preferred"
    elif stage == "reversal":
        bias = "blocked"
    elif stage in ("cooling", "crowded"):
        bias = "avoid"
    else:
        bias = "watch"
    reasons = {
        "preferred": "处于优选阶段路径，可作为情绪周期主观察对象。",
        "watch": "处于可跟踪阶段，但还不是优选出手路径。",
        "avoid": "处于冷却或拥挤阶段，宜观察不宜积极出手。",
        "blocked": "处于反转阶段，应优先回避。",
    }
    return {"bias": bias, "allowed": bias == "preferred", "reason": reasons[bias]}


def neutralize_gap_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """P3 gap 帧 risk 输入中性化：NaN 动量分量→0（无加无减=证据缺失不加分），temporalGap 标记保留。

    仅 lifecycleTimeGapStrictness≠off 的 trial 路径会命中（默认 mixed/off 恒原样返回）。
    NaN 原样进 analyze_risk 会让 overheat/pressure 变 NaN 且比较行为不确定——risk 的动量
    分量缺证据按中性处理，缺口事实由 metrics.temporalGap 与 decision reasons 承载（fail-visible）。
    """
    if not isinstance(metrics, dict) or not metrics.get("temporalGap"):
        return metrics
    out = dict(metrics)
    for key in ("rankVelocity", "rankAcceleration", "rankShock"):
        value = out.get(key)
        if isinstance(value, float) and not math.isfinite(value):
            out[key] = 0.0
    return out


def _evidence_num(value: Any) -> Any:
    """evidence 序列化护栏：NaN→None（合同 B5：不得以 0 伪装，JSON 无 NaN）。"""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def lifecycle_decision(
    raw: str,
    stage: str,
    transition: str,
    confidence: float,
    metrics: dict[str, Any],
    risk: dict[str, Any] | None = None,
    momentum: dict[str, Any] | None = None,
    config: RankTrendConfig | None = None,
) -> dict[str, Any]:
    c = config or RankTrendConfig()
    reasons: list[str] = []
    action = "caution"
    risk = risk or {}
    divergence = risk.get("divergence") if isinstance(risk.get("divergence"), dict) else {}
    overheat = risk.get("overheat") if isinstance(risk.get("overheat"), dict) else {}
    risk_pressure = float(risk.get("pressure") or 0)
    divergence_severity = float(divergence.get("severity") or 0)
    overheat_severity = float(overheat.get("severity") or 0)
    discovery_reasons: list[str] = []
    high_risk_conflict = risk_pressure >= c.lifecycleHighRiskPressureMin or (divergence_severity >= c.lifecycleHighRiskDivergenceMin and overheat_severity >= c.lifecycleHighRiskOverheatMin)
    rank_path = float(metrics.get("rankPathCommitment", 0.5))
    momentum = momentum if isinstance(momentum, dict) else {}
    momentum_short = float(momentum.get("short") or 0)
    momentum_mid = float(momentum.get("mid") or 0)
    momentum_long = float(momentum.get("long") or 0)
    momentum_acceleration = float(momentum.get("acceleration") or 0)
    mid_long_committed = momentum_mid >= c.lifecycleMidLongCommitmentMin and momentum_long >= c.lifecycleMidLongCommitmentMin and momentum_acceleration >= c.lifecycleAccelCommitmentMin
    weak_path_commitment = (
        rank_path < c.lifecycleWeakPathCommitmentMax
        and float(metrics.get("rankVelocity") or 0) > c.lifecycleVelocityMin
        and float(metrics.get("rankAcceleration") or 0) > c.lifecycleAccelMin
        and not mid_long_committed
        and stage in ("ignition", "expansion")
    )
    low_visibility_ignition = (
        stage == "ignition"
        and transition == "cooling->ignition"
        and int(metrics.get("hotZoneStreak") or 0) == 0
        and rank_path < c.lifecycleLowVisibilityPathMax
        and float(metrics.get("rankVelocity") or 0) > c.lifecycleVelocityMin
        and float(metrics.get("rankAcceleration") or 0) > c.lifecycleAccelMin
        and momentum_short >= c.lifecycleLowVisibilityMomentumMin
        and momentum_mid >= c.lifecycleLowVisibilityMomentumMin
        and momentum_acceleration >= c.lifecycleLowVisibilityMomentumMin
    )
    if stage == "reversal" or raw == "reversal":
        action = "veto"
        reasons.append("生命周期进入反转路径，辅助决策一票否决。")
    elif weak_path_commitment:
        action = "caution"
        reasons.append("生命周期B识别到最后一跳过强但整段承接不足，按假突破路径谨慎观察。")
    elif low_visibility_ignition:
        action = "caution"
        reasons.append("生命周期B识别到低可见度首段点火，承接尚未扩散，防止抢占后续高质量仓位。")
    elif high_risk_conflict and stage in ("ignition", "expansion"):
        action = "veto"
        reasons.append("生命周期虽处于点火/扩散，但风险背离与过热证据明确反对，辅助决策一票否决。")
    elif stage == "crowded":
        action = "exit_watch"
        reasons.append("生命周期进入拥挤路径，持仓后应进入退出观察。")
    elif stage in ("ignition", "expansion"):
        action = "allow"
        reasons.append("生命周期处于点火或扩散路径，允许 RankTrend 主结构继续进入候选评估。")
    else:
        reasons.append("生命周期仍在冷却路径，辅助决策保持谨慎。")
    if "->" in transition:
        reasons.append(f"阶段路径：{transition}。")
    if metrics.get("temporalGap"):
        reasons.append("序列跨时间缺口，本帧动量证据不可判定（temporalGap），动量类判据按缺失处理。")
    if stage in ("ignition", "expansion") and float(metrics.get("rankVelocity") or 0) > 0:
        discovery_reasons.append("生命周期存在漏选研究价值：点火/扩散路径仍在改善，但不得绕过 RankTrend 主结构直接制造买入。")
    return {
        "action": action,
        "confidence": confidence,
        "reasons": reasons,
        "discovery": {
            "action": "research_watch" if discovery_reasons else "none",
            "reasons": discovery_reasons,
        },
        "evidence": {
            "rawStage": raw,
            "stage": stage,
            "transition": transition,
            "rankVelocity": _evidence_num(metrics.get("rankVelocity", 0)),
            "rankAcceleration": _evidence_num(metrics.get("rankAcceleration", 0)),
            "drawdownFromPeak": _evidence_num(metrics.get("drawdownFromPeak", 0)),
            "hotZoneStreak": _evidence_num(metrics.get("hotZoneStreak", 0)),
            "rankPathCommitment": _evidence_num(rank_path),
            "momentumShort": momentum_short,
            "momentumMid": momentum_mid,
            "momentumLong": momentum_long,
            "momentumAcceleration": momentum_acceleration,
            "riskPressure": _evidence_num(risk_pressure),
            "divergenceSeverity": _evidence_num(divergence_severity),
            "overheatSeverity": _evidence_num(overheat_severity),
        },
    }
