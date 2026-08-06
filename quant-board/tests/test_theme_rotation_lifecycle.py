from backend.analysis.theme.rotation.config import ThemeRotationConfig
from backend.analysis.theme.rotation.lifecycle import (
    lifecycle_for,
    mainline_concentration,
    market_phase_for,
    rotation_speed_score,
    rotation_state_for,
)

CFG = ThemeRotationConfig()


def _row(**overrides):
    base = {"heatScore": 70.0, "momentumScore": 60.0, "crowdingRisk": 50.0,
            "mainNetInflow": 1.0, "positiveInflowStreak": 2,
            "negativeInflowStreak": 0, "maxBoardHeight": 3}
    base.update(overrides)
    return base


def test_lifecycle_climax():
    state, reasons = lifecycle_for(_row(heatScore=85.0, crowdingRisk=80.0), "expanding", CFG)
    assert state == "climax"
    assert reasons


def test_lifecycle_cooling_by_momentum():
    state, _ = lifecycle_for(_row(momentumScore=30.0), "expanding", CFG)
    assert state == "cooling"


def test_lifecycle_cooling_by_negative_streak():
    state, _ = lifecycle_for(_row(heatScore=90.0, momentumScore=80.0, negativeInflowStreak=2), "expanding", CFG)
    assert state == "cooling"


def test_lifecycle_expanding():
    state, _ = lifecycle_for(_row(heatScore=70.0), "expanding", CFG)
    assert state == "expanding"


def test_lifecycle_emerging():
    state, _ = lifecycle_for(_row(heatScore=45.0, positiveInflowStreak=1), "ice", CFG)
    assert state == "emerging"


def test_lifecycle_ice():
    state, _ = lifecycle_for(_row(heatScore=30.0, momentumScore=30.0), "emerging", CFG)
    assert state == "ice"


def test_lifecycle_transition_clamped():
    state, reasons = lifecycle_for(_row(heatScore=85.0, crowdingRisk=80.0), "ice", CFG)
    assert state == "expanding"
    assert any("transition_clamped" in reason for reason in reasons)


def test_rotation_state_mainline():
    assert rotation_state_for("expanding", 70.0, True, True) == "mainline"
    assert rotation_state_for("cooling", 20.0, True, False) == "cooling"
    assert rotation_state_for("expanding", 70.0, False, True) == "inflow"
    assert rotation_state_for("neutral", 45.0, False, False) == "outflow"


def test_market_phase():
    assert market_phase_for(max_board_height=8, rotation_speed=30.0, mainline_count=2,
                            mainline_concentration=0.5, total_zt_count=60, cfg=CFG) == "rising"
    assert market_phase_for(max_board_height=2, rotation_speed=20.0, mainline_count=0,
                            mainline_concentration=0.3, total_zt_count=10, cfg=CFG) == "ice"
    assert market_phase_for(max_board_height=11, rotation_speed=70.0, mainline_count=1,
                            mainline_concentration=0.7, total_zt_count=80, cfg=CFG) == "climax"
    assert market_phase_for(max_board_height=5, rotation_speed=20.0, mainline_count=0,
                            mainline_concentration=0.3, total_zt_count=50,
                            cooling_theme_ratio=0.4, cfg=CFG) == "cooling"
    assert market_phase_for(max_board_height=5, rotation_speed=20.0, mainline_count=0,
                            mainline_concentration=0.3, total_zt_count=50, cfg=CFG) == "neutral"


def test_market_phase_rising_wins_over_cooling():
    # R3：有稳定主线（board=8、mainline≥1）时，即使部分题材降温也不标退潮
    assert market_phase_for(
        max_board_height=8,
        rotation_speed=30.0,
        mainline_count=2,
        mainline_concentration=0.5,
        total_zt_count=60,
        cooling_theme_ratio=0.5,
        cfg=CFG,
    ) == "rising"


def test_rotation_speed_and_concentration():
    assert rotation_speed_score([3, -3, 4]) == 8 * (10 / 3)
    assert mainline_concentration([90.0, 10.0], 1) == 0.9
    assert mainline_concentration([]) is None
