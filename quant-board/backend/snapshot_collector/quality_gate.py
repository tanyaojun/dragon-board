"""Quality gate that runs BEFORE any MongoDB write.

Evaluates stock rows, source health, snapshot identity, timestamps, and
dataset rules.  Hard blockers set ``ok=False``; warnings keep ``ok=True``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .models import QualityResult

if TYPE_CHECKING:
    pass

# A-share stock codes: 6-digit strings starting with 0, 3, or 6
_A_SHARE_CODE_RE = re.compile(r"^[036]\d{5}$")

# Threshold for source-specific warnings
_MONEY_FLOW_RE = re.compile(r"money[_]?flow", re.IGNORECASE)
_L1_RE = re.compile(r"l1", re.IGNORECASE)
_DEPTH_RE = re.compile(r"depth", re.IGNORECASE)
_THEME_RE = re.compile(r"theme", re.IGNORECASE)


def evaluate_quality(
    stock_rows: list[dict],
    frames: list[dict],
    source_health: list[dict],
    sector_rows: list[dict] | None = None,
    *,
    dataset_id: str = "",
    allow_live_dataset: bool = False,
    snapshot_type: str = "",
    trading_date: str = "",
    slot_time: str = "",
    slot_timestamp_ms: int = 0,
    actual_timestamp_ms: int = 0,
    grace_minutes: int = 5,
) -> QualityResult:
    """Inspect collector inputs and return a structured quality outcome.

    **Hard blockers** (any one flips *ok* to ``False``):

    * ``empty_stock_rows`` — zero stock rows
    * ``missing_snapshot_identity`` — empty *snapshot_type*, *trading_date*,
      *slot_time* or zero *slot_timestamp_ms*
    * ``all_hotlist_sources_failed`` — every source in *source_health* has
      ``ok=False`` (or the list is empty)
    * ``invalid_stock_code`` — any stock row has a code that is empty or
      does not match the A-share format (6 digits starting with 0/3/6)
    * ``timestamp_outside_slot`` — *actual_timestamp_ms* is before
      *slot_timestamp_ms*
    * ``invalid_live_dataset_in_shadow_mode`` — *dataset_id* is
      ``"dragonboard_live"`` but *allow_live_dataset* is ``False``

    **Soft warnings** (informational, do NOT flip *ok*):

    * ``quote_provider_partial`` — some (but not all) sources failed
    * ``depth_provider_missing`` — a depth-related source failed
    * ``money_flow_estimated_l1`` — a money-flow source indicates L1
      estimation or has failed
    * ``theme_mapping_partial`` — a theme-related source failed
    * ``delayed_capture`` — *actual_timestamp_ms* exceeds the grace window
    """
    blocking: list[str] = []
    warnings: list[str] = []
    sector_rows = sector_rows or []

    # ── source_counts ───────────────────────────────────────────────────────
    ok_count = sum(1 for s in source_health if s.get("ok"))
    failed_count = len(source_health) - ok_count
    source_counts: dict[str, int] = {"ok": ok_count, "failed": failed_count}

    # ── hard blockers ───────────────────────────────────────────────────────

    # 1. empty_stock_rows
    if len(stock_rows) == 0:
        blocking.append("empty_stock_rows")

    # 2. missing_snapshot_identity
    if (
        not snapshot_type
        or not trading_date
        or not slot_time
        or slot_timestamp_ms == 0
    ):
        blocking.append("missing_snapshot_identity")

    # 3. all_hotlist_sources_failed
    if len(source_health) == 0 or all(not s.get("ok") for s in source_health):
        blocking.append("all_hotlist_sources_failed")

    # 4. invalid_stock_code
    if _has_invalid_stock_code(stock_rows):
        blocking.append("invalid_stock_code")

    # 5. timestamp_outside_slot
    if actual_timestamp_ms < slot_timestamp_ms:
        blocking.append("timestamp_outside_slot")

    # 6. invalid_live_dataset_in_shadow_mode
    if dataset_id == "dragonboard_live" and not allow_live_dataset:
        blocking.append("invalid_live_dataset_in_shadow_mode")

    # ── soft warnings ───────────────────────────────────────────────────────

    # quote_provider_partial: some failed but not all
    if failed_count > 0 and ok_count > 0:
        warnings.append("quote_provider_partial")

    # depth_provider_missing
    if _source_failed_matching(source_health, _DEPTH_RE):
        warnings.append("depth_provider_missing")

    # money_flow_estimated_l1
    if _money_flow_l1_detected(source_health) or any(
        row.get("moneyFlowEstimated") is True
        or str(row.get("moneyFlowSource") or "").lower() == "estimated_l1"
        for row in stock_rows
    ):
        warnings.append("money_flow_estimated_l1")

    # theme_mapping_partial
    if _source_failed_matching(source_health, _THEME_RE):
        warnings.append("theme_mapping_partial")

    theme_heat_sources = [
        source
        for source in source_health
        if str(source.get("source") or "") == "theme_heat"
    ]
    if any(not source.get("ok") for source in theme_heat_sources):
        warnings.append("theme_heat_blocked")
    if any(source.get("ok") for source in theme_heat_sources) and not sector_rows:
        warnings.append("theme_sector_rows_empty")
    if any(
        "sectorRowCount" in frame
        and int(frame.get("sectorRowCount") or 0) != len(sector_rows)
        for frame in frames
    ):
        warnings.append("sector_row_count_drift")

    # delayed_capture
    grace_ms = grace_minutes * 60 * 1000
    if actual_timestamp_ms > slot_timestamp_ms + grace_ms:
        warnings.append("delayed_capture")

    return QualityResult(
        ok=len(blocking) == 0,
        blocking_issues=blocking,
        warnings=warnings,
        source_counts=source_counts,
    )


# ── internal helpers ───────────────────────────────────────────────────────────


def _has_invalid_stock_code(stock_rows: list[dict]) -> bool:
    """Return ``True`` if any stock row has a missing or non-A-share code."""
    for row in stock_rows:
        code = row.get("code")
        if code is None:
            return True
        code_str = str(code).strip()
        if not _A_SHARE_CODE_RE.match(code_str):
            return True
    return False


def _source_failed_matching(
    source_health: list[dict], pattern: re.Pattern
) -> bool:
    """Return ``True`` if any source whose name matches *pattern* has ``ok=False``."""
    for s in source_health:
        source_name = str(s.get("source", ""))
        if pattern.search(source_name) and not s.get("ok"):
            return True
    return False


def _money_flow_l1_detected(source_health: list[dict]) -> bool:
    """Return ``True`` if a money-flow source indicates L1 estimation or failure."""
    for s in source_health:
        source_name = str(s.get("source", ""))
        if not _MONEY_FLOW_RE.search(source_name):
            continue
        # Source name itself suggests L1 estimation
        if _L1_RE.search(source_name):
            return True
        # Error message mentions L1
        error = str(s.get("error") or "")
        if _L1_RE.search(error):
            return True
        # Source is failing (could indicate L2→L1 fallback)
        if not s.get("ok"):
            return True
    return False
