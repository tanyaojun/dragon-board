from __future__ import annotations

import asyncio
import json
import math
import re
import time
from contextlib import asynccontextmanager
from typing import Any, Callable

import httpx

from backend.data.snapshot_cache import create_snapshot_redis_client
from backend.settings import get_settings


THS_URL = "https://vaserviece.10jqka.com.cn/Level2/index.php"
THS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://vaserviece.10jqka.com.cn/",
    "Accept": "application/json,text/plain,*/*",
}


class ThsMainMonitorError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class ThsMainMonitorService:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        redis_client: Any | None = None,
        redis_prefix: str = "dragon-board",
        now_ms: Callable[[], int] | None = None,
        request_timeout_seconds: float = 15.0,
        upstream_url: str = THS_URL,
        max_concurrency: int = 2,
    ) -> None:
        self._client = client or httpx.AsyncClient(headers=THS_HEADERS)
        self._owns_client = client is None
        self._redis = redis_client
        self._redis_prefix = redis_prefix.strip(":")
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._request_timeout_seconds = request_timeout_seconds
        self._upstream_url = upstream_url.strip() or THS_URL
        self._raw_memory: dict[str, dict[str, Any]] = {}
        self._condition = asyncio.Condition()
        self._active_requests = 0
        self._max_concurrency = max(1, min(2, int(max_concurrency)))
        self._effective_concurrency = self._max_concurrency
        self._cooldown_until_ms = 0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def enter_cooldown(self, seconds: float) -> None:
        self._cooldown_until_ms = max(
            self._cooldown_until_ms,
            self._now_ms() + max(0, int(seconds * 1000)),
        )

    async def set_effective_concurrency(self, value: int) -> None:
        async with self._condition:
            self._effective_concurrency = max(1, min(self._max_concurrency, int(value)))
            self._condition.notify_all()

    async def load_raw(self, code: str, *, force: bool = False) -> dict[str, Any]:
        stock_code = self._normalize_code(code)
        cached = self._read_raw(stock_code)
        if cached and not force and self._now_ms() - int(cached["fetchedAt"]) <= 3_000:
            return self._raw_result(stock_code, cached, stale=False)
        try:
            payload = await self._fetch_payload(stock_code)
            raw = self._validate_payload(payload)
            raw["fetchedAt"] = self._now_ms()
            self._write_raw(stock_code, raw)
            return self._raw_result(stock_code, raw, stale=False)
        except ThsMainMonitorError:
            if cached:
                return self._raw_result(stock_code, cached, stale=True)
            raise

    async def load_row(self, code: str) -> dict[str, Any]:
        stock_code = self._normalize_code(code)
        payload = await self._fetch_payload(stock_code)
        raw = self._validate_payload(payload)
        source_ts = self._now_ms()
        raw["fetchedAt"] = source_ts
        self._write_raw(stock_code, raw)
        main_buy = self._parse_amount(raw["title"].get("mainbuy"))
        main_sell = self._parse_amount(raw["title"].get("mainsell"))
        return {
            "code": stock_code,
            "zlje": main_buy - main_sell,
            "sessionDate": raw["sessionDate"],
            "source": "ths_main_monitor",
            "moneyFlowSource": "ths_main_monitor",
            "sourceTs": source_ts,
        }

    async def load_batch(self, codes: list[str], *, concurrency: int = 2) -> dict[str, list[dict[str, Any]]]:
        normalized = list(dict.fromkeys(self._normalize_code(code) for code in codes))
        if len(normalized) > 5:
            raise ValueError("too_many_codes")
        local_gate = asyncio.Semaphore(max(1, min(2, int(concurrency))))

        async def load(code: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            async with local_gate:
                try:
                    return await self.load_row(code), None
                except ThsMainMonitorError as error:
                    return None, {"code": code, "errorCode": error.code}

        results = await asyncio.gather(*(load(code) for code in normalized))
        return {
            "rows": [row for row, _ in results if row is not None],
            "failures": [failure for _, failure in results if failure is not None],
        }

    async def _fetch_payload(self, code: str) -> dict[str, Any]:
        async with self._request_slot():
            try:
                response = await self._client.get(
                    self._upstream_url,
                    params={"op": "mainMonitorDetail", "stockcode": code},
                    headers=THS_HEADERS,
                    timeout=self._request_timeout_seconds,
                )
            except httpx.TimeoutException as error:
                raise ThsMainMonitorError("ths_timeout") from error
            except httpx.HTTPError as error:
                raise ThsMainMonitorError("ths_upstream_unavailable") from error
        if response.status_code == 429:
            raise ThsMainMonitorError("ths_rate_limited")
        if response.status_code >= 500:
            raise ThsMainMonitorError("ths_upstream_unavailable")
        text = response.text
        if "验证码" in text or "captcha" in text.lower():
            raise ThsMainMonitorError("ths_captcha_required")
        try:
            payload = response.json()
        except ValueError as error:
            raise ThsMainMonitorError("ths_invalid_payload") from error
        if not isinstance(payload, dict):
            raise ThsMainMonitorError("ths_invalid_payload")
        return payload

    @asynccontextmanager
    async def _request_slot(self):
        if self._now_ms() < self._cooldown_until_ms:
            raise ThsMainMonitorError("ths_rate_limited")
        async with self._condition:
            await self._condition.wait_for(
                lambda: self._active_requests < self._effective_concurrency
            )
            if self._now_ms() < self._cooldown_until_ms:
                raise ThsMainMonitorError("ths_rate_limited")
            self._active_requests += 1
        try:
            yield
        finally:
            async with self._condition:
                self._active_requests -= 1
                self._condition.notify_all()

    def _validate_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            error_code = int(payload.get("errorcode") or 0)
        except (TypeError, ValueError) as error:
            raise ThsMainMonitorError("ths_invalid_payload") from error
        if error_code != 0:
            raise ThsMainMonitorError("ths_invalid_payload")
        title = payload.get("title")
        rows = payload.get("list")
        if not isinstance(title, dict) or not isinstance(rows, list):
            raise ThsMainMonitorError("ths_invalid_payload")
        self._parse_amount(title.get("mainbuy"))
        self._parse_amount(title.get("mainsell"))
        session_date = self._infer_session_date(payload)
        if not session_date:
            raise ThsMainMonitorError("ths_invalid_payload")
        return {
            "sessionDate": session_date,
            "title": title,
            "list": rows,
            "pricechange": payload.get("pricechange") if isinstance(payload.get("pricechange"), list) else [],
        }

    @staticmethod
    def _parse_amount(value: Any) -> float:
        text = str(value or "").strip().replace(",", "").replace("元", "")
        match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([万亿]?)", text)
        if not match:
            raise ThsMainMonitorError("ths_invalid_payload")
        amount = float(match.group(1)) * {"": 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
        if not math.isfinite(amount):
            raise ThsMainMonitorError("ths_invalid_payload")
        return amount

    @staticmethod
    def _infer_session_date(payload: dict[str, Any]) -> str:
        for key in ("sessionDate", "tradeDate", "date"):
            value = str(payload.get(key) or "").strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                return value
        for row in payload.get("pricechange") or []:
            value = str(row[1] if isinstance(row, list) and len(row) > 1 else "")
            match = re.match(r"(\d{4})(\d{2})(\d{2})", value)
            if match:
                return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        for row in payload.get("list") or []:
            if not isinstance(row, dict):
                continue
            match = re.match(r"(\d{4}-\d{2}-\d{2})\s", str(row.get("otime") or row.get("ctime") or ""))
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _normalize_code(value: Any) -> str:
        code = str(value or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("invalid_stock_code")
        return code

    def _raw_key(self, code: str) -> str:
        return f"{self._redis_prefix}:ths-main-monitor:raw:v1:{code}"

    def _read_raw(self, code: str) -> dict[str, Any] | None:
        if code in self._raw_memory:
            return dict(self._raw_memory[code])
        try:
            raw = self._redis.get(self._raw_key(code)) if self._redis is not None else None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            value = json.loads(raw) if raw else None
            if isinstance(value, dict):
                self._raw_memory[code] = value
                return dict(value)
        except Exception:
            return None
        return None

    def _write_raw(self, code: str, value: dict[str, Any]) -> None:
        self._raw_memory[code] = dict(value)
        try:
            if self._redis is not None:
                self._redis.set(self._raw_key(code), json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        except Exception:
            pass

    def _raw_result(self, code: str, raw: dict[str, Any], *, stale: bool) -> dict[str, Any]:
        return {
            "stockCode": code,
            "sessionDate": raw["sessionDate"],
            "fetchedAt": int(raw["fetchedAt"]),
            "servedAt": self._now_ms(),
            "stale": stale,
            "data": {
                "title": raw["title"],
                "list": raw["list"],
                "pricechange": raw["pricechange"],
            },
        }


_service: ThsMainMonitorService | None = None


def get_ths_main_monitor_service() -> ThsMainMonitorService:
    global _service
    if _service is None:
        settings = get_settings()
        redis_client = create_snapshot_redis_client(
            enabled=bool(settings.redis_url),
            redis_url=settings.redis_url,
            connect_timeout=settings.snapshot_cache_connect_timeout_seconds,
            socket_timeout=settings.snapshot_cache_socket_timeout_seconds,
        )
        _service = ThsMainMonitorService(
            redis_client=redis_client,
            redis_prefix=settings.redis_key_prefix,
            request_timeout_seconds=settings.theme_fund_upstream_timeout_seconds,
            upstream_url=settings.theme_fund_ths_upstream_url,
            max_concurrency=settings.theme_fund_concurrency,
        )
    return _service
