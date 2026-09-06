from __future__ import annotations

from typing import Any

DEFAULT_TRADE_CONFIG: dict[str, Any] = {
    "initialCapital": 1000000,
    "maxPositions": 5,
    "positionSize": 0.2,
    "minJumpConfidence": 90.0,
    "feeRate": 0.0003,
    "stampTaxRate": 0.0005,
    "slippageRate": 0.001,
    "fallbackSlippageRate": 0.001,  # 快照退化成交（fillFallbackMode=fallback_penalized）额外滑点罚（WP3.1 定值）
    "maxHoldingBars": 40,
    "minHoldingBars": 0,  # 阶段6 退出结构研究：最小持有帧数，默认 0 不改变行为
    "signalExitDelayBars": 0,  # 阶段6 方向2 信号驱动退出去噪：最小持有期内抑制信号驱动退出，默认 0 不改变行为
    "targetHoldingDays": 5.0,
    "enforceT1": True,
    "executionMode": "current_bar",
    "stopLoss": -0.06,
    "takeProfit": 0.12,
    "useOrderBookPrice": True,
    "enforceLimitStatus": True,
    "enforceVolumeLimit": True,
    "enforceOrderBookQueue": True,
    "allowPartialFills": True,
    "volumeParticipationRate": 0.05,
    "orderBookParticipationRate": 0.3,
    "useIntrabarStops": True,
    "intrabarAmbiguity": "stop_first",
    # 策略层改进（全部默认关闭，开启时行为变更，见 tests/test_trade_simulator_entry_refinements.py）
    "entryMomentumConfirm": "off",
    "useAtrStops": False,
    "atrStopMultiplier": 2.0,
    "atrTakeMultiplier": 3.0,
    "breakevenTrailing": False,
    "breakevenThreshold": 0.02,
    "tierPositionScale": False,
    "tierPositionScales": {"S": 1.0, "A": 1.0, "B": 0.5},
    "synergyExitOnDowngrade": False,
    "synergyDowngradeSteps": 2,
    # 阶段6 趋势反转 × jump 新买点候选（趋势反转层入场，默认关闭不改变现状）：
    # 开启后 entryStrategy="trend_reversal_jump" 要求 trendReversal ∧ jump buy ∧ mag≥min 且 fresh≥min
    "trendReversalJumpMagMin": 20.0,
    "trendReversalJumpFreshMin": 0.0,
    # 排名恶化退出判定字段（阶段6 修复）：默认 "rank" 保持现状（重排序号>50）；
    # 低位弱转强策略（trend_reversal_jump）建议 "avgranknum"——相对恶化：
    # 当前 avgRankNum 比入场时恶化超过 avgRankNumExitDelta（默认 20 个百分点）才退出
    # （绝对阈值 avgRankNumExitMax 2026-08-16 实测证伪，改为相对增量语义）
    "rankExitField": "rank",
    "avgRankNumExitDelta": 20.0,
    # 弱势状态退出（2026-08-16 拐头向下研究立项，默认关闭零行为变化）：
    # weakStateExit=True 时，D_EXIT_RISK 档位不再直接触发退出（低分位预测反弹 0.5264，
    # 过早离场），改由"持续弱势状态"触发——放量下跌(quadrant=fall_volume) 或
    # 资金强流出(zljzb < weakStateExitZljzb，默认 -5) 预测继续下跌（winRate 0.4778/0.4832）。
    "weakStateExit": False,
    "weakStateExitZljzb": -5.0,
}

V5_LIFECYCLE_FUSION_TRADE_DEFAULTS: dict[str, Any] = {
    "minJumpConfidence": 90.0,
    "maxHoldingBars": 30,
    "stopLoss": -0.05,
    "takeProfit": 9.99,
    "volumeParticipationRate": 0.1,
}
