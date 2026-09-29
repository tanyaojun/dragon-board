from __future__ import annotations

from collections.abc import Generator
from typing import Any


def init_db() -> bool:
    """mongodb 单链下为空操作。

    历史 sqlite 建库/逐列迁移已随 2026-09-29「sqlite 链退役」删除；
    ORM 基类（Base/ResearchBase）已随 models.py 深度解绑（dataclass 化）一并删除。
    保留本占位以免大面积改动 mongodb 模式下本就 no-op 的调用点。
    """
    return True


def primary_status() -> dict[str, str | bool | None]:
    from backend.data.repositories.repository_factory import mongodb_status

    return mongodb_status()


def get_db() -> Generator[Any | None, None, None]:
    """mongodb 单链：会话依赖恒为 None（保留作 FastAPI Depends 兼容占位）。"""
    yield None
    return
