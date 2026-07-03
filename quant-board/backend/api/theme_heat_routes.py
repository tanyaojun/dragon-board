from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.theme_heat_service import (
    ThemeHeatUnavailable,
    get_theme_heat_service as create_theme_heat_service,
)


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
