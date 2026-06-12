"""Tests for snapshot_collector quality_gate module — Task 4: Quality Gate.

Covers all hard blockers and soft warnings per the design contract.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.snapshot_collector.models import QualityResult
from backend.snapshot_collector.quality_gate import evaluate_quality

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

# ── helpers ────────────────────────────────────────────────────────────────────


def _make_ts(date_str: str, time_str: str) -> int:
    """Convert a date and time in Asia/Shanghai to epoch milliseconds."""
    dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return int(dt.timestamp() * 1000)


def _make_stock_row(code: str, **extra: object) -> dict:
    """Build a minimal stock row dict with a stock code field."""
    return {"code": code, **extra}


def _make_source_health(source: str, ok: bool, error: str | None = None) -> dict:
    """Build a SourceHealth-like dict."""
    d: dict = {"source": source, "ok": ok}
    if error is not None:
        d["error"] = error
    return d


def _make_frame(**overrides: object) -> dict:
    """Build a minimal frame dict."""
    d: dict = {
        "snapshotId": "half_hour:2026-06-11:15:00",
        "type": "half_hour",
        "tradingDate": "2026-06-11",
        "slotTime": "15:00",
    }
    d.update(overrides)
    return d


# Reusable valid fixtures
VALID_STOCK_ROWS = [
    _make_stock_row("600001"),
    _make_stock_row("000001"),
    _make_stock_row("300001"),
]

VALID_SOURCE_HEALTH = [
    _make_source_health("eastmoney", True),
    _make_source_health("xueqiu", True),
]

VALID_FRAMES = [_make_frame()]

SLOT_TS = _make_ts("2026-06-11", "15:00")

VALID_IDENTITY = {
    "snapshot_type": "half_hour",
    "trading_date": "2026-06-11",
    "slot_time": "15:00",
    "slot_timestamp_ms": SLOT_TS,
}


def _call(
    *,
    stock_rows: list[dict] | None = None,
    frames: list[dict] | None = None,
    source_health: list[dict] | None = None,
    dataset_id: str = "dragonboard_backend_shadow",
    allow_live_dataset: bool = False,
    snapshot_type: str = "half_hour",
    trading_date: str = "2026-06-11",
    slot_time: str = "15:00",
    slot_timestamp_ms: int | None = None,
    actual_timestamp_ms: int | None = None,
    grace_minutes: int = 5,
) -> QualityResult:
    """Convenience wrapper to reduce per-test boilerplate."""
    if stock_rows is None:
        stock_rows = [dict(r) for r in VALID_STOCK_ROWS]
    if frames is None:
        frames = [dict(f) for f in VALID_FRAMES]
    if source_health is None:
        source_health = [dict(s) for s in VALID_SOURCE_HEALTH]
    if slot_timestamp_ms is None:
        slot_timestamp_ms = SLOT_TS
    if actual_timestamp_ms is None:
        actual_timestamp_ms = SLOT_TS
    return evaluate_quality(
        stock_rows=stock_rows,
        frames=frames,
        source_health=source_health,
        dataset_id=dataset_id,
        allow_live_dataset=allow_live_dataset,
        snapshot_type=snapshot_type,
        trading_date=trading_date,
        slot_time=slot_time,
        slot_timestamp_ms=slot_timestamp_ms,
        actual_timestamp_ms=actual_timestamp_ms,
        grace_minutes=grace_minutes,
    )


# ── QualityResult dataclass ────────────────────────────────────────────────────


class TestQualityResult:
    """Verify the QualityResult frozen dataclass."""

    def test_construct_with_all_fields(self) -> None:
        result = QualityResult(
            ok=True,
            blocking_issues=[],
            warnings=["delayed_capture"],
            source_counts={"ok": 2, "failed": 0},
        )
        assert result.ok is True
        assert result.blocking_issues == []
        assert result.warnings == ["delayed_capture"]
        assert result.source_counts == {"ok": 2, "failed": 0}

    def test_frozen_prevents_mutation(self) -> None:
        result = QualityResult(
            ok=False,
            blocking_issues=["empty_stock_rows"],
            warnings=[],
            source_counts={"ok": 0, "failed": 0},
        )
        with pytest.raises(Exception):
            result.ok = True  # type: ignore[misc]

    def test_equality_by_value(self) -> None:
        a = QualityResult(
            ok=False,
            blocking_issues=["empty_stock_rows"],
            warnings=[],
            source_counts={"ok": 0, "failed": 0},
        )
        b = QualityResult(
            ok=False,
            blocking_issues=["empty_stock_rows"],
            warnings=[],
            source_counts={"ok": 0, "failed": 0},
        )
        assert a == b
        # QualityResult contains list/dict fields so it is not hashable —
        # this is correct: the mutable contents should not be used as dict keys.

    def test_different_values_not_equal(self) -> None:
        a = QualityResult(ok=True, blocking_issues=[], warnings=[], source_counts={})
        b = QualityResult(ok=False, blocking_issues=["x"], warnings=[], source_counts={})
        assert a != b


# ── HARD BLOCKERS ──────────────────────────────────────────────────────────────


class TestHardBlockerEmptyStockRows:
    """empty_stock_rows — zero stock rows → blocked."""

    def test_empty_list_blocks(self) -> None:
        result = _call(stock_rows=[])
        assert result.ok is False
        assert "empty_stock_rows" in result.blocking_issues

    def test_non_empty_stock_rows_passes(self) -> None:
        result = _call(stock_rows=VALID_STOCK_ROWS)
        assert "empty_stock_rows" not in result.blocking_issues


class TestHardBlockerMissingSnapshotIdentity:
    """missing_snapshot_identity — no snapshotId / type / tradingDate / slotTime → blocked."""

    def test_empty_snapshot_type_blocked(self) -> None:
        result = _call(snapshot_type="")
        assert result.ok is False
        assert "missing_snapshot_identity" in result.blocking_issues

    def test_empty_trading_date_blocked(self) -> None:
        result = _call(trading_date="")
        assert result.ok is False
        assert "missing_snapshot_identity" in result.blocking_issues

    def test_empty_slot_time_blocked(self) -> None:
        result = _call(slot_time="")
        assert result.ok is False
        assert "missing_snapshot_identity" in result.blocking_issues

    def test_zero_slot_timestamp_blocked(self) -> None:
        result = _call(slot_timestamp_ms=0)
        assert result.ok is False
        assert "missing_snapshot_identity" in result.blocking_issues

    def test_all_identity_present_passes(self) -> None:
        result = _call(
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="15:00",
            slot_timestamp_ms=SLOT_TS,
        )
        assert "missing_snapshot_identity" not in result.blocking_issues


class TestHardBlockerAllHotlistSourcesFailed:
    """all_hotlist_sources_failed — all hotlist providers returned error → blocked."""

    def test_all_failed_blocked(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", False, "timeout"),
                _make_source_health("xueqiu", False, "500"),
            ]
        )
        assert result.ok is False
        assert "all_hotlist_sources_failed" in result.blocking_issues

    def test_single_failed_source_blocked_when_only_one(self) -> None:
        """When there is only one source and it fails, all sources failed."""
        result = _call(
            source_health=[_make_source_health("eastmoney", False, "timeout")]
        )
        assert result.ok is False
        assert "all_hotlist_sources_failed" in result.blocking_issues

    def test_no_source_health_entries_blocked(self) -> None:
        """Zero source providers means no data could be collected."""
        result = _call(source_health=[])
        assert result.ok is False
        assert "all_hotlist_sources_failed" in result.blocking_issues

    def test_some_ok_passes(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", False, "timeout"),
                _make_source_health("xueqiu", True),
            ]
        )
        assert "all_hotlist_sources_failed" not in result.blocking_issues


class TestHardBlockerInvalidStockCode:
    """invalid_stock_code — stock codes that are empty or not A-share format → blocked."""

    def test_empty_code_blocked(self) -> None:
        result = _call(stock_rows=[_make_stock_row("")])
        assert result.ok is False
        assert "invalid_stock_code" in result.blocking_issues

    def test_too_short_code_blocked(self) -> None:
        result = _call(stock_rows=[_make_stock_row("60")])
        assert result.ok is False
        assert "invalid_stock_code" in result.blocking_issues

    def test_too_long_code_blocked(self) -> None:
        result = _call(stock_rows=[_make_stock_row("6000010")])
        assert result.ok is False
        assert "invalid_stock_code" in result.blocking_issues

    def test_non_digit_code_blocked(self) -> None:
        result = _call(stock_rows=[_make_stock_row("60abc1")])
        assert result.ok is False
        assert "invalid_stock_code" in result.blocking_issues

    def test_invalid_prefix_4_blocked(self) -> None:
        """Codes starting with 4 are not A-shares (likely indices or other)."""
        result = _call(stock_rows=[_make_stock_row("400001")])
        assert result.ok is False
        assert "invalid_stock_code" in result.blocking_issues

    def test_invalid_prefix_8_blocked(self) -> None:
        """Codes starting with 8 are not A-shares."""
        result = _call(stock_rows=[_make_stock_row("800001")])
        assert result.ok is False
        assert "invalid_stock_code" in result.blocking_issues

    def test_invalid_prefix_9_blocked(self) -> None:
        """Codes starting with 9 are B-shares."""
        result = _call(stock_rows=[_make_stock_row("900001")])
        assert result.ok is False
        assert "invalid_stock_code" in result.blocking_issues

    def test_shanghai_600_prefix_valid(self) -> None:
        result = _call(stock_rows=[_make_stock_row("600001")])
        assert "invalid_stock_code" not in result.blocking_issues

    def test_shenzhen_000_prefix_valid(self) -> None:
        result = _call(stock_rows=[_make_stock_row("000001")])
        assert "invalid_stock_code" not in result.blocking_issues

    def test_chinext_300_prefix_valid(self) -> None:
        result = _call(stock_rows=[_make_stock_row("300001")])
        assert "invalid_stock_code" not in result.blocking_issues

    def test_star_market_688_prefix_valid(self) -> None:
        """688xxx (STAR Market) starts with 6, should be valid A-share."""
        result = _call(stock_rows=[_make_stock_row("688001")])
        assert "invalid_stock_code" not in result.blocking_issues

    def test_missing_code_field_blocked(self) -> None:
        """A stock row without a 'code' field is treated as invalid."""
        result = _call(stock_rows=[{"name": "测试"}])
        assert result.ok is False
        assert "invalid_stock_code" in result.blocking_issues

    def test_none_code_blocked(self) -> None:
        result = _call(stock_rows=[{"code": None}])
        assert result.ok is False
        assert "invalid_stock_code" in result.blocking_issues

    def test_only_one_invalid_among_many_blocks(self) -> None:
        result = _call(
            stock_rows=[
                _make_stock_row("600001"),
                _make_stock_row("000001"),
                _make_stock_row("bad"),
            ]
        )
        assert result.ok is False
        assert "invalid_stock_code" in result.blocking_issues


class TestHardBlockerTimestampOutsideSlot:
    """timestamp_outside_slot — timestamp doesn't fall in target slot range → blocked."""

    def test_actual_before_slot_blocked(self) -> None:
        slot_ts = _make_ts("2026-06-11", "15:00")
        before_ts = slot_ts - 60_000  # 1 minute before
        result = _call(slot_timestamp_ms=slot_ts, actual_timestamp_ms=before_ts)
        assert result.ok is False
        assert "timestamp_outside_slot" in result.blocking_issues

    def test_actual_equals_slot_passes(self) -> None:
        slot_ts = _make_ts("2026-06-11", "15:00")
        result = _call(slot_timestamp_ms=slot_ts, actual_timestamp_ms=slot_ts)
        assert "timestamp_outside_slot" not in result.blocking_issues

    def test_actual_within_grace_window_passes(self) -> None:
        slot_ts = _make_ts("2026-06-11", "15:00")
        after_ts = slot_ts + 4 * 60_000  # 4 minutes after
        result = _call(
            slot_timestamp_ms=slot_ts,
            actual_timestamp_ms=after_ts,
            grace_minutes=5,
        )
        assert "timestamp_outside_slot" not in result.blocking_issues


