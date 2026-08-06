from backend.analysis.theme.momentum import (
    LIFECYCLE_BOOST,
    LIFECYCLE_PENALTY,
    REVERSAL_LIFECYCLES,
    fuse_theme_resonance,
)


def test_lifecycle_vocabulary_extends_engine_words() -> None:
    # R7：theme_momentum 消费的是 rotationState（值域 mainline/inflow/outflow/cooling/emerging/neutral），
    # 有效新词为 emerging/inflow；expanding/climax 是 lifecycle 词，永不匹配，已从词表移除
    assert "inflow" in LIFECYCLE_BOOST
    assert "emerging" in LIFECYCLE_BOOST
    assert "outflow" in LIFECYCLE_PENALTY
    assert "cooling" in REVERSAL_LIFECYCLES
    assert "expanding" not in LIFECYCLE_BOOST
    assert "climax" not in LIFECYCLE_PENALTY


def test_fuse_resonance_boosts_inflow_leader() -> None:
    frame_momentum = {
        "crossSectionOk": True,
        "themes": {"BKAI": {"status": "ok", "score": 70.0, "direction": "up"}},
    }
    exposure = {
        "themeId": "BKAI", "themeName": "人工智能", "role": "leader", "roleWeight": 1.0,
        "rotationState": "inflow", "themeContribution": 60.0, "reasons": [],
        "crowdingRisk": 50.0,
    }
    fused = fuse_theme_resonance({"score": 60.0}, exposure, frame_momentum)
    assert fused["theme"]["status"] == "ok"
    assert fused["theme"]["themeLifecycle"] == "inflow"
    # adjustment = (70-50)*1.0*0.3 = 6.0 + lifecycleBonus 5.0 → 11.0
    assert fused["theme"]["adjustment"] == 11.0


def test_fuse_resonance_penalizes_outflow_follower() -> None:
    frame_momentum = {
        "crossSectionOk": True,
        "themes": {"BKAI": {"status": "ok", "score": 50.0, "direction": "down"}},
    }
    exposure = {
        "themeId": "BKAI", "themeName": "人工智能", "role": "follower", "roleWeight": 0.62,
        "rotationState": "outflow", "themeContribution": 60.0, "reasons": [],
        "crowdingRisk": 80.0,
    }
    fused = fuse_theme_resonance({"score": 60.0}, exposure, frame_momentum)
    # adjustment = 0 - min(10, 80/10) → -8.0
    assert fused["theme"]["adjustment"] == -8.0
