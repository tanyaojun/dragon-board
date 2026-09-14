from __future__ import annotations

import math
from typing import Any
from ..engine.config import RankTrendConfig
from ..engine.primitives import clamp, _is_finite_number

def analyze_risk(current_percentile: float, technical: dict[str, Any], cycle: dict[str, Any], zlje: float | None, zljzb: float | None, volume_ratio: float | None, config: RankTrendConfig | None = None) -> dict[str, Any]:
    c = config or RankTrendConfig()
    metrics = cycle["metrics"]
    # 加减分阶梯 2026-09-14 参数化（默认值=原硬编码，golden 不漂移）
    overheat = 0.0
    overheat += max(0, current_percentile - c.riskOverheatPercentileMin) * c.riskOverheatPercentileSlope
    overheat += max(0, metrics["rankShock"]) * c.riskOverheatShockSlope
    if metrics["rankVelocity"] > 0:
        overheat += min(c.riskOverheatVelocityCap, metrics["rankVelocity"] * c.riskOverheatVelocitySlope)
    if metrics["rankAcceleration"] < 0:
        overheat += min(c.riskOverheatAccelCap, abs(metrics["rankAcceleration"]) * c.riskOverheatAccelSlope)
    if technical["macd"]["histogram"] < 0:
        overheat += min(c.riskOverheatMacdCap, abs(technical["macd"]["histogram"]) * c.riskOverheatMacdSlope)
    if technical["signals"]["direction"]["signal"] == "buy":
        overheat += c.riskOverheatDirectionBuyBonus
    if technical["signals"]["acceleration"]["signal"] != "buy":
        overheat += c.riskOverheatAccelMissPenalty
    if technical["signals"]["zeroCross"]["signal"] == "sell":
        overheat += c.riskOverheatZeroCrossSellPenalty
    overheat = clamp(overheat, 0, 100)

    hot_attention = current_percentile >= c.riskHotAttentionPercentileMin or metrics["rankVelocity"] > 0
    divergence = 0.0
    if hot_attention:
        divergence += c.riskDivergenceHotBonus
    if hot_attention and zlje is not None and zlje <= 0:
        divergence += c.riskDivergenceHotOutflowPenalty
    if hot_attention and zljzb is not None and zljzb <= 0:
        divergence += c.riskDivergenceHotDumpPenalty
    if volume_ratio is not None and volume_ratio >= c.riskDivergenceVolumeHighMin and zlje is not None and zlje <= 0:
        divergence += c.riskDivergenceVolumeOutflowPenalty
    if volume_ratio is not None and volume_ratio >= c.riskDivergenceVolumeHighMin and zljzb is not None and zljzb <= 0:
        divergence += c.riskDivergenceVolumeDumpPenalty
    if metrics["rankShock"] > c.riskDivergenceShockMin and zlje is not None and zlje <= 0:
        divergence += c.riskDivergenceShockOutflowPenalty
    if cycle["stage"] in ("crowded", "reversal") and zlje is not None and zlje <= 0:
        divergence += c.riskDivergenceStageOutflowPenalty
    if zlje is not None and zlje > 0:
        divergence -= c.riskDivergenceInflowRelief
    if zljzb is not None and zljzb > 0:
        divergence -= c.riskDivergenceDumpRelief
    if volume_ratio is not None and 0 < volume_ratio < c.riskDivergenceShrinkVolumeMax and zlje is not None and zlje > 0:
        divergence -= c.riskDivergenceShrinkInflowRelief
    divergence = clamp(divergence, 0, 100)

    stage = cycle["stage"]
    # 阶段乘数 2026-09-14 参数化（list 按 ignition/expansion/crowded/reversal/cooling 顺序）
    _stage_order = ("ignition", "expansion", "crowded", "reversal", "cooling")
    over_multipliers = list(c.riskOverheatStageMultipliers or [])
    div_multipliers = list(c.riskDivergenceStageMultipliers or [])
    over_mult = dict(zip(_stage_order, over_multipliers)) if len(over_multipliers) == 5 else {"ignition": 0.3, "expansion": 0.55, "crowded": 0.85, "reversal": 1, "cooling": 0.3}
    div_mult = dict(zip(_stage_order, div_multipliers)) if len(div_multipliers) == 5 else {"ignition": 0.35, "expansion": 0.65, "crowded": 0.9, "reversal": 1, "cooling": 0.35}
    over_sev = clamp((overheat - c.riskOverheatOffset) / c.riskOverheatScale, 0, 1) * over_mult.get(stage, 1)
    div_sev = clamp((divergence - c.riskDivergenceOffset) / c.riskDivergenceScale, 0, 1) * div_mult.get(stage, 1)
    pressure = clamp(c.riskPressureWeights[0] * over_sev + c.riskPressureWeights[1] * div_sev, 0, 1)
    return {
        "overheat": {"score": overheat, "signal": "sell" if overheat >= c.riskOverheatSellMin and stage in ("crowded", "reversal") else "hold" if overheat >= c.riskOverheatHoldMin else "buy", "severity": over_sev},
        "divergence": {"score": divergence, "signal": "sell" if divergence >= c.riskDivergenceSellMin else "hold" if divergence >= c.riskDivergenceHoldMin else "buy", "severity": div_sev},
        "pressure": pressure,
        "synergy": 1 if over_sev >= c.riskSynergyOverheatSevMin and div_sev >= c.riskSynergyDivergenceSevMin else 0,
    }


