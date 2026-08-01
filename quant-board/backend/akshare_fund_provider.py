from __future__ import annotations

import asyncio
import math
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


AMOUNT_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d+)?|\.\d+))\s*([万亿]?)\s*$")
AMOUNT_UNITS: dict[str, float] = {"": 1.0, "万": 10_000.0, "亿": 100_000_000.0}

SYSTEMIC_ERRORS = {"ths_rate_limited", "ths_captcha_required", "ths_upstream_unavailable"}


class AkshareFundProviderError(RuntimeError):
    """Structured upstream failure with a stable error code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass
class AkshareFundBatch:
    rows: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    fetched_at_ms: int
    session_date: str
    source: str = field(default="akshare_ths_individual")


def parse_amount(value: Any) -> float | None:
    """Parse THS 万/亿 formatted amounts, or return None for unparseable values."""
    text = str(value or "").strip().replace(",", "").replace("元", "")
    match = AMOUNT_RE.fullmatch(text)
    if not match:
        return None
    amount = float(match.group(1)) * AMOUNT_UNITS[match.group(2)]
    return amount if math.isfinite(amount) else None


def normalize_code(value: Any) -> str:
    """Normalize 股票代码 to a zero-padded 6-digit string, or empty string."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip() if not isinstance(value, int) else str(value)
    if not re.fullmatch(r"\d{1,6}", text):
        return ""
    return text.zfill(6)


class AkshareFundProvider:
    """Full-market THS individual fund flow via akshare.

    One call to ``ak.stock_fund_flow_individual(symbol="即时")`` returns every
    listed A-share, so the scheduler can refresh the whole market in a single
    batch instead of polling stock by stock. The THS data center still enforces
    anti-crawling (hexin-v token per page, rate limits, captcha), so failures
    are mapped to stable codes and callers keep last-good data.
    """

    def __init__(
        self,
        *,
        akshare_module: Any | None = None,
        tqdm_module: Any | None = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._ak = akshare_module
        self._tqdm_module = tqdm_module
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))

    async def fetch_all(self, *, session_date: str) -> AkshareFundBatch:
        return await asyncio.to_thread(self._fetch_all_sync, session_date)

    def _fetch_all_sync(self, session_date: str) -> AkshareFundBatch:
        fetched_at_ms = self._now_ms()
        ak = self._ak or self._import_akshare()
        tqdm_module = self._tqdm_module or self._import_tqdm_module()
        with self._silence_tqdm(tqdm_module):
            try:
                frame = ak.stock_fund_flow_individual(symbol="即时")
            except Exception as error:
                raise self._map_fetch_error(error) from error
        rows, failures = self._parse_frame(
            frame,
            session_date=session_date,
            fetched_at_ms=fetched_at_ms,
        )
        return AkshareFundBatch(
            rows=rows,
            failures=failures,
            fetched_at_ms=fetched_at_ms,
            session_date=session_date,
        )

    @staticmethod
    def _import_akshare() -> Any:
        import akshare

        return akshare

    @staticmethod
    def _import_tqdm_module() -> Any:
        try:
            import akshare.stock_feature.stock_fund_flow as module

            return module
        except Exception:
            return None

    @contextmanager
    def _silence_tqdm(self, module: Any) -> Iterator[None]:
        original = getattr(module, "get_tqdm", None) if module is not None else None
        if module is not None and original is not None:
            module.get_tqdm = lambda *args, **kwargs: (
                lambda iterable, *iter_args, **iter_kwargs: iterable
            )
        try:
            yield
        finally:
            if module is not None and original is not None:
                module.get_tqdm = original

    def _parse_frame(
        self,
        frame: Any,
        *,
        session_date: str,
        fetched_at_ms: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if frame is None or not hasattr(frame, "to_dict"):
            raise AkshareFundProviderError("ths_invalid_payload", "empty or unexpected fund flow frame")
        try:
            records = frame.to_dict("records")
        except Exception as error:
            raise AkshareFundProviderError("ths_invalid_payload", str(error)) from error

        rows: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                failures.append({"index": index, "code": "", "reason": "not_a_row"})
                continue
            raw_code = record.get("股票代码")
            code = normalize_code(raw_code)
            name = str(record.get("股票简称") or "").strip()
            # zlje 直接取同花顺“个股资金流”页面的“净额”（主力净流入 = 主力流入 − 主力流出）。
            # 注意：该口径与旧 mainMonitorDetail 的 mainbuy − mainsell 并不等价，
            # 同一交易日同一只票两者数值（甚至符号）都可能不同；勿按旧口径换算。
            net = parse_amount(record.get("净额"))
            if not code or net is None:
                failures.append(
                    {
                        "index": index,
                        "code": code or self._display_code(raw_code),
                        "name": name,
                        "reason": "invalid_stock_code_or_zlje",
                    }
                )
                continue
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "zlje": net,
                    "inflow": parse_amount(record.get("流入资金")),
                    "outflow": parse_amount(record.get("流出资金")),
                    "turnover": parse_amount(record.get("成交额")),
                    "sessionDate": session_date,
                    "tradingDate": session_date,
                    "source": "ths_main_monitor",
                    "moneyFlowSource": "ths_main_monitor",
                    "sourceTs": fetched_at_ms,
                }
            )
        return rows, failures

    @staticmethod
    def _display_code(value: Any) -> str:
        """Render a raw 股票代码 for failure reports without NaN noise."""
        if value is None:
            return ""
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        return str(value).strip()

    @staticmethod
    def _map_fetch_error(error: Exception) -> AkshareFundProviderError:
        try:
            import requests
        except Exception:
            requests = None
        if requests is not None:
            if isinstance(error, requests.exceptions.Timeout):
                return AkshareFundProviderError("ths_timeout", str(error))
            if isinstance(error, requests.exceptions.HTTPError):
                status = getattr(getattr(error, "response", None), "status_code", None)
                if status == 429:
                    return AkshareFundProviderError("ths_rate_limited", str(error))
                if status is not None and status >= 500:
                    return AkshareFundProviderError("ths_upstream_unavailable", str(error))
        message = str(error)
        if isinstance(error, AttributeError) or "验证码" in message or "captcha" in message.lower():
            return AkshareFundProviderError("ths_captcha_required", message)
        if isinstance(error, (ValueError, KeyError, TypeError, IndexError)):
            return AkshareFundProviderError("ths_invalid_payload", message)
        return AkshareFundProviderError("ths_upstream_unavailable", message)


_provider: AkshareFundProvider | None = None


def get_akshare_fund_provider() -> AkshareFundProvider:
    global _provider
    if _provider is None:
        _provider = AkshareFundProvider()
    return _provider
