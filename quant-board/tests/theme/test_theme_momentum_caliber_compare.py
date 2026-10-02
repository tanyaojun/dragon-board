# quant-board/tests/test_theme_momentum_validation_v2.py
"""v2 回放对比：题材动量独立维度 vs v1 融合代理的排序位移统计。"""
from __future__ import annotations

from backend.analysis.theme.momentum_validation import compare_theme_momentum_v1_v2


def _theme(theme_id: str, name: str, heat: float, change: float) -> dict:
    return {
        "themeId": theme_id,
        "themeName": name,
        "entityType": "hot_theme",
        "heatScore": heat,
        "rank": 1,
        "change": change,
        "ztCount": 3,
        "breadthScore": 60.0,
        "mainNetInflow": 1.0,
        "volumeRatio": 1.2,
        "metadata": {"amountRatio": 0.05},
    }


def _frame(date: str, themes: list[dict]) -> dict:
    return {
        "tradingDate": date,
        "slotTime": "15:00",
        "timestamp": 0,
        "stocks": [],
        "hotThemes": themes,
    }


def test_compare_v1_v2_reports_rank_shifts_and_directions() -> None:
    # 25 个交易日：BKAI 持续强涨（v2 动量强、方向 up），BKBA 温和
    themes = [
        _theme("BKAI", "人工智能", 90.0, 0.05),
        _theme("BKBA", "机器人", 70.0, 0.01),
    ]
    frames = [_frame(f"2026-06-{10 + i:02d}", themes) for i in range(25)]

    result = compare_theme_momentum_v1_v2(frames)
    assert result["ok"] is True
    assert "BKAI" in result["perTheme"]
    assert "BKBA" in result["perTheme"]
    assert result["perTheme"]["BKAI"]["v2Direction"] == "up"
    # v2 排序中 BKAI 应在前（涨幅更高）
    assert result["perTheme"]["BKAI"]["v2Rank"] <= result["perTheme"]["BKBA"]["v2Rank"]
    assert "meanAbsRankShift" in result
    assert "directionDistribution" in result
    assert result["directionDistribution"]["up"] >= 1


def test_compare_v1_v2_insufficient_series_flagged() -> None:
    # 日线序列不足 5 日：RPS/窗口动量/距高点维度 None，题材保留并打 insufficient 标记
    # （fail-visible：不伪造缺失、不静默过滤）
    themes = [_theme("BKAI", "人工智能", 90.0, 0.05)]
    frames = [_frame("2026-06-10", themes) for _ in range(2)]

    result = compare_theme_momentum_v1_v2(frames)
    assert result["ok"] is True
    # 题材保留在 perTheme（即使 score=None）
    assert "BKAI" in result["perTheme"]
    assert "cross_section_insufficient" in result["qualityFlags"]
    # 2 帧 < 5 日：维度不足 → insufficient 标记 + reason（fail-visible）
    assert result["perTheme"]["BKAI"]["insufficient"] is True
    assert any("history_insufficient" in r for r in result["perTheme"]["BKAI"]["reasons"])
