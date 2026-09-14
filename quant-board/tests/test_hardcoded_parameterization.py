# -*- coding: utf-8 -*-
"""五维信号硬编码参数化锚点测试（2026-09-14，阶段 23 追问：硬编码行为全面 config 化）。

范围（清点 2026-09-14，六区域）：
1. synergy 总档：档位强度 _VOTE_STRENGTH（S/A/B/C/D/E）+ cs 档位强度 _CS_STRENGTH（A/B/C/D）；
2. 量价：涨跌幅档位边界、volume score 上涨/下跌阶梯系数、fund score 公式系数、成交额加分；
3. 风险：overheat/divergence 加减分阶梯、hot_attention 阈值、阶段乘数、signal 阈值、
   risk synergy 双门、regime 五因子打分系数与状态阈值；
4. 技术信号 fallback：方向/加速度/零线阈值、合成权重、归一化尺度；
5. 共振 label 阈值（展示）；
6. 展示面：STAGE_FITNESS、compose_strategy reasons 阈值。

纪律：默认值 = 参数化前硬编码值（golden 不漂移，与 b2b3bc7/ba6e301 同模式）；
全部登记为结构参数（未扫描，无自由度消耗）；新 list 字段同步 _STRATEGY_LIST_KEYS。
"""
from __future__ import annotations

import pytest

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.ranking.volume_price import (
    _direction_bucket,
    _synergy_tier,
    compute_volume_price_score,
)
from backend.analysis.ranktrend.trend.risk import REGIME_STRONG_SCORE, analyze_risk, market_regime
from backend.analysis.ranktrend.trend.technical import fallback_signals

# ---------------------------------------------------------------------------
# 默认值锚（全部新字段 = 参数化前硬编码值；漂移即红）
# ---------------------------------------------------------------------------

