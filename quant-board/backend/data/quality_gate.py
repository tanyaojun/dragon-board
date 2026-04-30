from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


FORMAL_CAPTURE_MODES = {"real_time", "delayed"}
LOW_HOTLIST_THRESHOLD = 20


@dataclass
class QualityGateResult:
    passed: bool
    severity: str
    issues: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "severity": self.severity,
            "issues": self.issues,
            "stats": self.stats,
        }


def evaluate_snapshot_quality(
    frames: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
    snapshot_type: str = "half_hour",
    min_snapshot_count: int = 2,
    min_hotlist_size: int = 1,
    research_min_hotlist_size: int = LOW_HOTLIST_THRESHOLD,
    strict: bool = False,
) -> QualityGateResult:
    issues: list[str] = []
    filtered = [frame for frame in frames if frame.get("type") == snapshot_type]
    row_count_by_snapshot: dict[str, int] = {}
    for row in stock_rows:
        row_count_by_snapshot[str(row.get("snapshotId") or "")] = row_count_by_snapshot.get(str(row.get("snapshotId") or ""), 0) + 1

    stats = {
        "totalFrames": len(frames),
        "targetFrames": len(filtered),
        "minSnapshotCount": min_snapshot_count,
        "minHotlistSize": min_hotlist_size,
        "researchMinHotlistSize": research_min_hotlist_size,
        "invalidCaptureMode": 0,
        "restoredCount": 0,
        "nonMonotonicTimestamp": 0,
        "duplicateSnapshotId": 0,
        "emptyHotlistCount": 0,
        "lowHotlistCount": 0,
        "missingCoreFieldCount": 0,
        "hotlistCountMin": None,
        "hotlistCountMax": None,
        "hotlistCountAvg": None,
        "lowHotlistExamples": [],
    }

    if len(filtered) < min_snapshot_count:
        issues.append(f"{snapshot_type} snapshots below minimum {min_snapshot_count}: {len(filtered)}")

    seen: set[str] = set()
    previous_ts = -1
    hotlist_counts: list[int] = []
    for frame in sorted(filtered, key=lambda item: int(item.get("timestamp") or 0)):
        snapshot_id = str(frame.get("snapshotId") or frame.get("id") or "")
        timestamp = int(frame.get("timestamp") or 0)
        capture_mode = str(frame.get("captureMode") or "real_time")
        hotlist_count = row_count_by_snapshot.get(snapshot_id, 0)
        hotlist_counts.append(hotlist_count)
        if snapshot_id in seen:
            stats["duplicateSnapshotId"] += 1
        seen.add(snapshot_id)
        if capture_mode == "restored":
            stats["restoredCount"] += 1
        if capture_mode not in FORMAL_CAPTURE_MODES:
            stats["invalidCaptureMode"] += 1
        if timestamp <= 0:
            stats["missingCoreFieldCount"] += 1
        if previous_ts > timestamp:
            stats["nonMonotonicTimestamp"] += 1
        previous_ts = timestamp
        if hotlist_count == 0:
            stats["emptyHotlistCount"] += 1
        if hotlist_count < min_hotlist_size:
            stats["lowHotlistCount"] += 1
        elif 0 < hotlist_count < research_min_hotlist_size:
            stats["lowHotlistCount"] += 1
        if 0 <= hotlist_count < research_min_hotlist_size and len(stats["lowHotlistExamples"]) < 10:
            stats["lowHotlistExamples"].append(
                {
                    "snapshotId": snapshot_id,
                    "tradingDate": frame.get("tradingDate"),
                    "slotTime": frame.get("slotTime"),
                    "stockRowCount": hotlist_count,
                }
            )

    if hotlist_counts:
        stats["hotlistCountMin"] = min(hotlist_counts)
        stats["hotlistCountMax"] = max(hotlist_counts)
        stats["hotlistCountAvg"] = round(sum(hotlist_counts) / len(hotlist_counts), 2)

    for key, label in [
        ("invalidCaptureMode", "Invalid capture mode"),
        ("duplicateSnapshotId", "Duplicate snapshot id"),
        ("nonMonotonicTimestamp", "Non-monotonic timestamp"),
        ("missingCoreFieldCount", "Missing core field"),
    ]:
        if stats[key] > 0:
            issues.append(f"{label}: {stats[key]}")
    if stats["emptyHotlistCount"] > 0:
        issues.append(f"Empty hotlist snapshot: {stats['emptyHotlistCount']}")
    low_research_count = max(0, stats["lowHotlistCount"] - stats["emptyHotlistCount"])
    if low_research_count > 0:
        issues.append(f"Hotlist below research size {research_min_hotlist_size}: {low_research_count}")
    if stats["restoredCount"] > 0:
        issues.append(f"Restored snapshots excluded from formal analysis: {stats['restoredCount']}")

    fatal = (
        len(filtered) < min_snapshot_count
        or stats["invalidCaptureMode"] > 0
        or stats["duplicateSnapshotId"] > 0
        or stats["nonMonotonicTimestamp"] > 0
        or stats["missingCoreFieldCount"] > 0
        or stats["emptyHotlistCount"] > 0
    )
    warning = stats["lowHotlistCount"] > 0 or stats["restoredCount"] > 0
    passed = not fatal and (not strict or not warning)
    return QualityGateResult(
        passed=passed,
        severity="fail" if fatal else "warn" if warning else "pass",
        issues=issues,
        stats=stats,
    )
