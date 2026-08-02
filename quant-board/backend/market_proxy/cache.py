from __future__ import annotations

from typing import Any

from backend.settings import Settings


def get_hotlist_redis_client(settings: Settings | None = None) -> Any | None:
    """热榜共享缓存 Redis client；未配置或连接失败时返回 None。

    缓存属于优化层：Redis 不可用必须回退到进程内缓存/直连上游，不能阻断数据链路。
    """
    if settings is None:
        from backend.settings import get_settings

        settings = get_settings()
    if not settings.redis_url:
        return None
    try:
        import redis

        return redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.snapshot_cache_connect_timeout_seconds,
            socket_timeout=settings.snapshot_cache_socket_timeout_seconds,
            decode_responses=True,
        )
    except Exception:
        return None