EXPECTED_DEFAULTS: dict[str, object] = {
    # 批 1：synergy 总档档位强度
    "tierSynergyVoteStrengths": [1.2, 1.0, 0.8, 0.5, 1.0, 1.0],  # S/A/B/C/D/E
    "tierSynergyCsStrengths": [1.0, 0.5, -0.5, -1.0],  # A/B/C/D
    # 批 2：量价
    "volumePriceDirectionThresholds": [7.0, 5.0, 3.0, 2.0, 1.0, 0.5],
    "volumeScoreUpShrinkLimitUp": 8.0,
    "volumeScoreUpShrinkBase": 10.0,
    "volumeScoreUpShrinkSlope": 15.0,
    "volumeScoreUpCap": 15.0,
    "volumeScoreUpMildLimitUp": 10.0,
    "volumeScoreUpMildNormal": 5.0,
    "volumeScoreUpNormalBase": 10.0,
    "volumeScoreUpNormalSlope": 5.0,
    "volumeScoreUpOverBase": 15.0,
    "volumeScoreUpOverSlope": 10.0,
    "volumeScoreUpOverFloor": 5.0,
    "volumeScoreUpExcessBase": 15.0,
    "volumeScoreUpExcessSlope": 10.0,
    "volumeScoreUpExcessCap": 20.0,
    "volumeScoreDownOverMild": -20.0,
    "volumeScoreDownShrink": -5.0,
    "volumeScoreDownLimitDown": -15.0,
    "volumeScoreDownNormal": -10.0,
    "fundScoreCap": 15.0,
    "fundScoreDumpBase": 10.0,
    "fundScoreDumpSlope": 0.5,
    "fundScoreNetSlope": 3.0,
    "fundScoreInOutStep": 5.0,
    "amountScoreStep": 5.0,
    # 批 3：风险
    "riskOverheatPercentileMin": 70.0,
    "riskOverheatPercentileSlope": 1.2,
    "riskOverheatShockSlope": 12.0,
    "riskOverheatVelocitySlope": 1.5,
    "riskOverheatVelocityCap": 15.0,
    "riskOverheatAccelSlope": 4.0,
    "riskOverheatAccelCap": 20.0,
    "riskOverheatMacdSlope": 15.0,
    "riskOverheatMacdCap": 10.0,
    "riskOverheatDirectionBuyBonus": 5.0,
    "riskOverheatAccelMissPenalty": 10.0,
    "riskOverheatZeroCrossSellPenalty": 18.0,
    "riskHotAttentionPercentileMin": 70.0,
    "riskDivergenceHotBonus": 10.0,
    "riskDivergenceHotOutflowPenalty": 25.0,
    "riskDivergenceHotDumpPenalty": 18.0,
    "riskDivergenceVolumeHighMin": 2.0,
    "riskDivergenceVolumeOutflowPenalty": 15.0,
    "riskDivergenceVolumeDumpPenalty": 8.0,
    "riskDivergenceShockMin": 0.8,
    "riskDivergenceShockOutflowPenalty": 12.0,
    "riskDivergenceStageOutflowPenalty": 12.0,
    "riskDivergenceInflowRelief": 15.0,
    "riskDivergenceDumpRelief": 10.0,
    "riskDivergenceShrinkVolumeMax": 1.5,
    "riskDivergenceShrinkInflowRelief": 6.0,
    "riskOverheatStageMultipliers": [0.3, 0.55, 0.85, 1.0, 0.3],  # ignition/expansion/crowded/reversal/cooling
    "riskDivergenceStageMultipliers": [0.35, 0.65, 0.9, 1.0, 0.35],
    "riskOverheatSellMin": 70.0,
    "riskOverheatHoldMin": 45.0,
    "riskDivergenceSellMin": 65.0,
    "riskDivergenceHoldMin": 40.0,
    "riskSynergyOverheatSevMin": 0.65,
    "riskSynergyDivergenceSevMin": 0.6,
    "regimeStageAdjust": [8.0, 5.0, 0.0, -6.0, -8.0],  # 高潮/发酵/启动/退潮/冰点
    "regimeStrongScore": 70.0,
    "regimeNormalScore": 50.0,
    "regimeWeakScore": 30.0,
    "regimeLimitUpChange": 9.8,
    "regimeLimitUpBaseShare": 0.08,
    "regimeRiskHighAdjust": -8.0,
    "regimeRiskLowAdjust": 3.0,
    "regimeBaseScore": 50.0,
    "regimeUpShareSlope": 40.0,
    "regimeUpShareFloor": -20.0,
    "regimeUpShareCap": 20.0,
    "regimeLimitUpSlope": 80.0,
    "regimeLimitUpFloor": -15.0,
    "regimeLimitUpCap": 25.0,
    "regimeActiveVolumeMin": 1.2,
    "regimeActiveBaseShare": 0.35,
    "regimeActiveSlope": 10.0,
    "regimeActiveFloor": -5.0,
    "regimeActiveCap": 7.0,
    "regimeMoneySlope": 20.0,
    "regimeMoneyFloor": -10.0,
    "regimeMoneyCap": 10.0,
    # 批 4：技术 fallback
    "fallbackDirectionThreshold": 0.2,
    "fallbackAccelThreshold": 0.18,
    "fallbackZeroDisplayMin": 0.15,
    "fallbackZeroVolumeBand": 0.2,
    "fallbackDisplayNormScale": 8.0,
    "fallbackPriceNormScale": 6.0,
    "fallbackVolumeTanhScale": 0.75,
    "fallbackDirectionWeights": [0.4, 0.3, 0.2, 0.1],  # display/price/capital/volume
    "fallbackAccelWeights": [0.55, 0.25, 0.2],
    "fallbackZeroWeights": [0.5, 0.35, 0.15],
    "fallbackCapitalWeights": [0.6, 0.4],  # zlje/zljzb
    # 批 4：共振 label + 展示面
    "resonanceLabelThresholds": [85.0, 67.0, 50.0, 27.0],
    "lifecycleStageFitness": [1.0, 0.8, 0.35, 0.2, 0.0],  # expansion/ignition/crowded/cooling/reversal
    "strategyDivergenceReasonMin": 0.6,
    "strategyOverheatReasonMin": 0.65,
}


def test_all_parameterized_defaults_match_hardcoded_values() -> None:
    """每个新字段的默认值必须等于参数化前的硬编码值（golden 不漂移第一道锚）。"""
    c = RankTrendConfig()
    for field, expected in EXPECTED_DEFAULTS.items():
        actual = getattr(c, field)
        if isinstance(expected, list):
            assert actual == pytest.approx(expected), field
        else:
            assert actual == pytest.approx(expected), field


def test_regime_module_constants_track_config_defaults() -> None:
    """risk.py 模块常量保留为向后兼容默认，且与 config 默认一致。"""
    c = RankTrendConfig()
    assert REGIME_STRONG_SCORE == pytest.approx(c.regimeStrongScore)


def test_new_list_fields_registered_in_strategy_list_keys() -> None:
    """新 list 字段必须同步 _STRATEGY_LIST_KEYS 白名单（SKILLS.md 硬规则）。"""
    from backend.optimization.search_space import _STRATEGY_LIST_KEYS

    for field, expected in EXPECTED_DEFAULTS.items():
        if isinstance(expected, list):
            assert field in _STRATEGY_LIST_KEYS, field


# ---------------------------------------------------------------------------
# 代表性行为测试（每参数组一个：改参数 → 行为变；默认参数 → 行为不变）
# ---------------------------------------------------------------------------


