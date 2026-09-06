from __future__ import annotations

from backend.core.backtest.evaluator import OutcomeEvaluator, build_frame_lookup


def _frame(snapshot_id: str, date: str, prices: dict[str, float]) -> dict:
    return {
        "snapshotId": snapshot_id,
        "tradingDate": date,
        "stocks": [{"code": code, "price": price, "rank": 3} for code, price in prices.items()],
    }


def _signal(code: str, snapshot_id: str) -> dict:
    return {
        "code": code,
        "snapshotId": snapshot_id,
        "candidateTier": "A_MAIN",
        "stage": "10:00",
        "regime": "normal",
        "rankTrend": {"decision": {"final": {"signal": "buy"}}},
    }


def _frames():
    return [
        _frame("s1", "2026-06-05", {"000001": 10.0, "000002": 20.0}),
        _frame("s2", "2026-06-05", {"000001": 10.5, "000002": 21.0}),
        _frame("s3", "2026-06-05", {"000001": 11.0, "000002": 22.0}),  # 06-05 尾帧
        _frame("s4", "2026-06-08", {"000001": 12.0, "000002": 25.0}),  # 跨日不参与
    ]


def test_hold_to_close_exit_at_same_day_last_frame():
    frames = _frames()
    row = OutcomeEvaluator()._outcome(
        frames, _signal("000001", "s1"), "hold_to_close", build_frame_lookup(frames),
        OutcomeEvaluator._last_entry_index(frames),
    )
    assert row["found"] is True
    assert row["horizon"] == "hold_to_close"
    assert row["priceReturn"] == 0.1  # 10.0 → 11.0（s3），跨日 s4 的 12.0 不参与


def test_hold_to_close_entry_at_last_frame_is_zero_return():
    frames = _frames()
    row = OutcomeEvaluator()._outcome(
        frames, _signal("000001", "s3"), "hold_to_close", build_frame_lookup(frames),
        OutcomeEvaluator._last_entry_index(frames),
    )
    assert row["found"] is True
    assert row["priceReturn"] == 0.0


def test_hold_to_close_missing_trading_date_fails_visible():
    frames = [{"snapshotId": "s1", "stocks": [{"code": "000001", "price": 10.0, "rank": 3}]}]
    row = OutcomeEvaluator()._outcome(
        frames, _signal("000001", "s1"), "hold_to_close", build_frame_lookup(frames),
        OutcomeEvaluator._last_entry_index(frames),
    )
    assert row["found"] is False  # 缺 tradingDate 无法定位尾帧 → 样本不足结构


def test_evaluate_hold_to_close_group_report_and_default_off():
    frames = _frames()
    signals = [_signal("000001", "s1"), _signal("000002", "s1")]
    evaluator = OutcomeEvaluator()
    result = evaluator.evaluate(frames, signals, [1], include_hold_to_close=True)
    a_main = next(r for r in result["holdToClose"]["byTier"] if r["groupKey"] == "A_MAIN")
    assert a_main["foundCount"] == 2
    assert a_main["avgPriceReturn"] == 0.1  # 000001 +10%、000002 +10%
    default_result = evaluator.evaluate(frames, signals, [1])
    assert default_result["holdToClose"] is None  # 默认关闭，现行为零变化