class TestHardBlockerInvalidLiveDatasetInShadowMode:
    """invalid_live_dataset_in_shadow_mode — datasetId is dragonboard_live but ALLOW_LIVE_DATASET=0 → blocked."""

    def test_live_dataset_blocked_when_not_allowed(self) -> None:
        result = _call(dataset_id="dragonboard_live", allow_live_dataset=False)
        assert result.ok is False
        assert "invalid_live_dataset_in_shadow_mode" in result.blocking_issues

    def test_live_dataset_allowed_when_flag_set(self) -> None:
        result = _call(dataset_id="dragonboard_live", allow_live_dataset=True)
        assert "invalid_live_dataset_in_shadow_mode" not in result.blocking_issues

    def test_non_live_dataset_not_blocked_even_without_flag(self) -> None:
        result = _call(dataset_id="dragonboard_backend_shadow", allow_live_dataset=False)
        assert "invalid_live_dataset_in_shadow_mode" not in result.blocking_issues

    def test_non_live_dataset_with_flag_also_passes(self) -> None:
        result = _call(dataset_id="my_dataset", allow_live_dataset=True)
        assert "invalid_live_dataset_in_shadow_mode" not in result.blocking_issues


# ── SOFT WARNINGS (do NOT block) ───────────────────────────────────────────────


