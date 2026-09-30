# -*- coding: utf-8 -*-
"""M1 相位标签器测试（ranktrend-phase-acceptance-design.md §5 M1）。

纪律：标签本身 as-of（只用当前帧及之前可得数据）；信号缺失 → unknown（fail-visible）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_labeler import (
    daily_phase_from_frames,
    load_sentiment_scores,
    phase_from_emotion_value,
    phase_from_sentiment_score,
)


def test_phase_from_sentiment_score_three_buckets():
    assert phase_from_sentiment_score(69.7, hi=55.0, lo=40.0) == "offense"
    assert phase_from_sentiment_score(48.3, hi=55.0, lo=40.0) == "neutral"
    assert phase_from_sentiment_score(13.6, hi=55.0, lo=40.0) == "defense"
    assert phase_from_sentiment_score(None, hi=55.0, lo=40.0) == "unknown"


def test_phase_from_emotion_value():
    assert phase_from_emotion_value(0.02, hi=0.005, lo=-0.005) == "offense"
    assert phase_from_emotion_value(0.0, hi=0.005, lo=-0.005) == "neutral"
    assert phase_from_emotion_value(-0.0115, hi=0.005, lo=-0.005) == "defense"
    assert phase_from_emotion_value(None, hi=0.005, lo=-0.005) == "unknown"


def test_load_sentiment_scores_filters_half_hour_and_eod():
    docs = [
        {"tradingDate": "2026-09-30", "slotTime": "10:00", "snapshotType": "half_hour",
         "emotionScore": {"score": 65.6}},
        {"tradingDate": "2026-09-30", "slotTime": "10:00", "snapshotType": "daily",
         "emotionScore": {"score": 99.0}},   # 非 half_hour：整体排除
        {"tradingDate": "2026-09-30", "slotTime": "09:30", "snapshotType": "half_hour",
         "emotionScore": None},               # 无连续分：该键值为 None（unknown 语义）
        {"tradingDate": "2026-09-30", "slotTime": "EOD", "snapshotType": "half_hour",
         "emotionScore": {"score": 48.3}},   # EOD 进独立键
    ]
    frame_scores, eod_scores = load_sentiment_scores(docs)
    assert frame_scores[("2026-09-30", "10:00")] == 65.6
    assert frame_scores[("2026-09-30", "09:30")] is None
    assert eod_scores["2026-09-30"] == 48.3


def test_daily_phase_from_frames_majority_tie_and_missing():
    frames = [
        {"tradingDate": "2026-09-30", "slotTime": "09:30", "phase": "offense"},
        {"tradingDate": "2026-09-30", "slotTime": "10:00", "phase": "offense"},
        {"tradingDate": "2026-09-30", "slotTime": "10:30", "phase": "defense"},
        {"tradingDate": "2026-10-09", "slotTime": "09:30", "phase": "unknown"},
    ]
    daily = daily_phase_from_frames(frames)
    assert daily["2026-09-30"] == "offense"   # 众数
    assert daily["2026-10-09"] == "unknown"   # 全 unknown → unknown（不伪造）


def test_daily_phase_tie_breaks_conservative():
    """平票（offense 1 : defense 1）取防守侧——宁可少进攻不可漏防守。"""
    frames = [
        {"tradingDate": "2026-09-30", "slotTime": "09:30", "phase": "offense"},
        {"tradingDate": "2026-09-30", "slotTime": "10:00", "phase": "defense"},
    ]
    assert daily_phase_from_frames(frames)["2026-09-30"] == "defense"
