# -*- coding: utf-8 -*-
"""技术信号五因子决策合同锁（2026-09-13 阶段 21.7 五因子化 → 阶段 22.8 权重重定义）。

当前默认 = 阶段 22 p2_aggressive 实证口径 0.06/0.04/0.24/0.29/0.37（用户 2026-09-13
决策落默认；来源：evaluate_ts_factor_weights 三窗两层实证 + Track 2 判定卡
PASS_CANDIDATE，oos 双窗同向 +30.0%/+28.9%，详见长测计划 §22）。

历史沿革：阶段 21.7 五因子落默认 0.24/0.20/0.16/0.20/0.20（= 阶段 20.4 ma_join
设计值归一化口径）；阶段 22 重定义为实证口径。

MACD 完整保留：权重位、共识票、trend_buy OR 链、risk histogram、
观察字段（technical.macd）零改动；maCross 缺键的旧调用方/测试夹具不抛错。
"""
from __future__ import annotations

import pytest

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.engine.runtime import compose_decision

WEIGHT_FIELDS = ("directionWeight", "accelerationWeight", "crossWeight", "macdWeight", "maWeight")

# 与 test_ranktrend_ma_cross_factor.py 同构的金叉序列（本地定义，避免跨测试模块导入）
GOLDEN_SERIES = [10.0] * 21 + [95.0]  # len 22 = maSlow(20)+1，末帧 fast 18.5 > slow 14.25


# ---------------------------------------------------------------------------
# 默认配置：五权重归一化 + 落默认 = 实证口径锚
# ---------------------------------------------------------------------------


def test_default_config_ma_weight_enabled() -> None:
    """默认 maWeight=0.37（阶段 22 p2_aggressive 实证口径），MACD 权重位 0.29。"""
    c = RankTrendConfig()
    assert c.maWeight == pytest.approx(0.37)
    assert c.macdWeight == pytest.approx(0.29)


def test_default_config_weights_normalized_to_one() -> None:
    """__post_init__ 归一化：直接构造权重和恒=1（0.06/0.04/0.24/0.29/0.37）。"""
    c = RankTrendConfig()
    total = sum(getattr(c, f) for f in WEIGHT_FIELDS)
    assert total == pytest.approx(1.0)
    assert c.directionWeight == pytest.approx(0.06)
    assert c.accelerationWeight == pytest.approx(0.04)
    assert c.crossWeight == pytest.approx(0.24)
    assert c.macdWeight == pytest.approx(0.29)
    assert c.maWeight == pytest.approx(0.37)


def test_stage22_p2_patch_equals_default_config() -> None:
    """落默认 = 实证口径锚：阶段 22 p2_aggressive 五权重（和=1）patch 与默认构造
    逐位一致（from_patch 归一化幂等）。"""
    p2 = RankTrendConfig.from_patch(
        {
            "directionWeight": 0.06,
            "accelerationWeight": 0.04,
            "crossWeight": 0.24,
            "macdWeight": 0.29,
            "maWeight": 0.37,
        }
    )
    default = RankTrendConfig()
    for field in WEIGHT_FIELDS:
        assert getattr(p2, field) == pytest.approx(getattr(default, field)), field


def test_legacy_ma_join_patch_normalization_unchanged() -> None:
    """历史口径锚（阶段 20.4 ma_join 设计值 1.25 归一化）不随落默认漂移：
    归一化只看 patch 自身和，与当前默认无关 → 0.24/0.20/0.16/0.20/0.20。"""
    joined = RankTrendConfig.from_patch(
        {
            "directionWeight": 0.3,
            "accelerationWeight": 0.25,
            "crossWeight": 0.2,
            "macdWeight": 0.25,
            "maWeight": 0.25,
        }
    )
    assert joined.directionWeight == pytest.approx(0.24)
    assert joined.accelerationWeight == pytest.approx(0.20)
    assert joined.crossWeight == pytest.approx(0.16)
    assert joined.macdWeight == pytest.approx(0.20)
    assert joined.maWeight == pytest.approx(0.20)


def test_patch_equal_to_default_is_noop() -> None:
    """归一化幂等锚：patch 值与默认相同（权重和已=1）时归一化无操作，结果=默认构造。

    注意 from_patch 是"替换+归一化"的相对语义——以归一化后的值再 patch 一次会得到
    不同基座下的结果（非幂等场景），故幂等锚只在"和已=1"时成立。
    """
    once = RankTrendConfig.from_patch({"maWeight": 0.37})
    default = RankTrendConfig()
    for field in WEIGHT_FIELDS:
        assert getattr(once, field) == pytest.approx(getattr(default, field)), field


# ---------------------------------------------------------------------------
# compose_decision：MA 第 5 分量参与合成（MACD 项与共识票保留）
# ---------------------------------------------------------------------------


