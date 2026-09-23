"""Theme trend / confluence backtest, optimization, report, and theme-trend CLI tests.

Extracted from tests/test_quant_board.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.cli import build_parser
from backend.core.backtest import DEFAULT_TRADE_CONFIG
from backend.main import app
from backend.services import BacktestService

from tests.fixtures.helpers import add_theme_follower_to_bundle, make_bundle, make_theme_trade_bundle


def test_theme_trade_config_uses_v5_lifecycle_fusion_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(DEFAULT_TRADE_CONFIG, "minJumpConfidence", 91.5)

    config = BacktestService._theme_trade_config({}, "ranktrend_early_big_move_v3_lifecycle_fusion")

    assert config["minJumpConfidence"] == 90.0
    assert config["maxHoldingBars"] == 30
    assert config["stopLoss"] == -0.05
    # 2026-09-23 落默认（docs/ranktrend-tier-backtest/exit-scan-batch3-verdict.md）
    assert config["takeProfit"] == 0.06
    assert config["breakevenTrailing"] is True
    assert config["breakevenThreshold"] == 0.02
    assert config["volumeParticipationRate"] == 0.1


def test_theme_trade_config_keeps_non_v5_platform_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(DEFAULT_TRADE_CONFIG, "minJumpConfidence", 91.5)

    config = BacktestService._theme_trade_config({}, "rank_trend_candidate")

    assert config["minJumpConfidence"] == 91.5
    assert config["maxHoldingBars"] == 40
    assert config["stopLoss"] == -0.06
    assert config["takeProfit"] == 0.12
    assert config["volumeParticipationRate"] == 0.05


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


def test_theme_confluence_score_ignores_absolute_heat_score(tmp_path: Path) -> None:
    """新口径绝对值 heatScore（>100 落库值，2026-09 theme-market-v2）不伪装成 0-100 满分 confluence。"""
    client = TestClient(app)
    bundle = make_theme_trade_bundle(tmp_path)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    for record in data["records"]:
        record["payload"]["sectors"][0]["heatScore"] = 2000
    bundle.write_text(json.dumps({"records": data["records"]}, ensure_ascii=False), encoding="utf-8")
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-absolute-heat", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "hotlist_theme_confluence",
            "randomSeed": 20260430,
            "maxHoldingBars": 2,
        },
    )
    assert response.status_code == 200, response.text
    signal = next(
        item for item in response.json()["result"]["executionSignals"] if item["code"] == "600001"
    )
    # 绝对值热度按缺失（0）计入：confluence = exposure_weight 95*0.35 + contribution 20*0.8 = 49.25，
    # 不再恒过 75 门槛（exposure_weight 为 replay 重建值 45+50=95，非 stock 携带的 88）
    assert signal["themeConfluenceScore"] == 49.25
    assert "hotlist_confluence" not in signal["themeReasons"]


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


# ── heatLevel 落库迁移（design §4.2/B10）：执行信号热度分量与透传按相对分口径消费 ──

from backend.services.backtest_service import BacktestService, _persisted_heat_level


def test_persisted_heat_level_consumes_heat_level_and_caliber() -> None:
    """执行信号热度分量按 design §4.2 消费：heatLevel 优先，v2 绝对值不回退。"""
    assert _persisted_heat_level({"heatLevel": 96.3, "heatScore": 2000}) == 96.3
    assert _persisted_heat_level({"heatLevel": None, "heatScore": 2000}) == 0.0
    assert _persisted_heat_level({"heatScore": 85}) == 85.0
    assert _persisted_heat_level({"heatScore": 85, "metadata": {"factorVersion": "theme-market-v1"}}) == 85.0
    assert _persisted_heat_level({"heatScore": 85, "heatFactorVersion": "theme-market-v2"}) == 0.0
    assert _persisted_heat_level({"heatScore": 2000}) == 0.0
    assert _persisted_heat_level({}) == 0.0
    assert _persisted_heat_level(None) == 0.0


def test_execution_signal_theme_heat_relative_caliber() -> None:
    """B10（评审 M4）：执行信号 themeHeat 透传字段改吃 heatLevel 相对分，不再透传绝对值。"""
    frames = [{
        "snapshotId": "snap_b10", "timestamp": 100,
        "tradingDate": "2026-09-03", "slotTime": "10:00",
        "stocks": [{"code": "600001", "name": "样本", "rank": 1, "price": 10.0, "change": 5.0}],
    }]
    factors = [{
        "snapshotId": "snap_b10", "themeName": "人工智能",
        "heatScore": 2000.0, "heatLevel": 96.3,
        "rotationState": "mainline", "crowdingRisk": 30,
    }]
    exposures = [{
        "snapshotId": "snap_b10", "code": "600001", "themeName": "人工智能",
        "role": "core", "themeContribution": 10.0, "exposureWeight": 82.0,
    }]
    signals = BacktestService._theme_execution_signals(frames, factors, exposures, "theme_rotation")
    assert signals[0]["themeHeat"] == 96.3

    # heatLevel 缺失 → 回退 stock.themeHeat（本例无）→ 0.0，不落绝对值
    factors_missing = [{**factors[0], "heatLevel": None}]
    signals_missing = BacktestService._theme_execution_signals(
        frames, factors_missing, exposures, "theme_rotation",
    )
    assert signals_missing[0]["themeHeat"] == 0.0
