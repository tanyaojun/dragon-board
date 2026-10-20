# -*- coding: utf-8 -*-
"""跌停复盘读口（JEV 叙事工作台【跌停复盘】页，2026-10-20）。

- GET /api/hotlist-jev/dieban-review?date=YYYY-MM-DD：单日负反馈名单——
  跌停 / 连跌 / 一字跌停 / 大跌 / 触板后深回撤逐股 + 全市场跌停家数（参考集合）
  + 池内涨跌结构与回撤池统计。该日无任何可用原始记录 → noData=true（fail-visible，
  不伪造空成功）；「0 家跌停」是真读数，照常返回空名单。

纯读为主，**但非无副作用**（2026-10-20 review minor）：当日收盘后首次读可能触发一次
东财跌停池懒加载并 upsert 家数/逐股文档（1 次/日，受 15:05 截点与 120s 进程内缓存约束）。
聚合逻辑见 services/jev/jev_dieban_review（独立路由文件，避免动 hotlist_jev_routes）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.data.repositories import repository_factory
from backend.services.jev.jev_dieban_review import collect_dieban_review

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])


@router.get("/dieban-review")
def get_dieban_review(date: str) -> Any:
    if not date:
        return JSONResponse(status_code=422, content={"ok": False, "reason": "missing date"})
    try:
        db = repository_factory.get_runtime_mongodb_database()
        return collect_dieban_review(db, date)
    except Exception as exc:  # noqa: BLE001 — 读口错误显式返回（fail-visible）
        return JSONResponse(status_code=502, content={"ok": False, "reason": f"db error: {exc}"})
