# -*- coding: utf-8 -*-
"""大盘指数分时读口测试（2026-10-28，总览页大盘走势图数据源）。

钉住合同：腾讯 ifzq minute/query 行 "HHMM 价 累计量 累计额" → 归一化增量；
昨收取 qt[4]；空分时/缺昨收 fail-visible；路由上游异常 → 结构化 502。
测试红线：全 mock httpx.get，零真实上游请求。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import market_data_routes
from backend.services import market_history_service as svc


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _upstream(rows, prev="3648.30"):
    return {"data": {"sh000001": {
        "data": {"data": rows, "date": "20261028"},
        "qt": {"sh000001": ["1", "上证指数", "000001", "3676.37", prev, "3676.92"]}}}}


@pytest.fixture(autouse=True)
def _clear_cache():
    svc._CACHE.clear()
    yield
    svc._CACHE.clear()


def test_minute_rows_normalized_to_increment(monkeypatch):
    rows = ["0930 3676.92 1000 7000000", "0931 3670.00 4000 27000000", "0932 3672.00 4000 47000000"]
    monkeypatch.setattr(svc.httpx, "get", lambda url, **kw: _FakeResp(_upstream(rows)))
    out = svc.get_index_minute()
    assert out["ok"] is True and out["name"] == "上证指数" and out["prevClose"] == 3648.30
    assert [p["vol"] for p in out["points"]] == [1000, 3000, 0]      # 累计 → 逐分钟增量
    assert out["totalAmount"] == pytest.approx(47000000)
    assert out["lastPrice"] == 3672.00


def test_minute_empty_rows_fail_visible(monkeypatch):
    monkeypatch.setattr(svc.httpx, "get", lambda url, **kw: _FakeResp(_upstream([])))
    with pytest.raises(svc.MarketHistoryError) as ei:
        svc.get_index_minute()
    assert ei.value.reason == "upstream_empty_minute"


def test_minute_invalid_code_rejected(monkeypatch):
    monkeypatch.setattr(svc.httpx, "get", lambda url, **kw: _FakeResp(_upstream([])))
    with pytest.raises(svc.MarketHistoryError) as ei:
        svc.get_index_minute("sh999999")
    assert ei.value.reason == "invalid_code"


def test_index_minute_route_upstream_error_502(monkeypatch):
    def boom(code="sh000001"):
        raise svc.MarketHistoryError("upstream_unreachable", code=code)
    monkeypatch.setattr(svc, "get_index_minute", boom)   # 实例方法体调用模块级名，打补丁即生效
    app = FastAPI()
    app.include_router(market_data_routes.router)
    client = TestClient(app)
    r = client.get("/api/market/index-minute")
    assert r.status_code == 502
    body = r.json()
    assert body["ok"] is False and body["reason"] == "upstream_unreachable"
