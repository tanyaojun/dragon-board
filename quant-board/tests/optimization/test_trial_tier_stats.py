"""trial 接入 tierStats（回测方案 §5.3）。

- evaluate_phase：replay 后注入 metrics["tierStats"]（档位单调性统计）+ artifact.tierMonotonicity；
- score_trial：收到带 tierStats 的 simulation 后 tier_risk_adjusted 惩罚生效。
"""

from __future__ import annotations

from backend.optimization.objective import score, score_trial
from backend.optimization.trial import TrialExecutor


def _make_frames(n: int = 24) -> list[dict]:
    stocks_by_change = {"000001": 3.5, "000002": -2.5, "000003": 0.2}
    frames = []
    for i in range(n):
        stocks = []
        for idx, (code, change) in enumerate(stocks_by_change.items()):
            stocks.append(
                {
                    "code": code,
                    "name": f"股{idx}",
                    "rank": max(1, 20 - i - idx),
                    "avgRankNum": max(1, 20 - i - idx),
                    "change": change,
                    "volumeRatio": 1.8 if change > 0 else 0.7,
                    "zlje": 1200 if change > 0 else -800,
                    "zljzb": 5.0 if change > 0 else -4.0,
                }
            )
        frames.append(
            {
                "snapshotId": f"s{i}",
                "type": "half_hour",
                "timestamp": i,
                "tradingDate": "2026-06-05",
                "slotTime": "10:00",
                "marketContext": {
                    "payload": {
                        "sentiment": {"phaseName": "发酵期"},
                        "marketData": {"ztCount": 10, "dtCount": 1, "upCount": 500, "downCount": 100},
                    }
                },
                "stocks": stocks,
            }
        )
    return frames


def _run_phase() -> dict:
    frames = _make_frames()
    return TrialExecutor().evaluate_phase(
        "train",
        frames,
        frames,
        {},
        {},
        {"entryStrategy": "rank_trend_candidate"},
        "rank_trend_candidate",
        "trial_0001",
        "config_hash",
        {"tier_horizon": 3, "dataset_id": "d1", "snapshot_type": "half_hour", "objective": "tier_risk_adjusted"},
        {},
    )


def test_evaluate_phase_injects_tier_stats() -> None:
    result = _run_phase()
    tier_stats = result["metrics"]["tierStats"]
    assert "monotonicity" in tier_stats
    assert "tiers" in tier_stats
    assert "passHardConstraint" in tier_stats["monotonicity"]
    assert "tierMonotonicity" in result["artifact"]["result"]
    assert "passHardConstraint" in result["artifact"]["result"]["tierMonotonicity"]


def test_score_trial_applies_tier_penalty_via_injected_stats() -> None:
    """simulation 注入 tierStats 后，tier_risk_adjusted 分数 = risk_adjusted − 惩罚。"""
    base_result = {"totalReturn": 0.1, "maxDrawdown": 0.05, "sharpe": 1.5, "tradeCount": 10}
    tier_stats = {
        "monotonicity": {"passHardConstraint": False},
        "tiers": {"S": {"count": 40}},
        "unknownRate": 0.01,
    }
    train = {**base_result, "tierStats": tier_stats}
    details = score_trial(train, None, "tier_risk_adjusted", {})
    expected = score(base_result, "tier_risk_adjusted") - 0.5  # 违约惩罚已在 score 内计算
    assert details["score"] == round(expected, 6)
    assert details["objective"] == "tier_risk_adjusted"


def test_score_trial_without_tier_stats_degrades() -> None:
    """tierStats 未注入时 tier_risk_adjusted 退化为 risk_adjusted（无惩罚）。"""
    base_result = {"totalReturn": 0.1, "maxDrawdown": 0.05, "sharpe": 1.5, "tradeCount": 10}
    details = score_trial(base_result, None, "tier_risk_adjusted", {})
    assert details["score"] == round(score(base_result, "risk_adjusted"), 6)


def test_phase_public_score_matches_trial_score_scope() -> None:
    """phase_public 对 tier_risk_adjusted 注入 tierStats：phase 分数与 trial 分数同口径（含档位惩罚）。"""
    from backend.optimization.objective import phase_public

    base_result = {"totalReturn": 0.1, "maxDrawdown": 0.05, "sharpe": 1.5, "tradeCount": 10}
    tier_stats = {
        "monotonicity": {"passHardConstraint": False},
        "tiers": {"S": {"count": 40}},
        "unknownRate": 0.01,
    }
    phase_eval = {
        "runId": "r1",
        "range": "r",
        "signalFrameRange": "s",
        "simulation": base_result,
        "metrics": {"tierStats": tier_stats},
    }
    public = phase_public(phase_eval, "tier_risk_adjusted")
    assert public["score"] == round(score({**base_result, "tierStats": tier_stats}, "tier_risk_adjusted"), 6)
    assert public["score"] < round(score(base_result, "risk_adjusted"), 6)  # 惩罚生效


def test_tier_horizon_fallback_on_invalid_value() -> None:
    """tier_horizon 非法/缺失回退 3（不炸 trial）。"""
    from backend.optimization.trial import TrialExecutor

    frames = _make_frames()
    result = TrialExecutor().evaluate_phase(
        "train", frames, frames, {}, {},
        {"entryStrategy": "rank_trend_candidate"}, "rank_trend_candidate",
        "trial_0002", "config_hash",
        {"objective": "tier_risk_adjusted", "tier_horizon": "abc"},
        {},
    )
    assert "tierStats" in result["metrics"]
    assert result["metrics"]["tierStats"]["horizon"] == 3  # 非法 "abc" 回退默认 3
