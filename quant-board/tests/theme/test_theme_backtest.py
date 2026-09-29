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

from tests.fixtures.helpers import (
    add_theme_follower_to_bundle,
    make_bundle,
    make_theme_sg_bundle,
    make_theme_trade_bundle,
    strip_dataset_id,
)


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


def test_theme_rotation_chase_uses_sg_flags(tmp_path: Path) -> None:
    """chase 变体：SG2 触发日给 B_IGNITION（补涨语义不给 A_MAIN），未触发日 N_NEUTRAL，outflow 保持 D_EXIT_RISK。"""
    client = TestClient(app)
    bundle = make_theme_sg_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-sg-chase", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/theme-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "strategyName": "theme_rotation_chase", "randomSeed": 20260430},
    )
    assert response.status_code == 200, response.text
    signals = response.json()["result"]["executionSignals"]
    tier_by_day = {}
    reasons_by_day = {}
    for s in signals:
        if s["slotTime"] == "15:00":
            tier_by_day[s["tradingDate"]] = s["candidateTier"]
            reasons_by_day[s["tradingDate"]] = s["themeReasons"]
    # d1 outflow：保持 D_EXIT_RISK（退出预警优先于 SG）
    assert tier_by_day["2026-04-01"] == "D_EXIT_RISK"
    # d2 inflow 且 SG2（outflow→inflow）触发：B_IGNITION + sg2 归因
    assert tier_by_day["2026-04-02"] == "B_IGNITION"
    assert "sg2" in reasons_by_day["2026-04-02"]
    # d3 inflow 但 SG 未触发（rotationState 无新切换，daily 缺数据 SG1/SG3 不可判）：N_NEUTRAL
    assert tier_by_day["2026-04-03"] == "N_NEUTRAL"


def test_theme_state_hybrid_gates_by_engine_mainlines(tmp_path: Path) -> None:
    """hybrid 变体：引擎 mainLines 非空日走主线确认规则，空/缺失日走 SG 驱动补涨并打标。"""
    client = TestClient(app)
    bundle = make_theme_sg_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-sg-hybrid", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/theme-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "strategyName": "theme_state_hybrid", "randomSeed": 20260430},
    )
    assert response.status_code == 200, response.text
    signals = response.json()["result"]["executionSignals"]
    by_day = {}
    for s in signals:
        if s["slotTime"] == "15:00":
            by_day[s["tradingDate"]] = s
    # d1 mainLines=[]（引擎判定无主线）→ 补涨臂；SG 未触发；rotationState=outflow
    # 退出预警优先于补涨（与 chase 同规则）→ D_EXIT_RISK
    assert by_day["2026-04-01"]["candidateTier"] == "D_EXIT_RISK"
    assert "missing_mainlines" not in by_day["2026-04-01"]["themeRiskFlags"]
    # d2 mainLines 键缺失 → 补涨臂；SG2 触发 → B_IGNITION。
    # （missing_mainlines 标记仅在 Mongo 生产链路可打出：SQLite H4 会给缺键帧兜底
    # 塞 mainLines=[]，两环境对"缺失"的呈现不同，语义结果一致——都走补涨臂。）
    assert by_day["2026-04-02"]["candidateTier"] == "B_IGNITION"
    assert "engine_mainline_day" not in by_day["2026-04-02"]["themeReasons"]
    # d3 引擎主线日且题材在名单 → 主线确认规则（inflow+exposure 88 → A_MAIN）
    assert by_day["2026-04-03"]["candidateTier"] == "A_MAIN"
    assert "engine_mainline_day" in by_day["2026-04-03"]["themeReasons"]


def test_theme_sg_variants_not_used_by_baseline_strategy(tmp_path: Path) -> None:
    """回归保护：theme_rotation 基线在 SG 接线后行为不变（同夹具下 d2/d3 仍 A_MAIN）。"""
    client = TestClient(app)
    bundle = make_theme_sg_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-sg-baseline", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/theme-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "strategyName": "theme_rotation", "randomSeed": 20260430},
    )
    assert response.status_code == 200, response.text
    signals = response.json()["result"]["executionSignals"]
    tier_by_day = {s["tradingDate"]: s["candidateTier"] for s in signals if s["slotTime"] == "15:00"}
    assert tier_by_day["2026-04-01"] == "D_EXIT_RISK"
    assert tier_by_day["2026-04-02"] == "A_MAIN"
    assert tier_by_day["2026-04-03"] == "A_MAIN"


