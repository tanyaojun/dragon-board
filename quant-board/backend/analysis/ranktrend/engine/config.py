from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

@dataclass
class RankTrendConfig:
    momentumPeriods: list[int] = field(default_factory=lambda: [3, 5, 8, 13, 21])
    momentumWeights: list[float] = field(default_factory=lambda: [0.15, 0.2, 0.25, 0.25, 0.15])
    buyThresholds: list[float] = field(default_factory=lambda: [5, 8, 13, 21, 34])
    sellThresholds: list[float] = field(default_factory=lambda: [-5, -8, -13, -21, -34])
    macdFast: int = 13
    macdSlow: int = 21
    macdSignal: int = 8
    requireMacdGoldenCross: bool = False
    # ── 趋势因子硬编码阈值参数化（2026-08-17，默认值=原硬编码，golden 不漂移）──
    # 多周期动量：方向/加速度判定
    momentumDirectionThreshold: float = 0.2  # direction_signal 判定阈值（原 0.2）
    momentumSignalShareMin: float = 0.6  # direction 正/负占比门槛（原 0.6）
    momentumLongOpposeThreshold: float = 0.25  # 长周期反对阈值（原 0.25）
    momentumLongAgreeThreshold: float = 0.15  # 长周期附和阈值（原 0.15）
    momentumDirectionShareBoost: list[float] = field(default_factory=lambda: [0.5, 0.5])  # direction share boost（原 0.5/0.5）
    momentumAccelThreshold: float = 0.18  # accel_signal 判定阈值（原 0.18）
    momentumAccelShareBoost: list[float] = field(default_factory=lambda: [0.7, 0.3])  # accel share boost（原 0.7/0.3）
    momentumScoreThreshold: float = 35.0  # momentum_data signal 阈值（原 35）
    momentumConfidenceSlope: float = 0.45  # momentum_data confidence slope（原 0.45）
    # 零线交叉（zeroCross）
    momentumZeroWeights: list[float] = field(default_factory=lambda: [0.7, 0.3])  # trigger/confirm 权重（原 0.7/0.3）
    momentumZeroConfirmThreshold: float = 0.15  # confirm_score 方向判定阈值（原 0.15）
    momentumZeroStrongConfirmThreshold: float = 0.15  # strong_confirm 阈值（原 0.15）
    momentumZeroStrongConfirmBonus: float = 5.0  # strong_confirm confidence bonus（原 5）
    # MACD
    macdGoldenStrongGapMin: float = 0.2  # golden strong_gap 阈值（原 0.2）
    macdGoldenGapScaleRatio: float = 0.18  # golden gap/gap_scale 比例（原 0.18）
    macdDeathGapScaleRatio: float = 0.12  # death gap/gap_scale 比例（原 0.12）
    macdDeathStrongGapMin: float = 0.18  # death strong_gap 阈值（原 0.18）
    macdRawScoreWeights: list[float] = field(default_factory=lambda: [0.7, 0.3])  # rawScore strong_gap/impulse 权重（原 0.7/0.3）
    # ── ATR 真实波动均值回归（2026-08-17，设计 v2；独立观察维度，不进 synergy 投票）──
    atrPeriod: int = 14  # ATR 周期（简单均值，与 execution.py::_atr_of 一致）
    atrRefPeriod: int = 20  # close 参考均值周期
    atrChannelK: float = 2.0  # 通道倍数（偏离阈值）
    atrDeepDeviation: float = 3.0  # S 档绝对偏离阈值（审计修订，替代 2.5×k 相对式）
    atrMaxHistoryBars: int = 60  # 历史 bar 截断窗口（防内存）
    atrGapResetBars: int = 2  # 断档重置阈值（帧间隔 ≥ N 个 slot 即重置；跨 tradingDate 恒重置）
    atrAggregateByDay: bool = False  # 是否按日聚合（False=逐帧快照 bar，与回测同口径）
    atrBucketBySlot: bool = False  # 是否按 slot 分桶聚合（桶内 max high/min low/last close）
    jumpDeltaPct: float = 15.0  # 对齐旧 TS detectRankJumps 固定 delta=15
    jumpResetLookback: int = 3  # 事件触发后重置窗口（原硬编码 min(3, i+1)）
    jumpSustainCount: int = 2  # 持续事件判定阈值 surge/collapse 次数（原硬编码 2）
    directionWeight: float = 0.3
    accelerationWeight: float = 0.25
    crossWeight: float = 0.2
    macdWeight: float = 0.25
    buyScoreThreshold: float = 0.12
    sellScoreThreshold: float = -0.12
    # compose_strategy tier thresholds (configurable, defaults match legacy hardcoded values)
    tierAMainMidMomentumMin: float = 4.0
    tierAMainShortMomentumMin: float = -1.0
    tierAMainDivergenceSeverityMax: float = 0.7
    tierBIgnitionShortMomentumMin: float = 3.0
    tierBIgnitionAccelMin: float = 0.5
    tierBIgnitionRiskPressureMax: float = 0.65
    tierCrowdedLongMomentumMin: float = 4.0
    tierCrowdedAccelMax: float = 0.0
    tierCrowdedRiskPressureMin: float = 0.45
    tierExitRiskShortMomentumMax: float = -2.0
    tierExitRiskAccelMax: float = -2.0
    tierExitRiskPressureMin: float = 0.55
    # ── resonance（analyze_rank_resonance）：默认值 = 原硬编码/模块常量 ──
    resonanceShortWindowBars: int = 3
    resonanceMidWindowBars: int = 8
    resonancePathWindowBars: int = 8
    resonanceMinMarketSampleCount: int = 20
    resonanceMomentumScale: float = 15.0
    resonanceAccelerationScale: float = 15.0
    resonancePathDirectionWeight: float = 0.2
    resonanceDirectionThreshold: float = 0.1
    resonanceWeights: list[float] = field(default_factory=lambda: [0.35, 0.25, 0.2, 0.2, 0.2])
    resonanceReversalSwitchWeight: float = 0.6
    resonanceReversalDrawdownWeight: float = 0.4
    resonanceReversalDrawdownScale: float = 20.0
    resonanceJumpFreshnessDecay: float = 3.0
    resonanceEntryStrengthScale: float = 25.0
    resonanceNewEntryWeights: list[float] = field(default_factory=lambda: [0.7, 0.3])
    # ── volume_price（compute_volume_price_score / compute_synergy_state） ──
    volumePriceBase: float = 50.0
    volumePriceOverVolumeRatio: float = 2.5
    volumePriceAbnormalFundRatio: float = 20.0
    volumePriceShrinkRatio: float = 0.95
    volumePriceMildRatio: float = 1.05
    # ── 量价硬编码参数化（2026-08-17，默认值=原硬编码，golden 不漂移）──
    volumePriceDirectionBuckets: list[float] = field(
        default_factory=lambda: [15.0, 12.0, 10.0, 8.0, 6.0, 4.0, 2.0, 1.0]
    )  # 方向八档分值：涨停/7%+/5-7/3-5/2-3/1-2/0.5-1/0-0.5（原硬编码）
    volumePriceNormalRatio: float = 2.0  # 量比正常上限（原硬编码 vr<=2.0 边界）
    # ── crossSection（横截面相对强弱因子，2026-08-17 方向 A；第 5 维投票默认打开，见 tierSynergyCrossSectionVote）──
    crossSectionStrongMin: float = 85.0  # A 档 percentile 下限（高位）
    crossSectionStrongDeltaUp: float = 5.0  # A 档 delta 上升确认
    crossSectionMidMin: float = 50.0  # B 档中位下限
    crossSectionMidDeltaUp: float = 15.0  # B 档 delta 显著上升
    crossSectionWeakMax: float = 15.0  # D 档 percentile 上限（低位）
    crossSectionWeakDeltaDown: float = -5.0  # D 档 delta 下降确认
    crossSectionMidMax: float = 50.0  # C 档中位上限
    crossSectionMidDeltaDown: float = -15.0  # C 档 delta 显著下降
    jumpConfirmChangeMin: float = 3.0  # Jump 价格确认：涨跌幅 ≥3%（up）/ ≤-3%（down），2026-08-17 G4 默认生效
    jumpConfirmVolumeRatioMin: float = 1.0  # Jump 量确认：量比 ≥1（放量配合）
    # ── amount 成交额量比（2026-08-18 G3：跨帧成交额量比进量价，"价量资金"落地）──
    amountRatioPeriod: float = 5.0  # 成交额量比均额窗口（前 N 帧平均）
    amountRatioHigh: float = 1.5  # 放量资金阈值（成交额 ≥ 均额 1.5 倍 → 加分）
    amountRatioLow: float = 0.5  # 缩量资金阈值（成交额 ≤ 均额 0.5 倍 → 减分）
    # ── priceRankDivergence（价格-排名背离观察因子，2026-08-18 G1 相位差方案；不进 synergy 投票）──
    priceRankChangeMin: float = 0.0  # 价格方向阈值：change ≥ 此值判涨、≤ -此值判跌
    priceRankDeltaMin: float = 0.0  # 排名方向阈值：percentile delta ≥ 此值判升、≤ -此值判降
    # ── regime 环境门（2026-08-18 数据修正：strong 禁 A/B、weak 放开；False 回退旧 weak/retreat 禁）──
    regimeGateStrongBan: bool = True
    # 2026-08-19 方向 C 强度门控：strong 市场 A/B 分层禁（A -0.0739 比 B -0.0172 衰减更重）——
    # banStrongA=banStrongB=True 等价旧全禁；banStrongB=False = A 禁 B 观察（默认值由验证定）
    banStrongA: bool = True
    banStrongB: bool = True
    tierSynergyDivergenceVote: float = 0.0  # priceRankDivergence 第 6 维投票权重（0=观察；数据验证后定默认）
    tierSynergyCrossSectionVote: float = 1.0  # crossSection 第 5 维投票权重（1.0=启用，2026-08-17 用户决策默认打开；验证 all+10%/8月+237%）
    tierSynergyPriceMomentumVote: float = 0.0  # priceMomentum 第 6 维投票权重（0=关闭：实证负贡献 all −32%/8月 −，保留观察不进投票）
    # ── priceMomentum（价格动量观察因子，2026-08-17 审计缺口 G1；不进 synergy 投票）──
    priceMaShort: float = 5.0  # 价格（change）短均线周期
    priceMaLong: float = 10.0  # 价格（change）长均线周期
    priceMomentumPeriod: float = 3.0  # 价格动量均值周期
    priceMomentumScoreThreshold: float = 0.5  # 价格动量 buy/sell 阈值（%）
    synergyLowVp: float = 40.0
    synergyHighVp: float = 75.0
    resonanceVolumePriceWeight: float = 0.15
    # ── decision（compose_decision）：置信度公式与反转降级 ──
    decisionMinAgreement: int = 2
    decisionMaxOpposition: int = 1
    decisionConfidenceBase: float = 50.0
    decisionConfidenceSlope: float = 25.0
    decisionAgreementSlope: float = 15.0
    decisionMarginSlope: float = 10.0
    decisionConfidenceMin: float = 50.0
    decisionConfidenceMax: float = 95.0
    decisionRiskPenaltyWeights: list[float] = field(default_factory=lambda: [11.0, 9.0, 5.0])
    decisionReversalFinalConfCap: float = 62.0
    decisionReversalPressureMin: float = 0.78
    decisionReversalOverheatMin: float = 0.7
    decisionReversalMarginMax: float = 0.05
    # ── lifecycle（compose_observation_scores / lifecycle_decision） ──
    lifecycleWeights: list[float] = field(default_factory=lambda: [0.35, 0.25, 0.2, 0.2])
    lifecycleMomentumWeights: list[float] = field(default_factory=lambda: [0.3, 0.45, 0.25])
    lifecycleMomentumScales: list[float] = field(default_factory=lambda: [15.0, 15.0, 8.0])
    lifecycleMidLongCommitmentMin: float = 15.0
    lifecycleAccelCommitmentMin: float = 8.0
    lifecycleWeakPathCommitmentMax: float = 0.45
    lifecycleVelocityMin: float = 18.0
    lifecycleAccelMin: float = 12.0
    lifecycleLowVisibilityPathMax: float = 0.7
    lifecycleLowVisibilityMomentumMin: float = 18.0
    lifecycleHighRiskPressureMin: float = 0.75
    lifecycleHighRiskDivergenceMin: float = 0.8
    lifecycleHighRiskOverheatMin: float = 0.7
    # ── risk（analyze_risk）：压力合成与严重度归一 ──
    riskPressureWeights: list[float] = field(default_factory=lambda: [0.58, 0.42])
    riskOverheatOffset: float = 45.0
    riskOverheatScale: float = 30.0
    riskDivergenceOffset: float = 40.0
    riskDivergenceScale: float = 30.0
    # ── 五维观察档位阈值（回测方案 §3.1）：默认值 = 当前硬编码，golden 不漂移 ──
    tierResonanceReversalPenaltyMin: float = 0.6  # _resonance_tier 首条（reversal 否决）
    tierResonanceJumpFreshnessMin: float = 0.5  # _resonance_tier 第二条（Jump 事件）+ 新入榜 S
    tierResonancePersistenceMin: float = 0.6  # _resonance_tier 第三条（buy+persistence）
    tierResonanceEntryStrengthMin: float = 0.3  # 新入榜 A 判定
    tierRankTrendStrongMin: float = 0.5  # _rank_trend_tier S
    tierRankTrendConfirmMin: float = 0.25  # _rank_trend_tier A
    tierSynergyVoteStrong: float = 2.0  # _synergy_tier vote_sum≥strong（S/A 分界，档位加权后 float）
    tierSynergyVoteWeak: float = 1.0  # _synergy_tier vote_sum≥weak（B）
    tierSynergyVoteReverse: float = -1.0  # _synergy_tier vote_sum≤reverse（D）
    # ── 生命周期分层阈值（阈值数据驱动优化设计 2026-08-16，默认值=当前硬编码，零行为变化）──
    # raw_stage（5 态初判）
    cycleRawWarmPercentileMin: float = 65.0
    cycleRawWarmBestRankMax: float = 25.0
    cycleRawHotZonePercentileMin: float = 85.0
    cycleRawHotZoneBestRankMax: float = 10.0
    cycleRawRecoveryVelocityMin: float = 0.0
    cycleRawRecoveryAccelMin: float = -1.2
    cycleRawRecoveryPercentileMin: float = 50.0
    cycleRawRecoveryBestRankMax: float = 30.0
    cycleRawRecoveryHotMin: int = 1
    cycleRawExpansionPercentileMin: float = 70.0
    cycleRawExpansionAccelMin: float = -1.0
    cycleRawExpansionHotMin: int = 1
    cycleRawExpansionBestRankMax: float = 20.0
    cycleRawCrowdedHotMin: int = 3
    cycleRawCrowdedBestRankMax: float = 5.0
    cycleRawCrowdedDrawdownMax: float = 1.0
    cycleRawCrowdedVelocityMax: float = 1.0
    cycleRawReversalDrawdownMin: float = 2.0
    cycleRawReversalAccelMax: float = -1.0
    cycleRawReversalHotMin: int = 2
    cycleRawReversalBestRankMax: float = 10.0
    # normalize_stage（状态机平滑）
    cycleNormWeakeningAccelMax: float = -1.0
    cycleNormSevereAccelMax: float = -2.5
    cycleNormSevereDrawdownMin: float = 3.0
    cycleNormCoolingReadyPercentileMax: float = 72.0
    cycleNormCrowdedCarryPercentileMin: float = 82.0
    cycleNormCrowdedCarryBestRankMax: float = 12.0
    # cycle_confidence（每态区域/动量/持续性/回撤）
    cycleConfCoolingRegionPctMax: float = 60.0
    cycleConfIgnitionRegionPctMin: float = 50.0
    cycleConfIgnitionRegionPctMax: float = 80.0
    cycleConfExpansionRegionPctMin: float = 60.0
    cycleConfCrowdedRegionPctMin: float = 82.0
    cycleConfCrowdedRegionBestMax: float = 10.0
    cycleConfReversalRegionPctMin: float = 70.0
    cycleConfReversalRegionBestMax: float = 20.0
    cycleConfIgnitionMomentumAccelMin: float = -0.8
    cycleConfExpansionMomentumAccelMin: float = -0.2
    cycleConfCrowdedMomentumHotMin: int = 2
    cycleConfCoolingMomentumPctMax: float = 60.0
    cycleConfCrowdedMomentumPctMin: float = 80.0
    cycleConfCoolingPersistenceHotMax: int = 1
    cycleConfIgnitionPersistenceHotMax: int = 1
    cycleConfExpansionPersistenceHotMax: int = 2
    cycleConfCrowdedPersistenceHotMin: int = 2
    cycleConfReversalPersistenceHotMin: int = 2
    cycleConfReversalPersistenceBestMax: float = 10.0
    cycleConfCoolingDrawdownMax: float = 1.0
    cycleConfExpansionDrawdownMax: float = 1.0
    cycleConfCrowdedDrawdownMax: float = 1.0
    cycleConfReversalDrawdownMin: float = 1.0

    @classmethod
    def from_patch(cls, patch: dict[str, Any] | None = None) -> "RankTrendConfig":
        base = cls()
        if not patch:
            return base
        for key, value in patch.items():
            if hasattr(base, key):
                current = getattr(base, key)
                if isinstance(current, bool):
                    if isinstance(value, str):
                        normalized = value.strip().lower()
                        if normalized in {"true", "1", "yes", "on"}:
                            value = True
                        elif normalized in {"false", "0", "no", "off"}:
                            value = False
                        else:
                            raise ValueError(f"{key} 需要布尔值，实际 {value!r}")
                    elif isinstance(value, bool):
                        pass
                    elif isinstance(value, (int, float)) and value in (0, 1):
                        value = bool(value)
                    else:
                        raise ValueError(f"{key} 需要布尔值，实际 {value!r}")
                elif isinstance(current, int):
                    # int 字段（macd*/resonance*Bars/decision* 等）强制整数：非整数值拒绝。
                    # float() 统一处理 str/numpy/Decimal 等数值输入，非数值在此抛 ValueError。
                    as_float = float(value)
                    if not as_float.is_integer():
                        raise ValueError(f"{key} 需要整数，实际 {value!r}")
                    value = int(as_float)
                elif isinstance(current, float):
                    value = float(value)
                setattr(base, key, value)
        _validate_tier_constraints(base)
        if base.macdSlow <= base.macdFast:
            base.macdSlow = base.macdFast + 1
        total = base.directionWeight + base.accelerationWeight + base.crossWeight + base.macdWeight
        if total > 0:
            base.directionWeight /= total
            base.accelerationWeight /= total
            base.crossWeight /= total
            base.macdWeight /= total
        return base