def test_synergy_vote_strengths_config_applies() -> None:
    """票强度 config 化：S 档强度 1.2→2.0 改变 v 合成与最终档位。"""
    base_args = (("S", "buy"), ("C", "hold"), ("C", "up"), None)
    # v = S 买 1.2 + C hold 0 + C up 0.5 + 无 cs = 1.7 → B（v>=1）
    tier_default, _ = _synergy_tier(base_args[0][0], base_args[0][1], base_args[1][0], base_args[1][1], base_args[2][0], base_args[2][1], "C", None, cs_tier=None)
    assert tier_default == "B"
    c = RankTrendConfig.from_patch({"tierSynergyVoteStrengths": [2.0, 1.0, 0.8, 0.5, 1.0, 1.0]})
    tier_boost, _ = _synergy_tier(base_args[0][0], base_args[0][1], base_args[1][0], base_args[1][1], base_args[2][0], base_args[2][1], "C", c, cs_tier=None)
    assert tier_boost == "A"  # v = 2.0 + 0.5 = 2.5 ≥ strong=2


def test_synergy_cs_strengths_config_applies() -> None:
    """cs 档位强度 config 化：A 强度 1.0→2.0 改变 v（采纳口径 res/rank/cs=0.75 下验证）。

    票值明细：res C hold=0、rank A buy=+0.75（1.0×0.75）、vp C neutral=0 → v=0.75；
    加 cs A ×0.75 = 1.5 → B；cs 强度 2.0 → v = 0.75 + 1.5 = 2.25 → A。
    """
    tier_default, _ = _synergy_tier("C", "hold", "A", "buy", "C", "neutral", "C", None, cs_tier="A")
    assert tier_default == "B"
    c = RankTrendConfig.from_patch({"tierSynergyCsStrengths": [2.0, 0.5, -0.5, -1.0]})
    tier_boost, _ = _synergy_tier("C", "hold", "A", "buy", "C", "neutral", "C", c, cs_tier="A")
    assert tier_boost == "A"


def test_direction_bucket_thresholds_config_applies() -> None:
    """涨跌幅档位边界 config 化：5% 边界上移 → 原 5.5% 从 ±10 档落回 ±8 档。"""
    assert _direction_bucket("600000", 5.5, None) == pytest.approx(10.0)
    c = RankTrendConfig.from_patch({"volumePriceDirectionThresholds": [7.0, 6.0, 3.0, 2.0, 1.0, 0.5]})
    assert _direction_bucket("600000", 5.5, c) == pytest.approx(8.0)


def test_volume_score_ladder_config_applies() -> None:
    """量比阶梯系数 config 化：常态段斜率 (vr−1)×5 → ×10 改变 score。"""
    base = compute_volume_price_score("600000", 2.0, 1.5, 100.0, 5.0, None)
    boosted = compute_volume_price_score(
        "600000", 2.0, 1.5, 100.0, 5.0,
        RankTrendConfig.from_patch({"volumeScoreUpNormalSlope": 10.0}),
    )
    assert base["score"] is not None and boosted["score"] is not None
    assert boosted["score"] > base["score"]  # 1.5 → (1.5-1)*5=2.5 vs (1.5-1)*10=5


def test_fund_score_slopes_config_applies() -> None:
    """资金分斜率 config 化：净流入 slope 3→6 改变 score（ratio=4 未撞 cap：12 vs 15）。"""
    base = compute_volume_price_score("600000", 2.0, 1.5, 100.0, 4.0, None)
    boosted = compute_volume_price_score(
        "600000", 2.0, 1.5, 100.0, 4.0,
        RankTrendConfig.from_patch({"fundScoreNetSlope": 6.0}),
    )
    assert boosted["score"] > base["score"]


def _risk_inputs(percentile: float = 90.0) -> dict:
    return {
        "technical": {
            "macd": {"histogram": 1.0},
            "signals": {
                "direction": {"signal": "buy"},
                "acceleration": {"signal": "buy"},
                "zeroCross": {"signal": "buy"},
            },
        },
        "cycle": {"stage": "expansion", "metrics": {"rankShock": 0.5, "rankVelocity": 2.0, "rankAcceleration": 0.5}},
        "zlje": 100.0,
        "zljzb": 5.0,
        "volume_ratio": 1.5,
    }


def test_risk_overheat_ladder_config_applies() -> None:
    """过热阶梯 config 化：percentile 斜率 1.2→2.4 提高 overheat 与 severity。"""
    inp = _risk_inputs()
    base = analyze_risk(90.0, inp["technical"], inp["cycle"], inp["zlje"], inp["zljzb"], inp["volume_ratio"], None)
    boosted = analyze_risk(
        90.0, inp["technical"], inp["cycle"], inp["zlje"], inp["zljzb"], inp["volume_ratio"],
        RankTrendConfig.from_patch({"riskOverheatPercentileSlope": 2.4}),
    )
    assert boosted["overheat"]["score"] > base["overheat"]["score"]
    assert boosted["overheat"]["severity"] >= base["overheat"]["severity"]