def _sg_hybrid_frames() -> list[dict]:
    return [{
        "snapshotId": "snap_sg_hybrid_gate", "timestamp": 100,
        "tradingDate": "2026-09-03", "slotTime": "15:00",
        "stocks": [{"code": "600001", "name": "样本", "rank": 1, "price": 10.0, "change": 5.0}],
    }]


def _sg_hybrid_exposures() -> list[dict]:
    return [{
        "snapshotId": "snap_sg_hybrid_gate", "code": "600001", "themeName": "人工智能",
        "role": "core", "themeContribution": 10.0, "exposureWeight": 82.0,
    }]


def test_theme_hybrid_mainline_day_gates_non_listed_theme() -> None:
    """hybrid 主线日非名单题材 → N_NEUTRAL + not_in_engine_mainlines 标记（R3 复审补强：
    共享夹具单题材在名单内，覆盖不到该分支）；outflow 基线 D_EXIT_RISK 亦被覆盖为
    N_NEUTRAL（计划原文"不在名单 N_NEUTRAL"语义，档位退出让位于主线日门控）。"""
    factors = [{
        "snapshotId": "snap_sg_hybrid_gate", "themeName": "人工智能",
        "rotationState": "outflow", "crowdingRisk": 30,
    }]
    sg_inputs = {
        "sgFlags": {"人工智能": {"2026-09-03": {"sg1": None, "sg2": True, "sg3": None}}},
        "mainlineNamesByDay": {"2026-09-03": ["机器人主线"]},
        "qualityFlags": [],
    }
    signals = BacktestService._theme_execution_signals(
        _sg_hybrid_frames(), factors, _sg_hybrid_exposures(), "theme_state_hybrid", sg_inputs=sg_inputs,
    )
    assert signals[0]["candidateTier"] == "N_NEUTRAL"
    assert "not_in_engine_mainlines" in signals[0]["themeRiskFlags"]
    assert "engine_mainline_day" in signals[0]["themeReasons"]


def test_theme_hybrid_missing_mainlines_takes_sg_arm() -> None:
    """hybrid mainLines 缺失（None）→ missing_mainlines 标记 + 补涨臂：SG 触发 B_IGNITION
    （补涨不给 A_MAIN），未触发 N_NEUTRAL（inflow+高暴露的基线 A_MAIN 被覆盖）。"""
    factors = [{
        "snapshotId": "snap_sg_hybrid_gate", "themeName": "人工智能",
        "rotationState": "inflow", "crowdingRisk": 30,
    }]
    sg_inputs_hit = {
        "sgFlags": {"人工智能": {"2026-09-03": {"sg1": None, "sg2": True, "sg3": None}}},
        "mainlineNamesByDay": {"2026-09-03": None},
        "qualityFlags": [],
    }
    signals_hit = BacktestService._theme_execution_signals(
        _sg_hybrid_frames(), factors, _sg_hybrid_exposures(), "theme_state_hybrid", sg_inputs=sg_inputs_hit,
    )
    assert signals_hit[0]["candidateTier"] == "B_IGNITION"
    assert "missing_mainlines" in signals_hit[0]["themeRiskFlags"]
    assert "sg2" in signals_hit[0]["themeReasons"]

    sg_inputs_miss = {
        "sgFlags": {"人工智能": {"2026-09-03": {"sg1": None, "sg2": False, "sg3": None}}},
        "mainlineNamesByDay": {"2026-09-03": None},
        "qualityFlags": [],
    }
    signals_miss = BacktestService._theme_execution_signals(
        _sg_hybrid_frames(), factors, _sg_hybrid_exposures(), "theme_state_hybrid", sg_inputs=sg_inputs_miss,
    )
    assert signals_miss[0]["candidateTier"] == "N_NEUTRAL"
    assert "missing_mainlines" in signals_miss[0]["themeRiskFlags"]


