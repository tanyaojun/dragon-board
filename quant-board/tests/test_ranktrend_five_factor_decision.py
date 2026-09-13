# -*- coding: utf-8 -*-
"""技术信号五因子化：MA 作为第 5 决策分量正式落默认（2026-09-13 阶段 21.7）。

用户决策（阶段 21.7 修订，取代 §21.2 参数替换）：TS 归一化合同扩展为 5 权重，
技术信号 = 四因子 + MA 五因子结构；py 默认 maWeight 0→0.25，并新增 __post_init__
权重归一化（任何构造路径权重和恒=1，直接构造与 from_patch 行为统一）。

核心锚：落默认口径必须与阶段 20.4/20.5 的 ma_join 实证口径逐位一致——
from_patch({"maWeight": 0.25}) 归一化后 0.24/0.20/0.16/0.20/0.20。

MACD 完整保留：权重位（0.25）、共识票、trend_buy OR 链、risk histogram、
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
    """默认 maWeight=0.2（设计值 0.25 五权重归一化后），MACD 权重位保留同值。"""
    c = RankTrendConfig()
    assert c.maWeight == pytest.approx(0.2)
    assert c.macdWeight == pytest.approx(0.2)


def test_default_config_weights_normalized_to_one() -> None:
    """__post_init__ 归一化：直接构造权重和恒=1（0.24/0.20/0.16/0.20/0.20）。"""
    c = RankTrendConfig()
    total = sum(getattr(c, f) for f in WEIGHT_FIELDS)
    assert total == pytest.approx(1.0)
    assert c.directionWeight == pytest.approx(0.24)
    assert c.accelerationWeight == pytest.approx(0.20)
    assert c.crossWeight == pytest.approx(0.16)
    assert c.macdWeight == pytest.approx(0.20)
    assert c.maWeight == pytest.approx(0.20)


def test_ma_join_patch_equals_default_config() -> None:
    """落默认 = 实证口径锚：全 raw 设计值 patch（阶段 20.4 ma_join trial 的展开形式）
    经 from_patch 归一化后与默认构造五权重逐位一致。"""
    joined = RankTrendConfig.from_patch(
        {
            "directionWeight": 0.3,
            "accelerationWeight": 0.25,
            "crossWeight": 0.2,
            "macdWeight": 0.25,
            "maWeight": 0.25,
        }
    )
    default = RankTrendConfig()
    for field in WEIGHT_FIELDS:
        assert getattr(joined, field) == pytest.approx(getattr(default, field)), field


def test_patch_equal_to_default_is_noop() -> None:
    """归一化幂等锚：patch 值与默认相同（权重和已=1）时归一化无操作，结果=默认构造。

    注意 from_patch 是"替换+归一化"的相对语义——以归一化后的值再 patch 一次会得到
    不同基座下的结果（非幂等场景），故幂等锚只在"和已=1"时成立。
    """
    once = RankTrendConfig.from_patch({"maWeight": 0.2})
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
    """四信号全 hold + MA golden(rawScore=1) → combined == 归一化 maWeight(0.2)。"""
    result = _compose(_technical(ma={"cross": "golden", "rawScore": 1.0}))
    assert result["base"]["combinedScore"] == pytest.approx(0.20)


def test_compose_decision_ma_death_negative() -> None:
    """MA death(rawScore=-1) → combined == -0.2（负向贡献对称）。"""
    result = _compose(_technical(ma={"cross": "death", "rawScore": -1.0}))
    assert result["base"]["combinedScore"] == pytest.approx(-0.20)


def test_compose_decision_macd_component_retained() -> None:
    """MACD 分量保留：MACD golden(rawScore=1) → combined == 归一化 macdWeight(0.2)。"""
    result = _compose(_technical(macd_cross="golden", macd_raw=1.0))
    assert result["base"]["combinedScore"] == pytest.approx(0.20)


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
    旧字典和=1.0 但只含 4 权重 → maWeight 取默认 0.2 → 和=1.2 ≠ 1 → 必须拒绝，
    否则 combinedScore 静默放大 20%。自定义权重应走 from_patch（自动归一化）。"""
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
