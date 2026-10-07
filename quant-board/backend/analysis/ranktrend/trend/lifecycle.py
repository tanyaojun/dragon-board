from __future__ import annotations

import math
from typing import Any
from ..engine.config import RankTrendConfig
from ..engine.primitives import clamp, average, signal_confidence
from .technical import cycle_rank_shock, rank_path_commitment

# Q1 机制一注入人群阈值（合同 C-c1 冻结）：跨日步 ∧ |ΔrankPct|≥10 = D3 效度证据人群（≈2.1 万步）。
# 冻结为常量非 config——人群定义属判定合同，剂量臂只动 P/vrGate，防误调。
GAP_PV_POPULATION_DELTA_MIN = 10.0


def _finite_num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def gap_velocity_proxy(
    change: Any, volume_ratio: Any, config: "RankTrendConfig | None" = None
) -> float | None:
    """Q1 机制一（合同 C-c1 表格）：跨日 gap 步的价格方向虚拟速度。

    价跌一律 −P（D4：价跌组量比中位 0.77 且 25% 步 ≤0.02，方向本身已是退潮证据，
    无需量确认）；价升须 volumeRatio ≥ vrGate 放量确认（排除无量假升）；
    价平/任一输入缺失或非有限 → None（证据缺，维持 G1 置缺+沿袭）。
    """
    c = config or RankTrendConfig()
    ch = _finite_num(change)
    vr = _finite_num(volume_ratio)
    if ch is None or vr is None:
        return None
    p = float(getattr(c, "lifecycleGapPriceVolumeProxyP", 5.0) or 5.0)
    vr_gate = float(getattr(c, "lifecycleGapPriceVolumeVrGate", 1.0) or 1.0)
    if ch > 0.0 and vr >= vr_gate:
        return p
    if ch < 0.0:
        return -p
    return None


