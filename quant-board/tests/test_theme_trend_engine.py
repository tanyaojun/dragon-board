from __future__ import annotations

import json
from pathlib import Path

from backend.analysis.theme_trend import (
    ThemeTrendConfig,
    ThemeTrendPythonEngine,
    build_theme_quality_report,
)


def _frame(snapshot_id: str, timestamp: int, stocks: list[dict], sectors: list[dict]) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": timestamp,
        "tradingDate": "2026-05-05",
        "stocks": stocks,
        "sectors": sectors,
    }


def test_theme_trend_python_matches_ts_runtime_golden_case() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "theme_trend_ts_golden_v12.json").read_text(encoding="utf-8")
    )

    result = ThemeTrendPythonEngine().replay(fixture["input"]["frames"], config=ThemeTrendConfig())

    factor_fields = [
        "themeId",
        "themeName",
        "heatScore",
        "momentumScore",
        "breadthScore",
        "fundScore",
        "leadershipScore",
        "correlationScore",
        "crowdingRisk",
        "persistenceScore",
        "rotationState",
        "rank",
        "qualityFlags",
    ]
    actual_factors = [{field: item.get(field) for field in factor_fields} for item in result["factors"]]
    assert actual_factors == fixture["expected"]["factors"]

    exposure_fields = [
        "code",
        "themeId",
        "themeName",
        "role",
        "roleScore",
        "exposureWeight",
        "themeContribution",
        "riskPenalty",
        "reasons",
    ]
    actual_exposures = [{field: item.get(field) for field in exposure_fields} for item in result["exposures"]]
    assert actual_exposures == fixture["expected"]["exposures"]


def test_replay_outputs_mainline_theme_factor_for_single_frame() -> None:
    frames = [
        _frame(
            "snap_1",
            100,
            [
                {
                    "code": "000001",
                    "name": "龙头科技",
                    "mainTheme": "人工智能",
                    "themeRole": "leader",
                    "themeContribution": 18,
                    "themeHeat": 92,
                    "rank": 1,
                },
                {
                    "code": "000002",
                    "name": "核心科技",
                    "mainTheme": "人工智能",
                    "themeRole": "core",
                    "themeContribution": 12,
                    "themeHeat": 76,
                    "rank": 5,
                },
            ],
            [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "rank": 1,
                    "heatScore": 90,
                    "momentumScore": 84,
                    "breadthScore": 78,
                    "fundScore": 82,
                    "leadershipScore": 88,
                    "correlationScore": 74,
                    "crowdingRisk": 32,
                    "persistenceScore": 80,
                    "rotationState": "mainline",
                }
            ],
        )
    ]

    result = ThemeTrendPythonEngine().replay(frames, config=ThemeTrendConfig())

    assert result["strategyVersion"] == "theme-trend-v12"
    assert result["factorVersion"] == "theme-factor-v12"
    assert result["signalVersion"] == "theme-signal-v12"
    assert result["qualityReport"]["blocked"] is False

    factor = result["factors"][0]
    assert factor["themeId"] == "ai"
    assert factor["themeName"] == "人工智能"
    assert factor["rotationState"] == "mainline"
    assert factor["lifecycle"] == "mainline"
    assert factor["rank"] == 1
    assert factor["qualityFlags"] == []
    assert factor["heatScore"] >= 85
    assert factor["momentumScore"] >= 80
    assert factor["breadthScore"] >= 70
    assert factor["fundScore"] >= 80
    assert factor["leadershipScore"] >= 80
    assert factor["correlationScore"] >= 70
    assert factor["crowdingRisk"] < 50
    assert factor["persistenceScore"] >= 75
    assert result["signals"][0]["themeId"] == "ai"
    assert result["signals"][0]["signal"] == "mainline"


def test_crowded_theme_sets_crowded_lifecycle_and_risk_signal() -> None:
    frames = [
        _frame(
            "snap_1",
            100,
            [{"code": "000001", "mainTheme": "机器人", "themeRole": "leader", "themeContribution": 20}],
            [
                {
                    "entityKey": "robot",
                    "entityName": "机器人",
                    "rank": 1,
                    "heatScore": 94,
                    "momentumScore": 86,
                    "breadthScore": 82,
                    "fundScore": 80,
                    "leadershipScore": 90,
                    "correlationScore": 78,
                    "crowdingRisk": 86,
                    "persistenceScore": 86,
                    "rotationState": "mainline",
                }
            ],
        )
    ]

    result = ThemeTrendPythonEngine().replay(frames)

    assert result["factors"][0]["lifecycle"] == "crowded"
    assert "crowding_risk_high" in result["factors"][0]["qualityFlags"]
    assert result["signals"][0]["signal"] == "risk"
    assert result["signals"][0]["risk"] == "crowded"


def test_quality_report_warns_when_frames_are_out_of_order() -> None:
    frames = [
        _frame("snap_2", 200, [{"code": "000001", "mainTheme": "AI"}], [{"entityName": "AI"}]),
        _frame("snap_1", 100, [{"code": "000001", "mainTheme": "AI"}], [{"entityName": "AI"}]),
    ]

    report = build_theme_quality_report(frames)

    assert report["blocked"] is False
    assert "time_order_invalid" in report["warnings"]


def test_empty_frames_are_blocked_and_replay_returns_empty_outputs() -> None:
    result = ThemeTrendPythonEngine().replay([])

    assert result["qualityReport"]["blocked"] is True
    assert "empty_frames" in result["qualityReport"]["errors"]
    assert result["factors"] == []
    assert result["exposures"] == []
    assert result["signals"] == []


def test_replay_builds_leader_and_core_stock_exposures() -> None:
    frames = [
        _frame(
            "snap_1",
            100,
            [
                {
                    "code": "000001",
                    "name": "龙头科技",
                    "mainTheme": "人工智能",
                    "themeRole": "leader",
                    "themeContribution": 18,
                    "themeHeat": 90,
                },
                {
                    "code": "000002",
                    "name": "核心科技",
                    "themes": [{"name": "人工智能", "role": "core", "themeContribution": 12}],
                    "themeHeat": 72,
                },
            ],
            [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "heatScore": 88,
                    "momentumScore": 80,
                    "breadthScore": 76,
                    "fundScore": 78,
                    "leadershipScore": 84,
                    "correlationScore": 72,
                    "crowdingRisk": 24,
                    "persistenceScore": 78,
                    "rotationState": "mainline",
                }
            ],
        )
    ]

    exposures = ThemeTrendPythonEngine().replay(frames)["exposures"]

    leader = next(item for item in exposures if item["code"] == "000001")
    core = next(item for item in exposures if item["code"] == "000002")
    assert leader["themeId"] == "ai"
    assert leader["themeName"] == "人工智能"
    assert leader["role"] == "leader"
    assert leader["roleScore"] > core["roleScore"]
    assert leader["exposureWeight"] > core["exposureWeight"]
    assert leader["themeContribution"] == 18
    assert leader["riskPenalty"] == 0
    assert "role:leader" in leader["reasons"]
    assert core["role"] == "core"
    assert "role:core" in core["reasons"]
