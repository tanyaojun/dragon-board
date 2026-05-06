from __future__ import annotations

import json
import math
import time
from types import SimpleNamespace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from importlib.util import find_spec
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.analysis.ranktrend import RankTrendConfig, analyze_cycle, analyze_momentum_signals, analyze_risk, analyze_technical
from backend.cli import build_parser, build_ranktrend_payload, cmd_migrate_snapshots, cmd_verify_themes
from backend.core.backtest import TradeSimulator
from backend.data.database import ResearchSessionLocal, SessionLocal, init_db
from backend.data.backup_sync import BackupSyncService
from backend.data.models import (
    BacktestEquityCurve,
    BacktestQualityReport,
    BacktestRun,
    BacktestSignal,
    BacktestTrade,
    Dataset,
    GoldenRankTrendCase,
    OptimizationRun,
    SyncOutboxModel,
)
from backend.data.repository import Repository
from backend.data.supabase_homomorphic import SupabaseBackupClient, _chunk_rows_by_payload_size
from backend.main import app
from backend.services import DEFAULT_BACKTEST_STRATEGY_CONFIG, BacktestService
from backend.utils import json_dumps


def wait_for_optimization(client: TestClient, run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        response = client.get(f"/api/optimizations/{run_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("status") in {"completed", "failed"}:
            return last
        time.sleep(0.1)
    raise AssertionError(f"optimization did not finish: {last}")


def make_bundle(path: Path) -> Path:
    frames = []
    records = []
    for i in range(35):
        day = i // 7 + 1
        bar = i % 7
        date = f"2026-04-{day:02d}"
        slot = f"{10 + (bar // 2):02d}:{(bar % 2) * 30:02d}"
        snapshot_id = f"half_hour:{date}:{i:02d}"
        hotlist = [
            {
                "code": "600001",
                "name": "样本A",
                "rank": max(1, 50 - i),
                "price": 10 + i * 0.1,
                "change": 1,
                "volumeRatio": 1.3,
                "zlje": 1000000,
                "zljzb": 3,
            },
            {
                "code": "600002",
                "name": "样本B",
                "rank": 20 + (i % 5),
                "price": 20 - i * 0.03,
                "change": -0.5,
                "volumeRatio": 0.9,
                "zlje": -100000,
                "zljzb": -1,
            },
        ]
        if i in {3, 10}:
            hotlist = hotlist[:1]
        record = {
            "id": snapshot_id,
            "type": "half_hour",
            "tradingDate": date,
            "slotTime": slot,
            "timestamp": 1775000000000 + i * 1800000,
            "captureMode": "real_time",
            "payload": {"type": "half_hour", "tradingDate": date, "slotTime": slot, "timestamp": 1775000000000 + i * 1800000, "hotlist": hotlist},
        }
        records.append(record)
    bundle = path / "bundle.json"
    bundle.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    return bundle


def make_bundle_with_empty_hotlist(path: Path) -> Path:
    bundle = make_bundle(path)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    records = data["records"]
    for index in {8, 15, 22}:
        records[index]["payload"]["hotlist"] = []
    bundle.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    return bundle


def make_theme_trade_bundle(path: Path) -> Path:
    frames = []
    records = []
    for i in range(8):
        date = f"2026-04-{1 + i // 4:02d}"
        slot = f"{10 + (i % 4) // 2:02d}:{((i % 4) % 2) * 30:02d}"
        snapshot_id = f"half_hour:{date}:theme:{i:02d}"
        hotlist = [
            {
                "code": "600001",
                "name": "题材龙头",
                "rank": 1,
                "price": 10 + i * 0.2,
                "lastTradePrice": 10 + i * 0.2,
                "change": 1.2,
                "volume": 10000000,
                "turnover": 100000000,
                "volumeRatio": 2.2,
                "zlje": 3000000,
                "zljzb": 6,
                "mainTheme": "机器人",
                "themeRole": "leader",
                "themeContribution": 20,
                "themeExposureWeight": 88,
            }
        ]
        sectors = [
            {
                "name": "机器人",
                "entityName": "机器人",
                "entityKey": "robot",
                "rank": 1,
                "heatScore": 86,
                "momentumScore": 82,
                "breadthScore": 68,
                "fundScore": 70,
                "leadershipScore": 85,
                "correlationScore": 65,
                "crowdingRisk": 35,
                "persistenceScore": 72,
                "rotationState": "mainline",
            }
        ]
        record = {
            "id": snapshot_id,
            "type": "half_hour",
            "tradingDate": date,
            "slotTime": slot,
            "timestamp": 1775000000000 + i * 1800000,
            "captureMode": "real_time",
            "payload": {
                "type": "half_hour",
                "tradingDate": date,
                "slotTime": slot,
                "timestamp": 1775000000000 + i * 1800000,
                "hotlist": hotlist,
                "sectors": sectors,
            },
        }
        records.append(record)
    bundle = path / "theme_trade_bundle.json"
    bundle.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    return bundle


def add_theme_follower_to_bundle(bundle: Path) -> None:
    data = json.loads(bundle.read_text(encoding="utf-8"))
    for record in data["records"]:
        record["payload"]["hotlist"].append(
            {
                "code": "600002",
                "name": "题材跟随",
                "rank": 2,
                "price": 9.5,
                "lastTradePrice": 9.5,
                "change": 0.8,
                "volume": 8000000,
                "turnover": 80000000,
                "volumeRatio": 1.5,
                "zlje": 1000000,
                "zljzb": 3,
                "mainTheme": "机器人",
                "themeRole": "follower",
                "themeContribution": 6,
                "themeExposureWeight": 62,
            }
        )
    bundle.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_supabase_upsert_chunks_are_limited_by_payload_size() -> None:
    rows = [
        {"id": "a", "code": "600001", "name": "x" * 40},
        {"id": "b", "code": "600002", "name": "y" * 40},
        {"id": "c", "code": "600003", "name": "z" * 40},
    ]

    chunks = _chunk_rows_by_payload_size(rows, max_rows=100, max_payload_bytes=90)

    assert [len(chunk) for chunk in chunks] == [1, 1, 1]
    assert [chunk[0]["id"] for chunk in chunks] == ["a", "b", "c"]


def test_supabase_theme_string_fields_preserve_explicit_empty_values() -> None:
    stock_row = SupabaseBackupClient._stock_to_row(
        "ds_1",
        {
            "snapshotId": "snap_1",
            "code": "000001",
            "themeRole": "",
            "theme_role": "leader",
        },
    )
    sector_row = SupabaseBackupClient._sector_to_row(
        "ds_1",
        {
            "snapshotId": "snap_1",
            "entityType": "hot_theme",
            "entityKey": "AI",
            "rotationState": "",
            "rotation_state": "mainline",
        },
    )

    assert stock_row["theme_role"] == ""
    assert sector_row["rotation_state"] == ""


def test_ranktrend_uses_fallback_until_technical_min_samples() -> None:
    config = RankTrendConfig()
    percentiles = [
        40,
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        50,
        51,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
        59,
        60,
        61,
        62,
        63,
        64,
        65,
        66,
        67,
        68,
    ]
    fallback = {"displayChange": 2.2, "stockChange": 1.8, "volumeRatio": 1.5, "zlje": 1, "zljzb": 1}

    technical = analyze_technical(percentiles, config, fallback)

    assert len(percentiles) < 30
    display_score = math.tanh(fallback["displayChange"] / 8)
    price_score = math.tanh(fallback["stockChange"] / 6)
    volume_score = math.tanh((fallback["volumeRatio"] - 1) / 0.75)
    expected_direction_score = display_score * 0.4 + price_score * 0.3 + 0.2 + volume_score * 0.1
    expected_direction_confidence = 50 + abs(expected_direction_score) * 40 + 4.5

    assert abs(technical["signals"]["direction"]["score"] - expected_direction_score) < 1e-12
    assert abs(technical["signals"]["direction"]["confidence"] - expected_direction_confidence) < 1e-12
    assert technical["signals"]["direction"]["signal"] == "buy"
    assert technical["signals"]["acceleration"]["confidence"] > 50


def test_ranktrend_momentum_signals_match_typescript_edge_cases() -> None:
    config = RankTrendConfig()
    signals = analyze_momentum_signals(
        {
            "values": [-1, -1, 0, 0, 0],
            "prevValues": [-4, -4, -3, -3, -3],
        },
        config,
    )

    assert signals["acceleration"]["signal"] == "buy"
    assert signals["acceleration"]["score"] > 0.18

    confirm_value = -math.atanh(0.13) * abs(config.sellThresholds[1])
    zero_cross = analyze_momentum_signals(
        {
            "values": [1, confirm_value, 0, 0, 0],
            "prevValues": [0, 0, 0, 0, 0],
        },
        config,
    )

    assert zero_cross["zeroCross"]["signal"] == "buy"


def test_ranktrend_risk_severity_clamps_before_stage_multiplier() -> None:
    risk = analyze_risk(
        90,
        {
            "macd": {"histogram": 0},
            "signals": {
                "direction": {"signal": "hold"},
                "acceleration": {"signal": "buy"},
                "zeroCross": {"signal": "hold"},
            },
        },
        {
            "stage": "cooling",
            "metrics": {
                "rankVelocity": 1,
                "rankAcceleration": 0,
                "rankShock": 0,
            },
        },
        zlje=-1,
        zljzb=-1,
        volume_ratio=1,
    )

    assert risk["divergence"]["severity"] == pytest.approx(0.15166666666666667)
    assert risk["pressure"] == pytest.approx(0.0637)


def test_ranktrend_cycle_crowded_raw_stage_persists_like_typescript() -> None:
    ranks = [
        147,
        186,
        192,
        189,
        166,
        150,
        53,
        4,
        3,
        3,
        8,
        7,
        7,
        8,
        8,
        10,
        11,
        10,
        12,
        20,
        30,
        31,
        20,
        14,
        16,
        8,
        5,
    ]
    percentiles = [
        45.52238805970149,
        20.600858369098713,
        30.79710144927536,
        27.413127413127413,
        36.29343629343629,
        51.77993527508091,
        76.78571428571429,
        98.45360824742268,
        96.0,
        99.10313901345292,
        97.4910394265233,
        98.07073954983923,
        97.32142857142857,
        96.72897196261681,
        97.21115537848605,
        96.34146341463415,
        95.63318777292577,
        96.08695652173913,
        95.23809523809523,
        92.08333333333333,
        87.71186440677965,
        87.28813559322035,
        92.14876033057851,
        94.6058091286307,
        93.44978165938865,
        96.875,
        98.23008849557522,
    ]

    cycle = analyze_cycle(ranks, percentiles)

    assert cycle["rawStage"] == "crowded"
    assert cycle["stage"] == "cooling"
    assert cycle["previousStage"] == "cooling"


def test_import_backtest_optimize_and_golden(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["default_snapshot_type"] == "half_hour"
    assert "autoSync" in health.json()["database"]
    assert "backupRetention" in health.json()["database"]

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
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "randomSeed": 20260430},
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
    assert run["tradeSimulation"]["entryStrategy"] == "rank_trend_candidate"
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
    assert derived_dataset["id"] == dataset["id"]
    assert derived_dataset["virtual"] is True
    assert derived_dataset["policy"] == "snapshot_facts_view"
    assert derived_dataset["frame_count"] == 35
    assert derived_dataset["stock_row_count"] >= 35
    assert derived_dataset["metadata"]["sourceDatasetId"] == dataset["id"]
    assert derived_dataset["metadata"]["filters"]["maxSnapshots"] == 35

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
    assert derived_dry_run.json()["frame_count"] == 5

    golden_default = RankTrendConfig()
    assert golden_default.macdFast == 13
    assert golden_default.macdSlow == 21
    assert golden_default.macdSignal == 8

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

    fetched = client.get(f"/api/backtests/{run['runId']}")
    assert fetched.status_code == 200
    assert fetched.json()["runId"] == run["runId"]
    assert fetched.json()["isCompact"] is True
    assert fetched.json()["signalCount"] >= len(fetched.json()["signals"])
    assert len(fetched.json()["tradeEvents"]) >= len(fetched.json()["trades"])
    assert "sharpe" in fetched.json()
    assert "controlBacktests" in fetched.json()

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

    golden_signals = run["signals"][:5]
    assert golden_signals
    with SessionLocal() as session:
        golden_frames = Repository(session).load_frames(dataset["id"], snapshot_type="half_hour", include_payload=False)
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

    empty_browser_import = client.post(
        "/api/datasets/import",
        json={"sourceType": "indexeddb", "name": "empty-browser-import", "records": [], "preview": None},
    )
    assert empty_browser_import.status_code == 400
    assert "browser_bridge" in empty_browser_import.json()["detail"]


def test_backtest_excludes_empty_hotlist_frames_but_keeps_quality_warning(tmp_path: Path) -> None:
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
    assert data_quality["droppedEmptyHotlistSnapshots"] == 3
    assert data_quality["snapshotCount"] == dataset["frame_count"] - 3
    assert data_quality["sourceSnapshotCount"] == dataset["frame_count"]
    assert data_quality["runtimeFilter"]["reason"] == "empty_hotlist_snapshots_excluded"
    assert any("自动剔除 3 个空热榜快照" in item for item in run["warnings"])


def test_snapshot_ingest_is_idempotent_and_queues_outbox() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_live_test_{suffix}"
    idempotency_key = f"ingest-test-key-{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            {
                "id": "half_hour:2026-04-21:10:00",
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "displayKey": "[半小时快照] 2026-04-21 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-21",
                    "slotTime": "10:00",
                    "timestamp": 1776746400000,
                    "hotlist": [{"code": "600001", "name": "样本A", "rank": 1, "price": 10}],
                },
            }
        ],
    }

    first = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "tradingDate": "2026-04-21",
            "bundle": bundle,
        },
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["ok"] is True
    assert first_body["deduped"] is False
    assert first_body["outbox"]["status"] == "pending"
    assert first_body["dataset"]["id"] == dataset_id
    assert first_body["dataset"]["frame_count"] == 1
    assert first_body["dataset"]["stock_row_count"] == 1

    second = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "tradingDate": "2026-04-21",
            "bundle": bundle,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["deduped"] is True

    datasets = client.get("/api/datasets")
    assert any(item["id"] == dataset_id and item["frame_count"] == 1 for item in datasets.json())


