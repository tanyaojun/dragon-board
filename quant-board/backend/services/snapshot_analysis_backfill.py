# -*- coding: utf-8 -*-
"""snapshot_analysis 补跑编排（CLI 入口用）。

**背景（2026-09-10 定位）**：analyze 产物持久化只挂在 ``POST /api/snapshots/ingest`` 的
BackgroundTasks（``backend/main.py`` 的 ``_schedule_snapshot_analysis``），而日常采集由
``backend/snapshot_collector`` 直写 MongoDB、**绕过该路由** → ``snapshot_analysis`` 集合
长期为空（实测 0 文档），导致 hotlist 展示状态的 displayStatus join 恒为 0、面板
100% 走 fallback 旧口径。

本模块提供"从库选帧 → 组装当前帧 → 复用生产 analyze → （可选）持久化"的补跑编排：
- 只复用 ``backend.services.snapshot_analysis_service`` 的实现，不复制 analyze 逻辑；
- **关键前提**：analyze 的 ``current_frame`` 必须是**含 stocks 行的帧**
  （``backend/api/ranktrend_routes.py`` 读 ``current_frame["stocks"]``），而
  ``snapshot_frames`` 文档只有 ``stockRowCount`` → 必须从 ``snapshot_stock_rows`` 组装；
- 默认 dry-run（``apply=False``）：只算不写，输出将写入的股票数与 displayStatus 分布。
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Any

from backend.data.repositories.mongo_repository import MongoRepository
from backend.services.snapshot_analysis_service import (
    compute_snapshot_analysis,
    persist_snapshot_analysis,
)

DEFAULT_DATASET_ID = "dragonboard_live"
DEFAULT_SNAPSHOT_TYPES = ("half_hour",)

# 帧类型枚举（与 snapshot_collector / snapshot_frames.type 一致）
SNAPSHOT_TYPE_ENUM = ("five_minutes", "quarter_hour", "half_hour", "hourly", "daily")


def normalize_snapshot_types(raw: Any) -> list[str]:
    """把 CLI 传入的 ``--snapshot-type``（可重复 / 逗号分隔）规范化为枚举内的列表。"""
    items: list[str] = []
    if raw is None:
        items = list(DEFAULT_SNAPSHOT_TYPES)
    elif isinstance(raw, str):
        items = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        for value in raw:
            items.extend(part.strip() for part in str(value).split(",") if part.strip())
    unknown = [item for item in items if item not in SNAPSHOT_TYPE_ENUM]
    if unknown:
        raise ValueError(f"unknown snapshot_type: {unknown}; allowed={list(SNAPSHOT_TYPE_ENUM)}")
    return items or list(DEFAULT_SNAPSHOT_TYPES)


def select_recent_frames(
    db: Any,
    dataset_id: str,
    snapshot_types: list[str],
    limit: int,
    *,
    start_date: str | None = None,
) -> list[dict[str, Any]]:
    """按 ``tradingDate`` + ``slotTime`` 倒序取最近 ``limit`` 帧（只读）。

    ``start_date``（``YYYY-MM-DD``）为下界（含当日）—— 按日期范围回填比帧数直观，
    也便于断点续跑。``limit<=0`` 且给了 ``start_date`` 时表示"该日期起全部"。
    """
    if limit <= 0 and not start_date:
        return []
    query: dict[str, Any] = {"datasetId": dataset_id, "type": {"$in": list(snapshot_types)}}
    if start_date:
        query["tradingDate"] = {"$gte": str(start_date)}
    cursor = (
        db["snapshot_frames"]
        .find(query)
        .sort([("tradingDate", -1), ("slotTime", -1)])
    )
    if limit > 0:
        cursor = cursor.limit(int(limit))
    return list(cursor)


def build_current_frame(db: Any, frame_doc: dict[str, Any]) -> dict[str, Any]:
    """把 ``snapshot_frames`` 文档 + ``snapshot_stock_rows`` 行组装成 analyze 的 current_frame。"""
    snapshot_id = str(frame_doc.get("snapshotId") or "")
    rows = list(db["snapshot_stock_rows"].find({"snapshotId": snapshot_id}))
    return {
        "tradingDate": frame_doc.get("tradingDate"),
        "slotTime": frame_doc.get("slotTime"),
        "type": frame_doc.get("type"),
        "snapshotId": snapshot_id,
        "stocks": rows,
    }


def _summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    labels: Counter[str] = Counter()
    stages: Counter[str] = Counter()
    with_display = 0
    for entry in entries:
        analysis = entry.get("analysis") or {}
        display = analysis.get("displayStatus")
        if isinstance(display, dict) and display.get("label"):
            with_display += 1
            labels[str(display["label"])] += 1
        stages[str((analysis.get("cycle") or {}).get("stage") or "<missing>")] += 1
    return {
        "stocksWithObservation": len(entries),
        "stocksWithDisplayStatus": with_display,
        "displayStatusCounts": dict(labels.most_common()),
        "cycleStageCounts": dict(stages.most_common()),
    }


def _backfill_single(
    repo: MongoRepository,
    db: Any,
    dataset_id: str,
    frame_doc: dict[str, Any],
    *,
    apply: bool,
) -> dict[str, Any]:
    """单帧补跑：串行路径与并行 worker **共用的唯一实现**（禁止另写一套 analyze 组装）。"""
    snapshot_id = str(frame_doc.get("snapshotId") or "")
    snapshot_type = str(frame_doc.get("type") or "")
    started = time.time()
    current_frame = build_current_frame(db, frame_doc)
    stock_rows = len(current_frame["stocks"])
    entry: dict[str, Any] = {
        "snapshotId": snapshot_id,
        "snapshotType": snapshot_type,
        "tradingDate": frame_doc.get("tradingDate"),
        "slotTime": frame_doc.get("slotTime"),
        "stockRows": stock_rows,
        "applied": bool(apply),
    }
    if stock_rows == 0:
        entry.update(
            {
                "written": 0,
                "elapsedSeconds": round(time.time() - started, 1),
                "reason": "empty_stock_rows",
            }
        )
        return entry
    try:
        computed = compute_snapshot_analysis(repo, dataset_id, snapshot_type, current_frame)
    except Exception as exc:  # noqa: BLE001 —— fail-visible：单帧失败不阻断其余帧
        entry.update(
            {
                "written": 0,
                "elapsedSeconds": round(time.time() - started, 1),
                "reason": f"analyze_failed: {type(exc).__name__}: {exc}"[:400],
            }
        )
        return entry
    entry.update(_summarize(computed))
    written = 0
    if apply and computed:
        written = persist_snapshot_analysis(repo, dataset_id, snapshot_id, computed)
    entry["written"] = written
    entry["elapsedSeconds"] = round(time.time() - started, 1)
    if not computed:
        entry["reason"] = "no_observation_produced"
    return entry


def _backfill_summary(
    dataset_id: str,
    results: list[dict[str, Any]],
    *,
    apply: bool,
) -> dict[str, Any]:
    return {
        "ok": True,
        "dataset_id": dataset_id,
        "apply": bool(apply),
        "frameCount": len(results),
        "totalWritten": sum(int(item.get("written") or 0) for item in results),
        "frames": results,
    }


def backfill_frames(
    db: Any,
    dataset_id: str,
    frames: list[dict[str, Any]],
    *,
    apply: bool = False,
    workers: int = 1,
) -> dict[str, Any]:
    """对给定帧补跑 analyze；``apply=False`` 时只算不写（dry-run，默认）。

    逐帧结构化输出（fail-visible）：取不到行/无 observation/单帧异常时该帧
    ``written=0`` 且保留 ``reason``，不吞、不伪装、不阻断其余帧。

    ``workers > 1`` 时按帧并行（``ProcessPoolExecutor`` + spawn context）。
    单帧 analyze 约 20~40s CPU：全量历史回填（~2800 帧）串行需十几小时，
    并行 6~8 进程可压到 2~3 小时。
    """
    if workers > 1 and len(frames) > 1:
        return _backfill_frames_parallel(dataset_id, frames, apply=apply, workers=workers)

    repo = MongoRepository(db)
    results = [
        _backfill_single(repo, db, dataset_id, frame_doc, apply=apply)
        for frame_doc in frames
    ]
    return _backfill_summary(dataset_id, results, apply=apply)


def _parallel_worker(payload: dict[str, Any]) -> dict[str, Any]:
    """进程池 worker：Mongo 连接不可跨进程，故在子进程内自建 db + repo。

    只接收可 pickle 的基本类型（dataset_id / frame dict / apply），与串行路径
    共用 ``_backfill_single``。
    """
    from backend.data.repositories import repository_factory

    db = repository_factory.get_runtime_mongodb_database()
    return _backfill_single(
        MongoRepository(db),
        db,
        str(payload.get("dataset_id") or DEFAULT_DATASET_ID),
        payload.get("frame") or {},
        apply=bool(payload.get("apply")),
    )


def _backfill_frames_parallel(
    dataset_id: str,
    frames: list[dict[str, Any]],
    *,
    apply: bool,
    workers: int,
) -> dict[str, Any]:
    """按帧并行补跑；结果按输入顺序回填，进度写 stderr（stdout 保持纯 JSON）。"""
    import multiprocessing
    import sys
    from concurrent.futures import ProcessPoolExecutor, as_completed

    payloads = [
        {"dataset_id": dataset_id, "frame": dict(frame_doc), "apply": bool(apply)}
        for frame_doc in frames
    ]
    ordered: list[dict[str, Any] | None] = [None] * len(payloads)
    total = len(payloads)
    done = 0
    # spawn：Windows / Linux 行为一致；CLI 入口有 __main__ 保护
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=max(1, int(workers)), mp_context=context) as pool:
        future_index = {
            pool.submit(_parallel_worker, payload): index
            for index, payload in enumerate(payloads)
        }
        for future in as_completed(future_index):
            index = future_index[future]
            try:
                ordered[index] = future.result()
            except Exception as exc:  # noqa: BLE001 —— 单帧失败隔离，不阻断整批
                frame_doc = payloads[index]["frame"]
                ordered[index] = {
                    "snapshotId": str(frame_doc.get("snapshotId") or ""),
                    "snapshotType": str(frame_doc.get("type") or ""),
                    "tradingDate": frame_doc.get("tradingDate"),
                    "slotTime": frame_doc.get("slotTime"),
                    "stockRows": 0,
                    "applied": bool(apply),
                    "written": 0,
                    "elapsedSeconds": 0,
                    "reason": f"worker_failed: {type(exc).__name__}: {exc}"[:400],
                }
            done += 1
            entry = ordered[index] or {}
            print(
                f"[{done}/{total}] {entry.get('tradingDate')} {entry.get('slotTime')} "
                f"written={entry.get('written')} elapsed={entry.get('elapsedSeconds')}s "
                f"{entry.get('reason') or ''}".rstrip(),
                file=sys.stderr,
                flush=True,
            )
    results = [item for item in ordered if item is not None]
    return _backfill_summary(dataset_id, results, apply=apply)
