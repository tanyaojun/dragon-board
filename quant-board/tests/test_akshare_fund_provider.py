from __future__ import annotations

import json
import socket
import time

import pandas as pd
import pytest

from backend.market_proxy.akshare_fund_provider import (
    AkshareFundProvider,
    AkshareFundProviderError,
    normalize_code,
    parse_amount,
)


def _clist_response(diff: list[dict], total: int) -> str:
    return json.dumps({"data": {"total": total, "diff": diff}})


def _em_diff_row(*, code: object, name: str = "", net: object = -83062800.0, net_pct: object = -24.81) -> dict:
    """东财 push2 clist diff 行（f62 净额单位：元）。"""
    return {
        "f12": code,
        "f14": name,
        "f2": 50.8,
        "f3": 20.01,
        "f62": net,
        "f184": net_pct,
        "f66": -83062800.0,
        "f72": 0.0,
        "f78": 1000000.0,
        "f84": -200000.0,
    }


def _provider(**kwargs) -> AkshareFundProvider:
    defaults = {"page_interval_seconds": 0.0}
    defaults.update(kwargs)
    return AkshareFundProvider(**defaults)


def test_parse_amount_handles_wan_yi_and_invalid() -> None:
    assert parse_amount("-8306.28万") == -83062800.0
    assert parse_amount("3.38亿") == 338000000.0
    assert parse_amount("1,234.5万") == 12345000.0
    assert parse_amount("0") == 0.0
    assert parse_amount(None) is None
    assert parse_amount("-") is None
    assert parse_amount("N/A") is None
    # 东财 fltt=2 返回元 float，也应直接可解析
    assert parse_amount(-83062800.0) == -83062800.0
    assert parse_amount(60704000) == 60704000.0


def test_normalize_code_pads_and_rejects() -> None:
    assert normalize_code(509) == "000509"
    assert normalize_code(300720) == "300720"
    assert normalize_code("000001") == "000001"
    assert normalize_code(688426) == "688426"
    assert normalize_code("SZ000001") == ""
    assert normalize_code(None) == ""
    assert normalize_code("") == ""


def test_fetch_all_parses_full_market_rows(monkeypatch) -> None:
    now_ms = 1234567
    captured: dict[str, object] = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        captured["timeout"] = timeout
        return SimpleResponse(
            _clist_response(
                [
                    _em_diff_row(code=300720, name="海川智能"),
                    _em_diff_row(code=509, name="华塑控股", net=60704000.0, net_pct=15.37),
                ],
                total=2,
            )
        )

    monkeypatch.setattr("requests.get", fake_get)
    provider = _provider(now_ms=lambda: now_ms)
    batch = provider._fetch_all_sync(session_date="2026-07-30")

    assert captured["url"] == "https://push2.eastmoney.com/api/qt/clist/get"
    assert captured["params"]["pn"] == 1
    assert captured["timeout"] == 20.0
    headers = captured["headers"] or {}
    assert "Mozilla" in str(headers.get("User-Agent", ""))
    assert batch.session_date == "2026-07-30"
    assert batch.source == "akshare_eastmoney_rank"
    assert len(batch.rows) == 2
    assert len(batch.failures) == 0

    first = batch.rows[0]
    assert first["code"] == "300720"
    assert first["name"] == "海川智能"
    assert first["zlje"] == -83062800.0
    assert first["zljzb"] == -24.81
    assert first["source"] == "eastmoney_seed"
    assert first["moneyFlowSource"] == "eastmoney_seed"
    assert first["moneyFlowEstimated"] is True
    assert first["sessionDate"] == "2026-07-30"
    assert first["sourceTs"] == now_ms
    assert "inflow" not in first
    assert "outflow" not in first

    second = batch.rows[1]
    assert second["code"] == "000509"
    assert second["zlje"] == 60704000.0
    assert second["zljzb"] == 15.37


