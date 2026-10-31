# -*- coding: utf-8 -*-
"""复盘日报读口（JEV 叙事工作台【复盘日报】页，2026-10-31）。

- GET /api/hotlist-jev/daily-recap?date=YYYY-MM-DD：读 `hotlist_jev_daily_recap` 当日文档。
- 纯读零副作用、零 jev 调用：日报由 operations.jev_daily_recap（盘后 CLI/排程链）产出落库。
- 缺文档 → {ok, missing:true, missingReason}（fail-visible，不空伪装 §4.0）；读库异常 → 502。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.data.repositories import repository_factory

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])

_MISSING_REASON = ("当日复盘日报未生成（盘后链未执行 / pilot 期未到 / 非交易日；"
                   "原料不足日不产出不伪造，fail-visible）")


@router.get("/daily-recap")
def get_daily_recap(date: str) -> Any:
    if not date:
        return JSONResponse(status_code=422, content={"ok": False, "reason": "missing date"})
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc = db["hotlist_jev_daily_recap"].find_one({"_id": date})
    except Exception as exc:  # noqa: BLE001 — 读口错误显式返回（fail-visible）
        return JSONResponse(status_code=502, content={"ok": False, "reason": f"db error: {exc}"})
    if not doc or doc.get("ok") is not True:
        return {"ok": True, "date": date, "missing": True, "missingReason": _MISSING_REASON}
    doc.pop("_id", None)
    return {"ok": True, "date": date, "missing": False, "report": doc}
