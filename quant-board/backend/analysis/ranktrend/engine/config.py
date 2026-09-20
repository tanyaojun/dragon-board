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
    # ── MA 交叉因子（2026-09-12 阶段 17：MA10/20 观察接线，默认全关，golden 不漂移）──
    # 排名百分位序列上的快慢均线金叉/死叉，与 MACD 同输入同二值交叉参与语义（阶段 17 评估结论见
    # docs/ranktrend-tier-backtest/ranktrend-longterm-backtest-plan.md）。
    maFastPeriod: int = 10  # MA 快线周期（用户指定 10）
    maSlowPeriod: int = 20  # MA 慢线周期（用户指定 20；from_patch 保证 > maFastPeriod）
    maWeight: float = 0.37  # compose_decision 第 5 分量权重（2026-09-13 阶段 22.8 落默认：p2_aggressive 实证口径）
    maCrossTrendBuy: bool = False  # MA 金叉是否参与 trend_buy OR 链（False=关闭）
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
    # ── 决策合成五权重（2026-09-13 阶段 21.7 五因子化 → 阶段 22.8 权重重定义落默认）──
    # 当前默认 = 阶段 22 p2_aggressive 实证口径（用户决策），和恒=1；
    # 依据：evaluate_ts_factor_weights 两层实证（层 1 事件级 + 层 2 边际贡献/剂量扫描，
    # decision/oos1/oos2 三窗）+ Track 2 判定卡 PASS_CANDIDATE（C1 +12.5%、
    # C2 oos 双窗同向 +30.0%/+28.9%、C3 passHard 保持；详见长测计划 §22）。
    # 历史口径：阶段 21.7 落默认 0.24/0.20/0.16/0.20/0.20（设计值归一化）。
    # 直接构造与 from_patch 归一化结果逐位一致；MACD 项保留（权重位/共识票/trend_buy
    # 链/风险面/观察字段零改动）。
    directionWeight: float = 0.06
    accelerationWeight: float = 0.04
    crossWeight: float = 0.24
    macdWeight: float = 0.29
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
    volumePriceAbnormalFundRatio: float = 10.0  # 2026-09-15 阶段 25 fund10 落默认（20→10）：C-a 新基线三窗判定卡 PASS（+7.3/−4.1/+1.9%）+ Track 1 交易复核主窗无害（wrxpf +2.9%）；回退 = 还原 20.0
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
    # B 档绝对线（2026-09-15 P1-0 参数化：原 _tier_from 硬编码 70，delta 分支与首帧降级分支复用；
    # 默认=原值 golden 不漂移。注意 percentile<=30 的 C 档低位线为无效轴（与中位兜底同返回 C），
    # 审计 I-1 已归档不参数化）
    crossSectionStrongAbsMin: float = 70.0
    # ── crossSection 持续高位 A 档替代路径（2026-09-13 方案2；默认关闭 golden 不漂移）──
    # 数学边界：delta = pct[-1] − pct[-2] ≤ 100 − pct[-1]，pct > 95 的强势股（榜首
    # pct=100）永远无法满足 A 档 delta≥5 上升确认——强势体现在"持续停留高位"而非
    # "继续上升"。路径：pct ≥ PersistMin 且近 Frames 帧均值 ≥ PersistMeanMin 且窗口满
    # Frames 帧合法值（证据不足不伪造）。判定顺序 A-delta > A-persist > 原分支，
    # 开启后行为变更 = 纯增量（部分 B 升 A），默认值是否落地由实证数据决定。
    crossSectionPersistFrames: int = 0  # 持续高位窗口 N（近 N 帧 percentile 均值）；0=关闭（默认）
    crossSectionPersistMin: float = 90.0  # 当前 pct 门槛（路径开启时生效）
    crossSectionPersistMeanMin: float = 85.0  # 近 N 帧均值门槛
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
    # WP2 环境门去噪参数（默认值 = 现行为；L1 档案登记，未经 longterm-test 证实不得改默认）
    lifecycleConfirmFrames: int = 1        # veto/B-D 降档连续确认帧数
    regimeScoreEmaAlpha: float = 1.0       # regime score EMA 系数（1=直通）
    regimeStateHysteresis: bool = False    # strong 边界迟滞开关
    regimeStrongHysteresisBand: float = 5.0  # strong 退出阈值 = 进入阈值 - band
    tierSynergyDivergenceVote: float = 0.0  # priceRankDivergence 第 6 维投票权重（0=观察；数据验证后定默认）
    # ── P_repool_timeline_gap 研究参数（2026-09-20 参数化，默认值=原硬编码 5，golden 不漂移）──
    # 出池回池重建期三档判定的中档线（runtime sample_status）：degradedSampleFloor
    # <= len(percentiles) < momentum_min_samples → degraded（有判定，前端显示真实 stage）；
    # 低于该线 → insufficient（前端周期列显示「样本不足」）。中期扫描档位：3/4/5(默认)/7/10。
    # 约束（validate 校验）：1 <= degradedSampleFloor < momentum_min_samples。
    degradedSampleFloor: int = 5
    tierSynergyPriceMomentumVote: float = 0.0  # priceMomentum 第 6 维投票权重（0=关闭：实证负贡献 all −32%/8月 −，保留观察不进投票）
    # ── 维度票权重（2026-09-14 参数化 + 阶段 23.9 实证落默认）──
    # 用户决策采纳 combo_three_quarter：res/rank/cs 1.0 → 0.75（判定卡 C1 +11.2%/
    # oos +7.5%/+26.6%，C1-C5 全过），vp 两轮证据维持 1.0（窄峰，两侧受损）。
    # 回退 = 三字段还原 1.0。结构下限：三轴同减 ≤0.5 时 S/A 档塌缩（长测计划 §23.9）。
    tierSynergyResonanceVote: float = 0.75  # resonance 票权重（共振维自阶段 3 修复方向 1 起在 replay 投票）
    tierSynergyRankVote: float = 0.75  # rankTrend 票权重
    tierSynergyVolumePriceVote: float = 1.0  # volumePrice 票权重（注意：vp E→D 出货硬降为结构规则，不随权重归零）
    tierSynergyCrossSectionVote: float = 0.75  # crossSection 第 5 维投票权重（1.0=启用，2026-08-17 用户决策默认打开；2026-09-14 阶段 23.9 降权 0.75）
    # ── 硬编码参数化清点（2026-09-14，六区域全面 config 化；默认值=参数化前硬编码值，
    # golden 不漂移；全部登记为结构参数未扫描，无自由度消耗）──
    # 批 1：synergy 总档档位强度（原 volume_price._VOTE_STRENGTH / _CS_STRENGTH 模块硬编码）
    tierSynergyVoteStrengths: list[float] = field(default_factory=lambda: [1.2, 1.0, 0.8, 0.5, 1.0, 1.0])  # S/A/B/C/D/E
    tierSynergyCsStrengths: list[float] = field(default_factory=lambda: [1.0, 0.5, -0.5, -1.0])  # A/B/C/D（cs/pm/dv 三维共用映射）
    # 批 2：量价打分阶梯（原 compute_volume_price_score 内硬编码；2026-09-15 阶段 25 方案 C-b
    # 扫描判零效应冗余——全部为分值幅度面，×正缩放不改符号/阈值比较，无档位杠杆，冗余归档不删实现）
    volumePriceDirectionThresholds: list[float] = field(default_factory=lambda: [7.0, 5.0, 3.0, 2.0, 1.0, 0.5])  # 涨跌幅档位边界（涨停外 7-0.5%）
    volumeScoreUpShrinkLimitUp: float = 8.0   # 缩量涨停弱加成
    volumeScoreUpShrinkBase: float = 10.0     # 缩量上涨基准
    volumeScoreUpShrinkSlope: float = 15.0    # 缩量斜率（×(shrink−vr)）
    volumeScoreUpCap: float = 15.0            # 上涨侧常态/缩量段封顶
    volumeScoreUpMildLimitUp: float = 10.0    # 准缩量涨停
    volumeScoreUpMildNormal: float = 5.0      # 准缩量常态
    volumeScoreUpNormalBase: float = 10.0     # 常态量基准（min(cap, base+(vr−1)×slope)）
    volumeScoreUpNormalSlope: float = 5.0
    volumeScoreUpOverBase: float = 15.0       # 放量段（max(floor, base−(vr−2)×slope)）
    volumeScoreUpOverSlope: float = 10.0
    volumeScoreUpOverFloor: float = 5.0
    volumeScoreUpExcessBase: float = 15.0     # 过度放量负分（−min(cap, base+(vr−2)×slope)）
    volumeScoreUpExcessSlope: float = 10.0
    volumeScoreUpExcessCap: float = 20.0
    volumeScoreDownOverMild: float = -20.0    # 放量下跌
    volumeScoreDownShrink: float = -5.0       # 准缩量下跌
    volumeScoreDownLimitDown: float = -15.0   # 缩量跌停（封死卖不出，重于常态）
    volumeScoreDownNormal: float = -10.0      # 缩量下跌常态
    fundScoreCap: float = 15.0                # 资金分封顶
    fundScoreDumpBase: float = 10.0           # 对倒出货基准（−min(cap, base+(ratio−abnormal)×slope)）
    fundScoreDumpSlope: float = 0.5
    fundScoreNetSlope: float = 3.0            # 净流入/流出斜率（min(cap, ratio×slope)）
    fundScoreInOutStep: float = 5.0           # 净额方向步进（inflow>0 → +step）
    amountScoreStep: float = 5.0              # 成交额量比放量/缩量加分（G3）
    # 批 3：风险阶梯（原 risk.analyze_risk 内硬编码；over/div 分数 → severity → pressure
    # → decision 风险惩罚 / lifecycle veto / compose_strategy 退出门槛）
    riskOverheatPercentileMin: float = 70.0   # 关注度过热线（×slope 计分）
    riskOverheatPercentileSlope: float = 1.2
    riskOverheatShockSlope: float = 12.0      # ×rankShock
    riskOverheatVelocitySlope: float = 1.5    # ×rankVelocity（min cap）
    riskOverheatVelocityCap: float = 15.0
    riskOverheatAccelSlope: float = 4.0       # ×|rankAcceleration|（负加速，min cap）
    riskOverheatAccelCap: float = 20.0
    riskOverheatMacdSlope: float = 15.0       # ×|histogram|（负柱，min cap）
    riskOverheatMacdCap: float = 10.0
    riskOverheatDirectionBuyBonus: float = 5.0        # direction buy 逆温加成
    riskOverheatAccelMissPenalty: float = 10.0        # acceleration 非 buy
    riskOverheatZeroCrossSellPenalty: float = 18.0    # zeroCross sell
    riskHotAttentionPercentileMin: float = 70.0       # 高关注度判定线（divergence 前提）
    riskDivergenceHotBonus: float = 10.0              # 高关注度基础加分
    riskDivergenceHotOutflowPenalty: float = 25.0     # 高关注度+主力流出
    riskDivergenceHotDumpPenalty: float = 18.0        # 高关注度+净占比负
    riskDivergenceVolumeHighMin: float = 2.0          # 高量比线
    riskDivergenceVolumeOutflowPenalty: float = 15.0  # 高量比+流出
    riskDivergenceVolumeDumpPenalty: float = 8.0      # 高量比+净占比负
    riskDivergenceShockMin: float = 0.8               # 高震幅线
    riskDivergenceShockOutflowPenalty: float = 12.0   # 高震幅+流出
    riskDivergenceStageOutflowPenalty: float = 12.0   # 拥挤/反转+流出
    riskDivergenceInflowRelief: float = 15.0          # 主力流入缓释
    riskDivergenceDumpRelief: float = 10.0            # 净占比正缓释
    riskDivergenceShrinkVolumeMax: float = 1.5        # 缩量缓释量比上限
    riskDivergenceShrinkInflowRelief: float = 6.0     # 缩量+流入缓释
    riskOverheatStageMultipliers: list[float] = field(default_factory=lambda: [0.3, 0.55, 0.85, 1.0, 0.3])  # ignition/expansion/crowded/reversal/cooling
    riskDivergenceStageMultipliers: list[float] = field(default_factory=lambda: [0.35, 0.65, 0.9, 1.0, 0.35])
    riskOverheatSellMin: float = 70.0         # overheat signal=sell 线（且 crowded/reversal）
    riskOverheatHoldMin: float = 45.0         # overheat signal=hold 线
    riskDivergenceSellMin: float = 65.0
    riskDivergenceHoldMin: float = 40.0
    riskSynergyOverheatSevMin: float = 0.65   # risk.synergy 双门（over_sev）
    riskSynergyDivergenceSevMin: float = 0.6  # risk.synergy 双门（div_sev）
    # regime 环境打分（原 market_regime 内硬编码；REGIME_* 模块常量保留为向后兼容默认）
    regimeStageAdjust: list[float] = field(default_factory=lambda: [8.0, 5.0, 0.0, -6.0, -8.0])  # 高潮/发酵/启动/退潮/冰点
    regimeStrongScore: float = 70.0
    regimeNormalScore: float = 50.0
    regimeWeakScore: float = 30.0
    regimeLimitUpChange: float = 9.8          # 池内涨停判定涨幅线
    regimeLimitUpBaseShare: float = 0.08      # 涨停占比基线
    regimeRiskHighAdjust: float = -8.0        # 热榜情绪风险高修正
    regimeRiskLowAdjust: float = 3.0          # 热榜情绪风险低修正
    regimeBaseScore: float = 50.0             # regime 打分基线
    regimeUpShareSlope: float = 40.0          # 池内上涨占比因子（clamp(floor, cap)）
    regimeUpShareFloor: float = -20.0
    regimeUpShareCap: float = 20.0
    regimeLimitUpSlope: float = 80.0          # 涨停占比因子
    regimeLimitUpFloor: float = -15.0
    regimeLimitUpCap: float = 25.0
    regimeActiveVolumeMin: float = 1.2        # 量能活跃判定线
    regimeActiveBaseShare: float = 0.35       # 活跃占比基线
    regimeActiveSlope: float = 10.0
    regimeActiveFloor: float = -5.0
    regimeActiveCap: float = 7.0
    regimeMoneySlope: float = 20.0            # 资金正向占比因子
    regimeMoneyFloor: float = -10.0
    regimeMoneyCap: float = 10.0
    # 批 4：技术信号 fallback（原 fallback_signals 内硬编码；percentile 序列不足时兜底路径）
    fallbackDirectionThreshold: float = 0.2   # direction buy/sell 线
    fallbackAccelThreshold: float = 0.18
    fallbackZeroDisplayMin: float = 0.15      # 零线交叉 display 门
    fallbackZeroVolumeBand: float = 0.2       # 零线交叉 volume 容带
    fallbackDisplayNormScale: float = 8.0     # displayChange 归一化尺度
    fallbackPriceNormScale: float = 6.0       # stockChange 归一化尺度
    fallbackVolumeTanhScale: float = 0.75     # 量比 tanh 尺度
    fallbackDirectionWeights: list[float] = field(default_factory=lambda: [0.4, 0.3, 0.2, 0.1])  # display/price/capital/volume
    fallbackAccelWeights: list[float] = field(default_factory=lambda: [0.55, 0.25, 0.2])  # display/price/volume
    fallbackZeroWeights: list[float] = field(default_factory=lambda: [0.5, 0.35, 0.15])
    fallbackCapitalWeights: list[float] = field(default_factory=lambda: [0.6, 0.4])  # zlje/zljzb
    # 批 4：共振 label 阈值（展示面）
    resonanceLabelThresholds: list[float] = field(default_factory=lambda: [85.0, 67.0, 50.0, 27.0])
    # 批 4：展示面（observation.lifecycle 展示分与 strategy reasons，2026-09-13 已证 signal-neutral）
    lifecycleStageFitness: list[float] = field(default_factory=lambda: [1.0, 0.8, 0.35, 0.2, 0.0])  # expansion/ignition/crowded/cooling/reversal
    strategyDivergenceReasonMin: float = 0.6       # strategy reasons 背离提示线
    strategyOverheatReasonMin: float = 0.65        # strategy reasons 过热提示线
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
    # ── lifecycle 环境门干预形态（2026-09-14 阶段 24 方案 A 参数化；默认=现行为，golden 不漂移）──
    # 审计修订稿 §3.1 单一 lifecycleGateMode 实施时拆为 veto/降档两个正交开关：§5.1 trial 表
    # 的 b 组（只动 veto 剂量）与 c 组（只动降档形态）要求单变量归因，单枚举会把两轴绑死。
    lifecycleVetoGateMode: str = "hard"        # E 干预形态：hard=短路否决（现行为）| soft=负票 | off=不干预（评估锚）
    lifecycleVetoPathMode: str = "all_soft"    # 仅 soft 生效，veto 双路径分流：all_soft | reversal_hard | highrisk_hard
    lifecycleVetoVoteStrength: float = 1.5     # soft：E 帧 v_final = v_raw − strength 后重走阈值阶梯
    lifecycleDowngradeGateMode: str = "hard"   # lc B/D 对已达 S/A 的干预：hard=降一档（现行为）| soft=惩罚 | off=不干预
    lifecycleDowngradePenalty: float = 0.5     # soft：首评 ∈ {S,A} 时 v −= penalty 后重走阶梯
    volumePriceGateMode: str = "hard"          # vp E→D 出货短路（同构位）：hard=现行为 | soft=强制负票 | off=静默
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

    def __post_init__(self) -> None:
        # 决策合成五权重不变量（2026-09-13 review 跟进）：直接构造 fail-fast——
        # 旧四权重全量字典等未归一化状态会让 combinedScore 静默失真，禁止落引擎；
        # from_patch 不受影响（cls() 时默认值和=1 通过，patch 后由归一化保证）。
        _validate_decision_weights(self)
        _validate_repool_params(self)

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
        _validate_repool_params(base)
        # setattr 绕过 __post_init__：归一化前显式拒绝负权重（负值会扭曲归一化比例）
        for _w in _DECISION_WEIGHT_FIELDS:
            if getattr(base, _w) < 0:
                raise ValueError(f"决策权重 {_w} 不能为负，实际 {getattr(base, _w)}")
        if base.macdSlow <= base.macdFast:
            base.macdSlow = base.macdFast + 1
        if base.maFastPeriod < 1 or base.maSlowPeriod < 1:
            raise ValueError(f"MA 周期需 ≥1，实际 fast={base.maFastPeriod}, slow={base.maSlowPeriod}")
        if base.maSlowPeriod <= base.maFastPeriod:
            base.maSlowPeriod = base.maFastPeriod + 1
        total = base.directionWeight + base.accelerationWeight + base.crossWeight + base.macdWeight + base.maWeight
        if total > 0:
            base.directionWeight /= total
            base.accelerationWeight /= total
            base.crossWeight /= total
            base.macdWeight /= total
            base.maWeight /= total
        return base


