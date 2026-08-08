from __future__ import annotations
from pathlib import Path
from typing import Any
from backend.core.utils import json_loads
from backend.services.efficacy import compute_execution_quality




def read_checkpoint_history(
    jsonl_path: str | Path,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Read recent checkpoint records from long_test_runs.jsonl."""
    path = Path(jsonl_path)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json_loads(line.strip())
                if record and record.get("checkpointId"):
                    records.append(record)
            except Exception:
                continue
    return records[-limit:] if len(records) > limit else records


def select_longtest_baseline_slots(
    baselines: list[dict[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    """Map legacy/new long-test baselines into trend-page slots."""

    def pick(predicate: Any) -> dict[str, Any] | None:
        for baseline in baselines:
            if predicate(baseline):
                return baseline
        return None

    def label_of(baseline: dict[str, Any]) -> str:
        return str(baseline.get("label") or "")

    def lower_label_of(baseline: dict[str, Any]) -> str:
        return label_of(baseline).lower()

    def snapshot_type_of(baseline: dict[str, Any]) -> str:
        return str(baseline.get("snapshotType") or "").lower()

    def execution_mode_of(baseline: dict[str, Any]) -> str:
        return str(baseline.get("executionMode") or "").lower()

    def has_trade_metrics(baseline: dict[str, Any]) -> bool:
        return baseline.get("totalReturn") is not None or baseline.get("tradeCount") is not None

    h1 = pick(lambda baseline: label_of(baseline) == "H1_half_hour_current_bar")
    if h1 is None:
        h1 = pick(
            lambda baseline: ("_E2_" in label_of(baseline) or label_of(baseline).startswith("E2_"))
            and "strict_fill" not in lower_label_of(baseline)
        )
    if h1 is None:
        h1 = pick(
            lambda baseline: execution_mode_of(baseline) == "current_bar"
            and snapshot_type_of(baseline) == "half_hour"
            and "signal_forward" not in lower_label_of(baseline)
            and has_trade_metrics(baseline)
        )

    h2 = pick(lambda baseline: label_of(baseline) == "H2_half_hour_next_bar")
    if h2 is None:
        h2 = pick(lambda baseline: "_E3_" in label_of(baseline) or label_of(baseline).startswith("E3_"))
    if h2 is None:
        h2 = pick(lambda baseline: "strict_fill" in lower_label_of(baseline))
    if h2 is None:
        h2 = pick(
            lambda baseline: execution_mode_of(baseline) == "next_bar"
            and snapshot_type_of(baseline) == "half_hour"
            and has_trade_metrics(baseline)
        )

    q1 = pick(lambda baseline: label_of(baseline) == "Q1_quarter_hour_next_bar")
    if q1 is None:
        q1 = pick(lambda baseline: snapshot_type_of(baseline) == "quarter_hour")

    l1 = pick(
        lambda baseline: "signal_forward" in lower_label_of(baseline)
        and isinstance(baseline.get("layer1SignalEfficacy"), dict)
    )
    if l1 is None:
        l1 = pick(
            lambda baseline: ("_E1_" in label_of(baseline) or label_of(baseline).startswith("E1_"))
            and isinstance(baseline.get("layer1SignalEfficacy"), dict)
        )
    if l1 is None:
        l1 = pick(lambda baseline: isinstance(baseline.get("layer1SignalEfficacy"), dict))
    if l1 is None:
        l1 = h1

    return {
        "h1": h1,
        "h2": h2,
        "q1": q1,
        "l1": l1,
    }


def compute_checkpoint_layer2(baselines: list[dict[str, Any]]) -> dict[str, Any] | None:
    slots = select_longtest_baseline_slots(baselines)
    h1 = slots.get("h1")
    h2 = slots.get("h2")
    for baseline in (h1, h2):
        if isinstance(baseline, dict):
            layer2 = baseline.get("layer2ExecutionQuality")
            if isinstance(layer2, dict) and layer2.get("layer2Status"):
                return layer2
    if not isinstance(h1, dict) or not isinstance(h2, dict):
        return None
    if h1.get("totalReturn") is None or h2.get("totalReturn") is None:
        return None
    return compute_execution_quality(h1_summary=h1, h2_summary=h2)


def summarize_longtest_slot_label(baseline: dict[str, Any] | None) -> str | None:
    if not isinstance(baseline, dict):
        return None
    label = str(baseline.get("label") or "")
    if not label:
        return None
    if label.startswith("V5_E1_"):
        return "V5 E1"
    if label.startswith("V5_E2_"):
        return "V5 E2"
    if label.startswith("V5_E3_"):
        return "V5 E3"
    if label.startswith("H1_"):
        return "H1"
    if label.startswith("H2_"):
        return "H2"
    if label.startswith("Q1_"):
        return "Q1"
    if "_E1_" in label or label.startswith("E1_"):
        return "E1"
    if "_E2_" in label or label.startswith("E2_"):
        return "E2"
    if "_E3_" in label or label.startswith("E3_"):
        return "E3"
    return label


def check_layer1_meltdown(
    history: list[dict[str, Any]],
    label_filter: str = "H1_half_hour_current_bar",
    metric_key: str = "layer1SignalEfficacy",
) -> dict[str, Any]:
    """Check if Layer 1 has been red for 3+ consecutive checkpoints (meltdown)."""
    if len(history) < 3:
        return {
            "meltdown": False,
            "consecutiveRedPeriods": 0,
            "diagnostics": "insufficient_history",
            "metricKey": metric_key,
        }

    statuses: list[str] = []
    selected_label: str | None = None
    selected_slot: str | None = None
    for record in history:
        baselines = record.get("baselines") or []
        baseline = next((b for b in baselines if b.get("label") == label_filter), None)
        slot = "label"
        if baseline is None and metric_key == "layer1SignalEfficacy":
            baseline = select_longtest_baseline_slots(baselines).get("l1")
            slot = "l1"
        if not baseline:
            continue
        l1 = baseline.get(metric_key) or {}
        if not isinstance(l1, dict):
            continue
        selected_label = str(baseline.get("label") or "") or selected_label
        selected_slot = slot
        statuses.append(str(l1.get("layer1Status") or "unknown"))

    consecutive_red = 0
    for status in reversed(statuses):
        if status == "red":
            consecutive_red += 1
        else:
            break

    return {
        "meltdown": consecutive_red >= 3,
        "consecutiveRedPeriods": consecutive_red,
        "statuses": statuses[-6:],
        "selectedLabel": selected_label,
        "selectedSlot": selected_slot,
        "metricKey": metric_key,
        "recommendation": (
            "触发策略结构性复审：连续 3 期方向精度不达标，建议检查市场状态归属、信号有效性和执行方式"
            if consecutive_red >= 3
            else None
        ),
    }


def check_layer3_trend(
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check Layer 3 alignment trend across recent checkpoints."""
    if len(history) < 2:
        return {"greenLight": False, "diagnostics": "insufficient_history"}

    statuses: list[str] = []
    for record in history[-2:]:
        l3 = record.get("layer3Alignment") or {}
        statuses.append(str(l3.get("alignmentStatus") or "unknown"))

    consecutive_sufficient = all(s == "sufficient" for s in statuses)

    return {
        "greenLight": consecutive_sufficient,
        "recentStatuses": statuses,
        "recommendation": (
            "连续 2 期对齐充足，Layer 3 绿灯"
            if consecutive_sufficient
            else None
        ),
    }
