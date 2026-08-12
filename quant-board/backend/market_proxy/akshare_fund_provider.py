from __future__ import annotations

import asyncio
import math
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from backend.core.fund_sources import FUND_SOURCE_AKSHARE_THS_INDIVIDUAL
from backend.core.settings import get_settings


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
    source: str = field(default=FUND_SOURCE_AKSHARE_THS_INDIVIDUAL)


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
        request_timeout_seconds: float = 20.0,
    ) -> None:
        self._ak = akshare_module
        self._tqdm_module = tqdm_module
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.request_timeout_seconds = max(5.0, float(request_timeout_seconds))

    async def fetch_all(self, *, session_date: str) -> AkshareFundBatch:
        return await asyncio.to_thread(self._fetch_all_sync, session_date)

    def _fetch_all_sync(self, session_date: str) -> AkshareFundBatch:
        fetched_at_ms = self._now_ms()
        ak = self._ak or self._import_akshare()
        tqdm_module = self._tqdm_module or self._import_tqdm_module()
        with self._silence_tqdm(tqdm_module):
            with self._bounded_requests():
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

    @contextmanager
    def _bounded_requests(self) -> Iterator[None]:
        """akshare 的 requests 调用不带 timeout，且部分网络 IPv6 链路黑洞会导致请求永久挂起。

        在 akshare 调用期间：
        1. 给 requests.get/post 注入默认 timeout，让单个 HTTP 请求有硬上限；
        2. 强制 getaddrinfo 优先返回 IPv4 记录——data.10jqka.com.cn 在本机
           IPv6 链路可建立 TCP 但数据被黑洞（IPv4 直连正常），IPv4 优先 + timeout 双保险。
        超时抛 requests.exceptions.Timeout，由 _map_fetch_error 映射为 ths_timeout，
        调度器可以正常熔断重试，挂起线程不会无限堆积。
        """
        import requests as requests_module
        import socket as socket_module

        original_get = requests_module.get
        original_post = requests_module.post
        original_getaddrinfo = socket_module.getaddrinfo

        def _with_timeout(original: Callable[..., Any]) -> Callable[..., Any]:
            def wrapped(url: str, *args: Any, **kwargs: Any) -> Any:
                kwargs.setdefault("timeout", self.request_timeout_seconds)
                return original(url, *args, **kwargs)

            return wrapped

        def _ipv4_first_getaddrinfo(*args: Any, **kwargs: Any) -> list[Any]:
            results = original_getaddrinfo(*args, **kwargs)
            ipv4 = [item for item in results if item[0] == socket_module.AF_INET]
            return ipv4 or results

        requests_module.get = _with_timeout(original_get)
        requests_module.post = _with_timeout(original_post)
        socket_module.getaddrinfo = _ipv4_first_getaddrinfo
        try:
            yield
        finally:
            requests_module.get = original_get
            requests_module.post = original_post
            socket_module.getaddrinfo = original_getaddrinfo

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
            turnover = parse_amount(record.get("成交额"))
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
            row: dict[str, Any] = {
                "code": code,
                "name": name,
                "zlje": net,
                "inflow": parse_amount(record.get("流入资金")),
                "outflow": parse_amount(record.get("流出资金")),
                "turnover": turnover,
                "sessionDate": session_date,
                "tradingDate": session_date,
                # 数据源诚实标识（2026-08-12 用户确认）：本行来自 akshare 同花顺
                # 网页个股资金流（stock_fund_flow_individual），并非 mainMonitorDetail
                # L2 口径——source 用 akshare_ths_individual，前端显示"同花顺网页资金流"
                # 而非 L2 标识，避免误导。
                "source": FUND_SOURCE_AKSHARE_THS_INDIVIDUAL,
                "moneyFlowSource": FUND_SOURCE_AKSHARE_THS_INDIVIDUAL,
                "sourceTs": fetched_at_ms,
            }
            # zljzb（主力%）：akshare 个股资金流“即时”接口没有净占比列，
            # 按“主力净额占成交额比例”推导；成交额缺失/为 0 时保持缺失，不用 0 伪装。
            if turnover and turnover > 0:
                row["zljzb"] = round(net / turnover * 100, 2)
            rows.append(row)
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
        settings = get_settings()
        # 单请求超时上限取调度器整体预算的一半，避免 60s 预算全被一次挂起耗尽
        request_timeout = min(
            30.0,
            max(10.0, settings.market_fund_fetch_timeout_seconds / 2),
        )
        _provider = AkshareFundProvider(request_timeout_seconds=request_timeout)
    return _provider
