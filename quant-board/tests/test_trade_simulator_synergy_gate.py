"""交易接入 synergy 门（回测方案 §3.3）。

TradeSimulator 消费 synergy.signalTier（signal.rankTrend.observation.synergy.signalTier）：
- synergyEntryTierMin：入场交集门（"none"=不启用；"s"=仅 S；"a"=S/A），默认 "none" 行为不变；
- synergyExitOnDanger：D/E 档强制卖出，默认 False；
- 启用时缺 signalTier → 拦截并计入 matchingDiagnostics.blockedBySynergyTier（fail-visible）。
"""

from __future__ import annotations

from backend.core.backtest import TradeSimulator


def _signal(snapshot_id: str, date: str, price: float, tier: str | None, final_signal: str = "buy") -> dict:
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
        "volume": 100_000,
        "candidateTier": "A_MAIN",
        "stage": "expansion",
        "regime": "strong",
        "confidence": 90,
        "rankTrend": {
            "decision": {"final": {"signal": final_signal, "confidence": 90}},
            "strategy": {"momentum": {"acceleration": 1.0}},
            "observation": {"synergy": {"signalTier": tier, "tierReasons": []} if tier is not None else {}},
        },
    }


def _frame(snapshot_id: str, date: str) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": snapshot_id,
        "tradingDate": date,
        "slotTime": "10:00",
        "price": 10.0,
    }


def _run(frames: list[dict], signals: list[dict], patch: dict) -> dict:
    return TradeSimulator().run(
        frames,
        signals,
        {
            # 阶段6：A_MAIN 降级观察档后默认策略不入场，本组测试验证 A_MAIN 入场的 synergy 门，
            # 改用 a_b_combined 对照组显式保留 A_MAIN 入场（含 momentum confirm 行为）
            "entryStrategy": "a_b_combined",
            "initialCapital": 100000,
            "positionSize": 0.1,
            "maxPositions": 2,
            "maxHoldingBars": 10,
            "enforceT1": True,
            "useOrderBookPrice": False,
            "enforceLimitStatus": False,
            "enforceOrderBookQueue": False,
            "enforceVolumeLimit": False,
            "feeRate": 0,
            "stampTaxRate": 0,
            "slippageRate": 0,
            "stopLoss": -0.5,
            "takeProfit": 0.5,
            **patch,
        },
    )


def test_synergy_gate_disabled_by_default() -> None:
    """默认不启用：synergy 档位不拦截入场（行为与现状一致）。"""
    frames = [_frame("s1", "2026-05-06"), _frame("s2", "2026-05-07")]
    signals = [
        _signal("s1", "2026-05-06", 10.0, "C"),
        _signal("s2", "2026-05-07", 10.5, "C"),
    ]
    result = _run(frames, signals, {})
    assert result["openPositionCount"] == 1  # C 档仍可入场


def test_synergy_entry_gate_s_only() -> None:
    """synergyEntryTierMin="s"：仅 S 档入场，A/C 档被拦截并计数。"""
    frames = [_frame("s1", "2026-05-06"), _frame("s2", "2026-05-07")]
    # A 档：拦截
    blocked = _run(frames, [_signal("s1", "2026-05-06", 10.0, "A")], {"synergyEntryTierMin": "s"})
    assert blocked["openPositionCount"] == 0
    assert blocked["matchingDiagnostics"]["blockedBySynergyTier"] >= 1
    # S 档：入场
    allowed = _run(frames, [_signal("s1", "2026-05-06", 10.0, "S")], {"synergyEntryTierMin": "s"})
    assert allowed["openPositionCount"] == 1


def test_synergy_entry_gate_a_allows_s_and_a() -> None:
    """synergyEntryTierMin="a"：S/A 入场，C 拦截。"""
    frames = [_frame("s1", "2026-05-06"), _frame("s2", "2026-05-07")]
    assert _run(frames, [_signal("s1", "2026-05-06", 10.0, "S")], {"synergyEntryTierMin": "a"})["openPositionCount"] == 1
    assert _run(frames, [_signal("s1", "2026-05-06", 10.0, "A")], {"synergyEntryTierMin": "a"})["openPositionCount"] == 1
    assert _run(frames, [_signal("s1", "2026-05-06", 10.0, "C")], {"synergyEntryTierMin": "a"})["openPositionCount"] == 0


def test_synergy_exit_on_danger_sells_d_tier() -> None:
    """synergyExitOnDanger=True：持仓帧档位 D → 强制卖出，reason 注明四维合并档位。"""
    frames = [_frame("s1", "2026-05-06"), _frame("s2", "2026-05-07")]
    signals = [
        _signal("s1", "2026-05-06", 10.0, "A"),
        _signal("s2", "2026-05-07", 10.5, "D", final_signal="hold"),
    ]
    result = _run(frames, signals, {"synergyExitOnDanger": True})
    assert result["tradeCount"] == 1
    trade = result["roundTripTrades"][0]
    assert trade["action"] == "sell"
    assert "四维合并档位" in (trade.get("reason") or "")


def test_synergy_exit_on_danger_default_off() -> None:
    """默认关闭：D 档不触发卖出（finalSignal=hold 且非 D_EXIT_RISK/排名退出）。"""
    frames = [_frame("s1", "2026-05-06"), _frame("s2", "2026-05-07")]
    signals = [
        _signal("s1", "2026-05-06", 10.0, "A"),
        _signal("s2", "2026-05-07", 10.5, "D", final_signal="hold"),
    ]
    result = _run(frames, signals, {})
    # 未卖出 → 持仓未平 → tradeCount==0（roundTrip 未完成）
    assert result["openPositionCount"] == 1
    assert result["tradeCount"] == 0


def test_synergy_exit_reason_keeps_final_sell_attribution() -> None:
    """finalSignal=sell 与 D 档同时成立：卖出归因保留"compose_decision 卖出信号"（synergy 标签不覆盖）。"""
    frames = [_frame("s1", "2026-05-06"), _frame("s2", "2026-05-07")]
    signals = [
        _signal("s1", "2026-05-06", 10.0, "A"),
        _signal("s2", "2026-05-07", 10.5, "D", final_signal="sell"),
    ]
    result = _run(frames, signals, {"synergyExitOnDanger": True})
    assert result["tradeCount"] == 1
    trade = result["roundTripTrades"][0]
    assert "compose_decision 卖出信号" in (trade.get("reason") or "")


def test_synergy_gate_missing_tier_blocked_and_counted() -> None:
    """启用时缺 signalTier（旧数据/降级）→ 拦截并计入 blockedBySynergyTier（不静默放行）。"""
    frames = [_frame("s1", "2026-05-06"), _frame("s2", "2026-05-07")]
    signals = [_signal("s1", "2026-05-06", 10.0, None)]
    result = _run(frames, signals, {"synergyEntryTierMin": "a"})
    assert result["openPositionCount"] == 0
    assert result["matchingDiagnostics"]["blockedBySynergyTier"] >= 1
