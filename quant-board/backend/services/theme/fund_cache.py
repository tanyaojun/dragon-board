from __future__ import annotations

import json
import logging
import math
import sys
import time
from datetime import date
from threading import Lock
from typing import Any

from backend.core.fund_sources import (
    FUND_SOURCE_AKSHARE_THS_INDIVIDUAL,
    FUND_SOURCE_THS_MAIN_MONITOR,
    SUPPORTED_FUND_SOURCES,
)
from backend.core.settings import get_settings

logger = logging.getLogger(__name__)


# 允许写入运行态资金缓存的来源由 backend.core.fund_sources.SUPPORTED_FUND_SOURCES
# 统一提供（L2 主源 + akshare 题材源）；本模块不再本地重定义（2026-08-14 清理，
# 此前本地 frozenset 覆盖了统一入口，导致种子源被误接受）。
# 同一 sessionDate 下 source rank 高者覆盖低者：L2 主源(2) > akshare 题材估算(1)。
FUND_SOURCE_RANK: dict[str, int] = {
    FUND_SOURCE_AKSHARE_THS_INDIVIDUAL: 1,
    FUND_SOURCE_THS_MAIN_MONITOR: 2,
}


class ThemeFundCache:
    def __init__(
        self,
        redis_client: Any | None,
        *,
        prefix: str,
        ttl_seconds: int = 900,
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = max(60, int(ttl_seconds))
        self._base = f"{prefix.strip(':')}:theme-fund:v3"
        self._latest: dict[str, dict[str, object]] = {}
        self._owners: dict[str, list[str]] = {}
        self._owners_loaded = False
        self._memory_version = 0
        # 旧交易日行清理标记（2026-08-12）：仅跨日时清理 Redis hash——
        # 同日内重复写入不重复 hgetall（5200 字段 hgetall 太重，曾导致大 batch
        # put_many 超时、Redis latest 未写入）
        self._last_pruned_date: str | None = None
        # fail-visible：最近一次 Redis 写入错误（put_many 静默失败时记录，供诊断）
        self._last_redis_write_error: str | None = None
        self._lock = Lock()

    def put(self, row: dict[str, object], *, is_final: bool = False) -> dict[str, object]:
        del is_final
        parsed = self._parse_fund_row(row)
        if parsed is None:
            raise ValueError("invalid fund row")
        code, session_date, zlje = parsed

        with self._lock:
            previous = self._read_latest(code)
            if previous and self._is_older(row, previous, session_date):
                return dict(previous)
            version = self._next_version()
            stored: dict[str, object] = {
                **self._build_stored(row, code, session_date, zlje),
                "version": version,
            }
            self._latest[code] = stored
            self._write_hash(self._key("latest"), code, stored)
            # 全市场行数据带 TTL：跨进程/跨重启 last-good，过期后自动清理（fail-visible 由进程内兜底）
            self._touch(self._key("latest"))
            # 清理策略（2026-08-11 用户确认，容灾 1 个交易日）：跨日即清旧交易日行
            self._prune_stale_sessions(session_date)
            return dict(stored)

    def _prune_stale_sessions(self, current_session: str) -> None:
        """清理策略（2026-08-11 用户确认，容灾 1 个交易日）。

        删除 sessionDate 早于本次写入日期的行（跨日即清旧，天然覆盖周末：
        周五数据保留到周一新写入后自动清理）——Redis 里只保留最近 1 个交易日行，
        避免旧交易日累计值滞留（首屏 bug 根源）；TTL 仅作停止写入后的兜底过期。
        """
        stale = [
            code
            for code, value in self._latest.items()
            if str(value.get("sessionDate") or "") < current_session
        ]
        if not stale:
            return
        for code in stale:
            self._latest.pop(code, None)
        if self._redis is not None:
            try:
                self._redis.hdel(self._key("latest"), *stale)
            except Exception:
                logger.warning("theme-fund 清理旧交易日行失败 codes=%s", len(stale), exc_info=True)

    @staticmethod
    def _parse_fund_row(row: dict[str, object]) -> tuple[str, str, float] | None:
        """解析并校验单行资金流：返回 (code, session_date, zlje)，非法返回 None。"""
        code = str(row.get("code") or "").strip()
        session_date = str(row.get("sessionDate") or row.get("tradingDate") or "").strip()
        source = str(row.get("moneyFlowSource") or row.get("source") or "").strip()
        try:
            zlje = float(row.get("zlje"))
        except (TypeError, ValueError):
            zlje = math.nan
        if (
            not code
            or source not in SUPPORTED_FUND_SOURCES
            or not session_date
            or not math.isfinite(zlje)
        ):
            return None
        return code, session_date, zlje

    @staticmethod
    def _build_stored(
        row: dict[str, object],
        code: str,
        session_date: str,
        zlje: float,
    ) -> dict[str, object]:
        return {
            **row,
            "code": code,
            "zlje": zlje,
            "sessionDate": session_date,
            "tradingDate": session_date,
            # 数据源诚实标识（2026-08-12）：保留行原始 source（akshare_ths_individual
            # 或 ths_main_monitor），不再硬编码 L2；回退 ths_main_monitor 兼容历史行。
            "source": str(row.get("source") or row.get("moneyFlowSource") or FUND_SOURCE_THS_MAIN_MONITOR),
            "moneyFlowSource": str(
                row.get("moneyFlowSource") or row.get("source") or FUND_SOURCE_THS_MAIN_MONITOR
            ),
            "sourceTs": int(row.get("sourceTs") or 0),
            "updatedAt": int(row.get("updatedAt") or int(time.time() * 1000)),
        }

    def put_many(
        self,
        rows: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """批量写入全市场资金流行（单锁 + 单次 hmget + 单次 pipeline）。

        与 ``put`` 逐行语义完全一致：
        - 更旧的行返回既有行（不覆盖）；
        - 非法行收集到 ``failures``，不阻断其余行（fail-visible）；
        - 版本号一次 ``incrby`` 递增，Redis 失败自动回退进程内 last-good。
        Redis 往返从逐行的 3×N 降到每批 3 次（hmget + pipeline + incrby）。
        """
        validated: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        for row in rows:
            parsed = self._parse_fund_row(row)
            if parsed is None:
                code = str(row.get("code") or "").strip()
                failures.append({"code": code, "reason": "invalid fund row"})
                continue
            code, session_date, zlje = parsed
            validated.append(self._build_stored(row, code, session_date, zlje))

        if not validated:
            return [], failures

        saved_rows: list[dict[str, object]] = []
        hash_key = self._key("latest")
        with self._lock:
            # 1) 批量读缺失 code 的最新行（单次 hmget，避免逐行 redis 读）
            missing_codes = [
                str(candidate.get("code") or "")
                for candidate in validated
                if str(candidate.get("code") or "") not in self._latest
            ]
            if missing_codes:
                for code, value in self._read_hash_many(hash_key, missing_codes).items():
                    if value.get("moneyFlowSource") in SUPPORTED_FUND_SOURCES:
                        self._latest[code] = value

            # 2) 版本号批量递增
            version = self._next_version_batch(len(validated))

            # 3) 组装并 pipeline 写入
            pipeline = None
            if self._redis is not None:
                try:
                    pipeline = self._redis.pipeline(transaction=False)
                except Exception:
                    pipeline = None
                    logger.exception("theme-fund redis pipeline() failed")
            if self._redis is None:
                # fail-visible（2026-08-12）：Redis client 不可用（连接/配置失败）——
                # 只写内存，Redis 无持久化；此前静默导致"内存有、Redis 无"
                self._last_redis_write_error = "redis client unavailable (get_hotlist_redis_client returned None)"
                logger.warning(
                    "theme-fund redis client unavailable; skip redis write (memory only): %s",
                    self._last_redis_write_error,
                )
            today = str(validated[0].get("sessionDate") or "")
            for candidate in validated:
                code = str(candidate.get("code") or "")
                previous = self._latest.get(code)
                session_date = str(candidate.get("sessionDate") or "")
                if previous and self._is_older(candidate, previous, session_date):
                    saved_rows.append(dict(previous))
                    continue
                stored: dict[str, object] = {
                    **candidate,
                    "version": version,
                }
                version += 1
                self._latest[code] = stored
                saved_rows.append(dict(stored))
                if pipeline is not None:
                    pipeline.hset(hash_key, code, json.dumps(stored, ensure_ascii=False, separators=(",", ":")))
            # 旧交易日行主动清理（2026-08-12）：TTL 加长后旧累计值不能滞留——
            # 仅在写入日期变化（跨日）时清理 Redis hash + 内存里 sessionDate <
            # 当天 的行；同日内重复写入跳过（5200 字段 hgetall 太重，曾导致大
            # batch put_many 超时、Redis latest 未写入、前端资金列空）
            if (
                self._redis is not None
                and pipeline is not None
                and today != self._last_pruned_date
            ):
                try:
                    self._last_pruned_date = today
                    written_codes = {str(c.get("code")) for c in validated}
                    all_rows = self._read_hash_all(hash_key)
                    stale_fields = [
                        field
                        for field, value in all_rows.items()
                        if field not in written_codes and str(value.get("sessionDate") or "") < today
                    ]
                    if stale_fields:
                        for field in stale_fields:
                            pipeline.hdel(hash_key, field)
                            self._latest.pop(field, None)
                except Exception:
                    pass
            if pipeline is not None:
                try:
                    pipeline.expire(hash_key, self._ttl_seconds)
                    pipeline.execute()
                except Exception:
                    # fail-visible（2026-08-12）：写 Redis 失败必须暴露原因（此前静默吞掉，
                    # 导致内存有数据但 Redis 无——跨重启丢失；socket_timeout 曾 0.2s 超时）
                    logger.exception("theme-fund redis put_many pipeline execute failed")
                    self._last_redis_write_error = str(sys.exc_info()[1]) if sys.exc_info()[1] else "unknown"

            # 4) 清理策略（2026-08-11 用户确认，容灾 1 个交易日）：跨日即清旧交易日行
            self._prune_stale_sessions(today)

        return saved_rows, failures

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
                if value.get("moneyFlowSource") in SUPPORTED_FUND_SOURCES:
                    self._latest[code] = value
            for code in normalized:
                latest = self._latest.get(code)
                if latest:
                    result[code] = dict(latest)
        return result

    def has_redis_data(self) -> bool:
        """Redis 里 theme-fund:latest key 是否存在（2026-08-12：key 曾被误清/
        过期导致前端资金列空，恢复机制用此判断是否需要从内存 last-good 写回）。"""
        if self._redis is None:
            return False
        try:
            return bool(self._redis.exists(self._key("latest")))
        except Exception:
            return False

    def memory_rows(self) -> list[dict[str, object]]:
        """导出进程内 last-good 全部行（用于 Redis key 缺失时写回，零上游请求）。"""
        with self._lock:
            return [dict(value) for value in self._latest.values()]

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
        candidate_rank = FUND_SOURCE_RANK.get(str(candidate.get("moneyFlowSource") or ""), 0)
        previous_rank = FUND_SOURCE_RANK.get(str(previous.get("moneyFlowSource") or ""), 0)
        if candidate_rank != previous_rank:
            return candidate_rank < previous_rank
        return int(candidate.get("sourceTs") or 0) < int(previous.get("sourceTs") or 0)

    def _next_version(self) -> int:
        try:
            if self._redis is not None:
                version_key = self._key("version")
                version = int(self._redis.incr(version_key))
                if version <= self._memory_version:
                    version = self._memory_version + 1
                    self._redis.set(version_key, version)
                self._memory_version = max(self._memory_version, version)
                # 清理策略（2026-08-12）：version 与 latest 同生命周期（TTL 兑底），
                # 停止写入后过期重置，前端 full_state 会清空本地版本记录兑底
                self._redis.expire(version_key, self._ttl_seconds)
                return version
        except Exception:
            pass
        self._memory_version += 1
        return self._memory_version

    def _next_version_batch(self, count: int) -> int:
        """为一批 count 行分配连续版本号，返回起始版本。"""
        if count <= 0:
            return self._memory_version + 1
        try:
            if self._redis is not None:
                version_key = self._key("version")
                end_version = int(self._redis.incrby(version_key, count))
                if end_version - count + 1 <= self._memory_version:
                    end_version = self._memory_version + count
                    self._redis.set(version_key, end_version)
                self._memory_version = max(self._memory_version, end_version)
                self._redis.expire(version_key, self._ttl_seconds)
                return end_version - count + 1
        except Exception:
            pass
        self._memory_version += count
        return self._memory_version - count + 1

    def _read_latest(self, code: str) -> dict[str, object] | None:
        if code in self._latest:
            return self._latest[code]
        value = self._read_hash(self._key("latest"), code)
        if value and value.get("moneyFlowSource") in SUPPORTED_FUND_SOURCES:
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

    def _read_hash_all(self, key: str) -> dict[str, dict[str, object]]:
        """读取 hash 全部字段（用于旧交易日行清理）。"""
        if self._redis is None:
            return {}
        try:
            raw_all = self._redis.hgetall(key)
        except Exception:
            return {}
        result: dict[str, dict[str, object]] = {}
        for field, raw in raw_all.items():
            field_str = field.decode("utf-8") if isinstance(field, bytes) else str(field)
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                value = json.loads(raw) if raw else None
            except (TypeError, ValueError, UnicodeDecodeError):
                continue
            if isinstance(value, dict):
                result[field_str] = value
        return result

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

    def _touch(self, key: str) -> None:
        try:
            if self._redis is not None:
                self._redis.expire(key, self._ttl_seconds)
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
        # akshare 全市场批量刷新，结果写入 Redis（TTL）供跨进程/跨重启共享，
        # 进程内 last-good 继续作为兜底；Redis 故障自动回退不阻断。
        from backend.market_proxy.redis_client import get_hotlist_redis_client

        _theme_fund_cache = ThemeFundCache(
            # 资金大批次 pipeline 写入/连接需要更长超时（快照缓存默认 0.2s 太短，
            # 曾导致 5204 行写入超时/连接超时、Redis 未写入——2026-08-12）
            get_hotlist_redis_client(
                settings,
                socket_timeout=10.0,
                connect_timeout=3.0,
            ),
            prefix=settings.redis_key_prefix,
            ttl_seconds=settings.theme_fund_cache_ttl_seconds,
        )
    return _theme_fund_cache
