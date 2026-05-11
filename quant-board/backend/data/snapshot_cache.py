from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from backend.settings import get_settings


CSV_PARAMS = {"types", "codes", "allowed_capture_modes", "entity_types", "entity_keys"}


@dataclass(frozen=True)
class SnapshotCacheKeyBuilder:
    prefix: str
    version: str = "v1"

    def response_key(
        self,
        resource: str,
        *,
        resolved_dataset_id: str,
        params: dict[str, Any],
    ) -> str:
        normalized = self.normalize_params(params)
        payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
        return (
            f"{self.prefix.strip(':')}:snapshot:{resource}:{self.version}:"
            f"{resolved_dataset_id}:{digest}"
        )

    def normalize_params(self, params: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in sorted((params or {}).items()):
            if key == "dataset_id":
                continue
            if value is None or value == "":
                continue
            if key in CSV_PARAMS:
                items = sorted({item.strip() for item in str(value).split(",") if item.strip()})
                if items:
                    normalized[key] = items
                continue
            normalized[key] = value
        return normalized


class SnapshotRedisCache:
    def __init__(
        self,
        *,
        redis_client: Any | None,
        ttl_seconds: int,
        empty_ttl_seconds: int,
    ) -> None:
        self.redis_client = redis_client
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.empty_ttl_seconds = max(1, int(empty_ttl_seconds))

    def get_response(self, key: str) -> dict[str, Any] | None:
        if self.redis_client is None:
            return None
        try:
            raw = self.redis_client.get(key)
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            payload = json.loads(str(raw))
            if not isinstance(payload, dict):
                return None
            return {
                **payload,
                "cache": {"hit": True, "store": "redis"},
            }
        except Exception:
            return None

    def set_response(self, key: str, response: dict[str, Any]) -> None:
        if self.redis_client is None:
            return
        try:
            ttl = self.empty_ttl_seconds if self._is_empty_response(response) else self.ttl_seconds
            payload = json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            self.redis_client.setex(key, ttl, payload)
        except Exception:
            return

    def register_dependencies(self, response_key: str, index_keys: list[str]) -> None:
        if self.redis_client is None:
            return
        try:
            for index_key in index_keys:
                self.redis_client.sadd(index_key, response_key)
                self.redis_client.expire(index_key, self.ttl_seconds + self.empty_ttl_seconds)
        except Exception:
            return

    def invalidate_indexes(self, index_keys: list[str]) -> None:
        if self.redis_client is None:
            return
        try:
            keys_to_delete: set[str] = set()
            for index_key in index_keys:
                members = self.redis_client.smembers(index_key)
                keys_to_delete.update(self._decode_members(members))
                keys_to_delete.add(index_key)
            if keys_to_delete:
                self.redis_client.delete(*keys_to_delete)
        except Exception:
            return

    def _is_empty_response(self, response: dict[str, Any]) -> bool:
        count = response.get("count")
        if isinstance(count, int):
            return count <= 0
        for key in ("frames", "records", "rows"):
            value = response.get(key)
            if isinstance(value, list):
                return len(value) == 0
        return False

    def _decode_members(self, members: Any) -> set[str]:
        decoded: set[str] = set()
        for member in members or []:
            if isinstance(member, bytes):
                decoded.add(member.decode("utf-8"))
            else:
                decoded.add(str(member))
        return decoded


def build_snapshot_cache_index_keys(
    *,
    prefix: str,
    dataset_id: str,
    snapshot_type: str | None = None,
    trading_date: str | None = None,
    snapshot_ids: list[str] | None = None,
) -> list[str]:
    normalized_prefix = prefix.strip(":")
    keys = [f"{normalized_prefix}:snapshot:index:dataset:{dataset_id}"]
    if snapshot_type and trading_date:
        keys.append(f"{normalized_prefix}:snapshot:index:date:{dataset_id}:{snapshot_type}:{trading_date}")
    for snapshot_id in snapshot_ids or []:
        if snapshot_id:
            keys.append(f"{normalized_prefix}:snapshot:index:snapshot:{dataset_id}:{snapshot_id}")
    return list(dict.fromkeys(keys))


def create_snapshot_redis_client(
    *,
    enabled: bool,
    redis_url: str,
    connect_timeout: float,
    socket_timeout: float,
) -> Any | None:
    if not enabled or not redis_url:
        return None
    try:
        import redis

        return redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
            decode_responses=True,
        )
    except Exception:
        return None


_snapshot_redis_cache: SnapshotRedisCache | None = None


def get_snapshot_redis_cache() -> SnapshotRedisCache:
    global _snapshot_redis_cache
    if _snapshot_redis_cache is None:
        settings = get_settings()
        _snapshot_redis_cache = SnapshotRedisCache(
            redis_client=create_snapshot_redis_client(
                enabled=settings.snapshot_cache_enabled,
                redis_url=settings.redis_url,
                connect_timeout=settings.snapshot_cache_connect_timeout_seconds,
                socket_timeout=settings.snapshot_cache_socket_timeout_seconds,
            ),
            ttl_seconds=settings.snapshot_cache_ttl_seconds,
            empty_ttl_seconds=settings.snapshot_empty_cache_ttl_seconds,
        )
    return _snapshot_redis_cache
