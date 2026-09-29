"""完整回测链路验证（回测方案 §6 流程端到端）。

合成 frames 跑 TrialExecutor.evaluate（objective=tier_risk_adjusted）：
replay（含 synergy.signalTier）→ TradeSimulator（synergy 门）→ tier_forward_returns
（metrics.tierStats）→ tier_risk_adjusted 评分；trial 含 tierMonotonicity/tierConstraintFailed。

断言采用确定性值（合成数据 S 样本 < 30 → 硬约束必然失败 → tierConstraintFailed=True、
score 必含惩罚），并验证 synergy 交易参数只透传交易层、不污染信号/档位统计。
"""

from __future__ import annotations

import pytest

from backend.optimization.objective import score, tier_penalty
from backend.optimization.trial import TrialExecutor


def _make_frames(n: int = 26) -> list[dict]:
    stocks_by_change = {
        "000001": 3.5, "000002": 2.8, "000003": -2.5, "000004": 0.2, "000005": 1.8,
        "000006": -1.2, "000007": 0.8, "000008": 4.2,
    }
    frames = []
    for i in range(n):
        stocks = []
        for idx, (code, change) in enumerate(stocks_by_change.items()):
            stocks.append(
                {
                    "code": code,
                    "name": f"股{idx}",
                    "rank": max(1, 30 - i - idx),
                    "avgRankNum": max(1, 30 - i - idx),
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


def _split(frames: list[dict]) -> dict:
    return {
        "train_frames": frames,
        "train_signal_frames": frames,
        "validation_frames": [],
        "validation_signal_frames": [],
        "metadata": {"dataset_id": "d1", "snapshot_type": "half_hour"},
    }


def _request() -> dict:
    return {
        "dataset_id": "d1",
        "snapshot_type": "half_hour",
        "strategy_name": "rank_trend_candidate",
        "method": "grid",
        "random_seed": 1,
        "search_space": {},
        "objective": "tier_risk_adjusted",
        "tier_horizon": 3,
    }


def _run_trial(params: dict) -> tuple[dict, list]:
    return TrialExecutor().evaluate(
        0,
        params,
        _split(_make_frames()),
        {},
        {"entryStrategy": "rank_trend_candidate", "positionSize": 0.05, "maxPositions": 4},
        "rank_trend_candidate",
        "tier_risk_adjusted",
        _request(),
        {},
        "test",
    )


def test_end_to_end_trial_completes_with_deterministic_tier_stats() -> None:
    """完整链路跑通：trial completed，tierStats 注入，合成数据 S 样本=0 → 惩罚精确 0.7（0.5 违约 + 0.2 样本不足）。"""
    trial, artifacts = _run_trial({"tierRankTrendStrongMin": 0.5})
    assert trial["status"] == "completed"
    ts = trial["metrics"]["tierStats"]
    assert ts["frameCount"] == 26
    assert ts["tiers"]["S"]["count"] == 0  # replay 无 resonance，合成数据确定性：无 S 档
    assert ts["unknownRate"] == 0.0
    assert tier_penalty(ts) == pytest.approx(0.7)
    assert ts["monotonicity"]["passHardConstraint"] is False
    assert trial["tierConstraintFailed"] is True
    assert trial["tierMonotonicity"]["train"]["passHardConstraint"] is False
    assert artifacts  # train artifact 落盘


def test_end_to_end_score_equals_risk_adjusted_minus_penalty() -> None:
    """score = risk_adjusted(artifact simulation) − tier_penalty(tierStats)。
    合成数据无成交 → base=0 → score 精确 -0.7（惩罚真实生效的硬编码断言）。"""
    trial, artifacts = _run_trial({"tierRankTrendStrongMin": 0.5})
    assert trial["status"] == "completed"
    simulation = artifacts[0]["result"]["tradeSimulation"]
    assert simulation["tradeCount"] == 0  # 前置：合成数据无成交 → base=0
    base = score(simulation, "risk_adjusted")
    assert base == pytest.approx(0.0)
    expected = base - tier_penalty(trial["metrics"]["tierStats"])
    assert expected == pytest.approx(-0.7)
    assert trial["score"] == pytest.approx(-0.7)


def test_synergy_trade_param_does_not_pollute_tier_stats() -> None:
    """synergy 交易参数只透传交易层：开启门不影响信号/档位统计（tierStats 完全一致）。"""
    frames = _make_frames()
    baseline, _ = TrialExecutor().evaluate(
        0, {"synergyEntryTierMin": "none"}, _split(frames), {}, {"entryStrategy": "rank_trend_candidate"},
        "rank_trend_candidate", "tier_risk_adjusted", _request(), {}, "test",
    )
    gated, _ = TrialExecutor().evaluate(
        0, {"synergyEntryTierMin": "a", "synergyExitOnDanger": True}, _split(frames), {},
        {"entryStrategy": "rank_trend_candidate"}, "rank_trend_candidate", "tier_risk_adjusted", _request(), {}, "test",
    )
    assert baseline["status"] == "completed"
    assert gated["status"] == "completed"
    assert baseline["metrics"]["tierStats"] == gated["metrics"]["tierStats"]