def test_snapshot_ingest_dedupes_existing_snapshot_id_without_replacing_rows() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_live_existing_{suffix}"
    snapshot_id = "half_hour:2026-04-21:10:00"
    base_bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "displayKey": "[半小时快照] 2026-04-21 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-21",
                    "slotTime": "10:00",
                    "timestamp": 1776746400000,
                    "hotlist": [{"code": "600001", "name": "样本A", "rank": 1, "price": 10}],
                },
            }
        ],
    }
    changed_bundle = {
        **base_bundle,
        "items": [
            {
                **base_bundle["items"][0],
                "payload": {
                    **base_bundle["items"][0]["payload"],
                    "hotlist": [{"code": "600999", "name": "不应覆盖", "rank": 1, "price": 99}],
                },
            }
        ],
    }

    first = client.post(
        "/api/snapshots/ingest",
        json={"datasetId": dataset_id, "idempotencyKey": f"first-{suffix}", "bundle": base_bundle},
    )
    assert first.status_code == 200, first.text
    assert first.json()["deduped"] is False

    second = client.post(
        "/api/snapshots/ingest",
        json={"datasetId": dataset_id, "idempotencyKey": f"second-{suffix}", "bundle": changed_bundle},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["deduped"] is True
    assert second_body["outbox"]["status"] == "pending"

    stocks = client.get("/api/snapshots/stock-rows", params={"dataset_id": dataset_id, "snapshot_id": snapshot_id})
    assert stocks.status_code == 200, stocks.text
    assert [row["code"] for row in stocks.json()["rows"]] == ["600001"]


def test_snapshot_ingest_filters_existing_snapshot_ids_from_mixed_bundle() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_live_mixed_{suffix}"
    existing_snapshot_id = "half_hour:2026-04-21:10:00"
    new_snapshot_id = "half_hour:2026-04-21:10:30"

    def item(snapshot_id: str, slot_time: str, code: str) -> dict[str, Any]:
        return {
            "id": snapshot_id,
            "type": "half_hour",
            "tradingDate": "2026-04-21",
            "slotTime": slot_time,
            "timestamp": 1776746400000,
            "displayKey": f"[半小时快照] 2026-04-21 {slot_time}",
            "captureMode": "real_time",
            "source": "browser_runtime",
            "payload": {
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": slot_time,
                "timestamp": 1776746400000,
                "hotlist": [{"code": code, "name": code, "rank": 1, "price": 10}],
            },
        }

    first_bundle = {"version": "v4", "tradingDate": "2026-04-21", "items": [item(existing_snapshot_id, "10:00", "600001")]}
    mixed_bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            item(existing_snapshot_id, "10:00", "600999"),
            item(new_snapshot_id, "10:30", "600002"),
        ],
    }

    first = client.post(
        "/api/snapshots/ingest",
        json={"datasetId": dataset_id, "idempotencyKey": f"first-mixed-{suffix}", "bundle": first_bundle},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/snapshots/ingest",
        json={"datasetId": dataset_id, "idempotencyKey": f"second-mixed-{suffix}", "bundle": mixed_bundle},
    )
    assert second.status_code == 200, second.text
    assert second.json()["deduped"] is False

    counts = client.get("/api/snapshots/counts", params={"dataset_id": dataset_id})
    assert counts.status_code == 200, counts.text
    assert counts.json()["counts"]["snapshot_frames"] == 2
    assert counts.json()["counts"]["snapshot_stock_rows"] == 2

    existing_rows = client.get(
        "/api/snapshots/stock-rows",
        params={"dataset_id": dataset_id, "snapshot_id": existing_snapshot_id},
    )
    assert existing_rows.status_code == 200, existing_rows.text
    assert [row["code"] for row in existing_rows.json()["rows"]] == ["600001"]

    new_rows = client.get(
        "/api/snapshots/stock-rows",
        params={"dataset_id": dataset_id, "snapshot_id": new_snapshot_id},
    )
    assert new_rows.status_code == 200, new_rows.text
    assert [row["code"] for row in new_rows.json()["rows"]] == ["600002"]


