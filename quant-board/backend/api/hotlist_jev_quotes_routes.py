# -*- coding: utf-8 -*-
"""热榜行情读口路由（行情列表五维信号 jev 复核台账展示侧，2026-10-12）。

- GET /api/hotlist-jev/quotes-review?date=YYYY-MM-DD[&dataset_id=][&with_docs=1]：
  当日 half_hour 15:00 收盘槽全量热榜股 + 五维观察档位 + vote_confirm/lifecycle_recheck
  双题集复核台账；with_docs=1 时有文档股嵌入完整存档（工作台行展开用）。

纯读（零 jev 调用零写入）；聚合逻辑见 services/jev/jev_quotes_review。
独立路由文件，沿 hotlist_jev_limitup_routes 归档模式（不动 hotlist_jev_routes）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.data.repositories import repository_factory
from backend.services.jev.jev_quotes_review import collect_quotes_review

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])


@router.get("/quotes-review")
def get_hotlist_jev_quotes_review(date: str, dataset_id: str = "dragonboard_live",
                                  with_docs: int = 0) -> Any:
    if not date:
        return JSONResponse(status_code=422, content={"ok": False, "reason": "missing date"})
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:  # noqa: BLE001 — 数据库不可用显式降级（fail-visible）
        return JSONResponse(status_code=502, content={"ok": False, "reason": f"db error: {exc}"})
    try:
        return collect_quotes_review(db, date, dataset_id=dataset_id, with_docs=bool(with_docs))
    except Exception as exc:  # noqa: BLE001 — 读口错误显式返回（fail-visible）
        return JSONResponse(status_code=502, content={"ok": False, "reason": f"quotes_review_read_failed: {exc}"})
