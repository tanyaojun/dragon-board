from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.market_proxy.concepts import get_concept_map_service
from backend.api.lhb_fallback import walk_back
from backend.market_proxy.hotlists import (
    GET_PLATFORMS,
    POST_PLATFORMS,
    get_hotlist_service,
)
from backend.market_proxy.indices import get_market_overview_service
from backend.market_proxy.limitup import get_limitup_service
from backend.market_proxy.lhb_seat_detail import (
    LhbSeatParamError,
    LhbSeatUpstreamError,
    get_lhb_seat_service,
)
from backend.market_proxy.longhu import get_longhu_service
from backend.market_proxy.quotes import get_market_quotes_cache, normalize_stock_code
from backend.market_proxy.sentiment import get_sentiment_service
from backend.market_proxy.surge import get_surge_stock_service
from backend.market_proxy.xuangubao import get_xuangubao_service
from backend.services.market.volume_ratio_service import compute_volume_ratios
from backend.services.market_history_service import (
    MarketHistoryError,
    get_service as get_market_history_service,
)


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


@router.get("/api/market/index-history", response_model=None)
def market_index_history(date: str = ""):
    """大盘指数（沪/深/创）历史收盘+涨跌幅（腾讯 ifzq 日 K，2026-10-28 KPI 历史修复）。"""
    try:
        return JSONResponse(content=get_market_history_service().index_history(date))
    except MarketHistoryError as exc:
        return JSONResponse(status_code=404, content=exc.to_payload())
    except Exception as exc:
        return JSONResponse(status_code=502, content={
            "ok": False, "reason": "index_history_upstream_error", "message": str(exc)[:200]})


@router.get("/api/market/breadth-history", response_model=None)
def market_breadth_history(date: str = ""):
    """全市场涨跌家数历史（东财 push2ex 仅最近交易日可得，本地逐日持久化累积）。"""
    try:
        return JSONResponse(content=get_market_history_service().breadth_history(date))
    except MarketHistoryError as exc:
        return JSONResponse(status_code=404, content=exc.to_payload())
    except Exception as exc:
        return JSONResponse(status_code=502, content={
            "ok": False, "reason": "breadth_history_upstream_error", "message": str(exc)[:200]})


@router.get("/api/market/index-minute", response_model=None)
def market_index_minute(code: str = "sh000001"):
    """大盘指数当日分时（腾讯 ifzq minute/query，2026-10-28 总览页大盘走势图）。

    同步 def（同步 httpx，入线程池不阻塞事件循环）；fail-visible 502。
    """
    try:
        return JSONResponse(content=get_market_history_service().index_minute(code))
    except MarketHistoryError as exc:
        return JSONResponse(status_code=502, content=exc.to_payload())
    except Exception as exc:
        return JSONResponse(status_code=502, content={
            "ok": False, "reason": "index_minute_upstream_error", "message": str(exc)[:200]})


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


@router.get("/api/market/lhb-seat-dates", response_model=None)
async def lhb_seat_dates(code: str = ""):
    """东财龙虎榜：个股历史上榜日期列表（倒序，供前端席位明细选日/空态提示）。"""
    try:
        payload = await get_lhb_seat_service().get_seat_dates(code)
    except LhbSeatParamError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "reason": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={"ok": False, "degraded": True, "source": "lhb-seat-dates",
                     "errorCode": "upstream_unavailable", "message": str(exc)[:200],
                     "code": code, "dates": []},
        )
    return JSONResponse(content={"ok": True, **payload})


@router.get("/api/market/lhb-seat-detail", response_model=None)
async def lhb_seat_detail(code: str = "", date: str = ""):
    """东财龙虎榜：个股某日买卖前 5 席位明细（东财 datacenter-web，2026-10-30 用户解禁）。"""
    try:
        payload = await get_lhb_seat_service().get_seat_detail(code, date)
    except LhbSeatParamError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "reason": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={"ok": False, "degraded": True, "source": "lhb-seat-detail",
                     "errorCode": "upstream_unavailable", "message": str(exc)[:200],
                     "code": code, "date": date, "buy": [], "sell": []},
        )
    return JSONResponse(content=payload)