def test_snapshot_frames_api_reads_sqlite_frame_bundles() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_sqlite_read_{suffix}"
    snapshot_id = f"half_hour:2026-04-21:{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "displayKey": "[半小时快照] 2026-04-21 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {"hotlist": [{"code": "600001", "name": "样本A", "rank": 1}]},
            }
        ],
        "frames": [
            {
                "id": snapshot_id,
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "stockRowCount": 1,
                "sectorRowCount": 1,
                "rotationSummary": {"stage": "start"},
            }
        ],
        "stockRows": [
            {
                "id": f"{snapshot_id}:600001",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "code": "600001",
                "name": "样本A",
                "rank": 1,
                "price": 10,
            }
        ],
        "sectorRows": [
            {
                "id": f"{snapshot_id}:sector:AI",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "entityType": "sector",
                "entityKey": "AI",
                "entityName": "人工智能",
                "rank": 1,
                "strength": 90,
            }
        ],
    }

    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"sqlite-read-key-{suffix}",
            "tradingDate": "2026-04-21",
            "bundle": bundle,
        },
    )
    assert ingest.status_code == 200, ingest.text

    response = client.get(
        "/api/snapshots/frames",
        params={
            "dataset_id": dataset_id,
            "snapshot_type": "half_hour",
            "trading_date": "2026-04-21",
            "allowed_capture_modes": "real_time",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "sqlite"
    assert body["count"] == 1
    frame = body["frames"][0]
    assert frame["snapshotId"] == snapshot_id
    assert frame["hotlist"][0]["code"] == "600001"
    assert frame["sectors"][0]["name"] == "人工智能"


def test_snapshot_detail_read_apis_use_sqlite() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_sqlite_detail_{suffix}"
    snapshot_id = f"half_hour:2026-04-22:{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-22",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-22",
                "slotTime": "10:30",
                "timestamp": 1776834600000,
                "displayKey": "[半小时快照] 2026-04-22 10:30",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {"hotlist": [{"code": "600010", "name": "样本C", "rank": 1}]},
            }
        ],
        "frames": [
            {
                "id": snapshot_id,
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-22",
                "slotTime": "10:30",
                "timestamp": 1776834600000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "stockRowCount": 1,
                "sectorRowCount": 1,
            }
        ],
        "stockRows": [
            {
                "id": f"{snapshot_id}:600010",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-22",
                "slotTime": "10:30",
                "timestamp": 1776834600000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "code": "600010",
                "name": "样本C",
                "rank": 1,
                "volumeRatio": 2.5,
                "themeContribution": 15.5,
                "themeRole": "leader",
                "themeExposureWeight": 1,
                "themeRiskFlags": ["riskPenalty:2"],
            }
        ],
        "sectorRows": [
            {
                "id": f"{snapshot_id}:hot_theme:robot",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-22",
                "slotTime": "10:30",
                "timestamp": 1776834600000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "entityType": "hot_theme",
                "entityKey": "robot",
                "entityName": "机器人",
                "rank": 1,
                "momentumScore": 77,
                "crowdingRisk": 18,
                "rotationState": "mainline",
                "themeQualityFlags": [{"code": "low_sample"}],
            }
        ],
    }

    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"sqlite-detail-key-{suffix}",
            "tradingDate": "2026-04-22",
            "bundle": bundle,
        },
    )
    assert ingest.status_code == 200, ingest.text

    records = client.get(
        "/api/snapshots/records",
        params={"dataset_id": dataset_id, "snapshot_type": "half_hour", "trading_date": "2026-04-22"},
    )
    assert records.status_code == 200, records.text
    assert records.json()["records"][0]["id"] == snapshot_id

    record = client.get(f"/api/snapshots/records/{snapshot_id}", params={"dataset_id": dataset_id})
    assert record.status_code == 200, record.text
    assert record.json()["record"]["payload"] == {}
    assert record.json()["record"]["source"] == "browser_runtime"

    stocks = client.get("/api/snapshots/stock-rows", params={"dataset_id": dataset_id, "snapshot_id": snapshot_id})
    assert stocks.status_code == 200, stocks.text
    assert stocks.json()["rows"][0]["code"] == "600010"
    assert stocks.json()["rows"][0]["volumeRatio"] == 2.5
    assert stocks.json()["rows"][0]["themeContribution"] == 15.5
    assert stocks.json()["rows"][0]["themeRole"] == "leader"
    assert stocks.json()["rows"][0]["themeRiskFlags"] == ["riskPenalty:2"]

    sectors = client.get("/api/snapshots/sector-rows", params={"dataset_id": dataset_id, "snapshot_id": snapshot_id})
    assert sectors.status_code == 200, sectors.text
    assert sectors.json()["rows"][0]["captureMode"] == "real_time"
    assert sectors.json()["rows"][0]["entityName"] == "机器人"
    assert sectors.json()["rows"][0]["momentumScore"] == 77
    assert sectors.json()["rows"][0]["rotationState"] == "mainline"
    assert sectors.json()["rows"][0]["themeQualityFlags"] == [{"code": "low_sample"}]

    counts = client.get("/api/snapshots/counts", params={"dataset_id": dataset_id})
    assert counts.status_code == 200, counts.text
    assert counts.json()["counts"] == {
        "snapshots": 1,
        "snapshot_frames": 1,
        "snapshot_stock_rows": 1,
        "snapshot_sector_rows": 1,
    }