_DECISION_WEIGHT_FIELDS = (
    "directionWeight",
    "accelerationWeight",
    "crossWeight",
    "macdWeight",
    "maWeight",
)


def _validate_repool_params(config: "RankTrendConfig") -> None:
    """P_repool_timeline_gap：degraded 门槛必须落在 [1, momentum_min_samples) 开区间。"""
    _momentum_floor = max(2, max(config.momentumPeriods) + 1)
    if not (1 <= config.degradedSampleFloor < _momentum_floor):
        raise ValueError(
            f"degradedSampleFloor 必须在 [1, momentum_min_samples={_momentum_floor}) 内，"
            f"实际 {config.degradedSampleFloor}"
        )


def _validate_decision_weights(config: "RankTrendConfig") -> None:
    """决策合成五权重不变量校验（2026-09-13 review 跟进，直接构造路径 fail-fast）。

    合法状态：五权重和 ≈1（默认值/任意 from_patch 归一化后状态），
    或全 0（显式全关闭哨兵，与 from_patch 全 0 patch 行为一致）；
    负权重一律拒绝。违反抛 ValueError——from_patch 自动归一化不受影响。
    """
    weights = [getattr(config, name) for name in _DECISION_WEIGHT_FIELDS]
    if any(w < 0 for w in weights):
        raise ValueError(f"决策权重不能为负：{dict(zip(_DECISION_WEIGHT_FIELDS, weights))}")
    total = sum(weights)
    if not (math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-6) or total == 0.0):
        raise ValueError(
            f"决策合成五权重和须为 1（或全 0 显式关闭），实际和={total}："
            f"{dict(zip(_DECISION_WEIGHT_FIELDS, weights))}；"
            "自定义权重请走 RankTrendConfig.from_patch（自动归一化）"
        )


