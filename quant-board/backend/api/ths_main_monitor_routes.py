from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from backend.ths_main_monitor_service import (
    ThsMainMonitorError,
    ThsMainMonitorService,
    get_ths_main_monitor_service,
)


router = APIRouter(prefix="/api/big-order", tags=["big-order"])


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
    return {"ok": True, "source": "ths_main_monitor", "data": result}
