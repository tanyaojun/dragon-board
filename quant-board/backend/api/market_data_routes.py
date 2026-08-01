from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.market_proxy.hotlists import (
    GET_PLATFORMS,
    POST_PLATFORMS,
    get_hotlist_service,
)
from backend.market_proxy.indices import get_market_overview_service
from backend.market_proxy.limitup import get_limitup_service
from backend.market_proxy.longhu import get_longhu_service
from backend.market_proxy.quotes import get_market_quotes_cache, normalize_stock_code
from backend.market_proxy.sentiment import get_sentiment_service
from backend.market_proxy.surge import get_surge_stock_service
from backend.market_proxy.xuangubao import get_xuangubao_service


router = APIRouter(tags=["market-data"])


def _parse_codes(value: str | None) -> list[str]:
    if not value:
        return []
    codes: list[str] = []
    for raw in str(value).split(","):
        code = normalize_stock_code(raw)
        if code and code not in codes:
            codes.append(code)
    return codes[:120]


def _missing_codes_response() -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "ok": False,
            "degraded": False,
            "source": "quotes",
            "errorCode": "missing_codes",
            "message": "缺少 codes 参数",
        },
    )


def _coerce_int(
    value: Any,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """把查询参数安全转 int：非法/空值回落默认值，再按上下限裁剪。"""
    try:
        parsed = int(str(value).strip()) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _quotes_payload(codes_value: str | None) -> dict[str, Any] | JSONResponse:
    code_list = _parse_codes(codes_value)
    if not code_list:
        return _missing_codes_response()
    cache = get_market_quotes_cache()
    status = cache.status()
    if status["rowCount"] == 0:
        # 全市场快照未就绪或刷新失败：不能伪装成“有数据但为空”，显式降级（fail-visible）。
        if status["lastError"]:
            error_code = "upstream_unavailable"
            message = status["lastError"]
        else:
            error_code = "cache_not_ready"
            message = "全市场行情缓存尚未就绪"
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "degraded": True,
                "source": "quotes",
                "errorCode": error_code,
                "message": message,
                "rc": 0,
                "data": {"diff": []},
            },
        )
    return cache.get_diff(code_list)


@router.get("/api/quotes/tencent", response_model=None)
def quotes_tencent(codes: str = ""):
    return _quotes_payload(codes)


@router.get("/api/quotes/sina", response_model=None)
def quotes_sina(codes: str = ""):
    return _quotes_payload(codes)


@router.get("/api/market/overview", response_model=None)
async def market_overview():
    service = get_market_overview_service()
    try:
        snapshot = await service.get_overview()
    except Exception as exc:
        stale = service.stale_snapshot()
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "degraded": True,
                "source": "market-overview",
                "errorCode": "upstream_unavailable",
                "message": str(exc)[:200],
                "staleData": stale,
            },
        )
    return JSONResponse(content=snapshot)


@router.get("/api/{platform}/hot", response_model=None)
async def platform_hot_get(platform: str):
    if platform not in GET_PLATFORMS:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "errorCode": "platform_not_found", "message": f"unknown platform: {platform}"},
        )
    try:
        payload = await get_hotlist_service().get(platform)
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "errorCode": "platform_not_found", "message": str(exc)},
        )
    return JSONResponse(content=payload)


@router.post("/api/{platform}/hot", response_model=None)
async def platform_hot_post(platform: str):
    if platform not in POST_PLATFORMS:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "errorCode": "platform_not_found", "message": f"unknown platform: {platform}"},
        )
    try:
        payload = await get_hotlist_service().get(platform)
    except ValueError as exc:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "errorCode": "platform_not_found", "message": str(exc)},
        )
    return JSONResponse(content=payload)


@router.get("/api/limitup/10jqka", response_model=None)
async def limitup_10jqka(date: str = ""):
    try:
        payload = await get_limitup_service().get_limit_up_list(date)
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "degraded": True,
                "source": "limitup-10jqka",
                "errorCode": "upstream_unavailable",
                "message": str(exc)[:200],
                "data": {"data": {"info": []}},
            },
        )
    return JSONResponse(content=payload)


@router.get("/api/limitup/ths/pools", response_model=None)
async def limitup_ths_pools(date: str = ""):
    try:
        payload = await get_limitup_service().get_ths_pools(date)
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "degraded": True,
                "date": date or "",
                "source": "limitup-ths-pools",
                "errorCode": "upstream_unavailable",
                "message": str(exc)[:200],
                "pools": {},
                "errors": [],
            },
        )
    return JSONResponse(content=payload)


@router.get("/api/surge-stock/performance", response_model=None)
async def surge_stock_performance():
    try:
        payload = await get_surge_stock_service().get_performance()
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "degraded": True,
                "source": "surge-stock-performance",
                "errorCode": "upstream_unavailable",
                "message": str(exc)[:200],
                "data": [],
            },
        )
    return JSONResponse(content=payload)


@router.get("/api/sentiment/composite", response_model=None)
async def sentiment_composite():
    payload = await get_sentiment_service().get()
    return JSONResponse(content=payload)


@router.get("/api/big-order/main-monitor", response_model=None)
async def big_order_main_monitor(
    stockCode: str = "",
    limit: str = "100",
    money: str = "0",
    index: str = "0",
):
    if not stockCode:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "degraded": False,
                "source": "big-order-main-monitor",
                "errorCode": "missing_stock_code",
                "message": "缺少 stockCode 参数",
            },
        )
    try:
        payload = await get_longhu_service().load_page(
            stockCode,
            money=_coerce_int(money, 0, minimum=0),
            index=_coerce_int(index, 0, minimum=0),
            limit=_coerce_int(limit, 100, minimum=1, maximum=500),
        )
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "degraded": True,
                "source": "big-order-main-monitor",
                "errorCode": "upstream_unavailable",
                "message": str(exc)[:200],
                "data": {"List": []},
            },
        )
    return JSONResponse(content=payload)


@router.get("/api/big-order/all-day", response_model=None)
async def big_order_all_day(stockCode: str = "", money: str = "0"):
    if not stockCode:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "degraded": False,
                "source": "big-order-all-day",
                "errorCode": "missing_stock_code",
                "message": "缺少 stockCode 参数",
            },
        )
    try:
        payload = await get_longhu_service().load_all_day(
            stockCode, money=_coerce_int(money, 0, minimum=0)
        )
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "degraded": True,
                "source": "big-order-all-day",
                "errorCode": "upstream_unavailable",
                "message": str(exc)[:200],
                "data": {"List": []},
            },
        )
    return JSONResponse(content=payload)


@router.get("/api/xuangubao/events", response_model=None)
async def xuangubao_events(count: str = "", types: str = ""):
    try:
        payload = await get_xuangubao_service().get_events(
            count or None, types or None
        )
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "degraded": True,
                "source": "xuangubao-events",
                "errorCode": "upstream_unavailable",
                "message": str(exc)[:200],
                "data": [],
            },
        )
    return JSONResponse(content=payload)
