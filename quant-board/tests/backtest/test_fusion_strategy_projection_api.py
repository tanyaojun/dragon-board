from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.main import app


def _signal(
    snapshot_id: str,
    timestamp: int,
    trading_date: str,
    slot_time: str,
    code: str,
    name: str,
    candidate_tier: str,
    lifecycle_action: str,
    *,
    final_signal: str = "hold",
    rank: int = 1,
    confidence: float = 80,
) -> dict[str, object]:
    return {
        "snapshotId": snapshot_id,
        "timestamp": timestamp,
        "tradingDate": trading_date,
        "slotTime": slot_time,
        "code": code,
        "name": name,
        "candidateTier": candidate_tier,
        "rank": rank,
        "confidence": confidence,
        "action": "exit_watch" if lifecycle_action == "exit_watch" else "focus",
        "rankTrend": {
            "cycle": {
                "decision": {
                    "action": lifecycle_action,
                }
            },
            "decision": {
                "final": {
                    "signal": final_signal,
                }
            },
        },
    }


def _run(
    *,
    run_id: str = "bt_fusion_projection",
    snapshot_type: str | None = "half_hour",
    strategy_name: str = "ranktrend_early_big_move_v3_lifecycle_fusion",
    signals: list[dict[str, object]] | None = None,
    trade_simulation: dict[str, object] | None = None,
) -> SimpleNamespace:
    request_payload = {
        "datasetId": "ds_fusion_projection",
        "snapshotType": snapshot_type,
        "tradeConfig": {"maxPositions": 3},
    }
    result_payload = {
        "signals": signals or [],
        "tradeSimulation": trade_simulation or {},
    }
    return SimpleNamespace(
        id=run_id,
        dataset_id="ds_fusion_projection",
        snapshot_type=snapshot_type,
        strategy_name=strategy_name,
        strategy_version="0.1.0",
        config_hash="cfg_fusion_projection",
        random_seed=20260608,
        request_json=json.dumps(request_payload),
        result_json=json.dumps(result_payload),
    )


class FakeRepo:
    def __init__(
        self,
        run: SimpleNamespace | None,
        *,
        fallback_signals: list[dict[str, object]] | None = None,
        fallback_trades: list[dict[str, object]] | None = None,
    ):
        self.run = run
        self.fallback_signals = fallback_signals
        self.fallback_trades = fallback_trades

    def get_backtest_run(self, run_id: str) -> SimpleNamespace | None:
        if self.run and self.run.id == run_id:
            return self.run
        return None

    def get_backtest_signals(self, run_id: str, limit: int | None = None, offset: int = 0) -> list[dict[str, object]]:
        if self.fallback_signals is None:
            raise AssertionError("fusion projection API should read raw backtest signals from run.result_json in this contract test")
        return self.fallback_signals

    def get_backtest_trades(self, run_id: str, limit: int | None = None, offset: int = 0) -> list[dict[str, object]]:
        if self.fallback_trades is None:
            raise AssertionError("fusion projection API should read lifecycle trade facts from run.result_json in this contract test")
        return self.fallback_trades


