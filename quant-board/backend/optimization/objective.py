from __future__ import annotations

from typing import Any

from backend.analysis.ranktrend.tier_monotonicity import MAX_UNKNOWN_RATE, MIN_S_SAMPLES
from backend.core.backtest import _round_or_none

# tier_risk_adjusted 惩罚权重（回测方案 §5.2）
TIER_PENALTY_HARD_CONSTRAINT = 0.5
TIER_PENALTY_S_SAMPLE = 0.2
TIER_PENALTY_UNKNOWN_RATE = 1.0


def score(result: dict[str, Any], objective: str, request: dict[str, Any] | None = None) -> float:
    if objective == "ranktrend_jump":
        total_return = float(result.get("totalReturn") or 0)
        win_rate = float(result.get("winRate") or 0)
        drawdown = abs(float(result.get("maxDrawdown") or 0))
        trade_count = int(result.get("tradeCount") or 0)
        diagnostics = result.get("matchingDiagnostics") or {}
        fallback_rate = float(diagnostics.get("snapshotFallbackRate") or 0)
        low_trade_penalty = max(0, 8 - trade_count) * 0.03
        fallback_penalty = fallback_rate * 0.12
        return total_return + win_rate * 0.03 - drawdown * 1.2 - low_trade_penalty - fallback_penalty
    if objective == "max_drawdown":
        return -abs(float(result.get("maxDrawdown") or 0))
    if objective == "sharpe":
        return float(result.get("sharpe") or 0)
    if objective == "win_rate":
        trade_count = int(result.get("tradeCount") or 0)
        low_trade_penalty = max(0, 3 - trade_count) * 0.05
        return float(result.get("winRate") or 0) - low_trade_penalty
    if objective == "win_rate_pf":
        # 阶段 4.1：win_rate 主 + 盈亏比约束（计划 §5 风险 4——纯 win_rate 会倾向紧止损刷胜率，
        # profitFactor 压制低盈亏比高胜率组合）+ 低交易数温和惩罚（验收线 tradeCount≥60 由报告筛选）。
        win_rate = float(result.get("winRate") or 0)
        trade_count = int(result.get("tradeCount") or 0)
        profit_factor = result.get("profitFactor")
        pf_penalty = 0.0
        if profit_factor is not None:
            if profit_factor < 1.0:
                pf_penalty += 0.2
            elif profit_factor < 1.3:
                pf_penalty += 0.1
        trade_penalty = max(0, 30 - trade_count) * 0.005
        return win_rate - pf_penalty - trade_penalty
    if objective in ("risk_adjusted", "tier_risk_adjusted"):
        total_return = float(result.get("totalReturn") or 0)
        drawdown = abs(float(result.get("maxDrawdown") or 0))
        sharpe = float(result.get("sharpe") or 0)
        base = total_return - drawdown * 1.5 + sharpe * 0.02
        if objective == "tier_risk_adjusted":
            # 回测方案 §5.2：档位硬约束违约/样本不足/unknown 占比惩罚（tierStats 由 trial 注入）
            return base - tier_penalty(result.get("tierStats") or {})
        return base
    return float(result.get("totalReturn") or 0)


def tier_penalty(tier_stats: dict[str, Any]) -> float:
    """档位单调性惩罚（回测方案 §5.2）。

    - 硬约束违约（passHardConstraint=False）→ +0.5；
    - S 档样本 < 30 → +0.2；
    - unknown 占比 ≥ 5% → +unknown_rate * 1.0。
    """
    if not tier_stats:
        return 0.0
    monotonicity = tier_stats.get("monotonicity") or {}
    penalty = 0.0
    if monotonicity.get("passHardConstraint") is False:
        penalty += TIER_PENALTY_HARD_CONSTRAINT
    s_count = int(((tier_stats.get("tiers") or {}).get("S") or {}).get("count") or 0)
    if s_count < MIN_S_SAMPLES:
        penalty += TIER_PENALTY_S_SAMPLE
    unknown_rate = float(tier_stats.get("unknownRate") or 0)
    if unknown_rate >= MAX_UNKNOWN_RATE:
        penalty += unknown_rate * TIER_PENALTY_UNKNOWN_RATE
    return penalty


