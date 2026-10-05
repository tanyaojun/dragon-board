# -*- coding: utf-8 -*-
"""韭研认证链（2026-10-05 认证链自动化）：动态登录会话 + 浏览器铸造 token + Redis 缓存。

已验证事实（2026-10-05 浏览器抓包/探针，详见 jiuyan-collector-design.md §8）：
- 登录接口 `POST {API_BASE}/user/login`，body {"phone","password"} 明文，无前置验证码；
  但必须携带 token 头（缺/假 → errCode 110），与数据接口同款防伪；
- token 铸造 = 页内 `globalThis.nR4xKp7mQa($nuxt.$store.state.mQ7vL2xR9a, Date.now())`，
  返回 {timestamp:"…Z", token:<80hex>}，匿名 headless 页即可铸（无 cookie 调 count-pc 返回
  errCode=1「登录失效」而非 110「token无效」= token 已过防伪层）；VM 混淆+反篡改，Node
  路线已证伪 → playwright headless chromium 为唯一自动铸造路径；
- 单会话纪律：账号新登录踢掉所有旧会话——自动登录即 canonical 登录；用户在他处登录会踢掉
  自动链（下次采集自愈重登），自动登录同样会踢掉用户浏览器会话。

凭据层级（AGENTS.md §1.2 红线：静态凭据只进 .env.local，动态令牌只进 Redis 带 TTL）：
  resolve_auth()：Redis 缓存（session+token）→ 缓存缺则浏览器铸造 token / 账号密码登录
  → 无凭据则静态 JIUYAN_SESSION 回退 → 全无则 fail-visible。
  登录失败不静默回退静态会话（凭据路径必须响）；静态回退会话不入缓存（不伪装成动态凭据）。
"""
from __future__ import annotations

import os
from datetime import datetime

from backend.operations import jiuyan_store
from backend.operations.jiuyan_fetch import API_BASE, build_headers

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # 缺 playwright 时 resolve_auth 走静态回退并 fail-visible，不炸模块导入
    sync_playwright = None

LOGIN_PATH = "/user/login"
MINT_WAIT_MS = 15_000
NAV_TIMEOUT_MS = 20_000
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"
MINT_EXPR = "globalThis.nR4xKp7mQa($nuxt.$store.state.mQ7vL2xR9a, Date.now())"


def _requests_session():
    import requests

    return requests.Session()


def login_session(*, phone: str, password: str, token: str, timestamp: str) -> dict:
    """账号密码登录换 SESSION。成功 {ok, session}；失败 {ok:False, error, authFailed:False}。

    密码错误/请求异常≠会话失效（authFailed=False），不触发自愈清除语义。
    """
    sess = _requests_session()
    headers = build_headers("", token, timestamp)
    headers.pop("Cookie", None)  # 登录请求不携带旧会话
    try:
        resp = sess.post(API_BASE + LOGIN_PATH, json={"phone": phone, "password": password},
                         headers=headers, timeout=20)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"登录请求异常: {exc}", "authFailed": False}
    if resp.status_code != 200:
        return {"ok": False, "error": f"登录 HTTP {resp.status_code}", "authFailed": False}
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"登录响应非 JSON: {exc}", "authFailed": False}
    if payload.get("errCode") not in (0, "0"):
        return {"ok": False, "error": f"登录失败: {payload.get('msg')}", "authFailed": False}
    session = resp.cookies.get("SESSION") if resp.cookies is not None else None
    if not session:
        from http.cookies import SimpleCookie

        jar = SimpleCookie()
        try:
            jar.load(resp.headers.get("set-cookie") or "")
        except Exception:  # noqa: BLE001
            jar = {}
        if "SESSION" in jar:
            session = jar["SESSION"].value
    if not session:
        return {"ok": False, "authFailed": False,
                "error": "登录成功但未取得 SESSION cookie（协议可能变更，留痕排查）"}
    return {"ok": True, "session": session}


def mint_token_via_browser(date: str) -> dict:
    """headless chromium 匿名打开异动页，页内铸造 {timestamp, token}。失败 fail-visible。"""
    if sync_playwright is None:
        return {"ok": False, "error": "playwright 未安装（venv 缺 playwright 依赖）"}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(user_agent=BROWSER_UA)
                try:
                    page = context.new_page()
                    page.goto(f"https://www.jiuyangongshe.com/action/{date}",
                              timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                    page.wait_for_function("() => !!(window.nR4xKp7mQa && window.$nuxt)",
                                           timeout=MINT_WAIT_MS)
                    minted = page.evaluate(MINT_EXPR)
                finally:
                    context.close()
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"浏览器铸造失败: {exc}"}
    token = minted.get("token") if isinstance(minted, dict) else None
    timestamp = minted.get("timestamp") if isinstance(minted, dict) else None
    if not token or not timestamp:
        return {"ok": False, "error": f"铸造返回形状异常: {str(minted)[:80]}"}
    return {"ok": True, "token": str(token), "timestamp": str(timestamp), "source": "playwright"}


def resolve_auth(*, date: str | None = None, force_refresh: bool = False) -> dict:
    """解析可用认证 {ok, session, token, timestamp, source}；全无则 {ok:False, error, authFailed}。

    source = "<会话源>+<token源>"：cache|login|env + cache|minted。force_refresh 跳过两缓存
    （会话强制重登/静态回退，token 强制重铸）——仅供 authFailed 自愈路径使用。
    """
    date = date or datetime.now().strftime("%Y-%m-%d")
    phone = os.environ.get("JIUYAN_PHONE") or ""
    password = os.environ.get("JIUYAN_PASSWORD") or ""
    static_session = os.environ.get("JIUYAN_SESSION") or ""

    session = None
    session_src = None
    if not force_refresh:
        cached_session = jiuyan_store.get_cached_session()
        if cached_session and cached_session.get("session"):
            session = cached_session["session"]
            session_src = "cache"

    if session is None and not (phone and password) and not static_session:
        return {"ok": False, "authFailed": True,
                "error": "无可用凭据：Redis 无缓存会话、JIUYAN_PHONE/JIUYAN_PASSWORD 未配置、"
                         "JIUYAN_SESSION 未配置（.env.local 任填其一）"}

    token_pair = None
    token_src = None
    if not force_refresh:
        cached_token = jiuyan_store.get_cached_token()
        if cached_token and cached_token.get("token"):
            token_pair = (str(cached_token["token"]), str(cached_token["timestamp"]))
            token_src = "cache"
    if token_pair is None:
        minted = mint_token_via_browser(date)
        if not minted.get("ok"):
            return {"ok": False, "authFailed": True,
                    "error": f"token 铸造失败: {minted.get('error')}"}
        token_pair = (minted["token"], minted["timestamp"])
        token_src = "minted"
        jiuyan_store.save_token(token=minted["token"], timestamp=minted["timestamp"],
                                source="playwright")

    if session is None and phone and password:
        login = login_session(phone=phone, password=password, token=token_pair[0],
                              timestamp=token_pair[1])
        if not login.get("ok"):
            return {"ok": False, "authFailed": bool(login.get("authFailed")),
                    "error": login.get("error")}
        session = login["session"]
        session_src = "login"
        jiuyan_store.save_session(session=session, source="login")

    if session is None:
        session = static_session
        session_src = "env"

    return {"ok": True, "session": session, "token": token_pair[0], "timestamp": token_pair[1],
            "source": f"{session_src}+{token_src}"}