def _validate_tier_constraints(config: "RankTrendConfig") -> None:
    """档位阈值强校验（回测方案 §3.1）。

    约束：0 < confirm < strong <= 1；reverse <= weak < strong；
    0 <= tierResonance*Min <= 1。不满足抛 ValueError（回测 trial 记 failed）。
    weak 必须严格小于 strong，防止 _synergy_tier 的 v==weak 分支被 v>=strong 吞掉而不可达。
    """
    # list 形状守卫（2026-09-15 补扫总纲预检纪律 1 / P5-0）：此前对 list 长度零校验——
    # 短 list 运行期 IndexError、长 list 静默截断、tierSynergyVoteStrengths 长度不符时
    # _vote 静默回退旧硬编码 fallback（volume_price.py:405-406，trial 假绿）。fail-fast。
    for _list_name, _expected_len in (
        ("buyThresholds", 5),
        ("sellThresholds", 5),
        ("tierSynergyVoteStrengths", 6),
        ("tierSynergyCsStrengths", 4),
    ):
        _list_value = getattr(config, _list_name, None)
        if isinstance(_list_value, list) and len(_list_value) != _expected_len:
            raise ValueError(
                f"{_list_name} 长度必须为 {_expected_len}，实际 {len(_list_value)}"
                "（短 list 运行期越界、长 list 静默截断、VoteStrengths 长度不符会静默回退旧硬编码）"
            )
    for _field in (
        "tierSynergyResonanceVote",
        "tierSynergyRankVote",
        "tierSynergyVolumePriceVote",
        "tierSynergyCrossSectionVote",
        "tierSynergyPriceMomentumVote",
        "tierSynergyDivergenceVote",
    ):
        if getattr(config, _field) < 0:
            raise ValueError(f"synergy 投票权重 {_field} 不能为负（负值翻转票向），实际 {getattr(config, _field)}")
    # P_repool_timeline_gap：degraded 门槛必须落在 [1, momentum_min_samples) 开区间内
    # （>= momentum_min_samples 会吞掉 ok 档；< 1 会让 insufficient 桶永空 = 伪造样本充足）
    _momentum_floor = max(2, max(config.momentumPeriods) + 1)
    if not (1 <= config.degradedSampleFloor < _momentum_floor):
        raise ValueError(
            f"degradedSampleFloor 必须在 [1, momentum_min_samples={_momentum_floor}) 内，"
            f"实际 {config.degradedSampleFloor}"
        )
    # 环境门干预形态枚举与强度校验（2026-09-14 阶段 24 方案 A）
    for _mode_field, _legal in (
        ("lifecycleVetoGateMode", ("hard", "soft", "off")),
        ("lifecycleVetoPathMode", ("all_soft", "reversal_hard", "highrisk_hard")),
        ("lifecycleDowngradeGateMode", ("hard", "soft", "off")),
        ("volumePriceGateMode", ("hard", "soft", "off")),
    ):
        _mode_value = str(getattr(config, _mode_field))
        if _mode_value not in _legal:
            raise ValueError(f"{_mode_field} 非法枚举 {_mode_value!r}（可选 {'/'.join(_legal)}）")
    if config.lifecycleVetoVoteStrength < 0 or config.lifecycleDowngradePenalty < 0:
        raise ValueError(
            f"lifecycleVetoVoteStrength/lifecycleDowngradePenalty 不能为负，"
            f"实际 {config.lifecycleVetoVoteStrength}/{config.lifecycleDowngradePenalty}"
        )
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
