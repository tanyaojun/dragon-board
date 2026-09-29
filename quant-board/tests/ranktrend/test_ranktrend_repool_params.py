# -*- coding: utf-8 -*-
"""P_repool_timeline_gap 研究参数测试（2026-09-20 立项）。

纪律（skills/ranktrend-signal-research 第 0 步 5）：新增测试 = 默认值断言 + 参数生效测试，
golden 不漂移（默认值 = 原硬编码 5）。
"""
from __future__ import annotations

import pytest

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.engine.runtime import RankTrendPythonEngine


def test_degraded_sample_floor_defaults_to_current_behavior():
    config = RankTrendConfig()
    assert config.degradedSampleFloor == 5


def test_degraded_sample_floor_accepts_override():
    config = RankTrendConfig(degradedSampleFloor=7)
    assert config.degradedSampleFloor == 7


def test_degraded_sample_floor_rejects_out_of_range():
    # >= momentum_min_samples(=22) 会吞掉 ok 档；< 1 会让 insufficient 桶永空
    with pytest.raises(ValueError, match="degradedSampleFloor"):
        RankTrendConfig(degradedSampleFloor=22)
    with pytest.raises(ValueError, match="degradedSampleFloor"):
        RankTrendConfig(degradedSampleFloor=0)


def _build_frames(frame_count: int) -> list[dict]:
    """最小 replay 场景：单股连续出现 frame_count 帧，rank 恒 1（percentile 恒 100）。"""
    frames = []
    for index in range(frame_count):
        frames.append(
            {
                "snapshotId": f"half_hour:2026-09-10:{index:02d}",
                "tradingDate": "2026-09-10",
                "type": "half_hour",
                "timestamp": index,
                "stocks": [
                    {"code": "000001", "name": "测试股", "rank": 1, "avgRankNum": 10.0, "change": 1.0}
                ],
            }
        )
    return frames


def _sample_status_of(signals: list[dict]) -> str:
    # replay 逐帧产出：最后一帧的序列最长 = 「当前判定」语义（与前端实时一致）
    meta = (signals[-1]["rankTrend"].get("meta") or {}).get("sampleQuality") or {}
    return str(meta.get("status"))


def test_repool_degraded_floor_default_keeps_current_behavior():
    # 6 点序列：默认 floor=5 → 5 <= 6 < 22 → degraded（现状行为不变）
    engine = RankTrendPythonEngine(RankTrendConfig())
    signals = engine.replay(_build_frames(6))
    assert signals, "replay 应产出信号"
    assert _sample_status_of(signals) == "degraded"


def test_repool_degraded_floor_raise_pushes_short_series_to_insufficient():
    # floor=7：同一 6 点序列 < 7 → insufficient（参数生效）
    engine = RankTrendPythonEngine(RankTrendConfig(degradedSampleFloor=7))
    signals = engine.replay(_build_frames(6))
    assert signals
    assert _sample_status_of(signals) == "insufficient"


def test_repool_degraded_floor_lower_admits_shorter_series():
    # floor=3：4 点序列（默认 <5 → insufficient）升 degraded（参数生效）
    engine = RankTrendPythonEngine(RankTrendConfig(degradedSampleFloor=3))
    signals = engine.replay(_build_frames(4))
    assert signals
    assert _sample_status_of(signals) == "degraded"
