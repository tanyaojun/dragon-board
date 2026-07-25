from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from backend.theme_heat_service import (
    ThemeHeatUnavailable,
    get_theme_heat_service as create_theme_heat_service,
)
from backend.theme_fund_cache import get_theme_fund_cache
from backend.theme_fund_stream import get_theme_fund_stream


router = APIRouter(prefix="/api/themes")
_PUBLIC_INTERNAL_KEYS = {
    "quoteRowsByCode",
    "fundRowsByCode",
    "themeStocks",
    "stockThemes",
}
_SORT_FIELDS = {"change", "volumeRatio", "mainNetInflow", "code", "name"}


def get_theme_heat_service():
    return create_theme_heat_service()


def public_theme_heat_snapshot(snapshot: dict[str, object] | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    return {key: value for key, value in snapshot.items() if key not in _PUBLIC_INTERNAL_KEYS}


def _unavailable_response(error: ThemeHeatUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "ok": False,
            "errorCode": error.code,
            "message": error.message,
            "staleData": public_theme_heat_snapshot(error.stale_data),
        },
    )


@router.get("/heat", response_model=None)
def get_theme_heat(force: bool = False) -> dict[str, object] | JSONResponse:
    try:
        snapshot = get_theme_heat_service().get_snapshot(force=force)
        return {"ok": True, "data": public_theme_heat_snapshot(snapshot)}
    except ThemeHeatUnavailable as error:
        return _unavailable_response(error)


@router.get("/fund-rows", response_model=None)
def get_theme_fund_rows(codes: str = "") -> dict[str, object] | JSONResponse:
    requested_codes = list(dict.fromkeys(code.strip() for code in codes.split(",") if code.strip()))
    rows = get_theme_fund_cache().get_latest(requested_codes)
    return {
        "ok": True,
        "version": get_theme_fund_cache().current_version(),
        "data": {
            "diff": [
                {
                    "f12": code,
                    "f62": row.get("zlje"),
                    "f66": row.get("cddje"),
                    "f69": row.get("cddjzb"),
                    "f184": row.get("zljzb"),
                    "version": row.get("version"),
                    "tradingDate": row.get("tradingDate"),
                    "isFinal": row.get("isFinal"),
                    "moneyFlowSource": row.get("moneyFlowSource"),
                    "sourceTs": row.get("sourceTs"),
                }
                for code, row in rows.items()
            ]
        },
    }


@router.websocket("/fund-stream")
async def theme_fund_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    stream = get_theme_fund_stream()
    queue = None
    try:
        initial = await websocket.receive_json()
        market_codes = initial.get("marketCodes") if isinstance(initial, dict) else []
        priority_codes = initial.get("priorityCodes") if isinstance(initial, dict) else []
        queue = await stream.subscribe_async(
            market_codes=market_codes if isinstance(market_codes, list) else [],
            priority_codes=priority_codes if isinstance(priority_codes, list) else [],
        )
        await websocket.send_json(queue.get_nowait())

        while True:
            client_task = asyncio.create_task(websocket.receive_json())
            patch_task = asyncio.create_task(queue.get())
            done, pending = await asyncio.wait(
                {client_task, patch_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if client_task in done:
                message = client_task.result()
                updated_market = message.get("marketCodes") if isinstance(message, dict) else []
                updated_priority = message.get("priorityCodes") if isinstance(message, dict) else []
                if isinstance(updated_market, list) and isinstance(updated_priority, list):
                    await stream.update_subscription_async(
                        queue,
                        market_codes=updated_market,
                        priority_codes=updated_priority,
                    )
                    await websocket.send_json(await stream.snapshot_async(updated_market, updated_priority))
            if patch_task in done:
                await websocket.send_json(patch_task.result())
    except WebSocketDisconnect:
        pass
    finally:
        if queue is not None:
            await stream.unsubscribe_async(queue)
        for task_name in ("client_task", "patch_task"):
            task = locals().get(task_name)
            if isinstance(task, asyncio.Task) and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task


@router.get("/heat/{theme_id}/stocks", response_model=None)
def get_theme_heat_stocks(
    theme_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=80, ge=1, le=500),
    sort_by: str = "change",
    descending: bool = True,
) -> dict[str, Any] | JSONResponse:
    if sort_by not in _SORT_FIELDS:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "errorCode": "invalid_sort_field",
                "message": f"unsupported sort field: {sort_by}",
            },
        )
    try:
        data = get_theme_heat_service().get_theme_stocks(
            theme_id,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            descending=descending,
        )
        return {"ok": True, "data": data}
    except ThemeHeatUnavailable as error:
        return _unavailable_response(error)