def test_fusion_projection_api_keeps_separate_lifecycle_segments_per_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.api.fusion_strategy_projection_routes as route_module

    signals = [
        _signal("snap-001", 1_780_452_000_000, "2026-06-03", "10:00", "600001", "Alpha", "A_MAIN", "allow", final_signal="buy"),
        _signal("snap-002", 1_780_453_800_000, "2026-06-03", "10:30", "600001", "Alpha", "D_EXIT_RISK", "exit_watch", final_signal="sell"),
        _signal("snap-003", 1_780_462_800_000, "2026-06-03", "13:00", "600001", "Alpha", "A_MAIN", "allow", final_signal="buy"),
        _signal("snap-004", 1_780_464_600_000, "2026-06-03", "13:30", "600001", "Alpha", "D_EXIT_RISK", "exit_watch", final_signal="sell"),
        _signal("snap-005", 1_780_466_400_000, "2026-06-03", "14:00", "600002", "Beta", "B_IGNITION", "caution", final_signal="hold"),
    ]
    trade_simulation = {
        "roundTripTrades": [
            {
                "code": "600001",
                "name": "Alpha",
                "entrySignalSnapshotId": "snap-001",
                "entrySnapshotId": "snap-001",
                "entryTime": 1_780_452_000_000,
                "entryTradingDate": "2026-06-03",
                "entryPrice": 10.0,
                "exitSignalSnapshotId": "snap-002",
                "exitSnapshotId": "snap-002",
                "exitTime": 1_780_453_800_000,
                "exitTradingDate": "2026-06-03",
                "exitPrice": 10.6,
                "holdingBars": 1,
                "netReturn": 0.06,
                "profit": 600.0,
                "reason": "D_EXIT_RISK",
                "candidateTier": "D_EXIT_RISK",
                "stage": "cooling",
                "regime": "strong",
            },
            {
                "code": "600001",
                "name": "Alpha",
                "entrySignalSnapshotId": "snap-003",
                "entrySnapshotId": "snap-003",
                "entryTime": 1_780_462_800_000,
                "entryTradingDate": "2026-06-03",
                "entryPrice": 11.0,
                "exitSignalSnapshotId": "snap-004",
                "exitSnapshotId": "snap-004",
                "exitTime": 1_780_464_600_000,
                "exitTradingDate": "2026-06-03",
                "exitPrice": 11.4,
                "holdingBars": 1,
                "netReturn": 0.0364,
                "profit": 400.0,
                "reason": "D_EXIT_RISK",
                "candidateTier": "D_EXIT_RISK",
                "stage": "cooling",
                "regime": "strong",
            },
        ],
        "tradeEvents": [
            {"snapshotId": "snap-001", "signalSnapshotId": "snap-001", "timestamp": 1_780_452_000_000, "tradingDate": "2026-06-03", "code": "600001", "action": "buy", "reason": "A_MAIN 入场"},
            {"snapshotId": "snap-002", "signalSnapshotId": "snap-002", "timestamp": 1_780_453_800_000, "tradingDate": "2026-06-03", "code": "600001", "action": "sell", "reason": "D_EXIT_RISK"},
            {"snapshotId": "snap-003", "signalSnapshotId": "snap-003", "timestamp": 1_780_462_800_000, "tradingDate": "2026-06-03", "code": "600001", "action": "buy", "reason": "A_MAIN 二次入场"},
            {"snapshotId": "snap-004", "signalSnapshotId": "snap-004", "timestamp": 1_780_464_600_000, "tradingDate": "2026-06-03", "code": "600001", "action": "sell", "reason": "D_EXIT_RISK"},
        ],
        "openPositions": [],
    }
    fake_repo = FakeRepo(_run(signals=signals, trade_simulation=trade_simulation))
    monkeypatch.setattr(route_module, "create_repository", lambda *_args, **_kwargs: fake_repo)

    client = TestClient(app)
    response = client.get("/api/backtests/bt_fusion_projection/fusion-projections")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["runId"] == "bt_fusion_projection"
    assert body["snapshotType"] == "half_hour"

    rows = body["rows"]
    assert [row["snapshotId"] for row in rows] == ["snap-001", "snap-002", "snap-003", "snap-004", "snap-005"]

    alpha_rows = [row for row in rows if row["stockCode"] == "600001"]
    assert [row["strategyState"] for row in alpha_rows] == [
        "active_holding",
        "closed",
        "active_holding",
        "closed",
    ]
    assert alpha_rows[0]["strategyExitAt"] is None
    assert alpha_rows[0]["strategyExitPrice"] is None
    assert alpha_rows[0]["strategyReturnPct"] is None
    assert alpha_rows[0]["exitReason"] is None
    assert [row["triggerAt"] for row in alpha_rows if row["strategyState"] == "closed"] == [
        "2026-06-03T10:00:00+08:00",
        "2026-06-03T13:00:00+08:00",
    ]
    assert [row["strategyEntryAt"] for row in alpha_rows if row["strategyState"] == "closed"] == [
        "2026-06-03T10:00:00+08:00",
        "2026-06-03T13:00:00+08:00",
    ]

    beta_row = next(row for row in rows if row["stockCode"] == "600002")
    assert beta_row["strategyState"] == "triggered_wait_entry"
    assert beta_row["strategyEntryAt"] is None
    assert beta_row["strategyExitAt"] is None


