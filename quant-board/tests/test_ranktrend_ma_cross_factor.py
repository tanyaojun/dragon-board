"""MA 交叉因子测试（2026-09-12 阶段 17，four-dim-algorithm-research 流程步骤 1）。

背景：技术结构四因子（方向/加速度/零线交叉/MACD）之外，用户提出补均线 MA 因子
（参数定 10/20）。设计：排名百分位序列上的 MA10×MA20 金叉/死叉（与 MACD 同输入、
同二值交叉参与语义），两个接线点默认全关——compose_decision 第 5 分量 maWeight=0、
trend_buy OR 链 maCrossTrendBuy=False——golden 逐位不漂移。

本测试验证：默认值断言、交叉检测（金叉/死叉/样本不足 fail-visible）、参数生效、
接线生效（maWeight>0 / maCrossTrendBuy=True）、默认关闭时决策逐位不变。
"""

from __future__ import annotations

import pytest

from backend.analysis.ranktrend.engine import (
    RankTrendConfig,
    analyze_technical,
    calculate_ma_cross,
    compose_analysis_candidate_tier,
    compose_decision,
)


# ── 构造序列（手工验算）：金叉 = 长期 10 平台后单点跳升；死叉 = 长期 50 平台后单点跳水 ──
GOLDEN_SERIES = [10.0] * 21 + [95.0]  # len 22 = maSlow(20)+1，末帧 fast 18.5 > slow 14.25，前帧 10==10
DEATH_SERIES = [50.0] * 21 + [5.0]  # 末帧 fast 45.5 < slow 47.75，前帧 50==50


def test_ma_cross_fields_default_to_closed_state() -> None:
    """新字段默认值：周期 10/20（用户指定）、权重 0、trend_buy 不参与（golden 不漂移）。"""
    c = RankTrendConfig()
    assert c.maFastPeriod == 10
    assert c.maSlowPeriod == 20
    assert c.maWeight == 0.0
    assert c.maCrossTrendBuy is False


def test_ma_cross_detects_golden_and_death() -> None:
    golden = calculate_ma_cross(GOLDEN_SERIES, RankTrendConfig())
    assert golden["cross"] == "golden"
    assert golden["rawScore"] == 1.0
    assert golden["state"] == "bull"
    assert golden["fast"] == pytest.approx(18.5)
    assert golden["slow"] == pytest.approx(14.25)

    death = calculate_ma_cross(DEATH_SERIES, RankTrendConfig())
    assert death["cross"] == "death"
    assert death["rawScore"] == -1.0
    assert death["state"] == "bear"


def test_ma_cross_flat_series_has_no_cross() -> None:
    flat = calculate_ma_cross([30.0] * 25, RankTrendConfig())
    assert flat["cross"] == "none"
    assert flat["rawScore"] == 0.0
    assert flat["state"] == "flat"
    assert flat["fast"] == pytest.approx(30.0)


def test_ma_cross_insufficient_samples_fail_visible() -> None:
    """样本不足（len < maSlowPeriod）→ fast/slow=None 不伪造 0；len==maSlow 无前值不判交叉。"""
    short = calculate_ma_cross([10.0] * 18 + [95.0], RankTrendConfig())
    assert short["fast"] is None
    assert short["slow"] is None
    assert short["cross"] == "none"
    assert short["rawScore"] == 0.0
    assert short["state"] == "unknown"

    no_prev = calculate_ma_cross([10.0] * 20, RankTrendConfig())
    assert no_prev["fast"] is not None and no_prev["slow"] is not None
    assert no_prev["cross"] == "none"


def test_ma_cross_period_parameters_take_effect() -> None:
    """周期参数化生效：同一序列 fast=5/slow=10 可判金叉，默认 10/20 样本不足。"""
    series = [10.0] * 11 + [95.0]  # len 12：默认 10/20 不足，5/10 可判
    fast_config = RankTrendConfig.from_patch({"maFastPeriod": 5, "maSlowPeriod": 10})
    result = calculate_ma_cross(series, fast_config)
    assert result["cross"] == "golden"
    assert calculate_ma_cross(series, RankTrendConfig())["cross"] == "none"


def test_ma_cross_periods_are_repaired_and_guarded() -> None:
    """maSlow <= maFast 自动修正（镜像 MACD）；非法周期拒绝。"""
    c = RankTrendConfig.from_patch({"maFastPeriod": 25})
    assert c.maFastPeriod == 25 and c.maSlowPeriod == 26
    with pytest.raises(ValueError):
        RankTrendConfig.from_patch({"maFastPeriod": 0})


def test_ma_cross_runtime_guard_rejects_invalid_direct_construction() -> None:
    """直接构造 RankTrendConfig 绕过 from_patch 校验：calculate_ma_cross 运行期复检
    fail-fast 抛 ValueError（防 -0 切片=全列表、fast>slow 恒 flat 的静默空因子）。"""
    # fast=0：percentiles[-0:] 等价 [0:]（整列表），语义错但不崩——必须拒绝
    with pytest.raises(ValueError):
        calculate_ma_cross(GOLDEN_SERIES, RankTrendConfig(maFastPeriod=0))
    # fast >= slow：from_patch 会静默修复，直接构造不修复 → 运行期拒绝
    with pytest.raises(ValueError):
        calculate_ma_cross(GOLDEN_SERIES, RankTrendConfig(maFastPeriod=25))
    # 默认构造（10/20 合法）不受影响
    calculate_ma_cross(GOLDEN_SERIES, RankTrendConfig())


