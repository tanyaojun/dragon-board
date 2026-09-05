from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.data.models.database import get_db
from backend.data.repositories.repository_factory import create_repository, storage_source_label


router = APIRouter(prefix="/api/themes")


@router.get("/stock-volume-series", response_model=None)
def get_theme_stock_volume_series(
    theme_name: str = Query(default=""),
    dataset_id: str | None = None,
    snapshot_type: str | None = None,
    types: str | None = None,
    trading_date: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = Query(default=2000, ge=1, le=20000),
    db: Session | None = Depends(get_db),
) -> dict[str, Any] | JSONResponse:
    """题材成分股成交量/成交额槽位聚合序列（历史趋势页签数据源）。

    - theme_name 必填：stock rows 的 themes 数组以题材名关联。
    - 仅 MongoDB 主链提供；其余后端返回 503 结构化原因，不伪造空序列。
    """
    requested_name = theme_name.strip()
    if not requested_name:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "errorCode": "theme_name_required",
                "message": "theme_name is required",
            },
        )
    if storage_source_label() != "mongodb":
        # 守卫不看 db 是否为 None：sqlite 模式下 get_db 会给出 session，
        # 而 SQL Repository 没有聚合方法，落过去会变成 AttributeError 500。
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "errorCode": "storage_unavailable",
                "message": "theme stock volume series requires the mongodb storage backend",
            },
        )
    requested_types = [t.strip() for t in types.split(",") if t.strip()] if types else None
    repo = create_repository(db, enable_backup=False)
    result = repo.aggregate_stock_volume_by_theme(
        dataset_id or "dragonboard_live",
        requested_name,
        snapshot_type=snapshot_type,
        snapshot_types=requested_types,
        trading_date=trading_date,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return {
        "ok": True,
        "themeName": requested_name,
        "datasetId": dataset_id or "dragonboard_live",
        "rows": result["rows"],
        "count": result["count"],
        "source": result.get("source"),
    }