def test_fetch_all_paginates_until_total(monkeypatch) -> None:
    pages: list[dict[str, object]] = []

    def fake_get(url, params=None, headers=None, timeout=None):
        pages.append(params)
        page = int(params["pn"])
        if page == 1:
            return SimpleResponse(_clist_response([_em_diff_row(code=100 + i) for i in range(100)], total=250))
        if page == 2:
            return SimpleResponse(_clist_response([_em_diff_row(code=200 + i) for i in range(100)], total=250))
        return SimpleResponse(_clist_response([_em_diff_row(code=300 + i) for i in range(50)], total=250))

    monkeypatch.setattr("requests.get", fake_get)
    provider = _provider()
    batch = provider._fetch_all_sync(session_date="2026-07-30")

    assert [p["pn"] for p in pages] == [1, 2, 3]
    assert len(batch.rows) == 250
    assert batch.rows[0]["code"] == "000100"
    assert batch.rows[-1]["code"] == "000349"


def test_fetch_all_respects_page_interval(monkeypatch) -> None:
    sleeps: list[float] = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    def fake_get(url, params=None, headers=None, timeout=None):
        page = int(params["pn"])
        if page == 1:
            return SimpleResponse(_clist_response([_em_diff_row(code=100 + i) for i in range(100)], total=250))
        if page == 2:
            return SimpleResponse(_clist_response([_em_diff_row(code=200 + i) for i in range(100)], total=250))
        return SimpleResponse(_clist_response([_em_diff_row(code=300 + i) for i in range(50)], total=250))

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr("time.sleep", fake_sleep)
    provider = _provider(page_interval_seconds=0.5)
    provider._fetch_all_sync(session_date="2026-07-30")

    assert sleeps == [0.5, 0.5]  # 第 1、2 页后各间隔一次，最后一页后不再 sleep


def test_fetch_all_maps_connection_error_to_rate_limited(monkeypatch) -> None:
    import requests

    def boom(url, params=None, headers=None, timeout=None):
        raise requests.exceptions.ConnectionError("Remote end closed connection without response")

    monkeypatch.setattr("requests.get", boom)
    provider = _provider()
    with pytest.raises(AkshareFundProviderError) as exc_info:
        provider._fetch_all_sync(session_date="2026-07-30")
    assert exc_info.value.code == "ths_rate_limited"


def test_fetch_all_maps_timeout(monkeypatch) -> None:
    import requests

    def hang(url, params=None, headers=None, timeout=None):
        raise requests.exceptions.ReadTimeout("read timed out")

    monkeypatch.setattr("requests.get", hang)
    provider = _provider()
    with pytest.raises(AkshareFundProviderError) as exc_info:
        provider._fetch_all_sync(session_date="2026-07-30")
    assert exc_info.value.code == "ths_timeout"


def test_fetch_all_maps_invalid_payload(monkeypatch) -> None:
    def bad(url, params=None, headers=None, timeout=None):
        return SimpleResponse("not-json")

    monkeypatch.setattr("requests.get", bad)
    provider = _provider()
    with pytest.raises(AkshareFundProviderError) as exc_info:
        provider._fetch_all_sync(session_date="2026-07-30")
    assert exc_info.value.code == "ths_invalid_payload"


def test_fetch_all_prefers_ipv4_during_call(monkeypatch) -> None:
    """IPv6 链路黑洞环境下，请求期间 DNS 解析必须优先返回 IPv4。"""
    captured: dict[str, object] = {}

    def fake_getaddrinfo(host: str, port: int, *args, **kwargs):
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (host, port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.2.3.4", port)),
        ]

    def fake_get(url, params=None, headers=None, timeout=None):
        infos = socket.getaddrinfo("push2.eastmoney.com", 80)
        captured["families"] = [item[0] for item in infos]
        return SimpleResponse(_clist_response([_em_diff_row(code=300720)], total=1))

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("requests.get", fake_get)
    provider = _provider()
    batch = provider._fetch_all_sync(session_date="2026-07-30")

    assert captured["families"] == [socket.AF_INET]
    assert batch.rows[0]["code"] == "300720"
    # provider 退出后 getaddrinfo 恢复为进入 _ipv4_first_dns 时的值（monkeypatch 的 fake）
    assert socket.getaddrinfo is fake_getaddrinfo


