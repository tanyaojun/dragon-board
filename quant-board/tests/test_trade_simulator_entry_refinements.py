"""交易模拟器入场/退出精细化（策略层改进方向 1/3/4）。

TradeSimulator 新增（全部默认关闭，行为与现状一致）：
- entryMomentumConfirm="short_positive"：A_MAIN 入场要求 momentum.short > 0（方向1：入场时机过滤）
- useAtrStops：止损/止盈价 = entry ∓ 倍数×ATR(14)，缺历史数据回退固定百分比（方向3）
- breakevenTrailing：盈利达 breakevenThreshold 后止损上移至入场价（方向3）
- tierPositionScale：按 synergy 档位缩放入场仓位（S/A 满仓、B 半仓）（方向4）
- synergyExitOnDowngrade：持仓档位相对入场档位降 >= synergyDowngradeSteps 档退出（方向4）
"""

from __future__ import annotations

from backend.core.backtest import TradeSimulator


def _signal(
    snapshot_id: str,
    date: str,
    price: float,
    *,
    tier: str | None = None,
    final_signal: str = "buy",
    momentum_short: float = 5.0,
    candidate_tier: str = "A_MAIN",
) -> dict:
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
        "candidateTier": candidate_tier,
        "stage": "expansion",
        "regime": "strong",
        "confidence": 90,
        "rankTrend": {
            "decision": {"final": {"signal": final_signal, "confidence": 90}},
            "strategy": {"momentum": {"short": momentum_short, "mid": 2.0, "long": 1.0, "acceleration": 1.0}},
            "observation": {"synergy": {"signalTier": tier, "tierReasons": []} if tier is not None else {}},
        },
    }


def _frame(snapshot_id: str, date: str, price: float = 10.0) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": snapshot_id,
        "tradingDate": date,
        "slotTime": "10:00",
        "price": price,
    }


def _frame_with_stock(snapshot_id: str, date: str, code: str, high: float, low: float, close: float) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": snapshot_id,
        "tradingDate": date,
        "slotTime": "10:00",
        "price": close,
        "stocks": [
            {
                "code": code,
                "name": "测试股",
                "high": high,
                "low": low,
                "close": close,
                "lastTradePrice": close,
                "price": close,
            }
        ],
    }


def _run(frames: list[dict], signals: list[dict], patch: dict) -> dict:
    return TradeSimulator().run(
        frames,
        signals,
        {
            # 阶段6 业务口径：默认策略 rank_trend_candidate 不再入场 A_MAIN（观察档）；
            # 本组测试验证 A_MAIN 入场后的交易行为开关，改用 a_b_combined 对照组策略
            # 显式保留 A_MAIN 入场（含 momentum confirm 行为，与旧默认路径一致）。
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
            "stopLoss": -0.06,
            "takeProfit": 0.12,
            **patch,
        },
    )


# ---------- 方向1：入场 momentum 确认 ----------


def test_entry_momentum_confirm_off_by_default() -> None:
    """默认关闭：momentum.short <= 0 的 A_MAIN 仍可入场（回归）。"""
    frames = [_frame("s1", "2026-05-06"), _frame("s2", "2026-05-07")]
    signals = [
        _signal("s1", "2026-05-06", 10.0, momentum_short=-5.0),
        _signal("s2", "2026-05-07", 10.1, momentum_short=-5.0),
    ]
    result = _run(frames, signals, {})
    assert result["openPositionCount"] == 1


def test_entry_momentum_confirm_filters_short_negative() -> None:
    """entryMomentumConfirm=short_positive：momentum.short <= 0 的 A_MAIN 被过滤不入场。"""
    frames = [_frame("s1", "2026-05-06"), _frame("s2", "2026-05-07")]
    signals = [
        _signal("s1", "2026-05-06", 10.0, momentum_short=-5.0),
        _signal("s2", "2026-05-07", 10.1, momentum_short=-5.0),
    ]
    result = _run(frames, signals, {"entryMomentumConfirm": "short_positive"})
    assert result["openPositionCount"] == 0


