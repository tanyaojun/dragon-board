from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

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
    """查看即刷新：ths-detail 成功拉到有效摘要时同步更新资金列。

    调度器只刷 fund-stream 订阅池（前端热榜 codes）；用户查看的非订阅池个股
    资金列会停留在 MongoDB 恢复的历史旧值。这里在 HTTP 查看入口顺带把
    mainMonitorDetail 摘要写入 theme-fund（fail-visible：解析失败保留 last-good，
    不阻断明细返回）。
    """
    try:
        summary = parse_l2_summary(code, raw)
        if summary is None:
            return
        get_theme_fund_cache().put(dict(summary))
    except Exception:  # noqa: BLE001 - 缓存写入失败不影响查看接口
        logger.warning("ths-detail 同步资金列失败 code=%s", code, exc_info=True)


def _refresh_theme_fund_from_rows(rows: list[dict[str, object]]) -> None:
    """查看即刷新：ths-fund-batch 的 rows 已是摘要行，批量写入资金列。"""
    if not rows:
        return
    try:
        get_theme_fund_cache().put_many([dict(row) for row in rows])
    except Exception:  # noqa: BLE001 - 缓存写入失败不影响批量查看接口
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


@router.get("/ths-fund-batch", response_model=None)
async def get_ths_fund_batch(
    codes: str = Query(default=""),
    concurrency: int = Query(default=2),
    service: ThsMainMonitorService = Depends(get_ths_main_monitor_service),
) -> dict[str, object] | JSONResponse:
    requested = list(dict.fromkeys(value.strip() for value in codes.split(",") if value.strip()))
    if len(requested) > 5:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "errorCode": "too_many_codes"},
        )
    if not requested or any(len(code) != 6 or not code.isdigit() for code in requested):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "errorCode": "invalid_stock_code"},
        )
    result = await service.load_batch(requested, concurrency=max(1, min(2, concurrency)))
    _refresh_theme_fund_from_rows(result.get("rows") or [])
    return {"ok": True, "source": "ths_main_monitor", "data": result}
