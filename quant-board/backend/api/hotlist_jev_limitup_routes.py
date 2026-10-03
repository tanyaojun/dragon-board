# -*- coding: utf-8 -*-
"""涨停打标轨道读口（研究↔展示同步 2026-10-03）。

- GET /api/hotlist-jev/limitup-labels?date=YYYY-MM-DD：单日读口——
  个股四题标签（driver/depth/freshness/buySide + 概率 + 韦研/热榜语境）
  + 日级相位哨兵 + 分布小结；该日无文档 no_data=true（fail-visible，不伪造空成功）。

纯读；聚合逻辑见 services/jev/jev_limitup_labels（独立路由文件，避开 hotlist_jev_routes 在途改动）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.data.repositories import repository_factory
from backend.services.jev.jev_limitup_labels import collect_limitup_labels

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])


@router.get("/limitup-labels")
def get_limitup_labels(date: str) -> Any:
    if not date:
        return JSONResponse(status_code=422, content={"ok": False, "reason": "missing date"})
    try:
        db = repository_factory.get_runtime_mongodb_database()
        return collect_limitup_labels(db, date)
    except Exception as exc:  # noqa: BLE001 — 读口错误显式返回（fail-visible）
        return JSONResponse(status_code=502, content={"ok": False, "reason": f"db error: {exc}"})
