"""tier_risk_adjusted 目标函数（回测方案 §5.2）。

- score(result, objective, request=None) 新增 "tier_risk_adjusted" 分支：risk_adjusted 基线
  − 档位硬约束/样本/unknown 惩罚；
- tier_penalty：硬约束违约 +0.5、S 样本<30 +0.2、unknown≥5% +unknown_rate*1.0；
- 无 tierStats 时退化为 risk_adjusted（向后兼容，不破坏既有 objective）。
"""

from __future__ import annotations

import pytest

from backend.optimization.objective import score, tier_penalty


def _base_result() -> dict:
    return {"totalReturn": 0.1, "maxDrawdown": 0.05, "sharpe": 1.5}


def test_tier_risk_adjusted_without_tier_stats_equals_risk_adjusted() -> None:
    assert score(_base_result(), "tier_risk_adjusted") == pytest.approx(score(_base_result(), "risk_adjusted"))


def test_tier_penalty_hard_constraint_break() -> None:
    stats = {"monotonicity": {"passHardConstraint": False}, "tiers": {"S": {"count": 40}}, "unknownRate": 0.01}
    assert tier_penalty(stats) == pytest.approx(0.5)


def test_tier_penalty_s_sample_insufficient() -> None:
    stats = {"monotonicity": {"passHardConstraint": True}, "tiers": {"S": {"count": 20}}, "unknownRate": 0.01}
    assert tier_penalty(stats) == pytest.approx(0.2)


def test_tier_penalty_unknown_rate_excess() -> None:
    stats = {"monotonicity": {"passHardConstraint": True}, "tiers": {"S": {"count": 40}}, "unknownRate": 0.1}
    assert tier_penalty(stats) == pytest.approx(0.1)


def test_tier_penalty_stacks() -> None:
    """违约 + S 不足 + unknown 超限三惩罚叠加。"""
    stats = {
        "monotonicity": {"passHardConstraint": False},
        "tiers": {"S": {"count": 10}},
        "unknownRate": 0.2,
    }
    assert tier_penalty(stats) == pytest.approx(0.5 + 0.2 + 0.2)


def test_tier_penalty_empty_stats() -> None:
    """tierStats 未注入（空 dict）→ 不惩罚（退化）；注入但 S 样本 0 → 样本不足惩罚。"""
    assert tier_penalty({}) == 0.0
    assert tier_penalty({"tiers": {}, "unknownRate": 0.0}) == pytest.approx(0.2)


def test_score_tier_risk_adjusted_applies_penalty() -> None:
    base = score(_base_result(), "risk_adjusted")
    result = {
        **_base_result(),
        "tierStats": {"monotonicity": {"passHardConstraint": False}, "tiers": {"S": {"count": 40}}, "unknownRate": 0.01},
    }
    assert score(result, "tier_risk_adjusted") == pytest.approx(base - 0.5)


def test_other_objectives_unaffected() -> None:
    """既有 objective 行为不变（request 参数默认 None 向后兼容）。"""
    assert score(_base_result(), "max_drawdown") == pytest.approx(-0.05)
    assert score(_base_result(), "sharpe") == pytest.approx(1.5)
    assert score(_base_result(), "risk_adjusted") == pytest.approx(0.1 - 0.05 * 1.5 + 1.5 * 0.02)
