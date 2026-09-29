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


def test_state_rejudged_from_ema_score_when_hysteresis_off():
    # spec §2b：state 由 EMA 后的分数判定（阈值与 market_regime 同源 70/50/30）。
    # 历史（2026-09-09 2c 扫描发现）：首版实现 state=raw_state 原样透传，α 轴扫描
    # 全档与 baseline 逐位一致才暴露；原测试 test_state_untouched_when_hysteresis_off
    # 把该偏差锁成了合同，随本修复改为本合同。
    smoother = RegimeSmoother(alpha=0.5)
    smoother.smooth(_regime(80.0, "strong"))          # ema=80 → strong
    out = smoother.smooth(_regime(40.0, "weak"))      # ema=60 → normal（raw 40 为 weak）
    assert out["score"] == 60.0
    assert out["state"] == "normal"


def test_state_rejudged_strong_boundary_from_ema():
    smoother = RegimeSmoother(alpha=0.25)
    smoother.smooth(_regime(80.0, "strong"))          # ema=80 → strong
    out = smoother.smooth(_regime(40.0, "weak"))      # ema=70 → ≥70 strong（raw 40 为 weak）
    assert out["state"] == "strong"


def test_state_ladder_normal_weak_retreat_from_ema():
    smoother = RegimeSmoother(alpha=0.75)
    out = smoother.smooth(_regime(55.0, "normal"))    # ema=55 → normal
    assert out["state"] == "normal"
    out2 = smoother.smooth(_regime(20.0, "retreat"))  # ema=28.75 → <30 retreat
    assert out2["state"] == "retreat"
    out3 = smoother.smooth(_regime(40.0, "weak"))     # ema=37.1875 → ≥30 weak
    assert out3["state"] == "weak"


def test_hysteresis_band_applies_on_ema_judged_state():
    # 迟滞带作用于 EMA 重判后的 state（α<1 + 迟滞开组合语义）
    smoother = RegimeSmoother(alpha=0.5, hysteresis=True, strong_enter=70.0, strong_exit_band=5.0)
    smoother.smooth(_regime(80.0, "strong"))          # ema=80 → strong
    out = smoother.smooth(_regime(50.0, "normal"))    # ema=65 → 判 normal；65 ≥ 65 退出线 → 保持 strong
    assert out["state"] == "strong"
    out2 = smoother.smooth(_regime(30.0, "weak"))     # ema=47.5 < 65 → 退出 → weak
    assert out2["state"] == "weak"


def test_hysteresis_keeps_strong_until_exit_band():
    smoother = RegimeSmoother(alpha=1.0, hysteresis=True, strong_enter=70.0, strong_exit_band=5.0)
    smoother.smooth(_regime(75.0, "strong"))          # 进入 strong
    out = smoother.smooth(_regime(67.0, "normal"))    # 67 ≥ 65 退出线：保持 strong
    assert out["state"] == "strong"
    out2 = smoother.smooth(_regime(60.0, "normal"))   # 60 < 65：退出保持；EMA=60 重判 → normal
    assert out2["state"] == "normal"


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
