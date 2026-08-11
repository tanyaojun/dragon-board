from __future__ import annotations

import asyncio

import pytest

from backend.services.market.fund_stream import MarketFundStream


class FakeCache:
    def __init__(self, rows: dict[str, dict] | None = None) -> None:
        self._rows = rows or {}

    def get_latest(self, codes: list[str]) -> dict[str, dict]:
        return {code: dict(self._rows[code]) for code in codes if code in self._rows}

    def current_version(self) -> int:
        return 1


def _stream(cache: FakeCache | None = None) -> MarketFundStream:
    return MarketFundStream(cache=cache or FakeCache())


@pytest.mark.asyncio
async def test_snapshot_only_serves_latest_trading_session_rows() -> None:
    # 首屏链路修复（2026-08-11 实盘复盘）：Redis 旧交易日行（TTL 不清）不得
    # 随 fund_full_state 下发——旧票显示过期交易日累计值，与当日实时偏差大
    from backend.services.market.fund_stream import latest_trading_session

    latest = latest_trading_session()
    stale = "2026-08-10"
    cache = FakeCache(
        {
            "000001": {"code": "000001", "zlje": 1.0, "sessionDate": latest, "moneyFlowSource": "ths_main_monitor"},
            "000002": {"code": "000002", "zlje": 2.0, "sessionDate": stale, "moneyFlowSource": "ths_main_monitor"},
        }
    )
    stream = _stream(cache)
    queue = await stream.subscribe(["000001", "000002"])

    payload = queue.get_nowait()
    assert payload["type"] == "fund_full_state"
    assert [row["code"] for row in payload["items"]] == ["000001"]  # 旧交易日行不下发
    stream.unsubscribe(queue)


@pytest.mark.asyncio
async def test_publish_filters_out_stale_trading_session_rows() -> None:
    from backend.services.market.fund_stream import latest_trading_session

    latest = latest_trading_session()
    stale = "2026-08-07"
    stream = _stream()
    queue = await stream.subscribe(["000001"])
    queue.get_nowait()  # 消费 subscribe 时的 fund_full_state

    stream.publish(
        [
            {"code": "000001", "zlje": 1.0, "sessionDate": latest, "moneyFlowSource": "ths_main_monitor", "version": 1},
            {"code": "000001", "zlje": 9.0, "sessionDate": stale, "moneyFlowSource": "ths_main_monitor", "version": 2},
        ]
    )

    payload = queue.get_nowait()
    assert payload["type"] == "fund_patch"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["zlje"] == 1.0  # 只推最近交易日行
    stream.unsubscribe(queue)


@pytest.mark.asyncio
async def test_subscribe_without_priority_has_empty_priority_codes() -> None:
    stream = _stream()
    queue = await stream.subscribe(["000001", "000002"])

    assert stream.market_codes() == ["000001", "000002"]
    assert stream.priority_codes() == []
    stream.unsubscribe(queue)


@pytest.mark.asyncio
async def test_subscribe_with_priority_tracks_separately() -> None:
    stream = _stream()
    queue = await stream.subscribe(["000001", "000002", "000003"], priority_codes=["000001"])

    # 全池不受 priority 影响，priority 是子集
    assert stream.market_codes() == ["000001", "000002", "000003"]
    assert stream.priority_codes() == ["000001"]
    stream.unsubscribe(queue)


@pytest.mark.asyncio
async def test_update_replaces_priority() -> None:
    stream = _stream()
    queue = await stream.subscribe(["000001", "000002"], priority_codes=["000001"])

    await stream.update(queue, ["000002", "000003"], priority_codes=["000002"])

    assert stream.market_codes() == ["000002", "000003"]
    assert stream.priority_codes() == ["000002"]
    stream.unsubscribe(queue)


@pytest.mark.asyncio
async def test_multiple_subscribers_priority_union() -> None:
    stream = _stream()
    queue_a = await stream.subscribe(["000001", "000002"], priority_codes=["000001"])
    queue_b = await stream.subscribe(["000002", "000003"], priority_codes=["000003"])

    assert stream.priority_codes() == ["000001", "000003"]
    stream.unsubscribe(queue_a)
    stream.unsubscribe(queue_b)
    # 断开后返回最后已知池（owner 持久化）：queue_b 的 priority
    assert stream.priority_codes() == ["000003"]


@pytest.mark.asyncio
async def test_priority_normalizes_and_dedups() -> None:
    stream = _stream()
    queue = await stream.subscribe(["000001"], priority_codes=["000001", "000001", "600519.SH", "abc"])

    # 非 6 位数字被丢弃，重复去重
    assert stream.priority_codes() == ["000001"]
    stream.unsubscribe(queue)


@pytest.mark.asyncio
async def test_update_without_priority_clears_it() -> None:
    stream = _stream()
    queue = await stream.subscribe(["000001"], priority_codes=["000001"])

    await stream.update(queue, ["000001"])

    assert stream.priority_codes() == []
    stream.unsubscribe(queue)


@pytest.mark.asyncio
async def test_unsubscribe_all_keeps_persisted_owner_pool() -> None:
    stream = _stream()
    queue = await stream.subscribe(["000001", "000002"], priority_codes=["000001"])
    assert stream.has_active_owner() is True

    stream.unsubscribe(queue)

    # 浏览器断开后仍按最后已知池刷新（owner 持久化），P0/P1 都保留
    assert stream.has_active_owner() is False
    assert stream.market_codes() == ["000001", "000002"]
    assert stream.priority_codes() == ["000001"]
    assert stream.persisted_owner() == {
        "codes": ["000001", "000002"],
        "priority": ["000001"],
    }


@pytest.mark.asyncio
async def test_new_subscription_replaces_persisted_owner() -> None:
    stream = _stream()
    queue_a = await stream.subscribe(["000001"], priority_codes=["000001"])
    stream.unsubscribe(queue_a)
    assert stream.market_codes() == ["000001"]

    queue_b = await stream.subscribe(["000003", "000004"], priority_codes=["000003"])
    assert stream.market_codes() == ["000003", "000004"]
    assert stream.priority_codes() == ["000003"]
    stream.unsubscribe(queue_b)
    # 持久池 = 最近一次订阅（queue_b）
    assert stream.market_codes() == ["000003", "000004"]
    assert stream.priority_codes() == ["000003"]


@pytest.mark.asyncio
async def test_no_owner_before_first_subscription() -> None:
    stream = _stream()
    assert stream.market_codes() == []
    assert stream.priority_codes() == []
    assert stream.has_active_owner() is False
    assert stream.persisted_owner() == {"codes": [], "priority": []}
