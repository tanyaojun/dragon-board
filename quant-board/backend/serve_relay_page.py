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
        # trust_env=False：忽略系统代理（Clash 全局模式会劫持 127.0.0.1 目标导致 502）
        async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
            upstream = await client.get(url)
        return JSONResponse(content=upstream.json(), status_code=upstream.status_code)
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
        async with httpx.AsyncClient(timeout=_POST_PROXY_TIMEOUT_SECONDS, trust_env=False) as client:
            upstream = await client.post(url, json=body)
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
