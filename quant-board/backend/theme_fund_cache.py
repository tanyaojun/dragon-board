from __future__ import annotations

import json
import math
import time
from datetime import date
from threading import Lock
from typing import Any

from backend.data.snapshot_cache import create_snapshot_redis_client
from backend.settings import get_settings


class ThemeFundCache:
    def __init__(self, redis_client: Any | None, *, prefix: str) -> None:
        self._redis = redis_client
        self._base = f"{prefix.strip(':')}:theme-fund:v3"
        self._latest: dict[str, dict[str, object]] = {}
        self._owners: dict[str, list[str]] = {}
        self._owners_loaded = False
        self._memory_version = 0
        self._lock = Lock()

    def put(self, row: dict[str, object], *, is_final: bool = False) -> dict[str, object]:
        del is_final
        code = str(row.get("code") or "").strip()
        session_date = str(row.get("sessionDate") or row.get("tradingDate") or "").strip()
        source = str(row.get("moneyFlowSource") or row.get("source") or "").strip()
        try:
            zlje = float(row.get("zlje"))
        except (TypeError, ValueError):
            zlje = math.nan
        if (
            not code
            or source != "ths_main_monitor"
            or not session_date
            or not math.isfinite(zlje)
        ):
            raise ValueError("invalid ths_main_monitor fund row")

        with self._lock:
            previous = self._read_latest(code)
            if previous and self._is_older(row, previous, session_date):
                return dict(previous)
            version = self._next_version()
            stored: dict[str, object] = {
                **row,
                "code": code,
                "zlje": zlje,
                "sessionDate": session_date,
                "tradingDate": session_date,
                "source": "ths_main_monitor",
                "moneyFlowSource": "ths_main_monitor",
                "sourceTs": int(row.get("sourceTs") or 0),
                "updatedAt": int(row.get("updatedAt") or int(time.time() * 1000)),
                "version": version,
            }
            self._latest[code] = stored
            self._write_hash(self._key("latest"), code, stored)
            if len(self._latest) > 1000:
                today = session_date
                stale = [c for c, v in self._latest.items() if str(v.get("sessionDate") or "") < today]
                for c in stale[:100]:
                    self._latest.pop(c, None)
            return dict(stored)

    def get_latest(
        self,
        codes: list[str],
        *,
        as_of: date | None = None,
    ) -> dict[str, dict[str, object]]:
        del as_of
        normalized = list(dict.fromkeys(str(value).strip() for value in codes if str(value).strip()))
        result: dict[str, dict[str, object]] = {}
        with self._lock:
            missing = [code for code in normalized if code not in self._latest]
            for code, value in self._read_hash_many(self._key("latest"), missing).items():
                if value.get("moneyFlowSource") == "ths_main_monitor":
                    self._latest[code] = value
            for code in normalized:
                latest = self._latest.get(code)
                if latest:
                    result[code] = dict(latest)
        return result

    def set_owner_codes(self, owner: str, codes: list[str]) -> None:
        key = str(owner).strip()
        if not key:
            return
        normalized = list(
            dict.fromkeys(
                str(code).strip()
                for code in codes
                if len(str(code).strip()) == 6 and str(code).strip().isdigit()
            )
        )
        with self._lock:
            self._load_owners()
            self._owners[key] = normalized
            self._write_value(
                self._key("owners"),
                json.dumps(self._owners, ensure_ascii=False, separators=(",", ":")),
            )

    def get_owner_codes(self) -> dict[str, list[str]]:
        with self._lock:
            self._load_owners()
            return {owner: list(codes) for owner, codes in self._owners.items()}

    def current_version(self) -> int:
        raw = self._read_value(self._key("version"))
        try:
            return max(self._memory_version, int(raw or 0))
        except (TypeError, ValueError):
            return self._memory_version

    @staticmethod
    def _is_older(
        candidate: dict[str, object],
        previous: dict[str, object],
        candidate_date: str,
    ) -> bool:
        previous_date = str(previous.get("sessionDate") or previous.get("tradingDate") or "")
        if candidate_date != previous_date:
            return candidate_date < previous_date
        return int(candidate.get("sourceTs") or 0) < int(previous.get("sourceTs") or 0)

    def _next_version(self) -> int:
        try:
            if self._redis is not None:
                version = int(self._redis.incr(self._key("version")))
                if version <= self._memory_version:
                    version = self._memory_version + 1
                    self._redis.set(self._key("version"), version)
                self._memory_version = max(self._memory_version, version)
                return version
        except Exception:
            pass
        self._memory_version += 1
        return self._memory_version

    def _read_latest(self, code: str) -> dict[str, object] | None:
        if code in self._latest:
            return self._latest[code]
        value = self._read_hash(self._key("latest"), code)
        if value and value.get("moneyFlowSource") == "ths_main_monitor":
            self._latest[code] = value
            return value
        return None

    def _load_owners(self) -> None:
        if self._owners_loaded:
            return
        self._owners_loaded = True
        raw = self._read_value(self._key("owners"))
        try:
            value = json.loads(raw) if isinstance(raw, str) and raw else {}
        except ValueError:
            value = {}
        if isinstance(value, dict):
            self._owners = {
                str(owner): [str(code) for code in codes]
                for owner, codes in value.items()
                if isinstance(codes, list)
            }

    def _key(self, suffix: str) -> str:
        return f"{self._base}:{suffix}"

    def _write_hash(self, key: str, field: str, value: dict[str, object]) -> None:
        try:
            if self._redis is not None:
                self._redis.hset(key, field, json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        except Exception:
            pass

    def _read_hash(self, key: str, field: str) -> dict[str, object] | None:
        try:
            raw = self._redis.hget(key, field) if self._redis is not None else None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            value = json.loads(raw) if raw else None
            return value if isinstance(value, dict) else None
        except Exception:
            return None

    def _read_hash_many(self, key: str, fields: list[str]) -> dict[str, dict[str, object]]:
        if not fields or self._redis is None:
            return {}
        try:
            raw_values = self._redis.hmget(key, fields)
        except Exception:
            return {}
        result: dict[str, dict[str, object]] = {}
        for field, raw in zip(fields, raw_values):
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                value = json.loads(raw) if raw else None
            except (TypeError, ValueError, UnicodeDecodeError):
                continue
            if isinstance(value, dict):
                result[field] = value
        return result

    def _write_value(self, key: str, value: str) -> None:
        try:
            if self._redis is not None:
                self._redis.set(key, value)
        except Exception:
            pass

    def _read_value(self, key: str) -> object | None:
        try:
            raw = self._redis.get(key) if self._redis is not None else None
            return raw.decode("utf-8") if isinstance(raw, bytes) else raw
        except Exception:
            return None


_theme_fund_cache: ThemeFundCache | None = None


def get_theme_fund_cache() -> ThemeFundCache:
    global _theme_fund_cache
    if _theme_fund_cache is None:
        settings = get_settings()
        redis_client = create_snapshot_redis_client(
            enabled=bool(settings.redis_url),
            redis_url=settings.redis_url,
            connect_timeout=settings.snapshot_cache_connect_timeout_seconds,
            socket_timeout=settings.snapshot_cache_socket_timeout_seconds,
        )
        _theme_fund_cache = ThemeFundCache(redis_client, prefix=settings.redis_key_prefix)
    return _theme_fund_cache
