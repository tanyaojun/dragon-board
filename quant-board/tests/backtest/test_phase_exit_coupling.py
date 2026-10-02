# -*- coding: utf-8 -*-
"""SP2-T1 per_band 出场参数表测试（章程 §4 SP2-T1；计划 ranktrend-position-sp2-plan.md）。

覆盖：_exit_coupling_overrides 解析/夹界/未命中回退、_effective_max_holding_bars 单一解析、
_exit_prices BE 阈值覆盖消费、全模拟 TP 倍率提前止盈与 maxHolding 覆盖、golden 锚（无键逐位不变）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest import TradeSimulator


def _jump_signal(snapshot_id: str, date: str, price: float, volume: int) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": snapshot_id,
        "tradingDate": date,
        "slotTime": "10:00",
        "code": "600001",
        "name": "测试股",
        "rank": 8,
        "price": price,
        "change": 2,
        "volume": volume,
        "candidateTier": "A_MAIN",
        "stage": "ignite",
        "regime": "strong",
        "confidence": 90,
        "rankTrend": {
            "jump": {"event": "jump", "direction": "buy", "sustained": True, "confidence": 90},
            "technical": {
                "macd": {"cross": "golden"},
                "signals": {"direction": {"signal": "buy"}, "acceleration": {"signal": "buy"}},
            },
            "meta": {"rawChange": 120},
        },
    }


def _frames_with_prices() -> list[dict]:
    return [
        {"snapshotId": "s1", "timestamp": "s1", "tradingDate": "2026-05-06", "slotTime": "10:00",
         "stocks": [{"code": "600001", "lastPrice": 10.0, "volume": 2000}]},
        {"snapshotId": "s2", "timestamp": "s2", "tradingDate": "2026-05-07", "slotTime": "10:00",
         "stocks": [{"code": "600001", "lastPrice": 10.4, "volume": 2000}]},
        {"snapshotId": "s3", "timestamp": "s3", "tradingDate": "2026-05-08", "slotTime": "10:00",
         "stocks": [{"code": "600001", "lastPrice": 10.8, "volume": 2000}]},
        {"snapshotId": "s4", "timestamp": "s4", "tradingDate": "2026-05-09", "slotTime": "10:00",
         "stocks": [{"code": "600001", "lastPrice": 11.0, "volume": 2000}]},
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
    "takeProfit": 0.05,
}

ENTRY_STRONG = {"phaseExposureControl": {"mode": "off", "eodScores": {"2026-05-05": 65.0}}}


def _run(trade_config: dict) -> dict:
    return TradeSimulator().run(
        _frames_with_prices(),
        [_jump_signal("s1", "2026-05-06", 10.0, 2_000)],
        {**BASE, **ENTRY_STRONG, **trade_config},
    )


# ── 单元：解析/夹界/回退 ──


def test_overrides_per_band_hit_and_miss():
    eod = {"2026-05-05": 65.0}
    cfg = {"phaseExitCoupling": {"mode": "per_band", "bands": {"强60-80": {"tpMultiplier": 0.8, "maxHoldingBars": 30}}, "eodScores": eod}}
    out = TradeSimulator._exit_coupling_overrides(cfg, "2026-05-06")
    assert out == {"exitTpMultiplier": 0.8, "exitMaxHoldingBars": 30}
    assert TradeSimulator._exit_coupling_overrides(cfg, "2026-05-06", ) != {}  # 自包含：不依赖 phaseExposureControl
    weak = {**cfg, "phaseExitCoupling": {**cfg["phaseExitCoupling"], "eodScores": {"2026-05-05": 50.0}}}
    assert TradeSimulator._exit_coupling_overrides(weak, "2026-05-06") == {}  # 未命中带
    assert TradeSimulator._exit_coupling_overrides({"phaseExitCoupling": {"mode": "per_band", "bands": {"强60-80": {"tpMultiplier": 0.8}}}}, "2026-05-06") == {}  # 无 eodScores → 缺分不动作
    assert TradeSimulator._exit_coupling_overrides({}, "2026-05-06") == {}  # 无键


def test_overrides_mode_cold_tp_widen_not_consumed_here():
    """cold_tp_widen 走旧路径（_exit_tp_multiplier），per_band 解析器不消费。"""
    cfg = {"phaseExitCoupling": {"mode": "cold_tp_widen", "multiplier": 1.5, "bandLow": 10.0, "bandHigh": 40.0}}
    assert TradeSimulator._exit_coupling_overrides(cfg, "2026-05-06") == {}


def test_overrides_clamps():
    cfg = {"phaseExitCoupling": {"mode": "per_band", "bands": {"强60-80": {
        "tpMultiplier": 9.0, "breakevenThreshold": 9.0, "maxHoldingBars": 0.5}},
        "eodScores": {"2026-05-05": 65.0}}}
    out = TradeSimulator._exit_coupling_overrides(cfg, "2026-05-06")
    assert out["exitTpMultiplier"] == 3.0
    assert out["exitBreakevenThreshold"] == 0.5
    assert out["exitMaxHoldingBars"] == 1


def test_effective_max_holding_bars_resolution():
    cfg = {"maxHoldingBars": 40}
    assert TradeSimulator._effective_max_holding_bars({"exitMaxHoldingBars": 30}, cfg) == 30
    assert TradeSimulator._effective_max_holding_bars({}, cfg) == 40
    assert TradeSimulator._effective_max_holding_bars({"exitMaxHoldingBars": "bad"}, cfg) == 40  # 非法回退
    assert TradeSimulator._effective_max_holding_bars({"exitMaxHoldingBars": None}, cfg) == 40


def test_exit_prices_consumes_be_threshold_override():
    cfg = {"breakevenTrailing": True, "breakevenThreshold": 0.02, "stopLoss": -0.06, "takeProfit": 0.5}
    pos_low = {"entryPrice": 10.0, "exitBreakevenThreshold": 0.01}
    pos_none = {"entryPrice": 10.0}
    # 阈值 0.01 + gross 1.5% → 激活保本；默认 0.02 → 不激活
    _, _, notes_low = TradeSimulator._exit_prices(pos_low, {}, cfg, gross_return=0.015)
    _, _, notes_none = TradeSimulator._exit_prices(pos_none, {}, cfg, gross_return=0.015)
    assert "breakeven" in notes_low
    assert "breakeven" not in notes_none


# ── 全模拟：消费端到端 ──


def test_per_band_tp_multiplier_exits_earlier():
    baseline = _run({})
    coupled = _run({"phaseExitCoupling": {"mode": "per_band", "bands": {"强60-80": {"tpMultiplier": 0.5}},
                                          "eodScores": {"2026-05-05": 65.0}}})
    # 路径 s2 +4% / s3 +8%；TP 5%：baseline s3 触发；0.5×→2.5%：coupled s2 触发
    assert baseline["roundTripTrades"][0]["exitTradingDate"] == "2026-05-08"
    assert coupled["roundTripTrades"][0]["exitTradingDate"] == "2026-05-07"
    assert coupled["roundTripTrades"][0]["reason"] == "止盈"
    assert baseline["roundTripTrades"][0]["reason"] == "止盈"


def test_per_band_standalone_without_exposure_control():
    """评审 P0-1 回归锚：per_band 单独启用（无 phaseExposureControl）必须盖章并消费。"""
    coupled = TradeSimulator().run(
        _frames_with_prices(),
        [_jump_signal("s1", "2026-05-06", 10.0, 2_000)],
        {**BASE, "takeProfit": 0.05,
         "phaseExitCoupling": {"mode": "per_band", "bands": {"强60-80": {"tpMultiplier": 0.5}},
                               "eodScores": {"2026-05-05": 65.0}}})
    assert coupled["tradeCount"] == 1
    assert coupled["roundTripTrades"][0]["exitTradingDate"] == "2026-05-07"  # 0.5×→2.5% 提前止盈
    assert coupled["roundTripTrades"][0]["reason"] == "止盈"


def test_per_band_max_holding_override_exits_earlier():
    # 关 TP（0.5 不会触发），隔离 max-hold 行为
    baseline = _run({"takeProfit": 0.5})  # maxHoldingBars=99 → 期末仍持仓
    assert baseline["tradeCount"] == 0 and baseline["openPositionCount"] == 1
    coupled = _run({"takeProfit": 0.5, "phaseExitCoupling": {"mode": "per_band", "bands": {"强60-80": {"maxHoldingBars": 2}},
                                                             "eodScores": {"2026-05-05": 65.0}}})
    assert coupled["tradeCount"] == 1
    assert coupled["roundTripTrades"][0]["exitTradingDate"] == "2026-05-08"  # s3 holdingBars=2
    assert coupled["roundTripTrades"][0]["reason"] == "到达最大持有快照"


def test_golden_anchor_no_coupling_key_identical():
    plain = _run({})
    off = _run({"phaseExitCoupling": {"mode": "per_band", "bands": {}}})
    assert plain["roundTripTrades"] == off["roundTripTrades"]
    assert plain["tradeEvents"] == off["tradeEvents"]
    assert [p["equity"] for p in plain["equityCurve"]] == [p["equity"] for p in off["equityCurve"]]
