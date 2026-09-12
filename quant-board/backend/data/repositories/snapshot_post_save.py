# -*- coding: utf-8 -*-
"""快照写入后的共享钩子机制（2026-09-10）。

**为什么需要它**：``save_snapshot_ingest`` 有两条调用路径 —— ``POST /api/snapshots/ingest``
与 ``snapshot_collector`` 直写库（``service_factory`` → ``self._mongo.save_snapshot_ingest``），
而 after-save 后处理（快照缓存失效、analyze 产物持久化）原先**各写一份**、从未对齐：

- 2026-07-28 审计已记录缓存失效只在 ingest 侧
  （``docs/ranktrend/2026-07-28-resonance-chain-audit-findings.md:151``），当时靠"在 collector
  补一次调用"打了单点补丁；
- 2026-08-23 新增 analyze 持久化时又踩同一个坑（只挂 ingest 路由 → ``snapshot_analysis``
  空了一个多月，2026-09-10 才定位）。

本模块把触发点**下移到数据层**：任何写库路径都必然经过 ``save_snapshot_ingest``，在那里统一
调用注册的钩子 → 以后新增 after-save 步骤**不可能"只加在一边"**。

约定：
- 钩子由上层进程在启动时注册（见 ``backend/services/snapshot_post_save_hooks.py``：
  ``register_default_snapshot_post_save_hooks()``，``main.py`` 与 ``collector_main.py`` 各调一次）；
- **钩子异常一律吞掉并记 warning**：后处理失败绝不能影响已完成的写库结果，也不改写库返回值；
- 未注册任何钩子时行为与从前完全一致（零副作用）；
- deduped 早退路径同样触发钩子（与改造前 ingest 路由"无条件调用后处理"的行为等价），
  钩子自行决定是否跳过（例如 analyze 应跳过 deduped 帧）。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

SnapshotPostSaveHook = Callable[..., None]

_hooks: list[SnapshotPostSaveHook] = []


def register_snapshot_post_save_hook(hook: SnapshotPostSaveHook) -> None:
    """注册一个 after-save 钩子（幂等：同一 callable 只注册一次）。"""
    if hook not in _hooks:
        _hooks.append(hook)


def clear_snapshot_post_save_hooks() -> None:
    """清空已注册钩子（**仅供测试**）。"""
    _hooks.clear()


def registered_snapshot_post_save_hooks() -> list[SnapshotPostSaveHook]:
    """已注册钩子快照（诊断/测试用）。"""
    return list(_hooks)


def run_snapshot_post_save_hooks(
    *,
    dataset_id: str,
    frames: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    records: list[dict[str, Any]],
    deduped: bool,
    source: str = "",
) -> None:
    """在 ``save_snapshot_ingest`` 返回前触发全部钩子。

    逐个 try/except：单个钩子失败不影响其它钩子，更不影响写库结果（fail-visible：记 warning）。
    """
    for hook in tuple(_hooks):
        try:
            hook(
                dataset_id=dataset_id,
                frames=frames,
                stock_rows=stock_rows,
                sector_rows=sector_rows,
                records=records,
                deduped=deduped,
                source=source,
            )
        except Exception:  # noqa: BLE001 —— 后处理失败绝不冒泡到写库路径
            logger.warning(
                "snapshot post-save hook %s failed (dataset_id=%s, deduped=%s)",
                getattr(hook, "__name__", repr(hook)),
                dataset_id,
                deduped,
                exc_info=True,
            )