def test_theme_chase_crowding_overrides_sg_trigger() -> None:
    """chase 拥挤优先：crowding≥75 时即使 SG 触发仍保持 C_CROWDED，SG 归因保留可追溯。"""
    factors = [{
        "snapshotId": "snap_sg_hybrid_gate", "themeName": "人工智能",
        "rotationState": "inflow", "crowdingRisk": 80,
    }]
    sg_inputs = {
        "sgFlags": {"人工智能": {"2026-09-03": {"sg1": None, "sg2": True, "sg3": None}}},
        "mainlineNamesByDay": {},
        "qualityFlags": [],
    }
    signals = BacktestService._theme_execution_signals(
        _sg_hybrid_frames(), factors, _sg_hybrid_exposures(), "theme_rotation_chase", sg_inputs=sg_inputs,
    )
    assert signals[0]["candidateTier"] == "C_CROWDED"
    assert "sg2" in signals[0]["themeReasons"]


def _sg1_frame(date: str, entities: list[dict]) -> dict:
    return {
        "snapshotId": f"half_hour:{date}:sg1", "timestamp": 100,
        "tradingDate": date, "slotTime": "15:00",
        "entities": entities,
    }


def _sg1_entity(name: str, change: float | None) -> dict:
    return {
        "entityType": "hot_theme", "entityName": name, "entityKey": name,
        "rotationState": "neutral", "change": change,
    }


def test_theme_sg_inputs_sg1_uses_close_slot_series() -> None:
    """R3b：SG1 change 序列改吃 15:00 收盘槽 entities（daily 7 月仅 15 天结构性饿死 SG1）。

    A=[-10,-2,+3] vs B=[0,0,0]（基准=全题材等权）→ d2 lagging、d3 lagging→improving 触发。
    """
    svc = BacktestService(None)
    days = ["2026-07-06", "2026-07-07", "2026-07-08"]
    changes = {"2026-07-06": -10.0, "2026-07-07": -2.0, "2026-07-08": 3.0}
    frames = [
        _sg1_frame(d, [_sg1_entity("A", changes[d]), _sg1_entity("B", 0.0)]) for d in days
    ]
    sg = svc._theme_sg_inputs("ds-sg1", frames)
    flags_a = sg["sgFlags"]["A"]
    assert flags_a["2026-07-06"]["sg1"] is None   # 首日象限不可知
    assert flags_a["2026-07-07"]["sg1"] is None   # 首个已知象限日（lagging），前日象限不可知
    assert flags_a["2026-07-08"]["sg1"] is True   # lagging→improving 迁移
    # B 相对基准 leading→weakening，无目标迁移 → False（可判定）
    flags_b = sg["sgFlags"]["B"]
    assert flags_b["2026-07-07"]["sg1"] is None and flags_b["2026-07-08"]["sg1"] is False
    assert not any(f.startswith("sg1_insufficient") for f in sg["qualityFlags"])


def test_theme_sg_inputs_sg1_missing_change_stays_none() -> None:
    """entities 无 change（现夹具形态）→ SG1 全 None + insufficient 计数，不伪造。"""
    svc = BacktestService(None)
    days = ["2026-07-06", "2026-07-07", "2026-07-08"]
    frames = [_sg1_frame(d, [_sg1_entity("A", None), _sg1_entity("B", None)]) for d in days]
    sg = svc._theme_sg_inputs("ds-sg1", frames)
    for name in ("A", "B"):
        assert all(v["sg1"] is None for v in sg["sgFlags"][name].values())
    assert "sg1_insufficient_count:2" in sg["qualityFlags"]


def test_theme_sg_inputs_sg1_attendance_gap_insufficient() -> None:
    """span 内缺勤（7-07 A 无行）→ A 整题材 insufficient；全出勤的 B 正常可判定。"""
    svc = BacktestService(None)
    frames = [
        _sg1_frame("2026-07-06", [_sg1_entity("A", -1.0), _sg1_entity("B", 0.0)]),
        _sg1_frame("2026-07-07", [_sg1_entity("B", 0.0)]),
        _sg1_frame("2026-07-08", [_sg1_entity("A", 1.0), _sg1_entity("B", 0.0)]),
    ]
    sg = svc._theme_sg_inputs("ds-sg1", frames)
    assert all(v["sg1"] is None for v in sg["sgFlags"]["A"].values())
    assert "sg1_insufficient_count:1" in sg["qualityFlags"]
    assert sg["sgFlags"]["B"]["2026-07-08"]["sg1"] is False


