# -*- coding: utf-8 -*-
"""jev_client 瞬时失败重试测试（全 mock，零真实调用，零真实 sleep）。

背景：2026-10-09 上游 typesafe/jev 间歇性执行故障（500/2002），同载荷存在
亚分钟级 ✅→❌→✅ 抖动；秒级退避重试可接住翻转窗口。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.jev import jev_client
from backend.services.jev.jev_client import _envelope_completed, call_jev

OK = {"result": {"state": "Completed",
                 "result": {"model": "jev-1.13.0", "answers": {"q": {"type": "choice", "choice": "start"}}}},
      "success": True}
FAIL = {"success": False, "errors": [{"message": "Model execution failed (Error)"}]}


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(jev_client.time, "sleep", lambda s: slept.append(s))
    return slept


def test_retry_converts_transient_failure(monkeypatch, _no_real_sleep):
    """前两次失败、第三次成功 → 返回成功；恰好重试 2 次、退避 2s/5s。"""
    seq = [dict(FAIL), dict(FAIL), dict(OK)]
    calls: list[int] = []

    def _fake_primary(*args, **kwargs):
        calls.append(1)
        return dict(seq[len(calls) - 1]), 10

    monkeypatch.setattr(jev_client, "_call_primary", _fake_primary)
    envelope, _ = call_jev("acc", "tok", {}, {})
    assert len(calls) == 3  # 共 3 次尝试
    assert _envelope_completed(envelope) is True
    assert _no_real_sleep == [2.0, 5.0]  # 失败后才退避，序列与 JEV_RETRY_DELAYS 一致


def test_retry_all_fail_returns_last(monkeypatch):
    """全败：共 3 次尝试，返回最后一次的 failure envelope。"""
    calls: list[int] = []
    monkeypatch.setattr(jev_client, "_call_primary",
                        lambda *a, **k: (calls.append(1) or (dict(FAIL), 10)))
    envelope, _ = call_jev("acc", "tok", {}, {})
    assert len(calls) == 3
    assert envelope["errors"] == FAIL["errors"]


def test_first_attempt_success_no_retry(monkeypatch):
    """首试即成功：不重试、不 sleep。"""
    calls: list[int] = []
    monkeypatch.setattr(jev_client, "_call_primary",
                        lambda *a, **k: (calls.append(1) or (dict(OK), 8)))
    envelope, ms = call_jev("acc", "tok", {}, {})
    assert len(calls) == 1 and ms == 8
    assert _envelope_completed(envelope) is True
