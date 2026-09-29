from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """快照事实库 ORM 基类（领域模型见 models.py；mongo 仓库复用同一套领域类）。"""


class ResearchBase(DeclarativeBase):
    """research 库 ORM 基类（保留：models.py 领域类仍在此声明）。"""


def init_db() -> bool:
    """mongodb 单链下为空操作。

    历史 sqlite 建库/逐列迁移已随 2026-09-29「sqlite 链退役」删除；
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