REGIME_STAGE_ADJUST = {"高潮": 8, "发酵": 5, "启动": 0, "退潮": -6, "冰点": -8}
REGIME_STRONG_SCORE = 70.0
REGIME_NORMAL_SCORE = 50.0
REGIME_WEAK_SCORE = 30.0
REGIME_LIMIT_UP_CHANGE = 9.8
REGIME_LIMIT_UP_BASE_SHARE = 0.08


def market_regime(frame: dict[str, Any], config: RankTrendConfig | None = None) -> dict[str, Any]:
    """热榜池口径五因子市场环境：池内上涨占比、涨停强度、量能活跃、资金正向、情绪阶段参考。

    全A 涨跌家数/成交额不再进入打分（分化行情下与热榜池赚钱效应脱节）。
    权重为基线 v1，样本验证后冻结（见 P2 计划 Phase 8）；五因子系数与状态阈值
    2026-09-14 参数化（config.regime*，默认值=原硬编码，golden 不漂移）；
    config=None 时按默认配置（等价原行为，既有调用点不受影响）。

    2026-08-18 口径统一（环境门优化第 1 阶）：情绪阶段改读 hotlistSentiment
    （frame.hotlistSentiment.stage/riskLevel——热榜池同口径），全市场 sentiment 降为对照
    （仅保留在 reasons/observation，不再进入打分）。riskLevel 高 → 风险修正减分。
    """
    c = config or RankTrendConfig()
    context = frame.get("marketContext") or {}
    payload = context.get("payload") or {}
    sentiment = context.get("sentiment") or payload.get("sentiment") or {}
    hotlist_sentiment = frame.get("hotlistSentiment")
    hotlist_missing = not isinstance(hotlist_sentiment, dict)
    stocks = [s for s in (frame.get("stocks") or []) if isinstance(s, dict)]
    pool_size = len(stocks)
    if pool_size == 0:
        return {"state": "normal", "score": c.regimeNormalScore, "reasons": ["市场环境数据不足，按中性处理"]}

    score = c.regimeBaseScore
    reasons: list[str] = []

    valid_changes = [float(s.get("change")) for s in stocks if _is_finite_number(s.get("change"))]
    if valid_changes:
        up_share = sum(1 for value in valid_changes if value > 0) / len(valid_changes)
        score += clamp((up_share - 0.5) * c.regimeUpShareSlope, c.regimeUpShareFloor, c.regimeUpShareCap)
        reasons.append(f"池内上涨{up_share * 100:.0f}%")
        limit_share = sum(1 for value in valid_changes if value >= c.regimeLimitUpChange) / len(valid_changes)
        score += clamp((limit_share - c.regimeLimitUpBaseShare) * c.regimeLimitUpSlope, c.regimeLimitUpFloor, c.regimeLimitUpCap)
        reasons.append(f"池内涨停{limit_share * 100:.0f}%")
    else:
        reasons.append("池内涨跌幅缺失")

    valid_volume = [float(s.get("volumeRatio")) for s in stocks if _is_finite_number(s.get("volumeRatio"))]
    if valid_volume:
        active_share = sum(1 for value in valid_volume if value >= c.regimeActiveVolumeMin) / len(valid_volume)
        score += clamp((active_share - c.regimeActiveBaseShare) * c.regimeActiveSlope, c.regimeActiveFloor, c.regimeActiveCap)
        reasons.append(f"量能活跃{active_share * 100:.0f}%")
    valid_money = [float(s.get("zlje")) for s in stocks if _is_finite_number(s.get("zlje"))]
    if valid_money:
        money_share = sum(1 for value in valid_money if value > 0) / len(valid_money)
        score += clamp((money_share - 0.5) * c.regimeMoneySlope, c.regimeMoneyFloor, c.regimeMoneyCap)
        reasons.append(f"热榜资金正向{money_share * 100:.0f}%")

    # 2026-08-18 口径统一：情绪阶段用热榜池同源 hotlistSentiment（stage），全市场 sentiment 仅作对照。
    # 缺失 → 标注 missing，不阻断打分（fail-visible）。
    phase = ""
    risk_adjust = 0.0
    if hotlist_missing:
        reasons.append("热榜情绪缺失（regime 情绪阶段按中性）")
    else:
        phase = str(hotlist_sentiment.get("stage") or hotlist_sentiment.get("phase") or "").strip()
        hotlist_risk = str(hotlist_sentiment.get("riskLevel") or "").strip()
        if hotlist_risk in ("高", "high", "HIGH"):
            risk_adjust = c.regimeRiskHighAdjust
            reasons.append(f"热榜情绪风险={hotlist_risk}（{c.regimeRiskHighAdjust:+g}）")
        elif hotlist_risk in ("低", "low", "LOW"):
            risk_adjust = c.regimeRiskLowAdjust
            reasons.append(f"热榜情绪风险={hotlist_risk}（{c.regimeRiskLowAdjust:+g}）")
        conf = hotlist_sentiment.get("confidence")
        if conf is not None:
            reasons.append(f"热榜情绪置信={conf}")
    if phase.endswith("期"):
        phase = phase[:-1]
    if phase:
        _adjust_order = ("高潮", "发酵", "启动", "退潮", "冰点")
        adjust_values = list(c.regimeStageAdjust or [])
        stage_adjust = dict(zip(_adjust_order, adjust_values)) if len(adjust_values) == 5 else dict(REGIME_STAGE_ADJUST)
        score += stage_adjust.get(phase, 0)
        reasons.append(f"热榜情绪阶段{phase}")
    score += risk_adjust
    # 全市场 sentiment 仅作对照（不再打分）
    market_phase = str(sentiment.get("phaseName") or sentiment.get("phase") or "").strip()
    if market_phase:
        reasons.append(f"全市场情绪对照={market_phase}")

    # WP1c：stale 情绪回退标注（fail-visible，不改打分——分数构成见上）
    if str(frame.get("hotlistSentimentStatus") or "") == "stale":
        reasons.append("热榜情绪为前日 stale 口径（as-of 回退）")

    score = clamp(score, 0, 100)
    state = (
        "strong" if score >= c.regimeStrongScore
        else "normal" if score >= c.regimeNormalScore
        else "weak" if score >= c.regimeWeakScore
        else "retreat"
    )
    return {"state": state, "score": round(score, 1), "reasons": reasons}
