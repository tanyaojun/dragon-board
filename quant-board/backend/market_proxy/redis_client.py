from __future__ import annotations

from functools import lru_cache
from typing import Any

from backend.core.settings import Settings


@lru_cache(maxsize=16)
def _build_redis_client(
    redis_url: str,
    connect_timeout: float,
    socket_timeout: float,
) -> Any:
    """按 (url, connect_timeout, socket_timeout) 组合缓存 Redis 客户端。

    跨调用复用连接池，避免高频缓存读写反复建连（此前每次 ``from_url`` 都新建
    一个短命 ConnectionPool，在 GC 前无法跨调用复用，量比/资金流等高频场景反复
    TCP 握手）。不同 timeout 组合（快照缓存 0.2s 短超时 vs 资金大批次 10s 长超时）
    各自持有独立连接池，互不干扰。
    """
    import redis

    return redis.Redis.from_url(
        redis_url,
        socket_connect_timeout=connect_timeout,
        socket_timeout=socket_timeout,
        decode_responses=True,
    )


def get_hotlist_redis_client(
    settings: Settings | None = None,
    *,
    socket_timeout: float | None = None,
    connect_timeout: float | None = None,
) -> Any | None:
    """热榜共享缓存 Redis client；未配置或连接失败时返回 None。

    缓存属于优化层：Redis 不可用必须回退到进程内缓存/直连上游，不能阻断数据链路。
    ``socket_timeout``/``connect_timeout`` 覆盖默认（快照缓存 0.2s）——资金大批次
    写入需要更长（2026-08-12：0.2s 曾导致 fund_cache 大批次写入超时/连接超时）。
    """
    if settings is None:
        from backend.core.settings import get_settings

        settings = get_settings()
    if not settings.redis_url:
        return None
    try:
        return _build_redis_client(
            settings.redis_url,
            connect_timeout
            if connect_timeout is not None
            else settings.snapshot_cache_connect_timeout_seconds,
            socket_timeout
            if socket_timeout is not None
            else settings.snapshot_cache_socket_timeout_seconds,
        )
    except Exception:
        return None
