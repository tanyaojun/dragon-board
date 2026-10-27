# -*- coding: utf-8 -*-
"""KPL 代理路由 `backend/api/kpl_proxy_routes.py` 合同测试（2026-10-27 加）。

钉住 fail-visible 合同（AGENTS §4.0）：
1. 上游 :8002 正常 → 状态原样透传；
2. 上游不可用 → 结构化 502（ok=False + degraded=True + reason），不得空数据伪装成功；
3. 上游异常 JSON/网络错误 → 同样结构化 502。

测试红线：全部 mock 上游（httpx AsyncClient / websockets），零真实连接。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import kpl_proxy_routes


class _FakeResponse:
    def __init__(self, content, status_code=200):
        self._content = content
        self.status_code = status_code

    def json(self):
        return self._content


class _FakeAsyncClient:
    """上下文管理器风格的假 httpx.AsyncClient（共享客户端契约：is_closed 可查）。"""
    responses = []  # 由测试注入
    fail_with = None
    is_closed = False

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, timeout=None):
        if _FakeAsyncClient.fail_with:
            raise _FakeAsyncClient.fail_with
        return _FakeAsyncClient.responses.pop(0)

    async def post(self, url, json=None, timeout=None):
        if _FakeAsyncClient.fail_with:
            raise _FakeAsyncClient.fail_with
        return _FakeAsyncClient.responses.pop(0)


@pytest.fixture()
def client(monkeypatch):
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.fail_with = None
    monkeypatch.setattr(kpl_proxy_routes.httpx, "AsyncClient", _FakeAsyncClient)
    kpl_proxy_routes._SHARED_CLIENT = None  # 共享客户端重建（否则跨测试复用真客户端）
    app = FastAPI()
    app.include_router(kpl_proxy_routes.router)
    return TestClient(app)


def test_status_passthrough(client):
    _FakeAsyncClient.responses = [
        _FakeResponse({"ok": True, "status": "streaming", "sessions": 3})
    ]
    r = client.get("/api/kpl/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "streaming"
    assert body["sessions"] == 3


def test_upstream_unavailable_is_structured_502(client):
    _FakeAsyncClient.fail_with = OSError("connection refused")
    r = client.get("/api/kpl/status")
    assert r.status_code == 502
    body = r.json()
    assert body["ok"] is False
    assert body["degraded"] is True
    assert "kpl_upstream_unavailable" in body["reason"]


def test_start_stop_post_passthrough(client):
    _FakeAsyncClient.responses = [
        _FakeResponse({"ok": True, "running": True}),
        _FakeResponse({"ok": True, "running": False}),
    ]
    assert client.post("/api/kpl/start").json()["running"] is True
    assert client.post("/api/kpl/stop").json()["running"] is False


def test_subscriptions_passthrough(client):
    _FakeAsyncClient.responses = [
        _FakeResponse({"ok": True, "subscriptions": {"count": 240, "running": True}})
    ]
    r = client.post("/api/kpl/subscriptions", json={"stock_ids": ["801159"]})
    assert r.status_code == 200
    assert r.json()["subscriptions"]["count"] == 240


class TestHistoryReads:
    """历史回看读口（KPL HTTP 三端点）：日期校验 + 服务层结构化错误透出。"""

    def test_missing_date_rejected_400(self, client):
        r = client.get("/api/kpl/sector-ranking")
        assert r.status_code == 400
        assert r.json()["ok"] is False

    def test_malformed_date_rejected_400(self, client):
        assert client.get("/api/kpl/sector-ranking", params={"date": "20261024"}).status_code == 400
        assert client.get(
            "/api/kpl/sector-stocks", params={"plate": "801159", "date": "x"}).status_code == 400

    def test_missing_plate_rejected_400(self, client):
        r = client.get("/api/kpl/sector-stocks", params={"date": "2026-10-24"})
        assert r.status_code == 400
        assert r.json()["reason"] == "missing_plate"

    def test_ranking_ok_passthrough(self, client, monkeypatch):
        monkeypatch.setattr(
            kpl_proxy_routes.kpl_ranking_service, "get_sector_ranking",
            lambda date: {"ok": True, "date": date, "items": [{"plate_id": "801159"}]})
        r = client.get("/api/kpl/sector-ranking", params={"date": "2026-10-24"})
        assert r.status_code == 200
        assert r.json()["items"][0]["plate_id"] == "801159"

    def test_ranking_service_error_structured_502(self, client, monkeypatch):
        from backend.services.kpl_ranking_service import KplRankingError

        def _raise(date):
            raise KplRankingError("kpl_errcode", errorCode="1020")

        monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_sector_ranking", _raise)
        r = client.get("/api/kpl/sector-ranking", params={"date": "2026-10-24"})
        assert r.status_code == 502
        body = r.json()
        assert body["ok"] is False and body["degraded"] is True
        assert body["errorCode"] == "1020"

    def test_stocks_service_error_structured_502(self, client, monkeypatch):
        from backend.services.kpl_ranking_service import KplRankingError

        def _raise(plate, date, page=0):
            raise KplRankingError("empty_list_check_credentials", plate_id=plate)

        monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_sector_stocks", _raise)
        r = client.get("/api/kpl/sector-stocks",
                       params={"plate": "801159", "date": "2026-10-24"})
        assert r.status_code == 502
        assert r.json()["reason"] == "empty_list_check_credentials"

    def test_stocks_page_param_passthrough(self, client, monkeypatch):
        captured = {}

        def _fake(plate, date, page=0):
            captured["page"] = page
            return {"ok": True, "items": [], "total": 0}

        monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_sector_stocks", _fake)
        client.get("/api/kpl/sector-stocks", params={"plate": "801159", "date": "2026-10-24", "page": 2})
        assert captured["page"] == 2

    def test_stocks_negative_page_rejected_400(self, client):
        r = client.get("/api/kpl/sector-stocks",
                       params={"plate": "801159", "date": "2026-10-24", "page": -1})
        assert r.status_code == 400
        assert r.json()["reason"] == "invalid_page"


class TestWsRelay:
    """WS /api/kpl/ws/kpl-quotes 双向中继：mock 上游 websockets.connect。"""

    def test_ws_relay_downstream_and_upstream(self, client, monkeypatch):
        import asyncio
        import json as jsonlib

        upstream_msgs = [jsonlib.dumps({"type": "ping", "n": 1}),
                         jsonlib.dumps({"type": "stock_quotes", "items": []})]
        upstream_sent = []

        class _FakeUpstream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def recv(self):
                if upstream_msgs:
                    await asyncio.sleep(0.01)
                    return upstream_msgs.pop(0)
                # 无更多上游消息后挂起，等测试端关闭
                await asyncio.sleep(3600)

            async def send(self, msg):
                upstream_sent.append(msg)

        def _fake_connect(*args, **kwargs):
            return _FakeUpstream()

        monkeypatch.setattr(kpl_proxy_routes.websockets, "connect", _fake_connect)
        with client.websocket_connect("/api/kpl/ws/kpl-quotes") as ws:
            first = ws.receive_json()
            assert first["type"] == "ping"
            second = ws.receive_json()
            assert second["type"] == "stock_quotes"
            # 下行：浏览器 → 上游
            ws.send_text(jsonlib.dumps({"type": "ping", "n": 2}))
