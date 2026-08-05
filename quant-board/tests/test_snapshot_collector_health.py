"""Health endpoint regression tests for the standalone collector (8001).

Guards the launcher probe contract: after a process restart the collector
health endpoint must only backfill ``last_run_at`` from a completed run that
belongs to *today*.  A stale run from a previous trading day must not be
presented as today's activity, otherwise the launcher probe reports
"超过2小时未执行" at the first slot of a new trading day and kill/restarts
the collector right before the first capture.
"""

from datetime import datetime
from unittest.mock import patch

from backend.collector_main import health
from backend.snapshot_collector.scheduler import snapshot_collector_scheduler


def _status(**overrides):
    base = {
        "enabled": True,
        "running": True,
        "dataset_id": "dragonboard_live",
        "snapshot_types": ["half_hour", "daily"],
        "grace_minutes": 5,
        "is_trading_day": True,
        "trading_date": "2026-08-05",
        "in_session": True,
        "upcoming_slot": "half_hour:2026-08-05:10:00",
        "last_run_at": None,
        "last_slot_collected": None,
        "last_error": None,
        "last_error_at": None,
        "last_error_slot": None,
        "collection_count": 0,
        "error_count": 0,
        "in_flight_slots": [],
    }
    base.update(overrides)
    return base


class _FakeRepo:
    def __init__(self, items):
        self._items = items

    def list_runs(self, filters):
        return {"items": self._items, "total": len(self._items)}


def _call_health(repo_items, status=None):
    fake_repo = _FakeRepo(repo_items)
    with patch(
        "backend.snapshot_collector.service_factory.create_snapshot_collector_repository",
        return_value=fake_repo,
    ):
        with patch("backend.collector_main._background_task_status", return_value={}):
            with patch.object(
                snapshot_collector_scheduler,
                "status",
                return_value=status if status is not None else _status(),
            ):
                return health()


def test_health_does_not_backfill_previous_trading_day_run():
    repo_items = [
        {
            "runId": "sc-yesterday",
            "snapshotId": "half_hour:2026-08-04:15:30",
            "tradingDate": "2026-08-04",
            "status": "completed",
            "createdAt": datetime(2026, 8, 4, 3, 11, 0),
        }
    ]

    collector = _call_health(repo_items)["snapshotCollector"]

    assert collector.get("last_run_at") is None
    assert collector.get("last_slot_collected") is None


def test_health_backfills_today_completed_run():
    repo_items = [
        {
            "runId": "sc-today",
            "snapshotId": "half_hour:2026-08-05:09:30",
            "tradingDate": "2026-08-05",
            "status": "completed",
            "createdAt": datetime(2026, 8, 5, 1, 57, 0),
        }
    ]

    collector = _call_health(repo_items)["snapshotCollector"]

    assert collector["last_run_at"] == "2026-08-05T01:57:00Z"
    assert collector["last_slot_collected"] == "half_hour:2026-08-05:09:30"


# --- launcher 健康契约字段（P0.1：status/restartable/recommendedAction/reason） ---


def test_health_ok_contract():
    payload = _call_health([])
    assert payload["status"] == "ok"
    assert payload["restartable"] is True
    assert payload["recommendedAction"] == "none"
    assert payload["reason"]


def test_health_scheduler_stopped_contract():
    payload = _call_health([], status=_status(running=False))
    assert payload["status"] == "error"
    assert payload["restartable"] is True
    assert payload["recommendedAction"] == "restart"


def test_health_last_error_contract():
    payload = _call_health([], status=_status(last_error="quote fetch failed"))
    assert payload["status"] == "degraded"
    assert payload["restartable"] is False
    assert payload["recommendedAction"] == "alert"
    assert "quote fetch failed" in payload["reason"]


def test_health_contract_preserves_snapshot_collector_block():
    payload = _call_health([])
    assert "snapshotCollector" in payload
    assert payload["snapshotCollector"]["enabled"] is True
