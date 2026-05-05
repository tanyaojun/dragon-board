from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from backend.analysis.theme_support import build_theme_candidate_support, build_theme_support_index
from backend.core.backtest.strategy import RankTrendCandidateStrategy, StrategyInput
from backend.data.database import _apply_column_migrations
from backend.data.models import BacktestSignal, SnapshotSectorRowModel, SnapshotStockRowModel
from backend.data.repository import Repository


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


def test_column_migrations_are_idempotent_for_existing_sqlite_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE sample (id TEXT PRIMARY KEY)"))

    migrations = [("sample", "theme_role", "VARCHAR(32)")]
    _apply_column_migrations(engine, migrations)
    _apply_column_migrations(engine, migrations)

    columns = {column["name"] for column in inspect(engine).get_columns("sample")}
    assert "theme_role" in columns


def test_repository_persists_theme_snapshot_columns() -> None:
    stock = SnapshotStockRowModel(
        dataset_id="ds_theme",
        row_id="snap_1:000001",
        snapshot_id="snap_1",
        type="half_hour",
        trading_date="2026-05-05",
        timestamp=1,
        code="000001",
        name="样本股",
        rank=1,
        theme_contribution=16,
        theme_role="leader",
        theme_exposure_weight=1,
        theme_risk_flags_json='["riskPenalty:2"]',
    )
    sector = SnapshotSectorRowModel(
        dataset_id="ds_theme",
        row_id="snap_1:hot_theme:AI",
        snapshot_id="snap_1",
        type="half_hour",
        trading_date="2026-05-05",
        timestamp=1,
        entity_type="hot_theme",
        entity_key="AI",
        entity_name="人工智能",
        rank=1,
        momentum_score=77,
        crowding_risk=21,
        rotation_state="mainline",
        theme_quality_flags_json='[{"code":"low_sample"}]',
    )

    assert Repository.local_stock_to_bundle_dict(stock)["themeContribution"] == 16
    sector_dict = Repository.local_sector_to_bundle_dict(sector)
    assert sector_dict["momentumScore"] == 77
    assert sector_dict["rotationState"] == "mainline"
    assert sector_dict["themeQualityFlags"] == [{"code": "low_sample"}]


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
