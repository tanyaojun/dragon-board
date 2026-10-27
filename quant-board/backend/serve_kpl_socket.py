# -*- coding: utf-8 -*-
"""KPL 实时行情 WebSocket 服务（:8002，独立于 :8000 主后端，避免互相影响）。

- GET  /kpl          → 浏览器实时面板（backend/kpl_page/index.html）
- WS   /ws/kpl-quotes → 订阅采集服务广播的行情/状态/错误事件流
- GET  /api/kpl/status → 采集服务状态（sessions/pushes/errors/last_error，fail-visible）
- POST /api/kpl/start → 启动采集线程（幂等）
- POST /api/kpl/stop  → 停止采集线程

启动：.\\.venv\\Scripts\\python.exe -m uvicorn backend.serve_kpl_socket:app --host 127.0.0.1 --port 8002
依赖（双轨，KPL_CODEC 切换）：pc（默认）= unicorn 本机模拟 libauthSign（kpl_pcemu/，
工件在 data/kpl_pcemu/，scripts/extract_kpl_pcemu.py 提取，不依赖 adb/模拟器）；
adb = 模拟器在线 + signsvc（/data/local/tmp/signsvc.dex）兼容兑底轨。
未就绪时页面显示结构化错误而非空白（fail-visible）。
身份：KPL_USER_ID/KPL_TOKEN 只从环境变量读（凭据不入仓，AGENTS.md 红线 3）；
默认游客 userId=0 可收行情但服务器会话更短；正式账户值放 .env.local / 环境变量注入。

pytest 纪律：本模块的测试不得启动真实采集线程/真实 signsvc —— 全部用 FakeCodec + 不调用 start()。
"""
from __future__ import annotations

import asyncio
import os
import queue
import time
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from backend.core import settings as _settings  # noqa: F401  # 导入即载入 .env.local（KPL_* 凭据正式唯一来源）
from backend.services.kpl_collector_service import KplCollectorService, SignSvcAdbCodec
from backend.services.kpl_pcemu import PCEmulatorCodec

app = FastAPI(title="KPL Quotes Relay", docs_url=None, redoc_url=None)

_PAGE = Path(__file__).parent / "kpl_page" / "index.html"

_ADB_PATH = os.environ.get("KPL_ADB_PATH", r"D:/Android/Sdk/platform-tools/adb.exe")
_ADB_DEVICE = os.environ.get("KPL_ADB_DEVICE", "emulator-5554")
_SIGNVC_SHELL = os.environ.get(
    "KPL_SIGNVC_SHELL",
    'su -c "export LD_LIBRARY_PATH=/data/app/com.aiyu.kaipanla-MibnEsTYjx-z7wDAymTrqQ==/lib/x86_sig; '
    'export CLASSPATH=/data/local/tmp/signsvc.dex; '
    '/system/bin/app_process32 /system/bin com.yzj.kaipanh.newindex.data.SignSvc"',
)
_DEVICE_ID = os.environ.get("KPL_DEVICE_ID", "4a81acf4-b516-3e79-ae26-40a67af7b97c")
# 身份凭据只从环境变量读（不入仓；正式值在 quant-board/.env.local，游客 userId=0 可收
# 行情但会话寿命较短；进程环境已设同名变量时以环境变量优先——settings 加载器不覆盖）
_USER_ID = os.environ.get("KPL_USER_ID", "0")
_TOKEN = os.environ.get("KPL_TOKEN", "")

# 双轨 codec：pc（默认，unicorn 本机模拟）| adb（signsvc 兼容兑底）。
# 切换需重启进程；codec 构造无副作用（懒初始化在首次调用时）。
_CODEC_MODE = os.environ.get("KPL_CODEC", "pc").strip().lower()
if _CODEC_MODE == "adb":
    _codec = SignSvcAdbCodec(_ADB_PATH, _ADB_DEVICE, _SIGNVC_SHELL)
elif _CODEC_MODE == "pc":
    _codec = PCEmulatorCodec(assets_dir=os.environ.get("KPL_PCEMU_ASSETS"))
else:
    raise RuntimeError(f"KPL_CODEC 非法值 {_CODEC_MODE!r}（仅支持 pc|adb）")

# 构造无副作用，饿汉单例避免懒初始化竞态
_service_lock = asyncio.Lock()
_service = KplCollectorService(
    _codec,
    device_id=_DEVICE_ID, user_id=_USER_ID, token=_TOKEN)


def _get_service() -> KplCollectorService:
    return _service


@app.get("/kpl")
def page() -> FileResponse:
    return FileResponse(_PAGE, media_type="text/html")


@app.get("/api/kpl/status")
def status() -> JSONResponse:
    svc = _get_service()
    return JSONResponse(content={"ok": True, "codec": _CODEC_MODE, **svc.status()})


@app.post("/api/kpl/start")
async def start() -> JSONResponse:
    svc = _get_service()
    async with _service_lock:
        if not svc.is_running():
            svc.start()
    return JSONResponse(content={"ok": True, **svc.status()})


@app.post("/api/kpl/stop")
async def stop() -> JSONResponse:
    svc = _get_service()
    async with _service_lock:
        svc.stop()
    return JSONResponse(content={"ok": True, **svc.status()})


@app.post("/api/kpl/subscriptions")
async def subscriptions(request: Request) -> JSONResponse:
    """更新 3001/3006 订阅清单（body: {"stock_ids": ["801159", ...]}）。

    下一个 3001 轮询即生效（~2s）；空清单拒绝并结构化返回（fail-visible）。
    """
    svc = _get_service()
    try:
        body = await request.json()
    except Exception:
        body = {}
    result = svc.set_subscriptions((body or {}).get("stock_ids") or [])
    status_code = 200 if result.get("ok") else 400
    return JSONResponse(content={"ok": result.pop("ok", False), "subscriptions": result,
                                 **svc.status()}, status_code=status_code)


@app.websocket("/ws/kpl-quotes")
async def ws_quotes(ws: WebSocket) -> None:
    """事件流转发：服务广播队列 → 浏览器。队列溢出/断连都 fail-visible 上报。"""
    await ws.accept()
    svc = _get_service()
    if not svc.is_running():
        # 页面显式按钮触发 start；连接时自动启动一次（首次体验友好）
        async with _service_lock:
            if not svc.is_running():
                svc.start()
    q = svc.subscribe()
    try:
        while True:
            try:
                event = await asyncio.to_thread(q.get, timeout=1.0)
            except queue.Empty:
                # 心跳 keepalive，防止代理空闲断开
                await ws.send_json({"type": "ping", "ts": time.time()})
                continue
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        svc.unsubscribe(q)
