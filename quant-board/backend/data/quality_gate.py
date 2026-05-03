from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


FORMAL_CAPTURE_MODES = {"real_time", "delayed"}
LOW_HOTLIST_THRESHOLD = 20

CORE_NUMERIC_FIELDS = [
    "price",
    "change",
    "volume",
    "turnover",
    "turnoverRate",
    "avgRankNum",
    "finalConfidence",
]

FATAL_NAN_FIELDS = {"price", "volume"}


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


def _check_nan_inf_for_rows(stock_rows: list[dict[str, Any]]) -> dict[str, Any]:
    nan_counts: dict[str, int] = {}
    inf_counts: dict[str, int] = {}
    fatal_nan_row_ids: list[str] = []
    fatal_inf_row_ids: list[str] = []
    for row in stock_rows:
        for field in CORE_NUMERIC_FIELDS:
            value = row.get(field)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isnan(number):
                nan_counts[field] = nan_counts.get(field, 0) + 1
                if field in FATAL_NAN_FIELDS:
                    fatal_nan_row_ids.append(str(row.get("rowId") or row.get("code") or ""))
            elif math.isinf(number):
                inf_counts[field] = inf_counts.get(field, 0) + 1
                if field in FATAL_NAN_FIELDS:
                    fatal_inf_row_ids.append(str(row.get("rowId") or row.get("code") or ""))
    return {
        "nanCounts": nan_counts,
        "infCounts": inf_counts,
        "fatalNanRowIds": fatal_nan_row_ids[:20],
        "fatalNanRowCount": len(fatal_nan_row_ids),
        "fatalInfRowIds": fatal_inf_row_ids[:20],
        "fatalInfRowCount": len(fatal_inf_row_ids),
    }


def _check_negative_values(stock_rows: list[dict[str, Any]]) -> dict[str, Any]:
    negative_price_count = 0
    non_positive_price_count = 0
    negative_volume_count = 0
    non_positive_price_examples: list[dict[str, Any]] = []
    for row in stock_rows:
        price = row.get("price")
        if price is not None:
            try:
                p = float(price)
            except (TypeError, ValueError):
                continue
            if p < 0:
                negative_price_count += 1
            if p <= 0:
                non_positive_price_count += 1
                if len(non_positive_price_examples) < 10:
                    non_positive_price_examples.append(
                        {
                            "snapshotId": row.get("snapshotId"),
                            "code": row.get("code"),
                            "price": p,
                        }
                    )
        volume = row.get("volume")
        if volume is not None:
            try:
                v = float(volume)
            except (TypeError, ValueError):
                continue
            if v < 0:
                negative_volume_count += 1
    return {
        "negativePriceCount": negative_price_count,
        "nonPositivePriceCount": non_positive_price_count,
        "negativeVolumeCount": negative_volume_count,
        "nonPositivePriceExamples": non_positive_price_examples,
    }


def _check_coverage(frames: list[dict[str, Any]], snapshot_ids_with_stocks: set[str]) -> dict[str, Any]:
    if not frames:
        return {"coverageRatio": 0.0, "coveredTradingDates": 0, "totalTradingDates": 0}
    target_snapshot_ids = {str(f.get("snapshotId") or "") for f in frames}
    covered = target_snapshot_ids & snapshot_ids_with_stocks
    coverage_ratio = len(covered) / len(target_snapshot_ids) if target_snapshot_ids else 0.0
    trading_dates = sorted({str(f.get("tradingDate") or "") for f in frames})
    covered_dates = sorted(
        {
            str(f.get("tradingDate") or "")
            for f in frames
            if str(f.get("snapshotId") or "") in covered
        }
    )
    return {
        "coverageRatio": round(coverage_ratio, 4),
        "coveredSnapshotIds": len(covered),
        "totalSnapshotIds": len(target_snapshot_ids),
        "coveredTradingDates": len(covered_dates),
        "totalTradingDates": len(trading_dates),
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

    nan_inf = _check_nan_inf_for_rows(stock_rows)
    neg_check = _check_negative_values(stock_rows)
    coverage = _check_coverage(frames, {str(r.get("snapshotId") or "") for r in stock_rows})

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
        "nanCounts": nan_inf["nanCounts"],
        "infCounts": nan_inf["infCounts"],
        "fatalNanRowCount": nan_inf["fatalNanRowCount"],
        "fatalInfRowCount": nan_inf["fatalInfRowCount"],
        "negativePriceCount": neg_check["negativePriceCount"],
        "nonPositivePriceCount": neg_check["nonPositivePriceCount"],
        "negativeVolumeCount": neg_check["negativeVolumeCount"],
        "nonPositivePriceExamples": neg_check["nonPositivePriceExamples"],
        "coverageRatio": coverage["coverageRatio"],
        "coveredTradingDates": coverage["coveredTradingDates"],
        "totalTradingDates": coverage["totalTradingDates"],
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

    fatal_nan = nan_inf["fatalNanRowCount"] > 0
    fatal_inf = nan_inf["fatalInfRowCount"] > 0
    fatal_negative_volume = neg_check["negativeVolumeCount"] > 0
    fatal_non_positive_price = neg_check["nonPositivePriceCount"] > 0

    fatal = (
        len(filtered) < min_snapshot_count
        or stats["invalidCaptureMode"] > 0
        or stats["duplicateSnapshotId"] > 0
        or stats["nonMonotonicTimestamp"] > 0
        or stats["missingCoreFieldCount"] > 0
        or stats["emptyHotlistCount"] > 0
        or fatal_nan
        or fatal_inf
        or fatal_negative_volume
        or fatal_non_positive_price
    )

    if fatal_nan:
        issues.append(f"fatal NaN in price/volume fields: {nan_inf['fatalNanRowCount']} rows")
    if fatal_inf:
        issues.append(f"fatal Infinity in price/volume fields: {nan_inf['fatalInfRowCount']} rows")
    if fatal_negative_volume:
        issues.append(f"negative volume: {neg_check['negativeVolumeCount']} rows")
    if fatal_non_positive_price:
        issues.append(f"non-positive price: {neg_check['nonPositivePriceCount']} rows")

    nan_warnings = {k: v for k, v in nan_inf["nanCounts"].items() if k not in FATAL_NAN_FIELDS}
    inf_warnings = nan_inf["infCounts"]
    if nan_warnings:
        issues.append(f"NaN in non-fatal fields: {nan_warnings}")
    if inf_warnings:
        issues.append(f"Infinity values: {inf_warnings}")

    warning = (
        stats["lowHotlistCount"] > 0
        or stats["restoredCount"] > 0
        or bool(nan_warnings)
        or bool(inf_warnings)
    )
    passed = not fatal and (not strict or not warning)
    return QualityGateResult(
        passed=passed,
        severity="fail" if fatal else "warn" if warning else "pass",
        issues=issues,
        stats=stats,
    )
