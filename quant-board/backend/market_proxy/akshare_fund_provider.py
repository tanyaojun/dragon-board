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

# 东财 push2 clist 参数（与 akshare stock_individual_fund_flow_rank 一致）。
# akshare 1.18.81 的该函数 53 页无间隔连发会触发 push2 WAF（RemoteDisconnected），
# 且无 UA/timeout，因此本 provider 直接分页请求，每页间隔摊薄限流。
EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_FIELDS = "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124"
EASTMONEY_UT = "b2884a393a59ad64002292a3e90d46a5"
EASTMONEY_FS = (
    "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,"
    "m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2"
)
# diff 的 f 字段 → _parse_frame 使用的中文列名
EASTMONEY_COLUMN_MAP: dict[str, str] = {
    "f12": "代码",
    "f14": "名称",
    "f2": "最新价",
    "f3": "今日涨跌幅",
    "f62": "今日主力净流入-净额",
    "f184": "今日主力净流入-净占比",
    "f66": "今日超大单净流入-净额",
    "f69": "今日超大单净流入-净占比",
    "f72": "今日大单净流入-净额",
    "f75": "今日大单净流入-净占比",
    "f78": "今日中单净流入-净额",
    "f81": "今日中单净流入-净占比",
    "f84": "今日小单净流入-净额",
    "f87": "今日小单净流入-净占比",
}
DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}


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
    """Parse 万/亿 formatted amounts (or EastMoney float 元), or None for unparseable."""
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
    """Full-market EastMoney individual fund flow (own paginated clist fetch).

    One full pass returns every listed A-share (主力净流入 = 超大单 + 大单净流入,
    与 L2 mainMonitorDetail 的 mainbuy − mainsell 口径近似，实盘验证差异远小于
    同花顺网页口径), so the scheduler refreshes the whole market in a single
    batch. akshare's ``stock_individual_fund_flow_rank`` is NOT used: it issues
    53 pages back-to-back with no interval/UA/timeout and trips the push2 WAF
    (RemoteDisconnected). This provider paginates itself with:
    - UA/Referer headers and a hard request timeout;
    - IPv4-first DNS (some IPv6 links blackhole push2);
    - a configurable per-page sleep to stay under the rate limit;
    - page-count cap and stable error codes for the scheduler's circuit breaker.
    """

    def __init__(
        self,
        *,
        now_ms: Callable[[], int] | None = None,
        request_timeout_seconds: float = 20.0,
        page_interval_seconds: float = 0.35,
        max_pages: int = 120,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.request_timeout_seconds = max(5.0, float(request_timeout_seconds))
        self.page_interval_seconds = max(0.0, float(page_interval_seconds))
        self.max_pages = max(1, int(max_pages))
        self.headers = dict(headers or DEFAULT_HEADERS)

    async def fetch_all(self, *, session_date: str) -> AkshareFundBatch:
        return await asyncio.to_thread(self._fetch_all_sync, session_date)

    def _fetch_all_sync(self, session_date: str) -> AkshareFundBatch:
        fetched_at_ms = self._now_ms()
        with self._ipv4_first_dns():
            diff = self._fetch_eastmoney_pages()
        if not diff:
            return AkshareFundBatch(
                rows=[],
                failures=[],
                fetched_at_ms=fetched_at_ms,
                session_date=session_date,
            )
        frame = pd.DataFrame(diff)
        rename = {k: v for k, v in EASTMONEY_COLUMN_MAP.items() if k in frame.columns}
        if rename:
            frame = frame.rename(columns=rename)
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

    def _fetch_eastmoney_pages(self) -> list[dict[str, Any]]:
        """分页拉取东财 clist 全市场排行，每页间隔摊薄限流。"""
        import requests

        collected: list[dict[str, Any]] = []
        page = 1
        while page <= self.max_pages:
            params = {
                "fid": "f62",
                "po": "1",
                "pz": "100",
                "pn": page,
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "ut": EASTMONEY_UT,
                "fs": EASTMONEY_FS,
                "fields": EASTMONEY_FIELDS,
            }
            try:
                resp = requests.get(
                    EASTMONEY_CLIST_URL,
                    params=params,
                    headers=self.headers,
                    timeout=self.request_timeout_seconds,
                )
                # 显式检查 HTTP 状态：429/5xx 由 _map_fetch_error 映射为
                # ths_rate_limited / ths_upstream_unavailable（触发调度器限流冷却），
                # 否则会被 resp.json() 的 JSONDecodeError 吞成 ths_invalid_payload
                resp.raise_for_status()
                data = resp.json().get("data") or {}
            except Exception as error:
                raise self._map_fetch_error(error) from error
            diff = data.get("diff") or []
            total = int(data.get("total") or 0)
            collected.extend(diff)
            total_pages = max(1, math.ceil(total / 100)) if total else page
            if not diff or page >= total_pages:
                break
            page += 1
            if self.page_interval_seconds > 0:
                time.sleep(self.page_interval_seconds)
        return collected

    @contextmanager
    def _ipv4_first_dns(self) -> Iterator[None]:
        """东财 push2 在部分 IPv6 链路上可能黑洞，请求期间强制 DNS 优先 IPv4。"""
        import socket

        original_getaddrinfo = socket.getaddrinfo

        def _ipv4_first(*args: Any, **kwargs: Any) -> list[Any]:
            results = original_getaddrinfo(*args, **kwargs)
            ipv4 = [item for item in results if item[0] == socket.AF_INET]
            return ipv4 or results

        socket.getaddrinfo = _ipv4_first
        try:
            yield
        finally:
            socket.getaddrinfo = original_getaddrinfo

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
            raw_code = record.get("代码")
            code = normalize_code(raw_code)
            name = str(record.get("名称") or "").strip()
            # zlje 取东财“个股资金流”排行（今日）的主力净流入净额（元），
            # 口径 = 超大单 + 大单净流入，与 L2 mainMonitorDetail 的
            # mainbuy − mainsell 近似（实盘验证差异远小于同花顺网页口径）。
            # 本行只作为全市场“种子占位”（source=eastmoney_seed + moneyFlowEstimated），
            # 盘中由 mainMonitorDetail（ths_main_monitor）逐票校准覆盖，见
            # docs/theme-module/2026-08-08-ths-fund-source-optimization-design.md。
            net = parse_amount(record.get("今日主力净流入-净额"))
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
            # zljzb（主力净占比 %）：东财排行接口直接提供，缺失/为空时保持缺失，
            # 不用 0 伪装占比。
            net_pct = parse_amount(record.get("今日主力净流入-净占比"))
            if net_pct is not None:
                row["zljzb"] = net_pct
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
            # 东财 push2 对高频/大页请求直接断开连接（RemoteDisconnected），
            # 属服务端风控，映射为 ths_rate_limited 走调度器限流冷却。
            if isinstance(error, requests.exceptions.ConnectionError):
                return AkshareFundProviderError("ths_rate_limited", str(error))
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