def test_entry_momentum_confirm_passes_short_positive() -> None:
    """entryMomentumConfirm=short_positive：momentum.short > 0 的 A_MAIN 正常入场。"""
    frames = [_frame("s1", "2026-05-06"), _frame("s2", "2026-05-07")]
    signals = [
        _signal("s1", "2026-05-06", 10.0, momentum_short=5.0),
        _signal("s2", "2026-05-07", 10.1, momentum_short=5.0),
    ]
    result = _run(frames, signals, {"entryMomentumConfirm": "short_positive"})
    assert result["openPositionCount"] == 1


# ---------- 方向3：保本移动止损 ----------


def test_breakeven_trailing_raises_stop_to_entry() -> None:
    """breakevenTrailing：盈利达阈值后回落到入场价下方触发保本止损。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.3),  # +3% >= breakevenThreshold
        _frame("s3", "2026-05-08", 9.98),  # 回落到入场价下方
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0),
        _signal("s2", "2026-05-07", 10.3),
        _signal("s3", "2026-05-08", 9.98, final_signal="hold"),  # hold：验证止损退出，不重新入场
    ]
    result = _run(frames, signals, {"breakevenTrailing": True, "breakevenThreshold": 0.02})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["reason"] == "止损" or "保本" in result["roundTripTrades"][0]["reason"]


def test_breakeven_disabled_by_default() -> None:
    """默认关闭：盈利后回落到入场价下方不触发（仍持有，回归）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.3),
        _frame("s3", "2026-05-08", 9.98),
    ]
    signals = [_signal(s, d, p) for s, d, p in (("s1", "2026-05-06", 10.0), ("s2", "2026-05-07", 10.3), ("s3", "2026-05-08", 9.98))]
    result = _run(frames, signals, {})
    assert result["openPositionCount"] == 1


# ---------- 方向3：ATR 自适应止损 ----------


def _atr_frames() -> tuple[list[dict], list[dict]]:
    """14+ 根 K 线，TR 稳定 0.1（high=entry+0.05/low=entry-0.05），ATR≈0.1。"""
    frames: list[dict] = []
    signals: list[dict] = []
    dates = [f"2026-05-{d:02d}" for d in range(6, 25)]
    for i, date in enumerate(dates):
        price = 10.0
        frames.append(_frame_with_stock(f"s{i}", date, "600001", price + 0.05, price - 0.05, price))
        signals.append(_signal(f"s{i}", date, price))
    return frames, signals


def test_atr_stops_trigger_earlier_than_fixed_pct() -> None:
    """useAtrStops：ATR≈0.1、atrStopMultiplier=2 → 止损价 9.79；跌到 9.70（-3%）触发 ATR 止损但未到固定 -6%。"""
    frames, signals = _atr_frames()
    frames[-1] = _frame_with_stock("s19", "2026-05-24", "600001", 9.75, 9.70, 9.70)
    signals[-1] = _signal("s19", "2026-05-24", 9.70, final_signal="hold")
    result = _run(frames, signals, {"useAtrStops": True, "atrStopMultiplier": 2.0, "atrTakeMultiplier": 3.0, "maxHoldingBars": 40})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["reason"] == "止损"


def test_atr_stops_fallback_without_history() -> None:
    """无价格历史时回退固定百分比止损，不报错（fail-visible）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 9.85),  # -1.5%，未到固定 -6%
    ]
    signals = [_signal("s1", "2026-05-06", 10.0), _signal("s2", "2026-05-07", 9.85)]
    result = _run(frames, signals, {"useAtrStops": True, "atrStopMultiplier": 2.0})
    assert result["openPositionCount"] == 1  # 固定止损 -6% 未触发，继续持有


# ---------- 方向4：档位联动仓位 ----------


def test_tier_position_scale_b_half_size() -> None:
    """tierPositionScale：B 档入场仓位为 S/A 档的一半（fee=0 时精确 0.5）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="B"),
        _signal("s2", "2026-05-07", 10.1, tier="B"),
    ]
    base = _run(frames, signals, {})
    scaled = _run(frames, signals, {"tierPositionScale": True, "tierPositionScales": {"S": 1.0, "A": 1.0, "B": 0.5}})
    assert base["openPositionCount"] == 1 and scaled["openPositionCount"] == 1
    base_qty = base["openPositions"][0]["quantity"]
    scaled_qty = scaled["openPositions"][0]["quantity"]
    assert scaled_qty == base_qty // 2  # B 档半仓


