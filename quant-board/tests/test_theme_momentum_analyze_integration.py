# quant-board/tests/test_theme_momentum_analyze_integration.py
"""analyze 接入题材动量 v2：resonance 回归纯六因子 + themeMomentumContext/每股投影。"""
from __future__ import annotations

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.theme.daily_series import ThemeDailySeries
from backend.analysis.theme.momentum import compute_theme_momentum_v2
from backend.api.ranktrend_routes import (
    _analyze_frames,
    _apply_resonance_final,
    _theme_momentum_projection,
    _to_engine_frame,
)


def _frame(date: str, slot: str, ts: int, stocks: list[dict], hot_themes: list[dict]) -> dict:
    return {
        "tradingDate": date,
        "slotTime": slot,
        "type": "half_hour",
        "timestamp": ts,
        "stocks": stocks,
        "hotThemes": hot_themes,
        "marketContext": {"sentiment": {}, "marketStats": {}},
    }


def _stock(code: str, rank: int = 1, avg: float = 90.0) -> dict:
    return {"code": code, "rank": rank, "avgRankNum": avg}


def _theme(theme_id: str, name: str, heat: float = 80.0, rank: int = 1,
           rotation: str = "neutral", change: float = 0.05) -> dict:
    return {
        "themeId": theme_id,
        "themeName": name,
        "entityType": "hot_theme",
        "heatScore": heat,
        "rank": rank,
        "rotationState": rotation,
        "change": change,
        "ztCount": 5,
        "breadthScore": 70.0,
        "mainNetInflow": 2.0,
        "volumeRatio": 1.5,
        "metadata": {"amountRatio": 0.05},
    }


def _series(code: str, days: int = 25) -> list[tuple[str, int, float]]:
    return [(f"2026-07-{10 + i:02d} 15:00", i + 1, 90.0) for i in range(days)]


def test_analyze_outputs_theme_momentum_context_and_keeps_resonance_pure() -> None:
    stocks = [_stock("600001", 1), _stock("600002", 2)]
    themes = [_theme("BKAI", "人工智能"), _theme("BKBA", "机器人")]
    # 25 个不同交易日，日线序列满足 20 日窗口
    frames = [
        _frame(f"2026-06-{10 + i:02d}", "15:00", 1000 + i, stocks, themes)
        for i in range(25)
    ]
    engine = RankTrendPythonEngine(RankTrendConfig())
    series = {
        "600001": _series("600001"),
        "600002": _series("600002"),
    }
    out = _analyze_frames(
        engine, frames, series, ["600001", "600002"],
        dataset_id="dragonboard_live",
    )
    last = out[-1]
    # 帧级 themeMomentumContext 存在且版本正确
    assert "themeMomentumContext" in last
    assert last["themeMomentumContext"]["version"] == "theme_momentum_v2"
    factors = last["themeMomentumContext"]["factors"]
    assert any(f["themeId"] == "BKAI" for f in factors)

    for stock_out in last["stocks"]:
        analysis = stock_out["analysis"]
        assert analysis["resonance"]["status"] == "ok"
        # 解耦：resonance 不再含 theme 子对象（不再融合）
        assert "theme" not in analysis["resonance"]
        # 新只读投影存在
        tm = analysis["themeMomentum"]
        assert tm["status"] in {"ok", "insufficient"}
        if tm["status"] == "ok":
            assert tm["direction"] in {"up", "neutral", "down"}
            assert "themeId" in tm and "themeName" in tm
        assert "decision" in analysis


def test_theme_momentum_projection_ok() -> None:
    exposure = {
        "themeId": "BKAI",
        "themeName": "人工智能",
        "role": "core",
        "roleWeight": 0.82,
        "themeContribution": 12.0,
        "rotationState": "neutral",
        "reasons": ["mainTheme match"],
    }
    context = {
        "version": "theme_momentum_v2",
        "factors": [{
            "themeId": "BKAI",
            "themeName": "人工智能",
            "score": 78.0,
            "direction": "up",
            "phaseLabel": "扩散",
        }],
        "qualityFlags": [],
        "computedAt": 0,
    }
    proj = _theme_momentum_projection(exposure, context)
    assert proj["status"] == "ok"
    assert proj["score"] == 78.0
    assert proj["direction"] == "up"
    assert proj["phaseLabel"] == "扩散"
    assert proj["role"] == "core"


def test_theme_momentum_projection_insufficient() -> None:
    proj = _theme_momentum_projection(None, {"factors": [], "qualityFlags": [], "computedAt": 0})
    assert proj["status"] == "insufficient"
    assert "theme_mapping_missing" in proj["reasons"]

    proj2 = _theme_momentum_projection(
        {"themeId": "BKXX", "themeName": "未知", "role": "noise"},
        {"factors": [], "qualityFlags": [], "computedAt": 0},
    )
    assert proj2["status"] == "insufficient"
    assert any("insufficient" in r for r in proj2["reasons"])


def test_apply_resonance_final_uses_pure_resonance() -> None:
    analysis = {"decision": {"final": {"signal": "hold", "confidence": 0}}}
    resonance = {"status": "ok", "direction": "buy", "score": 82.0}
    _apply_resonance_final(analysis, resonance)
    assert analysis["decision"]["final"] == {"signal": "buy", "confidence": 82.0}


def test_build_daily_series_feeds_v2() -> None:
    """daily_series 聚合产物可直接喂 compute_theme_momentum_v2（Task 2/3 衔接）。"""
    from backend.analysis.theme.daily_series import build_daily_series

    rows = [
        _theme("BKAI", "人工智能", change=0.05, rank=1),
        _theme("BKBA", "机器人", change=0.01, rank=2),
    ]
    # 25 个不同交易日，日线序列才有 25 个点（满足 20 日窗口）
    frames = [
        _frame(f"2026-06-{10 + i:02d}", "15:00", 1000 + i, [], rows)
        for i in range(25)
    ]
    # 与 _compute_theme_momentum_v2_context 相同的日期补丁：theme 行补 frame 日期
    sector_rows = []
    for f in frames:
        for t in (f.get("hotThemes") or []):
            t = dict(t)
            t.setdefault("tradingDate", f.get("tradingDate"))
            t.setdefault("slotTime", f.get("slotTime"))
            sector_rows.append(t)
    daily = build_daily_series(sector_rows, [])
    result = compute_theme_momentum_v2(list(daily.values()))
    assert "BKAI" in result["factors"]
    assert result["factors"]["BKAI"]["direction"] == "up"
