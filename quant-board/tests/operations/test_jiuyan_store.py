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

    def find_one(self, flt, projection=None):
        doc = self.docs.get(flt["_id"])
        if doc is None or not projection:
            return doc
        return {k: doc.get(k) for k, v in projection.items() if v}

    def update_one(self, flt, update):
        doc = self.docs.get(flt["_id"])
        if doc is None:
            return
        for path, value in (update.get("$set") or {}).items():
            if "." in path:
                head, tail = path.split(".", 1)
                doc.setdefault(head, {})[tail] = value
            else:
                doc[path] = value
        for path, spec in (update.get("$push") or {}).items():
            items = spec.get("$each") if isinstance(spec, dict) else [spec]
            arr = list(doc.get(path) or []) + list(items or [])
            if isinstance(spec, dict) and "$slice" in spec:
                n = spec["$slice"]
                arr = arr[n:] if n < 0 else arr[:n]
            doc[path] = arr

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


# ── 午盘事实源保护（2026-10-20 重启自愈覆盖真午盘实测缺陷） ──────────────
def _noon_doc(db, fetched_at, total=65):
    save_action_doc(db, date="2026-10-20", kind="midday",
                    parsed={"fields": [{"name": "机器人", "count": 3, "stocks": [{}, {}, {}]}],
                            "totalStocks": total, "degradedSources": []},
                    counts={"all": 65})
    doc = db["jiuyan_action"].docs["2026-10-20:midday"]
    doc["fetchedAt"] = fetched_at
    return doc


def test_in_midday_noon_window_boundaries():
    assert jiuyan_store.in_midday_noon_window("2026-10-20T12:06:11")
    assert jiuyan_store.in_midday_noon_window("2026-10-20T11:00:00")
    assert jiuyan_store.in_midday_noon_window("2026-10-20T13:30:00")
    assert not jiuyan_store.in_midday_noon_window("2026-10-20T14:44:01")
    assert not jiuyan_store.in_midday_noon_window("2026-10-20T10:59:59")
    assert not jiuyan_store.in_midday_noon_window("")
    assert jiuyan_store.MIDDAY_NOON_WINDOW == jiuyan_store.MIDDAY_NOON_WINDOW


def test_noon_snapshot_survives_late_heal():
    db = FakeDB()
    _noon_doc(db, "2026-10-20T12:06:11")
    noon_fields = db["jiuyan_action"].docs["2026-10-20:midday"]["fields"]
    save_action_doc(db, date="2026-10-20", kind="midday",
                    parsed={"fields": [{"name": "公告", "count": 7, "stocks": [{}] * 7}],
                            "totalStocks": 71, "degradedSources": []},
                    counts={"all": 71}, fetched_at="2026-10-20T14:44:01")
    doc = db["jiuyan_action"].docs["2026-10-20:midday"]
    assert doc["fetchedAt"] == "2026-10-20T12:06:11", "真午盘 fetchedAt 不得被收盘后的抓取覆盖"
    assert doc["fields"] == noon_fields and doc["totalStocks"] == 65
    assert doc["quality"]["noonPreserved"] is True
    assert doc["laterObservations"] == [{
        "fetchedAt": "2026-10-20T14:44:01", "counts": {"all": 71}, "totalStocks": 71,
        "boards": [{"name": "公告", "stocks": 7}]}]


def test_late_heal_observations_are_bounded():
    db = FakeDB()
    _noon_doc(db, "2026-10-20T12:06:11")
    for minute in range(1, 9):
        save_action_doc(db, date="2026-10-20", kind="midday",
                        parsed={"fields": [], "totalStocks": minute, "degradedSources": []},
                        fetched_at=f"2026-10-20T15:{minute:02d}:00")
    doc = db["jiuyan_action"].docs["2026-10-20:midday"]
    assert doc["quality"]["noonPreserved"] is True
    assert len(doc["laterObservations"]) == jiuyan_store.LATER_OBSERVATION_LIMIT
    assert doc["laterObservations"][-1]["fetchedAt"] == "2026-10-20T15:08:00"


def test_noon_overwrites_noon_and_pseudo_noon_is_flagged():
    db = FakeDB()
    # 首次就是伪午盘（无更早的真午盘）→ 照写，但显式标记窗口外，不假装是真午盘
    save_action_doc(db, date="2026-10-20", kind="midday",
                    parsed={"fields": [], "totalStocks": 71, "degradedSources": []},
                    fetched_at="2026-10-20T20:04:00")
    doc = db["jiuyan_action"].docs["2026-10-20:midday"]
    assert doc["quality"]["noonWindowOk"] is False and doc["totalStocks"] == 71
    assert "laterObservations" not in doc
    # 真午盘刷新真午盘 → 正常覆盖（更新鲜的午盘数据）
    save_action_doc(db, date="2026-10-20", kind="midday",
                    parsed={"fields": [], "totalStocks": 66, "degradedSources": []},
                    fetched_at="2026-10-20T12:20:00")
    doc = db["jiuyan_action"].docs["2026-10-20:midday"]
    assert doc["totalStocks"] == 66 and doc["quality"]["noonWindowOk"] is True
    assert "laterObservations" not in doc


def test_midday_source_state_and_store_share_one_window():
    from backend.operations.jev_label_jiuyan import _MIDDAY_FETCH_WINDOW
    assert _MIDDAY_FETCH_WINDOW == jiuyan_store.MIDDAY_NOON_WINDOW