def test_risk_signal_thresholds_config_applies() -> None:
    """风险 signal 阈值 config 化：overheat hold 线 45→20 改变 signal 判定。"""
    inp = _risk_inputs(percentile=71.0)
    inp["cycle"]["metrics"]["rankShock"] = 0.0
    inp["cycle"]["metrics"]["rankVelocity"] = 0.0
    # percentile 71 → overheat = (71-70)*1.2 = 1.2 → buy（<45）
    base = analyze_risk(71.0, inp["technical"], inp["cycle"], inp["zlje"], inp["zljzb"], inp["volume_ratio"], None)
    assert base["overheat"]["signal"] == "buy"
    c = RankTrendConfig.from_patch({"riskOverheatHoldMin": 1.0})
    tuned = analyze_risk(71.0, inp["technical"], inp["cycle"], inp["zlje"], inp["zljzb"], inp["volume_ratio"], c)
    assert tuned["overheat"]["signal"] == "hold"


def test_regime_stage_adjust_config_applies() -> None:
    """regime 情绪阶段调整 config 化：高潮 +8→+20 改变 score。"""
    frame = {
        "marketContext": {"payload": {}},
        "hotlistSentiment": {"stage": "高潮期", "riskLevel": "中", "confidence": 0.8},
        "stocks": [{"change": 1.0, "volumeRatio": 1.0, "zlje": 100.0}],
    }
    base = market_regime(frame, None)
    c = RankTrendConfig.from_patch({"regimeStageAdjust": [20.0, 5.0, 0.0, -6.0, -8.0]})
    boosted = market_regime(frame, c)
    assert boosted["score"] == pytest.approx(base["score"] + 12.0)


def test_regime_state_thresholds_config_applies() -> None:
    """regime 状态阈值 config 化：strong 线 70→60 改变 state 判定。"""
    frame = {
        "marketContext": {"payload": {}},
        "hotlistSentiment": {"stage": "高潮期", "riskLevel": "中"},
        "stocks": [{"change": 1.0, "volumeRatio": 1.0, "zlje": 100.0}],
    }
    # base = 50 + 0(上涨 100% → (1-0.5)*40=20 → clamp 20)=70 + 高潮 8 = 78 → strong（≥70）
    base = market_regime(frame, None)
    assert base["state"] == "strong"
    c = RankTrendConfig.from_patch({"regimeStrongScore": 90.0})
    tuned = market_regime(frame, c)
    assert tuned["state"] != "strong"


def test_fallback_thresholds_config_applies() -> None:
    """fallback 信号阈值 config 化：direction 阈值 0.2→0.5 改变 buy→hold。"""
    fallback = {"displayChange": 1.5, "stockChange": 1.0, "volumeRatio": 1.2, "zlje": 100.0, "zljzb": 5.0}
    macd = {"cross": "none", "rawScore": 0.0}
    base_signals, _, _ = fallback_signals([], macd, fallback, False)
    assert base_signals["direction"]["signal"] == "buy"  # direction_score ≈ 0.35 ≥ 0.2
    c = RankTrendConfig.from_patch({"fallbackDirectionThreshold": 0.5})
    tuned_signals, _, _ = fallback_signals([], macd, fallback, False, c)
    assert tuned_signals["direction"]["signal"] == "hold"


def test_resonance_label_thresholds_config_applies() -> None:
    """共振 label 阈值 config 化（展示面）：85 线上移改变标签。"""
    from backend.analysis.ranktrend.engine.runtime import _resonance_label

    assert _resonance_label(86.0) == "非常强"
    c = RankTrendConfig.from_patch({"resonanceLabelThresholds": [90.0, 67.0, 50.0, 27.0]})
    assert _resonance_label(86.0, c) == "强"


def test_stage_fitness_config_applies() -> None:
    """STAGE_FITNESS config 化（展示分面）：expansion 1.0→0.5 降低 lifecycle 展示分。"""
    from backend.analysis.ranktrend.engine.runtime import compose_observation_scores

    def _input() -> dict:
        return {
            "technical": {"momentumProfile": {"short": 0, "mid": 0, "long": 0, "acceleration": 0}},
            "cycle": {"stage": "expansion", "decision": {"action": "allow", "reasons": []}, "metrics": {"rankPathCommitment": 0.5}},
            "risk": {"pressure": 0.5},
            "decision": {"base": {"signal": "hold", "combinedScore": 0.0}},
        }

    base = compose_observation_scores(_input(), None)
    c = RankTrendConfig.from_patch({"lifecycleStageFitness": [0.5, 0.8, 0.35, 0.2, 0.0]})
    tuned = compose_observation_scores(_input(), c)
    assert tuned["lifecycle"]["score"] < base["lifecycle"]["score"]
