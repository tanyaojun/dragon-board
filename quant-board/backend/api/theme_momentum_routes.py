# quant-board/backend/api/theme_momentum_routes.py
"""题材动量 v2 只读 API：GET /api/theme-momentum/summary。

从 snapshot_sector_rows（hot_theme）按交易日聚合日线序列，计算 v2 题材动量，
返回全字段排行（RPS/距年内高点/多窗口动量/整体性/资金量能/拥挤惩罚/intraday/reasons）。
复用 theme-rotation/summary 的 Redis 缓存模式；纯计算无 I/O 副作用。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.analysis.theme.daily_series import build_daily_series
from backend.analysis.theme.momentum import compute_theme_momentum_v2
from backend.analysis.theme.momentum_config import ThemeMomentumConfig
from backend.data import snapshot_cache
from backend.data.repository_factory import get_runtime_mongodb_database
from backend.settings import get_settings

router = APIRouter(prefix="/api/theme-momentum", tags=["theme-momentum"])

# 最近 N 行 sector rows（≈ 60 题材 × 21+ 交易日，覆盖 20 日 RPS/52 周高降级窗口）
RECENT_SECTOR_ROWS_LIMIT = 20000
SUMMARY_TOP_N = 50


def _cache_key(dataset_id: str, snapshot_type: str) -> str:
    builder = snapshot_cache.SnapshotCacheKeyBuilder(prefix=get_settings().redis_key_prefix)
    return builder.response_key(
        "theme-momentum-summary",
        resolved_dataset_id=dataset_id,
        params={"snapshot_type": snapshot_type},
    )


def _load_recent_sector_rows(db: Any, dataset_id: str, snapshot_type: str) -> list[dict[str, Any]]:
    """最近 RECENT_SECTOR_ROWS_LIMIT 行 hot_theme sector rows（desc → 逆序为时间升序）。"""
    rows = list(
        db["snapshot_sector_rows"]
        .find(
            {
                "datasetId": dataset_id,
                "type": snapshot_type,
                "entityType": "hot_theme",
            }
        )
        .sort([("timestamp", -1)])
        .limit(RECENT_SECTOR_ROWS_LIMIT)
    )
    rows.reverse()
    return rows


@router.get("/summary")
def theme_momentum_summary(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
) -> dict[str, Any]:
    """返回题材动量 v2 全字段排行（Top-N by score）与质量标记。"""
    cache = snapshot_cache.get_snapshot_redis_cache()
    settings = get_settings()
    cache_key = _cache_key(dataset_id, snapshot_type)
    cached = cache.get_response(cache_key)
    if cached is not None:
        return cached

    db = get_runtime_mongodb_database()
    rows = _load_recent_sector_rows(db, dataset_id, snapshot_type)
    daily = build_daily_series(rows, [])
    result = compute_theme_momentum_v2(list(daily.values()), cfg=ThemeMomentumConfig())

    factors = sorted(
        (v for v in result["factors"].values() if v.get("score") is not None),
        key=lambda item: -float(item["score"]),
    )[:SUMMARY_TOP_N]
    response: dict[str, Any] = {
        "ok": True,
        "status": "ok",
        "version": result["version"],
        "factors": factors,
        "qualityFlags": result["qualityFlags"],
        "computedAt": result["computedAt"],
        "cache": {"hit": False, "store": "mongodb"},
    }
    cache.set_response(cache_key, response, ttl_seconds=settings.theme_rotation_cache_ttl_seconds)
    cache.register_dependencies(
        cache_key,
        snapshot_cache.build_snapshot_cache_index_keys(
            prefix=settings.redis_key_prefix,
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
        ),
    )
    return response
