"""题材日频因子盘后调度器（设计 §5.1，2026-09-27 Task1 接线）。

在 FastAPI lifespan 中注册（对齐 ThemeMappingRefreshScheduler 先例，不新增
独立守护进程），默认交易日盘后 18:30 执行一次 compute_and_store_daily_factors：
补算"有 daily stock rows 但缺因子行"的日期（单轮上限内），幂等覆盖写。

启用条件与映射刷新一致：storage_backend == "mongodb"（theme_daily_factors
仅 MongoDB 后端建集合）；运行结果（status/qualityFlags）经 status() 暴露，
异常不中断调度循环。
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from typing import Any

from backend.core.settings import get_settings
from backend.services.theme.daily_factors_service import compute_and_store_daily_factors


class ThemeDailyFactorsScheduler:
    """后台异步调度器：每日盘后补算题材日频因子。"""

    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = settings.storage_backend == "mongodb"
        self.target_hour = 18
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
                await asyncio.sleep(self._seconds_until_next_target())
                await self._run_once()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._last_error = str(exc)

    async def _run_once(self) -> None:
        result = await asyncio.to_thread(compute_and_store_daily_factors)
        self._last_run_at = datetime.now().isoformat()
        self._last_result = result
        self._last_error = None if result.get("ok") else str(
            (result.get("qualityFlags") or ["unknown"])[0]
        )

    def _seconds_until_next_target(self) -> float:
        now = datetime.now()
        target = now.replace(hour=self.target_hour, minute=self.target_minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(1.0, (target - now).total_seconds())


# 模块级单例
theme_daily_factors_scheduler = ThemeDailyFactorsScheduler()
