"""ThemeTrend v12 升级 Task2：条件层门控机制接线测试（默认关）。

覆盖（设计 §5.3 双维门控语义：只调节权重与可信度标签，不做硬门禁）：
  - 情绪门控：gated 相位（cooling/ice）下 A_MAIN/B_IGNITION 降 confidence +
    打标，tier 不变；非 gated 相位/缺失相位/非进场层不动；
  - 拥挤度分位门控：BC ≥ 阈值降 confidence + 打标；
  - 默认关：gating_inputs=None（缺省）输出与不传完全一致（既有三策略零变化）；
  - _theme_gating_inputs：half_hour 15:00 帧 marketPhase 提取 + 缺帧打标 +
    非 Mongo 后端显式降级打标。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.backtest_service import BacktestService
from tests.fixtures.helpers import make_theme_sg_bundle

FRAMES = [{
    "snapshotId": "snap_gate", "timestamp": 100,
    "tradingDate": "2026-09-03", "slotTime": "10:00",
    "stocks": [{"code": "600001", "name": "样本", "rank": 1, "price": 10.0, "change": 5.0}],
}]
FACTORS = [{
    "snapshotId": "snap_gate", "themeName": "机器人",
    "heatLevel": 80.0, "rotationState": "mainline", "crowdingRisk": 30,
}]
EXPOSURES = [{
    "snapshotId": "snap_gate", "code": "600001", "themeName": "机器人",
    "role": "leader", "themeContribution": 10.0, "exposureWeight": 88.0,
}]


def make_gating(**overrides: object) -> dict[str, object]:
    gating: dict[str, object] = {
        "marketPhaseByDay": {"2026-09-03": "cooling"},
        "sentimentPhases": ("cooling", "ice"),
        "sentimentConfidencePenalty": 10.0,
        "crowdingPercentileByDay": {},
        "crowdingPercentileHighThreshold": 90.0,
        "crowdingPercentileConfidencePenalty": 10.0,
        "qualityFlags": [],
    }
    gating.update(overrides)
    return gating


def run_signals(gating_inputs: dict[str, object] | None, *, factors: list[dict] | None = None) -> dict:
    signals = BacktestService._theme_execution_signals(
        FRAMES, factors or FACTORS, EXPOSURES, "theme_rotation", gating_inputs=gating_inputs,
    )
    assert len(signals) == 1
    return signals[0]


class TestSentimentGating:
    def test_cooling_downgrades_confidence_keeps_tier(self) -> None:
        base = run_signals(None)
        gated = run_signals(make_gating())
        # 不做硬门禁：tier 保持 A_MAIN，只降可信 + 打标
        assert base["candidateTier"] == "A_MAIN"
        assert gated["candidateTier"] == "A_MAIN"
        assert base["confidence"] == pytest.approx(gated["confidence"] + 10.0)
        assert "sentiment_gate:cooling" in gated["themeReasons"]
        assert "sentiment_phase:cooling" in gated["themeRiskFlags"]
        assert "sentiment_gate:cooling" not in base["themeReasons"]

    def test_non_gated_phase_and_missing_phase_noop(self) -> None:
        base = run_signals(None)
        climax = run_signals(make_gating(marketPhaseByDay={"2026-09-03": "climax"}))
        missing = run_signals(make_gating(marketPhaseByDay={}))
        assert climax["confidence"] == base["confidence"]
        assert missing["confidence"] == base["confidence"]

    def test_exit_risk_tier_not_adjusted(self) -> None:
        outflow_factors = [{**FACTORS[0], "rotationState": "outflow"}]
        base = run_signals(None, factors=outflow_factors)
        gated = run_signals(make_gating(), factors=outflow_factors)
        assert base["candidateTier"] == "D_EXIT_RISK"
        # 降可信只作用于进场层 A_MAIN/B_IGNITION，退出/拥挤层不动
        assert gated["candidateTier"] == "D_EXIT_RISK"
        assert gated["confidence"] == base["confidence"]
        assert "sentiment_phase:cooling" not in gated["themeRiskFlags"]

    def test_ignition_tier_adjusted(self) -> None:
        # 低暴露（<55）且低贡献（<8）的 inflow 才落 B_IGNITION（A_MAIN 分支优先）
        inflow_exposures = [{**EXPOSURES[0], "exposureWeight": 40.0, "themeContribution": 4.0}]
        inflow_factors = [{**FACTORS[0], "rotationState": "inflow"}]
        signals = BacktestService._theme_execution_signals(
            FRAMES, inflow_factors, inflow_exposures, "theme_rotation"
        )
        assert signals[0]["candidateTier"] == "B_IGNITION"
        gated = BacktestService._theme_execution_signals(
            FRAMES, inflow_factors, inflow_exposures, "theme_rotation", gating_inputs=make_gating()
        )[0]
        assert gated["candidateTier"] == "B_IGNITION"
        assert signals[0]["confidence"] == pytest.approx(gated["confidence"] + 10.0)
        assert "sentiment_gate:cooling" in gated["themeReasons"]


class TestCrowdingPercentileGating:
    def test_high_percentile_downgrades(self) -> None:
        base = run_signals(None)
        gated = run_signals(make_gating(
            marketPhaseByDay={},
            crowdingPercentileByDay={"机器人": {"2026-09-03": 95.0}},
        ))
        assert base["confidence"] == pytest.approx(gated["confidence"] + 10.0)
        assert "crowding_percentile_high:95.0" in gated["themeReasons"]
        assert "crowding_percentile_high" in gated["themeRiskFlags"]

    def test_below_threshold_noop(self) -> None:
        base = run_signals(None)
        gated = run_signals(make_gating(
            marketPhaseByDay={},
            crowdingPercentileByDay={"机器人": {"2026-09-03": 85.0}},
        ))
        assert gated["confidence"] == base["confidence"]

    def test_missing_percentile_noop(self) -> None:
        base = run_signals(None)
        gated = run_signals(make_gating(
            marketPhaseByDay={},
            crowdingPercentileByDay={"机器人": {"2026-09-03": None}, "其他": {"2026-09-03": 99.0}},
        ))
        assert gated["confidence"] == base["confidence"]

    def test_both_gates_cumulative(self) -> None:
        base = run_signals(None)
        gated = run_signals(make_gating(
            crowdingPercentileByDay={"机器人": {"2026-09-03": 95.0}},
        ))
        assert base["confidence"] == pytest.approx(gated["confidence"] + 20.0)


class TestGatingInputsBuilder:
    def test_market_phase_extracted_from_15h_frames(self) -> None:
        frames = [
            {"tradingDate": "2026-09-03", "slotTime": "15:00", "rotationSummary": {"marketPhase": "cooling"}},
            {"tradingDate": "2026-09-04", "slotTime": "10:30", "rotationSummary": {"marketPhase": "climax"}},
        ]
        ctx = BacktestService._theme_gating_inputs(frames, "dsx", include_crowding_percentile=False)
        assert ctx["marketPhaseByDay"]["2026-09-03"] == "cooling"
        # 非 15:00 帧不取数：09-04 无 15:00 帧 → None + missing 标记
        assert ctx["marketPhaseByDay"]["2026-09-04"] is None
        assert "missing_15h_frame:2026-09-04" in ctx["qualityFlags"]

    def test_crowding_percentile_disabled_by_storage_backend(self) -> None:
        # 测试环境 storage_backend=sqlite（conftest）：非 Mongo 后端显式降级并打标
        frames = [{"tradingDate": "2026-09-03", "slotTime": "15:00", "rotationSummary": {"marketPhase": "cooling"}}]
        ctx = BacktestService._theme_gating_inputs(frames, "dsx", include_crowding_percentile=True)
        assert ctx["crowdingPercentileByDay"] == {}
        assert any(
            flag.startswith("crowding_percentile_source_unavailable:")
            for flag in ctx["qualityFlags"]
        )


def make_cooling_bundle(path: Path) -> Path:
    """复用 SG 夹具并把全部 15:00 帧 marketPhase 改为 cooling（情绪门控 API 测试）。"""
    bundle = make_theme_sg_bundle(path)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    for record in data["records"]:
        payload = record.get("payload") or {}
        if record.get("slotTime") == "15:00" or payload.get("slotTime") == "15:00":
            rotation_summary = payload.setdefault("rotationSummary", {})
            rotation_summary["marketPhase"] = "cooling"
    cooled = path / "theme_cooling_bundle.json"
    cooled.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return cooled


class TestGatingApiWiring:
    def test_sentiment_gating_flag_changes_confidence_only(self, tmp_path: Path) -> None:
        client = TestClient(app)
        bundle = make_cooling_bundle(tmp_path)
        imported = client.post(
            "/api/datasets/import",
            json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-gating", "snapshotTypes": ["half_hour"]},
        )
        assert imported.status_code == 200, imported.text
        dataset = imported.json()

        base = client.post(
            "/api/backtests/theme-trend",
            json={"datasetId": dataset["id"], "snapshotType": "half_hour", "strategyName": "theme_rotation", "randomSeed": 20260430},
        )
        gated = client.post(
            "/api/backtests/theme-trend",
            json={
                "datasetId": dataset["id"], "snapshotType": "half_hour",
                "strategyName": "theme_rotation", "randomSeed": 20260430,
                "sentimentGatingEnabled": True,
            },
        )
        assert base.status_code == 200, base.text
        assert gated.status_code == 200, gated.text
        base_by_day = {
            s["tradingDate"]: s
            for s in base.json()["result"]["executionSignals"]
            if s["slotTime"] == "15:00" and s["code"] == "600001"
        }
        gated_by_day = {
            s["tradingDate"]: s
            for s in gated.json()["result"]["executionSignals"]
            if s["slotTime"] == "15:00" and s["code"] == "600001"
        }
        # 默认关：base 无门控标记
        for day, signal in base_by_day.items():
            assert not any(flag.startswith("sentiment_") for flag in signal["themeRiskFlags"])
        # d1 outflow → D_EXIT_RISK（退出层不动）；d2/d3 inflow+高暴露 → A_MAIN（进场层降 10）
        assert base_by_day["2026-04-01"]["candidateTier"] == "D_EXIT_RISK"
        assert gated_by_day["2026-04-01"]["confidence"] == base_by_day["2026-04-01"]["confidence"]
        for day in ("2026-04-02", "2026-04-03"):
            assert base_by_day[day]["candidateTier"] == "A_MAIN"
            assert gated_by_day[day]["candidateTier"] == "A_MAIN"
            assert base_by_day[day]["confidence"] == pytest.approx(gated_by_day[day]["confidence"] + 10.0)
            assert "sentiment_gate:cooling" in gated_by_day[day]["themeReasons"]

    def test_default_run_ignores_gating_params(self, tmp_path: Path) -> None:
        """默认关合同：不传开关时传入门控参数也不生效（一次一候选纪律）。"""
        client = TestClient(app)
        bundle = make_cooling_bundle(tmp_path)
        imported = client.post(
            "/api/datasets/import",
            json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "theme-gating-default", "snapshotTypes": ["half_hour"]},
        )
        assert imported.status_code == 200, imported.text
        dataset = imported.json()
        response = client.post(
            "/api/backtests/theme-trend",
            json={
                "datasetId": dataset["id"], "snapshotType": "half_hour",
                "strategyName": "theme_rotation", "randomSeed": 20260430,
                "sentimentGatingConfidencePenalty": 50.0,
                "crowdingPercentileHighThreshold": 0.0,
            },
        )
        assert response.status_code == 200, response.text
        signals = [
            s for s in response.json()["result"]["executionSignals"]
            if s["slotTime"] == "15:00" and s["code"] == "600001"
        ]
        assert signals
        for signal in signals:
            assert not any(flag.startswith("sentiment_") for flag in signal["themeRiskFlags"])
            assert not any(flag.startswith("crowding_percentile") for flag in signal["themeRiskFlags"])
