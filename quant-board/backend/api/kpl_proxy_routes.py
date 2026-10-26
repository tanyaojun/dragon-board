# -*- coding: utf-8 -*-
"""KPL 实时行情代理路由（:8000 → KPL 服务 :8002）。

- GET  /api/kpl/status       → 透传 :8002 状态（fail-visible：服务不可用返回结构化 502）
- POST /api/kpl/start|stop   → 透传采集启停
- WS   /ws/kpl-quotes        → 双向中继 :8002 的行情事件流到浏览器

KPL 服务本体在 backend/serve_kpl_socket.py（:8002，独立进程，避免 adb/signsvc
依赖影响主后端生命周期）；本路由只做转发，不承载采集逻辑。
pytest 纪律：本路由的测试仅 mock 上游，不触发真实连接。
"""
from __future__ import annotations

import asyncio

import httpx
import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/kpl", tags=["kpl-socket"])

_UPSTREAM_HTTP = "http://127.0.0.1:8002"
_UPSTREAM_WS = "ws://127.0.0.1:8002/ws/kpl-quotes"


@router.get("/status")
async def status() -> JSONResponse:
    return await _proxy_get("/api/kpl/status")


@router.post("/start")
async def start() -> JSONResponse:
    return await _proxy_post("/api/kpl/start")


@router.post("/stop")
async def stop() -> JSONResponse:
    return await _proxy_post("/api/kpl/stop")


async def _proxy_get(path: str) -> JSONResponse:
    try:
        # trust_env=False：忽略系统代理，防止 Clash 全局模式劫持 127.0.0.1（同 relay_page 教训）
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            r = await client.get(_UPSTREAM_HTTP + path)
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": f"kpl_upstream_unavailable: {exc}"},
            status_code=502,
        )


async def _proxy_post(path: str) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            r = await client.post(_UPSTREAM_HTTP + path)
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": f"kpl_upstream_unavailable: {exc}"},
            status_code=502,
        )


@router.websocket("/ws/kpl-quotes")
async def ws_quotes(ws: WebSocket) -> None:
    """:8000 浏览器连接 ↔ :8002 KPL 服务 双向中继。"""
    await ws.accept()
    try:
        async with websockets.connect(_UPSTREAM_WS, open_timeout=10) as upstream:
            async def pump_upstream():
                while True:
                    msg = await upstream.recv()
                    await ws.send_text(msg if isinstance(msg, str) else msg.decode())

            async def pump_downstream():
                while True:
                    msg = await ws.receive_text()
                    await upstream.send(msg)

            done, pending = await asyncio.wait(
                [asyncio.create_task(pump_upstream()), asyncio.create_task(pump_downstream())],
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            exc = next((t.exception() for t in done if t.exception()), None)
            if exc is not None and not isinstance(exc, (WebSocketDisconnect, websockets.exceptions.ConnectionClosed)):
                raise exc
    except (WebSocketDisconnect, websockets.exceptions.ConnectionClosed):
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