def test_analyze_technical_exposes_ma_cross() -> None:
    """analyze_technical 输出新增 maCross 字段（additive，不改变既有键）。"""
    technical = analyze_technical(GOLDEN_SERIES, RankTrendConfig())
    assert technical["maCross"]["cross"] == "golden"
    for legacy_key in ("movingAverage", "macd", "signals", "momentumScore", "momentumProfile"):
        assert legacy_key in technical


def _technical_dict(with_ma: bool) -> dict:
    technical = {
        "signals": {
            "direction": {"signal": "buy", "confidence": 60, "score": 0.5},
            "acceleration": {"signal": "hold", "confidence": 50, "score": 0.0},
            "zeroCross": {"signal": "hold", "confidence": 50, "score": 0.0},
        },
        "macd": {"cross": "none", "rawScore": 0.0},
        "momentumProfile": {"short": 5.0, "mid": 5.0, "long": 0.0, "acceleration": 1.0},
    }
    if with_ma:
        technical["maCross"] = {"fast": 18.5, "slow": 14.25, "state": "bull", "cross": "golden", "rawScore": 1.0}
    return technical


_CYCLE = {"stage": "expansion", "decision": {}}
_RISK = {
    "pressure": 0.1,
    "divergence": {"severity": 0.1},
    "overheat": {"severity": 0.1},
    "synergy": 0.0,
}


def test_compose_decision_zero_drift_when_ma_disabled() -> None:
    """默认 maWeight=0：technical 含/不含 maCross 的决策合成逐位一致（golden 不漂移）。"""
    config = RankTrendConfig()
    with_ma = compose_decision(_technical_dict(with_ma=True), _CYCLE, _RISK, config)
    without_ma = compose_decision(_technical_dict(with_ma=False), _CYCLE, _RISK, config)
    assert with_ma["base"]["combinedScore"] == without_ma["base"]["combinedScore"]
    assert with_ma["base"]["signal"] == without_ma["base"]["signal"]


def test_compose_decision_ma_weight_joins_as_fifth_component() -> None:
    """maWeight>0：MA 金叉进决策合成，且 from_patch 归一化 5 权重和为 1。

    权重归一化 [0.3,0.25,0.2,0.25,0.25]/1.25=[0.24,0.2,0.16,0.2,0.2]：
    combined = 0.5*0.24 + 0*0.2 + 0*0.16 + 0*0.2 + 1*0.2 = 0.32；
    buy_count 由 1（仅 direction）增至 2（+MA），越过 decisionMinAgreement=2 → buy。
    """
    config = RankTrendConfig.from_patch({"maWeight": 0.25})
    assert config.maWeight == pytest.approx(0.2)
    assert config.directionWeight == pytest.approx(0.24)
    result = compose_decision(_technical_dict(with_ma=True), _CYCLE, _RISK, config)
    assert result["base"]["combinedScore"] == pytest.approx(0.32)
    assert result["base"]["signal"] == "buy"
    # 对照：同一 technical 在默认配置下只有 1 个 buy 分量 → hold
    legacy = compose_decision(_technical_dict(with_ma=True), _CYCLE, _RISK, RankTrendConfig())
    assert legacy["base"]["signal"] == "hold"


def test_candidate_tier_ma_cross_trend_buy_wiring() -> None:
    """maCrossTrendBuy=False（默认）：仅 MA 金叉不触发 trend_buy，A_MAIN 不放行；
    True 时 MA 金叉进 trend_buy OR 链 → A_MAIN 放行（expansion+动量+环境门全过）。"""
    technical = {
        "signals": {
            "direction": {"signal": "hold"},
            "acceleration": {"signal": "hold"},
            "zeroCross": {"signal": "hold"},
        },
        "macd": {"cross": "none"},
        "maCross": {"cross": "golden", "rawScore": 1.0},
        "momentumProfile": {"short": 5.0, "mid": 5.0, "long": 0.0, "acceleration": 1.0},
    }
    regime = {"state": "normal", "score": 0, "reasons": []}
    default = compose_analysis_candidate_tier(technical, _CYCLE, _RISK, regime, RankTrendConfig())
    assert default["candidateTier"] != "A_MAIN"

    enabled_config = RankTrendConfig.from_patch({"maCrossTrendBuy": True})
    enabled = compose_analysis_candidate_tier(technical, _CYCLE, _RISK, regime, enabled_config)
    assert enabled["candidateTier"] == "A_MAIN"


def test_candidate_tier_tolerates_missing_ma_cross_field() -> None:
    """旧调用方/测试夹具的 technical 无 maCross 键：默认与开启配置均按无信号处理，不抛错。"""
    technical = {
        "signals": {"direction": {"signal": "hold"}, "acceleration": {"signal": "hold"}},
        "macd": {"cross": "none"},
        "momentumProfile": {"short": 5.0, "mid": 5.0, "long": 0.0, "acceleration": 1.0},
    }
    regime = {"state": "normal", "score": 0, "reasons": []}
    enabled_config = RankTrendConfig.from_patch({"maCrossTrendBuy": True})
    result = compose_analysis_candidate_tier(technical, _CYCLE, _RISK, regime, enabled_config)
    assert result["candidateTier"] != "A_MAIN"