def _technical(macd_cross: str = "none", macd_raw: float = 0.0, ma: dict | None = None) -> dict:
    return {
        "signals": {
            "direction": {"signal": "hold", "confidence": 0.5, "score": 0.0},
            "acceleration": {"signal": "hold", "confidence": 0.5, "score": 0.0},
            "zeroCross": {"signal": "hold", "confidence": 0.5, "score": 0.0},
        },
        "macd": {"cross": macd_cross, "rawScore": macd_raw},
        "maCross": ma if ma is not None else {"cross": "none", "rawScore": 0.0},
    }


def _risk() -> dict:
    return {
        "overheat": {"severity": 0.0},
        "divergence": {"severity": 0.0},
        "synergy": 0.0,
        "pressure": 0.0,
    }


def _compose(technical: dict) -> dict:
    config = RankTrendConfig()
    return compose_decision(technical, {"stage": "expansion"}, _risk(), config)


def test_compose_decision_ma_contributes_to_combined() -> None:
    """四信号全 hold + MA golden(rawScore=1) → combined == 归一化 maWeight(0.37)。"""
    result = _compose(_technical(ma={"cross": "golden", "rawScore": 1.0}))
    assert result["base"]["combinedScore"] == pytest.approx(0.37)


def test_compose_decision_ma_death_negative() -> None:
    """MA death(rawScore=-1) → combined == -0.37（负向贡献对称）。"""
    result = _compose(_technical(ma={"cross": "death", "rawScore": -1.0}))
    assert result["base"]["combinedScore"] == pytest.approx(-0.37)


def test_compose_decision_macd_component_retained() -> None:
    """MACD 分量保留：MACD golden(rawScore=1) → combined == 归一化 macdWeight(0.29)。"""
    result = _compose(_technical(macd_cross="golden", macd_raw=1.0))
    assert result["base"]["combinedScore"] == pytest.approx(0.29)


def test_compose_decision_legacy_technical_without_macross_key() -> None:
    """旧调用方/测试夹具 technical 缺 maCross 键：按无信号处理不抛错（阶段 17 兼容合同）。"""
    technical = _technical()
    technical.pop("maCross")
    result = _compose(technical)
    assert result["base"]["combinedScore"] == pytest.approx(0.0)


def test_compose_decision_baseline_hold_unchanged() -> None:
    """全 hold 零 rawScore：combined=0、base=hold（与四因子时代行为一致）。"""
    result = _compose(_technical())
    assert result["base"]["signal"] == "hold"
    assert result["base"]["combinedScore"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 权重不变量校验（2026-09-13 review 跟进：直接构造 fail-fast）
# ---------------------------------------------------------------------------


def test_direct_construction_with_legacy_four_weight_dict_raises() -> None:
    """历史陷阱锚：旧四权重全量字典直接构造（缺 maWeight，和=1.0≠1？不，和=1 但缺第 5 项）——
    旧字典和=1.0 但只含 4 权重 → maWeight 取默认 0.37 → 和=1.37 ≠ 1 → 必须拒绝，
    否则 combinedScore 静默放大。自定义权重应走 from_patch（自动归一化）。"""
    legacy = dict(
        directionWeight=0.3,
        accelerationWeight=0.25,
        crossWeight=0.2,
        macdWeight=0.25,
    )
    with pytest.raises(ValueError, match="from_patch"):
        RankTrendConfig(**legacy)


def test_direct_construction_negative_weight_raises() -> None:
    """负权重直接构造：拒绝（负值会静默扭曲其余权重比例）。"""
    with pytest.raises(ValueError, match="不能为负"):
        RankTrendConfig(maWeight=-0.1, directionWeight=0.34)


def test_from_patch_negative_weight_raises() -> None:
    """from_patch 负权重：拒绝（setattr 绕过 __post_init__，需在归一化前显式校验）。"""
    with pytest.raises(ValueError, match="不能为负"):
        RankTrendConfig.from_patch({"maWeight": -0.1})


def test_direct_construction_all_zero_weights_allowed() -> None:
    """全 0 哨兵：五权重全 0 = 显式全关闭，直接构造合法（与 from_patch 全 0 patch 行为一致）。"""
    c = RankTrendConfig(
        directionWeight=0.0,
        accelerationWeight=0.0,
        crossWeight=0.0,
        macdWeight=0.0,
        maWeight=0.0,
    )
    assert sum(getattr(c, f) for f in WEIGHT_FIELDS) == 0.0


def test_analyze_technical_emits_ma_cross_even_when_ma_weight_zero() -> None:
    """观察字段与决策门控解耦锚：maWeight=0（关闭决策参与）时 analyze_technical
    仍无条件产出 maCross 观察字段——前端徽章/观察行不随决策关闭消失。"""
    from backend.analysis.ranktrend.engine import analyze_technical

    technical = analyze_technical(GOLDEN_SERIES, RankTrendConfig.from_patch({"maWeight": 0.0}))
    assert technical["maCross"]["cross"] == "golden"
    assert technical["maCross"]["rawScore"] == 1.0
