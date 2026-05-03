from __future__ import annotations

import math
from typing import Any

from backend.optimization.search_space import freeze


def parameter_stability(trials: list[dict[str, Any]]) -> dict[str, Any]:
    if not trials:
        return {"topTrialCount": 0, "parameters": [], "warnings": ["没有完成的 trial，无法做参数稳定性分析。"]}
    top_count = max(1, min(5, math.ceil(len(trials) * 0.2)))
    top_trials = trials[:top_count]
    parameter_keys = sorted({key for trial in top_trials for key in (trial.get("parameters") or {}).keys()})
    rows = []
    warnings = []
    for key in parameter_keys:
        values = [(trial.get("parameters") or {}).get(key) for trial in top_trials]
        frozen_counts: dict[str, int] = {}
        for value in values:
            frozen_counts[freeze(value)] = frozen_counts.get(freeze(value), 0) + 1
        numeric_values = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(float(value))]
        row: dict[str, Any] = {
            "key": key,
            "bestValue": (top_trials[0].get("parameters") or {}).get(key),
            "uniqueCount": len(frozen_counts),
            "topValues": [{"value": value, "count": count} for value, count in sorted(frozen_counts.items(), key=lambda item: item[1], reverse=True)],
        }
        if len(numeric_values) == len(values) and numeric_values:
            row.update(
                {
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "mean": round(sum(numeric_values) / len(numeric_values), 6),
                }
            )
        if len(frozen_counts) == len(values) and len(values) > 1:
            warnings.append(f"top {top_count} 中 {key} 未形成集中取值。")
        rows.append(row)
    scores = [float(trial.get("score") or 0) for trial in top_trials]
    return {
        "topTrialCount": top_count,
        "topTrialIds": [trial.get("trialId") for trial in top_trials],
        "scoreSpread": round(max(scores) - min(scores), 6) if scores else None,
        "parameters": rows,
        "warnings": warnings,
    }
