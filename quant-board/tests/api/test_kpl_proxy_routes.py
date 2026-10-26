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
    """上下文管理器风格的假 httpx.AsyncClient。"""
    responses = []  # 由测试注入
    fail_with = None

    def __init__(self, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        if _FakeAsyncClient.fail_with:
            raise _FakeAsyncClient.fail_with
        return _FakeAsyncClient.responses.pop(0)

    async def post(self, url):
        if _FakeAsyncClient.fail_with:
            raise _FakeAsyncClient.fail_with
        return _FakeAsyncClient.responses.pop(0)


@pytest.fixture()
def client(monkeypatch):
    _FakeAsyncClient.responses = []
    _FakeAsyncClient.fail_with = None
    monkeypatch.setattr(kpl_proxy_routes.httpx, "AsyncClient", _FakeAsyncClient)
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
