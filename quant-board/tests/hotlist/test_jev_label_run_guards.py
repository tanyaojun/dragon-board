# -*- coding: utf-8 -*-
"""批次C 稳定与成本测试（2026-10-05，审查 I3/I4/I12/I15）——全 fake/monkeypatch，禁触真实 jev。

- I3 单股异常隔离：一只抛异常不炸整日/后续日期（部分异常仍写入仍继续）；
- I4 TDX 全节点不可用负缓存（不再每股重探）；
- I12 FINAL 成本口径=本次运行实付；
- I15 打标文档盖 questionSetVersion/questionSetHash 代际戳。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.operations.jev_label_jiuyan import (
    QUESTION_SET_VERSION_DRIVER,
    QUESTIONS_STOCK,
    _label_one,
    _questions_hash,
    _tdx_daily_client,
    _usage_tokens,
    run,
)


class _FakeCol:
    def __init__(self, docs: dict | None = None):
        self.docs = docs or {}
        self.replaced: list[tuple[dict, dict]] = []

    def find(self, _query, _projection=None):
        return list(self.docs.values())

    def find_one(self, query, _projection=None, sort=None):
        return self.docs.get(query.get("_id"))

    def replace_one(self, query, doc, upsert=False):
        self.replaced.append((query, doc))


class _FakeDb:
    def __init__(self, col: _FakeCol):
        self._col = col

    def __getitem__(self, name):
        if name == "jiuyan_action":
            return _FakeCol({"d1": {"_id": "d1", "tradingDate": "2026-10-09"}})
        return self._col


# ---- I3 单股隔离 + I12 本次运行成本口径 ----

def test_run_survives_single_stock_exception(monkeypatch, capsys):
    """一只股票抛异常：当日其余照常处理，异常不穿出 run()（部分异常仍写入仍继续）。"""
    db = _FakeDb(_FakeCol())
    monkeypatch.setattr(runner, "_db", lambda: db)
    monkeypatch.setattr(runner, "day_population", lambda db_, date: [
        {"stock": {"code": "600001", "name": "甲"}, "board": "b"},
        {"stock": {"code": "600002", "name": "乙"}, "board": "b"}])
    monkeypatch.setattr(runner, "_strip", lambda c: c)
    monkeypatch.setattr(runner, "hotlist_ranks", lambda db_, date, codes, *a, **k: {})
    called: list[str] = []

    def fake_label_one(db_, col, acc, token, date, code, *a, **k):
        called.append(code)
        if code == "600001":
            raise RuntimeError("mongo boom")
        return True, 120

    monkeypatch.setattr(runner, "_label_one", fake_label_one)

    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc", workers=1,
        confirm_budget=True)  # 不抛异常即通过
    assert called == ["600001", "600001", "600002"]  # 异常股重试 2 次后放弃，第二只照常打
    out = capsys.readouterr().out
    assert "mongo boom" in out  # 失败原因可见（fail-visible）
    assert "done n=2" in out


def test_final_usage_is_this_run_only(monkeypatch, capsys):
    """FINAL totalTokens=本次运行实付合计（不再扫全集合历史 usage）。"""
    db = _FakeDb(_FakeCol())
    # 预埋历史 usage 文档：不得计入 FINAL
    db._col.docs["old:1"] = {"_id": "old:1", "usage": {"total_tokens": 999999}}
    monkeypatch.setattr(runner, "_db", lambda: db)
    monkeypatch.setattr(runner, "day_population", lambda db_, date: [
        {"stock": {"code": "600001", "name": "甲"}, "board": "b"}])
    monkeypatch.setattr(runner, "_strip", lambda c: c)
    monkeypatch.setattr(runner, "hotlist_ranks", lambda db_, date, codes, *a, **k: {})
    monkeypatch.setattr(runner, "_label_one", lambda *a, **k: (True, 130))

    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc", workers=1,
        confirm_budget=True)
    out = capsys.readouterr().out
    assert "'totalTokens': 130" in out and "'calls': 1" in out
    assert "999999" not in out


def test_usage_tokens_prefers_total_then_io():
    assert _usage_tokens({"total_tokens": 50}) == 50
    assert _usage_tokens({"input_tokens": 40, "output_tokens": 10}) == 50
    assert _usage_tokens({"total_tokens": 0, "input_tokens": 40, "output_tokens": 10}) == 50
    assert _usage_tokens(None) == 0
    assert _usage_tokens("junk") == 0


# ---- I4 TDX 负缓存 ----

def test_tdx_negative_cache_skips_reprobe(monkeypatch):
    saved = (runner._TDX_DOWN_UNTIL, runner._DAILY_CLIENT)
    try:
        runner._DAILY_CLIENT = None
        runner._TDX_DOWN_UNTIL = __import__("time").time() + 999
        probed: list = []

        def _must_not_probe():
            probed.append(1)
            raise AssertionError("负缓存窗口内不应重探")

        monkeypatch.setattr(runner, "_tdx_hosts_path", _must_not_probe)
        assert _tdx_daily_client() is None
        assert probed == []
    finally:
        runner._TDX_DOWN_UNTIL, runner._DAILY_CLIENT = saved


def test_tdx_hosts_path_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("TDX_HOSTS_PATH", str(tmp_path / "hosts.json"))
    assert runner._tdx_hosts_path() == tmp_path / "hosts.json"
    monkeypatch.delenv("TDX_HOSTS_PATH")
    # 默认路径=仓库同级 python-bridge/tdx_hosts.json（不再写死 D:\ 绝对路径）
    assert runner._tdx_hosts_path().name == "tdx_hosts.json"
    assert "python-bridge" in str(runner._tdx_hosts_path())


# ---- I15 代际戳 ----

def test_label_one_stamps_question_generation(monkeypatch):
    monkeypatch.setattr(runner, "build_pilot_narrative", lambda *a, **k: "N")

    def fake_call(state, qs):
        return ("env", 5)

    monkeypatch.setattr(runner, "_dispatch_jev", fake_call)
    monkeypatch.setattr(runner, "parse_jev_response",
                        lambda env, ms, **_kw: {"ok": True,
                                                "answers": {q: {"choice": "x"} for q in QUESTIONS_STOCK},
                                                "scores": {}, "usage": {"total_tokens": 77},
                                                "model": "m", "errorCode": None, "errorDetail": None})
    col = _FakeCol()
    ok, used = _label_one(_FakeDb(col), col, "acc", "tok", "2026-10-09", "600825",
                          {"name": "X"}, "b", None)
    assert ok is True and used == 77
    doc = col.replaced[0][1]
    assert doc["questionSetVersion"] == QUESTION_SET_VERSION_DRIVER == "v3.1"
    assert doc["questionSetHash"] == _questions_hash(QUESTIONS_STOCK)
    assert doc["ammoVersion"]  # 原料代际同章


def test_questions_hash_changes_with_criteria():
    base = runner._questions_hash(QUESTIONS_STOCK)
    tweaked = {**QUESTIONS_STOCK, "driver_type": {**QUESTIONS_STOCK["driver_type"],
                                                  "instructions": "改动一个字"}}
    assert runner._questions_hash(tweaked) != base


# ---- force 口径代际重放（2026-10-16 连板口径修正回填前置）----

def test_run_force_rejudges_ok_docs(monkeypatch):
    """force=True：已 status=ok 的个股也重判（口径代际升级重放，replace_one 幂等覆盖）。

    背景：连板高度改真连板口径后，历史打标文档的弹药（盘面事实行最高板/梯队/跌停）
    全带旧口径，需 --force 回放；不带 force 维持增量补跑语义。
    """
    db = _FakeDb(_FakeCol({"2026-10-09:600001": {"_id": "2026-10-09:600001", "code": "600001",
                                                 "tradingDate": "2026-10-09", "status": "ok"}}))
    monkeypatch.setattr(runner, "_db", lambda: db)
    monkeypatch.setattr(runner, "day_population", lambda db_, date: [
        {"stock": {"code": "600001", "name": "甲"}, "board": "b"}])
    monkeypatch.setattr(runner, "_strip", lambda c: c)
    monkeypatch.setattr(runner, "hotlist_ranks", lambda db_, date, codes, *a, **k: {})
    called: list[str] = []

    def _fake(db_, col, acc, token, date, code, *a, **k):
        called.append(code)
        return True, 10

    monkeypatch.setattr(runner, "_label_one", _fake)

    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc", workers=1,
        confirm_budget=True, force=True)
    assert called == ["600001"]            # 已 ok 也被重判
    # 不带 force：已 ok 跳过，不重打
    called.clear()
    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc", workers=1,
        confirm_budget=True)
    assert called == []


def test_run_codes_filter_rejudges_only_named_stocks(monkeypatch, capsys):
    """--codes：只重打指定股票，不当日全量重烧。

    2026-10-16 停牌分辨只改「最高板/梯队」等共享语料里的一行，但受影响的往往只是个别股
    （600825 自身证据变了，其余 100 只只是共享行变了一个数）——全量 --force 会白烧
    ≈35 万 tokens/日，故给单股重跑入口。
    """
    db = _FakeDb(_FakeCol({f"2026-10-09:{c}": {"_id": f"2026-10-09:{c}", "code": c,
                                               "tradingDate": "2026-10-09", "status": "ok"}
                           for c in ("600001", "600002", "600003")}))
    monkeypatch.setattr(runner, "_db", lambda: db)
    monkeypatch.setattr(runner, "day_population", lambda db_, date: [
        {"stock": {"code": c, "name": f"股{c}"}, "board": "b"}
        for c in ("600001", "600002", "600003")])
    monkeypatch.setattr(runner, "_strip", lambda c: c)
    monkeypatch.setattr(runner, "hotlist_ranks", lambda db_, date, codes, *a, **k: {})
    called: list[str] = []

    def _fake(db_, col, acc, token, date, code, *a, **k):
        called.append(code)
        return True, 10

    monkeypatch.setattr(runner, "_label_one", _fake)

    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc", workers=1,
        confirm_budget=True, force=True, only_codes={"600002"})
    assert called == ["600002"]            # 只重打指定的那只
    # 不在当日池的 code：披露跳过，不外呼不伪造
    called.clear()
    run("2026-10-09", "2026-10-09", dry_run=False, token="tok", acc="acc", workers=1,
        confirm_budget=True, force=True, only_codes={"999999"})
    assert called == []
    assert "999999" in capsys.readouterr().out
