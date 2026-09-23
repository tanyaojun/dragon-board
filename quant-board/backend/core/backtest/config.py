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
    # 阶段 B1 真·移动止盈（2026-09-23 立项，docs/ranktrend-tier-backtest/exit-rules-scan-plan.md，
    # 默认关闭零行为变化，golden 不漂移）：trailingStopActivateGain=null 不启用；启用时
    # peakPrice（按 bar high 粘性记录）相对入场的涨幅 >= activate 后，止损线
    # = max(现线, peakPrice × (1 - trailingStopDrawdown))；peak 粘性 → 激活与止损线均不回退。
    # 生效路径与 breakeven 相同：_exit_prices 止损线（通用链 bar 级 + 全链 intrabar 盘中线）。
    "trailingStopActivateGain": None,
    "trailingStopDrawdown": 0.5,
    # 阶段 B2 断板事件卖出（2026-09-23 立项，默认关闭零行为变化）：持仓期曾触及涨停
    # （bar high 或现价达 limitUpPrice×0.999 容差，粘性）且当前 bar 未封板（price 低于
    # 容差线，或封单 fengdan 归零——fengdan 从原始字段读取，0 是有效信号不视为缺失）
    # → 卖出 reason="断板"；breakBoardMinBars 是总持仓 bar 数门槛（holdingBars >= N
    # 才允许断板卖出，防入场初期噪声）；limitUpPrice 缺失时不判定（fail-visible 不误杀）。
    "breakBoardExit": False,
    "breakBoardMinBars": 1,
}

V5_LIFECYCLE_FUSION_TRADE_DEFAULTS: dict[str, Any] = {
    "minJumpConfidence": 90.0,
    "maxHoldingBars": 30,
    "stopLoss": -0.05,
    # 2026-09-23 用户裁决落默认（阶段 A 终局，docs/ranktrend-tier-backtest/
    # exit-scan-batch3-verdict.md）：tp0.06 × breakeven 0.02 组合 wrxpf 0.9756
    # （基线 0.4824）/ ret +13.52% / maxDD -4.72%。警示（四次复现）：decision 窗
    # （4-7 月）读数与旧默认逐位相同，改善 100% 来自 8 月中后样本外——
    # "平衡市零成本、高波动市保护"定位。端到端锚 bt_1c35ee7c74e441d2。
    "takeProfit": 0.06,
    "breakevenTrailing": True,
    "breakevenThreshold": 0.02,
    "volumeParticipationRate": 0.1,
}
