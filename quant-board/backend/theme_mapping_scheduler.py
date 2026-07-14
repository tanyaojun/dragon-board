"""每日定时从 longhuvip API 刷新 theme_stock_mappings 的后台调度器。

在 FastAPI lifespan 中注册，默认交易日 08:30 执行一次。
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from typing import Any

from backend.theme_mapping_refresh import refresh_theme_stock_mappings
from backend.settings import get_settings


class ThemeMappingRefreshScheduler:
    """后台异步调度器，每日定时刷新 theme_stock_mappings。

    启动后先 sleep 到下一个目标时间，然后执行刷新，之后每 24 小时重复。
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = settings.storage_backend == "mongodb"
        self.target_hour = 8
        self.target_minute = 30
        self._task: asyncio.Task[None] | None = None
        self._last_run_at: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run_loop())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self._task is not None,
            "targetHour": self.target_hour,
            "targetMinute": self.target_minute,
            "lastRunAt": self._last_run_at,
            "lastResult": self._last_result,
            "lastError": self._last_error,
        }

    async def _run_loop(self) -> None:
        while True:
            try:
                sleep_seconds = self._seconds_until_next_target()
                await asyncio.sleep(sleep_seconds)
                await self._refresh_once()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._last_error = str(exc)

    async def _refresh_once(self) -> None:
        """执行一次刷新（在线程池中运行以不阻塞事件循环）。"""
        result = await asyncio.to_thread(refresh_theme_stock_mappings)
        self._last_run_at = datetime.now().isoformat()
        self._last_result = result
        self._last_error = None if result.get("ok") else result.get("errors", ["unknown"])[0]

    def _seconds_until_next_target(self) -> float:
        """计算距下一次目标时间的秒数。"""
        now = datetime.now()
        target = now.replace(hour=self.target_hour, minute=self.target_minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(1.0, (target - now).total_seconds())


# 模块级单例
theme_mapping_refresh_scheduler = ThemeMappingRefreshScheduler()
