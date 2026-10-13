from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 30 * 60
DEFAULT_STALE_TTL_SECONDS = 72 * 3600
STOCK_CODE_PATTERN = re.compile(r"^\d{6}$")

SOURCE = "concept-map-theme"


class ConceptMapService:
    """全市场概念映射：自家 Mongo ``theme_stock_mappings`` 集合（单一事实源）。

    2026-10-13 盘中实测裁决：东财"概念"含大量非题材噪音（指数成分/人气热门股/
    炸板反包股等），不再作为板块异动映射源；改读自家题材库（themes +
    theme_stock_mappings，每日盘前更新）。

    - Mongo 读毫秒级，同步返回；``refreshing`` 恒为 False（客户端轮询协议保留兼容）。
    - 失败可见：Mongo 不可用时回退磁盘缓存（stale=true + errors）；磁盘也没有才抛错。
    - 磁盘缓存写 ``quant-board/data/cache/concept-map-theme.json``（gitignore 本地状态区）。
    """

    def __init__(
        self,
        *,
        database: Any = None,
        cache_dir: str | Path | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        stale_ttl_seconds: float = DEFAULT_STALE_TTL_SECONDS,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._database = database
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._stale_ttl_ms = max(1.0, float(stale_ttl_seconds)) * 1000
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        cache_root = Path(cache_dir) if cache_dir else Path(__file__).resolve().parents[2] / "data" / "cache"
        self._cache_path = cache_root / "concept-map-theme.json"
        self._payload: dict[str, Any] | None = None
        self._cached_at_ms = 0

    async def get_map(self, force_refresh: bool = False) -> dict[str, Any]:
        """返回概念映射快照；``refreshing`` 恒 False，首刷即全量（不再有 1-2 分钟后台窗口）。"""
        now_ms = self._now_ms()
        if (
            not force_refresh
            and self._payload is not None
            and now_ms - self._cached_at_ms < self._ttl_ms
        ):
            return self._payload

        errors: list[str] = []
        try:
            payload = self._load_from_database(now_ms, errors)
        except Exception as exc:
            logger.warning("题材映射读取失败: %s", exc)
            errors.append(f"database_unavailable: {exc}")
            cached = self._load_disk_cache()
            if cached is not None and now_ms - int(cached.get("_cachedAtMs") or 0) <= self._stale_ttl_ms:
                payload = self._with_stale(cached, errors)
            else:
                raise

        self._payload = payload
        self._cached_at_ms = now_ms
        self._save_disk_cache(payload, now_ms)
        return payload

    # ------------------------------------------------------------------ 数据源

    def _load_from_database(self, now_ms: int, errors: list[str]) -> dict[str, Any]:
        database = self._database or self._resolve_database()
        themes = list(database["themes"].find({}, {"id": 1, "name": 1}).sort([("id", 1)]))
        mappings = list(
            database["theme_stock_mappings"].find(
                {}, {"themeId": 1, "stockCode": 1}
            ).sort([("themeId", 1), ("stockCode", 1)])
        )
        by_theme: dict[str, list[str]] = {}
        for row in mappings:
            theme_id = str(row.get("themeId") or "")
            code = str(row.get("stockCode") or "")
            if not STOCK_CODE_PATTERN.fullmatch(code):
                if code:
                    errors.append(f"{theme_id or '?'}: invalid_stock_code:{code}")
                continue
            by_theme.setdefault(theme_id, []).append(code)

        version = ""
        last_update = ""
        try:
            meta = {
                str(row.get("key") or ""): str(row.get("value") or "")
                for row in database["theme_metadata"].find({})
            }
            version = meta.get("version", "")
            last_update = meta.get("lastUpdate", "")
        except Exception as exc:  # metadata 缺失不阻断映射
            errors.append(f"metadata_unavailable: {exc}")

        data = []
        for theme in themes:
            theme_id = str(theme.get("id") or "")
            name = str(theme.get("name") or "").strip()
            key = name or theme_id
            stocks = by_theme.get(theme_id, [])
            if not stocks:
                errors.append(f"{theme_id}: no_valid_members")
                continue
            data.append(
                {
                    "code": theme_id,
                    "name": name,
                    # 板块实时均涨由客户端按成员行情现算（SectorEventEngine 语义），
                    # 题材库不提供静态涨幅，置空避免过期数值被当真
                    "changePct": None,
                    "stocks": stocks,
                }
            )

        if not data:
            raise RuntimeError("theme mapping empty: themes=%d mappings=%d" % (len(themes), len(mappings)))

        return {
            "ok": True,
            "refreshing": False,
            "stale": False,
            "source": SOURCE,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "version": version,
            "lastUpdate": last_update,
            "conceptCount": len(data),
            "stockCount": len({code for row in data for code in row["stocks"]}),
            "data": data,
            "errors": errors,
            "_cachedAtMs": now_ms,
        }

    def _resolve_database(self) -> Any:
        # 函数内导入避免模块环（main → market_data_routes → concepts）
        from backend.main import get_runtime_mongodb_database

        self._database = get_runtime_mongodb_database()
        return self._database

    def _with_stale(self, cached: dict[str, Any], errors: list[str]) -> dict[str, Any]:
        payload = {key: value for key, value in cached.items() if not key.startswith("_")}
        payload["stale"] = True
        payload["errors"] = list(cached.get("errors") or []) + errors
        return payload

    # ------------------------------------------------------------------ 磁盘缓存

    def _load_disk_cache(self) -> dict[str, Any] | None:
        try:
            if not self._cache_path.exists():
                return None
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except Exception as exc:
            logger.warning("概念映射磁盘缓存读取失败: %s", exc)
            return None

    def _save_disk_cache(self, payload: dict[str, Any], fetched_at_ms: int) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot = {key: value for key, value in payload.items() if not key.startswith("_")}
            snapshot["_cachedAtMs"] = fetched_at_ms
            tmp_path = self._cache_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(self._cache_path)
        except Exception as exc:
            logger.warning("概念映射磁盘缓存写入失败: %s", exc)


_service: ConceptMapService | None = None


def get_concept_map_service() -> ConceptMapService:
    global _service
    if _service is None:
        _service = ConceptMapService()
    return _service


async def close_concept_map_client() -> None:
    """兼容保留：数据源已换 Mongo，无外部 HTTP 客户端需要释放。"""
    return None
