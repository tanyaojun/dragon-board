"""Layer1/3 meltdown, alignment, and checkpoints API tests.

Extracted from tests/test_quant_board.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.core.settings import get_settings
from backend.main import app


def test_longtest_baseline_summary_includes_layer1_layer2() -> None:
    from backend.cli import summarize_longtest_baseline

    spec = {
        "label": "H1_half_hour_current_bar",
        "purpose": "page-compatible optimistic baseline",
        "payload": {"maxHoldingBars": 40, "tradeConfig": {"executionMode": "current_bar"}},
    }
    run = {
        "runId": "bt_test_layer",
        "totalReturn": 0.05,
        "maxDrawdown": -0.03,
        "sharpe": 0.5,
        "winRate": 0.4,
        "tradeCount": 40,
        "dataQuality": {
            "severity": "warn",
            "researchGrade": "degraded",
            "layer1SignalEfficacy": {
                "tierRatio": 0.04,
                "directionAccuracy": 0.6,
                "tierDiscrimination": 0.08,
                "layer1Status": "green",
            },
            "layer2ExecutionQuality": {
                "bias": 0.03,
                "layer2Status": "green",
            },
            "qualityGate": {"stats": {}},
            "reportOnlyDiagnostics": {},
        },
    }

    summary = summarize_longtest_baseline(spec, run)

    layer1 = summary.get("layer1SignalEfficacy")
    assert layer1 is not None, "Layer 1 missing from summary"
    assert layer1["layer1Status"] == "green"

    layer2 = summary.get("layer2ExecutionQuality")
    assert layer2 is not None, "Layer 2 missing from summary"
    assert layer2["layer2Status"] == "green"


def test_layer1_meltdown_detects_consecutive_red() -> None:
    from backend.services import check_layer1_meltdown

    history = [
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "red"}}]},
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "red"}}]},
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "red"}}]},
    ]
    result = check_layer1_meltdown(history)
    assert result["meltdown"] is True
    assert result["consecutiveRedPeriods"] == 3
    assert result["recommendation"] is not None


def test_layer1_meltdown_resets_on_green() -> None:
    from backend.services import check_layer1_meltdown

    history = [
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "red"}}]},
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "green"}}]},
        {"baselines": [{"label": "H1_half_hour_current_bar", "layer1SignalEfficacy": {"layer1Status": "red"}}]},
    ]
    result = check_layer1_meltdown(history)
    assert result["meltdown"] is False
    assert result["consecutiveRedPeriods"] == 1


def test_layer1_meltdown_reports_selected_v5_slot() -> None:
    from backend.services import check_layer1_meltdown

    history = [
        {
            "baselines": [
                {
                    "label": "V5_E1_half_hour_fusion_signal_forward30",
                    "layer1SignalEfficacy": {"layer1Status": "red"},
                },
                {
                    "label": "V5_E2_half_hour_fusion_current_bar",
                    "executionLayer1Efficacy": {"layer1Status": "green"},
                },
            ]
        },
        {
            "baselines": [
                {
                    "label": "V5_E1_half_hour_fusion_signal_forward30",
                    "layer1SignalEfficacy": {"layer1Status": "red"},
                },
                {
                    "label": "V5_E2_half_hour_fusion_current_bar",
                    "executionLayer1Efficacy": {"layer1Status": "green"},
                },
            ]
        },
        {
            "baselines": [
                {
                    "label": "V5_E1_half_hour_fusion_signal_forward30",
                    "layer1SignalEfficacy": {"layer1Status": "red"},
                },
                {
                    "label": "V5_E2_half_hour_fusion_current_bar",
                    "executionLayer1Efficacy": {"layer1Status": "green"},
                },
            ]
        },
    ]

    signal_pool = check_layer1_meltdown(history, metric_key="layer1SignalEfficacy")
    execution_entry = check_layer1_meltdown(
        history,
        label_filter="V5_E2_half_hour_fusion_current_bar",
        metric_key="executionLayer1Efficacy",
    )

    assert signal_pool["meltdown"] is True
    assert signal_pool["selectedLabel"] == "V5_E1_half_hour_fusion_signal_forward30"
    assert signal_pool["selectedSlot"] == "l1"
    assert signal_pool["metricKey"] == "layer1SignalEfficacy"

    assert execution_entry["meltdown"] is False
    assert execution_entry["consecutiveRedPeriods"] == 0
    assert execution_entry["selectedLabel"] == "V5_E2_half_hour_fusion_current_bar"
    assert execution_entry["metricKey"] == "executionLayer1Efficacy"


def test_compute_execution_entry_layer1_efficacy_uses_actual_buy_events() -> None:
    from backend.services import compute_execution_entry_layer1_efficacy

    trade_events = [
        {
            "action": "buy",
            "signalSnapshotId": "s1",
            "code": "000001",
            "price": 10,
            "candidateTier": "A_MAIN",
        },
        {
            "action": "buy",
            "signalSnapshotId": "s1",
            "code": "000002",
            "price": 20,
            "candidateTier": "B_IGNITION",
        },
        {
            "action": "sell",
            "signalSnapshotId": "s1",
            "code": "000003",
            "price": 30,
            "candidateTier": "A_MAIN",
        },
    ]
    frames = [
        {
            "snapshotId": "s1",
            "stocks": [
                {"code": "000001", "price": 10},
                {"code": "000002", "price": 20},
            ],
        },
        {
            "snapshotId": "s2",
            "stocks": [
                {"code": "000001", "price": 11},
                {"code": "000002", "price": 19},
            ],
        },
    ]

    result = compute_execution_entry_layer1_efficacy(trade_events=trade_events, frames=frames)

    assert result["sampleScope"] == "execution_entry"
    assert result["totalSignals"] == 2
    assert result["aPlusBTierCount"] == 2
    assert result["directionAccuracy"] == pytest.approx(1.0)
    assert result["aMainSamples"] == 1
    assert result["tierCounts"] == {"A_MAIN": 1, "B_IGNITION": 1}


def test_layer3_trend_detects_consecutive_sufficient() -> None:
    from backend.services import check_layer3_trend

    history = [
        {"layer3Alignment": {"alignmentStatus": "sufficient"}},
        {"layer3Alignment": {"alignmentStatus": "sufficient"}},
    ]
    result = check_layer3_trend(history)
    assert result["greenLight"] is True
    assert result["recommendation"] is not None


def test_layer3_trend_insufficient_history() -> None:
    from backend.services import check_layer3_trend

    result = check_layer3_trend([])
    assert result["greenLight"] is False
    assert result["diagnostics"] == "insufficient_history"


def test_compute_alignment_skips_backtest_signal_scan_when_no_executed_journal() -> None:
    from backend.services import compute_alignment

    class Repo:
        def list_journal_entries(self, **_: object) -> list[dict]:
            return []

        def get_backtest_run(self, run_id: str) -> object:
            raise AssertionError(f"should not load backtest signals when journal is empty: {run_id}")

    result = compute_alignment(Repo(), ["bt_large_result"])

    assert result["alignmentStatus"] == "insufficient_data"
    assert result["journalExecutedCount"] == 0
    assert result["signalCodeCount"] == 0


def test_get_checkpoints_returns_list() -> None:
    client = TestClient(app)
    response = client.get("/api/backtests/checkpoints?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if data:
        item = data[0]
        assert "checkpointId" in item
        assert "h1TotalReturn" in item


def test_get_checkpoints_respects_limit() -> None:
    client = TestClient(app)
    response = client.get("/api/backtests/checkpoints?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data) <= 2


def test_get_checkpoints_maps_early_big_move_baselines(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(get_settings(), "reports_dir", reports_dir)

    record = {
        "checkpointId": "checkpoint_2026-06-07_early_big_move_v3",
        "createdAt": "2026-06-07T05:19:35.613557+00:00",
        "baselines": [
            {
                "label": "V3_E1_half_hour_signal_forward50",
                "layer1SignalEfficacy": {
                    "tierRatio": 0.0843,
                    "aPlusBTierCount": 6008,
                    "totalSignals": 71266,
                    "layer1Status": "red",
                    "directionAccuracy": 0.3756,
                },
            },
            {
                "label": "V3_E2_half_hour_ranked_current_bar",
                "totalReturn": 0.1293,
                "sharpe": 2.6936,
                "tradeCount": 31,
                "maxDrawdown": -0.0366,
            },
            {
                "label": "V3_E3_half_hour_ranked_strict_fill",
                "totalReturn": 0.0932,
                "sharpe": 1.9207,
                "tradeCount": 31,
                "maxDrawdown": -0.0713,
            },
        ],
        "layer3Alignment": {
            "alignmentStatus": "insufficient_data",
        },
    }
    (reports_dir / "long_test_runs.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    client = TestClient(app)
    response = client.get("/api/backtests/checkpoints?limit=5")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    item = data[0]
    assert item["checkpointId"] == "checkpoint_2026-06-07_early_big_move_v3"
    assert item["h1Label"] == "E2"
    assert item["h2Label"] == "E3"
    assert item["q1Label"] is None
    assert item["h1TotalReturn"] == pytest.approx(0.1293)
    assert item["h2TotalReturn"] == pytest.approx(0.0932)
    assert item["q1TotalReturn"] is None
    assert item["e1Label"] == "E1"
    assert item["e1SignalCount"] == 71266
    assert item["e1ABTierCount"] == 6008
    assert item["e1TierRatio"] == pytest.approx(0.0843)
    assert item["h1Layer1Status"] == "red"
    assert item["h1DirectionAccuracy"] == pytest.approx(0.3756)
    assert item["h1Layer2Status"] == "green"
    assert item["h1Layer2Bias"] == pytest.approx(0.0361)


def test_get_checkpoints_preserves_v5_baseline_labels(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(get_settings(), "reports_dir", reports_dir)

    record = {
        "checkpointId": "checkpoint_2026-06-09_early_big_move_v5",
        "createdAt": "2026-06-09T15:30:00+00:00",
        "baselineSet": "early_big_move_v5",
        "baselines": [
            {
                "label": "V5_E1_half_hour_fusion_signal_forward30",
                "layer1SignalEfficacy": {
                    "tierRatio": 0.0481,
                    "aPlusBTierCount": 3427,
                    "totalSignals": 71266,
                    "layer1Status": "red",
                    "directionAccuracy": 0.3756,
                },
            },
            {
                "label": "V5_E2_half_hour_fusion_current_bar",
                "totalReturn": 0.31,
                "realizedReturn": 0.2774,
                "sharpe": 3.6986,
                "tradeCount": 38,
                "maxDrawdown": -0.0319,
            },
        ],
    }
    (reports_dir / "long_test_runs.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    client = TestClient(app)
    response = client.get("/api/backtests/checkpoints?limit=5")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    item = data[0]
    assert item["checkpointId"] == "checkpoint_2026-06-09_early_big_move_v5"
    assert item["e1Label"] == "V5 E1"
    assert item["h1Label"] == "V5 E2"
    assert item["h2Label"] is None
    assert item["h1TotalReturn"] == pytest.approx(0.31)
    assert item["h1Trades"] == 38
