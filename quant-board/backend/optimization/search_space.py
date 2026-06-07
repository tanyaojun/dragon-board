from __future__ import annotations

import itertools as _itertools
import math
import random
from typing import Any


OPTUNA_METHODS = {"bayesian", "tpe", "optuna_tpe"}
SUPPORTED_METHODS = {"grid", "random", *OPTUNA_METHODS}


class _ItertoolsProxy:
    product = staticmethod(_itertools.product)


itertools = _ItertoolsProxy()


def default_search_space() -> dict[str, list[Any]]:
    """RankTrend V2 完整搜索空间 —— 覆盖信号层、分层阈值和交易层。

    compose_decision（MACD/动量合成信号）与 compose_strategy（生命周期分层）
    已通过 finalSignal 接入交易链路，本空间覆盖两阶段核心参数。
    """
    return {
        # ── compose_decision 信号层 ──
        "macdFast": [8, 13, 21],
        "macdSlow": [21, 34, 55],
        "macdSignal": [5, 8, 13],
        "buyScoreThreshold": [0.06, 0.12, 0.18],
        # ── compose_strategy 分层阈值（A_MAIN / B_IGNITION 核心入口）──
        "tierAMainMidMomentumMin": [2.0, 4.0, 6.0],
        "tierAMainShortMomentumMin": [-2.0, -1.0, 0.0],
        "tierBIgnitionShortMomentumMin": [1.5, 3.0, 5.0],
        "tierBIgnitionAccelMin": [0.0, 0.5, 1.0],
        "tierBIgnitionRiskPressureMax": [0.50, 0.65, 0.80],
        # ── 交易层 ──
        "maxPositions": [3, 5, 8],
        "takeProfit": [0.08, 0.12, 0.16],
        "stopLoss": [-0.04, -0.06, -0.08],
    }


def theme_search_space() -> dict[str, list[Any]]:
    """V12 题材策略优化搜索空间。

    首批完整合同覆盖因子权重、风险阈值、生命周期阈值、股票暴露阈值和交易参数。
    其中可映射到 ThemeTrendConfig 的参数会进入引擎，其余参数用于策略执行/报告敏感度。
    """
    return {
        "momentumWeight": [0.18, 0.24, 0.3],
        "breadthWeight": [0.14, 0.18, 0.22],
        "fundWeight": [0.1, 0.14, 0.18],
        "leadershipWeight": [0.12, 0.16, 0.2],
        "correlationWeight": [0.06, 0.1, 0.14],
        "persistenceWeight": [0.08, 0.12, 0.16],
        "crowdingWarnThreshold": [60, 65, 70],
        "crowdingBlockThreshold": [70, 75, 80],
        "divergenceBlockThreshold": [65, 70, 75],
        "ignitionMinMomentum": [45, 50, 55],
        "expansionMinBreadth": [55, 60, 65],
        "mainlineMinPersistence": [65, 70, 75],
        "coolingMaxMomentum": [30, 35, 40],
        "leaderMinContribution": [8, 12, 16],
        "coreMinContribution": [5, 8, 12],
        "noiseMaxContribution": [2, 3, 5],
        "maxThemeExposure": [0.35, 0.45, 0.55],
        "maxPositions": [3, 5, 8],
        "takeProfitPct": [0.08, 0.12, 0.16],
        "stopLossPct": [0.04, 0.06, 0.08],
        "crowdedRiskThreshold": [70, 75, 80],
        "mainlineHeatThreshold": [70, 75, 80],
        "mainlineMomentumThreshold": [65, 70, 75],
        "expansionMomentumThreshold": [55, 60, 65],
        "ignitionMomentumThreshold": [45, 50, 55],
        "coolingMomentumThreshold": [30, 35, 40],
        "reversalMomentumThreshold": [22, 25, 28],
        "minFrames": [2, 3, 5],
    }


def theme_confluence_search_space() -> dict[str, list[Any]]:
    space = theme_search_space()
    space.update(
        {
            "rankTrendWeight": [0.55, 0.65, 0.75],
            "themeWeight": [0.25, 0.35, 0.45],
            "leaderMinContribution": [10, 14, 18],
            "hotlistMinConfluenceScore": [65, 75, 85],
        }
    )
    return space


def theme_parameter_groups(profile: str = "theme_trend") -> list[str]:
    groups = [
        "factor_weights",
        "risk_thresholds",
        "lifecycle_thresholds",
        "stock_exposure_thresholds",
        "trade_config",
    ]
    if profile == "theme_confluence":
        groups.append("confluence_weights")
    return groups