@router.get("/api/market/lhb-day-detail", response_model=None)
async def lhb_day_detail(date: str = ""):
    """东财龙虎榜：全市场当日席位行按股聚合（左列表「有席位上榜」过滤集）。

    当日无数据（盘前/盘中未生成/非交易日）按日历日回看至最近有数据交易日，
    显式标注 requested_date/effective_date/note（fail-visible，不伪装当日数据）。
    """

    async def _fetch(d: str):
        try:
            return await get_lhb_seat_service().get_day_seats(d)
        except LhbSeatUpstreamError as exc:
            # 东财对无数据日期（周末/节假日/未生成）返回空响应体并抛上游异常——
            # 转译为空态继续回看；真实网络/限频故障仍走 degraded 快速失败
            if "返回数据为空" in str(exc):
                return {"ok": False, "date": d, "stocks": [], "branches": []}
            raise

    try:
        payload = await walk_back(date, _fetch, lambda p: not (p.get("stocks") or []))
    except LhbSeatParamError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "reason": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={"ok": False, "degraded": True, "source": "lhb-day-detail",
                     "errorCode": "upstream_unavailable", "message": str(exc)[:200],
                     "date": date, "stocks": []},
        )
    return JSONResponse(content=payload)


@router.get("/api/market/lhb-branch-detail", response_model=None)
async def lhb_branch_detail(date: str = "", name: str = ""):
    """东财龙虎榜：营业部反查（按名称模糊匹配，返回该营业部当日买卖个股明细）。"""
    try:
        payload = await get_lhb_seat_service().get_branch_seats(date, name)
    except LhbSeatParamError as exc:
        return JSONResponse(status_code=422, content={"ok": False, "reason": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={"ok": False, "degraded": True, "source": "lhb-branch-detail",
                     "errorCode": "upstream_unavailable", "message": str(exc)[:200],
                     "date": date, "name": name, "buy": [], "sell": []},
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


@router.get("/api/concepts/map", response_model=None)
async def concepts_map(refresh: str = ""):
    """全市场题材映射（theme_stock_mappings 集合，单一事实源），供异动监控板块聚合消费。

    2026-10-13 裁决：东财概念含指数成分/人气榜等非题材噪音，弃用；改读自家题材库。
    失败可见：Mongo 不可用且无有效磁盘缓存时返回 degraded 结构；
    陈旧磁盘缓存回退时 payload.stale=true。
    """
    try:
        payload = await get_concept_map_service().get_map(force_refresh=(refresh == "1"))
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "degraded": True,
                "source": "concept-map-theme",
                "errorCode": "upstream_unavailable",
                "message": str(exc)[:200],
                "data": [],
                "errors": [],
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


@router.post("/api/quotes/volume-ratio", response_model=None)
def volume_ratio(payload: dict[str, Any]) -> JSONResponse:
    """量比计算（Python golden，Redis TTL 缓存历史）：前端只消费结果。

    请求体：``{"stocks": [{"code": "600000", "volume": 12345}, ...]}``
    响应逐 code 返回结构化结果；部分 code 无历史时单独降级，不阻断其他 code。
    """
    stocks = payload.get("stocks") if isinstance(payload, dict) else None
    if not isinstance(stocks, list) or not stocks:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "errorCode": "missing_stocks",
                "message": "缺少 stocks 参数",
                "items": {},
            },
        )
    from backend.data.repositories import repository_factory

    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "errorCode": "storage_unavailable",
                "message": str(exc)[:200],
                "items": {},
            },
        )
    try:
        items = compute_volume_ratios(db, stocks)
    except Exception as exc:
        return JSONResponse(
            status_code=200,
            content={
                "ok": False,
                "errorCode": "volume_ratio_unavailable",
                "message": str(exc)[:200],
                "items": {},
            },
        )
    return JSONResponse(
        content={
            "ok": True,
            "source": "quantboard_volume_ratio",
            "items": items,
        }
    )