def test_tier_position_scale_disabled_by_default() -> None:
    """默认关闭：B 档与 S/A 档同仓位（回归）。"""
    frames = [_frame("s1", "2026-05-06", 10.0), _frame("s2", "2026-05-07", 10.1)]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="B"),
        _signal("s2", "2026-05-07", 10.1, tier="B"),
    ]
    result = _run(frames, signals, {})
    assert result["openPositions"][0]["quantity"] == 1000  # 10% 仓位满额（fee=0）


# ---------- 方向4：连续降级退出 ----------


def test_synergy_exit_on_downgrade_two_steps() -> None:
    """synergyExitOnDowngrade：入场 A，持仓期降到 C（降 2 档）触发退出。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
        _frame("s3", "2026-05-08", 10.2),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="A"),
        _signal("s2", "2026-05-07", 10.1, tier="B"),
        _signal("s3", "2026-05-08", 10.2, tier="C", final_signal="hold"),
    ]
    result = _run(frames, signals, {"synergyExitOnDowngrade": True, "synergyDowngradeSteps": 2})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1


def test_synergy_exit_on_downgrade_one_step_holds() -> None:
    """synergyExitOnDowngrade：入场 A，持仓期降到 B（降 1 档）不退出。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="A"),
        _signal("s2", "2026-05-07", 10.1, tier="B"),
    ]
    result = _run(frames, signals, {"synergyExitOnDowngrade": True, "synergyDowngradeSteps": 2})
    assert result["openPositionCount"] == 1


def test_synergy_exit_on_downgrade_disabled_by_default() -> None:
    """默认关闭：入场 A 持仓期降到 C 不退出（回归）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
        _frame("s3", "2026-05-08", 10.2),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="A"),
        _signal("s2", "2026-05-07", 10.1, tier="B"),
        _signal("s3", "2026-05-08", 10.2, tier="C"),
    ]
    result = _run(frames, signals, {})
    assert result["openPositionCount"] == 1


# ---------- 方向5：最小持有帧数（minHoldingBars，默认 0 不改变行为）----------


def test_min_holding_bars_disabled_by_default() -> None:
    """默认不设 minHoldingBars：D_EXIT_RISK 信号第 2 帧正常退出（行为不变回归）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
        _frame("s3", "2026-05-08", 10.2),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        _signal("s2", "2026-05-07", 10.1, tier="S", candidate_tier="D_EXIT_RISK"),
    ]
    result = _run(frames, signals, {})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1


