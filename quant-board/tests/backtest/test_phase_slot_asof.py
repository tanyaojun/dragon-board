# -*- coding: utf-8 -*-
"""SP3-T3.2 slot 级 as-of 相位分数测试（证据门 slot-asof-diff.json 达标后解锁的载体）。

覆盖：_phase_score 解析（slot 命中/回退/缺分）、factor 与 context 的 slot 消费、
source/usedSlot 归因、golden 锚（source 缺省=prev_eod 行为逐位不变）、全模拟 slot 阻断/放行。
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


def test_phase_score_slot_hit_and_fallback():
    ctrl = {
        "source": "slot_then_prev_eod",
        "eodScores": {"2026-05-05": 65.0},
        "slotScores": {"2026-05-06": {"09:30": 20.0, "10:00": 42.0}},
    }
    # 入场槽 10:30 → 同日严格更早最近档 = 10:00 → 42
    key, score = TradeSimulator._phase_score(ctrl, "2026-05-06", "10:30")
    assert key == "2026-05-06|10:00" and score == 42.0
    # 入场槽 09:30 → 同日无更早档 → 回退前日 EOD
    key2, score2 = TradeSimulator._phase_score(ctrl, "2026-05-06", "09:30")
    assert key2 == "2026-05-05" and score2 == 65.0
    # 无 slotScores → 回退前日 EOD
    ctrl2 = {"source": "slot_then_prev_eod", "eodScores": {"2026-05-05": 65.0}}
    assert TradeSimulator._phase_score(ctrl2, "2026-05-06", "10:30") == ("2026-05-05", 65.0)
    # source 缺省 → 永远走前日 EOD（slotScores 被忽略）
    ctrl3 = {"eodScores": {"2026-05-05": 65.0}, "slotScores": {"2026-05-06": {"09:30": 20.0}}}
    assert TradeSimulator._phase_score(ctrl3, "2026-05-06", "10:30") == ("2026-05-05", 65.0)


def test_factor_slot_overrides_ladder():
    cfg = {
        "phaseExposureControl": {
            "mode": "ladder", "ladder": [[40, 0.0], [999, 1.0]],
            "source": "slot_then_prev_eod",
            "eodScores": {"2026-05-05": 65.0},  # 前日 EOD 65 → 1d 口径 factor 1.0
            "slotScores": {"2026-05-06": {"09:30": 20.0}},  # slot 20 → 冷带 factor 0
        }
    }
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-05-06", "10:30") == 0.0
    # 同帧无 slot 参数（如旧调用）→ prev_eod 行为
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-05-06") == 1.0


def test_context_source_and_used_slot():
    cfg = {"phaseExposureControl": {
        "mode": "ladder", "ladder": [[40, 1.0], [999, 0.3]],
        "source": "slot_then_prev_eod",
        "eodScores": {"2026-05-05": 65.0, "2026-05-04": 50.0},
        "slotScores": {"2026-05-06": {"09:30": 20.0}},
    }}
    ctx = TradeSimulator._phase_context(cfg, "2026-05-06", "10:30")
    assert ctx["source"] == "slot_then_prev_eod"
    assert ctx["usedSlot"] == "09:30"
    assert ctx["prevScore"] == 20.0 and ctx["band"] == "冷10-40"
    # Δ 恒用 EOD 日链（与 slot 分无关）：65 − 50 = 15
    assert ctx["deltaScore"] == 15.0
    assert ctx["factor"] == 1.0  # ladder [40,1.0]：slot 分 20 < 40 → 满仓


def test_golden_anchor_default_source_identical():
    eod = {"2026-05-05": 65.0, "2026-05-06": 45.0}
    plain = _run({"phaseExposureControl": {"mode": "ladder", "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]],
                                          "eodScores": eod}})
    with_source = _run({"phaseExposureControl": {"mode": "ladder", "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]],
                                                 "source": "prev_eod", "eodScores": eod}})
    assert plain["roundTripTrades"] == with_source["roundTripTrades"]
    assert plain["tradeEvents"] == with_source["tradeEvents"]


def test_full_run_slot_blocks_entry():
    eod = {"2026-05-05": 65.0, "2026-05-06": 45.0}
    base = {"mode": "ladder", "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]], "eodScores": eod}
    # prev_eod 口径：入场 05-06 前日 65 → 三成仓 → 成交（持仓期末未平 → openPositions）
    res_prev = _run({"phaseExposureControl": {**base}})
    assert res_prev["openPositionCount"] == 1
    # slot 口径：同日 09:30 档 45 ∈[40,60) → factor 0 → 阻断
    slot_cfg = {**base, "source": "slot_then_prev_eod", "slotScores": {"2026-05-06": {"09:30": 45.0}}}
    res_slot = _run({"phaseExposureControl": slot_cfg})
    assert res_slot["openPositionCount"] == 0
    assert res_slot["matchingDiagnostics"]["blockedByPhase"] >= 1