def normalize_search_space(space: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(space, dict):
        raise ValueError("search_space must be an object")
    normalized: dict[str, list[Any]] = {}
    for key, values in space.items():
        if isinstance(values, dict):
            choices = values.get("choices") or values.get("values")
            range_type = str(values.get("type") or "").strip().lower()
            if range_type in {"float", "int"}:
                if "low" not in values or "high" not in values:
                    raise ValueError(f"search_space.{key} range spec must include low and high")
                low = float(values["low"])
                high = float(values["high"])
                if not math.isfinite(low) or not math.isfinite(high) or high < low:
                    raise ValueError(f"search_space.{key} range spec has invalid low/high")
                normalized[str(key)] = {
                    "type": range_type,
                    "low": int(low) if range_type == "int" else low,
                    "high": int(high) if range_type == "int" else high,
                    "step": values.get("step"),
                    "log": bool(values.get("log", False)),
                }
                continue
            if not isinstance(choices, list):
                raise ValueError(f"search_space.{key} range specs must use type=float/int or a choices list")
            values = choices
        if not isinstance(values, list) or not values:
            raise ValueError(f"search_space.{key} must be a non-empty list")
        normalized[str(key)] = list(values)
    if not normalized:
        raise ValueError("search_space has no optimizable parameters")
    return normalized


def _discrete_values(values: Any) -> list[Any]:
    if isinstance(values, list):
        return values
    if not isinstance(values, dict):
        return [values]
    low = values.get("low")
    high = values.get("high")
    if values.get("type") == "int":
        return [int(low), int(high)] if int(low) != int(high) else [int(low)]
    return [float(low), float(high)] if float(low) != float(high) else [float(low)]


def candidate_count(space: dict[str, Any]) -> int:
    total = 1
    for values in space.values():
        total *= len(_discrete_values(values))
    return total


def candidate_at_index(space: dict[str, Any], index: int) -> dict[str, Any]:
    keys = list(space.keys())
    values = [_discrete_values(space[key]) for key in keys]
    if not keys:
        return {}

    selected: list[Any] = [None] * len(keys)
    remainder = index
    for i in range(len(keys) - 1, -1, -1):
        options = values[i]
        size = len(options)
        choice_index = remainder % size
        remainder //= size
        selected[i] = options[choice_index]
    return dict(zip(keys, selected))


def select_candidates(space: dict[str, Any], max_count: int, method: str = "random", random_seed: int = 0) -> list[dict[str, Any]]:
    total = candidate_count(space)
    if total <= 0:
        return []
    limit = min(max(1, max_count), total)
    if total <= limit or method == "grid":
        return [candidate_at_index(space, idx) for idx in range(limit)]

    rng = random.Random(random_seed)
    indices = rng.sample(range(total), limit)
    return [candidate_at_index(space, idx) for idx in indices]


def candidates(space: dict[str, Any]) -> list[dict[str, Any]]:
    keys = list(space.keys())
    values = [_discrete_values(space[key]) for key in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def search_space_mode(space: dict[str, Any]) -> str:
    return "continuous" if any(isinstance(values, dict) for values in space.values()) else "discrete"


def suggest_params(trial: Any, search_space: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key, values in search_space.items():
        if isinstance(values, dict):
            if values.get("type") == "float":
                params[key] = trial.suggest_float(
                    key,
                    float(values["low"]),
                    float(values["high"]),
                    step=values.get("step"),
                    log=bool(values.get("log", False)),
                )
                continue
            if values.get("type") == "int":
                step = int(values["step"]) if values.get("step") else 1
                params[key] = trial.suggest_int(key, int(values["low"]), int(values["high"]), step=step)
                continue
        index = trial.suggest_int(f"{key}__idx", 0, len(values) - 1)
        params[key] = values[index]
    return params


def to_trade_config(params: dict[str, Any]) -> dict[str, Any]:
    mapped = dict(params)
    for key in _STRATEGY_PARAM_KEYS:
        mapped.pop(key, None)
    if "takeProfitPct" in mapped:
        mapped["takeProfit"] = mapped.pop("takeProfitPct")
    if "stopLossPct" in mapped:
        mapped["stopLoss"] = -abs(float(mapped.pop("stopLossPct")))
    if "initialCash" in mapped:
        mapped["initialCapital"] = mapped.pop("initialCash")
    return mapped


_STRATEGY_PARAM_KEYS = (
    "momentumPeriods",
    "macdFast",
    "macdSlow",
    "macdSignal",
    "jumpDeltaPct",
    "buyScoreThreshold",
    "sellScoreThreshold",
    "directionWeight",
    "accelerationWeight",
    "crossWeight",
    "macdWeight",
    "tierAMainMidMomentumMin",
    "tierAMainShortMomentumMin",
    "tierAMainDivergenceSeverityMax",
    "tierBIgnitionShortMomentumMin",
    "tierBIgnitionAccelMin",
    "tierBIgnitionRiskPressureMax",
    "tierCrowdedLongMomentumMin",
    "tierCrowdedAccelMax",
    "tierCrowdedRiskPressureMin",
    "tierExitRiskShortMomentumMax",
    "tierExitRiskAccelMax",
    "tierExitRiskPressureMin",
)


def to_strategy_config(params: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for key in _STRATEGY_PARAM_KEYS:
        if key in params:
            mapped[key] = params[key]
    return mapped


def freeze(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(f"{key}:{freeze(value[key])}" for key in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(freeze(item) for item in value) + "]"
    return repr(value)


def score_value(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return -1_000_000_000.0
    return score if math.isfinite(score) else -1_000_000_000.0
