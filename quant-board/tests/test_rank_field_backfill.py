from __future__ import annotations

from backend.operations.rank_field_backfill import build_comp_rank_backfill_plan


def test_build_plan_accepts_unique_contiguous_collector_ranks() -> None:
    plan = build_comp_rank_backfill_plan([
        {"snapshotId": "half_hour:2026-07-06:10:00", "code": "000001", "rank": 1},
        {"snapshotId": "half_hour:2026-07-06:10:00", "code": "000002", "rank": 2},
    ])

    assert plan == {
        "snapshotId": "half_hour:2026-07-06:10:00",
        "eligible": True,
        "rowCount": 2,
        "reason": None,
    }


def test_build_plan_rejects_rank_gaps() -> None:
    plan = build_comp_rank_backfill_plan([
        {"snapshotId": "half_hour:2026-07-06:10:00", "code": "000001", "rank": 1},
        {"snapshotId": "half_hour:2026-07-06:10:00", "code": "000003", "rank": 3},
    ])

    assert plan["eligible"] is False
    assert plan["reason"] == "rank_not_contiguous_1_to_n"


def test_build_plan_rejects_duplicate_codes() -> None:
    plan = build_comp_rank_backfill_plan([
        {"snapshotId": "half_hour:2026-07-06:10:00", "code": "000001", "rank": 1},
        {"snapshotId": "half_hour:2026-07-06:10:00", "code": "000001", "rank": 2},
    ])

    assert plan["eligible"] is False
    assert plan["reason"] == "duplicate_stock_code"
