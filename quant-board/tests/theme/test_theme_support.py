from __future__ import annotations


from backend.analysis.theme.support_index import build_theme_candidate_support, build_theme_support_index
from backend.core.backtest.strategy import RankTrendCandidateStrategy, StrategyInput
from backend.data.models.models import BacktestSignal, SnapshotSectorRowModel, SnapshotStockRowModel


def _ranktrend_final(signal: str = "buy") -> dict:
    return {"decision": {"final": {"signal": signal}}}


def test_theme_support_scores_mainline_and_flags_crowding_risk() -> None:
    frame = {
        "snapshotId": "snap_1",
        "stocks": [
            {
                "code": "000001",
                "name": "样本股",
                "mainTheme": "人工智能",
                "themeHeat": 88,
                "themeContribution": 16,
                "themeRole": "leader",
                "themes": [{"name": "人工智能", "role": "leader", "themeContribution": 16}],
            }
        ],
        "sectors": [
            {
                "entityName": "人工智能",
                "rotationState": "mainline",
                "momentumScore": 82,
                "correlationScore": 74,
                "crowdingRisk": 18,
            }
        ],
    }

    support = build_theme_candidate_support(frame, frame["stocks"][0])

    assert support["mainTheme"] == "人工智能"
    assert support["themeRole"] == "leader"
    assert support["themeSupportScore"] >= 70
    assert "题材处于主线" in support["reasons"]
    assert support["riskFlags"] == []

    crowded = dict(frame)
    crowded["sectors"] = [{**frame["sectors"][0], "crowdingRisk": 82}]
    crowded_support = build_theme_candidate_support(crowded, crowded["stocks"][0])
    assert "题材拥挤风险高" in crowded_support["riskFlags"]


def test_theme_support_index_uses_json_fallback_when_columns_missing() -> None:
    frame = {
        "snapshotId": "snap_1",
        "stocks": [
            {
                "code": "000001",
                "themes": [{"name": "机器人", "role": "core", "themeContribution": 11}],
            }
        ],
        "sectors": [
            {
                "entityName": "机器人",
                "metadata": {"themeFactor": {"rotationState": "inflow", "momentumScore": 60}},
            }
        ],
    }

    index = build_theme_support_index(frame)

    assert index["000001"]["mainTheme"] == "机器人"
    assert index["000001"]["themeRole"] == "core"
    assert index["000001"]["themeSupportScore"] > 0


def test_theme_support_does_not_match_short_prefix_to_different_sector() -> None:
    frame = {
        "stocks": [{"code": "000001", "mainTheme": "电力", "themeHeat": 40}],
        "sectors": [
            {
                "entityName": "电力设备",
                "rotationState": "mainline",
                "momentumScore": 95,
                "correlationScore": 95,
            }
        ],
    }

    support = build_theme_candidate_support(frame, frame["stocks"][0])

    assert support["themeSupportScore"] < 30
    assert "题材处于主线" not in support["reasons"]


def test_theme_support_ignores_non_finite_numeric_values() -> None:
    frame = {
        "stocks": [{"code": "000001", "mainTheme": "人工智能", "themeHeat": "nan"}],
        "sectors": [
            {
                "entityName": "人工智能",
                "momentumScore": "inf",
                "correlationScore": "-inf",
                "crowdingRisk": "not-a-number",
            }
        ],
    }

    support = build_theme_candidate_support(frame, frame["stocks"][0])

    assert support["themeSupportScore"] == 0
    assert support["riskFlags"] == []