def test_fetch_all_rejects_empty_frame(monkeypatch) -> None:
    def empty(url, params=None, headers=None, timeout=None):
        return SimpleResponse(_clist_response([], total=0))

    monkeypatch.setattr("requests.get", empty)
    provider = _provider()
    batch = provider._fetch_all_sync(session_date="2026-07-30")
    assert batch.rows == []
    assert batch.failures == []


def test_zljzb_absent_when_net_ratio_missing(monkeypatch) -> None:
    def fake_get(url, params=None, headers=None, timeout=None):
        return SimpleResponse(
            _clist_response(
                [
                    _em_diff_row(code=300720, name="海川智能", net=-83062800.0, net_pct=None),
                    _em_diff_row(code=509, name="华塑控股", net=60704000.0, net_pct="-"),
                ],
                total=2,
            )
        )

    monkeypatch.setattr("requests.get", fake_get)
    provider = _provider()
    batch = provider._fetch_all_sync(session_date="2026-07-30")

    assert "zljzb" not in batch.rows[0]
    assert "zljzb" not in batch.rows[1]
    assert batch.rows[0]["zlje"] == -83062800.0


def test_fetch_all_records_parse_failures_but_keeps_valid_rows(monkeypatch) -> None:
    def fake_get(url, params=None, headers=None, timeout=None):
        return SimpleResponse(
            _clist_response(
                [
                    _em_diff_row(code=300720, name="海川智能"),
                    _em_diff_row(code=300999, name="坏数据", net="-", net_pct="-"),
                    _em_diff_row(code=None, name="无代码", net=0.0, net_pct=0.0),
                ],
                total=3,
            )
        )

    monkeypatch.setattr("requests.get", fake_get)
    provider = _provider()
    batch = provider._fetch_all_sync(session_date="2026-07-30")

    assert len(batch.rows) == 1
    assert batch.rows[0]["code"] == "300720"
    assert len(batch.failures) == 2
    assert all(failure["reason"] == "invalid_stock_code_or_zlje" for failure in batch.failures)
    codes = {failure["code"] for failure in batch.failures}
    assert codes == {"300999", ""}


@pytest.mark.asyncio
async def test_fetch_all_async_wrapper(monkeypatch) -> None:
    def fake_get(url, params=None, headers=None, timeout=None):
        return SimpleResponse(_clist_response([_em_diff_row(code=300720, name="海川智能")], total=1))

    monkeypatch.setattr("requests.get", fake_get)
    provider = _provider()
    batch = await provider.fetch_all(session_date="2026-07-30")
    assert len(batch.rows) == 1
    assert batch.rows[0]["zlje"] == -83062800.0


class SimpleResponse:
    def __init__(self, body: str, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code

    def json(self):
        try:
            return json.loads(self._body)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid json payload: {error}") from error

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            error = requests.exceptions.HTTPError(f"{self.status_code} Server Error")
            error.response = self
            raise error


def test_fetch_all_maps_http_429_to_rate_limited(monkeypatch) -> None:
    def fake_get(url, params=None, headers=None, timeout=None):
        return SimpleResponse("{}", status_code=429)

    monkeypatch.setattr("requests.get", fake_get)
    provider = _provider()
    with pytest.raises(AkshareFundProviderError) as exc:
        provider._fetch_all_sync(session_date="2026-07-30")
    assert exc.value.code == "ths_rate_limited"


def test_fetch_all_maps_http_5xx_to_upstream_unavailable(monkeypatch) -> None:
    def fake_get(url, params=None, headers=None, timeout=None):
        return SimpleResponse("", status_code=503)

    monkeypatch.setattr("requests.get", fake_get)
    provider = _provider()
    with pytest.raises(AkshareFundProviderError) as exc:
        provider._fetch_all_sync(session_date="2026-07-30")
    assert exc.value.code == "ths_upstream_unavailable"