def _validate_tier_constraints(config: "RankTrendConfig") -> None:
    """档位阈值强校验（回测方案 §3.1）。

    约束：0 < confirm < strong <= 1；reverse <= weak < strong；
    0 <= tierResonance*Min <= 1。不满足抛 ValueError（回测 trial 记 failed）。
    weak 必须严格小于 strong，防止 _synergy_tier 的 v==weak 分支被 v>=strong 吞掉而不可达。
    """
    if not (0 < config.tierRankTrendConfirmMin < config.tierRankTrendStrongMin <= 1):
        raise ValueError(
            f"tierRankTrend 约束失败：需要 0 < confirm < strong <= 1，"
            f"实际 confirm={config.tierRankTrendConfirmMin}, strong={config.tierRankTrendStrongMin}"
        )
    if not (config.tierSynergyVoteReverse <= config.tierSynergyVoteWeak < config.tierSynergyVoteStrong):
        raise ValueError(
            f"tierSynergyVote 约束失败：需要 reverse <= weak < strong，"
            f"实际 reverse={config.tierSynergyVoteReverse}, weak={config.tierSynergyVoteWeak}, "
            f"strong={config.tierSynergyVoteStrong}"
        )
    for name in (
        "tierResonanceReversalPenaltyMin",
        "tierResonanceJumpFreshnessMin",
        "tierResonancePersistenceMin",
        "tierResonanceEntryStrengthMin",
    ):
        value = float(getattr(config, name))
        if not (0 <= value <= 1):
            raise ValueError(f"{name} 约束失败：需要 0 <= value <= 1，实际 {value}")
