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
from typing import Optional

import httpx
import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from backend.services import kpl_ranking_service
from backend.services.kpl_ranking_service import KplRankingError

router = APIRouter(prefix="/api/kpl", tags=["kpl-socket"])

_UPSTREAM_HTTP = "http://127.0.0.1:8002"
_UPSTREAM_WS = "ws://127.0.0.1:8002/ws/kpl-quotes"
_VOICE_WORKER = "http://127.0.0.1:32145"   # tools/VoiceWorker（本地常驻语音进程）


def _voice_offline(exc: Exception) -> JSONResponse:
    """连接层失败（拒连/超时）：fail-visible 200 + offline（前端提示启动命令并自动重试）。"""
    return JSONResponse(content={"ok": False, "offline": True,
                                 "reason": f"voice_worker_offline: {type(exc).__name__}"})


def _voice_bad_response(detail: str) -> JSONResponse:
    """在线但响应异常（非 2xx/非 JSON）：不误标 offline（避免误导排障方向）。"""
    return JSONResponse(content={"ok": False, "reason": f"voice_worker_bad_response: {detail}"})

# 共享 AsyncClient（2026-10-27）：每请求新建会在事件循环里同步加载 Windows 证书库
# ≈2s/发——:8000 KPL 路由每发中招，:8008 更被多页签轮询拖成事件循环瘫痪
_SHARED_CLIENT: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
        _SHARED_CLIENT = httpx.AsyncClient(trust_env=False)
    return _SHARED_CLIENT


@router.get("/status")
async def status() -> JSONResponse:
    return await _proxy_get("/api/kpl/status")


@router.post("/start")
async def start() -> JSONResponse:
    return await _proxy_post("/api/kpl/start")


@router.post("/stop")
async def stop() -> JSONResponse:
    return await _proxy_post("/api/kpl/stop")