def analyze_cycle(
    ranks: list[float],
    percentiles: list[float],
    config: RankTrendConfig | None = None,
    *,
    time_keys: list[Any] | None = None,
    frame_indices: list[int] | None = None,
    price_changes: list[Any] | None = None,
    volume_ratios: list[Any] | None = None,
) -> dict[str, Any]:
    """5 态生命周期主流程。

    P3 时间正规化（2026-10-07 预登记合同 B5；同日 G1=cross_day 已落生产默认，off 保留为诊断对照臂）：
    strictness=cross_day/non_adjacent 且提供 time_keys（每元素 tradingDate 等日期键）/
    frame_indices（全局帧索引）时，相邻序列元素跨交易日（或同日帧距 ≥2）判 temporalGap——
    该步 velocity/acceleration/shock 内部置 NaN + metrics["temporalGap"]=True（不插值，
    fail-visible），raw 沿袭前帧 raw（NaN 布尔比较全 False 会静默滑 cooling，显式禁止），
    normalize 照常运行；输出层经 _evidence_num 把 NaN 序列化为 null（不伪装 0）。
    strictness≠off 但时间键缺失/长度不匹配/空键步时降级不判 gap，decision reasons 显式
    标注（fail-visible，不静默）。G1/G2 不动 hot_streak/best/drawdown 的跨缺口累积
    （那是 G3 剂量，未预登记不实施）。

    Q1 价量证据喂入（2026-10-07 预登记合同 v1.1 机制一；lifecycleGapPriceVolumeMode，默认 off=零行为）：
    direction_gate 下 gap 步若落入注入人群（跨日步 ∧ |ΔrankPct|≥10，与 D3 效度证据人群对齐）
    且价量证据可用（price_changes/volume_ratios 与 percentiles 等长、当日 change 与 volumeRatio
    均有限），该步 rankVelocity 由价量方向虚拟速度 proxy 驱动（raw/stage 吃 proxy 值，不沿袭前帧；
    acceleration/shock 仍置缺），metrics 增 gapPriceVolumeProxy=True（fail-visible 来源标记）。
    证据缺步（人群外/价平/量缺失/vr 低于门）维持 G1 置缺+沿袭。
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
    # fail-visible 记账：strictness≠off 但键整体不可用 / 个别步键为空 → decision reasons 标注
    time_keys_unavailable = strictness != "off" and not use_dates
    missing_time_keys = 0
    # Q1 机制一（合同 C-c1）：direction_gate 需要价量序列与 percentiles 等长；不等长 → 降级标注
    pv_mode = str(getattr(c, "lifecycleGapPriceVolumeMode", "off") or "off")
    pv_len_ok = (
        price_changes is not None
        and volume_ratios is not None
        and len(price_changes) == len(percentiles)
        and len(volume_ratios) == len(percentiles)
    )
    use_pv = pv_mode == "direction_gate" and pv_len_ok
    pv_unavailable = pv_mode == "direction_gate" and not pv_len_ok
    for index in range(len(percentiles)):
        window_start = index - 7 if index >= 7 else 0
        metrics = cycle_metrics_window(ranks[window_start : index + 1], percentiles[window_start : index + 1], config=config)
        is_gap = False
        if use_dates and index >= 1:
            key_cur = str(time_keys[index] or "")
            key_prev = str(time_keys[index - 1] or "")
            if not key_cur or not key_prev:
                # 空键步无法判定跨日：保留差分（不判 gap 不误报），显式计数标注
                missing_time_keys += 1
            else:
                is_gap = key_cur != key_prev
                if not is_gap and use_frames:
                    is_gap = int(frame_indices[index]) - int(frame_indices[index - 1]) >= 2
        if is_gap:
            proxy = None
            if use_pv and index >= 1:
                # 注入人群选择器：|ΔrankPct|≥10（D3 效度证据人群；差分在此只作人群标识，
                # 不作动量证据——动量证据由当日价量方向承载）
                if abs(percentiles[index] - percentiles[index - 1]) >= GAP_PV_POPULATION_DELTA_MIN:
                    proxy = gap_velocity_proxy(price_changes[index], volume_ratios[index], c)
            if proxy is not None:
                # 证据可用步：proxy 驱动（不沿袭前帧 raw）；accel/shock 单帧构造不出，维持置缺
                metrics = {
                    **metrics,
                    "rankVelocity": proxy,
                    "rankAcceleration": float("nan"),
                    "rankShock": float("nan"),
                    "temporalGap": True,
                    "gapPriceVolumeProxy": True,
                }
                raw = raw_stage(index + 1, percentiles[index], metrics, config=c)
            else:
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
    if not metrics:
        metrics = {
            "rankVelocity": 0, "rankAcceleration": 0, "rankShock": 0, "hotZoneStreak": 0,
            "bestRecentRank": ranks[-1] if ranks else 999, "drawdownFromPeak": 0,
            "rankPathCommitment": 0.5,
        }
    # 输出层 NaN→None（与 evidence 同一护栏；G1 gap 帧动量分量缺证据序列化为 null，
    # 不得以 0 伪装；下游 lifecycle_decision 均按 `or 0` 消费、risk 输入经 neutralize_gap_metrics）
    metric_values = {key: _evidence_num(value) for key, value in metrics.items()}
    # fail-visible 过程标注走独立 annotations 通道（不进 metrics——「带键/不带键 metrics
    # 逐位一致」是既有合同断言；_build_signal 链上 analyze_cycle_with_risk 会用
    # lifecycle_decision 重建 decision，标注经 annotations 参数透传重建不丢失）
    annotations = {
        "timeKeysUnavailable": time_keys_unavailable,
        "timeKeysMissingSteps": missing_time_keys,
        "pvSeriesUnavailable": pv_unavailable,
    }
    decision = lifecycle_decision(
        raw, stage, transition, confidence, metric_values, config=config, annotations=annotations
    )
    return {
        "rawStage": raw,
        "stage": stage,
        "previousStage": previous_normalized,
        "transition": transition,
        "confidence": confidence,
        "metrics": metric_values,
        "annotations": annotations,
        "entryAdvice": entry_advice(stage, transition),
        "decision": decision,
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
    """risk 输入防御（analyze_risk 入口统一调用）：动量分量 None/NaN（缺证据）→ 0（无加无减）。

    覆盖三态：analyze_cycle 内部逐步 NaN、输出层 None、旧快照/外部构造的无标记 None——
    判据按值（None 或非有限 float → 0.0），不依赖 temporalGap 标记（标记只表达「该帧判过
    gap」，防御不能挂在它上面，2026-10-07 code review）。合法值（含 0.0/负值/int）恒原样
    返回同一对象（零开销）。缺口事实由 metrics.temporalGap 与 decision reasons 承载
    （fail-visible），不得以 0 伪装进 evidence。
    """
    if not isinstance(metrics, dict):
        return metrics
    out = metrics
    for key in ("rankVelocity", "rankAcceleration", "rankShock"):
        if key not in out:
            continue  # 缺键=缺证据，不悄悄补 0（fail-visible；键存在但 None/NaN 才中性化）
        value = out[key]
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            if out is metrics:
                out = dict(metrics)
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
    annotations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """annotations（Q1 合同 C-6，2026-10-07）：analyze_cycle 过程标注通道
    （timeKeysUnavailable/timeKeysMissingSteps/pvSeriesUnavailable）——
    decision reasons 的 fail-visible 文案从这里生成；analyze_cycle_with_risk 重建
    decision 时透传，防标注在 _build_signal 链上丢失。None=旧调用方（无标注，零影响）。"""
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
        if metrics.get("gapPriceVolumeProxy"):
            reasons.append("序列跨时间缺口，本帧动量证据由价量方向代理补位（gapPriceVolumeProxy）。")
        else:
            reasons.append("序列跨时间缺口，本帧动量证据不可判定（temporalGap），动量类判据按缺失处理。")
    # fail-visible 过程标注（来自 annotations 通道；analyze_cycle 直接调用与 _build_signal
    # 链（经 analyze_cycle_with_risk 重建）两条路径文案一致）
    annotations = annotations if isinstance(annotations, dict) else {}
    if annotations.get("timeKeysUnavailable"):
        reasons.append("时间键缺失或长度不匹配，跨日差分未做时间正规化（temporalGap 检测未启用）。")
    missing_tk = annotations.get("timeKeysMissingSteps")
    if missing_tk:
        reasons.append(
            f"{missing_tk} 步时间键缺失，对应步无法判定跨日（差分保留，temporalGap 可能低估）。"
        )
    if annotations.get("pvSeriesUnavailable"):
        reasons.append("价量证据序列缺失或长度不匹配，gap 帧价量方向代理未启用（direction_gate 降级）。")
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
