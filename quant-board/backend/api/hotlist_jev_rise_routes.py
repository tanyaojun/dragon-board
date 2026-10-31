# -*- coding: utf-8 -*-
"""上涨复盘读口（JEV 叙事工作台【上涨复盘】页，2026-10-31）。

- GET /api/hotlist-jev/rise-review?date=YYYY-MM-DD：单日上涨名单——
  全市场涨幅 > 5% 且未封涨停逐股（本地日线口径）+ 采集池快照行 + 连涨回溯 +
  触板未封 + 板块分布。该日无任何可用原始记录 → noData=true（fail-visible，
  不伪造空成功）；「0 只上涨」是真读数，照常返回空名单。

纯读为主，**但非无副作用**：当日收盘（15:05）后首次读可能触发一次本地日线懒加载
并 upsert `market_daily_rise_stocks`（1 次/日，无外呼；历史日只读参考集合）。
聚合逻辑见 services/jev/jev_rise_review（独立路由文件，避免动 hotlist_jev_routes）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.api.jev_view_date import resolve_view_date
from backend.data.repositories import repository_factory
from backend.services.jev.jev_rise_review import collect_rise_review

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])


@router.get("/rise-review")
def get_rise_review(date: str) -> Any:
    if not date:
        return JSONResponse(status_code=422, content={"ok": False, "reason": "missing date"})
    try:
        db = repository_factory.get_runtime_mongodb_database()
        # 盘中回退（同 dieban-review 裁决）：指定日全日无 half_hour 帧（盘前/非交易日）
        # → 回退 < 指定日最新有帧交易日；当日有帧（含盘中最新槽）时照常当日。
        date, date_fallback = resolve_view_date(db["snapshot_frames"], date,
                                                {"type": "half_hour"})
        result = collect_rise_review(db, date)
        if date_fallback:
            result["dateFallback"] = date_fallback
        return result
    except Exception as exc:  # noqa: BLE001 — 读口错误显式返回（fail-visible）
        return JSONResponse(status_code=502, content={"ok": False, "reason": f"db error: {exc}"})
