from __future__ import annotations

import asyncio

import pytest

from backend.services.market.fund_stream import MarketFundStream


class FakeCache:
    def get_latest(self, codes: list[str]) -> dict[str, dict]:
        return {}

    def current_version(self) -> int:
        return 1


def _stream() -> MarketFundStream:
    return MarketFundStream(cache=FakeCache())


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