def test_min_holding_bars_holds_through_exit_signals() -> None:
    """minHoldingBars=3：前 3 帧 D_EXIT_RISK 不退出，第 4 帧（holdingBars>=3）才退出。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
        _frame("s3", "2026-05-08", 10.2),
        _frame("s4", "2026-05-09", 10.3),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        _signal("s2", "2026-05-07", 10.1, tier="S", candidate_tier="D_EXIT_RISK"),
        _signal("s3", "2026-05-08", 10.2, tier="S", candidate_tier="D_EXIT_RISK"),
        _signal("s4", "2026-05-09", 10.3, tier="S", candidate_tier="D_EXIT_RISK"),
    ]
    result = _run(frames, signals, {"minHoldingBars": 3})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1
    trade = result["roundTripTrades"][0]
    assert trade["holdingBars"] == 3


def test_min_holding_bars_blocks_stop_loss() -> None:
    """minHoldingBars=3：s2/s3 触发止损（-6%）也不退出，s4（期满）止损生效退出。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 9.0),  # -10% 触发止损，但 min 期内强制持有
        _frame("s3", "2026-05-08", 9.2),  # -8% 仍触发，仍强制持有
        _frame("s4", "2026-05-09", 9.3),  # -7% 期满后止损生效
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        _signal("s2", "2026-05-07", 9.0, tier="S"),
        _signal("s3", "2026-05-08", 9.2, tier="S"),
        # s4 用 D_EXIT_RISK：期满后止损生效退出，且该帧不再满足入场条件（避免同帧重入）
        _signal("s4", "2026-05-09", 9.3, tier="S", candidate_tier="D_EXIT_RISK"),
    ]
    result = _run(frames, signals, {"minHoldingBars": 3})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1
    trade = result["roundTripTrades"][0]
    assert trade["holdingBars"] == 3
    # 止损被延后：退出价格是 s4 的 9.3 而非 s2 的 9.0
    assert trade["exitPrice"] == 9.3


def test_min_holding_bars_blocks_max_holding_and_downgrade() -> None:
    """minHoldingBars 优先于 maxHoldingBars 与 synergy 降档：最小持有期内均不退出，期满后降档退出。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
        _frame("s3", "2026-05-08", 10.2),
        _frame("s4", "2026-05-09", 10.3),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        _signal("s2", "2026-05-07", 10.1, tier="B", final_signal="sell"),
        _signal("s3", "2026-05-08", 10.2, tier="B"),
        _signal("s4", "2026-05-09", 10.3, tier="B", final_signal="sell"),
    ]
    # maxHoldingBars=1（第 2 帧就该退出）但 minHoldingBars=3 强制持有到 s4
    result = _run(frames, signals, {"minHoldingBars": 3, "maxHoldingBars": 1})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["holdingBars"] == 3


def test_min_holding_bars_zero_accepts_negative_or_string() -> None:
    """minHoldingBars 支持字符串/负数形态：<=0 视为不启用（与现状一致）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
        _frame("s3", "2026-05-08", 10.2),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        _signal("s2", "2026-05-07", 10.1, tier="S", candidate_tier="D_EXIT_RISK"),
    ]
    for value in (0, -1, "0", ""):
        result = _run(frames, signals, {"minHoldingBars": value})
        assert result["openPositionCount"] == 0
        assert result["tradeCount"] == 1


# ---------- 方向6：信号驱动退出去噪（signalExitDelayBars，默认 0 不改变行为）----------


def test_signal_exit_delay_disabled_by_default() -> None:
    """默认不设 signalExitDelayBars：D_EXIT_RISK 第 2 帧正常退出（行为不变回归）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
        _frame("s3", "2026-05-08", 10.2),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        _signal("s2", "2026-05-07", 10.1, tier="S", candidate_tier="D_EXIT_RISK"),
    ]
    result = _run(frames, signals, {})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1


def test_signal_exit_delay_holds_d_exit_risk() -> None:
    """signalExitDelayBars=3：D_EXIT_RISK 前 3 帧被抑制，第 4 帧（期满）才退出。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
        _frame("s3", "2026-05-08", 10.2),
        _frame("s4", "2026-05-09", 10.3),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        _signal("s2", "2026-05-07", 10.1, tier="S", candidate_tier="D_EXIT_RISK"),
        _signal("s3", "2026-05-08", 10.2, tier="S", candidate_tier="D_EXIT_RISK"),
        _signal("s4", "2026-05-09", 10.3, tier="S", candidate_tier="D_EXIT_RISK"),
    ]
    result = _run(frames, signals, {"signalExitDelayBars": 3})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["holdingBars"] == 3


