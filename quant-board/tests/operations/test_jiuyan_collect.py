# -*- coding: utf-8 -*-
"""韭研采集编排测试（resolve_auth 接线 + authFailed 单次自愈重试；全部 mock）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.operations import jiuyan_auth, jiuyan_collect, jiuyan_store

SESSION_KEY = "pfx:jiuyan:session"
TOKEN_KEY = "pfx:jiuyan:minted-token"

AUTH_OK = {"ok": True, "session": "SESS", "token": "T" * 80, "timestamp": "TS0",
           "source": "cache+cache"}


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


class FakeDB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture()
def fake_db():
    return FakeDB()


@pytest.fixture()
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jiuyan_store, "get_hotlist_redis_client", lambda: fake)
    monkeypatch.setattr(jiuyan_store, "_token_cache_key", lambda: TOKEN_KEY)
    monkeypatch.setattr(jiuyan_store, "_session_cache_key", lambda: SESSION_KEY)
    return fake


def _patch_fetch(monkeypatch, count_results, field_results):
    count_calls, field_calls = [], []

    def fake_count(date, **kwargs):
        count_calls.append(kwargs)
        return count_results.pop(0)

    def fake_field(date, **kwargs):
        field_calls.append(kwargs)
        return field_results.pop(0)

    monkeypatch.setattr(jiuyan_collect, "fetch_count", fake_count)
    monkeypatch.setattr(jiuyan_collect, "fetch_field", fake_field)
    return count_calls, field_calls


def test_collect_success_via_cached_auth(monkeypatch, fake_db, fake_redis):
    monkeypatch.setattr(jiuyan_auth, "resolve_auth", lambda **kw: dict(AUTH_OK))
    parsed = {"fields": [{"name": "医药医疗", "count": 1, "stocks": []}],
              "totalStocks": 3, "degradedSources": []}
    _patch_fetch(monkeypatch,
                 count_results=[{"ok": True, "all": 64, "recommend": 5}],
                 field_results=[{"ok": True, "date": "2026-10-05", "parsed": parsed}])
    out = jiuyan_collect.collect_and_store("2026-10-05", "final", db=fake_db)
    assert out["ok"] is True and out["stocks"] == 3 and out["docId"] == "2026-10-05:final"
    doc = fake_db["jiuyan_action"].docs["2026-10-05:final"]
    assert doc["quality"]["tokenSource"] == "cache+cache"


def test_collect_no_auth_fail_visible(monkeypatch, fake_db, fake_redis):
    monkeypatch.setattr(jiuyan_auth, "resolve_auth",
                        lambda **kw: {"ok": False, "error": "缺 JIUYAN_PHONE/JIUYAN_PASSWORD", "authFailed": True})
    count_calls, _ = _patch_fetch(monkeypatch, count_results=[], field_results=[])
    out = jiuyan_collect.collect_and_store("2026-10-05", "final", db=fake_db)
    assert out["ok"] is False and out["authFailed"] is True
    assert "JIUYAN_PHONE" in out["error"]
    assert count_calls == []  # 无凭据不得发请求


def test_collect_probe_auth_failed_self_heals(monkeypatch, fake_db, fake_redis):
    fake_redis.data[SESSION_KEY] = '{"session": "OLD", "source": "login", "savedAt": "t0"}'
    fake_redis.data[TOKEN_KEY] = '{"token": "OLDT", "timestamp": "TS0", "mintedAt": "t0", "source": "minted"}'
    auth_seq = [dict(AUTH_OK),
                {"ok": True, "session": "FRESH", "token": "N" * 80, "timestamp": "TS1",
                 "source": "login+minted"}]
    resolve_calls = []

    def fake_resolve(**kw):
        resolve_calls.append(kw)
        return auth_seq.pop(0)

    monkeypatch.setattr(jiuyan_auth, "resolve_auth", fake_resolve)
    parsed = {"fields": [], "totalStocks": 1, "degradedSources": []}
    count_calls, field_calls = _patch_fetch(
        monkeypatch,
        count_results=[{"ok": False, "authFailed": True, "error": "登录失效"},
                       {"ok": True, "all": 9, "recommend": 1}],
        field_results=[{"ok": True, "date": "2026-10-05", "parsed": parsed}])
    out = jiuyan_collect.collect_and_store("2026-10-05", "final", db=fake_db)
    assert out["ok"] is True
    assert resolve_calls == [{"date": "2026-10-05"},
                             {"date": "2026-10-05", "force_refresh": True}]  # 第二次强制刷新（触发重登）
    assert SESSION_KEY not in fake_redis.data and TOKEN_KEY not in fake_redis.data  # 陈旧缓存已清
    assert count_calls[0]["session_cookie"] == "SESS" and count_calls[1]["session_cookie"] == "FRESH"
    assert len(field_calls) == 1


def test_collect_field_110_self_heals(monkeypatch, fake_db, fake_redis):
    monkeypatch.setattr(jiuyan_auth, "resolve_auth",
                        lambda **kw: {"ok": True, "session": "SESS", "token": "T" * 80,
                                      "timestamp": "TS0", "source": "cache+cache"} if kw.get("force_refresh")
                        else dict(AUTH_OK))
    parsed = {"fields": [], "totalStocks": 2, "degradedSources": []}
    _patch_fetch(monkeypatch,
                 count_results=[{"ok": True, "all": 5, "recommend": 0},
                                {"ok": True, "all": 5, "recommend": 0}],
                 field_results=[{"ok": False, "date": "2026-10-05",
                                 "error": "errCode=110 msg=token无效", "authFailed": True},
                                {"ok": True, "date": "2026-10-05", "parsed": parsed}])
    out = jiuyan_collect.collect_and_store("2026-10-05", "final", db=fake_db)
    assert out["ok"] is True and out["stocks"] == 2


def test_collect_field_quota_no_self_heal(monkeypatch, fake_db, fake_redis):
    """配额(errCode 9)非会话失效：一次尝试即返回，不得白耗一次重登（评审 I-1）。"""
    resolve_calls = []

    def fake_resolve(**kw):
        resolve_calls.append(kw)
        return {"ok": True, "session": "SESS", "token": "T" * 80, "timestamp": "TS0",
                "source": "cache+cache"}

    monkeypatch.setattr(jiuyan_auth, "resolve_auth", fake_resolve)
    _patch_fetch(monkeypatch,
                 count_results=[{"ok": True, "all": 5, "recommend": 0}],
                 field_results=[{"ok": False, "date": "2026-10-05",
                                 "error": "errCode=9 查阅配额耗尽(您今天的查阅次数已达到上限)",
                                 "authFailed": False, "quota": True}])
    out = jiuyan_collect.collect_and_store("2026-10-05", "final", db=fake_db)
    assert out["ok"] is False and out["authFailed"] is False and out["quota"] is True
    assert len(resolve_calls) == 1  # 只解析一次，无 force_refresh 自愈


def test_collect_self_heal_failure_reports_original(monkeypatch, fake_db, fake_redis):
    resolve_seq = [dict(AUTH_OK), {"ok": False, "error": "浏览器铸造失败", "authFailed": True}]
    monkeypatch.setattr(jiuyan_auth, "resolve_auth", lambda **kw: resolve_seq.pop(0))
    _patch_fetch(monkeypatch,
                 count_results=[{"ok": False, "authFailed": True, "error": "登录失效"}],
                 field_results=[])
    out = jiuyan_collect.collect_and_store("2026-10-05", "final", db=fake_db)
    assert out["ok"] is False and out["error"] == "登录失效"
    assert out["selfHeal"]["error"] == "浏览器铸造失败"  # 自愈失败原因留痕
    assert out["selfHeal"]["firstError"] == "登录失效"  # 首次失败也留痕（评审 I-2）


def test_collect_self_heal_retry_fail_still_marked(monkeypatch, fake_db, fake_redis):
    """重解析成功但重试仍失败：结果附 selfHeal 留痕，两个错误都可追（评审 I-2/M-5）。"""
    monkeypatch.setattr(jiuyan_auth, "resolve_auth",
                        lambda **kw: {"ok": True, "session": "FRESH", "token": "N" * 80,
                                      "timestamp": "TS1", "source": "login+minted"})
    _patch_fetch(monkeypatch,
                 count_results=[{"ok": False, "authFailed": True, "error": "登录失效"},
                                {"ok": False, "authFailed": True, "error": "登录失效"}],
                 field_results=[])
    out = jiuyan_collect.collect_and_store("2026-10-05", "final", db=fake_db)
    assert out["ok"] is False and out["error"] == "登录失效"
    assert out["selfHeal"] == {"ok": False, "firstError": "登录失效", "error": "登录失效"}
