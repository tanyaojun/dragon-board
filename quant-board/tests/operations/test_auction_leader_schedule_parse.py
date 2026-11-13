# -*- coding: utf-8 -*-
"""竞价龙头挂链 stdout 解析 + 门控测试（零 jev / 零网络）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import schedule as S
from backend.operations.auction_leader_label import RESULT_MARKER


def test_parse_auction_marker_with_noise():
    stdout = ("降级披露行 {'driftBoards': ['x']}\n"
              + RESULT_MARKER + '{"ok": true, "leaders": 7, "okCount": 9, "tokensUsed": 1234}\n')
    result, err = S._parse_theme_leader_stdout(stdout, marker=RESULT_MARKER)
    assert err is None or result is not None
    assert result["okCount"] == 9 and result["tokensUsed"] == 1234


def test_parse_missing_marker_fails_visible():
    result, err = S._parse_theme_leader_stdout("no json here\n", marker=RESULT_MARKER)
    assert result is None and err


def test_enabled_gate_default_on(monkeypatch):
    monkeypatch.delenv("AUCTION_LEADER_LABEL_ENABLED", raising=False)
    assert S.auction_leader_label_enabled() is True
    monkeypatch.setenv("AUCTION_LEADER_LABEL_ENABLED", "0")
    assert S.auction_leader_label_enabled() is False


def test_run_once_disabled_skips(monkeypatch):
    monkeypatch.setenv("AUCTION_LEADER_LABEL_ENABLED", "0")
    res = S.run_auction_leader_label_once("2026-11-13")
    assert res["ok"] and res["skipped"] and res["reason"] == "disabled"


def test_run_once_dry_run_skips():
    res = S.run_auction_leader_label_once("2026-11-13", dry_run=True)
    assert res["ok"] and res["reason"] == "dry_run"

def test_parse_skip_marker_ok_true():
    """review major-4：缺席日 main 统一打标记 → 调度解析 ok=True 不误重试。"""
    stdout = RESULT_MARKER + '{"ok": true, "leaders": 0, "skippedReason": "auction_push_missing"}\n'
    result, err = S._parse_theme_leader_stdout(stdout, marker=RESULT_MARKER)
    assert result["ok"] is True and result["skippedReason"] == "auction_push_missing"


def test_parse_fetch_failed_ok_false():
    stdout = RESULT_MARKER + '{"ok": false, "errorCode": "auction_push_fetch_failed"}\n'
    result, err = S._parse_theme_leader_stdout(stdout, marker=RESULT_MARKER)
    assert result["ok"] is False
