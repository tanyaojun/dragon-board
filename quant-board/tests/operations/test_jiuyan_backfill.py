# -*- coding: utf-8 -*-
"""韭研回填 CLI 认证解析测试（--token 手动路径 vs 自动认证链；全 mock）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jiuyan_backfill


def test_resolve_backfill_auth_manual_pair_wins(monkeypatch):
    monkeypatch.setenv("JIUYAN_SESSION", "STATIC")
    monkeypatch.setattr("backend.operations.jiuyan_auth.resolve_auth",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("手动路径不应触发认证链")))
    out = jiuyan_backfill.resolve_backfill_auth("T" * 80, "TS0")
    assert out["ok"] is True
    assert out["session"] == "STATIC" and out["token"] == "T" * 80 and out["timestamp"] == "TS0"
    assert out["source"] == "manual-backfill"


def test_resolve_backfill_auth_auto_uses_auth_chain(monkeypatch):
    monkeypatch.setattr("backend.operations.jiuyan_auth.resolve_auth",
                        lambda **kw: {"ok": True, "session": "DYN", "token": "M" * 80,
                                      "timestamp": "TS1", "source": "login+minted"})
    out = jiuyan_backfill.resolve_backfill_auth(None, None)
    assert out["ok"] is True and out["session"] == "DYN" and out["source"] == "login+minted"


def test_resolve_backfill_auth_auto_fail_visible(monkeypatch):
    monkeypatch.setattr("backend.operations.jiuyan_auth.resolve_auth",
                        lambda **kw: {"ok": False, "error": "无可用凭据", "authFailed": True})
    out = jiuyan_backfill.resolve_backfill_auth(None, None)
    assert out["ok"] is False and "无可用凭据" in out["error"]


def test_resolve_backfill_auth_manual_pair_requires_session(monkeypatch):
    monkeypatch.delenv("JIUYAN_SESSION", raising=False)
    out = jiuyan_backfill.resolve_backfill_auth("T" * 80, "TS0")
    assert out["ok"] is False and "JIUYAN_SESSION" in out["error"]
