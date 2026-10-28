# -*- coding: utf-8 -*-
"""KPL 语音代理与直播读口路由测试（2026-10-28）。

钉住合同：
1. VoiceWorker 连接失败 → fail-visible 200+offline（不 500）；在线但非 2xx/非 JSON → bad_response（不误标 offline）；
2. /voice/speak text 截 200 再转发、空文本 400；
3. /live /radar 上游异常 → 结构化 502；正常 → payload 原样透传。
测试红线：全部 mock（VoiceWorker/KPL 上游），零真实请求、零真实发声。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import kpl_proxy_routes
from backend.services.kpl_ranking_service import KplRankingError


class _FakeResponse:
    def __init__(self, payload=None, status_code=200, raw=b"not-json"):
        self._payload = payload
        self.status_code = status_code
        self._raw = raw

    def json(self):
        if self._payload is None:
            raise ValueError("invalid json")
        return self._payload


class _FakeClient:
    """假 AsyncClient：mode 切换 在线/离线/坏响应；记录调用。"""
    mode = "online"          # online | offline | badstatus | badjson
    calls = []

    async def get(self, url, timeout=None):
        _FakeClient.calls.append(("GET", url, None))
        return self._resp()

    async def post(self, url, json=None, timeout=None):
        _FakeClient.calls.append(("POST", url, json))
        return self._resp()

    @staticmethod
    def _resp():
        if _FakeClient.mode == "offline":
            raise ConnectionError("refused")
        if _FakeClient.mode == "badstatus":
            return _FakeResponse(status_code=500)
        if _FakeClient.mode == "badjson":
            return _FakeResponse()
        return _FakeResponse(payload={"ok": True, "queued": True, "queueLength": 1})


@pytest.fixture()
def client(monkeypatch):
    _FakeClient.mode = "online"
    _FakeClient.calls = []
    monkeypatch.setattr(kpl_proxy_routes, "_get_client", lambda: _FakeClient())
    app = FastAPI()
    app.include_router(kpl_proxy_routes.router)
    return TestClient(app)


def test_voice_status_offline_fail_visible(client):
    _FakeClient.mode = "offline"
    r = client.get("/api/kpl/voice/status")
    assert r.status_code == 200                       # 离线不 500：fail-visible 200
    body = r.json()
    assert body["ok"] is False and body["offline"] is True
    assert "voice_worker_offline" in body["reason"]


def test_voice_bad_response_not_marked_offline(client):
    for mode in ("badstatus", "badjson"):
        _FakeClient.mode = mode
        r = client.get("/api/kpl/voice/status")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False and "offline" not in body      # 在线但异常：不误标 offline
        assert "voice_worker_bad_response" in body["reason"]


def test_voice_speak_truncates_and_forwards(client):
    r = client.post("/api/kpl/voice/speak", json={"text": "字" * 500})
    assert r.status_code == 200 and r.json()["queued"] is True
    _, url, payload = _FakeClient.calls[-1]
    assert url.endswith("/speak") and len(payload["text"]) == 200   # 先截 200 再转发


def test_voice_speak_empty_text_rejected(client):
    r = client.post("/api/kpl/voice/speak", json={"text": "  "})
    assert r.status_code == 400 and r.json()["reason"] == "empty_text"


def test_voice_speak_offline_fail_visible(client):
    _FakeClient.mode = "offline"
    r = client.post("/api/kpl/voice/speak", json={"text": "测试播报"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["offline"] is True


def test_voice_stop_forwards(client):
    r = client.post("/api/kpl/voice/stop")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert _FakeClient.calls[-1][1].endswith("/stop")


def test_live_upstream_error_502(client, monkeypatch):
    def boom(st):
        raise KplRankingError("upstream_http_502", url="x")
    monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_live_commentary", boom)
    r = client.get("/api/kpl/live")
    assert r.status_code == 502
    assert r.json()["ok"] is False and r.json()["degraded"] is True


def test_radar_upstream_error_502(client, monkeypatch):
    def boom(st):
        raise KplRankingError("upstream_unreachable: X", url="x")
    monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_market_radar", boom)
    r = client.get("/api/kpl/radar")
    assert r.status_code == 502
    assert r.json()["ok"] is False and r.json()["degraded"] is True


def test_radar_st_passthrough(client, monkeypatch):
    seen = {}
    def fake(st):
        seen["st"] = st
        return {"ok": True, "items": []}
    monkeypatch.setattr(kpl_proxy_routes.kpl_ranking_service, "get_market_radar", fake)
    r = client.get("/api/kpl/radar?st=25")
    assert r.status_code == 200 and seen["st"] == 25
