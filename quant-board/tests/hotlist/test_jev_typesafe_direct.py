# -*- coding: utf-8 -*-
"""官方直连通道（api.typesafe.ai）测试：适配器、重试、分流路由。全 mock 零真实调用。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.jev import jev_client, jev_sentiment_compute as v2_module
from backend.services.jev.jev_client import (
    TYPESAFE_API_URL,
    _call_typesafe_primary,
    _typesafe_to_envelope,
    call_jev_typesafe,
    parse_jev_response,
)

FLAT_OK = {"model": "jev-1.13.0",
           "answers": {"temperature": {"type": "score", "score": 1.05,
                                       "legend": {"0": "冷", "1": "中", "2": "热"},
                                       "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
                                       "confidence": 0.92}},
           "usage": {"input_tokens": 318, "output_tokens": 0}}
FAIL_401 = {"success": False, "errors": [{"message": "Unauthorized", "code": 401}]}


def test_adapter_normalizes_to_cf_envelope():
    """扁平响应 → CF envelope → parse_jev_response 直接可用（score 归一 0-100）。"""
    envelope = _typesafe_to_envelope(dict(FLAT_OK))
    assert envelope["success"] is True
    assert envelope["result"]["state"] == "Completed"
    parsed = parse_jev_response(envelope, 123, expected_keys={"temperature"})
    assert parsed["ok"] is True
    assert parsed["model"] == "jev-1.13.0"
    assert parsed["scores"] == {"temperature": 52.5}  # 1.05 / 2 * 100
    assert parsed["usage"] == {"input_tokens": 318, "output_tokens": 0}


def test_typesafe_primary_request_shape(monkeypatch):
    """请求体扁平结构 + Bearer 头 + 可选代理 opener（拦截在 opener 层校验）。"""
    captured: dict = {}

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            import json
            return json.dumps(FLAT_OK).encode()

    class _FakeOpener:
        def __init__(self, *handlers):
            captured["handlers"] = handlers

        def open(self, req, timeout):
            captured["url"] = req.full_url
            captured["auth"] = req.get_header("Authorization")
            captured["body"] = req.data
            return _FakeResp()

    monkeypatch.setattr(jev_client.urllib.request, "build_opener", lambda *h: _FakeOpener(*h))
    envelope, _ = _call_typesafe_primary("k-123", "state-text", {"q": {}}, proxy="http://127.0.0.1:7890")
    assert captured["url"] == TYPESAFE_API_URL
    assert captured["auth"] == "Bearer k-123"
    assert b'"model": "jev-latest"' in captured["body"] and b'"state": "state-text"' in captured["body"]
    assert envelope["result"]["state"] == "Completed"
    # 代理 opener 携带 ProxyHandler
    assert any(isinstance(h, jev_client.urllib.request.ProxyHandler) for h in captured["handlers"])


def test_typesafe_retry_converts_transient(monkeypatch):
    """前两次 401/网络失败、第三次成功 → 重试挽回，退避 2s/5s。"""
    slept: list[float] = []
    monkeypatch.setattr(jev_client.time, "sleep", lambda s: slept.append(s))
    seq = [dict(FAIL_401), dict(FAIL_401), _typesafe_to_envelope(dict(FLAT_OK))]
    calls: list[int] = []

    def _fake(*a, **k):
        calls.append(1)
        return dict(seq[len(calls) - 1]), 10

    monkeypatch.setattr(jev_client, "_call_typesafe_primary", _fake)
    envelope, _ = call_jev_typesafe("k", "s", {})
    assert len(calls) == 3 and slept == [2.0, 5.0]
    assert envelope["result"]["state"] == "Completed"


def test_dispatch_prefers_typesafe_key(monkeypatch):
    """JEV_TYPESAFE_KEY 存在 → 走官方直连（proxy 从环境读取），不走 CF。"""
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "ts-key")
    monkeypatch.setenv("JEV_TYPESAFE_PROXY", "http://127.0.0.1:7890")
    seen: dict = {}

    def _fake_ts(key, state, questions, proxy=None, **k):
        seen.update(key=key, proxy=proxy)
        return _typesafe_to_envelope(dict(FLAT_OK)), 5

    def _fail_cf(*a, **k):  # pragma: no cover - 走到即失败
        raise AssertionError("不应走 CF 通道")

    monkeypatch.setattr(v2_module, "call_jev_typesafe", _fake_ts)
    monkeypatch.setattr(v2_module, "call_jev", _fail_cf)
    envelope, _ = v2_module._dispatch_jev("n", {"q": {}})
    assert seen == {"key": "ts-key", "proxy": "http://127.0.0.1:7890"}
    assert envelope["result"]["state"] == "Completed"


def test_dispatch_falls_back_to_cf(monkeypatch):
    """无 JEV_TYPESAFE_KEY → 走 CF 通道（沿用 _jev_config 的 token/account）。"""
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "cf-tok", "cf-acc"))
    seen: dict = {}

    def _fake_cf(account, token, state, questions, **k):
        seen.update(account=account, token=token)
        return {"success": False, "errors": []}, 1

    monkeypatch.setattr(v2_module, "call_jev", _fake_cf)
    v2_module._dispatch_jev("n", {"q": {}})
    assert seen == {"account": "cf-acc", "token": "cf-tok"}
