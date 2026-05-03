from __future__ import annotations

import itertools
import math
from typing import Any


OPTUNA_METHODS = {"bayesian", "tpe", "optuna_tpe"}
SUPPORTED_METHODS = {"grid", "random", *OPTUNA_METHODS}


def default_search_space() -> dict[str, list[Any]]:
    return {
        "maxPositions": [3, 5, 8],
        "takeProfit": [0.08, 0.12, 0.16],
        "stopLoss": [-0.04, -0.06, -0.08],
    }


def normalize_search_space(space: dict[str, Any]) -> dict[str, list[Any]]:
    if not isinstance(space, dict):
        raise ValueError("search_space must be an object")
    normalized: dict[str, list[Any]] = {}
    for key, values in space.items():
        if isinstance(values, dict):
            choices = values.get("choices") or values.get("values")
            if not isinstance(choices, list):
                raise ValueError(f"search_space.{key} range specs are not supported yet; use a choices list")
            values = choices
        if not isinstance(values, list) or not values:
            raise ValueError(f"search_space.{key} must be a non-empty list")
        normalized[str(key)] = list(values)
    if not normalized:
        raise ValueError("search_space has no optimizable parameters")
    return normalized


def candidates(space: dict[str, list[Any]]) -> list[dict[str, Any]]:
    keys = list(space.keys())
    values = [space[key] for key in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def suggest_params(trial: Any, search_space: dict[str, list[Any]]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key, values in search_space.items():
        index = trial.suggest_int(f"{key}__idx", 0, len(values) - 1)
        params[key] = values[index]
    return params


def to_trade_config(params: dict[str, Any]) -> dict[str, Any]:
    mapped = dict(params)
    mapped.pop("momentumPeriods", None)
    mapped.pop("macdFast", None)
    mapped.pop("macdSlow", None)
    mapped.pop("macdSignal", None)
    if "takeProfitPct" in mapped:
        mapped["takeProfit"] = mapped.pop("takeProfitPct")
    if "stopLossPct" in mapped:
        mapped["stopLoss"] = -abs(float(mapped.pop("stopLossPct")))
    if "initialCash" in mapped:
        mapped["initialCapital"] = mapped.pop("initialCash")
    return mapped


def to_strategy_config(params: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    if "momentumPeriods" in params:
        mapped["momentumPeriods"] = params["momentumPeriods"]
    for key in ("macdFast", "macdSlow", "macdSignal"):
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
