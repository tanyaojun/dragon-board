# -*- coding: utf-8 -*-
"""SP4-T2 引擎载体测试：source="jev_seq_slot" 两因子制相位解析（设计 §13 授权 + T-jev 证据门）。

覆盖：标签直读/fallback 链/unknown 放行、三因子解析与夹取、mode 无关性、context 归因
（phaseLabel/fallbackUsed，score 侧字段置空）、golden 锚（无键/其他 source 逐位不变）、
全模拟阻断与降仓。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest import TradeSimulator


def _jump_signal(snapshot_id: str, date: str, slot: str, price: float, volume: int = 2_000) -> dict:
    return {
        "snapshotId": snapshot_id, "timestamp": snapshot_id, "tradingDate": date, "slotTime": slot,
        "code": "600001", "name": "测试股", "rank": 8, "price": price, "change": 2, "volume": volume,
        "candidateTier": "A_MAIN", "stage": "ignite", "regime": "strong", "confidence": 90,
        "rankTrend": {
            "jump": {"event": "jump", "direction": "buy", "sustained": True, "confidence": 90},
            "technical": {"macd": {"cross": "golden"},
                          "signals": {"direction": {"signal": "buy"}, "acceleration": {"signal": "buy"}}},
            "meta": {"rawChange": 120},
        },
    }


FRAMES = [
    {"snapshotId": "s1", "timestamp": "s1", "tradingDate": "2026-05-06", "slotTime": "10:30",
     "stocks": [{"code": "600001", "lastPrice": 10.0, "volume": 2000}]},
    {"snapshotId": "s2", "timestamp": "s2", "tradingDate": "2026-05-07", "slotTime": "10:30",
     "stocks": [{"code": "600001", "lastPrice": 10.4, "volume": 2000}]},
    {"snapshotId": "s3", "timestamp": "s3", "tradingDate": "2026-05-08", "slotTime": "10:30",
     "stocks": [{"code": "600001", "lastPrice": 10.8, "volume": 2000}]},
]

BASE = {
    "entryStrategy": "ranktrend_jump",
    "initialCapital": 100000,
    "positionSize": 0.1,
    "maxPositions": 1,
    "maxHoldingBars": 99,
    "enforceT1": True,
    "useOrderBookPrice": False,
    "enforceLimitStatus": False,
    "enforceOrderBookQueue": False,
    "enforceVolumeLimit": True,
    "volumeParticipationRate": 1,
    "feeRate": 0,
    "stampTaxRate": 0,
    "slippageRate": 0,
    "stopLoss": -0.5,
    "takeProfit": 0.5,
}


def _run(trade_config: dict) -> dict:
    return TradeSimulator().run(
        FRAMES, [_jump_signal("s1", "2026-05-06", "10:30", 10.0)], {**BASE, **trade_config})


def _ctrl(**over) -> dict:
    base = {
        "source": "jev_seq_slot",
        "phaseLabels": {"2026-05-06|10:30": "defense"},
        "fallbackLabels": {"2026-05-07": "offense"},
        "offenseFactor": 1.0, "defenseFactor": 0.3, "unknownFactor": 1.0,
    }
    base.update(over)
    return base


def test_jev_factor_direct_hit_offense_and_defense():
    cfg = {"phaseExposureControl": _ctrl(phaseLabels={"2026-05-06|10:30": "offense"})}
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-05-06", "10:30") == 1.0
    cfg2 = {"phaseExposureControl": _ctrl()}  # defense 直读 → 0.3
    assert TradeSimulator._phase_exposure_factor(cfg2, "2026-05-06", "10:30") == 0.3
    # 因子夹取 [0,1]
    cfg3 = {"phaseExposureControl": _ctrl(defenseFactor=1.7)}
    assert TradeSimulator._phase_exposure_factor(cfg3, "2026-05-06", "10:30") == 1.0
    cfg4 = {"phaseExposureControl": _ctrl(defenseFactor=-0.2)}
    assert TradeSimulator._phase_exposure_factor(cfg4, "2026-05-06", "10:30") == 0.0


def test_jev_factor_fallback_chain_and_unknown():
    # 直读未命中 → 日级 fallback（规则 v2 前日口径）
    cfg = {"phaseExposureControl": _ctrl(phaseLabels={})}
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-05-07", "10:30") == 1.0  # fallback offense
    # 双缺 → unknown 放行（缺标签不错杀）
    cfg2 = {"phaseExposureControl": _ctrl(phaseLabels={}, fallbackLabels={})}
    assert TradeSimulator._phase_exposure_factor(cfg2, "2026-05-07", "10:30") == 1.0
    # unknownFactor=0 → 阻断语义可用
    cfg3 = {"phaseExposureControl": _ctrl(phaseLabels={}, fallbackLabels={}, unknownFactor=0.0)}
    assert TradeSimulator._phase_exposure_factor(cfg3, "2026-05-07", "10:30") == 0.0
    # 无 slot 参数 → 直读不可能命中，走 fallback
    assert TradeSimulator._phase_exposure_factor({"phaseExposureControl": _ctrl()}, "2026-05-07") == 1.0


def test_jev_mode_independent_and_other_sources_untouched():
    # jev 源与 mode 无关（source 即模式选择器）
    cfg = {"phaseExposureControl": _ctrl(mode="off")}
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-05-06", "10:30") == 0.3
    # 其他 source 不受 jev 键影响（ladder 语义保持）
    cfg2 = {"phaseExposureControl": {"mode": "ladder", "ladder": [[40, 1.0], [999, 0.3]],
                                     "eodScores": {"2026-05-05": 20.0},
                                     "phaseLabels": {"2026-05-06|10:30": "defense"}, "defenseFactor": 0.0}}
    assert TradeSimulator._phase_exposure_factor(cfg2, "2026-05-06", "10:30") == 1.0


def test_jev_context_attribution_fields():
    ctx = TradeSimulator._phase_context({"phaseExposureControl": _ctrl()}, "2026-05-06", "10:30")
    assert ctx["source"] == "jev_seq_slot"
    assert ctx["phase"] == "defense" and ctx["phaseLabel"] == "defense"
    assert ctx["fallbackUsed"] is False and ctx["factor"] == 0.3
    assert ctx["prevScore"] is None and ctx["band"] is None and ctx["deltaScore"] is None
    # fallback 命中：source 标记 + fallbackUsed=True
    ctx2 = TradeSimulator._phase_context({"phaseExposureControl": _ctrl(phaseLabels={})}, "2026-05-07", "10:30")
    assert ctx2["phase"] == "offense" and ctx2["fallbackUsed"] is True
    # 非 jev 源 context 不携带 jev 专有键（逐位兼容既有研究运行）
    ctx3 = TradeSimulator._phase_context(
        {"phaseExposureControl": {"mode": "ladder", "ladder": [[40, 1.0], [999, 0.3]],
                                  "eodScores": {"2026-05-05": 20.0}}}, "2026-05-06", "10:30")
    assert "phaseLabel" not in ctx3 and "fallbackUsed" not in ctx3


def test_jev_golden_anchor_no_key_identical():
    plain = _run({})
    with_jev_key_absent = _run({"phaseExposureControl": {"mode": "off", "eodScores": {"2026-05-05": 65.0}}})
    assert plain["roundTripTrades"] == with_jev_key_absent["roundTripTrades"]


def test_full_run_jev_blocks_and_scales():
    # defenseFactor=0 → 同槽 defense 标签阻断开仓
    res_block = _run({"phaseExposureControl": _ctrl(defenseFactor=0.0)})
    assert res_block["openPositionCount"] == 0
    assert res_block["matchingDiagnostics"]["blockedByPhase"] >= 1
    # defenseFactor=0.3 → 入场但金额降为基线 30%
    res_scale = _run({"phaseExposureControl": _ctrl()})
    res_base = _run({})
    assert res_scale["openPositionCount"] == 1 and res_base["openPositionCount"] == 1
    scaled_amount = res_scale["openPositions"][0]["entryCost"]
    base_amount = res_base["openPositions"][0]["entryCost"]
    assert abs(scaled_amount - base_amount * 0.3) < 1.0
    # 盖戳归因可达（tradeEvents 入场事件带 entryPhase）
    buy = next(e for e in res_scale["tradeEvents"] if e["action"] == "buy")
    assert buy["entryPhase"]["phaseLabel"] == "defense" and buy["entryPhase"]["fallbackUsed"] is False