def objective_for_phase(objective: str) -> str:
    return "risk_adjusted" if objective == "stability" else objective


def score_trial(
    train_result: dict[str, Any],
    validation_result: dict[str, Any] | None,
    objective: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    phase_objective = objective_for_phase(objective)
    train_score = score(train_result, phase_objective)
    if not validation_result:
        return {
            "score": round(train_score, 6),
            "objective": objective,
            "trainScore": round(train_score, 6),
            "validationScore": None,
            "generalizationGap": None,
            "overfitPenalty": 0.0,
            "lowTradeCountPenalty": 0.0,
            "overfitRisk": "high",
            "reason": "未设置 validation_range 或自动验证拆分，分数完全来自样本内。",
        }

    validation_score = score(validation_result, phase_objective)
    gap = train_score - validation_score
    min_validation_trades = int(request.get("min_validation_trades") or request.get("minValidationTrades") or 3)
    validation_trades = int(validation_result.get("tradeCount") or 0)
    low_trade_penalty = max(0, min_validation_trades - validation_trades) * 0.05
    overfit_penalty = max(0.0, gap) * 0.25
    if objective == "stability":
        base_score = score(validation_result, "risk_adjusted")
        final_score = base_score - overfit_penalty - low_trade_penalty
    else:
        final_score = validation_score - overfit_penalty - low_trade_penalty

    risk = "low"
    reason = "validation 与 train 表现接近。"
    if validation_trades < min_validation_trades:
        risk = "medium"
        reason = f"validation 交易数 {validation_trades} 低于最低观察数 {min_validation_trades}。"
    if (float(train_result.get("totalReturn") or 0) > 0 and float(validation_result.get("totalReturn") or 0) < 0) or gap > max(0.05, abs(train_score) * 0.75):
        risk = "high"
        reason = "train 明显优于 validation，存在参数贴合样本内的风险。"

    return {
        "score": round(final_score, 6),
        "objective": objective,
        "phaseObjective": phase_objective,
        "trainScore": round(train_score, 6),
        "validationScore": round(validation_score, 6),
        "generalizationGap": round(gap, 6),
        "overfitPenalty": round(overfit_penalty, 6),
        "lowTradeCountPenalty": round(low_trade_penalty, 6),
        "overfitRisk": risk,
        "reason": reason,
    }


def phase_public(phase_eval: dict[str, Any], objective: str) -> dict[str, Any]:
    phase_objective = objective_for_phase(objective)
    simulation = phase_eval["simulation"]
    if phase_objective == "tier_risk_adjusted":
        # phase 分数与 trial 分数口径一致：注入 metrics.tierStats 使档位惩罚生效
        simulation = {**simulation, "tierStats": (phase_eval.get("metrics") or {}).get("tierStats")}
    return {
        "runId": phase_eval["runId"],
        "run_id": phase_eval["runId"],
        "range": phase_eval["range"],
        "signalFrameRange": phase_eval["signalFrameRange"],
        "score": round(score(simulation, phase_objective), 6),
        "metrics": phase_eval["metrics"],
    }


def trial_stability(
    train_metrics: dict[str, Any],
    validation_metrics: dict[str, Any] | None,
    score_details: dict[str, Any],
) -> dict[str, Any]:
    if not validation_metrics:
        return {
            "overfitRisk": "high",
            "returnGap": None,
            "sharpeGap": None,
            "tradeCountGap": None,
            "reason": "未设置 validation 分段。",
        }
    return {
        "overfitRisk": score_details.get("overfitRisk"),
        "returnGap": _round_or_none(float(train_metrics.get("totalReturn") or 0) - float(validation_metrics.get("totalReturn") or 0)),
        "sharpeGap": _round_or_none(float(train_metrics.get("sharpe") or 0) - float(validation_metrics.get("sharpe") or 0)),
        "tradeCountGap": int(train_metrics.get("tradeCount") or 0) - int(validation_metrics.get("tradeCount") or 0),
        "reason": score_details.get("reason"),
    }


