from __future__ import annotations

from typing import Any

from sqlalchemy.orm import DeclarativeBase


class ThemeBase(DeclarativeBase):
    """themeDATA 库 ORM 基类（theme_models.py 领域类仍在此声明；sqlite 引擎已退役）。"""


def theme_status() -> dict[str, str | bool | None]:
    """mongodb 单链：主题库状态即 mongodb 状态（历史 themeDATA.db 状态分支已删）。"""
    from backend.data.repositories.repository_factory import mongodb_status

    status = mongodb_status()
    return {
        "configured": status.get("configured"),
        "connected": status.get("connected"),
        "url": None,
        "last_error": status.get("last_error"),
        "source": "mongodb",
    }
