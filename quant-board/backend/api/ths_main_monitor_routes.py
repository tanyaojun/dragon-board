from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from backend.services.market.fund_stream import get_market_fund_stream
from backend.services.market.ths_fund_flow_buckets import parse_l2_summary
from backend.services.market.ths_main_monitor_service import (
    ThsMainMonitorError,
    ThsMainMonitorService,
    get_ths_main_monitor_service,
)
from backend.services.theme.fund_cache import get_theme_fund_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/big-order", tags=["big-order"])


def _refresh_theme_fund_from_raw(code: str, raw: dict[str, object]) -> None:
    """查看即刷新：ths-detail 成功拉到有效摘要时同步更新资金列并推送前端。

    调度器只刷 fund-stream 订阅池 ∪ 后端热度池；用户查看的非池内个股资金列
    会停留在历史旧值。这里在 HTTP 查看入口顺带把 mainMonitorDetail 摘要写入
    theme-fund，并 publish 到 fund-stream——前端**立即**收到该票 fund_patch，
    不用等重连/刷新页面（实盘验证 2026-08-11：仅写缓存不推送时，用户必须
    刷新浏览器才能看到新数据）。fail-visible：解析失败保留 last-good，不阻断明细返回。
    """
    try:
        summary = parse_l2_summary(code, raw)
        if summary is None:
            return
        stored = get_theme_fund_cache().put(dict(summary))
        get_market_fund_stream().publish([stored])
    except Exception:  # noqa: BLE001 - 缓存/推送失败不影响查看接口
        logger.warning("ths-detail 同步资金列失败 code=%s", code, exc_info=True)


def _refresh_theme_fund_from_rows(rows: list[dict[str, object]]) -> None:
    """查看即刷新：ths-fund-batch 的 rows 已是摘要行，批量写入资金列并推送前端。"""
    if not rows:
        return
    try:
        saved, _ = get_theme_fund_cache().put_many([dict(row) for row in rows])
        if saved:
            get_market_fund_stream().publish(saved)
    except Exception:  # noqa: BLE001 - 缓存/推送失败不影响批量查看接口
        logger.warning("ths-fund-batch 同步资金列失败 rows=%s", len(rows), exc_info=True)


@router.get("/ths-detail", response_model=None)
async def get_ths_detail(
    stockCode: str = Query(default=""),
    service: ThsMainMonitorService = Depends(get_ths_main_monitor_service),
) -> dict[str, object] | JSONResponse:
    if len(stockCode) != 6 or not stockCode.isdigit():
        return JSONResponse(
            status_code=400,
            content={"ok": False, "errorCode": "invalid_stock_code"},
        )
    try:
        result = await service.load_raw(stockCode)
    except ThsMainMonitorError as error:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "errorCode": error.code},
        )
    _refresh_theme_fund_from_raw(stockCode, result)
    data = dict(result["data"])
    data["dragonMeta"] = {
        "cache": {
            "uiStale": bool(result["stale"]),
            "ageSeconds": max(0, (int(result["servedAt"]) - int(result["fetchedAt"])) // 1000),
        }
    }
    return {
        "ok": True,
        "source": "ths-big-order-detail",
        "stockCode": stockCode,
        "sessionDate": result["sessionDate"],
        "fetchedAt": result["fetchedAt"],
        "servedAt": result["servedAt"],
        "data": data,
    }