def test_snapshot_detail_read_api_applies_capture_mode_filters() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_sqlite_detail_filter_{suffix}"
    snapshot_id = f"half_hour:2026-04-23:{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-23",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-23",
                "slotTime": "10:30",
                "timestamp": 1776921000000,
                "displayKey": "[半小时快照] 2026-04-23 10:30",
                "captureMode": "restored",
                "source": "cloud_restore",
                "payload": {},
            }
        ],
    }

    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"sqlite-detail-filter-key-{suffix}",
            "tradingDate": "2026-04-23",
            "bundle": bundle,
        },
    )
    assert ingest.status_code == 200, ingest.text

    excluded = client.get(
        f"/api/snapshots/records/{snapshot_id}",
        params={"dataset_id": dataset_id, "exclude_restored": True},
    )
    assert excluded.status_code == 404, excluded.text

    real_time_only = client.get(
        f"/api/snapshots/records/{snapshot_id}",
        params={"dataset_id": dataset_id, "allowed_capture_modes": "real_time"},
    )
    assert real_time_only.status_code == 404, real_time_only.text

    restored = client.get(
        f"/api/snapshots/records/{snapshot_id}",
        params={"dataset_id": dataset_id, "allowed_capture_modes": "restored"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["record"]["captureMode"] == "restored"


def test_snapshot_ingest_summary_is_persisted_and_outbox_retry_is_due_gated() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_live_summary_{suffix}"
    idempotency_key = f"ingest-summary-key-{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-22",
        "items": [
            {
                "id": "half_hour:2026-04-22:10:00",
                "type": "half_hour",
                "tradingDate": "2026-04-22",
                "slotTime": "10:00",
                "timestamp": 1776832800000,
                "displayKey": "[半小时快照] 2026-04-22 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-22",
                    "slotTime": "10:00",
                    "timestamp": 1776832800000,
                    "hotlist": [
                        {"code": "600001", "name": "样本A", "rank": 1, "price": 10},
                        {"code": "600002", "name": "样本B", "rank": 2, "price": 11},
                    ],
                },
            }
        ],
    }
    response = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "tradingDate": "2026-04-22",
            "bundle": bundle,
        },
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as session:
        saved = session.get(Dataset, dataset_id)
        assert saved is not None
        assert saved.snapshot_count == 1
        assert saved.frame_count == 1
        assert saved.stock_row_count == 2
        assert saved.start_date == "2026-04-22"
        assert saved.end_date == "2026-04-22"

        repo = Repository(session, enable_backup=False)
        row = repo.mark_outbox_failed(idempotency_key, "temporary outage", delay_seconds=3600, max_retries=3)
        assert row is not None
        assert row.status == "retry"
        assert row.next_retry_at is not None and row.next_retry_at > datetime.utcnow()
        pending_keys = {item.idempotency_key for item in repo.list_pending_outbox(limit=100)}
        assert idempotency_key not in pending_keys

        row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        session.commit()
        pending_keys = {item.idempotency_key for item in repo.list_pending_outbox(limit=100)}
        assert idempotency_key in pending_keys

        repo.mark_outbox_failed(idempotency_key, "still down", delay_seconds=0, max_retries=3)
        failed = repo.mark_outbox_failed(idempotency_key, "still down", delay_seconds=0, max_retries=3)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.next_retry_at is None
        pending_keys = {item.idempotency_key for item in repo.list_pending_outbox(limit=100)}
        assert idempotency_key not in pending_keys


def test_push_outbox_api_reports_due_items() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    with SessionLocal() as session:
        row = Repository(session, enable_backup=False).enqueue_outbox(
            "unsupported_test",
            {"value": suffix},
            idempotency_key=f"unsupported-test-{suffix}",
            dataset_id=f"ds_unsupported_{suffix}",
            next_retry_at=datetime.utcnow() - timedelta(seconds=1),
        )
        row.updated_at = datetime(1970, 1, 1)
        session.commit()

    response = client.post("/api/sync/push-outbox", params={"limit": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scanned"] == 1
    assert body["skipped"] == 1
    assert body["items"][0]["op_type"] == "unsupported_test"

    with SessionLocal() as session:
        row = Repository(session, enable_backup=False).get_outbox_by_idempotency_key(f"unsupported-test-{suffix}")
        if row:
            row.status = "done"
            session.commit()


def test_snapshot_json_migration_dry_run_and_idempotent_import(tmp_path: Path) -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_history_{suffix}"
    bundle = {
        "version": "v4",
        "items": [
            {
                "id": "half_hour:2026-04-23:10:00",
                "type": "half_hour",
                "tradingDate": "2026-04-23",
                "slotTime": "10:00",
                "timestamp": 1776919200000,
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-23",
                    "slotTime": "10:00",
                    "timestamp": 1776919200000,
                    "hotlist": [
                        {"code": "600001", "name": "样本A", "rank": 1, "price": 10},
                        {"code": "600002", "name": "样本B", "rank": 2, "price": 11},
                    ],
                    "sectors": [{"name": "样本行业", "rank": 1}],
                },
            },
            {
                "id": "half_hour:2026-04-23:10:30",
                "type": "half_hour",
                "tradingDate": "2026-04-23",
                "slotTime": "10:30",
                "timestamp": 1776921000000,
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-23",
                    "slotTime": "10:30",
                    "timestamp": 1776921000000,
                    "hotlist": [{"code": "600001", "name": "样本A", "rank": 1, "price": 10.2}],
                },
            },
        ],
    }
    path = tmp_path / "dragonboard-v4.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")

    dry_run = client.post(
        "/api/migrations/snapshots/import-json",
        json={"datasetId": dataset_id, "sourcePath": str(path), "dryRun": True},
    )
    assert dry_run.status_code == 200, dry_run.text
    dry_report = dry_run.json()["report"]
    assert dry_report == {
        "scanned": 2,
        "imported": 0,
        "skipped": 0,
        "errors": [],
        "dry_run": True,
        "record_count": 2,
        "frame_count": 2,
        "stock_row_count": 3,
        "sector_row_count": 1,
        "start_date": "2026-04-23",
        "end_date": "2026-04-23",
        "snapshot_types": ["half_hour"],
    }
    assert client.get(f"/api/datasets/{dataset_id}").status_code == 404

    first = client.post(
        "/api/migrations/snapshots/import-json",
        json={"datasetId": dataset_id, "sourcePath": str(path), "name": "history import"},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["ok"] is True
    assert first_body["deduped"] is False
    assert first_body["idempotencyKey"]
    assert first_body["report"] == {
        "scanned": 2,
        "imported": 2,
        "skipped": 0,
        "errors": [],
        "dry_run": False,
        "record_count": 2,
        "frame_count": 2,
        "stock_row_count": 3,
        "sector_row_count": 1,
        "start_date": "2026-04-23",
        "end_date": "2026-04-23",
        "snapshot_types": ["half_hour"],
    }
    assert first_body["dataset"]["id"] == dataset_id
    assert first_body["dataset"]["frame_count"] == 2
    assert first_body["dataset"]["stock_row_count"] == 3
    assert first_body["dataset"]["sector_row_count"] == 1

    second = client.post(
        "/api/migrations/snapshots/import-json",
        json={"datasetId": dataset_id, "sourcePath": str(path), "name": "history import"},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["ok"] is True
    assert second_body["deduped"] is True
    assert second_body["report"]["scanned"] == 2
    assert second_body["report"]["imported"] == 0
    assert second_body["report"]["skipped"] == 2
    assert second_body["report"]["stock_row_count"] == 3

    dataset = client.get(f"/api/datasets/{dataset_id}")
    assert dataset.status_code == 200
    assert dataset.json()["frame_count"] == 2
    assert dataset.json()["stock_row_count"] == 3
    assert dataset.json()["sector_row_count"] == 1


def test_snapshot_json_migration_retries_missing_rows_with_existing_outbox() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_history_retry_{suffix}"
    idempotency_key = f"migration-retry-key-{suffix}"
    first_bundle = {
        "version": "v4",
        "items": [
            {
                "id": "half_hour:2026-04-24:10:00",
                "type": "half_hour",
                "tradingDate": "2026-04-24",
                "slotTime": "10:00",
                "timestamp": 1777005600000,
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-24",
                    "slotTime": "10:00",
                    "timestamp": 1777005600000,
                    "hotlist": [{"code": "600001", "name": "样本A", "rank": 1}],
                },
            }
        ],
    }
    retry_bundle = {
        "version": "v4",
        "items": [
            *first_bundle["items"],
            {
                "id": "half_hour:2026-04-24:10:30",
                "type": "half_hour",
                "tradingDate": "2026-04-24",
                "slotTime": "10:30",
                "timestamp": 1777007400000,
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-24",
                    "slotTime": "10:30",
                    "timestamp": 1777007400000,
                    "hotlist": [{"code": "600002", "name": "样本B", "rank": 1}],
                },
            },
        ],
    }

    first = client.post(
        "/api/migrations/snapshots/import-json",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "content": first_bundle,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["report"]["imported"] == 1

    retry = client.post(
        "/api/migrations/snapshots/import-json",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "content": retry_bundle,
        },
    )
    assert retry.status_code == 200, retry.text
    retry_body = retry.json()
    assert retry_body["deduped"] is False
    assert retry_body["report"]["imported"] == 1
    assert retry_body["report"]["skipped"] == 1

    counts = client.get("/api/snapshots/counts", params={"dataset_id": dataset_id})
    assert counts.status_code == 200, counts.text
    assert counts.json()["counts"] == {
        "snapshots": 2,
        "snapshot_frames": 2,
        "snapshot_stock_rows": 2,
        "snapshot_sector_rows": 0,
    }


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
        {"initialCapital": 100000, "positionSize": 1, "maxPositions": 1},
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
        },
    )
    assert missing_next_bar_quote["eventCount"] == 0
    assert missing_next_bar_quote["matchingDiagnostics"]["nextBarEntries"] == 0
    assert missing_next_bar_quote["matchingDiagnostics"]["missingPriceRows"] >= 1