def test_theme_sg_inputs_sg1_void_gap_truncates_series() -> None:
    """4-15→7-06 空洞（>7 自然日）→ series 截断为 7-06 起重算，跨空洞动量不产生。"""
    svc = BacktestService(None)
    changes = {
        "2026-04-15": -10.0, "2026-04-27": 5.0,
        "2026-07-06": -10.0, "2026-07-07": -2.0, "2026-07-08": 3.0,
    }
    frames = [
        _sg1_frame(d, [_sg1_entity("A", changes[d]), _sg1_entity("B", 0.0)]) for d in sorted(changes)
    ]
    sg = svc._theme_sg_inputs("ds-sg1", frames)
    flags_a = sg["sgFlags"]["A"]
    # 空洞前段丢弃（不可判定），7-06 起与新 series 同基重算
    assert flags_a["2026-04-15"]["sg1"] is None and flags_a["2026-04-27"]["sg1"] is None
    assert flags_a["2026-07-07"]["sg1"] is None and flags_a["2026-07-08"]["sg1"] is True
    assert not any(f.startswith("sg1_insufficient") for f in sg["qualityFlags"])


def test_theme_sg_inputs_sg1_single_observation_insufficient() -> None:
    """单观测题材 → 不足以构成象限链 → insufficient 计数，SG1 全 None。"""
    svc = BacktestService(None)
    frames = [_sg1_frame("2026-07-06", [_sg1_entity("A", 1.0)])]
    sg = svc._theme_sg_inputs("ds-sg1", frames)
    assert sg["sgFlags"]["A"]["2026-07-06"]["sg1"] is None
    assert "sg1_insufficient_count:1" in sg["qualityFlags"]


