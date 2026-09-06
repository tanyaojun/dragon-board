from __future__ import annotations

from backend.analysis.ranktrend.engine.config import RankTrendConfig


def test_denoise_defaults_are_current_behavior():
    config = RankTrendConfig()
    assert config.lifecycleConfirmFrames == 1
    assert config.regimeScoreEmaAlpha == 1.0
    assert config.regimeStateHysteresis is False
    assert config.regimeStrongHysteresisBand == 5.0


def test_denoise_params_accept_overrides():
    config = RankTrendConfig(
        lifecycleConfirmFrames=3,
        regimeScoreEmaAlpha=0.5,
        regimeStateHysteresis=True,
        regimeStrongHysteresisBand=6.0,
    )
    assert config.lifecycleConfirmFrames == 3
    assert config.regimeScoreEmaAlpha == 0.5
    assert config.regimeStateHysteresis is True
    assert config.regimeStrongHysteresisBand == 6.0