def test_cli_run_ranktrend_exposes_ui_backtest_parameters() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-ranktrend",
            "--dataset-id",
            "ds_cli",
            "--snapshot-type",
            "half_hour",
            "--start-date",
            "2026-04-15",
            "--end-date",
            "2026-04-30",
            "--strategy-name",
            "a_main_only",
            "--seed",
            "42",
            "--initial-cash",
            "123456",
            "--max-positions",
            "3",
            "--position-size",
            "0.15",
            "--target-holding-days",
            "4.5",
            "--max-holding-bars",
            "32",
            "--take-profit-pct",
            "0.09",
            "--stop-loss-pct",
            "0.04",
            "--fee-rate",
            "0.0002",
            "--stamp-tax-rate",
            "0.0006",
            "--slippage-rate",
            "0.0008",
            "--macd-fast",
            "12",
            "--macd-slow",
            "26",
            "--macd-signal",
            "9",
            "--momentum-periods",
            "2,4,8,16",
            "--horizons",
            "1,2,5",
            "--execution-mode",
            "next_bar",
            "--volume-participation-rate",
            "0.02",
            "--order-book-participation-rate",
            "0.25",
            "--intrabar-ambiguity",
            "take_first",
            "--use-theme-factor-for-execution",
            "--no-t1",
            "--no-partial-fills",
        ]
    )

    payload = build_ranktrend_payload(args)

    assert payload["dataset_id"] == "ds_cli"
    assert payload["snapshot_type"] == "half_hour"
    assert payload["start_date"] == "2026-04-15"
    assert payload["end_date"] == "2026-04-30"
    assert payload["strategy_name"] == "a_main_only"
    assert payload["random_seed"] == 42
    assert payload["initialCash"] == 123456
    assert payload["maxPositions"] == 3
    assert payload["targetHoldingDays"] == 4.5
    assert payload["maxHoldingBars"] == 32
    assert payload["takeProfitPct"] == 0.09
    assert payload["stopLossPct"] == 0.04
    assert payload["macdFast"] == 12
    assert payload["macdSlow"] == 26
    assert payload["macdSignal"] == 9
    assert payload["momentumPeriods"] == [2, 4, 8, 16]
    assert payload["horizons"] == [1, 2, 5]
    assert payload["enable_trade_simulation"] is True
    assert payload["tradeConfig"] == {
        "positionSize": 0.15,
        "feeRate": 0.0002,
        "stampTaxRate": 0.0006,
        "slippageRate": 0.0008,
        "enforceT1": False,
        "executionMode": "next_bar",
        "useOrderBookPrice": True,
        "enforceLimitStatus": True,
        "enforceVolumeLimit": True,
        "enforceOrderBookQueue": True,
        "allowPartialFills": False,
        "volumeParticipationRate": 0.02,
        "orderBookParticipationRate": 0.25,
        "useIntrabarStops": True,
        "intrabarAmbiguity": "take_first",
        "useThemeFactorForExecution": True,
    }


