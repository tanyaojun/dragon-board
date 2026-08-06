from __future__ import annotations

from typing import Any


DEFAULT_JUMP_SEARCH_SPACE = {
    "jumpDeltaPct": {"type": "float", "low": 8.0, "high": 22.0},
}


def _get(payload: dict[str, Any], snake: str, camel: str | None = None, default: Any = None) -> Any:
    if snake in payload:
        return payload[snake]
    camel_key = camel or snake.split("_")[0] + "".join(part.title() for part in snake.split("_")[1:])
    return payload.get(camel_key, default)


def build_jump_research_request(payload: dict[str, Any]) -> dict[str, Any]:
    fill_mode = str(_get(payload, "fill_fallback_mode", "fillFallbackMode", "fallback_penalized"))
    max_trials = int(_get(payload, "max_trials", "trials", 24))
    random_seed = int(_get(payload, "random_seed", "randomSeed", 20260430))
    search_space = _get(payload, "search_space", "searchSpace") or _get(payload, "parameter_grid", "parameterGrid") or DEFAULT_JUMP_SEARCH_SPACE
    trade_config = {
        "initialCapital": float(_get(payload, "initial_cash", "initialCash", 1000000)),
        "maxPositions": int(_get(payload, "max_positions", "maxPositions", 3)),
        "positionSize": float(_get(payload, "position_size", "positionSize", 0.2)),
        "maxHoldingBars": int(_get(payload, "max_holding_bars", "maxHoldingBars", 40)),
        "targetHoldingDays": float(_get(payload, "target_holding_days", "targetHoldingDays", 5)),
        "enforceT1": bool(_get(payload, "enforce_t1", "enforceT1", True)),
        "executionMode": "current_bar",
        "takeProfit": float(_get(payload, "take_profit", "takeProfit", 0.12)),
        "stopLoss": -abs(float(_get(payload, "stop_loss", "stopLoss", 0.05))),
        "feeRate": float(_get(payload, "fee_rate", "feeRate", 0.0003)),
        "stampTaxRate": float(_get(payload, "stamp_tax_rate", "stampTaxRate", 0.0005)),
        "slippageRate": float(_get(payload, "slippage_rate", "slippageRate", 0.001)),
        "fallbackSlippageRate": float(_get(payload, "fallback_slippage_rate", "fallbackSlippageRate", 0.002)),
        "useOrderBookPrice": True,
        "enforceLimitStatus": True,
        "enforceVolumeLimit": True,
        "enforceOrderBookQueue": True,
        "allowPartialFills": bool(_get(payload, "allow_partial_fills", "allowPartialFills", True)),
        "volumeParticipationRate": float(_get(payload, "volume_participation_rate", "volumeParticipationRate", 0.05)),
        "orderBookParticipationRate": float(_get(payload, "order_book_participation_rate", "orderBookParticipationRate", 0.3)),
        "useIntrabarStops": True,
        "fillFallbackMode": fill_mode,
        "entryStrategy": "ranktrend_jump",
    }
    return {
        "method": "tpe",
        "random_seed": random_seed,
        "max_trials": max_trials,
        "objective": "ranktrend_jump",
        "search_space": search_space,
        "strategy_name": "ranktrend_jump",
        "strategy_version": str(_get(payload, "strategy_version", "strategyVersion", "jump-research-0.1.0")),
        "dataset_id": str(_get(payload, "dataset_id", "datasetId", "")),
        "snapshot_type": str(_get(payload, "snapshot_type", "snapshotType", "half_hour")),
        "validation_mode": str(_get(payload, "validation_mode", "validationMode", "auto_split")),
        "validation_ratio": float(_get(payload, "validation_ratio", "validationRatio", 0.3)),
        "validation_warmup_bars": int(_get(payload, "validation_warmup_bars", "validationWarmupBars", 40)),
        "walk_forward": {
            "enabled": bool(_get(payload, "walk_forward", "walkForward", True)),
            "trainWindowDays": int(_get(payload, "walk_forward_train_days", "walkForwardTrainDays", 8)),
            "validationWindowDays": int(_get(payload, "walk_forward_validation_days", "walkForwardValidationDays", 2)),
            "stepDays": int(_get(payload, "walk_forward_step_days", "walkForwardStepDays", 2)),
            "topTrials": int(_get(payload, "walk_forward_top_trials", "walkForwardTopTrials", 3)),
        },
        "backtest": {
            "strategy_name": "ranktrend_jump",
            "strategy_config": {
                "momentumPeriods": [3, 5, 8, 13, 21],
                "macdFast": int(_get(payload, "macd_fast", "macdFast", 21)),
                "macdSlow": int(_get(payload, "macd_slow", "macdSlow", 34)),
                "macdSignal": int(_get(payload, "macd_signal", "macdSignal", 13)),
            },
            "trade_config": trade_config,
        },
    }


def summarize_jump_research(result: dict[str, Any], fill_fallback_mode: str = "fallback_penalized") -> dict[str, Any]:
    best = result.get("best") or {}
    metrics = best.get("metrics") or {}
    params = best.get("parameters") or {}
    artifacts = result.get("backtestArtifacts") or []
    fallback_rates: list[float] = []
    fallback_count = 0
    for artifact in artifacts:
        diagnostics = (((artifact.get("result") or {}).get("tradeSimulation") or {}).get("matchingDiagnostics") or {})
        if diagnostics:
            fallback_rates.append(float(diagnostics.get("snapshotFallbackRate") or 0))
            fallback_count += int(diagnostics.get("snapshotPriceFallbacks") or 0)
    fallback_rate = sum(fallback_rates) / len(fallback_rates) if fallback_rates else 0.0
    walk_forward = result.get("walkForward") or {}
    positive_segment_rate = float((walk_forward.get("aggregate") or {}).get("positiveReturnSegmentRate") or 0)

    warnings: list[str] = []
    risk = "low"
    if fill_fallback_mode != "strict_fill" and fallback_rate >= 0.2:
        warnings.append(f"盘口缺失回退占比偏高({fallback_rate:.0%})，实盘验证时需要优先观察买一/卖一可成交性。")
        risk = "medium"
    if walk_forward.get("enabled") and int(walk_forward.get("segmentCount") or 0) == 0:
        warnings.append("walk-forward 未生成有效分段，样本外稳定性不足。")
        risk = "high"
    elif walk_forward.get("enabled") and positive_segment_rate < 0.5:
        warnings.append(f"walk-forward 正收益分段占比只有 {positive_segment_rate:.0%}，delta 仍可能贴合样本内。")
        risk = "medium" if risk == "low" else risk
    if int(metrics.get("tradeCount") or 0) < 5:
        warnings.append("成交样本仍偏少，适合继续实盘观察，不适合自动化参数固化。")
        risk = "medium" if risk == "low" else risk

    return {
        "language": "zh-CN",
        "bestDeltaPct": params.get("jumpDeltaPct"),
        "bestMetrics": metrics,
        "fillFallbackMode": fill_fallback_mode,
        "snapshotFallbackRate": round(fallback_rate, 4),
        "snapshotFallbackCount": fallback_count,
        "walkForward": {
            "enabled": bool(walk_forward.get("enabled", False)),
            "segmentCount": int(walk_forward.get("segmentCount") or 0),
            "positiveReturnSegmentRate": positive_segment_rate,
        },
        "riskLevel": risk,
        "warnings": warnings,
        "conclusion": "该结果只作为 RankTrend Jump 实盘验证候选，不自动写回默认参数。",
    }