class TestWarningQuoteProviderPartial:
    """quote_provider_partial — some quotes missing → warning, not blocked."""

    def test_partial_source_failure_warns(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", False, "timeout"),
                _make_source_health("xueqiu", True),
            ]
        )
        assert "quote_provider_partial" in result.warnings
        assert result.ok is True  # partial failure does not block

    def test_all_sources_ok_no_warning(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
                _make_source_health("xueqiu", True),
            ]
        )
        assert "quote_provider_partial" not in result.warnings

    def test_partial_warning_coexists_with_other_warnings(self) -> None:
        """Partial quote failure warning can coexist with other warnings."""
        result = _call(
            source_health=[
                _make_source_health("eastmoney", False, "timeout"),
                _make_source_health("xueqiu", True),
            ],
            actual_timestamp_ms=_make_ts("2026-06-11", "15:00") + 10 * 60_000,
            grace_minutes=5,
        )
        assert "quote_provider_partial" in result.warnings
        assert "delayed_capture" in result.warnings


class TestWarningDepthProviderMissing:
    """depth_provider_missing — depth data absent → warning."""

    def test_depth_source_failed_warns(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
                _make_source_health("depth_provider", False, "not available"),
            ]
        )
        assert "depth_provider_missing" in result.warnings
        assert result.ok is True

    def test_depth_source_present_no_warning(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
                _make_source_health("depth_provider", True),
            ]
        )
        assert "depth_provider_missing" not in result.warnings

    def test_no_depth_source_at_all_no_warning(self) -> None:
        """If no depth provider was attempted, don't warn."""
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
            ]
        )
        assert "depth_provider_missing" not in result.warnings