def _run_theme_rotation_with_persistence(client: TestClient, tmp_path: Path, value: float) -> dict:
    """persistenceScore 取指定值时跑一轮 theme_rotation 回测（确定性种子）。"""
    bundle = make_theme_trade_bundle(tmp_path)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    for record in data["records"]:
        for sector in record["payload"]["sectors"]:
            sector["persistenceScore"] = value
    bundle.write_text(json.dumps({"records": data["records"]}, ensure_ascii=False), encoding="utf-8")
    imported = client.post(
        "/api/datasets/import",
        json={
            "sourceType": "json_bundle",
            "sourcePath": str(bundle),
            "name": f"theme-persistence-{value}",
            "snapshotTypes": ["half_hour"],
        },
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
    return response.json()


def test_theme_backtest_pnl_invariant_to_persistence_score(tmp_path: Path) -> None:
    """回测 PnL 不变合同（2026-09-27 persistenceScore 重建立项）：

    修复后 persistenceScore 从恒 0 变真值（sector rows 落库值/themeSupportScore/
    exposure ×0.03 变化），但候选分层、置信度与进出场不得变化——同一 bundle 仅
    persistenceScore 取 0 与 100 两个极端，回测执行信号与成交事件必须逐条一致。
    历史 Mongo 数据恒 0，既有回测结论本就**不含**持续性效应，无需回溯修订。
    """
    client = TestClient(app)
    zero = _run_theme_rotation_with_persistence(client, tmp_path, 0)
    full = _run_theme_rotation_with_persistence(client, tmp_path, 100)

    def signal_digest(body: dict) -> list[tuple]:
        return [
            (item["code"], item["candidateTier"], item["confidence"])
            for item in body["result"]["executionSignals"]
        ]

    assert signal_digest(zero) == signal_digest(full)
    assert zero["result"]["tradeSimulation"] == full["result"]["tradeSimulation"]
    assert zero["result"]["executionSignals"], "合同测试需要非空执行信号才有约束力"


def _run_theme_trend_with_payload(
    client: TestClient,
    tmp_path: Path,
    name: str,
    extra_payload: dict | None = None,
) -> dict:
    """theme-trend 回测助手：同一 bundle + 可选 payload 覆盖（persistenceScoreWeight 接线用）。"""
    bundle = make_theme_trade_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": name, "snapshotTypes": ["half_hour"]},
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
            **(extra_payload or {}),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _theme_signal_scores(body: dict) -> list[float]:
    return [item["score"] for item in body["result"]["themeTrend"]["signals"]]


def test_theme_trend_persistence_score_weight_payload_defaults_off(tmp_path: Path) -> None:
    """payload 缺省 / 显式 0.0 / 非法值 → 与历史逐位一致（默认关，一次一候选）。"""
    client = TestClient(app)
    default_body = _run_theme_trend_with_payload(client, tmp_path, "theme-psw-default")
    explicit_zero = _run_theme_trend_with_payload(client, tmp_path, "theme-psw-zero", {"persistenceScoreWeight": 0.0})
    invalid = _run_theme_trend_with_payload(client, tmp_path, "theme-psw-invalid", {"persistenceScoreWeight": -1.0})
    non_numeric = _run_theme_trend_with_payload(client, tmp_path, "theme-psw-nan", {"persistenceScoreWeight": "abc"})

    base_scores = _theme_signal_scores(default_body)
    assert base_scores, "合同测试需要非空题材信号才有约束力"
    assert _theme_signal_scores(explicit_zero) == base_scores
    assert _theme_signal_scores(invalid) == base_scores
    assert _theme_signal_scores(non_numeric) == base_scores


def test_theme_trend_persistence_score_weight_payload_flags_when_source_unavailable(tmp_path: Path) -> None:
    """API 级降级路径（测试环境非 Mongo）：weight>0 时分数不变，
    但逐信号打 persistence_daily_key_missing——fail-visible，不静默按 0。"""
    client = TestClient(app)
    base_body = _run_theme_trend_with_payload(client, tmp_path, "theme-psw-base")
    weighted_body = _run_theme_trend_with_payload(
        client, tmp_path, "theme-psw-on", {"persistenceScoreWeight": 0.5}
    )

    base_scores = _theme_signal_scores(base_body)
    weighted_scores = _theme_signal_scores(weighted_body)
    assert len(base_scores) == len(weighted_scores)
    assert base_scores == weighted_scores  # 非 Mongo 无原料 → 附加项 = 0
    assert all(
        "persistence_daily_key_missing" in (sig.get("qualityFlags") or [])
        for sig in weighted_body["result"]["themeTrend"]["signals"]
    )
    assert all("qualityFlags" not in sig for sig in base_body["result"]["themeTrend"]["signals"])
    # 分层与成交不受持续性权重影响（只改 score 归因通道）
    # mongodb 读链在信号行注入 datasetId（每轮回测不同），比较需剥离
    assert strip_dataset_id(base_body["result"]["executionSignals"]) == strip_dataset_id(
        weighted_body["result"]["executionSignals"]
    )
    assert base_body["result"]["tradeSimulation"] == weighted_body["result"]["tradeSimulation"]


def test_theme_trend_persistence_score_weight_injects_daily_factors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端正向接线证明：payload weight>0 → 服务读日级原料 → 引擎合成分变化。

    测试环境非 Mongo，仓储正路径无法直测（API 级降级另测），此处 monkeypatch
    load_daily_persistence_inputs 证明服务层确实把原料送进引擎。
    """
    client = TestClient(app)
    base_body = _run_theme_trend_with_payload(client, tmp_path, "theme-psw-inj-base")
    captured: dict = {}

    def fake_inputs(dataset_id: str, days: list[str]) -> tuple[dict, list[str]]:
        captured["days"] = days
        captured["dataset_id"] = dataset_id
        return {d: {"机器人": {"heatLevelStreak": 6}} for d in days}, []

    import backend.services.theme.daily_factors_service as daily_factors_service_module

    monkeypatch.setattr(daily_factors_service_module, "load_daily_persistence_inputs", fake_inputs)
    weighted_body = _run_theme_trend_with_payload(
        client, tmp_path, "theme-psw-inj-on", {"persistenceScoreWeight": 1.0}
    )

    assert captured.get("days"), "weight>0 必须读取日级原料"
    base_scores = _theme_signal_scores(base_body)
    weighted_scores = _theme_signal_scores(weighted_body)
    assert len(base_scores) == len(weighted_scores)
    assert any(w > b for b, w in zip(base_scores, weighted_scores))
    injected = [
        sig for sig in weighted_body["result"]["themeTrend"]["signals"]
        if sig["themeName"] == "机器人"
    ]
    assert injected, "夹具主题必须命中"
    assert all("qualityFlags" not in sig for sig in injected)  # 注入命中 → 无降级标记


def test_grid_requests_daily_factors_detection() -> None:
    """搜索空间探测：list choices / range spec / 缺失 / 全零四态。"""
    from backend.services.optimization_service import _grid_requests_daily_factors

    assert _grid_requests_daily_factors({"persistenceScoreWeight": [0, 0.5, 1]}) is True
    assert _grid_requests_daily_factors({"persistenceScoreWeight": {"type": "float", "low": 0.0, "high": 2.0}}) is True
    assert _grid_requests_daily_factors({"persistenceScoreWeight": [0, 0]}) is False
    assert _grid_requests_daily_factors({"persistenceScoreWeight": {"type": "float", "low": 0.0, "high": 0.0}}) is False
    assert _grid_requests_daily_factors({}) is False
    assert _grid_requests_daily_factors({"crowdingBlockThreshold": [70, 80]}) is False


def test_theme_optimization_injects_daily_factors_for_positive_weight_grid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """优化器正向接线（P4-3 前置）：grid 含 >0 权重 → 装载原料并透传引擎。

    monkeypatch 双点：装载帮手返回夹具 + 引擎 replay_sequence 侦听 daily_factors
    实参，证明「搜索空间探测 → 一次装载 → 逐 trial 透传」全链贯通。
    """
    client = TestClient(app)
    bundle = make_theme_trade_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-opt-inject", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    import backend.services.theme.daily_factors_service as daily_factors_service_module
    from backend.analysis.theme.trend import ThemeTrendPythonEngine

    monkeypatch.setattr(
        daily_factors_service_module,
        "load_daily_persistence_inputs",
        lambda dataset_id, days: ({d: {"机器人": {"heatLevelStreak": 6}} for d in days}, []),
    )
    seen: list = []
    real_replay = ThemeTrendPythonEngine.replay_sequence

    def spy(self, frames, config=None, meta=None, daily_factors=None):
        seen.append(daily_factors)
        return real_replay(self, frames, config=config, meta=meta, daily_factors=daily_factors)

    monkeypatch.setattr(ThemeTrendPythonEngine, "replay_sequence", spy)

    response = client.post(
        "/api/optimizations/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "theme_rotation",
            "method": "grid",
            "trials": 4,
            "parameterGrid": {"persistenceScoreWeight": [0, 1]},
        },
    )
    assert response.status_code == 200, response.text
    assert seen, "至少一次引擎回放"
    assert all(df is not None and df for df in seen), "grid 含 >0 权重 → 每个 trial 都必须拿到注入原料"


def test_theme_optimization_skips_daily_factor_loading_for_default_grid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负向控制：默认网格（无该参数）→ 不读原料、引擎收到 None（零 IO 默认路径）。"""
    client = TestClient(app)
    bundle = make_theme_trade_bundle(tmp_path)
    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-opt-noinject", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    import backend.services.theme.daily_factors_service as daily_factors_service_module
    from backend.analysis.theme.trend import ThemeTrendPythonEngine

    def forbidden(dataset_id: str, days: list[str]) -> tuple[dict, list[str]]:
        raise AssertionError("默认网格不得触发日级原料装载")

    monkeypatch.setattr(daily_factors_service_module, "load_daily_persistence_inputs", forbidden)
    seen: list = []
    real_replay = ThemeTrendPythonEngine.replay_sequence

    def spy(self, frames, config=None, meta=None, daily_factors=None):
        seen.append(daily_factors)
        return real_replay(self, frames, config=config, meta=meta, daily_factors=daily_factors)

    monkeypatch.setattr(ThemeTrendPythonEngine, "replay_sequence", spy)

    response = client.post(
        "/api/optimizations/theme-trend",
        json={
            "datasetId": dataset["id"],
            "snapshotType": "half_hour",
            "strategyName": "theme_rotation",
            "method": "grid",
            "trials": 2,
            "parameterGrid": {"crowdingBlockThreshold": [70, 80]},
        },
    )
    assert response.status_code == 200, response.text
    assert seen and all(df is None for df in seen), "默认路径必须零注入"


def _theme_tier_set(body: dict) -> set[str]:
    return {item["candidateTier"] for item in body["result"]["executionSignals"]}


def test_theme_trend_crowding_hard_layer_payload_moves_tier(tmp_path: Path) -> None:
    """payload 阈值 35（夹具 sector crowdingRisk=35）→ 硬层触发 C_CROWDED；
    默认 75 不触发。信号层与执行层共用同一 payload 键（单旋钮双消费点）。"""
    client = TestClient(app)
    default_body = _run_theme_trend_with_payload(client, tmp_path, "theme-hl-default")
    lowered_body = _run_theme_trend_with_payload(
        client, tmp_path, "theme-hl-35", {"crowdingHardLayerThreshold": 35.0}
    )

    default_tiers = _theme_tier_set(default_body)
    lowered_tiers = _theme_tier_set(lowered_body)
    assert "C_CROWDED" not in default_tiers, "默认 75 下夹具（crowding=35）不得触发硬层"
    assert "C_CROWDED" in lowered_tiers, "阈值 35 应使夹具题材进入 C_CROWDED"
    # 信号层同旋钮：降阈值后题材信号 label 变 risk
    lowered_theme_signals = lowered_body["result"]["themeTrend"]["signals"]
    assert any(sig["signal"] == "risk" for sig in lowered_theme_signals)


def test_theme_trend_crowding_hard_layer_payload_default_zero_drift(tmp_path: Path) -> None:
    """显式默认 75.0 与缺省逐位一致（零漂移合同）。"""
    client = TestClient(app)
    default_body = _run_theme_trend_with_payload(client, tmp_path, "theme-hl-base")
    explicit_body = _run_theme_trend_with_payload(
        client, tmp_path, "theme-hl-explicit", {"crowdingHardLayerThreshold": 75.0}
    )

    assert strip_dataset_id(default_body["result"]["executionSignals"]) == strip_dataset_id(
        explicit_body["result"]["executionSignals"]
    )
    assert default_body["result"]["themeTrend"]["signals"] == explicit_body["result"]["themeTrend"]["signals"]
    assert default_body["result"]["tradeSimulation"] == explicit_body["result"]["tradeSimulation"]


def test_confluence_execution_signals_crowding_hard_layer_threshold() -> None:
    """confluence 执行层第六消费点（code review M-6）：阈值 35 时 crowding=35 题材
    降 D_EXIT_RISK；默认 75 不触发。直接调静态方法（无 API 依赖）。"""
    factor = {"snapshotId": "s1", "themeName": "机器人", "crowdingRisk": 35, "lifecycle": "mainline", "rotationState": "mainline"}
    rank_signal = {"snapshotId": "s1", "code": "600001", "name": "题材龙头", "rank": 1, "candidateTier": "A_MAIN", "confidence": 80.0}
    exposure = {"snapshotId": "s1", "code": "600001", "themeName": "机器人", "role": "leader", "themeContribution": 20}
    frames = [{"snapshotId": "s1", "timestamp": 100, "tradingDate": "2026-04-01", "slotTime": "10:00", "stocks": [{"code": "600001"}]}]

    default_out = BacktestService._confluence_execution_signals([rank_signal], [factor], [exposure])
    lowered_out = BacktestService._confluence_execution_signals([rank_signal], [factor], [exposure], crowded_hard_layer_threshold=35.0)

    assert all(item["candidateTier"] != "D_EXIT_RISK" for item in default_out)
    assert all(item["candidateTier"] == "D_EXIT_RISK" for item in lowered_out)


def test_grid_requests_daily_factors_accepts_numeric_strings() -> None:
    """code review M-5：探测数值化口径与 from_patch 一致（"0.5" 可析即算）。"""
    from backend.services.optimization_service import _grid_requests_daily_factors

    assert _grid_requests_daily_factors({"persistenceScoreWeight": [0, "0.5"]}) is True
    assert _grid_requests_daily_factors({"persistenceScoreWeight": ["abc"]}) is False
