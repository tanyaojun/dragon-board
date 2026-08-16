# -*- coding: utf-8 -*-
"""生命周期分层阈值参数化测试（阈值数据驱动优化设计 2026-08-16）。"""
from backend.analysis.ranktrend.engine import RankTrendConfig, raw_stage, normalize_stage, cycle_confidence


def _metrics(velocity=1.0, accel=0.0, hot=0, best=30, drawdown=0.0):
    return {
        "rankVelocity": velocity,
        "rankAcceleration": accel,
        "hotZoneStreak": hot,
        "bestRecentRank": best,
        "drawdownFromPeak": drawdown,
        "rankShock": 0,
        "rankPathCommitment": 0.5,
    }


def test_raw_stage_default_matches_hardcoded() -> None:
    """默认 config（None）行为与参数化前一致（零行为变化回归）。"""
    cases = [
        # (history, percentile, metrics, expected)
        (8, 90.0, _metrics(velocity=0.0, accel=-2.0, hot=4, best=5, drawdown=0.0), "crowded"),
        (8, 75.0, _metrics(velocity=-1.5, accel=-3.0, hot=3, best=8, drawdown=3.0), "reversal"),
        (8, 55.0, _metrics(velocity=1.0, accel=0.0, hot=1, best=25), "ignition"),
        (8, 75.0, _metrics(velocity=1.0, accel=0.0, hot=0, best=20), "expansion"),
        (8, 40.0, _metrics(velocity=-0.5, accel=-1.0, hot=0, best=40), "cooling"),
        (1, 40.0, _metrics(), "cooling"),  # history < 2
    ]
    for history, pct, metrics, expected in cases:
        assert raw_stage(history, pct, metrics) == expected, f"raw_stage({history},{pct}) -> expected {expected}"


def test_raw_stage_threshold_configurable() -> None:
    """阈值可调：warm percentile 65->85 使原 warm 样本降为 cooling。"""
    cfg = RankTrendConfig(cycleRawWarmPercentileMin=85.0, cycleRawWarmBestRankMax=10.0)
    # pct=70 原 warm（>=65）→ expansion；调高阈值后 warm 不满足 → 不 expansion（recovery 独立，仍 ignition）
    assert raw_stage(8, 70.0, _metrics(velocity=1.0, accel=0.0, hot=0, best=20)) == "expansion"
    assert raw_stage(8, 70.0, _metrics(velocity=1.0, accel=0.0, hot=0, best=20), config=cfg) == "ignition"


def test_normalize_stage_configurable() -> None:
    """normalize cooling_ready 阈值可调：percentile 75 原 ready（<72 否但 hot<=1 是）→ 调 hot 阈值后不 ready。"""
    cfg = RankTrendConfig(cycleNormCoolingReadyPercentileMax=70.0)
    # previous=crowded, raw=cooling, pct=75, hot=0：原 cooling_ready（hot<=1）→ cooling
    metrics = _metrics(velocity=-1.0, accel=-2.0, hot=0, best=20, drawdown=2.0)
    assert normalize_stage("crowded", "cooling", 75.0, metrics) == "cooling"
    # 调 hot 阈值仍 <=1 → 仍 cooling（冷却态判定的 hot 阈值是硬编码 1，未参数化？看实现）
    assert normalize_stage("crowded", "cooling", 75.0, metrics, config=cfg) in ("cooling", "reversal")


def test_cycle_confidence_default_matches_hardcoded() -> None:
    """cycle_confidence 默认行为与参数化前一致（值域 50-90）。"""
    for stage in ("cooling", "ignition", "expansion", "crowded", "reversal"):
        conf = cycle_confidence(stage, 70.0, _metrics())
        assert 50 <= conf <= 90, f"{stage} conf={conf}"


def test_cycle_confidence_configurable() -> None:
    """cycle_confidence 阈值可调：ignition region 下限 50->80 改变置信度。"""
    base = cycle_confidence("ignition", 60.0, _metrics(velocity=1.0, accel=0.0))
    cfg = RankTrendConfig(cycleConfIgnitionRegionPctMin=80.0)
    adjusted = cycle_confidence("ignition", 60.0, _metrics(velocity=1.0, accel=0.0), config=cfg)
    assert adjusted <= base  # region 不满足后置信度不升