class TestWarningMoneyFlowEstimatedL1:
    """money_flow_estimated_l1 — money flow source is estimated L1 → warning."""

    def test_money_flow_l1_source_warns(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
                _make_source_health("money_flow", False, "L1 estimate only"),
            ]
        )
        assert "money_flow_estimated_l1" in result.warnings
        assert result.ok is True

    def test_money_flow_source_l1_indicated_in_error_warns(self) -> None:
        """Warn when money_flow source error message mentions L1."""
        result = _call(
            source_health=[
                _make_source_health("money_flow_l2", False, "fallback to L1 estimation"),
            ]
        )
        assert "money_flow_estimated_l1" in result.warnings

    def test_money_flow_l1_in_source_name_warns(self) -> None:
        """Warn when source name itself indicates L1 estimation."""
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
                _make_source_health("money_flow_estimated_l1", True),
            ]
        )
        assert "money_flow_estimated_l1" in result.warnings

    def test_no_money_flow_source_no_warning(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
            ]
        )
        assert "money_flow_estimated_l1" not in result.warnings


class TestWarningThemeMappingPartial:
    """theme_mapping_partial — some themes missing → warning."""

    def test_theme_source_failed_warns(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
                _make_source_health("theme_mapping", False, "partial failure"),
            ]
        )
        assert "theme_mapping_partial" in result.warnings
        assert result.ok is True

    def test_theme_source_ok_no_warning(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
                _make_source_health("theme_mapping", True),
            ]
        )
        assert "theme_mapping_partial" not in result.warnings

    def test_no_theme_source_no_warning(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
            ]
        )
        assert "theme_mapping_partial" not in result.warnings


class TestWarningDelayedCapture:
    """delayed_capture — capture happened after slot grace window → warning."""

    def test_delayed_beyond_grace_warns(self) -> None:
        slot_ts = _make_ts("2026-06-11", "15:00")
        late_ts = slot_ts + 10 * 60_000  # 10 minutes after
        result = _call(
            slot_timestamp_ms=slot_ts,
            actual_timestamp_ms=late_ts,
            grace_minutes=5,
        )
        assert "delayed_capture" in result.warnings
        assert result.ok is True  # delayed capture is a warning, not a blocker

    def test_within_grace_no_warning(self) -> None:
        slot_ts = _make_ts("2026-06-11", "15:00")
        on_time_ts = slot_ts + 3 * 60_000  # 3 minutes after
        result = _call(
            slot_timestamp_ms=slot_ts,
            actual_timestamp_ms=on_time_ts,
            grace_minutes=5,
        )
        assert "delayed_capture" not in result.warnings

    def test_exact_grace_boundary_no_warning(self) -> None:
        slot_ts = _make_ts("2026-06-11", "15:00")
        boundary_ts = slot_ts + 5 * 60_000  # exactly at grace boundary
        result = _call(
            slot_timestamp_ms=slot_ts,
            actual_timestamp_ms=boundary_ts,
            grace_minutes=5,
        )
        assert "delayed_capture" not in result.warnings


