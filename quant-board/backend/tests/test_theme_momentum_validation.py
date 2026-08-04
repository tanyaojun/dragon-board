# quant-board/backend/tests/test_theme_momentum_validation.py
from backend.analysis.theme_momentum_validation import compare_theme_momentum_rolling


def _frame(index, stock_code, themes, heat_rows):
    return {
        "tradingDate": "2026-08-04",
        "slotTime": f"{index:02d}:00",
        "type": "half_hour",
        "timestamp": index,
        "stocks": [{"code": stock_code, "themes": themes, "change": 3.0}],
        "hotThemes": heat_rows,
    }


def _rolling_frames(count=12):
    frames = []
    for idx in range(count):
        hot = [{
            "entityType": "hot_theme",
            "themeId": "T0",
            "themeName": "主线概念板块",
            "heatScore": 40.0 + idx * 5.0,
            "rank": 1,
            "rotationState": "mainline",
            "crowdingRisk": 30.0,
            "metadata": {"rankEligible": True},
        }]
        hot += [{
            "entityType": "hot_theme",
            "themeId": f"T{i}",
            "themeName": f"普通概念{i}",
            "heatScore": 50.0,
            "rank": i + 1,
            "rotationState": "neutral",
            "crowdingRisk": 30.0,
            "metadata": {"rankEligible": True},
        } for i in range(1, 25)]
        frames.append(_frame(idx, "000001", ["主线概念"], hot))
    return frames


def test_compare_rolling_reports_multi_frame_stats():
    frames = _rolling_frames()
    base_resonance_by_frame = [
        {"000001": {"status": "ok", "direction": "buy", "score": 60, "label": "中等"}}
        for _ in frames
    ]
    result = compare_theme_momentum_rolling(frames, base_resonance_by_frame)
    assert result["ok"] is True
    assert result["frameCount"] >= 3
    assert result["adjustedCount"] >= 1
    assert result["insufficientCount"] == 0
    assert result["meanAdjustment"] > 0
    assert result["adjustmentByLifecycle"].get("mainline", 0) > 0
    assert result["directionDistribution"].get("buy", 0) >= 1
