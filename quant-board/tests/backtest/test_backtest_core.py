"""Backtest core tests: import/optimize/golden flow, quality filters,
TradeSimulator constraints, and run lifecycle.

Extracted from tests/test_quant_board.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from importlib.util import find_spec
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.core.backtest import TradeSimulator
from backend.data.models.database import init_db
from backend.data.models.models import (
    BacktestRun,
)
from backend.core.settings import get_settings
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.main import app
from backend.services import DEFAULT_BACKTEST_STRATEGY_CONFIG

from tests.fixtures.helpers import (
    BacktestRepoWriter,
    make_bundle,
    make_bundle_with_empty_hotlist,
    make_bundle_with_one_positive_price_frame,
    make_bundle_with_synthesized_empty_hotlist,
    wait_for_optimization,
)


def test_import_backtest_optimize_and_golden(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["default_snapshot_type"] == "half_hour"

    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "test", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()
    assert dataset["frame_count"] == 35

    datasets = client.get("/api/datasets")
    assert datasets.status_code == 200
    assert any(item["id"] == dataset["id"] for item in datasets.json())

    backtest = client.post(
        "/api/backtests/rank-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "randomSeed": 20260430, "strategyVersion": "test-v2"},
    )
    assert backtest.status_code == 200, backtest.text
    run = backtest.json()
    assert run["runId"]
    assert "equityCurve" in run
    assert run["isCompact"] is True
    assert run["signalCount"] >= len(run["signals"])
    assert "tradeEvents" in run
    assert "sharpe" in run
    assert run["strategyName"] == "rank_trend_candidate"
    assert run["strategyVersion"] == "test-v2"
    assert client.get(f"/api/backtests/{run['runId']}").json()["strategyVersion"] == "test-v2"
    assert run["tradeSimulation"]["entryStrategy"] == "rank_trend_candidate"
    assert run["tradeSimulation"]["config"]["minJumpConfidence"] == 90.0
    assert "controlBacktests" in run
    assert {row["key"] for row in run["controlBacktests"]} >= {"hot_top10", "a_main_only", "b_ignition_only", "a_b_combined"}
    assert "sampleDiagnostics" in run
    assert "macdDiagnostics" in run
    assert run["macdDiagnostics"]["macdFast"] == 21
    assert run["macdDiagnostics"]["macdSlow"] == 34
    assert run["macdDiagnostics"]["macdSignal"] == 13
    assert run["macdDiagnostics"]["role"] == "auxiliary_observation_only"
    assert run["dataQuality"]["researchGrade"] == "degraded"
    assert run["dataQuality"]["lowHotlistCount"] >= 1
    assert run["dataQuality"]["lowHotlistExamples"]
    assert run["warnings"]
    assert "tradeDiagnostics" in run
    assert "researchDiagnostics" in run
    research = run["researchDiagnostics"]
    assert research["policy"]["autoApplyDefaults"] is False
    assert research["policy"]["snapshotType"] == "half_hour"
    assert research["policy"]["randomSeed"] == 20260430
    assert {item["key"] for item in research["baselineComparisons"]} >= {"hot_top10", "a_main_only", "b_ignition_only", "a_b_combined"}
    assert {row["horizon"] for row in research["forwardOutcomeByTier"]} >= {1, 2, 5}
    assert "byRegimeTier" in research
    assert "byStageTier" in research
    assert run["forwardValidation"]["horizons"]
    assert "byMomentumBucket" in run["forwardValidation"]["horizons"][0]

    derived = client.post(
        "/api/datasets/import",
        json={
            "sourceType": "sqlite_snapshots",
            "sourceDatasetId": dataset["id"],
            "name": "derived",
            "snapshotTypes": ["half_hour"],
            "maxSnapshots": 35,
        },
    )
    assert derived.status_code == 200, derived.text
    derived_dataset = derived.json()
    assert derived_dataset["source_type"] == "sqlite_snapshots"
    assert derived_dataset["id"] != dataset["id"]
    assert derived_dataset["policy"] == "snapshot_facts_derived_dataset"
    assert derived_dataset["frame_count"] == 35
    assert derived_dataset["stock_row_count"] >= 35
    assert derived_dataset["metadata"]["sourceDatasetId"] == dataset["id"]
    assert derived_dataset["metadata"]["filters"]["maxSnapshots"] == 35
    assert any(item["id"] == derived_dataset["id"] for item in client.get("/api/datasets").json())

    derived_range = client.post(
        "/api/datasets/import",
        json={
            "sourceType": "sqlite_snapshots",
            "sourceDatasetId": dataset["id"],
            "name": "derived-range",
            "snapshotTypes": ["half_hour"],
            "startDate": "2026/4/1",
            "endDate": "2026/04/05",
        },
    )
    assert derived_range.status_code == 200, derived_range.text
    derived_range_dataset = derived_range.json()
    assert derived_range_dataset["metadata"]["filters"]["startDate"] == "2026-04-01"
    assert derived_range_dataset["metadata"]["filters"]["endDate"] == "2026-04-05"
    assert derived_range_dataset["start_date"] >= "2026-04-01"
    assert derived_range_dataset["end_date"] <= "2026-04-05"

    derived_backtest = client.post(
        "/api/backtests/rank-trend",
        json={"datasetId": derived_dataset["id"], "snapshotType": "half_hour", "randomSeed": 20260430},
    )
    assert derived_backtest.status_code == 200, derived_backtest.text
    assert derived_backtest.json()["datasetId"] == derived_dataset["id"]

    derived_dry_run = client.post(
        "/api/datasets/import",
        json={
            "sourceType": "sqlite_snapshots",
            "sourceDatasetId": dataset["id"],
            "name": "derived-dry-run",
            "snapshotTypes": ["half_hour"],
            "maxSnapshots": 5,
            "dryRun": True,
        },
    )
    assert derived_dry_run.status_code == 200, derived_dry_run.text
    assert derived_dry_run.json()["dryRun"] is True
    assert derived_dry_run.json()["virtual"] is True
    assert derived_dry_run.json()["policy"] == "snapshot_facts_view"
    assert derived_dry_run.json()["frame_count"] == 5

    golden_default = RankTrendConfig()
    assert golden_default.buyThresholds == [5, 8, 13, 21, 34]
    assert golden_default.sellThresholds == [-5, -8, -13, -21, -34]
    assert golden_default.macdFast == 13
    assert golden_default.macdSlow == 21
    assert golden_default.macdSignal == 8
    assert golden_default.requireMacdGoldenCross is False

    custom_matching_backtest = client.post(
        "/api/backtests/rank-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "positionSize": 0.12,
            "feeRate": 0.0002,
            "stampTaxRate": 0.0007,
            "slippageRate": 0.0009,
            "useOrderBookPrice": False,
            "enforceVolumeLimit": False,
            "allowPartialFills": False,
            "volumeParticipationRate": 0.02,
            "orderBookParticipationRate": 0.25,
            "intrabarAmbiguity": "take_first",
            "minJumpConfidence": 78.5,
        },
    )
    assert custom_matching_backtest.status_code == 200, custom_matching_backtest.text
    custom_config = custom_matching_backtest.json()["tradeSimulation"]["config"]
    assert custom_config["positionSize"] == 0.12
    assert custom_config["feeRate"] == 0.0002
    assert custom_config["stampTaxRate"] == 0.0007
    assert custom_config["slippageRate"] == 0.0009
    assert custom_config["useOrderBookPrice"] is False
    assert custom_config["enforceVolumeLimit"] is False
    assert custom_config["allowPartialFills"] is False
    assert custom_config["volumeParticipationRate"] == 0.02
    assert custom_config["orderBookParticipationRate"] == 0.25
    assert custom_config["intrabarAmbiguity"] == "take_first"
    assert custom_config["minJumpConfidence"] == 78.5

    fetched = client.get(f"/api/backtests/{run['runId']}")
    assert fetched.status_code == 200
    assert fetched.json()["runId"] == run["runId"]
    assert fetched.json()["isCompact"] is True
    assert fetched.json()["signalCount"] >= len(fetched.json()["signals"])
    assert len(fetched.json()["tradeEvents"]) >= len(fetched.json()["trades"])
    assert "sharpe" in fetched.json()
    assert "controlBacktests" in fetched.json()
    assert "researchDiagnostics" in fetched.json()
    assert fetched.json()["researchDiagnostics"]["policy"]["snapshotType"] == "half_hour"

    no_trade_backtest = client.post(
        "/api/backtests/rank-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "randomSeed": 20260431,
            "enableTradeSimulation": False,
        },
    )
    assert no_trade_backtest.status_code == 200, no_trade_backtest.text
    no_trade_run = no_trade_backtest.json()
    assert "researchDiagnostics" in no_trade_run
    assert no_trade_run["researchDiagnostics"]["policy"]["snapshotType"] == "half_hour"
    assert no_trade_run["researchDiagnostics"]["policy"]["randomSeed"] == 20260431
    assert no_trade_run["researchDiagnostics"]["forwardOutcomeByTier"]

    trades = client.get(f"/api/backtests/{run['runId']}/trades", params={"limit": 5, "offset": 0})
    assert trades.status_code == 200, trades.text
    trades_body = trades.json()
    assert trades_body["runId"] == run["runId"]
    assert trades_body["limit"] == 5
    assert trades_body["offset"] == 0
    assert trades_body["total"] >= len(trades_body["items"])
    if trades_body["items"]:
        assert {"code", "entryPrice", "quantity", "candidateTier"} <= set(trades_body["items"][0])

    equity = client.get(f"/api/backtests/{run['runId']}/equity")
    assert equity.status_code == 200, equity.text
    assert equity.json()["runId"] == run["runId"]
    assert len(equity.json()["items"]) == len(run["equityCurve"])

    signals = client.get(
        f"/api/backtests/{run['runId']}/signals",
        params={"limit": 5, "offset": 0, "tier": "A_MAIN"},
    )
    assert signals.status_code == 200, signals.text
    signals_body = signals.json()
    assert signals_body["runId"] == run["runId"]
    assert signals_body["filters"] == {"tier": "A_MAIN", "regime": None}
    assert signals_body["limit"] == 5
    assert signals_body["total"] >= len(signals_body["items"])
    assert all(item["candidateTier"] == "A_MAIN" for item in signals_body["items"])

    quality = client.get(f"/api/backtests/{run['runId']}/quality")
    assert quality.status_code == 200, quality.text
    quality_report = quality.json()["qualityReport"]
    assert quality_report["severity"] == "warn"
    assert quality_report["researchGrade"] == "degraded"
    assert quality_report["stockCount"] == dataset["stock_row_count"]
    assert "coverageRatio" in quality_report

    compare = client.post(
        "/api/backtests/compare",
        json={"run_ids": [run["runId"], custom_matching_backtest.json()["runId"]], "metrics": ["totalReturn", "winRate"]},
    )
    assert compare.status_code == 200, compare.text
    compare_body = compare.json()
    assert compare_body["metrics"] == ["totalReturn", "winRate"]
    assert [item["runId"] for item in compare_body["runs"]] == [run["runId"], custom_matching_backtest.json()["runId"]]
    assert all(item["snapshotType"] == "half_hour" for item in compare_body["runs"])
    assert all({"totalReturn", "winRate"} <= set(item["metrics"]) for item in compare_body["runs"])

    missing_detail = client.get("/api/backtests/bt_missing/trades").json()["detail"]
    assert missing_detail["code"] == "backtest_run_not_found"
    assert missing_detail["runId"] == "bt_missing"

    invalid_metric = client.post(
        "/api/backtests/compare",
        json={"run_ids": [run["runId"]], "metrics": ["annualReturn"]},
    )
    assert invalid_metric.status_code == 400
    assert invalid_metric.json()["detail"]["code"] == "invalid_backtest_metric"

    next_bar_backtest = client.post(
        "/api/backtests/rank-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "rank_trend_candidate",
            "executionMode": "next_bar",
        },
    )
    assert next_bar_backtest.status_code == 200, next_bar_backtest.text
    next_bar_run = next_bar_backtest.json()
    assert next_bar_run["tradeSimulation"]["executionMode"] == "next_bar"
    assert next_bar_run["tradeSimulation"]["config"]["executionMode"] == "next_bar"
    assert next_bar_run["tradeSimulation"]["matchingDiagnostics"]["nextBarEntries"] >= 0
    filled_buys = [event for event in next_bar_run["tradeEvents"] if event.get("action") == "buy"]
    if filled_buys:
        assert any(event.get("signalSnapshotId") and event.get("signalSnapshotId") != event.get("snapshotId") for event in filled_buys)

    hot_top10_backtest = client.post(
        "/api/backtests/rank-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "strategyName": "hot_top10"},
    )
    assert hot_top10_backtest.status_code == 200, hot_top10_backtest.text
    hot_top10_run = hot_top10_backtest.json()
    assert hot_top10_run["strategyName"] == "hot_top10"
    assert hot_top10_run["tradeSimulation"]["entryStrategy"] == "hot_top10"

    bad_strategy = client.post(
        "/api/backtests/rank-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "strategyName": "not_a_strategy"},
    )
    assert bad_strategy.status_code == 400
    assert "unsupported strategyName" in bad_strategy.json()["detail"]

    opt = client.post(
        "/api/optimizations/rank-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "a_main_only",
            "method": "grid",
            "trials": 2,
            "objective": "stability",
            "validationMode": "auto",
            "validationRatio": 0.3,
            "parameterGrid": {
                "momentumPeriods": [[3, 5, 8, 13, 21], [2, 4, 6, 10, 16]],
                "takeProfitPct": [0.12],
                "stopLossPct": [0.06],
                "maxPositions": [5],
                "minJumpConfidence": [77.5],
            },
        },
    )
    assert opt.status_code == 200, opt.text
    opt_start = opt.json()
    assert opt_start["runId"]
    assert opt_start["status"] == "running"
    opt_body = wait_for_optimization(client, opt_start["runId"])
    assert opt_body["status"] == "completed"
    assert opt_body["strategyName"] == "a_main_only"
    assert opt_body["dataQuality"]["researchGrade"] == "degraded"
    assert any("低热榜" in item for item in opt_body["warnings"])
    assert opt_body["experiment"]["split"]["hasValidation"] is True
    assert opt_body["overfitRisk"]["level"] in {"low", "medium", "high"}
    assert opt_body["results"][0]["metrics"]["entryStrategy"] == "a_main_only"
    assert opt_body["results"][0]["parameters"]["momentumPeriods"]
    assert opt_body["results"][0]["parameters"]["minJumpConfidence"] == 77.5
    assert opt_body["results"][0]["configHash"]
    assert opt_body["results"][0]["train"]["runId"]
    assert opt_body["results"][0]["validation"]["runId"]
    assert opt_body["results"][0]["scoreDetails"]["validationScore"] is not None
    assert opt_body["parameterStability"]["topTrialCount"] >= 1

    trial_report = client.get(f"/api/backtests/{opt_body['results'][0]['validation']['runId']}")
    assert trial_report.status_code == 200
    assert trial_report.json()["phase"] == "validation"
    assert trial_report.json()["trialId"] == opt_body["results"][0]["trialId"]

    opt_no_validation = client.post(
        "/api/optimizations/rank-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "method": "grid",
            "trials": 1,
            "validationMode": "none",
            "parameterGrid": {
                "momentumPeriods": [[3, 5, 8, 13, 21]],
                "takeProfitPct": [0.12],
                "stopLossPct": [0.06],
                "maxPositions": [5],
            },
        },
    )
    assert opt_no_validation.status_code == 200, opt_no_validation.text
    opt_no_validation_body = wait_for_optimization(client, opt_no_validation.json()["runId"])
    assert opt_no_validation_body["experiment"]["split"]["hasValidation"] is False
    assert opt_no_validation_body["overfitRisk"]["level"] == "high"

    bayes_opt = client.post(
        "/api/optimizations/rank-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "rank_trend_candidate",
            "method": "bayesian",
            "objective": "stability",
            "trials": 3,
            "validationMode": "auto",
            "validationRatio": 0.3,
            "walkForward": {
                "enabled": True,
                "trainWindowDays": 1,
                "validationWindowDays": 1,
                "stepDays": 1,
                "topTrials": 2,
            },
            "parameterGrid": {
                "momentumPeriods": [[3, 5, 8, 13, 21], [2, 4, 6, 10, 16]],
                "takeProfitPct": [0.1, 0.12],
                "stopLossPct": [0.05, 0.06],
                "maxPositions": [3, 5],
            },
        },
    )
    assert bayes_opt.status_code == 200, bayes_opt.text
    bayes_body = wait_for_optimization(client, bayes_opt.json()["runId"])
    assert bayes_body["method"] == "bayesian"
    if find_spec("torch") is None:
        assert bayes_body["status"] == "failed"
        assert bayes_body["error"]["code"] == "OPTIMIZATION_FAILED"
        assert "torch" in bayes_body["error"]["message"]
    else:
        assert bayes_body["status"] == "completed"
        assert bayes_body["optimizer"] == "optuna_gp"
        assert bayes_body["optimizerMeta"]["sampler"] == "GPSampler"
        assert bayes_body["optimizerMeta"]["model"] == "gaussian_process"
        assert bayes_body["completedTrialCount"] == 3
        assert bayes_body["walkForward"]["enabled"] is True
        assert bayes_body["walkForward"]["segmentCount"] >= 1
        assert bayes_body["results"][0]["validation"] is not None

    tpe_opt = client.post(
        "/api/optimizations/rank-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "method": "tpe",
            "objective": "stability",
            "trials": 2,
            "validationMode": "auto",
            "parameterGrid": {
                "momentumPeriods": [[3, 5, 8, 13, 21], [2, 4, 6, 10, 16]],
                "takeProfitPct": [0.1],
                "stopLossPct": [0.05],
                "maxPositions": [3],
            },
        },
    )
    assert tpe_opt.status_code == 200, tpe_opt.text
    tpe_body = wait_for_optimization(client, tpe_opt.json()["runId"])
    assert tpe_body["method"] == "tpe"
    assert tpe_body["optimizer"] == "optuna_tpe"
    assert tpe_body["optimizerMeta"]["sampler"] == "TPESampler"

    golden = client.post("/api/golden/validate", json={"caseId": "missing", "tolerance": 1e-6})
    assert golden.status_code == 200
    assert golden.json()["passed"] is False

    golden_frames = MongoRepository(get_runtime_mongodb_database()).load_frames(
        dataset["id"], snapshot_type="half_hour", include_payload=False
    )
    golden_signals = RankTrendPythonEngine(
        RankTrendConfig.from_patch(DEFAULT_BACKTEST_STRATEGY_CONFIG)
    ).replay(golden_frames, meta={"sampleQuality": "ok", "warnings": []})[:5]
    assert golden_signals
    imported_golden = client.post(
        "/api/golden/import",
        json={
            "caseId": "rank_trend_default",
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "source": "ts_golden_import",
            "payload": {
                "input": {"frames": golden_frames},
                "rankTrendConfig": DEFAULT_BACKTEST_STRATEGY_CONFIG,
                "signals": golden_signals,
            },
        },
    )
    assert imported_golden.status_code == 200, imported_golden.text
    assert imported_golden.json()["caseId"] == "rank_trend_default"
    assert imported_golden.json()["source"] == "ts_golden_import"

    validated_golden = client.post(
        "/api/golden/validate",
        json={"caseId": "rank_trend_default", "datasetId": dataset["id"], "tolerance": 1e-6},
    )
    assert validated_golden.status_code == 200
    assert validated_golden.json()["checked"] == len(golden_signals)
    assert validated_golden.json()["passed"] is True
    assert "expectedPreview" in validated_golden.json()
    assert "cycle" in validated_golden.json()["expectedPreview"][0]
    assert "decision" in validated_golden.json()["expectedPreview"][0]
    assert "transition" in validated_golden.json()["expectedPreview"][0]["cycle"]
    assert "final" in validated_golden.json()["expectedPreview"][0]["decision"]
    assert "actualPreview" in validated_golden.json()
    assert "cycle" in validated_golden.json()["actualPreview"][0]
    assert "decision" in validated_golden.json()["actualPreview"][0]
    assert "transition" in validated_golden.json()["actualPreview"][0]["cycle"]
    assert "final" in validated_golden.json()["actualPreview"][0]["decision"]

    limited_golden = client.post(
        "/api/golden/validate",
        json={"caseId": "rank_trend_default", "datasetId": dataset["id"], "tolerance": 1e-6, "sampleLimit": 3},
    )
    assert limited_golden.status_code == 200
    assert limited_golden.json()["checked"] == 3
    assert limited_golden.json()["expectedCount"] == len(golden_signals)
    assert limited_golden.json()["passed"] is True

    insufficient_golden = client.post(
        "/api/golden/validate",
        json={"caseId": "rank_trend_default", "datasetId": dataset["id"], "tolerance": 1e-6, "sampleLimit": 6},
    )
    assert insufficient_golden.status_code == 200
    assert insufficient_golden.json()["passed"] is False
    assert insufficient_golden.json()["checked"] == len(golden_signals)
    assert "re-export/import a larger TS Golden" in insufficient_golden.json()["issues"][0]

    dry_run = client.post(
        "/api/datasets/import",
        json={
            "sourceType": "json_bundle",
            "sourcePath": str(bundle),
            "name": "dry-run-test",
            "snapshotTypes": ["half_hour"],
            "dryRun": True,
        },
    )
    assert dry_run.status_code == 200, dry_run.text
    assert dry_run.json()["dryRun"] is True
    after_dry_run = client.get("/api/datasets")
    assert not any(item["id"] == dry_run.json()["id"] for item in after_dry_run.json())

    indexeddb_import = client.post(
        "/api/datasets/import",
        json={"sourceType": "indexeddb", "name": "legacy-browser-import", "records": [{"id": "s1"}]},
    )
    assert indexeddb_import.status_code == 400
    assert "sourceType=indexeddb is removed" in indexeddb_import.json()["detail"]


def test_backtest_retains_empty_hotlist_frames_with_quality_warning(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle_with_empty_hotlist(tmp_path)

    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "empty-hotlist", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()
    assert dataset["qualityGate"]["passed"] is False
    assert dataset["qualityGate"]["stats"]["emptyHotlistCount"] == 3

    response = client.post(
        "/api/backtests/rank-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "randomSeed": 20260430},
    )
    assert response.status_code == 200, response.text
    run = response.json()
    data_quality = run["dataQuality"]
    assert data_quality["severity"] == "warn"
    assert data_quality["researchGrade"] == "degraded"
    assert data_quality["emptyHotlistCount"] == 3
    assert data_quality["droppedEmptyHotlistSnapshots"] == 0
    assert data_quality["retainedEmptyHotlistSnapshots"] == 3
    assert data_quality["snapshotCount"] == dataset["frame_count"]
    assert data_quality["sourceSnapshotCount"] == dataset["frame_count"]
    assert data_quality["runtimeObservation"]["reason"] == "quality_issues_retained_for_backtest"
    assert any("保留 3 个空热榜快照" in item for item in run["warnings"])


def test_backtest_omits_empty_layer2_and_explains_synthesized_empty_hotlist(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle_with_synthesized_empty_hotlist(tmp_path)

    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "synth-empty-hotlist", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/rank-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "randomSeed": 20260430},
    )
    assert response.status_code == 200, response.text
    run = response.json()
    data_quality = run["dataQuality"]

    assert "layer2ExecutionQuality" not in data_quality
    assert data_quality["emptyHotlistCount"] == 3
    zero_examples = [example for example in data_quality["lowHotlistExamples"] if example["stockRowCount"] == 0]
    assert zero_examples
    assert all(example["captureMode"] == "synthesized" for example in zero_examples)
    assert any("synthesized 补帧" in item for item in run["warnings"])
    assert any("并非原始热榜抓取为 0 行" in item for item in run["warnings"])
    assert not any(item.startswith("Empty hotlist snapshot:") for item in run["warnings"])


def test_ranktrend_backtest_retains_frames_when_price_filter_leaves_too_few_usable_frames(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle_with_one_positive_price_frame(tmp_path)

    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "price-filter-block", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/rank-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "randomSeed": 20260430,
            "excludeNonPositivePriceRows": True,
        },
    )

    assert response.status_code == 200, response.text
    quality_gate = response.json()["dataQuality"]["qualityGate"]
    assert quality_gate["passed"] is False
    assert quality_gate["severity"] == "fail"
    assert quality_gate["runtimeFilter"]["priceFilter"]["emptySnapshotsAfterFilter"] == dataset["frame_count"] - 1
    assert quality_gate["runtimeFilter"]["priceFilter"]["usableTargetFrames"] == 1
    assert "runtime filters left usable snapshots below minimum 2: 1" in quality_gate["issues"]


def test_ranktrend_backtest_price_quality_diagnostics_are_report_only_by_default(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    first_hotlist = data["records"][0]["payload"]["hotlist"]
    first_hotlist.append(
        {"code": "009992", "name": "泡泡玛特", "rank": 3, "price": 0, "change": 0, "volume": 0, "turnover": 0}
    )
    first_hotlist.append(
        {"code": "600537", "name": "亿晶光电", "rank": 4, "price": 0, "change": 0, "volume": 100, "turnover": 1000}
    )
    data["records"][1]["payload"]["hotlist"] = [
        {"code": "000001", "name": "平安银行", "rank": 1, "price": 0},
        {"code": "000002", "name": "万科A", "rank": 2, "price": None},
    ]
    bundle.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "price-diagnostics", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/rank-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "randomSeed": 20260430},
    )

    assert response.status_code == 200, response.text
    run = response.json()
    data_quality = run["dataQuality"]
    price_quality = data_quality["reportOnlyDiagnostics"]["priceQuality"]
    assert data_quality["severity"] == "warn"
    assert data_quality["runtimeFilter"] == {}
    assert price_quality["role"] == "report_only"
    assert price_quality["autoApplyDefaults"] is False
    assert price_quality["computedBeforeResearchFilters"] is True
    assert price_quality["crossMarketZeroPriceRows"]["rowCount"] == 1
    assert price_quality["allZeroPriceFrames"]["frameCount"] == 1
    assert price_quality["partialAshareZeroPriceRows"]["rowCount"] == 1


def test_trade_simulator_realistic_matching_constraints() -> None:
    base_signal = {
        "snapshotId": "s1",
        "timestamp": 1,
        "tradingDate": "2026-04-01",
        "slotTime": "10:00",
        "code": "600001",
        "name": "样本A",
        "rank": 1,
        "price": 10,
        "change": 3,
        "ask1Price": 10.05,
        "ask1Volume": 500,
        "bid1Price": 9.95,
        "bid1Volume": 500,
        "volume": 1000,
        "candidateTier": "A_MAIN",
        "stage": "markup",
        "regime": "strong",
        "confidence": 80,
        "rankTrend": {"strategy": {"momentum": {"acceleration": 1}}, "technical": {}, "risk": {}, "decision": {}},
    }

    no_fill = TradeSimulator().run(
        [{"snapshotId": "s1", "timestamp": 1, "tradingDate": "2026-04-01", "slotTime": "10:00"}],
        [{**base_signal, "change": 10.0, "leadStatus": "涨停"}],
        {
            # 阶段6：A_MAIN 降级观察档后默认策略不入场，本测试验证 A_MAIN 成交约束，
            # 用 a_main_only 对照组显式启用
            "initialCapital": 100000,
            "positionSize": 1,
            "maxPositions": 1,
            "entryStrategy": "a_main_only",
        },
    )
    assert no_fill["tradeCount"] == 0
    assert no_fill["matchingDiagnostics"]["blockedByLimit"] == 1
    assert no_fill["skippedOrders"][0]["reason"] == "limit_up_unbuyable"

    partial = TradeSimulator().run(
        [{"snapshotId": "s1", "timestamp": 1, "tradingDate": "2026-04-01", "slotTime": "10:00"}],
        [base_signal],
        {
            "initialCapital": 100000,
            "positionSize": 1,
            "maxPositions": 1,
            "slippageRate": 0,
            "orderBookParticipationRate": 1,
            "volumeParticipationRate": 1,
            "entryStrategy": "a_main_only",
        },
    )
    buy_event = partial["tradeEvents"][0]
    assert buy_event["price"] == 10.05
    assert buy_event["quantity"] == 500
    assert buy_event["fill"]["partial"] is True
    assert partial["matchingDiagnostics"]["orderBookPricedFills"] == 1

    missing_next_bar_quote = TradeSimulator().run(
        [
            {"snapshotId": "s1", "timestamp": 1, "tradingDate": "2026-04-01", "slotTime": "10:00"},
            {"snapshotId": "s2", "timestamp": 2, "tradingDate": "2026-04-01", "slotTime": "10:30"},
        ],
        [base_signal],
        {
            "initialCapital": 100000,
            "positionSize": 1,
            "maxPositions": 1,
            "executionMode": "next_bar",
            "entryStrategy": "a_main_only",
        },
    )
    assert missing_next_bar_quote["eventCount"] == 0
    assert missing_next_bar_quote["matchingDiagnostics"]["nextBarEntries"] == 0
    assert missing_next_bar_quote["matchingDiagnostics"]["missingPriceRows"] >= 1


def test_trade_simulator_allows_a_main_entries_without_explicit_final_signal() -> None:
    signal = {
        "snapshotId": "s1",
        "timestamp": 1,
        "tradingDate": "2026-04-01",
        "slotTime": "10:00",
        "code": "600001",
        "name": "样本A",
        "rank": 1,
        "price": 10,
        "ask1Price": 10.05,
        "ask1Volume": 500,
        "bid1Price": 9.95,
        "bid1Volume": 500,
        "volume": 1000,
        "candidateTier": "A_MAIN",
        "stage": "mainline",
        "regime": "strong",
        "confidence": 80,
        "rankTrend": {"strategy": {"momentum": {"acceleration": 1}}, "technical": {}, "risk": {}, "decision": {}},
    }

    result = TradeSimulator().run(
        [{"snapshotId": "s1", "timestamp": 1, "tradingDate": "2026-04-01", "slotTime": "10:00"}],
        [signal],
        {
            # 阶段6：A_MAIN 降级观察档后默认策略不入场，本测试验证 A_MAIN 入场路径，
            # 用 a_main_only 对照组显式启用
            "initialCapital": 100000,
            "positionSize": 1,
            "maxPositions": 1,
            "slippageRate": 0,
            "entryStrategy": "a_main_only",
        },
    )

    assert result["matchingDiagnostics"]["buyAttempts"] == 1
    assert result["eventCount"] == 1
    assert result["tradeEvents"][0]["action"] == "buy"


def test_delete_backtest_run_removes_normalized_children() -> None:
    init_db()
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    run_id = f"bt_delete_{suffix}"
    with BacktestRepoWriter() as writer:
        writer.save_run(
            BacktestRun(
                id=run_id,
                dataset_id="ds_delete",
                strategy_name="rank_trend_candidate",
                snapshot_type="half_hour",
                config_hash="cfg_delete",
                random_seed=20260430,
                status="completed",
                request_json="{}",
                result_json='{"totalReturn": 0.01}',
            )
        )
        writer.save_trades(run_id, [{"code": "600001", "name": "A", "quantity": 100, "profit": 12.3}])
        writer.save_equity_curve(run_id, [{"snapshotId": "s1", "equity": 100000.0}])
        writer.save_signals(
            run_id,
            {"frameResults": [{"snapshotId": "s1", "tradingDate": "2026-04-30", "buyCandidates": [{"code": "600001", "signal": "buy"}]}]},
        )
        writer.save_quality_report(run_id, {"severity": "pass", "researchGrade": "research_ready", "snapshotCount": 1}, {})

    response = client.delete(f"/api/backtests/{run_id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["deleted"]["backtest_runs"] == 1
    assert body["deleted"]["backtest_trades"] == 1
    assert body["deleted"]["backtest_equity_curve"] == 1
    assert body["deleted"]["backtest_signals"] == 1
    assert body["deleted"]["backtest_quality_reports"] == 1

    assert client.get(f"/api/backtests/{run_id}").status_code == 404
    # mongo 单链：删除效果已由 deleted counts + 404 覆盖


def test_list_backtest_runs_returns_recent_lightweight_history() -> None:
    init_db()
    client = TestClient(app)
    now = datetime.utcnow()
    suffix = now.strftime("%Y%m%d%H%M%S%f")
    runs = [
        BacktestRun(
            id=f"bt_history_old_{suffix}",
            dataset_id="ds_history",
            strategy_name="rank_trend_candidate",
            strategy_version="0.1.0",
            snapshot_type="half_hour",
            config_hash="cfg_old",
            random_seed=20260430,
            status="completed",
            date_start="2026-06-01",
            date_end="2026-06-05",
            result_json='{"totalReturn": 0.01}',
            created_at=now - timedelta(minutes=2),
        ),
        BacktestRun(
            id=f"bt_history_mid_{suffix}",
            dataset_id="ds_history",
            strategy_name="rank_trend_candidate",
            strategy_version="0.1.0",
            snapshot_type="half_hour",
            config_hash="cfg_mid",
            random_seed=20260430,
            status="completed",
            date_start="2026-06-01",
            date_end="2026-06-06",
            result_json='{"totalReturn": 0.02}',
            created_at=now - timedelta(minutes=1),
        ),
        BacktestRun(
            id=f"bt_history_new_{suffix}",
            dataset_id="ds_history",
            strategy_name="rank_trend_candidate",
            strategy_version="0.1.0",
            snapshot_type="half_hour",
            config_hash="cfg_new",
            random_seed=20260430,
            status="completed",
            date_start="2026-06-01",
            date_end="2026-06-07",
            result_json='{"totalReturn": 0.03}',
            created_at=now,
        ),
    ]
    with BacktestRepoWriter() as writer:
        for run in runs:
            writer.save_run(run)

    response = client.get("/api/backtests?limit=100")
    assert response.status_code == 200, response.text
    body = response.json()
    our_ids = {run.id for run in runs}
    response_ids = [item["runId"] for item in body["items"]]
    assert our_ids.issubset(set(response_ids)), f"Missing runs in response: {our_ids - set(response_ids)}"
    # Our newest run should appear before the oldest
    new_idx = response_ids.index(runs[2].id)
    old_idx = response_ids.index(runs[0].id)
    assert new_idx < old_idx, f"Newest run {runs[2].id} at {new_idx} should be before oldest {runs[0].id} at {old_idx}"
    for item in body["items"]:
        if item["runId"] == runs[2].id:
            assert item["datasetId"] == "ds_history"
            assert item["snapshotType"] == "half_hour"
            assert item["dateEnd"] == "2026-06-07"
            assert "result_json" not in item
            assert "result" not in item
            break
    else:
        pytest.fail(f"Newest run {runs[2].id} not found in response")

    # Cleanup: remove test runs to avoid polluting other tests that share this DB
    with BacktestRepoWriter() as writer:
        for run in runs:
            writer.delete_run(run.id)


def test_ranktrend_backtest_includes_layer1_signal_efficacy(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    bundle.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "layer1-test", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/rank-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "randomSeed": 20260430},
    )
    assert response.status_code == 200, response.text
    run = response.json()

    data_quality = run.get("dataQuality") or {}
    layer1 = data_quality.get("layer1SignalEfficacy")
    assert layer1 is not None, "Layer 1 signal efficacy missing from backtest output"
    assert "tierRatio" in layer1
    assert "directionAccuracy" in layer1
    assert "layer1Status" in layer1
    assert layer1["totalSignals"] > 0
