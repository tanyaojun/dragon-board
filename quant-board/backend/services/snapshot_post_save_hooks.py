# -*- coding: utf-8 -*-
"""默认 after-save 钩子（2026-09-10）。

在 ``backend/data/repositories/snapshot_post_save.py`` 的机制上注册两条默认后处理，
由 ``main.py``（8000）与 ``collector_main.py``（8001）在启动时各调一次
``register_default_snapshot_post_save_hooks()``。

钩子内容：
1. ``snapshot_cache.invalidate_snapshot_cache_after_ingest`` —— 快照缓存失效
   （原先只在 ``POST /api/snapshots/ingest`` 里显式调用，collector 侧另有构造注入；
   统一到钩子后，任何写库路径都自动覆盖）；
2. analyze 产物持久化 —— 通过采集链路的 ``analysis_worker`` 后台线程提交
   （**这是本次修复的核心**：原先只挂 ingest 路由 → 日常采集绕过它 →
   ``snapshot_analysis`` 空了一个多月，2026-09-10 定位；详见
   ``backend/services/snapshot_analysis_backfill.py`` 的背景说明）。

设计约束：
- 钩子是**数据层触发**的（见机制模块 docstring）：新写入路径无需记得"补调用"；
- deduped 帧不重复算 analyze（补历史请用 CLI ``snapshot-analysis-backfill``）；
- 任何异常由机制层吞掉并记 warning，绝不影响写库结果。
"""
from __future__ import annotations

from typing import Any

from backend.data.repositories.snapshot_post_save import register_snapshot_post_save_hook

__all__ = ["register_default_snapshot_post_save_hooks"]


def _invalidate_snapshot_cache_hook(
    *,
    dataset_id: str,
    frames: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    deduped: bool,
    source: str = "",
) -> None:
    """快照缓存按索引失效（fail-open：由 snapshot_cache 内部保证）。"""
    from backend.data.cache import snapshot_cache

    snapshot_cache.invalidate_snapshot_cache_after_ingest(
        dataset_id=dataset_id,
        records=records,
        frames=frames,
        stock_rows=stock_rows,
        sector_rows=sector_rows,
    )


def _persist_snapshot_analysis_hook(
    *,
    dataset_id: str,
    frames: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    deduped: bool,
    source: str = "",
) -> None:
    """把本帧的 analyze 落库任务交给采集链路的后台 worker（不阻塞写库）。"""
    if deduped:
        return  # 帧已存在 → 不重复算；补历史用 CLI `snapshot-analysis-backfill`
    from backend.data.repositories import repository_factory
    from backend.snapshot_collector.analysis_worker import (
        analysis_enabled,
        submit_frame_analysis,
    )

    if not analysis_enabled():
        return
    db = repository_factory.get_runtime_mongodb_database()
    # 按 snapshotId 归组股票行（一个 bundle 可含多帧）
    rows_by_snapshot: dict[str, list[dict[str, Any]]] = {}
    for row in stock_rows:
        snapshot_id = str(row.get("snapshotId") or row.get("snapshot_id") or "")
        if snapshot_id:
            rows_by_snapshot.setdefault(snapshot_id, []).append(row)
    for frame in frames:
        snapshot_id = str(
            frame.get("snapshotId") or frame.get("snapshot_id") or frame.get("id") or ""
        )
        if not snapshot_id:
            continue
        rows = rows_by_snapshot.get(snapshot_id)
        if rows is None:
            # 单帧 bundle 且行未带 snapshotId 时回退全量（保持与采集侧一致）
            rows = list(stock_rows) if len(frames) == 1 else []
        if not rows:
            continue
        submit_frame_analysis(
            db=db,
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            snapshot_type=str(frame.get("type") or "half_hour"),
            trading_date=str(frame.get("tradingDate") or ""),
            slot_time=str(frame.get("slotTime") or ""),
            stock_rows=rows,
        )


def register_default_snapshot_post_save_hooks() -> None:
    """注册默认 after-save 钩子（幂等；8000/8001 进程启动时各调一次）。"""
    register_snapshot_post_save_hook(_invalidate_snapshot_cache_hook)
    register_snapshot_post_save_hook(_persist_snapshot_analysis_hook)
