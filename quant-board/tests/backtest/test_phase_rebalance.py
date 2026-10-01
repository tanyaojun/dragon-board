# -*- coding: utf-8 -*-
"""SP2-T2 相位调仓测试（章程 §4 SP2-T2；v1 规则=仅前日带下移入冷→清仓，历史反事实验证选定）。

覆盖：_phase_rebalance_triggered 触发矩阵（X→冷 触发 / →弱、上移、冷带豁免、缺归因、
缺分、禁用不动作）、全模拟入冷清仓端到端（含 rebalance 子文档与 reason）、T+1 同日不触发、
golden 锚（无键/enabled=False 逐位不变）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest import TradeSimulator


def _jump_signal(snapshot_id: str, date: str, slot: str, price: float, volume: int = 2_000) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": snapshot_id,
        "tradingDate": date,
        "slotTime": slot,
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


def _frames() -> list[dict]:
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
    "takeProfit": 0.5,
}


def _run(trade_config: dict, frames: list[dict] | None = None) -> dict:
    return TradeSimulator().run(
        frames if frames is not None else _frames(),
        [_jump_signal("s1", "2026-05-06", "10:00", 10.0)],
        {**BASE, "phaseExposureControl": {"mode": "off", "eodScores": trade_config.get("_eod", {})},
         **{k: v for k, v in trade_config.items() if k != "_eod"}},
    )


def _rb(eod: dict, **extra) -> dict:
    return {"phaseRebalance": {"enabled": True, "actOn": "into_cold_clear", "eodScores": eod, **extra}}


# ── 单元：触发矩阵 ──


def test_trigger_matrix():
    """eod 驱动矩阵（自包含：入场带/当前带都从 rb.eodScores 严格前日解）。"""

    def pos(ed: str) -> dict:
        return {"entryTradingDate": ed}

    def rb(eod: dict, **extra) -> dict:
        return {"phaseRebalance": {"enabled": True, "actOn": "into_cold_clear", "eodScores": eod, **extra}}

    # X→冷：强/极热/弱 入场（入场前日 65/85/50）→ 当前日前日 30 → 触发
    for entry_prev in (65.0, 85.0, 50.0):
        eod = {"2026-05-05": entry_prev, "2026-05-06": 30.0}
        assert TradeSimulator._phase_rebalance_triggered(rb(eod), pos("2026-05-06"), "2026-05-07")
    # 冷带入场豁免（慢牛区机制）：入场前日 30
    eod_cold = {"2026-05-05": 30.0, "2026-05-06": 30.0}
    assert not TradeSimulator._phase_rebalance_triggered(rb(eod_cold), pos("2026-05-06"), "2026-05-07")
    assert TradeSimulator._phase_rebalance_triggered(
        rb(eod_cold, coldEntryExempt=False), pos("2026-05-06"), "2026-05-07")
    # →弱 / →强 / 上移：不动作（v1 数据裁决：→弱 18 笔不动作完胜）
    assert not TradeSimulator._phase_rebalance_triggered(
        rb({"2026-05-05": 65.0, "2026-05-06": 50.0}), pos("2026-05-06"), "2026-05-07")
    assert not TradeSimulator._phase_rebalance_triggered(
        rb({"2026-05-05": 30.0, "2026-05-06": 65.0}), pos("2026-05-06"), "2026-05-07")
    # 缺分（当前日前日缺）/ 禁用 / actOn 不符 / 无键
    assert not TradeSimulator._phase_rebalance_triggered(
        rb({"2026-05-05": 65.0, "2026-05-06": None}), pos("2026-05-06"), "2026-05-07")
    assert not TradeSimulator._phase_rebalance_triggered(
        {"phaseRebalance": {"enabled": False, "actOn": "into_cold_clear", "eodScores": {"2026-05-05": 30.0}}},
        pos("2026-05-06"), "2026-05-07")
    assert not TradeSimulator._phase_rebalance_triggered(
        {"phaseRebalance": {"enabled": True, "actOn": "halve", "eodScores": {"2026-05-05": 30.0}}},
        pos("2026-05-06"), "2026-05-07")
    assert not TradeSimulator._phase_rebalance_triggered({}, pos("2026-05-06"), "2026-05-07")


# ── 全模拟：入冷清仓端到端 ──


def test_full_run_cold_downgrade_clears_with_annotation():
    eod = {"2026-05-05": 65.0, "2026-05-06": 62.0, "2026-05-07": 55.0, "2026-05-08": 30.0}
    cfg = _rb(eod)
    cfg["_eod"] = eod
    res = _run(cfg)
    # s2 prev=05-06 62 强带不动作；s3 prev=05-07 55 弱带不动作；s4 prev=05-08 30 冷带 → 清仓
    assert res["tradeCount"] == 1
    rt = res["roundTripTrades"][0]
    assert rt["reason"] == "相位调仓(入冷清仓)"
    assert rt["exitTradingDate"] == "2026-05-09"
    assert rt["rebalance"] == {"from": "强60-80", "to": "冷10-40", "factor": 0.0}
    assert res["openPositionCount"] == 0


def test_full_run_weak_downgrade_no_action():
    eod = {"2026-05-05": 65.0, "2026-05-06": 62.0, "2026-05-07": 55.0, "2026-05-08": 45.0}
    cfg = _rb(eod)
    cfg["_eod"] = eod
    res = _run(cfg)
    assert res["tradeCount"] == 0
    assert res["openPositionCount"] == 1  # →弱 不动作，持仓保留


def test_full_run_t1_same_day_not_triggered():
    # 判别力构造（评审 P2-7）：coldEntryExempt=False + 入场当日已入冷，
    # 使 s2 同日帧在无 T+1 时结构上必然触发 → T+1 门被真实验证
    eod = {"2026-05-05": 30.0, "2026-05-06": 30.0}
    cfg = _rb(eod, coldEntryExempt=False)
    cfg["_eod"] = eod
    frames = [
        {"snapshotId": "s1", "timestamp": "s1", "tradingDate": "2026-05-06", "slotTime": "10:00",
         "stocks": [{"code": "600001", "lastPrice": 10.0, "volume": 2000}]},
        {"snapshotId": "s2", "timestamp": "s2", "tradingDate": "2026-05-06", "slotTime": "11:00",
         "stocks": [{"code": "600001", "lastPrice": 10.2, "volume": 2000}]},
        {"snapshotId": "s3", "timestamp": "s3", "tradingDate": "2026-05-07", "slotTime": "10:00",
         "stocks": [{"code": "600001", "lastPrice": 10.4, "volume": 2000}]},
    ]
    res = _run(cfg, frames)
    # s2 与入场同日 → T+1 门跳过（无 T+1 此帧必触发）；s3 次日 prev=05-06 30 → 清仓
    assert res["tradeCount"] == 1
    assert res["roundTripTrades"][0]["exitTradingDate"] == "2026-05-07"
    # 归因溯源（评审 P2-3）：standalone 臂下 from 来自触发器自算入场带
    assert res["roundTripTrades"][0]["rebalance"]["from"] == "冷10-40"


def test_golden_anchor_no_rebalance_key_identical():
    plain = _run({})
    off = _run({"phaseRebalance": {"enabled": False, "actOn": "into_cold_clear", "eodScores": {"2026-05-05": 30.0}}})
    assert plain["roundTripTrades"] == off["roundTripTrades"]
    assert plain["tradeEvents"] == off["tradeEvents"]
    assert [p["equity"] for p in plain["equityCurve"]] == [p["equity"] for p in off["equityCurve"]]
