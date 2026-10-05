# -*- coding: utf-8 -*-
"""韭研认证链测试（resolve_auth 编排 / 登录 / 浏览器铸造合同；全部 mock，禁真调用）。"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.operations import jiuyan_auth, jiuyan_store

SESSION_KEY = "pfx:jiuyan:session"
TOKEN_KEY = "pfx:jiuyan:minted-token"


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)


def _patch_keys(monkeypatch):
    monkeypatch.setattr(jiuyan_store, "_token_cache_key", lambda: TOKEN_KEY)
    monkeypatch.setattr(jiuyan_store, "_session_cache_key", lambda: SESSION_KEY)


@pytest.fixture()
def fake_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(jiuyan_store, "get_hotlist_redis_client", lambda: fake)
    _patch_keys(monkeypatch)
    return fake


def _seed_caches(fake, session="S" * 48, token="T" * 80):
    if session is not None:
        fake.data[SESSION_KEY] = f'{{"session": "{session}", "source": "login", "savedAt": "t0"}}'
    if token is not None:
        fake.data[TOKEN_KEY] = f'{{"token": "{token}", "timestamp": "TS0", "mintedAt": "t0", "source": "minted"}}'


# ── mint_token_via_browser（playwright 合同；浏览器全程 mock） ────────────────

class _FakePage:
    def goto(self, url, timeout=None, wait_until=None):
        assert url.startswith("https://www.jiuyangongshe.com/action/")

    def wait_for_function(self, expr, timeout=None):
        pass

    def evaluate(self, expr):
        return {"timestamp": "2026-10-05T01:44:47Z", "token": "A" * 80}


class _FakeContext:
    def __init__(self):
        self.closed = False

    def new_page(self):
        return _FakePage()

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self):
        self.closed = False

    def new_context(self, user_agent=None):
        assert user_agent and "Headless" not in user_agent
        return _FakeContext()

    def close(self):
        self.closed = True


def _fake_playwright(launch_impl=None, eval_result=None):
    """构造 sync_playwright 替身；eval_result 覆盖页内铸造返回值。"""

    class FakePW:
        def __init__(self):
            self.browser = _FakeBrowser()
            self.chromium = type(
                "C", (), {"launch": staticmethod(launch_impl or (lambda headless=None: self.browser))})()

    pw = FakePW()
    if eval_result is not None:
        def new_page(self):
            page = _FakePage()
            page.evaluate = lambda expr: eval_result
            return page
        _FakeContext.new_page = new_page

    @contextlib.contextmanager
    def fake_sync_playwright():
        yield pw

    return fake_sync_playwright, pw


def test_mint_token_browser_contract(monkeypatch):
    fake_sync_playwright, pw = _fake_playwright()
    monkeypatch.setattr(jiuyan_auth, "sync_playwright", fake_sync_playwright)
    out = jiuyan_auth.mint_token_via_browser("2026-10-05")
    assert out["ok"] is True
    assert out["token"] == "A" * 80 and out["timestamp"] == "2026-10-05T01:44:47Z"
    assert out["source"] == "playwright"
    assert pw.browser.closed is True  # 用后即关，不留浏览器进程


def test_mint_token_browser_fail_visible(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("chromium gone")

    fake_sync_playwright, _ = _fake_playwright(launch_impl=boom)
    monkeypatch.setattr(jiuyan_auth, "sync_playwright", fake_sync_playwright)
    out = jiuyan_auth.mint_token_via_browser("2026-10-05")
    assert out["ok"] is False and "chromium gone" in out["error"]


def test_mint_token_browser_bad_shape_fail_visible(monkeypatch):
    fake_sync_playwright, _ = _fake_playwright(eval_result={"token": None})
    monkeypatch.setattr(jiuyan_auth, "sync_playwright", fake_sync_playwright)
    out = jiuyan_auth.mint_token_via_browser("2026-10-05")
    assert out["ok"] is False and "error" in out


# ── login_session（requests 合同） ────────────────────────────────────────────

class FakeResponse:
    def __init__(self, payload, cookies=None, set_cookie=None):
        self._payload = payload
        self.status_code = 200
        self.cookies = cookies or {}
        self.headers = {"set-cookie": set_cookie} if set_cookie else {}

    def json(self):
        return self._payload


def test_login_session_success_extracts_cookie(monkeypatch):
    captured = {}

    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["body"] = json
            captured["headers"] = headers
            return FakeResponse({"errCode": "0", "msg": "ok", "data": {}},
                                cookies={"SESSION": "SESS123"})

    monkeypatch.setattr(jiuyan_auth, "_requests_session", lambda: FakeSession())
    out = jiuyan_auth.login_session(phone="13800000000", password="pw",
                                    token="T" * 80, timestamp="TS")
    assert out["ok"] is True and out["session"] == "SESS123"
    assert captured["url"].endswith("/user/login")
    assert captured["body"] == {"phone": "13800000000", "password": "pw"}
    assert captured["headers"]["token"] == "T" * 80
    assert "Cookie" not in captured["headers"]  # 登录请求不携带旧会话


def test_login_session_set_cookie_header_fallback(monkeypatch):
    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            return FakeResponse({"errCode": 0}, set_cookie="SESSION=HDRSESS; Path=/; HttpOnly")

    monkeypatch.setattr(jiuyan_auth, "_requests_session", lambda: FakeSession())
    out = jiuyan_auth.login_session(phone="p", password="w", token="T", timestamp="TS")
    assert out["ok"] is True and out["session"] == "HDRSESS"


def test_login_session_wrong_password_fail_visible(monkeypatch):
    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            return FakeResponse({"errCode": "1", "msg": "账号或密码错误", "data": {}})

    monkeypatch.setattr(jiuyan_auth, "_requests_session", lambda: FakeSession())
    out = jiuyan_auth.login_session(phone="p", password="w", token="T", timestamp="TS")
    assert out["ok"] is False
    assert "账号或密码错误" in out["error"]
    assert out.get("authFailed") is False  # 密码错误≠会话失效，不触发自愈清除


def test_login_session_success_without_cookie_fail_visible(monkeypatch):
    class FakeSession:
        def post(self, url, json=None, headers=None, timeout=None):
            return FakeResponse({"errCode": "0", "msg": "ok", "data": {}})

    monkeypatch.setattr(jiuyan_auth, "_requests_session", lambda: FakeSession())
    out = jiuyan_auth.login_session(phone="p", password="w", token="T", timestamp="TS")
    assert out["ok"] is False and "SESSION" in out["error"]


# ── resolve_auth 编排 ─────────────────────────────────────────────────────────

def test_resolve_auth_cache_hit_no_browser(monkeypatch, fake_redis):
    _seed_caches(fake_redis)
    monkeypatch.setattr(jiuyan_auth, "mint_token_via_browser",
                        lambda date: (_ for _ in ()).throw(AssertionError("不应触发浏览器")))
    out = jiuyan_auth.resolve_auth()
    assert out["ok"] is True
    assert out["session"] == "S" * 48 and out["token"] == "T" * 80
    assert out["timestamp"] == "TS0" and out["source"] == "cache+cache"


def test_resolve_auth_mints_token_when_session_cached(monkeypatch, fake_redis):
    _seed_caches(fake_redis, token=None)
    calls = []

    def fake_mint(date):
        calls.append(date)
        return {"ok": True, "token": "M" * 80, "timestamp": "TS1", "source": "playwright"}

    monkeypatch.setattr(jiuyan_auth, "mint_token_via_browser", fake_mint)
    out = jiuyan_auth.resolve_auth(date="2026-10-05")
    assert out["ok"] is True and out["token"] == "M" * 80
    assert out["source"] == "cache+minted" and calls == ["2026-10-05"]
    assert "M" * 80 in fake_redis.data[TOKEN_KEY]  # 新 token 已缓存


def test_resolve_auth_login_when_no_cache(monkeypatch, fake_redis):
    monkeypatch.setenv("JIUYAN_PHONE", "13800000000")
    monkeypatch.setenv("JIUYAN_PASSWORD", "pw")
    monkeypatch.setenv("JIUYAN_SESSION", "STATIC")  # 有静态回退也不该用——凭据优先动态登录
    monkeypatch.setattr(jiuyan_auth, "mint_token_via_browser",
                        lambda date: {"ok": True, "token": "M" * 80, "timestamp": "TS1", "source": "playwright"})
    monkeypatch.setattr(jiuyan_auth, "login_session",
                        lambda phone, password, token, timestamp: {"ok": True, "session": "DYN"})
    out = jiuyan_auth.resolve_auth()
    assert out["ok"] is True and out["session"] == "DYN" and out["source"] == "login+minted"
    assert "DYN" in fake_redis.data[SESSION_KEY]  # 动态会话已缓存
    assert "M" * 80 in fake_redis.data[TOKEN_KEY]


def test_resolve_auth_login_failure_not_cached(monkeypatch, fake_redis):
    monkeypatch.setenv("JIUYAN_PHONE", "13800000000")
    monkeypatch.setenv("JIUYAN_PASSWORD", "pw")
    monkeypatch.delenv("JIUYAN_SESSION", raising=False)
    monkeypatch.setattr(jiuyan_auth, "mint_token_via_browser",
                        lambda date: {"ok": True, "token": "M" * 80, "timestamp": "TS1", "source": "playwright"})
    monkeypatch.setattr(jiuyan_auth, "login_session",
                        lambda phone, password, token, timestamp: {"ok": False, "error": "账号或密码错误"})
    out = jiuyan_auth.resolve_auth()
    assert out["ok"] is False and "账号或密码错误" in out["error"]
    assert SESSION_KEY not in fake_redis.data


def test_resolve_auth_env_session_fallback_not_cached(monkeypatch, fake_redis):
    monkeypatch.delenv("JIUYAN_PHONE", raising=False)
    monkeypatch.delenv("JIUYAN_PASSWORD", raising=False)
    monkeypatch.setenv("JIUYAN_SESSION", "STATIC")
    monkeypatch.setattr(jiuyan_auth, "mint_token_via_browser",
                        lambda date: {"ok": True, "token": "M" * 80, "timestamp": "TS1", "source": "playwright"})
    out = jiuyan_auth.resolve_auth()
    assert out["ok"] is True and out["session"] == "STATIC" and out["source"] == "env+minted"
    assert SESSION_KEY not in fake_redis.data  # 静态会话不入缓存


def test_resolve_auth_no_credentials_fail_visible(monkeypatch, fake_redis):
    monkeypatch.delenv("JIUYAN_PHONE", raising=False)
    monkeypatch.delenv("JIUYAN_PASSWORD", raising=False)
    monkeypatch.delenv("JIUYAN_SESSION", raising=False)
    out = jiuyan_auth.resolve_auth()
    assert out["ok"] is False and out["authFailed"] is True
    assert "JIUYAN_PHONE" in out["error"]


def test_resolve_auth_env_session_without_mint_fail_visible(monkeypatch, fake_redis):
    """静态会话在但浏览器铸造失败：ok:False，不得伪造可用凭据。"""
    monkeypatch.delenv("JIUYAN_PHONE", raising=False)
    monkeypatch.delenv("JIUYAN_PASSWORD", raising=False)
    monkeypatch.setenv("JIUYAN_SESSION", "STATIC")
    monkeypatch.setattr(jiuyan_auth, "mint_token_via_browser",
                        lambda date: {"ok": False, "error": "浏览器铸造失败"})
    out = jiuyan_auth.resolve_auth()
    assert out["ok"] is False and "浏览器铸造失败" in out["error"]


def test_resolve_auth_force_refresh_relogins(monkeypatch, fake_redis):
    _seed_caches(fake_redis)
    monkeypatch.setenv("JIUYAN_PHONE", "13800000000")
    monkeypatch.setenv("JIUYAN_PASSWORD", "pw")
    monkeypatch.setattr(jiuyan_auth, "mint_token_via_browser",
                        lambda date: {"ok": True, "token": "F" * 80, "timestamp": "TS2", "source": "playwright"})
    monkeypatch.setattr(jiuyan_auth, "login_session",
                        lambda phone, password, token, timestamp: {"ok": True, "session": "FRESH"})
    out = jiuyan_auth.resolve_auth(force_refresh=True)
    assert out["ok"] is True and out["session"] == "FRESH" and out["source"] == "login+minted"
    assert "FRESH" in fake_redis.data[SESSION_KEY]


def test_resolve_auth_force_refresh_env_fallback_still_works(monkeypatch, fake_redis):
    """force_refresh 且无凭据：退回静态会话+重铸 token，不因 force 而死。"""
    monkeypatch.delenv("JIUYAN_PHONE", raising=False)
    monkeypatch.delenv("JIUYAN_PASSWORD", raising=False)
    monkeypatch.setenv("JIUYAN_SESSION", "STATIC")
    monkeypatch.setattr(jiuyan_auth, "mint_token_via_browser",
                        lambda date: {"ok": True, "token": "F" * 80, "timestamp": "TS2", "source": "playwright"})
    out = jiuyan_auth.resolve_auth(force_refresh=True)
    assert out["ok"] is True and out["session"] == "STATIC" and out["token"] == "F" * 80
    assert out["source"] == "env+minted"
