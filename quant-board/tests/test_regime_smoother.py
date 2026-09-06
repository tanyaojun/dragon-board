from __future__ import annotations

from backend.analysis.ranktrend.trend.regime_smoother import RegimeSmoother


def _regime(score: float, state: str) -> dict:
    return {"score": score, "state": state, "reasons": [f"score={score}"]}


def test_passthrough_returns_same_dict_when_default_params():
    smoother = RegimeSmoother()  # alpha=1.0, hysteresis=False
    regime = _regime(80.0, "strong")
    assert smoother.smooth(regime) is regime          # 同一引用：零行为变化


def test_ema_smooths_score_with_alpha():
    smoother = RegimeSmoother(alpha=0.5)
    out1 = smoother.smooth(_regime(80.0, "strong"))
    assert out1["score"] == 80.0                      # 首帧 ema=score
    out2 = smoother.smooth(_regime(60.0, "normal"))
    assert out2["score"] == 70.0                      # 0.5*60 + 0.5*80
    out3 = smoother.smooth(_regime(60.0, "normal"))
    assert out3["score"] == 65.0
    assert any("EMA" in str(reason) for reason in out2["reasons"])


def test_state_untouched_when_hysteresis_off():
    smoother = RegimeSmoother(alpha=0.5)              # EMA 生效但迟滞关
    out = smoother.smooth(_regime(55.0, "weak"))
    assert out["state"] == "weak"                     # state 恒为 market_regime 原值
    assert out["score"] == 55.0


def test_hysteresis_keeps_strong_until_exit_band():
    smoother = RegimeSmoother(alpha=1.0, hysteresis=True, strong_enter=70.0, strong_exit_band=5.0)
    smoother.smooth(_regime(75.0, "strong"))          # 进入 strong
    out = smoother.smooth(_regime(67.0, "normal"))    # 67 ≥ 65 退出线：保持 strong
    assert out["state"] == "strong"
    out2 = smoother.smooth(_regime(60.0, "weak"))     # 60 < 65：退出
    assert out2["state"] == "weak"


def test_hysteresis_enters_strong_only_at_enter_threshold():
    smoother = RegimeSmoother(alpha=1.0, hysteresis=True, strong_enter=70.0, strong_exit_band=5.0)
    out = smoother.smooth(_regime(68.0, "normal"))    # 68 < 70：不进 strong
    assert out["state"] == "normal"
    out2 = smoother.smooth(_regime(72.0, "strong"))
    assert out2["state"] == "strong"


def test_reset_clears_ema_and_state_memory():
    smoother = RegimeSmoother(alpha=0.5)
    smoother.smooth(_regime(80.0, "strong"))
    smoother.reset()
    out = smoother.smooth(_regime(60.0, "normal"))
    assert out["score"] == 60.0                       # 首帧语义恢复
