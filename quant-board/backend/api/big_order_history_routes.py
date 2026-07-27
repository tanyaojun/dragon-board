from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.big_order_archive_service import BigOrderArchiveError, BigOrderArchiveService


router = APIRouter(prefix="/api/big-order", tags=["big-order"])


@router.get("/history")
def get_big_order_history(
    source: str,
    stockCode: str,
    sessionDate: date,
):
    try:
        return {"ok": True, "data": BigOrderArchiveService().load(source, stockCode, sessionDate)}
    except BigOrderArchiveError as error:
        status_code = 404 if error.code == "archive_not_found" else 422
        return JSONResponse(
            status_code=status_code,
            content={"ok": False, "errorCode": error.code, "error": str(error)},
        )