def test_fusion_projection_api_preserves_quarter_hour_snapshot_type(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.api.fusion_strategy_projection_routes as route_module

    fake_repo = FakeRepo(
        _run(
            run_id="bt_quarter_hour_projection",
            snapshot_type="quarter_hour",
            signals=[
                _signal(
                    "q-snap-001",
                    1_780_452_000_000,
                    "2026-06-03",
                    "10:00",
                    "300001",
                    "Gamma",
                    "A_MAIN",
                    "allow",
                    final_signal="buy",
                )
            ],
        )
    )
    monkeypatch.setattr(route_module, "create_repository", lambda *_args, **_kwargs: fake_repo)

    client = TestClient(app)
    response = client.get("/api/backtests/bt_quarter_hour_projection/fusion-projections")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshotType"] == "quarter_hour"
    assert body["rows"][0]["snapshotType"] == "quarter_hour"


def test_fusion_projection_api_defaults_snapshot_type_to_half_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.api.fusion_strategy_projection_routes as route_module

    fake_repo = FakeRepo(
        _run(
            run_id="bt_default_snapshot_type_projection",
            snapshot_type=None,
            signals=[
                _signal(
                    "h-snap-001",
                    1_780_452_000_000,
                    "2026-06-03",
                    "10:00",
                    "300002",
                    "Delta",
                    "B_IGNITION",
                    "caution",
                )
            ],
        )
    )
    monkeypatch.setattr(route_module, "create_repository", lambda *_args, **_kwargs: fake_repo)

    client = TestClient(app)
    response = client.get("/api/backtests/bt_default_snapshot_type_projection/fusion-projections")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshotType"] == "half_hour"
    assert body["rows"][0]["snapshotType"] == "half_hour"


def test_fusion_projection_api_prefers_open_position_over_closed_segment_for_same_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.api.fusion_strategy_projection_routes as route_module

    signals = [
        _signal("snap-open-001", 1_780_452_000_000, "2026-06-03", "10:00", "600003", "OpenAlpha", "A_MAIN", "allow", final_signal="buy"),
        _signal("snap-open-002", 1_780_453_800_000, "2026-06-03", "10:30", "600003", "OpenAlpha", "D_EXIT_RISK", "exit_watch", final_signal="sell"),
        _signal("snap-open-003", 1_780_455_600_000, "2026-06-03", "11:00", "600003", "OpenAlpha", "A_MAIN", "allow", final_signal="hold"),
    ]
    trade_simulation = {
        "roundTripTrades": [
            {
                "code": "600003",
                "name": "OpenAlpha",
                "entrySignalSnapshotId": "snap-open-001",
                "entrySnapshotId": "snap-open-001",
                "entryTime": 1_780_452_000_000,
                "entryTradingDate": "2026-06-03",
                "entryPrice": 10.0,
                "exitSignalSnapshotId": "snap-open-002",
                "exitSnapshotId": "snap-open-002",
                "exitTime": 1_780_453_800_000,
                "exitTradingDate": "2026-06-03",
                "exitPrice": 10.6,
                "holdingBars": 1,
                "netReturn": 0.06,
            }
        ],
        "tradeEvents": [],
        "openPositions": [
            {
                "code": "600003",
                "name": "OpenAlpha",
                "entrySnapshotId": "snap-open-001",
                "entryTime": 1_780_452_000_000,
                "entryTradingDate": "2026-06-03",
                "entryPrice": 10.0,
                "holdingBars": 2,
            }
        ],
    }
    fake_repo = FakeRepo(_run(run_id="bt_open_position_projection", signals=signals, trade_simulation=trade_simulation))
    monkeypatch.setattr(route_module, "create_repository", lambda *_args, **_kwargs: fake_repo)

    client = TestClient(app)
    response = client.get("/api/backtests/bt_open_position_projection/fusion-projections")

    assert response.status_code == 200, response.text
    rows = response.json()["rows"]
    latest_row = next(row for row in rows if row["snapshotId"] == "snap-open-003")
    assert latest_row["strategyState"] == "active_holding"
    assert latest_row["strategyEntryAt"] == "2026-06-03T10:00:00+08:00"
    assert latest_row["strategyExitAt"] is None


def test_fusion_projection_api_falls_back_to_repo_rows_when_result_json_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.api.fusion_strategy_projection_routes as route_module

    fallback_signals = [
        _signal("snap-fallback-001", 1_780_452_000_000, "2026-06-03", "10:00", "600004", "Fallback", "A_MAIN", "allow", final_signal="buy")
    ]
    fallback_trades = [
        {
            "code": "600004",
            "name": "Fallback",
            "entrySignalSnapshotId": "snap-fallback-001",
            "entrySnapshotId": "snap-fallback-001",
            "entryTime": 1_780_452_000_000,
            "entryTradingDate": "2026-06-03",
            "entryPrice": 10.0,
        }
    ]
    fake_repo = FakeRepo(
        _run(run_id="bt_fallback_projection", signals=[], trade_simulation={}),
        fallback_signals=fallback_signals,
        fallback_trades=fallback_trades,
    )
    monkeypatch.setattr(route_module, "create_repository", lambda *_args, **_kwargs: fake_repo)

    client = TestClient(app)
    response = client.get("/api/backtests/bt_fallback_projection/fusion-projections")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 1
    assert body["rows"][0]["snapshotId"] == "snap-fallback-001"
    assert body["rows"][0]["strategyState"] == "active_holding"


def test_fusion_projection_api_rejects_non_fusion_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.api.fusion_strategy_projection_routes as route_module

    fake_repo = FakeRepo(
        _run(
            run_id="bt_other_strategy_projection",
            strategy_name="ranktrend_intraday_other_strategy",
            signals=[
                _signal("snap-other-001", 1_780_452_000_000, "2026-06-03", "10:00", "600005", "Other", "A_MAIN", "allow")
            ],
        )
    )
    monkeypatch.setattr(route_module, "create_repository", lambda *_args, **_kwargs: fake_repo)

    client = TestClient(app)
    response = client.get("/api/backtests/bt_other_strategy_projection/fusion-projections")

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "unsupported_strategy"
