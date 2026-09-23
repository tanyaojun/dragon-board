# -*- coding: utf-8 -*-
"""交易模拟器退出规则补缺（阶段 B，2026-09-23 立项）。

TradeSimulator 新增（全部默认关闭，行为与现状一致，golden 不漂移）：
- trailingStopActivateGain / trailingStopDrawdown：真·移动止盈——浮盈达激活阈值后，
  止损线上移至 peak×(1-drawdown)（peak 按 bar high 粘性记录；激活粘性不回退）。
  生效路径与 breakeven 相同：_exit_prices 的止损线（通用链 bar 级 + 全链 intrabar 盘中线）。
- breakBoardExit / breakBoardMinBars：断板事件卖出——持仓期曾触及涨停（high>=limitUpPrice）
  且当前 bar 未封板（price<limitUpPrice 或 fengdan 归零）时卖出，reason="断板"；
  breakBoardMinBars 防触板次 bar 秒开噪声；limitUpPrice 缺失时不判定（fail-visible 不误杀）。

依据：docs/ranktrend-tier-backtest/exit-rules-scan-plan.md 阶段 B 与
exit-scan-batch3-verdict.md（tp0.06×be0.02 已落默认，B1 是其动态统一形式）。
"""

from __future__ import annotations

from backend.core.backtest import TradeSimulator


def _signal(
    snapshot_id: str,
    date: str,
    price: float,
    *,
    high: float | None = None,
    limit_up_price: float | None = None,
    fengdan: float | None = None,
    final_signal: str = "hold",
    momentum_short: float = 5.0,
    candidate_tier: str = "A_MAIN",
) -> dict:
    row = {
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
            "observation": {"synergy": {}, "volumePrice": {"quadrant": "normal"}, "lifecycle": {"veto": False}},
        },
    }
    if high is not None:
        row["high"] = high
    if limit_up_price is not None:
        row["limitUpPrice"] = limit_up_price
    if fengdan is not None:
        row["fengdan"] = fengdan
    return row


def _frame(snapshot_id: str, date: str, price: float) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": snapshot_id,
        "tradingDate": date,
        "slotTime": "10:00",
        "price": price,
    }


def _run(frames: list[dict], signals: list[dict], patch: dict) -> dict:
    return TradeSimulator().run(
        frames,
        signals,
        {
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
            "takeProfit": 0.99,
            **patch,
        },
    )


# ---------- B1：真·移动止盈 trailing stop ----------


def test_trailing_stop_disabled_by_default() -> None:
    """默认关闭：冲高回落后仍持有（行为与现状一致）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.6),
        _frame("s3", "2026-05-08", 10.3),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, final_signal="buy"),
        _signal("s2", "2026-05-07", 10.6),
        _signal("s3", "2026-05-08", 10.3),
    ]
    result = _run(frames, signals, {})
    assert result["openPositionCount"] == 1
    assert result["tradeCount"] == 0


def test_trailing_stop_exits_on_drawdown_after_gain() -> None:
    """激活（+5%）后从峰值回撤超 drawdown 触发止损退出。

    peak=10.6，线 = 10.6×(1-0.02)=10.388；bar3 close 10.3 跌破 → 卖出且仍盈利。
    """
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.6),
        _frame("s3", "2026-05-08", 10.3),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, final_signal="buy"),
        _signal("s2", "2026-05-07", 10.6),
        _signal("s3", "2026-05-08", 10.3),
    ]
    result = _run(frames, signals, {"trailingStopActivateGain": 0.05, "trailingStopDrawdown": 0.02})
    assert result["tradeCount"] == 1
    trade = result["roundTripTrades"][0]
    assert trade["reason"] == "止损"
    assert trade["netReturn"] > 0.02  # 锁盈离场而非 -6% 固定止损


def test_trailing_stop_activation_is_sticky() -> None:
    """激活粘性：激活后浮盈回落到激活阈值下方，移动止损线仍保持（不回退）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.6),  # +6% 激活，peak=10.6，线 10.388
        _frame("s3", "2026-05-08", 10.45),  # +4.5% < 激活阈值，但粘性保持；未破线
        _frame("s4", "2026-05-09", 10.38),  # 破线 → 卖出
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, final_signal="buy"),
        _signal("s2", "2026-05-07", 10.6),
        _signal("s3", "2026-05-08", 10.45),
        _signal("s4", "2026-05-09", 10.38),
    ]
    result = _run(frames, signals, {"trailingStopActivateGain": 0.05, "trailingStopDrawdown": 0.02})
    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["reason"] == "止损"