def test_signal_exit_delay_keeps_stop_loss_active() -> None:
    """signalExitDelayBars 只延迟信号驱动退出：止损仍立即生效（区别于 minHoldingBars 的硬扛）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 9.0),  # -10% 触发止损 → 立即退出，不受延迟影响
        _frame("s3", "2026-05-08", 9.2),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        # s2 用 D_EXIT_RISK：信号退出被延迟，但 -10% 止损必须立即生效（优先级高于去噪）
        _signal("s2", "2026-05-07", 9.0, tier="S", candidate_tier="D_EXIT_RISK"),
    ]
    result = _run(frames, signals, {"signalExitDelayBars": 8})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["holdingBars"] == 1


def test_signal_exit_delay_keeps_take_profit_active() -> None:
    """signalExitDelayBars 只延迟信号驱动退出：止盈仍立即生效。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 11.5),  # +15% 触发止盈 → 立即退出
        _frame("s3", "2026-05-08", 12.0),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        _signal("s2", "2026-05-07", 11.5, tier="S", candidate_tier="D_EXIT_RISK"),
    ]
    result = _run(frames, signals, {"signalExitDelayBars": 8})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["holdingBars"] == 1
    assert result["roundTripTrades"][0]["exitPrice"] == 11.5


def test_signal_exit_delay_holds_final_sell_and_rank() -> None:
    """signalExitDelayBars 同时抑制 final sell 与 rank>50 信号退出，期满后放行。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
        _frame("s3", "2026-05-08", 10.2),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        _signal("s2", "2026-05-07", 10.1, tier="S", final_signal="sell"),
        _signal("s3", "2026-05-08", 10.2, tier="S", final_signal="sell"),
    ]
    # rank=8 <= 50 不触发 rank 退出；final_signal=sell 前 2 帧被抑制，s3 期满（holdingBars=2）退出
    result = _run(frames, signals, {"signalExitDelayBars": 2})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["holdingBars"] == 2


def test_signal_exit_delay_zero_accepts_negative_or_string() -> None:
    """signalExitDelayBars 支持字符串/负数形态：<=0 视为不启用（与现状一致）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.1),
        _frame("s3", "2026-05-08", 10.2),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, tier="S"),
        _signal("s2", "2026-05-07", 10.1, tier="S", candidate_tier="D_EXIT_RISK"),
    ]
    for value in (0, -1, "0", ""):
        result = _run(frames, signals, {"signalExitDelayBars": value})
        assert result["openPositionCount"] == 0
        assert result["tradeCount"] == 1


# ---------- 字符串布尔形态（前端 search_space 提交 ["true","false"]）----------


def test_config_bool_accepts_string_forms() -> None:
    """_config_bool：容忍 "true"/"false"/"on"/"1" 字符串形态（前端提交字符串数组）。"""
    assert TradeSimulator._config_bool({}, "useAtrStops") is False
    assert TradeSimulator._config_bool({"useAtrStops": "true"}, "useAtrStops") is True
    assert TradeSimulator._config_bool({"useAtrStops": "on"}, "useAtrStops") is True
    assert TradeSimulator._config_bool({"useAtrStops": "1"}, "useAtrStops") is True
    assert TradeSimulator._config_bool({"useAtrStops": "false"}, "useAtrStops") is False
    assert TradeSimulator._config_bool({"useAtrStops": True}, "useAtrStops") is True
    assert TradeSimulator._config_bool({"useAtrStops": False}, "useAtrStops") is False


def test_switches_work_with_string_bool_values() -> None:
    """字符串布尔形态的开关在实际回测中生效（如前端提交 ["true"]）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.3),
        _frame("s3", "2026-05-08", 9.98, ),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0),
        _signal("s2", "2026-05-07", 10.3),
        _signal("s3", "2026-05-08", 9.98, final_signal="hold"),
    ]
    # "true" 字符串形态触发保本止损（否则 9.98 > 固定 -6% 不退出）
    result = _run(frames, signals, {"breakevenTrailing": "true", "breakevenThreshold": "0.02"})
    assert result["openPositionCount"] == 0
    assert result["tradeCount"] == 1
