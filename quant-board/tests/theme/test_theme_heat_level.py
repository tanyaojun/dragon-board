"""heatLevel（0-100 rank 百分位）生成与统一消费规则的锁定测试。

2026-09 heatLevel 落库迁移（design §4.2）：resolve_heat_level 是口径解释的唯一实现，
消费方（trend/momentum/rotation/backtest）不得再各自维护 ">100 视为缺失"启发式。
"""

from __future__ import annotations

from backend.analysis.theme.heat_level import (
    attach_heat_levels,
    heat_caliber_of,
    rank_percentile,
    resolve_heat_level,
)


def test_rank_percentile_bounds() -> None:
    assert rank_percentile(1, 10) == 100.0
    assert rank_percentile(10, 10) == 10.0
    assert rank_percentile(3, 8) == 75.0
    assert rank_percentile(0, 10) is None
    assert rank_percentile(1, 0) is None


def test_attach_heat_levels_marks_missing_explicitly() -> None:
    factors = [
        {"themeId": "AI", "heatScore": 2000, "rank": 1},
        {"themeId": "POWER", "heatScore": None, "rank": 0},
        {"themeId": "BANK", "heatScore": 500, "rank": 2},
    ]
    attach_heat_levels(factors)
    assert [f["heatLevel"] for f in factors] == [100.0, None, 50.0]
    # 降级帧：rank 全 0 → 全部显式 None，不回退 heatScore（2026-09 审计 M3 语义）
    degraded = [{"themeId": "AI", "heatScore": 85, "rank": 0}]
    attach_heat_levels(degraded)
    assert degraded[0]["heatLevel"] is None


def test_heat_caliber_of_reads_factor_version_then_metadata() -> None:
    assert heat_caliber_of({"heatFactorVersion": "theme-market-v2"}) == "theme-market-v2"
    assert heat_caliber_of({"metadata": {"factorVersion": "theme-market-v1"}}) == "theme-market-v1"
    assert heat_caliber_of({"metadata": {}}) == ""
    assert heat_caliber_of({}) == ""
    assert heat_caliber_of({"metadata": "bad"}) == ""


def test_resolve_rule1_heat_level_key_present() -> None:
    # key 存在：数值直接用（含 SQL varchar 回读的字符串数字）
    assert resolve_heat_level({"heatLevel": 96.3}) == 96.3
    assert resolve_heat_level({"heatLevel": "96.3"}) == 96.3
    # 显式 None / 非法值 = 诚实缺失，不回退 heatScore（M3：≤100 绝对值是冷题材人气总和）
    assert resolve_heat_level({"heatLevel": None, "heatScore": 85}) is None
    assert resolve_heat_level({"heatLevel": "abc", "heatScore": 85}) is None
    # 历史浏览器档位标签字符串（"热门"）不是数值，按缺失（评审 L2 混合行用例）
    assert resolve_heat_level({"heatLevel": "热门", "heatScore": 85}) is None


def test_resolve_rule2_missing_key_falls_back_by_caliber() -> None:
    assert resolve_heat_level({"heatScore": 85}) == 85.0  # 未标记：v1 语义回退（残留歧义 design §4.2 显式接受）
    assert resolve_heat_level({"heatScore": 85, "metadata": {"factorVersion": "theme-market-v1"}}) == 85.0
    assert resolve_heat_level({"heatScore": 85, "heatFactorVersion": "theme-market-v1"}) == 85.0
    # v2 标记：绝对值口径不回退（M1 边界窗口消除）
    assert resolve_heat_level({"heatScore": 85, "metadata": {"factorVersion": "theme-market-v2"}}) is None
    assert resolve_heat_level({"heatScore": 85, "heatFactorVersion": "theme-market-v2"}) is None


def test_resolve_rule3_absolute_heat_always_missing() -> None:
    assert resolve_heat_level({"heatScore": 2000}) is None
    assert resolve_heat_level({"heatScore": 2000, "metadata": {"factorVersion": "theme-market-v1"}}) is None
    assert resolve_heat_level({}) is None
    assert resolve_heat_level({"heatScore": "abc"}) is None


def test_resolve_clamps_to_0_100() -> None:
    assert resolve_heat_level({"heatLevel": 120}) == 100.0
    assert resolve_heat_level({"heatLevel": -5}) == 0.0
    assert resolve_heat_level({"heatScore": -5, "metadata": {"factorVersion": "theme-market-v1"}}) == 0.0
