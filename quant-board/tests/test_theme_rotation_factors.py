import math

from backend.analysis.theme_rotation.factors import (
    breadth_score,
    crowding_score,
    flow_score,
    lifecycle_score,
    linear_slope,
    robust_z,
    strength_score,
)


def _row(**overrides):
    base = {"themeId": "BKAI", "themeName": "人工智能", "heatScore": 70.0, "ztCount": 5,
            "change": 3.0, "mainNetInflow": 2.0, "breadthScore": 60.0,
            "crowdingRisk": 50.0, "rank": 1}
    base.update(overrides)
    return base


def test_linear_slope_ascending():
    assert abs(linear_slope([10.0, 20.0, 30.0]) - 10.0) < 1e-9


def test_robust_z_median_mad():
    assert abs(robust_z(60.0, [50.0, 60.0]) - 1.0) < 1e-9


def test_strength_score_high_heat():
    score, missing = strength_score(
        _row(heatScore=80.0, ztCount=6, change=5.0),
        history_heats=[60.0, 70.0],
        all_current_heats=[40.0, 80.0],
        market_change=1.0,
        prev_zt_count=3,
    )
    assert score is not None and 60 <= score <= 100
    assert "heatScore" not in missing


def test_strength_score_missing_heat_returns_none():
    score, missing = strength_score(_row(heatScore=None), [], [], 1.0, None)
    assert score is None
    assert "heatScore" in missing


def test_flow_score_missing_inflow_returns_none():
    score, missing = flow_score(_row(mainNetInflow=None), [2.0], [2.0, 3.0], 1)
    assert score is None
    assert "mainNetInflow" in missing


def test_breadth_score_promotion_degraded_when_no_history():
    score, missing = breadth_score(_row(breadthScore=70.0), None, [], None)
    assert score is not None
    assert "boardHeight" in missing
    assert "promotion" in missing


def test_breadth_score_promotion_uses_theme_scoped_denominator():
    current = [_row(breadthScore=70.0, boardHeight=2)]
    prev_theme = [
        {"code": "600001", "leadStatus": "涨停", "change": 9.6},
        {"code": "600002", "leadStatus": "", "change": 3.0},
    ]
    score, missing = breadth_score(current[0], None, current, prev_theme)
    # 主题内昨日涨停 1 只、今日连板 1 只 → 晋级率子分命中 100 上限并参与加权
    assert score is not None
    assert "promotion" not in missing
    # 与无晋级数据（降级路径）对照：晋级子分参与加权，复合分明显更高
    degraded, degraded_missing = breadth_score(current[0], None, current, None)
    assert score > degraded
    assert "promotion" in degraded_missing


def test_crowding_score_missing_risk_returns_none():
    score, missing = crowding_score(_row(crowdingRisk=None), [50.0], [])
    assert score is None
    assert "crowdingRisk" in missing


def test_lifecycle_score_without_prev_is_neutral_with_flag():
    score, missing = lifecycle_score(None, [])
    assert score == 50.0
    assert "prevLifecycle" in missing
    assert "rankHistory" in missing


def test_combine_scores_min_factors_gate():
    from backend.analysis.theme_rotation.factors import combine_scores
    from backend.analysis.theme_rotation.models import ThemeFactorScores

    scores = ThemeFactorScores(theme_id="BKAI", theme_name="人工智能", strength=80.0, flow=None)
    assert combine_scores(scores, {"strength": 0.3, "flow": 0.25, "breadth": 0.2,
                                   "crowding": 0.15, "lifecycle": 0.1}) is None
    scores.breadth = 60.0
    scores.crowding = 50.0
    combined = combine_scores(scores, {"strength": 0.3, "flow": 0.25, "breadth": 0.2,
                                       "crowding": 0.15, "lifecycle": 0.1})
    assert combined is not None