# ── source_counts ──────────────────────────────────────────────────────────────


class TestSourceCounts:
    """source_counts reflects ok vs failed tally from source_health."""

    def test_all_ok_counts(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
                _make_source_health("xueqiu", True),
            ]
        )
        assert result.source_counts == {"ok": 2, "failed": 0}

    def test_mixed_counts(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", True),
                _make_source_health("xueqiu", False, "timeout"),
                _make_source_health("depth_provider", False, "not available"),
            ]
        )
        assert result.source_counts == {"ok": 1, "failed": 2}

    def test_all_failed_counts(self) -> None:
        result = _call(
            source_health=[
                _make_source_health("eastmoney", False, "timeout"),
                _make_source_health("xueqiu", False, "500"),
            ]
        )
        assert result.source_counts == {"ok": 0, "failed": 2}

    def test_empty_source_health_counts(self) -> None:
        result = _call(source_health=[])
        assert result.source_counts == {"ok": 0, "failed": 0}


# ── happy path ─────────────────────────────────────────────────────────────────


class TestHappyPath:
    """Full valid inputs pass quality gate with ok=True."""

    def test_all_valid_inputs_passes(self) -> None:
        result = _call(
            stock_rows=VALID_STOCK_ROWS,
            source_health=VALID_SOURCE_HEALTH,
            frames=VALID_FRAMES,
            dataset_id="dragonboard_backend_shadow",
            allow_live_dataset=False,
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="15:00",
            slot_timestamp_ms=SLOT_TS,
            actual_timestamp_ms=SLOT_TS,
            grace_minutes=5,
        )
        assert result.ok is True
        assert result.blocking_issues == []
        # No warnings expected for perfect inputs
        assert result.warnings == []

    def test_snapshot_id_built_from_inputs(self) -> None:
        """Verify snapshot_id derived form matches SnapshotSlot convention."""
        result = _call(
            snapshot_type="quarter_hour",
            trading_date="2026-06-12",
            slot_time="09:45",
            slot_timestamp_ms=_make_ts("2026-06-12", "09:45"),
            actual_timestamp_ms=_make_ts("2026-06-12", "09:45"),
        )
        assert result.ok is True


# ── multiple issues ────────────────────────────────────────────────────────────


class TestMultipleBlockers:
    """When multiple hard blockers exist, all are reported."""

    def test_multiple_blockers_reported(self) -> None:
        """empty stock rows + missing identity + live dataset → all listed."""
        result = _call(
            stock_rows=[],
            source_health=[],
            snapshot_type="",
            trading_date="",
            slot_time="",
            slot_timestamp_ms=0,
            dataset_id="dragonboard_live",
            allow_live_dataset=False,
            actual_timestamp_ms=SLOT_TS - 60_000,
        )
        assert result.ok is False
        assert "empty_stock_rows" in result.blocking_issues
        assert "missing_snapshot_identity" in result.blocking_issues
        assert "all_hotlist_sources_failed" in result.blocking_issues
        assert "invalid_live_dataset_in_shadow_mode" in result.blocking_issues

    def test_warnings_still_reported_when_blocked(self) -> None:
        """Even when ok=False due to blockers, warnings should still be reported."""
        slot_ts = _make_ts("2026-06-11", "15:00")
        result = _call(
            stock_rows=[],
            source_health=[
                _make_source_health("eastmoney", False, "timeout"),
                _make_source_health("xueqiu", False, "500"),
            ],
            actual_timestamp_ms=slot_ts + 10 * 60_000,
            grace_minutes=5,
        )
        assert result.ok is False
        assert "empty_stock_rows" in result.blocking_issues
        assert "all_hotlist_sources_failed" in result.blocking_issues
        # Warnings should still be populated
        assert "delayed_capture" in result.warnings