@router.post("/subscriptions")
async def subscriptions(request: Request) -> JSONResponse:
    """更新 :8002 订阅清单（body: {"stock_ids": [...]}），透传采集服务。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    r = await _get_client().post(_UPSTREAM_HTTP + "/api/kpl/subscriptions", json=body or {},
                                 timeout=10)
    return JSONResponse(content=r.json(), status_code=r.status_code)


_DATE_LEN = 10


def _validate_date(date: str) -> Optional[JSONResponse]:
    """历史读口必须显式给日期（实时走 WS 不经此口），格式 YYYY-MM-DD。"""
    if not date or len(date) != _DATE_LEN or date[4] != "-" or date[7] != "-":
        return JSONResponse(
            content={"ok": False, "degraded": True,
                     "reason": "invalid_or_missing_date: 实时请走 WS，历史需 date=YYYY-MM-DD"},
            status_code=400)
    return None


@router.get("/daban-prev-day-basis")
def daban_prev_day_basis(date: str = "", codes: str = ""):
    """竞昨比原料（昨收/昨量）：date 前最近一根日K，腾讯 ifzq 逐股，按日缓存 12h。

    竞昨比=竞价成交量/昨日成交量×100%；竞价成交量=竞价成交额/(竞价价×100)，
    竞价价=昨收×(1+竞价涨幅/100)。同步 def：批量逐股拉取（首次≤数百发）入线程池，
    不阻塞事件循环。缺股以 missing 显式透出（fail-visible）。"""
    bad = _validate_date(date)
    if bad is not None:
        return bad
    code_list = [c for c in (codes or "").split(",") if c.strip()]
    if not code_list:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "missing_codes"},
            status_code=400)
    try:
        return JSONResponse(
            content=kpl_ranking_service.get_daban_prev_day_basis(date, code_list))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/plate-tree")
async def plate_tree() -> JSONResponse:
    """板块树（二级目录映射）：透传 :8002 的 2301 快照懒下载读口。"""
    return await _proxy_get("/api/kpl/plate-tree")


@router.get("/daban-list")
async def daban_list(pid_type: int = 8) -> JSONResponse:
    """2103 打板个股列表快照（KPL App 打板页签）：pid_type 8=集合竞价 / 0=即将涨停 / 6=风向标。

    数据源=socket 2103 订阅推送的最近快照（collector 缓存），非历史回看——历史走 /daban-list-history。
    """
    return await _proxy_get(f"/api/kpl/daban-list?pid_type={pid_type}")


@router.get("/daban-list-history")
async def daban_list_history(date: str = "", pid_type: int = 8) -> JSONResponse:
    """按日打板个股列表历史收盘帧（HisDaBanList HTTP，App 市场情绪·日期回看同款读口）。

    上游白名单参数（2026-10-28 实测）：仅 Day+五件套+凭据，不认页签/分页参数，
    返回默认集合；故无 page 透传（历史模式前端单发不轮询）。"""
    bad = _validate_date(date)
    if bad is not None:
        return bad
    if pid_type not in (0, 1, 2, 3, 4, 5, 6, 7, 8):
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "invalid_pid_type"},
            status_code=400)
    try:
        return JSONResponse(
            content=kpl_ranking_service.get_daban_list_history(date, pid_type))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/daban-head")
async def daban_head(date: str = "") -> JSONResponse:
    """按日打板头统计（HisDaBanHeadInfo HTTP）：今/昨涨停·封板率·跌停绝对值，KPI 三卡昨日侧来源。"""
    bad = _validate_date(date)
    if bad is not None:
        return bad
    try:
        return JSONResponse(content=kpl_ranking_service.get_daban_head_info(date))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/voice/status")
async def voice_status() -> JSONResponse:
    """VoiceWorker 状态探测（tools/VoiceWorker 本地 32145）。

    连接失败 → 200+offline（不报 500，前端自动重试）；在线但非 2xx/非 JSON → bad_response。
    """
    try:
        resp = await _get_client().get(f"{_VOICE_WORKER}/status", timeout=2.0)
    except Exception as exc:
        return _voice_offline(exc)
    if resp.status_code >= 400:
        return _voice_bad_response(f"http_{resp.status_code}")
    try:
        return JSONResponse(content=resp.json())
    except Exception as exc:
        return _voice_bad_response(f"json: {type(exc).__name__}")


@router.post("/voice/speak")
async def voice_speak(request: Request) -> JSONResponse:
    """语音播报转发（VoiceWorker POST /speak；text 上限 200 字，这里先截一层）。"""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(content={"ok": False, "reason": "invalid_json"}, status_code=400)
    text = str(body.get("text") or "").strip()
    if not text:
        return JSONResponse(content={"ok": False, "reason": "empty_text"}, status_code=400)
    payload = {"text": text[:200]}
    for key in ("rate", "volume", "voice"):
        if body.get(key) is not None:
            payload[key] = body[key]
    try:
        resp = await _get_client().post(f"{_VOICE_WORKER}/speak", json=payload, timeout=5.0)
    except Exception as exc:
        return _voice_offline(exc)
    if resp.status_code >= 400:
        return _voice_bad_response(f"http_{resp.status_code}")
    try:
        return JSONResponse(content=resp.json())
    except Exception as exc:
        return _voice_bad_response(f"json: {type(exc).__name__}")


@router.post("/voice/stop")
async def voice_stop() -> JSONResponse:
    """清空 VoiceWorker 播报队列。"""
    try:
        resp = await _get_client().post(f"{_VOICE_WORKER}/stop", timeout=3.0)
    except Exception as exc:
        return _voice_offline(exc)
    try:
        return JSONResponse(content=resp.json())
    except Exception as exc:
        return _voice_bad_response(f"json: {type(exc).__name__}")


@router.get("/live")
def live(st: int = 30) -> JSONResponse:
    """直播解说流（KPL App 直播页同源 ZhiBoContent，需 App 凭据；15s TTL 缓存）。

    同步 def：service 层是同步 urllib + 2s 节流 sleep，FastAPI 自动入线程池，
    不阻塞事件循环（同 daban_prev_day_basis 既有裁决）。凭据仅进请求参数（公共出口），
    不落日志不返回；fail-visible 结构化错误。
    """
    try:
        return JSONResponse(content=kpl_ranking_service.get_live_commentary(st=st))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/radar")
def radar(st: int = 60) -> JSONResponse:
    """市场雷达/直播流（KPL 层1 a=Radar c=HomeDingPan，仅实时；5s TTL 缓存）。同步 def 理由同 /live。"""
    try:
        return JSONResponse(content=kpl_ranking_service.get_market_radar(st=st))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/sector-ranking")
async def sector_ranking(date: str = "") -> JSONResponse:
    """按日板块强度排行（KPL 层1 RealRankingInfo Type=1+Date，历史回看读口）。"""
    bad = _validate_date(date)
    if bad is not None:
        return bad
    try:
        return JSONResponse(content=kpl_ranking_service.get_sector_ranking(date))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


@router.get("/sector-stocks")
async def sector_stocks(plate: str = "", date: str = "", page: int = 0) -> JSONResponse:
    """按日板块成分股（KPL 层3 ZhiShuStockList_W8，历史回看读口；page=每页100 只的分页序号）。

    分页契约（2026-10-27 用户裁决）：真·按页取数——一页 = 一次上游请求
    （st=page_size&Index=page*page_size），切板块/翻页各只发一枪，30s TTL 按
    (plate,date,page) 缓存；total 不可知，前端用 has_more 翻页。
    """
    bad = _validate_date(date)
    if bad is not None:
        return bad
    if not plate:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "missing_plate"},
            status_code=400)
    if page < 0:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": "invalid_page"},
            status_code=400)
    try:
        return JSONResponse(content=kpl_ranking_service.get_sector_stocks(plate, date, page=page))
    except KplRankingError as exc:
        return JSONResponse(content=exc.to_payload(), status_code=502)


async def _proxy_get(path: str) -> JSONResponse:
    try:
        # trust_env=False：忽略系统代理，防止 Clash 全局模式劫持 127.0.0.1（同 relay_page 教训）
        r = await _get_client().get(_UPSTREAM_HTTP + path, timeout=10)
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        return JSONResponse(
            content={"ok": False, "degraded": True, "reason": f"kpl_upstream_unavailable: {exc}"},
            status_code=502,
        )


async def _proxy_post(path: str) -> JSONResponse:
    try:
        r = await _get_client().post(_UPSTREAM_HTTP + path, timeout=10)
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
