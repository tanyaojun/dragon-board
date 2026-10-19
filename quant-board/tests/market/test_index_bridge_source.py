"""指数源切换到行情桥（TDX）的回归测试。

背景（2026-10-19）：akshare 新浪指数接口被风控限流，盘中每槽吃满 30s 预算仍拿不到
数据，frame.indices 全空。指数改由本地行情桥直连 TDX：
``GET 127.0.0.1:8765/api/quotes/index-snapshot``。

本文件锁定三件事：
1. 桥返回 → akshare 口径 items 的映射（含涨跌额/涨跌幅推导、名称补齐、代码过滤）；
2. 空返回/上游失败必须抛错（不得冒充"成功但没数据"，否则会用空列表覆盖 last-good）；
3. 映射结果喂给 ``providers.build_server_indices`` 后，frame.indices 键位与 akshare 口径一致。
"""

from __future__ import annotations

import pytest

from backend.market_proxy.index_bridge_source import (
    DEFAULT_INDEX_CODES,
    fetch_index_items,
    normalize_bridge_items,
)
from backend.snapshot_collector.providers import build_server_indices

BRIDGE_ROWS = [
    {
        "code": "sh000001",
        "market": 1,
        "lastPrice": 3716.02,
        "preClose": 3716.28,
        "changeAmount": -0.26,
        "changePct": -0.007,
        "open": 3694.12,
        "high": 3733.86,
        "low": 3692.29,
        "volume": 303356328,
        "amount": 501436579840.0,
    },
    {
        "code": "sz399001",
        "market": 0,
        "lastPrice": 11754.03,
        "preClose": 11802.46,
        "changeAmount": -48.43,
        "changePct": -0.4103,
        "volume": 360730932,
        "amount": 548790665216.0,
    },
    {
        "code": "sh000300",
        "market": 1,
        "lastPrice": 4590.0,
        "preClose": 4580.0,
        "volume": 100,
        "amount": 1000.0,
    },
    {
        "code": "sh000905",
        "market": 1,
        "lastPrice": 7200.0,
        "preClose": 7210.0,
        "volume": 100,
        "amount": 1000.0,
    },
    {
        "code": "sh000852",
        "market": 1,
        "lastPrice": 6800.0,
        "preClose": 6820.0,
        "volume": 100,
        "amount": 1000.0,
    },
]


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.calls: list[dict] = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return _FakeResponse(self.payload, self.status_code)


def test_normalize_maps_bridge_rows_to_akshare_contract() -> None:
    items = normalize_bridge_items(BRIDGE_ROWS)

    first = items[0]
    assert first["code"] == "sh000001"
    assert first["name"] == "上证指数"
    assert first["price"] == 3716.02
    assert first["change"] == -0.26
    assert first["changePct"] == -0.007
    assert first["prevClose"] == 3716.28
    assert first["amount"] == 501436579840.0


def test_normalize_derives_change_when_missing() -> None:
    items = normalize_bridge_items(
        [{"code": "sh000300", "lastPrice": 4590.0, "preClose": 4580.0}]
    )

    assert items[0]["change"] == pytest.approx(10.0)
    assert items[0]["changePct"] == pytest.approx(0.2183, abs=1e-3)


def test_normalize_skips_garbage_and_filters_codes() -> None:
    items = normalize_bridge_items(
        [{"code": ""}, "not-a-dict", {"code": "sz399006", "lastPrice": 2735.73}],
        code_filter=["sz399006"],
    )

    assert [item["code"] for item in items] == ["sz399006"]
    assert items[0]["name"] == "创业板指"


@pytest.mark.asyncio
async def test_fetch_index_items_uses_bridge_url_and_default_codes() -> None:
    client = _FakeClient({"ok": True, "quotes": BRIDGE_ROWS})

    items = await fetch_index_items(base_url="http://127.0.0.1:8765/", client=client)

    assert len(items) == len(BRIDGE_ROWS)
    assert client.calls[0]["url"] == "http://127.0.0.1:8765/api/quotes/index-snapshot"
    assert client.calls[0]["params"]["codes"] == ",".join(DEFAULT_INDEX_CODES)


@pytest.mark.asyncio
async def test_fetch_index_items_raises_on_empty_or_failed_payload() -> None:
    # 空返回必须抛错：否则会被当成"成功"，用空 items 覆盖 last-good 兜底库
    with pytest.raises(RuntimeError, match="unusable"):
        await fetch_index_items(
            base_url="http://127.0.0.1:8765", client=_FakeClient({"ok": False, "quotes": []})
        )

    with pytest.raises(RuntimeError, match="unusable"):
        await fetch_index_items(
            base_url="http://127.0.0.1:8765",
            client=_FakeClient({"ok": True, "quotes": [], "error": "no_tdx_server_available"}),
        )


@pytest.mark.asyncio
async def test_fetch_index_items_propagates_http_error() -> None:
    with pytest.raises(RuntimeError, match="HTTP 404"):
        await fetch_index_items(
            base_url="http://127.0.0.1:8765",
            client=_FakeClient({"ok": False}, status_code=404),
        )


def test_bridge_items_produce_same_frame_indices_contract() -> None:
    """键位契约锁定：sh / hs300 / zz500 / zz1000 + totalAmount（sh000001+sz399001）。"""
    items = normalize_bridge_items(BRIDGE_ROWS)

    indices = build_server_indices({"ok": True, "items": items})

    assert set(indices) == {"sh", "hs300", "zz500", "zz1000", "totalAmount"}
    assert indices["sh"]["change"] == -0.26
    assert indices["sh"]["changePct"] == -0.007
    assert indices["hs300"]["change"] == pytest.approx(10.0)
    assert indices["totalAmount"]["amount"] == pytest.approx(
        501436579840.0 + 548790665216.0
    )


def test_bridge_items_without_one_market_do_not_fake_total_amount() -> None:
    """只有一个市场的数据时不得写 totalAmount（半口径不得伪装全口径）。"""
    items = normalize_bridge_items([row for row in BRIDGE_ROWS if row["code"] == "sh000001"])

    indices = build_server_indices({"ok": True, "items": items})

    assert "totalAmount" not in indices
    assert "sh" in indices