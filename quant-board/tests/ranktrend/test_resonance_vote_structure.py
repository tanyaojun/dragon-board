# -*- coding: utf-8 -*-
"""D-a 共振缺票结构诊断测试（方案 D，提案 §5.3 分类口径锁定）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.diagnose_resonance_vote_structure import (
    _decile_baseline,
    _excess_of,
    classify_resonance,
    collect_samples,
)


def test_classify_insufficient_branches():
    for reason in ("快照时间轴不完整", "新入榜关注度无效", "横截面有效样本不足", "排名序列不足或无效", "快照样本不足"):
        bucket, driver = classify_resonance({"status": "insufficient", "reasons": [reason], "direction": "hold"})
        assert bucket == f"insufficient:{reason}"
        assert driver == ""


def test_classify_voted_drivers():
    new_entry = classify_resonance({"status": "ok", "direction": "buy", "historyState": "new_entry", "tierReasons": ["新入榜关注度较强"]})
    assert new_entry == ("voted", "新入榜(entry_strength)")
    jump = classify_resonance({"status": "ok", "direction": "buy", "historyState": "established", "tierReasons": ["Jump 事件驱动，排名跳跃式上升"]})
    assert jump == ("voted", "Jump 事件")
    ranked = classify_resonance({"status": "ok", "direction": "sell", "historyState": "established", "tierReasons": ["共振衰竭/反向"]})
    assert ranked == ("voted", "排名序列(direction_score)")


def test_classify_hold_ok_and_unknown_direction():
    assert classify_resonance({"status": "ok", "direction": "hold", "historyState": "established"}) == ("hold_ok", "")
    assert classify_resonance({"status": "ok", "direction": "", "historyState": "established"}) == ("hold_ok", "")


def _samples(deltas_pcts: list[tuple[float, float]], bucket: str = "voted"):
    return [{"bucket": bucket, "driver": "", "direction": "buy", "regime": "normal", "delta": d, "pct": p} for d, p in deltas_pcts]


def test_decile_baseline_and_excess():
    samples = _samples([(0.02, 5.0), (0.02, 15.0), (-0.01, 5.0), (-0.01, 15.0)])
    baseline = _decile_baseline(samples)
    # 桶 0（pct 0-10）：acc 0.5、mean 0.005；桶 1：同
    assert baseline[0] == (0.5, 0.005)
    branch = _samples([(0.04, 8.0), (0.04, 12.0)], bucket="insufficient:横截面有效样本不足")
    stats = _excess_of(branch, baseline)
    assert stats["n"] == 2
    assert stats["meanDelta"] == 0.04
    assert stats["excessMeanDelta"] == 0.035  # 0.04 − 0.005


def test_excess_of_empty_returns_none():
    assert _excess_of([], _decile_baseline(_samples([(0.01, 5.0)]))) is None


def test_collect_samples_fail_visible_skips():
    """帧边界/缺股剔除如实计数（fail-visible，不伪造样本）。"""

    class _Signal(dict):
        pass

    frames = [
        {"snapshotId": "s1", "stocks": [{"code": "1", "rank": 1}]},
        {"snapshotId": "s2", "stocks": [{"code": "1", "rank": 1}]},
    ]
    signals = [
        {"snapshotId": "s1", "code": "1", "rankTrend": {"resonance": {"status": "ok", "direction": "buy", "historyState": "new_entry"}}},
        {"snapshotId": "missing", "code": "1", "rankTrend": {"resonance": {"status": "insufficient", "reasons": ["快照时间轴不完整"]}}},
    ]
    out = collect_samples(signals, frames)
    assert len(out["samples"]) == 1
    assert out["skipped"]["no_snapshot"] == 1