def test_cli_exposes_sync_and_migration_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = build_parser()
    build_dataset_args = parser.parse_args(["build-dataset", "--source-dataset-id", "dragonboard_live", "--dry-run"])
    assert build_dataset_args.func.__name__ == "cmd_build_dataset"
    assert build_dataset_args.source_dataset_id == "dragonboard_live"
    assert build_dataset_args.dry_run is True
    assert parser.parse_args(["push-backup"]).func.__name__ == "cmd_push_backup"
    push_backup_args = parser.parse_args(["push-backup", "--full-history"])
    assert push_backup_args.func.__name__ == "cmd_push_backup"
    assert push_backup_args.full_history is True
    assert parser.parse_args(["push-outbox", "--limit", "7"]).limit == 7
    assert parser.parse_args(["pull-backup"]).func.__name__ == "cmd_pull_backup"
    assert parser.parse_args(["smoke-backup"]).func.__name__ == "cmd_smoke_backup"
    prune_backup_args = parser.parse_args(["prune-backup", "--dry-run"])
    assert prune_backup_args.func.__name__ == "cmd_prune_backup"
    assert prune_backup_args.dry_run is True
    after_market_args = parser.parse_args(["after-market-once", "--archive-limit", "3", "--backup-limit", "2", "--dry-run"])
    assert after_market_args.func.__name__ == "cmd_after_market_once"
    assert after_market_args.archive_limit == 3
    assert after_market_args.backup_limit == 2
    assert after_market_args.dry_run is True
    compare_args = parser.parse_args(["compare-backtests", "--run-ids", "bt_1", "bt_2", "--metrics", "totalReturn,winRate"])
    assert compare_args.func.__name__ == "cmd_compare_backtests"
    assert compare_args.run_ids == ["bt_1", "bt_2"]
    assert compare_args.metrics == "totalReturn,winRate"
    export_args = parser.parse_args(["export-report", "--run-id", "bt_1", "--output", str(tmp_path / "bt_1.json")])
    assert export_args.func.__name__ == "cmd_export_report"
    assert export_args.run_id == "bt_1"

    bundle_path = tmp_path / "migration.json"
    bundle_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "half_hour:2026-04-25:10:00",
                        "type": "half_hour",
                        "tradingDate": "2026-04-25",
                        "slotTime": "10:00",
                        "timestamp": 1777092000000,
                        "payload": {
                            "type": "half_hour",
                            "tradingDate": "2026-04-25",
                            "slotTime": "10:00",
                            "timestamp": 1777092000000,
                            "hotlist": [{"code": "600001", "rank": 1}],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    captured: list[dict[str, object]] = []
    monkeypatch.setattr("backend.cli.print_json", lambda payload: captured.append(payload))
    args = parser.parse_args(
        [
            "migrate-snapshots",
            "--path",
            str(bundle_path),
            "--dataset-id",
            "cli_migration_dry_run",
            "--dry-run",
        ]
    )
    cmd_migrate_snapshots(args)
    assert captured
    assert captured[0]["ok"] is True
    assert captured[0]["report"]["dry_run"] is True
    assert captured[0]["report"]["scanned"] == 1

    theme_path = tmp_path / "themes.json"
    theme_payload = {
        "version": "cli-theme-test",
        "themes": [{"id": "AI", "name": "人工智能", "stocks": ["000001", "SZ000001"]}],
    }
    theme_path.write_text(json.dumps(theme_payload, ensure_ascii=False), encoding="utf-8")
    verify_theme_args = parser.parse_args(["verify-themes", "--path", str(theme_path)])
    assert verify_theme_args.func.__name__ == "cmd_verify_themes"

    captured.clear()
    cmd_verify_themes(verify_theme_args)
    assert captured
    assert set(captured[0]) >= {
        "ok",
        "expected",
        "actual",
        "mismatches",
        "missingThemes",
        "extraThemes",
        "missingMappings",
        "extraMappings",
        "source",
    }


class MemoryBackup:
    last_error = None

    def __init__(self) -> None:
        self.datasets: dict[str, Dataset] = {}
        self.frames: dict[str, list[dict[str, object]]] = {}
        self.fail_writes = False

    def mirror_dataset_bundle(self, dataset, records, frames, stock_rows, sector_rows):
        if self.fail_writes:
            self.last_error = "backup offline"
            return False
        self.datasets[dataset.id] = dataset
        self.frames[dataset.id] = [
            {
                "payload": {"frame": frame, "stocks": [row for row in stock_rows if row.get("snapshotId") == frame.get("snapshotId")]},
                "timestamp": frame.get("timestamp") or 0,
            }
            for frame in frames
        ]
        return True

    def list_rows(self, record_type, source=None, page_size=500):
        if record_type == "qb_dataset":
            return [{"payload": {"dataset": Repository.dataset_to_dict(dataset)}, "display_key": dataset.id} for dataset in self.datasets.values()]
        if record_type == "qb_snapshot_bundle":
            return list(self.frames.get(source, []))
        return []

    def get_row(self, record_type, display_key, source=None):
        if record_type == "qb_dataset" and display_key in self.datasets:
            dataset = self.datasets[display_key]
            return {"payload": {"dataset": Repository.dataset_to_dict(dataset)}, "display_key": dataset.id}
        return None

    def dataset_from_row(self, row):
        payload = row["payload"]["dataset"]
        return Dataset(
            id=payload["id"],
            name=payload["name"],
            source_type=payload["source_type"],
            source_path=payload["source_path"],
            db_name=payload["db_name"],
            schema_fingerprint=payload["schema_fingerprint"],
            snapshot_count=payload["snapshot_count"],
            frame_count=payload["frame_count"],
            stock_row_count=payload["stock_row_count"],
            sector_row_count=payload["sector_row_count"],
            start_date=payload["start_date"],
            end_date=payload["end_date"],
            snapshot_types_json=json_dumps(payload["snapshot_types"]),
            metadata_json=json_dumps(payload["metadata"]),
        )

    def frames_from_rows(self, rows, snapshot_type="half_hour", start_date=None, end_date=None, include_payload=True):
        frames = []
        for row in rows:
            frame = row["payload"]["frame"]
            if frame.get("type") != snapshot_type:
                continue
            item = {
                "snapshotId": frame["snapshotId"],
                "timestamp": frame["timestamp"],
                "tradingDate": frame["tradingDate"],
                "slotTime": frame["slotTime"],
                "type": frame["type"],
                "captureMode": frame.get("captureMode", "real_time"),
                "source": frame.get("source", "browser_runtime"),
                "marketContext": {},
                "stocks": row["payload"]["stocks"],
            }
            frames.append(item)
        return frames

def test_repository_falls_back_to_backup_when_primary_session_is_unavailable() -> None:
    backup = MemoryBackup()
    repo = Repository(None, backup)
    dataset = Dataset(
        id="ds_backup",
        name="backup",
        source_type="json_bundle",
        source_path="",
        frame_count=1,
        stock_row_count=1,
        snapshot_count=1,
        sector_row_count=0,
        start_date="2026-04-01",
        end_date="2026-04-01",
        snapshot_types_json='["half_hour"]',
        metadata_json="{}",
        created_at=datetime.utcnow(),
    )
    frame = {
        "snapshotId": "s1",
        "type": "half_hour",
        "tradingDate": "2026-04-01",
        "slotTime": "10:00",
        "timestamp": 1,
    }
    stock = {"snapshotId": "s1", "code": "600001", "rank": 1}

    repo.save_dataset_bundle(dataset, [], [frame], [stock], [])

    fallback_repo = Repository(None, backup)
    assert fallback_repo.get_dataset("ds_backup").name == "backup"
    frames = fallback_repo.load_frames("ds_backup", "half_hour")
    assert frames[0]["snapshotId"] == "s1"
    assert frames[0]["stocks"][0]["code"] == "600001"


def test_snapshot_ingest_writes_backup_only_when_primary_session_is_unavailable() -> None:
    backup = MemoryBackup()
    repo = Repository(None, backup)
    dataset = Dataset(
        id="ds_ingest_failover",
        name="ingest failover",
        source_type="dragon_board_runtime",
        source_path="",
        frame_count=1,
        stock_row_count=1,
        snapshot_count=1,
        sector_row_count=0,
        start_date="2026-04-01",
        end_date="2026-04-01",
        snapshot_types_json='["half_hour"]',
        metadata_json="{}",
        created_at=datetime.utcnow(),
    )
    record = {
        "id": "half_hour:2026-04-01:10:00",
        "type": "half_hour",
        "tradingDate": "2026-04-01",
        "slotTime": "10:00",
        "timestamp": 1,
    }
    frame = {"snapshotId": record["id"], **record}
    stock = {"snapshotId": record["id"], "code": "600001", "rank": 1}

    result = repo.save_snapshot_ingest(
        dataset,
        [record],
        [frame],
        [stock],
        [],
        idempotency_key="snapshot-ingest-failover-key",
        trading_date="2026-04-01",
    )

    assert result["status"] == "backup_only"
    assert result["outbox"] is None
    assert result["failover"]["active"] is True
    assert result["failover"]["reason"] == "primary_database_unavailable"
    assert backup.datasets[dataset.id].id == dataset.id
    assert backup.frames[dataset.id][0]["payload"]["frame"]["snapshotId"] == record["id"]


def test_snapshot_ingest_failover_reports_unavailable_when_backup_write_fails() -> None:
    backup = MemoryBackup()
    backup.fail_writes = True
    repo = Repository(None, backup)
    dataset = Dataset(
        id="ds_ingest_failover_failed",
        name="ingest failover failed",
        source_type="dragon_board_runtime",
        source_path="",
        frame_count=1,
        stock_row_count=0,
        snapshot_count=1,
        sector_row_count=0,
        start_date="2026-04-01",
        end_date="2026-04-01",
        snapshot_types_json='["half_hour"]',
        metadata_json="{}",
        created_at=datetime.utcnow(),
    )
    record = {"id": "half_hour:2026-04-01:10:00", "type": "half_hour", "tradingDate": "2026-04-01"}

    with pytest.raises(RuntimeError, match="primary_database_unavailable and Supabase backup write failed"):
        repo.save_snapshot_ingest(
            dataset,
            [record],
            [{"snapshotId": record["id"], **record}],
            [],
            [],
            idempotency_key="snapshot-ingest-failover-failed-key",
        )


def test_outbox_push_replays_snapshot_mirrors_and_keeps_research_local() -> None:
    backup = MemoryBackup()
    backup.fail_writes = True
    with SessionLocal() as session:
        suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        dataset = Dataset(
            id=f"ds_outbox_{suffix}",
            name="outbox",
            source_type="json_bundle",
            source_path="",
            frame_count=1,
            stock_row_count=1,
            snapshot_count=1,
            sector_row_count=0,
            start_date="2026-04-24",
            end_date="2026-04-24",
            snapshot_types_json='["half_hour"]',
            metadata_json="{}",
            created_at=datetime.utcnow(),
        )
        frame = {
            "snapshotId": f"half_hour:2026-04-24:{suffix}",
            "type": "half_hour",
            "tradingDate": "2026-04-24",
            "slotTime": "10:00",
            "timestamp": 1777005600000,
        }
        stock = {"snapshotId": frame["snapshotId"], "code": "600001", "rank": 1}
        repo = Repository(session, backup)
        repo.save_dataset_bundle(dataset, [], [frame], [stock], [])
        repo.save_backtest_run(
            BacktestRun(
                id=f"bt_{suffix}",
                dataset_id=dataset.id,
                strategy_name="rank_trend_candidate",
                snapshot_type="half_hour",
                config_hash="cfg",
                random_seed=20260430,
                request_json="{}",
                result_json="{}",
            )
        )
        repo.save_optimization_run(
            OptimizationRun(
                id=f"opt_{suffix}",
                dataset_id=dataset.id,
                strategy_name="rank_trend_candidate",
                method="grid",
                config_hash="cfg",
                random_seed=20260430,
                request_json="{}",
                result_json="{}",
            )
        )
        repo.save_golden_case(
            GoldenRankTrendCase(
                id=f"golden_{suffix}",
                name="golden",
                dataset_id=dataset.id,
                input_json="{}",
                expected_json="[]",
            )
        )

        queued = list(
            session.scalars(
                select(SyncOutboxModel).where(
                    SyncOutboxModel.dataset_id == dataset.id,
                )
            )
        )
        assert {row.op_type for row in queued} == {"dataset_bundle"}
        assert all(not hasattr(row, "payload_json") for row in queued)
        for row in queued:
            row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        session.commit()

        backup.fail_writes = False
        service = BackupSyncService(session, backup)
        result = service.push_outbox_to_backup(repo, limit=200)
        for _ in range(3):
            unfinished = list(
                session.scalars(
                    select(SyncOutboxModel).where(
                        SyncOutboxModel.dataset_id == dataset.id,
                        SyncOutboxModel.status.in_(["pending", "retry"]),
                    )
                )
            )
            if not unfinished:
                break
            for row in unfinished:
                row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
            session.commit()
            result = service.push_outbox_to_backup(repo, limit=200)

        assert result["scanned"] >= 0
        assert result["failed"] == 0
        assert dataset.id in backup.datasets
        finished = list(
            session.scalars(
                select(SyncOutboxModel).where(
                    SyncOutboxModel.dataset_id == dataset.id,
                )
            )
        )
        assert {row.status for row in finished} == {"done"}


def test_delete_backtest_run_removes_normalized_children() -> None:
    init_db()
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    run_id = f"bt_delete_{suffix}"
    with SessionLocal() as session:
        repo = Repository(session, enable_backup=False)
        repo.save_backtest_run(
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
        repo.save_backtest_trades(run_id, [{"code": "600001", "name": "A", "quantity": 100, "profit": 12.3}])
        repo.save_backtest_equity_curve(run_id, [{"snapshotId": "s1", "equity": 100000.0}])
        repo.save_backtest_signals(
            run_id,
            {"frameResults": [{"snapshotId": "s1", "tradingDate": "2026-04-30", "buyCandidates": [{"code": "600001", "signal": "buy"}]}]},
        )
        repo.save_backtest_quality_report(run_id, {"severity": "pass", "researchGrade": "research_ready", "snapshotCount": 1}, {})

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
    with ResearchSessionLocal() as session:
        assert session.get(BacktestRun, run_id) is None
        assert session.scalar(select(func.count()).select_from(BacktestTrade).where(BacktestTrade.backtest_run_id == run_id)) == 0
        assert session.scalar(select(func.count()).select_from(BacktestEquityCurve).where(BacktestEquityCurve.backtest_run_id == run_id)) == 0
        assert session.scalar(select(func.count()).select_from(BacktestSignal).where(BacktestSignal.backtest_run_id == run_id)) == 0
        assert (
            session.scalar(
                select(func.count()).select_from(BacktestQualityReport).where(BacktestQualityReport.backtest_run_id == run_id)
            )
            == 0
        )


def test_research_vacuum_runs_outside_session_transaction() -> None:
    init_db()
    with SessionLocal() as session:
        result = BacktestService(session).vacuum_research_sqlite()

    assert result == {"ok": True, "vacuum": True}


def test_theme_trend_backtest_api_returns_theme_strategy_report(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-v12", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/theme-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "strategyName": "theme_rotation", "randomSeed": 20260430},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runId"]
    assert body["strategyName"] == "theme_rotation"
    assert body["analysisMode"] == "theme_trend"
    assert body["result"]["themeTrend"]["factorVersion"] == "theme-factor-v12"
    assert body["dataQuality"]["researchGrade"] in {"research_ready", "degraded"}

    signals = client.get(f"/api/backtests/{body['runId']}/signals").json()
    assert signals["runId"] == body["runId"]


def test_theme_trend_backtest_persists_trade_and_equity_results(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-v12-trades", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "theme_rotation",
            "randomSeed": 20260430,
            "enableTradeSimulation": True,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["tradeSimulation"]["enabled"] is True

    trades = client.get(f"/api/backtests/{body['runId']}/trades").json()
    equity = client.get(f"/api/backtests/{body['runId']}/equity").json()
    assert trades["runId"] == body["runId"]
    assert equity["runId"] == body["runId"]
    assert equity["items"], "ThemeTrend 回测必须落库权益曲线，不能只保存研究信号"
    assert body["result"]["themeTrend"]["tradeSimulation"]["equityCount"] == len(equity["items"])


def test_theme_trend_backtest_generates_trade_events_for_theme_exposures(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_theme_trade_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-v12-trade-events", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "theme_rotation",
            "randomSeed": 20260430,
            "maxHoldingBars": 2,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    simulation = body["result"]["tradeSimulation"]
    assert simulation["eventCount"] > 0
    assert simulation["matchingDiagnostics"]["buyAttempts"] > 0

    trades = client.get(f"/api/backtests/{body['runId']}/trades").json()
    assert trades["total"] >= 1
    assert trades["items"][0]["code"] == "600001"


def test_theme_strategy_execution_signals_are_strategy_specific(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_theme_trade_bundle(tmp_path)
    add_theme_follower_to_bundle(bundle)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-v12-strategy-specific", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    leader_response = client.post(
        "/api/backtests/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "leader_theme_confirmation",
            "randomSeed": 20260430,
            "maxHoldingBars": 2,
        },
    )
    assert leader_response.status_code == 200, leader_response.text
    leader_result = leader_response.json()["result"]
    leader_signal = next(item for item in leader_result["executionSignals"] if item["code"] == "600001")
    non_leader_signal = next(item for item in leader_result["executionSignals"] if item["code"] == "600002")
    assert leader_signal["candidateTier"] == "A_MAIN"
    assert "leader_confirmation" in leader_signal["themeReasons"]
    assert non_leader_signal["candidateTier"] in {"N_NEUTRAL", "D_EXIT_RISK"}
    assert "leader_required" in non_leader_signal["themeRiskFlags"]

    hotlist_response = client.post(
        "/api/backtests/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "hotlist_theme_confluence",
            "randomSeed": 20260430,
            "maxHoldingBars": 2,
        },
    )
    assert hotlist_response.status_code == 200, hotlist_response.text
    hotlist_signals = hotlist_response.json()["result"]["executionSignals"]
    hotlist_leader = next(item for item in hotlist_signals if item["code"] == "600001")
    assert hotlist_leader["candidateTier"] == "A_MAIN"
    assert hotlist_leader["themeConfluenceScore"] >= 80
    assert "hotlist_confluence" in hotlist_leader["themeReasons"]


def test_theme_trend_report_includes_lifecycle_returns_and_trade_diagnostics(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_theme_trade_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-v12-report-diagnostics", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "theme_rotation",
            "randomSeed": 20260430,
            "maxHoldingBars": 2,
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["runId"]

    report = client.get(f"/api/reports/theme-trend/{run_id}")
    assert report.status_code == 200, report.text
    body = report.json()

    assert "lifecycleReturnDistribution" in body
    assert body["lifecycleReturnDistribution"]["mainline"]["tradeCount"] >= 1
    assert "themeTradeDiagnostics" in body
    assert body["themeTradeDiagnostics"][0]["themeName"] == "机器人"
    assert body["themeTradeDiagnostics"][0]["tradeCount"] >= 1
    assert body["candidateTierDiagnostics"][0]["candidateTier"] == "A_MAIN"
    assert body["roleDiagnostics"][0]["role"] == "leader"
    assert body["crowdingRiskDecay"]["triggeredTradeCount"] == 0


def test_theme_confluence_backtest_api_keeps_ranktrend_visible(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-confluence", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/theme-confluence",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "strategyName": "hotlist_theme_confluence"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategyName"] == "hotlist_theme_confluence"
    assert body["analysisMode"] == "theme_confluence"
    assert "rankTrendControl" in body["result"]["themeTrend"]


def test_theme_confluence_report_includes_control_attribution(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-confluence-report", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/theme-confluence",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "strategyName": "hotlist_theme_confluence"},
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["runId"]

    report = client.get(f"/api/reports/theme-trend/{run_id}")
    assert report.status_code == 200, report.text
    body = report.json()

    assert body["controlGroupAttribution"]["rankTrendOnly"]["signalCount"] >= 0
    assert body["controlGroupAttribution"]["themeOnly"]["signalCount"] >= 0
    assert body["controlGroupAttribution"]["themeRankTrendConfluence"]["signalCount"] >= 0
    assert body["controlGroupAttribution"]["leaderConfirmation"]["signalCount"] >= 0
    assert "conclusion" in body["controlGroupAttribution"]


def test_theme_confluence_optimization_api_returns_run(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-confluence-opt", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/optimizations/theme-confluence",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "hotlist_theme_confluence",
            "method": "random",
            "trials": 2,
            "parameterGrid": {"crowdingBlockThreshold": [70, 80]},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runId"]
    assert body["strategyName"] == "hotlist_theme_confluence"
    assert body["analysisMode"] == "theme_confluence"


def test_theme_confluence_optimization_uses_confluence_specific_search_metadata(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-confluence-opt-specific", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/optimizations/theme-confluence",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "hotlist_theme_confluence",
            "method": "grid",
            "trials": 3,
            "parameterGrid": {"rankTrendWeight": [0.55], "themeWeight": [0.45], "leaderMinContribution": [10]},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysisMode"] == "theme_confluence"
    assert body["searchProfile"] == "theme_confluence"

    detail = client.get(f"/api/optimizations/{body['runId']}")
    assert detail.status_code == 200, detail.text
    result = detail.json()["result"]
    assert result["searchProfile"] == "theme_confluence"
    assert result["supportedParameterGroups"] >= [
        "factor_weights",
        "risk_thresholds",
        "lifecycle_thresholds",
        "stock_exposure_thresholds",
        "trade_config",
        "confluence_weights",
    ]


def test_theme_trend_default_optimization_does_not_materialize_full_grid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-opt-lazy-grid", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    from backend.optimization import search_space as search_space_module

    def fail_product(*_args, **_kwargs):
        raise AssertionError("full grid product should not be materialized")

    monkeypatch.setattr(search_space_module.itertools, "product", fail_product)

    response = client.post(
        "/api/optimizations/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "theme_rotation",
            "method": "grid",
            "trials": 2,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trialCount"] == 2


def test_theme_optimization_report_includes_parameter_sensitivity(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-opt-report", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/optimizations/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "theme_rotation",
            "method": "grid",
            "trials": 4,
            "parameterGrid": {"crowdingBlockThreshold": [70, 80], "mainlineHeatThreshold": [72, 78]},
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["runId"]

    report = client.get(f"/api/reports/theme-trend/{run_id}")
    assert report.status_code == 200, report.text
    body = report.json()

    sensitivity = body["parameterSensitivity"]
    assert sensitivity["trialCount"] >= 1
    assert {item["parameter"] for item in sensitivity["parameters"]} >= {"crowdingBlockThreshold", "mainlineHeatThreshold"}
    assert sensitivity["topParameterSet"]


def test_theme_optimization_api_returns_running_theme_run(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-opt", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/optimizations/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "theme_rotation",
            "method": "random",
            "trials": 2,
            "parameterGrid": {"crowdingBlockThreshold": [70, 80]},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runId"]
    assert body["status"] in {"running", "completed"}
    assert body["strategyName"] == "theme_rotation"


def test_cli_exposes_theme_trend_commands() -> None:
    parser = build_parser()

    run_args = parser.parse_args(
        [
            "run-theme-trend",
            "--dataset-id",
            "ds_theme",
            "--snapshot-type",
            "half_hour",
            "--strategy-name",
            "leader_theme_confirmation",
            "--max-theme-exposure",
            "0.35",
        ]
    )
    assert run_args.dataset_id == "ds_theme"
    assert run_args.strategy_name == "leader_theme_confirmation"
    assert run_args.max_theme_exposure == 0.35

    opt_args = parser.parse_args(
        [
            "optimize-theme-confluence",
            "--dataset-id",
            "ds_theme",
            "--method",
            "tpe",
            "--trials",
            "3",
            "--no-wait",
        ]
    )
    assert opt_args.dataset_id == "ds_theme"
    assert opt_args.method == "tpe"
    assert opt_args.no_wait is True
