# -*- coding: utf-8 -*-
"""默认 after-save 钩子（2026-09-10；2026-09-15 收窄）。

在 ``backend/data/repositories/snapshot_post_save.py`` 的机制上注册数据层 after-save
后处理，由 ``main.py``（8000）与 ``collector_main.py``（8001）在启动时各调一次
``register_default_snapshot_post_save_hooks()``。

钩子内容（2026-09-15 起）：
1. ``snapshot_cache.invalidate_snapshot_cache_after_ingest`` —— 快照缓存失效
   （原先只在 ``POST /api/snapshots/ingest`` 里显式调用；统一到钩子后，
   任何写库路径都自动覆盖）。

**analyze 产物落库已从钩子退役（2026-09-15 重构）**：钩子 + 后台 worker 的异步路径在
"落帧完成"与"analyze 落库"之间留时序空窗 → 热榜情绪 displayStatus join 恒 miss、
盘中 EOD 首算落在空窗内则全天固化 fallback 口径（生产实测 2026-09-08~09-15 槽位文档
全量 fallback）。现在 analyze 是**写路径自身的同步步骤**：

- 采集主链：``snapshot_collector/service.py`` ``_run_post_persist_chain``
  （analyze → 槽位情绪 → 当日 EOD 顺序同步执行，线程池内跑不阻塞事件循环）；
- 手工导入：``POST /api/snapshots/ingest`` 路由内 BackgroundTasks 同步执行 analyze。

设计约束（保留）：
- 钩子是**数据层触发**的（见机制模块 docstring）：新写入路径无需记得"补调用"；
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


def register_default_snapshot_post_save_hooks() -> None:
    """注册默认 after-save 钩子（幂等；8000/8001 进程启动时各调一次）。"""
    register_snapshot_post_save_hook(_invalidate_snapshot_cache_hook)
