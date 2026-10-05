# -*- coding: utf-8 -*-
"""韭研存储层测试（内存假 db，无 Mongo）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.operations import jiuyan_store
from backend.operations.jiuyan_store import (
    action_doc_id,
    get_action_doc,
    list_action_dates,
    save_action_doc,
)


class FakeCollection:
    def __init__(self):
        self.docs = {}

    def replace_one(self, flt, doc, upsert=False):
        key = flt["_id"]
        if key in self.docs or upsert:
            self.docs[key] = doc

    def find_one(self, flt):
        return self.docs.get(flt["_id"])

    def find(self, flt=None, projection=None):
        return list(self.docs.values())


class FakeDB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


def test_action_doc_id_kind_guard():
    assert action_doc_id("2026-09-30", "final") == "2026-09-30:final"
    assert action_doc_id("2026-09-30", "midday") == "2026-09-30:midday"
    with pytest.raises(ValueError):
        action_doc_id("2026-09-30", "weekly")


def test_save_and_get_idempotent_upsert():
    db = FakeDB()
    parsed = {"fields": [{"name": "医药医疗", "count": 1, "stocks": []}], "totalStocks": 1, "degradedSources": []}
    save_action_doc(db, date="2026-09-30", kind="final", parsed=parsed, counts={"all": 64}, token_source="cache")
    save_action_doc(db, date="2026-09-30", kind="final", parsed=parsed, counts={"all": 64})  # 重采覆盖
    doc = get_action_doc(db, "2026-09-30", "final")
    assert doc["tradingDate"] == "2026-09-30" and doc["updateKind"] == "final"
    assert doc["counts"] == {"all": 64} and doc["totalStocks"] == 1
    assert doc["quality"]["tokenSource"] == "cache"  # 第二次未传 → 默认 cache
    assert get_action_doc(db, "2026-09-30", "midday") is None  # 不同 kind 互不影响


def test_list_action_dates_sorted():
    db = FakeDB()
    for date, kind in (("2026-09-30", "final"), ("2026-09-01", "final"), ("2026-09-30", "midday")):
        save_action_doc(db, date=date, kind=kind, parsed={"fields": [], "totalStocks": 0, "degradedSources": []})
    dates = list_action_dates(db)
    assert [d["date"] for d in dates] == ["2026-09-01", "2026-09-30"]
    assert dates[1]["kinds"] == ["final", "midday"]


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)


def test_token_cache_roundtrip(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jiuyan_store, "get_hotlist_redis_client", lambda: fake)
    assert jiuyan_store.get_cached_token() is None
    assert jiuyan_store.save_token(token="T" * 80, timestamp="2026-10-02T00:51:52Z", source="manual") is True
    tok = jiuyan_store.get_cached_token()
    assert tok["token"] == "T" * 80 and tok["source"] == "manual" and tok["mintedAt"]
    jiuyan_store.save_token(token="NEW", timestamp="TS2", source="minted")
    assert jiuyan_store.get_cached_token()["token"] == "NEW"


def test_token_cache_unavailable_fail_visible(monkeypatch):
    monkeypatch.setattr(jiuyan_store, "get_hotlist_redis_client", lambda: None)
    assert jiuyan_store.get_cached_token() is None
    assert jiuyan_store.save_token(token="T", timestamp="TS", source="manual") is False


def test_token_cache_cleared_on_auth_failed(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jiuyan_store, "get_hotlist_redis_client", lambda: fake)
    jiuyan_store.save_token(token="OLD", timestamp="TS", source="manual")
    jiuyan_store.clear_cached_token()
    assert jiuyan_store.get_cached_token() is None


# ── 动态 SESSION 缓存（2026-10-05 认证链自动化：与铸造 token 缓存对称） ──────────

def test_session_cache_roundtrip(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jiuyan_store, "get_hotlist_redis_client", lambda: fake)
    assert jiuyan_store.get_cached_session() is None
    assert jiuyan_store.save_session(session="S" * 48, source="login") is True
    got = jiuyan_store.get_cached_session()
    assert got["session"] == "S" * 48 and got["source"] == "login" and got["savedAt"]
    jiuyan_store.save_session(session="NEW", source="login")
    assert jiuyan_store.get_cached_session()["session"] == "NEW"
    jiuyan_store.clear_cached_session()
    assert jiuyan_store.get_cached_session() is None


def test_session_cache_fail_visible(monkeypatch):
    monkeypatch.setattr(jiuyan_store, "get_hotlist_redis_client", lambda: None)
    assert jiuyan_store.get_cached_session() is None
    assert jiuyan_store.save_session(session="S", source="login") is False


def test_session_cache_rejects_empty(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jiuyan_store, "get_hotlist_redis_client", lambda: fake)
    assert jiuyan_store.save_session(session="", source="login") is False
    assert jiuyan_store.get_cached_session() is None


# ── 评审 M-1：Redis 懒连接故障时缓存层容错（返回缺失而非异常炸穿调度链） ────────

class ExplodingRedis(FakeRedis):
    def get(self, key):
        raise ConnectionError("redis down")

    def set(self, key, value, ex=None):
        raise ConnectionError("redis down")

    def delete(self, key):
        raise ConnectionError("redis down")


def test_token_cache_redis_down_fail_visible(monkeypatch):
    exploding = ExplodingRedis()
    monkeypatch.setattr(jiuyan_store, "get_hotlist_redis_client", lambda: exploding)
    assert jiuyan_store.get_cached_token() is None  # 视为无缓存，调用方走铸造路径
    assert jiuyan_store.save_token(token="T", timestamp="TS", source="manual") is False
    jiuyan_store.clear_cached_token()  # 清缓存静默容忍（缓存层无谓失败不该炸链）


def test_session_cache_redis_down_fail_visible(monkeypatch):
    exploding = ExplodingRedis()
    monkeypatch.setattr(jiuyan_store, "get_hotlist_redis_client", lambda: exploding)
    assert jiuyan_store.get_cached_session() is None
    assert jiuyan_store.save_session(session="S", source="login") is False
    jiuyan_store.clear_cached_session()
