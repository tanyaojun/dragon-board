import asyncio
import time

import pytest

from backend.theme_fund_stream import ThemeFundStream


class FakeCache:
    def __init__(self) -> None:
        self.latest: dict[str, dict[str, object]] = {}
        self.owners: dict[str, list[str]] = {}

    def get_latest(self, codes: list[str], **_kwargs) -> dict[str, dict[str, object]]:
        return {code: self.latest[code] for code in codes if code in self.latest}

    def current_version(self) -> int:
        return max((int(row.get("version") or 0) for row in self.latest.values()), default=0)

    def set_owner_codes(self, owner: str, codes: list[str]) -> None:
        self.owners[owner] = list(codes)

    def get_owner_codes(self) -> dict[str, list[str]]:
        return {owner: list(codes) for owner, codes in self.owners.items()}


def ths_row(code: str, version: int = 1) -> dict[str, object]:
    return {
        "code": code,
        "zlje": 12.5,
        "moneyFlowSource": "ths_main_monitor",
        "sessionDate": "2026-07-24",
        "version": version,
    }


def test_subscriber_receives_immediate_union_snapshot() -> None:
    cache = FakeCache()
    cache.latest = {"000001": ths_row("000001"), "600000": ths_row("600000", 2)}
    stream = ThemeFundStream(cache=cache)

    queue = stream.subscribe(market_codes=["000001"], priority_codes=["600000"])

    full = queue.get_nowait()
    assert full["type"] == "fund_full_state"
    assert {row["code"] for row in full["items"]} == {"000001", "600000"}


def test_theme_only_priority_code_receives_patch_without_becoming_p1_owner() -> None:
    cache = FakeCache()
    stream = ThemeFundStream(cache=cache)
    queue = stream.subscribe(market_codes=["000001"], priority_codes=["600000"])
    queue.get_nowait()

    stream.publish([ths_row("600000", 3)])

    assert queue.get_nowait()["items"][0]["code"] == "600000"
    assert cache.owners["dragon-board"] == ["000001"]


def test_disconnect_removes_priority_but_keeps_persisted_market_owner() -> None:
    cache = FakeCache()
    stream = ThemeFundStream(cache=cache)
    queue = stream.subscribe(market_codes=["000001"], priority_codes=["600000"])

    stream.unsubscribe(queue)

    assert stream.priority_codes() == []
    assert stream.market_codes() == ["000001"]
    assert cache.owners["dragon-board"] == ["000001"]


def test_persisted_market_owner_is_union_of_active_connections() -> None:
    cache = FakeCache()
    stream = ThemeFundStream(cache=cache)
    first = stream.subscribe(market_codes=["000001"], priority_codes=[])
    second = stream.subscribe(market_codes=["600000"], priority_codes=[])

    assert stream.market_codes() == ["000001", "600000"]

    stream.update_subscription(first, market_codes=["000002"], priority_codes=[])
    assert stream.market_codes() == ["000002", "600000"]

    stream.unsubscribe(first)
    assert stream.market_codes() == ["600000"]

    stream.unsubscribe(second)
    assert stream.market_codes() == ["600000"]


def test_priority_only_connection_does_not_clear_persisted_market_owner() -> None:
    cache = FakeCache()
    cache.owners["dragon-board"] = ["000001"]
    stream = ThemeFundStream(cache=cache)

    stream.subscribe(market_codes=[], priority_codes=["600000"])

    assert stream.market_codes() == ["000001"]


def test_stream_has_no_bridge_task_contract() -> None:
    stream = ThemeFundStream(cache=FakeCache())

    assert not hasattr(stream, "bridge_ws_url")
    assert not hasattr(stream, "accept_bridge_message")


@pytest.mark.asyncio
async def test_async_snapshot_does_not_block_the_event_loop() -> None:
    events: list[str] = []

    class SlowCache(FakeCache):
        def get_latest(self, codes: list[str], **_kwargs) -> dict[str, dict[str, object]]:
            events.append("cache-start")
            time.sleep(0.05)
            events.append("cache-end")
            return super().get_latest(codes, **_kwargs)

    cache = SlowCache()
    cache.latest["000001"] = ths_row("000001")
    stream = ThemeFundStream(cache=cache)

    snapshot = asyncio.create_task(stream.snapshot_async(["000001"], []))
    await asyncio.sleep(0.01)
    events.append("event-loop-tick")
    payload = await snapshot

    assert payload["items"][0]["code"] == "000001"
    assert events.index("event-loop-tick") < events.index("cache-end")
