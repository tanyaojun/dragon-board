# -*- coding: utf-8 -*-
"""JEV 叙事工作台独立页面服务（:8008，透传 :8000 API，不经 :3000 转发）。

- GET  /                → 静态单文件页面（quant-board/backend/relay_page/index.html）
- GET  /api/hotlist-jev/* → httpx 透传 http://127.0.0.1:8000（实时，不缓存）
- POST /api/hotlist-jev/* → 写操作透传（单日复跑 /relay-index/rerun、槽位 /slots/rerun、
  日级 /eod/rerun、分带表 /relay-band/refresh；超时 = _POST_PROXY_TIMEOUT_SECONDS）
启动：.\.venv\Scripts\python.exe -m uvicorn backend.serve_relay_page:app --host 127.0.0.1 --port 8008
"""
from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI(title="JEV Relay Workbench", docs_url=None, redoc_url=None)

_PAGE = Path(__file__).parent / "relay_page" / "index.html"
_UPSTREAM = "http://127.0.0.1:8000"

# 共享 AsyncClient（2026-10-27 根因修复）：每请求新建会在事件循环里同步加载 Windows
# 证书库 ≈2s/发——多页签 60s 轮询的连发把事件循环拖瘫（静态页都要 10s 的元凶）。
# trust_env=False：忽略系统代理（Clash 全局模式会劫持 127.0.0.1 目标导致 502）。
_SHARED_CLIENT = None


def _get_client():
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
        _SHARED_CLIENT = httpx.AsyncClient(trust_env=False)
    return _SHARED_CLIENT


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_PAGE, media_type="text/html")


@app.get("/api/hotlist-jev/{rest:path}")
async def proxy(rest: str, request: Request):
    """透传 hotlist-jev 读口到 8000（实时取数，不缓存不加工）。"""
    url = f"{_UPSTREAM}/api/hotlist-jev/{rest}"
    if request.url.query:
        url += "?" + request.url.query
    try:
        upstream = await _get_client().get(url, timeout=20)
        return JSONResponse(content=upstream.json(), status_code=upstream.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": f"upstream_unavailable: {exc}"},
            status_code=502)


@app.get("/api/market/{rest:path}")
async def proxy_market(rest: str, request: Request):
    """大盘读口透传（2026-10-28：总览页大盘分时走势，与 :8000 同合同）。"""
    url = f"{_UPSTREAM}/api/market/{rest}"
    if request.url.query:
        url += "?" + request.url.query
    try:
        upstream = await _get_client().get(url, timeout=20)
        return JSONResponse(content=upstream.json(), status_code=upstream.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": f"upstream_unavailable: {exc}"},
            status_code=502)


@app.get("/api/kpl/{rest:path}")


@app.get("/api/kpl/{rest:path}")
async def proxy_kpl(rest: str, request: Request):
    """透传 KPL 读口到 8000（精选板块历史回看等；实时行情走 WS 不经此）。"""
    url = f"{_UPSTREAM}/api/kpl/{rest}"
    if request.url.query:
        url += "?" + request.url.query
    try:
        upstream = await _get_client().get(url, timeout=30)
        return JSONResponse(content=upstream.json(), status_code=upstream.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": f"upstream_unavailable: {exc}"},
            status_code=502)


@app.post("/api/kpl/{rest:path}")
async def proxy_kpl_post(rest: str, request: Request):
    """写操作透传到 :8000（采集启停 start/stop、订阅清单 subscriptions）。"""
    url = f"{_UPSTREAM}/api/kpl/{rest}"
    if request.url.query:
        url += "?" + request.url.query
    try:
        body = await request.json()
    except Exception:
        body = None
    try:
        upstream = await _get_client().post(url, json=body, timeout=30)
        try:
            content = upstream.json()
        except Exception:
            content = {"ok": False, "degraded": True,
                       "reason": f"upstream_non_json: {upstream.text[:200]}"}
        return JSONResponse(content=content, status_code=upstream.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": f"upstream_unavailable: {exc}"},
            status_code=502)


# 透传超时须≥jev 客户端退避预算：退避 2s/5s/15s/30s，每次尝试读超时 60s，
# 最坏 = 5 次尝试×60s + 52s 退避 ≈ 352s（守卫测试按 (len+1)×60+sum 计算）。
# 2026-10-19 评审 F7：旧的 180s 会先截断，页面报「重跑失败」而 :8000 实际仍在跑并可能已写库
# ——用户按提示重试会白烧第二次真实模型调用（与前端 busy 防并发的成本护栏相冲）。
_POST_PROXY_TIMEOUT_SECONDS = 400


@app.post("/api/hotlist-jev/{rest:path}")
async def proxy_post(rest: str, request: Request):
    """写操作透传（2026-10-19：工作台「重跑」按钮 / 分带表刷新）。

    上游非 JSON 响应不得抛 500，统一降级为结构化 502（fail-visible）。
    """
    url = f"{_UPSTREAM}/api/hotlist-jev/{rest}"
    if request.url.query:
        url += "?" + request.url.query
    try:
        body = await request.json()
    except Exception:
        body = None
    try:
        upstream = await _get_client().post(url, json=body, timeout=_POST_PROXY_TIMEOUT_SECONDS)
        try:
            content = upstream.json()
        except Exception:
            content = {"ok": False, "degraded": True,
                       "reason": f"upstream_non_json: {upstream.text[:200]}"}
        return JSONResponse(content=content, status_code=upstream.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": f"upstream_unavailable: {exc}"},
            status_code=502)
