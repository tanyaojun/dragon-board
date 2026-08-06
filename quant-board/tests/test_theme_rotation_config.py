from backend.analysis.theme.rotation.config import ThemeRotationConfig


def test_default_config_contract():
    cfg = ThemeRotationConfig()
    assert cfg.window_slots == 8
    assert cfg.min_slots_for_state == 3
    assert abs(sum(cfg.weights.values()) - 1.0) < 1e-9
    assert set(cfg.weights) == {"strength", "flow", "breadth", "crowding", "lifecycle"}
    assert cfg.algorithm_version == "theme_rotation_v2"


def test_config_thresholds_are_in_expected_ranges():
    cfg = ThemeRotationConfig()
    assert 0 < cfg.ice_heat < cfg.expanding_heat < cfg.climax_heat <= 100
    assert cfg.mainline_top_n >= 1
    assert cfg.cooling_negative_inflow_streak >= 1
