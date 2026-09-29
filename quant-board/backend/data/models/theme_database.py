from __future__ import annotations

from typing import Any


def theme_status() -> dict[str, str | bool | None]:
    """mongodb 单链：主题库状态即 mongodb 状态（历史 themeDATA.db 链已退役）。"""
    from backend.data.repositories.repository_factory import mongodb_status

    status = mongodb_status()
    return {
        "configured": status.get("configured"),
        "connected": status.get("connected"),
        "url": None,
        "last_error": status.get("last_error"),
        "source": "mongodb",
    }
