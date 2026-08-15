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
    "maxHoldingBars": 40,
    "minHoldingBars": 0,  # 阶段6 退出结构研究：最小持有帧数，默认 0 不改变行为
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
}

V5_LIFECYCLE_FUSION_TRADE_DEFAULTS: dict[str, Any] = {
    "minJumpConfidence": 90.0,
    "maxHoldingBars": 30,
    "stopLoss": -0.05,
    "takeProfit": 9.99,
    "volumeParticipationRate": 0.1,
}
