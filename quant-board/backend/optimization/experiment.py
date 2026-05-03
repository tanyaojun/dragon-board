from __future__ import annotations

from typing import Any


def experiment_summary(
    split: dict[str, Any],
    request: dict[str, Any],
    total_candidate_count: int,
    executed_candidate_count: int,
    trials: list[dict[str, Any]],
    best: dict[str, Any] | None,
    walk_forward: dict[str, Any] | None = None,
    data_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    warnings = list(split.get("warnings") or [])
    has_validation = bool(split["metadata"].get("hasValidation"))
    has_walk_forward = bool((walk_forward or {}).get("segments"))
    if not has_validation:
        if has_walk_forward:
            overfit_risk = {"level": "medium", "reason": "未设置 validation_range，但已执行 walk-forward 分段复核。"}
        else:
            overfit_risk = {"level": "high", "reason": "未设置 validation_range 或自动拆分，结果只适合找候选参数。"}
            warnings.append("当前优化没有样本外验证，不能直接据此定参数。")
    else:
        best_risk = (((best or {}).get("scoreDetails") or {}).get("overfitRisk") or "medium")
        overfit_risk = {"level": best_risk, "reason": (((best or {}).get("scoreDetails") or {}).get("reason") or "已执行 train/validation 分段验证。")}
    warnings.extend((walk_forward or {}).get("warnings") or [])
    quality = data_quality or {}
    if quality.get("warnings"):
        warnings.extend(str(item) for item in quality.get("warnings") or [])
    if quality.get("researchGrade") in ("blocked", "degraded") and overfit_risk["level"] == "low":
        overfit_risk = {
            "level": "medium",
            "reason": f"{overfit_risk['reason']} 数据质量为 {quality.get('researchGrade')}，优化结论需降权。",
        }
    return {
        "datasetId": request.get("dataset_id"),
        "snapshotType": request.get("snapshot_type"),
        "method": request.get("method"),
        "objective": request.get("objective"),
        "randomSeed": request.get("random_seed"),
        "totalCandidateCount": total_candidate_count,
        "executedCandidateCount": executed_candidate_count,
        "completedTrialCount": len([trial for trial in trials if trial.get("status") == "completed"]),
        "failedTrialCount": len([trial for trial in trials if trial.get("status") == "failed"]),
        "split": split["metadata"],
        "overfitRisk": overfit_risk,
        "walkForward": {
            "enabled": bool((walk_forward or {}).get("enabled")),
            "segmentCount": int((walk_forward or {}).get("segmentCount") or 0),
        },
        "warnings": warnings,
    }
