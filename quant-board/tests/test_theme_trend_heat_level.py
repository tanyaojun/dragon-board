"""trend.py 适配 KPL 热度口径（heatScore 绝对值 / 缺失为 None）的行为锁定。

2026-09 热度口径切换（theme-market-v2）后：
- heatScore 是 KPL 人气总和（绝对值，可为数千），不再是 0-100 归一分；
- KPL 缺失时 heatScore 为 None（fail-visible），行情侧因子必须保留；
- role/信号/贡献度的热度消费点改用 heatLevel（rank 百分位相对分 0-100）。
"""

from __future__ import annotations

from backend.analysis.theme.trend import ThemeTrendPythonEngine, _theme_context_frames, _ts_heat_level


def _context_frame(*, kpl_hots: dict | None = None) -> dict:
    context: dict = {
        "mappingVersion": "theme-context-test",
        "themes": [
            {"id": "AI", "name": "人工智能"},
            {"id": "POWER", "name": "电力"},
        ],
        "themeStocks": {"AI": ["600001", "600002"], "POWER": ["600003"]},
        "stockThemes": {"600001": ["AI"], "600002": ["AI"], "600003": ["POWER"]},
        "funds": {},
        "previousFactors": {},
        "rotationAnalysis": {},
        "correlations": {},
    }
    if kpl_hots is not None:
        context["kplHots"] = kpl_hots
    return {
        "snapshotId": "snap_ctx_1",
        "timestamp": 1785807000000,
        "tradingDate": "2026-09-02",
        "themeContext": context,
        "stocks": [
            {"code": "600001", "change": 6.0},
            {"code": "600002", "change": 3.0},
            {"code": "600003", "change": 2.0},
        ],
    }


def test_replay_survives_missing_kpl_hots() -> None:
    """KPL 人气缺失：factors 不被 rankEligible 连带过滤，signals 不因 heatScore=None 崩溃。"""
    result = ThemeTrendPythonEngine().replay([_context_frame()])

    assert result["factors"], "KPL 缺失不应清空全部题材因子"
    assert all(factor["heatScore"] is None for factor in result["factors"])
    assert all(
        "kpl_hotness_unavailable" in (factor.get("qualityFlags") or [])
        for factor in result["factors"]
    )
    assert result["signals"], "heatScore=None 不应让信号构建崩溃"
    assert result["exposures"]


def test_heat_missing_stock_with_positive_change_is_not_noise() -> None:
    """热度缺失 ≠ 热度低：change>0 且无龙头/联动信息的股票不应被误判为 noise。"""
    _, exposures = _theme_context_frames(_context_frame())

    exposure = next(item for item in exposures if item["code"] == "600002")
    assert exposure["role"] != "noise"


def test_heat_level_is_rank_percentile_when_kpl_available() -> None:
    """KPL 可用时 factor 附带 heatLevel（rank 百分位 0-100 相对分），heatScore 保持绝对值。"""
    kpl_hots = {"AI": {"600001": 1200, "600002": 800}, "POWER": {"600003": 500}}
    factors, _ = _theme_context_frames(_context_frame(kpl_hots=kpl_hots))

    ai = next(item for item in factors if item["themeId"] == "AI")
    power = next(item for item in factors if item["themeId"] == "POWER")
    assert ai["heatScore"] == 2000  # 绝对值口径不变
    assert ai["rank"] == 1
    assert ai["heatLevel"] == 100
    assert power["rank"] == 2
    assert power["heatLevel"] == 50


def test_sector_absolute_heat_does_not_inflate_exposure_weight() -> None:
    """sector rows 落库的新口径绝对值 heatScore（>100）不伪装成 0-100 满分权重。"""
    frames = [
        {
            "snapshotId": "snap_abs",
            "timestamp": 100,
            "tradingDate": "2026-09-02",
            "stocks": [
                {
                    "code": "000001",
                    "name": "龙头科技",
                    "mainTheme": "人工智能",
                    "themeRole": "leader",
                    "themeContribution": 18,
                }
            ],
            "sectors": [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "rank": 1,
                    "heatScore": 2000,
                    "momentumScore": 84,
                    "breadthScore": 78,
                    "fundScore": 82,
                    "leadershipScore": 88,
                    "correlationScore": 74,
                    "crowdingRisk": 32,
                    "persistenceScore": 80,
                    "rotationState": "mainline",
                }
            ],
        }
    ]

    result = ThemeTrendPythonEngine().replay(frames)

    exposure = result["exposures"][0]
    # role_score 100*0.45 + contribution 18*2.5 + 热度缺失按 0 → 90，而非 clamp 天花板 100
    assert exposure["exposureWeight"] == 90
    signal = result["signals"][0]
    assert 0 <= signal["score"] <= 100


def test_ts_heat_level_respects_explicit_none_heat_level() -> None:
    """降级帧（rank 全 0）heatLevel 显式 None：不回退 heatScore，
    避免 ≤100 绝对值（冷题材人气总和）被反向解释成高相对分（2026-09 审计 M3）。"""
    assert _ts_heat_level({"heatLevel": None, "heatScore": 85}) is None
    # sector rows 路径（无 heatLevel key）仍回退：0-100 落库值有效
    assert _ts_heat_level({"heatScore": 85}) == 85.0
    # >100 绝对值仍视为缺失
    assert _ts_heat_level({"heatScore": 2000}) is None


def test_ts_heat_level_non_numeric_is_missing() -> None:
    """非数值热度按缺失（None），不伪装成 0 相对分（2026-09 审计 L2）。"""
    assert _ts_heat_level({"heatLevel": "abc"}) is None
    assert _ts_heat_level({"heatScore": "abc"}) is None


def test_sector_non_numeric_heat_stays_missing() -> None:
    """sector rows 非数值 heatScore 不被 _num 伪装成 0（2026-09 审计 L2）。"""
    frames = [
        {
            "snapshotId": "snap_bad_heat",
            "timestamp": 100,
            "tradingDate": "2026-09-02",
            "stocks": [],
            "sectors": [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "rank": 1,
                    "heatScore": "abc",
                    "momentumScore": 50,
                    "breadthScore": 50,
                    "fundScore": 50,
                    "leadershipScore": 50,
                    "correlationScore": 50,
                    "crowdingRisk": 30,
                    "persistenceScore": 50,
                }
            ],
        }
    ]

    result = ThemeTrendPythonEngine().replay(frames)

    assert result["factors"], "sector 行不应被丢弃"
    assert result["factors"][0]["heatScore"] is None
