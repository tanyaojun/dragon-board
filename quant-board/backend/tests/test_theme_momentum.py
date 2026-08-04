# quant-board/backend/tests/test_theme_momentum.py
import math

import pytest

from backend.analysis.theme_momentum import (
    THEME_CROSS_SECTION_MIN,
    build_theme_strength_series,
    compute_theme_momentum_series,
)


def _theme(theme_id, heat, rank, rotation="neutral", eligible=True, extra=None):
    item = {
        "entityType": "hot_theme",
        "themeId": theme_id,
        "themeName": f"{theme_id}概念板块",
        "heatScore": heat,
        "rank": rank,
        "rotationState": rotation,
        "metadata": {"rankEligible": eligible},
    }
    if extra:
        item.update(extra)
    return item


def _frame(index, theme_rows):
    return {
        "tradingDate": "2026-08-04",
        "slotTime": f"{index:02d}:00",
        "type": "half_hour",
        "timestamp": index,
        "stocks": [],
        "hotThemes": theme_rows,
    }


def test_series_keeps_only_rank_eligible_finite_heat():
    frames = [
        _frame(0, [
            _theme("A", 50.0, 1),
            _theme("B", math.nan, 2),
            _theme("C", 40.0, 3, eligible=False),
        ]),
    ]
    series = build_theme_strength_series(frames)
    assert list(series) == ["A"]
    assert series["A"][0][:2] == (0, 50.0)


def test_momentum_series_mirrors_resonance_bounds():
    themes = [_theme(f"T{i}", 50.0, i + 1) for i in range(25)]
    # T0 持续升温，其余横盘
    frames = []
    for idx in range(12):
        rows = [_theme("T0", 40.0 + idx * 2.0, 1)]
        rows += [_theme(f"T{i}", 50.0, i + 1) for i in range(1, 25)]
        frames.append(_frame(idx, rows))
    result = compute_theme_momentum_series(frames)
    frame = result["frames"][-1]
    assert frame["themeSampleCount"] >= THEME_CROSS_SECTION_MIN
    assert frame["qualityFlags"] == []
    momentum = frame["themes"]["T0"]
    assert momentum["status"] == "ok"
    assert 0 <= momentum["score"] <= 100
    assert momentum["direction"] == "buy"
    assert momentum["relativeMomentum"] > 0


def test_momentum_series_insufficient_cross_section():
    frames = [_frame(idx, [_theme(f"T{i}", 50.0, i + 1) for i in range(5)]) for idx in range(12)]
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert frame["themeSampleCount"] < THEME_CROSS_SECTION_MIN
    assert "theme_cross_section_insufficient" in frame["qualityFlags"]


def test_momentum_series_skips_short_history_theme():
    frames = [_frame(idx, [_theme("A", 50.0 + idx, 1), _theme("B", 50.0, 2)]) for idx in range(12)]
    # B 只在前 4 帧出现，之后缺槽
    for idx in range(4, 12):
        frames[idx]["hotThemes"] = [_theme("A", 50.0 + idx, 1)]
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert "B" not in frame["themes"]
    assert "A" in frame["themes"]


def test_momentum_series_all_nan_heat_is_insufficient():
    frames = [
        _frame(idx, [_theme("A", math.nan, 1), _theme("B", math.nan, 2)]) for idx in range(12)
    ]
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert frame["themes"] == {}
    assert frame["themeSampleCount"] == 0
    assert "theme_cross_section_insufficient" in frame["qualityFlags"]


def test_momentum_series_jump_by_rank_only():
    # heatScore 恒定，但第 10 帧 rank 从 8 跳到 1（提升 >= 3 槽）
    frames = []
    for idx in range(12):
        rank = 8 - (3 if idx >= 10 else 0)
        rows = [_theme(f"T{i}", 50.0, i + 1) for i in range(25)]
        rows[0] = _theme("T0", 50.0, rank)
        frames.append(_frame(idx, rows))
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    momentum = frame["themes"]["T0"]
    assert momentum["jumpFreshness"] > 0


def test_momentum_series_rank_missing_uses_heat_jump():
    # rank 全部缺失，heatScore 单帧提升 >= 15 触发 Jump
    frames = []
    for idx in range(12):
        rows = [_theme(f"T{i}", 50.0, None) for i in range(25)]
        rows[0] = _theme("T0", 50.0 if idx < 9 else 70.0, None)
        frames.append(_frame(idx, rows))
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert frame["themes"]["T0"]["jumpFreshness"] > 0


def test_momentum_series_reversal_penalty_adds_cooling_bonus():
    frames = []
    for idx in range(12):
        rows = [_theme(f"T{i}", 50.0, i + 1) for i in range(25)]
        rows[0] = _theme("T0", 50.0, 1, rotation="cooling")
        frames.append(_frame(idx, rows))
    momentum = compute_theme_momentum_series(frames)["frames"][-1]["themes"]["T0"]
    assert momentum["reversalPenalty"] == pytest.approx(0.2)
