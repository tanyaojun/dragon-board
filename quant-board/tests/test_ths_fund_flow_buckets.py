from __future__ import annotations

from backend.services.market.ths_fund_flow_buckets import (
    L2_BUCKETS,
    aggregate_l2_buckets,
)


def _tick(money: float, tradetype: str = "1") -> dict:
    return {
        "nature": "主动买入" if tradetype == "1" else "主动卖出",
        "volume": "100手",
        "tradetype": tradetype,
        "avgprice": "10.0",
        "value": "100万",
        "money": money,
        "ctime": "15:00:00",
        "otime": "2026-08-07 15:00:00",
    }


def test_seven_buckets_with_boundaries() -> None:
    rows = [
        _tick(10_000_000),   # ≥1000万 → ge_1000w
        _tick(9_999_999),    # 700-1000万
        _tick(7_000_000),    # 边界 700万 → 700_1000w（min 含）
        _tick(6_999_999),    # 500-700万
        _tick(5_000_000),    # 边界 500万 → 500_700w
        _tick(3_000_000),    # 边界 300万 → 300_500w
        _tick(2_999_999),    # 100-300万
        _tick(1_000_000),    # 边界 100万 → 100_300w
        _tick(999_999),      # 50-100万
        _tick(500_000),      # 边界 50万 → 50_100w
        _tick(499_999),      # 30-50万
        _tick(300_000),      # 边界 30万 → 30_50w
        _tick(299_999),      # 低于 30 万：不入档
    ]
    buckets = aggregate_l2_buckets(rows)
    by_tier = {b["tier"]: b for b in buckets}

    assert [b["tier"] for b in buckets] == [
        "ge_1000w",
        "700_1000w",
        "500_700w",
        "300_500w",
        "100_300w",
        "50_100w",
        "30_50w",
    ]
    assert by_tier["ge_1000w"]["buyCount"] == 1
    assert by_tier["700_1000w"]["buyCount"] == 2  # 9999999 + 7000000
    assert by_tier["500_700w"]["buyCount"] == 2  # 6999999 + 5000000
    assert by_tier["300_500w"]["buyCount"] == 1
    assert by_tier["100_300w"]["buyCount"] == 2  # 2999999 + 1000000
    assert by_tier["50_100w"]["buyCount"] == 2  # 999999 + 500000
    assert by_tier["30_50w"]["buyCount"] == 2  # 499999 + 300000
    # 低于 30 万不入档
    assert sum(b["buyCount"] + b["sellCount"] for b in buckets) == 12


def test_buy_sell_direction_and_amounts() -> None:
    rows = [
        _tick(5_000_000, "1"),   # 买 500万
        _tick(5_000_000, "2"),   # 卖 500万
        _tick(8_000_000, "1"),   # 买 800万
        _tick(1_500_000, "2"),   # 卖 150万（中单）
    ]
    buckets = aggregate_l2_buckets(rows)
    by_tier = {b["tier"]: b for b in buckets}

    b500 = by_tier["500_700w"]
    assert b500["buyCount"] == 1
    assert b500["sellCount"] == 1
    assert b500["buyAmount"] == 5_000_000
    assert b500["sellAmount"] == 5_000_000
    assert b500["net"] == 0.0

    b800 = by_tier["700_1000w"]
    assert b800["buyCount"] == 1
    assert b800["buyAmount"] == 8_000_000
    assert b800["net"] == 8_000_000

    b150 = by_tier["100_300w"]
    assert b150["sellCount"] == 1
    assert b150["sellAmount"] == 1_500_000
    assert b150["net"] == -1_500_000


def test_empty_and_invalid_rows() -> None:
    assert aggregate_l2_buckets([]) == [
        {**b, "buyCount": 0, "sellCount": 0, "buyAmount": 0.0, "sellAmount": 0.0, "net": 0.0}
        for b in L2_BUCKETS
    ]
    buckets = aggregate_l2_buckets([None, "x", {}, {"money": None}, {"money": 0}, {"money": "abc"}])
    assert all(b["buyCount"] == 0 and b["sellCount"] == 0 for b in buckets)


def test_bucket_categories() -> None:
    buckets = aggregate_l2_buckets([_tick(10_000_000), _tick(5_000_000), _tick(1_500_000), _tick(500_000)])
    by_tier = {b["tier"]: b for b in buckets}
    assert by_tier["ge_1000w"]["category"] == "超大单"
    assert by_tier["700_1000w"]["category"] == "大单"
    assert by_tier["500_700w"]["category"] == "大单"
    assert by_tier["300_500w"]["category"] == "大单"
    assert by_tier["100_300w"]["category"] == "中单"
    assert by_tier["50_100w"]["category"] == "小单"
    assert by_tier["30_50w"]["category"] == "小单"