def test_trailing_stop_peak_tracks_high() -> None:
    """peak 按 bar high 更新：s2 收盘仅 +3% 但盘中 high 冲 10.65 → 线抬至 10.437，
    s2 自身收盘 10.3 已跌破该线（bar 级判定用当 bar 线）→ s2 即触发离场。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.3),  # close 仅 +3%，但 high 冲到 10.65
        _frame("s3", "2026-05-08", 10.4),  # < 10.65×0.98=10.437 → 触发
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, final_signal="buy"),
        _signal("s2", "2026-05-07", 10.3, high=10.65),
        _signal("s3", "2026-05-08", 10.4),
    ]
    result = _run(frames, signals, {"trailingStopActivateGain": 0.05, "trailingStopDrawdown": 0.02})
    assert result["tradeCount"] == 1
    trade = result["roundTripTrades"][0]
    assert trade["reason"] == "止损"
    assert trade["exitSnapshotId"] == "s2"  # 线由 high 抬升后，当 bar 收盘即跌破


# ---------- B2：断板事件卖出 breakBoardExit ----------


def test_break_board_exit_disabled_by_default() -> None:
    """默认关闭：触板后开板仍持有（行为与现状一致）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.55),  # 触板（high 10.55 >= 涨停 10.5）
        _frame("s3", "2026-05-08", 10.2),  # 开板
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, final_signal="buy"),
        _signal("s2", "2026-05-07", 10.55, high=10.55, limit_up_price=10.5),
        _signal("s3", "2026-05-08", 10.2, limit_up_price=10.5, fengdan=0),
    ]
    result = _run(frames, signals, {})
    assert result["openPositionCount"] == 1
    assert result["tradeCount"] == 0


def test_break_board_exit_sells_when_seal_breaks() -> None:
    """breakBoardExit：曾触板且当前未封板 → 卖出 reason=断板。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.55),
        _frame("s3", "2026-05-08", 10.2),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, final_signal="buy"),
        _signal("s2", "2026-05-07", 10.55, high=10.55, limit_up_price=10.5),
        _signal("s3", "2026-05-08", 10.2, limit_up_price=10.5, fengdan=0),
    ]
    result = _run(frames, signals, {"breakBoardExit": True})
    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["reason"] == "断板"


def test_break_board_exit_min_bars_guards_one_bar_noise() -> None:
    """breakBoardMinBars：触板后需满足最少持有 bar 数才允许断板卖出。

    minBars=3：bar2 触板（holdingBars=1）、bar3 开板（holdingBars=2 < 3 不卖）、
    bar4 仍开板（holdingBars=3 ≥ 3 → 卖出）。
    """
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.55),
        _frame("s3", "2026-05-08", 10.2),
        _frame("s4", "2026-05-09", 10.1),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, final_signal="buy"),
        _signal("s2", "2026-05-07", 10.55, high=10.55, limit_up_price=10.5),
        _signal("s3", "2026-05-08", 10.2, limit_up_price=10.5, fengdan=0),
        _signal("s4", "2026-05-09", 10.1, limit_up_price=10.5, fengdan=0),
    ]
    result = _run(frames, signals, {"breakBoardExit": True, "breakBoardMinBars": 3})
    # bar3（holdingBars=2 < 3）未卖出
    assert result["tradeCount"] == 1
    trade = result["roundTripTrades"][0]
    assert trade["reason"] == "断板"
    assert trade["exitSnapshotId"] == "s4"  # 推迟到 bar4 才卖出


def test_break_board_exit_skips_when_limit_up_price_missing() -> None:
    """limitUpPrice 缺失时不判定断板（fail-visible 不误杀）。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.6),
        _frame("s3", "2026-05-08", 10.2),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, final_signal="buy"),
        _signal("s2", "2026-05-07", 10.6),  # 无 limitUpPrice
        _signal("s3", "2026-05-08", 10.2),
    ]
    result = _run(frames, signals, {"breakBoardExit": True})
    assert result["openPositionCount"] == 1
    assert result["tradeCount"] == 0


def test_break_board_exit_on_seal_amount_drained_at_limit_price() -> None:
    """fengdan 归零（封单排空）是有意义的断板信号：价格仍持平涨停价但封单归零 → 断板。

    回归背景（code review I-1）：_quote/_first_number 会把 0 归一为 None，
    若从 quote 读 fengdan 该分支永不可达——实现已改为从原始字段读取。
    """
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.55),
        _frame("s3", "2026-05-08", 10.5),  # 价格持平涨停价，但封单排空
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, final_signal="buy"),
        _signal("s2", "2026-05-07", 10.55, high=10.55, limit_up_price=10.5),
        _signal("s3", "2026-05-08", 10.5, limit_up_price=10.5, fengdan=0),
    ]
    result = _run(frames, signals, {"breakBoardExit": True})
    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["reason"] == "断板"


def test_break_board_exit_keeps_holding_when_fengdan_still_positive_at_limit_price() -> None:
    """对照：价格持平涨停价且封单仍为正 → 仍封板，不断板。"""
    frames = [
        _frame("s1", "2026-05-06", 10.0),
        _frame("s2", "2026-05-07", 10.55),
        _frame("s3", "2026-05-08", 10.5),
    ]
    signals = [
        _signal("s1", "2026-05-06", 10.0, final_signal="buy"),
        _signal("s2", "2026-05-07", 10.55, high=10.55, limit_up_price=10.5),
        _signal("s3", "2026-05-08", 10.5, limit_up_price=10.5, fengdan=80000),
    ]
    result = _run(frames, signals, {"breakBoardExit": True})
    assert result["openPositionCount"] == 1
    assert result["tradeCount"] == 0
