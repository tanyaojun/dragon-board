from __future__ import annotations

from typing import Any

DEFAULT_TRADE_CONFIG: dict[str, Any] = {
    "initialCapital": 1000000,
    "maxPositions": 5,
    "positionSize": 0.2,
    "minJumpConfidence": 77.5,
    "feeRate": 0.0003,
    "stampTaxRate": 0.0005,
    "slippageRate": 0.001,
    "maxHoldingBars": 40,
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
}
