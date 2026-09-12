# -*- coding: utf-8 -*-
"""采集链路内 analyze 落库后台 worker（2026-09-10）。

**背景**：analyze 产物原先只由 ``POST /api/snapshots/ingest`` 的 BackgroundTasks 写入
（``backend/main.py`` 的 ``_schedule_snapshot_analysis``），而日常采集由
``backend/snapshot_collector`` 直写 MongoDB、**绕过该路由** → ``snapshot_analysis``
长期为空（2026-09-10 实测 0 文档），热榜情绪面板的 displayStatus join 恒为 0、
8 类分布 100% 走 fallback 旧口径。

设计约束（对齐 AGENTS.md §4.0 / §11）：
- **进程内单工作线程 + 有界队列**：不是独立守护进程、不是计划任务（§11 明确反对）；
- **不阻塞采集**：``submit_frame_analysis`` 只入队（O(1)），analyze（单帧约 20~30s CPU）
  在后台线程执行，避免拖慢采集节奏与 8001 事件循环（行情/热榜刷新同进程）；
- **失败绝不阻断**：任何异常只记 ``logging.warning`` 并计入 ``stats()``，不抛给采集链路、
  不丢已保存的帧事实数据；
- **积压有界**：队列满则丢弃并返回 False（调用方记 warning），不无限增长；
- 进程退出由 ``collector_main.lifespan`` 调 ``shutdown()`` 优雅停止（flush + join）。

开关：``QUANT_BOARD_SNAPSHOT_ANALYSIS_ENABLED``（默认 ``1`` 开启——这是修复
``snapshot_analysis`` 空洞的功能；置 ``0`` 可关闭）。
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# 单帧 analyze ≈20~30s、半小时一帧；8 是"明显异常但仍不无限增长"的余量。
QUEUE_MAXSIZE = 8
DEFAULT_TIMEOUT_SECONDS = 30.0

ENV_ENABLED = "QUANT_BOARD_SNAPSHOT_ANALYSIS_ENABLED"

_queue: "queue.Queue[dict[str, Any] | None]" = queue.Queue(maxsize=QUEUE_MAXSIZE)
_worker: threading.Thread | None = None
_lock = threading.Lock()
_stats: dict[str, Any] = {
    "submitted": 0,
    "written": 0,
    "failed": 0,
    "dropped": 0,
    "lastWritten": None,
    "lastError": None,
}


def analysis_enabled() -> bool:
    """是否启用采集链路 analyze 落库（默认开启）。"""
    raw = str(os.environ.get(ENV_ENABLED, "1")).strip().lower()
    return raw not in ("0", "false", "no", "off")


def stats() -> dict[str, Any]:
    """worker 运行计数（供 health / 诊断读取；结构稳定，缺值保持 None）。"""
    return dict(_stats)


def _reset_stats() -> None:
    for key in ("submitted", "written", "failed", "dropped"):
        _stats[key] = 0
    _stats["lastWritten"] = None
    _stats["lastError"] = None


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(
            target=_run_loop,
            name="snapshot-analysis-worker",
            daemon=True,
        )
        _worker.start()


def submit_frame_analysis(
    *,
    db: Any,
    dataset_id: str,
    snapshot_id: str,
    snapshot_type: str,
    trading_date: str,
    slot_time: str,
    stock_rows: list[dict[str, Any]],
) -> bool:
    """把一个采集成功帧的 analyze 落库任务入队（**不阻塞**）。返回是否已入队。

    调用方（collector service）只关心"是否受理"：False 时记一条 warning 到 run doc，
    绝不因此阻断采集（无质量阻断）。
    """
    if not analysis_enabled():
        return False
    if not snapshot_id or not dataset_id or not stock_rows:
        return False
    _ensure_worker()
    task = {
        "db": db,
        "datasetId": dataset_id,
        "snapshotId": snapshot_id,
        "snapshotType": snapshot_type,
        "tradingDate": trading_date,
        "slotTime": slot_time,
        "stockRows": stock_rows,
    }
    try:
        _queue.put_nowait(task)
    except queue.Full:
        _stats["dropped"] += 1
        logger.warning("snapshot analysis queue full; dropped frame %s", snapshot_id)
        return False
    _stats["submitted"] += 1
    return True


def _run_loop() -> None:
    while True:
        task = _queue.get()
        if task is None:  # 停止哨兵
            _queue.task_done()
            return
        try:
            written = _analyze_task(task)
            _stats["written"] = int(_stats["written"]) + 1
            _stats["lastWritten"] = written
        except Exception as exc:  # noqa: BLE001 —— 失败静默：不阻断采集、不丢帧数据
            _stats["failed"] = int(_stats["failed"]) + 1
            _stats["lastError"] = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning(
                "snapshot analysis failed for %s: %s", task.get("snapshotId"), exc
            )
        finally:
            _queue.task_done()


def _analyze_task(task: dict[str, Any]) -> int:
    """构造 current_frame（含 stocks 行）并复用生产 analyze 落库。

    current_frame 必须含 ``stocks`` —— ``backend/api/ranktrend_routes.py`` 读
    ``current_frame["stocks"]``；采集侧手里就有该帧的 stock_rows，无需回查库。
    """
    from backend.data.repositories.mongo_repository import MongoRepository
    from backend.services.snapshot_analysis_service import analyze_snapshot_and_persist

    frame = {
        "tradingDate": task["tradingDate"],
        "slotTime": task["slotTime"],
        "type": task["snapshotType"],
        "snapshotId": task["snapshotId"],
        "stocks": task["stockRows"],
    }
    return analyze_snapshot_and_persist(
        MongoRepository(task["db"]),
        task["datasetId"],
        task["snapshotId"],
        task["snapshotType"],
        frame,
    )


def _pending() -> int:
    return int(getattr(_queue, "unfinished_tasks", 0))


def flush(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> bool:
    """等待队列排空（测试 / 退出用）。返回是否在超时前排空。"""
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if _queue.empty() and _pending() == 0:
            return True
        time.sleep(0.05)
    return _queue.empty() and _pending() == 0


def shutdown(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
    """优雅停止：先等队列排空，再投哨兵并 join（超时则放弃等待，线程为 daemon）。"""
    global _worker
    with _lock:
        worker = _worker
        _worker = None
    if worker is None:
        return
    drained = flush(timeout)
    if not drained:
        logger.warning("snapshot analysis worker still busy after %.0fs; stopping anyway", timeout)
    try:
        _queue.put_nowait(None)
    except queue.Full:
        pass
    worker.join(timeout=timeout)


def reset_for_tests(*, timeout: float = 5.0) -> None:
    """测试辅助：停止 worker 并清空统计（仅供测试调用）。"""
    shutdown(timeout)
    while not _queue.empty():
        try:
            _queue.get_nowait()
            _queue.task_done()
        except queue.Empty:
            break
    _reset_stats()
