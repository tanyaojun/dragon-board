from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

from backend.market_proxy.quotes import normalize_stock_code

logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36"
)

EM_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
BOARD_LIST_FS = "m:90+t:3"
BOARD_FIELDS = "f12,f14,f3"
CONSTITUENT_FIELDS = "f12,f14"
PAGE_SIZE = 100
MAX_BOARD_PAGES = 6
MAX_CONSTITUENT_PAGES = 8

DEFAULT_TTL_SECONDS = 6 * 3600
DEFAULT_STALE_TTL_SECONDS = 72 * 3600
DEFAULT_CONCURRENCY = 8


class ConceptMapService:
    """东财全市场概念板块映射：板块列表 + 成分股，内存 + 磁盘双缓存。

    - 单板块成分拉取失败计入 ``errors``，不阻断整体（fail-visible）。
    - 刷新失败时回退磁盘缓存并标 ``stale=true``；磁盘缓存超过 stale 窗口且
      刷新仍失败才抛错（路由层降级）。
    - 磁盘缓存默认写 ``quant-board/data/cache/concept-map-em.json``（gitignore 的本地状态区）。
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        cache_dir: str | Path | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        stale_ttl_seconds: float = DEFAULT_STALE_TTL_SECONDS,
        concurrency: int = DEFAULT_CONCURRENCY,
        max_board_pages: int = MAX_BOARD_PAGES,
        max_constituent_pages: int = MAX_CONSTITUENT_PAGES,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._stale_ttl_ms = max(1.0, float(stale_ttl_seconds)) * 1000
        self._semaphore = asyncio.Semaphore(max(1, int(concurrency)))
        self._max_board_pages = max(1, int(max_board_pages))
        self._max_constituent_pages = max(1, int(max_constituent_pages))
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        cache_root = Path(cache_dir) if cache_dir else Path(__file__).resolve().parents[2] / "data" / "cache"
        self._cache_path = cache_root / "concept-map-em.json"
        self._lock = asyncio.Lock()
        self._payload: dict[str, Any] | None = None
        self._cached_at_ms = 0
        self._refresh_cooldown_ms = 60_000.0
        self._last_fail_at_ms = 0
        self._refresh_task: asyncio.Task | None = None
        self._last_refresh_errors: list[str] = []

    async def get_map(self, force_refresh: bool = False, wait: bool = False) -> dict[str, Any]:
        """wait=False（默认）：需要刷新时后台起任务，立即返回 refreshing 快照（首刷不再阻塞请求-响应）；
        wait=True：同步刷新，供测试与诊断使用。"""
        now_ms = self._now_ms()
        if not force_refresh and self._fresh(now_ms):
            return self._payload  # type: ignore[return-value]
        async with self._lock:
            now_ms = self._now_ms()
            if not force_refresh and self._fresh(now_ms):
                return self._payload  # type: ignore[return-value]
            disk = self._load_disk_cache()
            if (
                not force_refresh
                and disk is not None
                and now_ms - disk["fetched_at_ms"] < self._ttl_ms
            ):
                self._payload = disk["payload"]
                self._cached_at_ms = disk["fetched_at_ms"]
                return self._payload  # type: ignore[return-value]

            task_running = self._refresh_task is not None and not self._refresh_task.done()
            if not task_running:
                if (
                    not force_refresh
                    and self._last_fail_at_ms
                    and now_ms - self._last_fail_at_ms < self._refresh_cooldown_ms
                ):
                    # 刷新失败冷却期：不再整轮重试上游，直接走缓存或抛错，避免重试放大
                    if disk is not None and now_ms - disk["fetched_at_ms"] < self._stale_ttl_ms:
                        payload = dict(disk["payload"])
                        payload["stale"] = True
                        payload["errors"] = list(payload.get("errors") or []) + [
                            "refresh_in_cooldown_serving_disk_cache"
                        ]
                        self._payload = payload
                        self._cached_at_ms = disk["fetched_at_ms"]
                        return payload
                    raise RuntimeError("upstream in refresh cooldown and no usable disk cache")
                if wait:
                    try:
                        payload = await self._refresh()
                    except Exception as exc:
                        self._last_fail_at_ms = self._now_ms()
                        if disk is not None and now_ms - disk["fetched_at_ms"] < self._stale_ttl_ms:
                            payload = dict(disk["payload"])
                            payload["stale"] = True
                            payload["errors"] = list(payload.get("errors") or []) + [
                                f"refresh_failed_serving_disk_cache: {str(exc)[:160]}"
                            ]
                            self._payload = payload
                            self._cached_at_ms = disk["fetched_at_ms"]
                            return payload
                        raise
                    fetched_at_ms = self._now_ms()
                    self._save_disk_cache(payload, fetched_at_ms)
                    self._payload = payload
                    self._cached_at_ms = fetched_at_ms
                    return payload
                self._refresh_task = asyncio.create_task(self._background_refresh())

            return self._snapshot_refreshing(disk)

    async def _background_refresh(self) -> None:
        async with self._lock:
            try:
                payload = await self._refresh()
            except Exception as exc:
                self._last_fail_at_ms = self._now_ms()
                self._last_refresh_errors = [f"background_refresh_failed: {str(exc)[:160]}"]
                logger.warning("concept-map background refresh failed: %s", exc)
                return
            fetched_at_ms = self._now_ms()
            self._save_disk_cache(payload, fetched_at_ms)
            self._payload = payload
            self._cached_at_ms = fetched_at_ms
            self._last_refresh_errors = []

    def _snapshot_refreshing(self, disk: dict[str, Any] | None) -> dict[str, Any]:
        """刷新进行中的立即快照：优先回 stale 磁盘缓存，否则空表并标 refreshing。"""
        if disk is not None:
            payload = dict(disk["payload"])
            payload["stale"] = True
            payload["refreshing"] = True
            return payload
        return {
            "ok": True,
            "source": "concept-map-em",
            "stale": False,
            "refreshing": True,
            "conceptCount": 0,
            "stockCount": 0,
            "data": [],
            "errors": ["initial_refresh_in_progress"],
        }

    def _fresh(self, now_ms: int) -> bool:
        return self._payload is not None and now_ms - self._cached_at_ms < self._ttl_ms

    async def _refresh(self) -> dict[str, Any]:
        client = self._client or _get_client()
        boards, board_truncation = await self._fetch_boards(client)
        errors: list[str] = []
        if board_truncation:
            errors.append(board_truncation)
        concepts: list[dict[str, Any]] = []
        if not boards:
            raise RuntimeError("eastmoney board list empty")
        stock_codes: set[str] = set()

        async def fetch_one(board: dict[str, Any]) -> None:
            async with self._semaphore:
                try:
                    stocks, truncated = await self._fetch_constituents(client, board["code"])
                except Exception as exc:
                    errors.append(f"{board['code']} {board['name']}: {str(exc)[:150]}")
                    return
            if truncated:
                errors.append(f"{board['code']} {board['name']}: {truncated}")
            valid = [(code, name) for code, name in stocks if code]
            if not valid:
                errors.append(f"{board['code']} {board['name']}: no_valid_members")
            for code, _ in valid:
                stock_codes.add(code)
            concepts.append(
                {
                    "code": board["code"],
                    "name": board["name"],
                    "changePct": board["changePct"],
                    "stocks": valid,
                }
            )

        await asyncio.gather(*(fetch_one(board) for board in boards))
        concepts.sort(key=lambda item: item["code"])
        return {
            "ok": True,
            "source": "concept-map-em",
            "stale": False,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "conceptCount": len(concepts),
            "stockCount": len(stock_codes),
            "data": concepts,
            "errors": errors,
        }

    async def _fetch_boards(self, client: httpx.AsyncClient) -> tuple[list[dict[str, Any]], str | None]:
        """返回 (板块列表, 截断告警)。告警非空表示分页封顶导致未拉满 total（fail-visible）。"""
        boards: list[dict[str, Any]] = []
        total: int | None = None
        for page in range(1, self._max_board_pages + 1):
            payload = await self._clist(
                client,
                fs=BOARD_LIST_FS,
                fields=BOARD_FIELDS,
                page=page,
            )
            diff = payload.get("diff") or []
            if total is None:
                total = int(payload.get("total") or 0)
            for row in diff:
                code = str(row.get("f12") or "").strip()
                name = str(row.get("f14") or "").strip()
                if not code.startswith("BK"):
                    continue
                boards.append(
                    {
                        "code": code,
                        "name": name,
                        "changePct": _optional_float(row.get("f3")),
                    }
                )
            if total is None or len(boards) >= total or not diff:
                break
        truncation = None
        if total is not None and len(boards) < total:
            truncation = f"board_list_truncated: {len(boards)}/{total}"
        return boards, truncation

    async def _fetch_constituents(
        self, client: httpx.AsyncClient, board_code: str
    ) -> tuple[list[tuple[str, str]], str | None]:
        """返回 (成分列表, 截断告警)。告警非空表示分页封顶导致未拉满 total（fail-visible）。"""
        stocks: list[tuple[str, str]] = []
        seen: set[str] = set()
        total: int | None = None
        for page in range(1, self._max_constituent_pages + 1):
            payload = await self._clist(
                client,
                fs=f"b:{board_code}",
                fields=CONSTITUENT_FIELDS,
                page=page,
            )
            diff = payload.get("diff") or []
            if total is None:
                total = int(payload.get("total") or 0)
            for row in diff:
                raw_code = str(row.get("f12") or "")
                name = str(row.get("f14") or "").strip()
                code = normalize_stock_code(raw_code)
                if not code or code in seen:
                    continue
                seen.add(code)
                stocks.append((code, name))
            if total is None or len(stocks) >= total or not diff:
                break
        truncation = None
        if total is not None and len(stocks) < total:
            truncation = f"{board_code}_cons_truncated: {len(stocks)}/{total}"
        return stocks, truncation

    async def _clist(
        self,
        client: httpx.AsyncClient,
        *,
        fs: str,
        fields: str,
        page: int,
    ) -> dict[str, Any]:
        params = {
            "pn": str(page),
            "pz": str(PAGE_SIZE),
            "po": "1",
            "np": "1",
            "fltt": "2",
            "invt": "2",
            "fid": "f12",
            "fs": fs,
            "fields": fields,
        }
        response = await client.get(
            EM_CLIST_URL,
            params=params,
            headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=8.0,
        )
        response.raise_for_status()
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            return {"total": 0, "diff": []}
        diff = data.get("diff")
        if isinstance(diff, dict):
            diff = list(diff.values())
        return {"total": data.get("total"), "diff": diff if isinstance(diff, list) else []}

    def _load_disk_cache(self) -> dict[str, Any] | None:
        if not self._cache_path.exists():
            return None
        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
            fetched_at_ms = int(raw.get("fetchedAtMs") or 0)
            payload = raw.get("payload")
            if fetched_at_ms <= 0 or not isinstance(payload, dict):
                return None
            return {"fetched_at_ms": fetched_at_ms, "payload": payload}
        except Exception as exc:
            logger.warning("concept-map disk cache unreadable: %s", exc)
            return None

    def _save_disk_cache(self, payload: dict[str, Any], fetched_at_ms: int) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._cache_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(
                    {"fetchedAtMs": fetched_at_ms, "payload": payload},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            os.replace(tmp_path, self._cache_path)
        except Exception as exc:
            logger.warning("concept-map disk cache write failed: %s", exc)


_client: httpx.AsyncClient | None = None
_service: ConceptMapService | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=8.0, headers={"User-Agent": UA})
    return _client


def get_concept_map_service() -> ConceptMapService:
    global _service
    if _service is None:
        _service = ConceptMapService()
    return _service


async def close_concept_map_client() -> None:
    global _client
    client = _client
    _client = None
    if client is not None:
        await client.aclose()


def _optional_float(value: Any) -> float | None:
    try:
        text = str(value).strip()
        if not text or text == "-":
            return None
        return float(text)
    except (TypeError, ValueError):
        return None
