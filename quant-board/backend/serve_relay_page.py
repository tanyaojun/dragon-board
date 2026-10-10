# -*- coding: utf-8 -*-
"""JEV 叙事工作台独立页面服务（:8008，透传 :8000 API，不经 :3000 转发）。

- GET /                → 静态单文件页面（quant-board/backend/relay_page/index.html）
- GET /api/hotlist-jev/* → httpx 透传 http://127.0.0.1:8000（实时，不缓存）
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
