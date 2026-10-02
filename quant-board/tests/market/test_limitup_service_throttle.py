# -*- coding: utf-8 -*-
"""LimitUpService 风控对策测试（2026-10-02）：池子集/请求节流/风控返空负缓存退避。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.market_proxy.limitup import LimitUpService

_EMPTY = {"data": {"info": []}}
_OK = {"data": {"info": [{"code": "600825"}]}}


class _FakeClient:
    """按 URL 前缀应答的假 httpx 客户端，记录每次请求时刻。"""

    def __init__(self, responses):
        self._responses = responses  # list：逐次弹出；None=空 info
        self.calls: list[float] = []

    async def get(self, url, timeout=None, headers=None):
        self.calls.append(len(self.calls))
        payload = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(payload, Exception):
            raise payload

        class _Resp:
            def __init__(self, body):
                self._body = body

            def raise_for_status(self):
                return None

            def json(self):
                return self._body

        if payload is None:
            return _Resp(_EMPTY)
        if url.startswith("https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"):
            return _Resp(_OK)
        if "drawdown" in url:
            return _Resp({"data": {"stock_list": [{"stock_code": "1", "max_drawdown": "-5"}]}})
        return _Resp({"data": {"stock_list": [{"code": "x"}]}})


def _now_factory():
    state = {"ms": 1_000_000}

    def now():
        return state["ms"]

    return now, state


def test_get_ths_pools_subset_fetches_only_requested_pools():
    now, _ = _now_factory()
    client = _FakeClient([_OK])
    svc = LimitUpService(client=client, now_ms=now, min_request_gap_ms=0)
    payload = asyncio.run(svc.get_ths_pools("20260929", keys=("failed", "drawdown")))
    assert set(payload["pools"]) == {"failed", "drawdown"}
    assert len(client.calls) == 2  # 只发两个池请求，八连发不再


def test_subset_cache_key_separated_from_full():
    now, state = _now_factory()
    client = _FakeClient([_OK])
    svc = LimitUpService(client=client, now_ms=now, min_request_gap_ms=0)
    asyncio.run(svc.get_ths_pools("20260929", keys=("failed",)))
    full = asyncio.run(svc.get_ths_pools("20260929"))  # 不同缓存键 → 真请求全量
    assert set(full["pools"]) == set(svc.POOL_KEYS_ALL)
    assert len(client.calls) == 1 + len(svc.POOL_KEYS_ALL)


def test_empty_info_negative_cache_backs_off():
    # 风控返空（200+空 info）：退避窗口内复用空结果不发请求；窗口外才重试
    now, state = _now_factory()
    client = _FakeClient([None])
    svc = LimitUpService(client=client, now_ms=now, ttl_seconds=1,
                         empty_backoff_base_ms=30_000, min_request_gap_ms=0)
    p1 = asyncio.run(svc.get_limit_up_list("20260915"))
    assert p1["data"]["info"] == []
    state["ms"] += 5_000  # 超过 TTL(1s) 但在 30s 退避窗口内
    p2 = asyncio.run(svc.get_limit_up_list("20260915"))
    assert p2["data"]["info"] == [] and len(client.calls) == 1  # 未重打
    state["ms"] += 31_000  # 出退避窗口 → 真重试
    p3 = asyncio.run(svc.get_limit_up_list("20260915"))
    assert p3["data"]["info"] == [] and len(client.calls) == 2


def test_success_resets_backoff_streak():
    now, state = _now_factory()
    client = _FakeClient([None, _OK, None])
    svc = LimitUpService(client=client, now_ms=now, ttl_seconds=1,
                         empty_backoff_base_ms=30_000, min_request_gap_ms=0)
    asyncio.run(svc.get_limit_up_list("20260915"))  # 空 → streak 1
    state["ms"] += 31_000
    asyncio.run(svc.get_limit_up_list("20260915"))  # 成功 → streak 归零
    state["ms"] += 5_000
    asyncio.run(svc.get_limit_up_list("20260915"))  # 再空 → 重新从 base 退避
    state["ms"] += 31_000
    asyncio.run(svc.get_limit_up_list("20260915"))  # 31s 后应已可重试（若 streak 未归零会是 60s 窗口）
    assert len(client.calls) == 4


def test_throttle_enforces_min_gap():
    # 真实场景：同次采集中列表+细分池两个不同键背靠背出网 → 第二发应错峰等待
    now, state = _now_factory()
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        state["ms"] += int(seconds * 1000)

    client = _FakeClient([_OK])
    svc = LimitUpService(client=client, now_ms=now, min_request_gap_ms=250, sleep_fn=fake_sleep)

    async def flow():
        await svc.get_limit_up_list("20260915")
        await svc.get_ths_pools("20260915", keys=("failed",))

    asyncio.run(flow())
    assert len(client.calls) == 2
    assert any(0.2 <= s <= 0.3 for s in sleeps)