def test_strategy_adds_theme_explanation_without_execution_by_default() -> None:
    strategy = RankTrendCandidateStrategy()
    input = StrategyInput(
        frame={"snapshotId": "snap_1", "timestamp": 1, "tradingDate": "2026-05-05"},
        frame_signals=[
            {
                "code": "000001",
                "name": "样本股",
                "candidateTier": "A_MAIN",
                "confidence": 60,
                "rank": 1,
                "regime": "rising",
                "rankTrend": _ranktrend_final("buy"),
            }
        ],
        theme_support_by_code={
            "000001": {
                "mainTheme": "人工智能",
                "themeSupportScore": 92,
                "riskFlags": ["题材拥挤风险高"],
                "reasons": ["题材处于主线"],
            }
        },
        config={"useThemeFactorForExecution": False},
    )

    result = strategy.evaluate_frame(input)
    decision = result.buy_candidates[0]

    assert decision.signal == "buy"
    assert decision.confidence == 60
    assert "题材处于主线" in decision.reasons
    assert "题材拥挤风险高" in decision.risk_flags


def test_strategy_can_downgrade_crowded_theme_when_execution_enabled() -> None:
    strategy = RankTrendCandidateStrategy()
    input = StrategyInput(
        frame={"snapshotId": "snap_1", "timestamp": 1, "tradingDate": "2026-05-05"},
        frame_signals=[
            {
                "code": "000001",
                "name": "样本股",
                "candidateTier": "A_MAIN",
                "confidence": 60,
                "rank": 1,
                "regime": "rising",
                "rankTrend": _ranktrend_final("buy"),
            }
        ],
        theme_support_by_code={
            "000001": {
                "mainTheme": "人工智能",
                "themeSupportScore": 92,
                "riskFlags": ["题材拥挤风险高"],
                "reasons": ["题材处于主线"],
            }
        },
        config={"useThemeFactorForExecution": True},
    )

    result = strategy.evaluate_frame(input)

    assert result.buy_candidates == []
    assert result.watch_candidates[0].signal == "watch"
    assert result.watch_candidates[0].confidence == 60


def test_strategy_can_boost_confidence_when_theme_support_is_strong_and_clean() -> None:
    strategy = RankTrendCandidateStrategy()
    input = StrategyInput(
        frame={"snapshotId": "snap_1", "timestamp": 1, "tradingDate": "2026-05-05"},
        frame_signals=[
            {
                "code": "000001",
                "name": "样本股",
                "candidateTier": "A_MAIN",
                "confidence": 60,
                "rank": 1,
                "regime": "rising",
                "rankTrend": _ranktrend_final("buy"),
            }
        ],
        theme_support_by_code={
            "000001": {
                "mainTheme": "人工智能",
                "themeSupportScore": 92,
                "riskFlags": [],
                "reasons": ["题材处于主线"],
            }
        },
        config={"useThemeFactorForExecution": True},
    )

    result = strategy.evaluate_frame(input)

    assert result.buy_candidates[0].signal == "buy"
    assert result.buy_candidates[0].confidence > 60


def test_backtest_signal_model_accepts_theme_columns() -> None:
    signal = BacktestSignal(
        backtest_run_id="bt_1",
        code="000001",
        main_theme="人工智能",
        theme_heat=88,
        theme_contribution=16,
        theme_role="leader",
        theme_support_score=92,
        theme_risk_flags_json='["题材拥挤风险高"]',
        theme_reasons_json='["题材处于主线"]',
    )

    assert signal.theme_support_score == 92


def test_candidate_support_uses_rotation_score_and_lifecycle() -> None:
    from backend.analysis.theme.support_index import build_theme_candidate_support

    frame = {
        "sectors": [{
            "themeId": "BKAI", "themeName": "人工智能",
            "rotationState": "mainline", "lifecycle": "climax", "rotationScore": 80.0,
            "momentumScore": 70.0, "correlationScore": 60.0, "crowdingRisk": 75.0,
        }],
    }
    stock = {"mainTheme": "人工智能", "themeHeat": 70.0, "themeContribution": 60.0,
             "themeRole": "leader", "change": 9.8, "themeRiskFlags": []}
    support = build_theme_candidate_support(frame, stock)
    assert "题材轮动高潮风险" in support.get("riskFlags", [])
    assert support.get("themeSupportScore", 0) >= 70
