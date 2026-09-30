from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from backend.core.fund_sources import FUND_SOURCE_EASTMONEY_MAIN
from backend.core.settings import get_settings


logger = logging.getLogger(__name__)

# push2 行情批量接口（参考 八合一热榜BK.html loadStockInfoByCodes）：
# 一次请求携带多只 secids，返回 f62 主力净额 / f66 超大单净额 / f69 超大单净占比 /
# f184 主力净占比 / f6 成交额，金额单位元、占比单位 %（fltt=2 时已是数值）。
EM_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EM_UT_TOKEN = "a79f54e3d4c8d44e494efb8f748db291"
EM_FIELDS = "f12,f14,f2,f3,f6,f62,f66,f69,f184"
# f2（最新价）/f3（涨跌幅）当前行合同未消费，随参考实现一并请求，
# 供后续行情侧字段扩展零改动复用（fields 数量不额外增加限流压力）。
EM_REFERER = "https://quote.eastmoney.com/"
EM_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
# 社区实战铁律（a-stock-data 10.4k 星 SKILL 防封铁律第 3 条）：复用 HTTP 会话
# （Keep-Alive），不要每次新建连接——连接重建频率本身是风控指纹之一。
# 故 provider 全程复用同一 client，不设 Connection: close。

# 系统性错误：命中即中止本轮剩余批次（东财风控信号，继续请求有封 IP 风险），
# 由 MarketFundScheduler 打开熔断冷却。
SYSTEMIC_ERRORS = frozenset({"em_rate_limited", "em_upstream_unavailable"})

# 连续多少批失败（任意错误）视为上游异常，中止本轮剩余批次。
MAX_CONSECUTIVE_BATCH_FAILURES = 3


class EastmoneyFundProviderError(RuntimeError):
    """Structured upstream failure with a stable error code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass
class EastmoneyFundBatch:
    rows: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    fetched_at_ms: int
    session_date: str
    source: str = field(default=FUND_SOURCE_EASTMONEY_MAIN)
    # 本轮实际发出的 HTTP 请求数（限流审计用）
    request_count: int = 0
    # 命中风控/上游异常中止剩余批次时的错误码（空串=完整跑完）。
    # fail-visible：中止前已成功批次的数据照常保存，同时结构化上报中止原因。
    truncated_by: str = ""


def build_secid(code: str) -> str:
    """股票代码 → 东财 secid：沪市（6/11/51 开头）``1.code``，其余 ``0.code``。

    与 八合一热榜BK.html 参考实现一致（6xx 沪主板/科创，11 沪可转债，
    51 沪 ETF；0/3 深市、4/8 北交所归 0.）。注意：沪 B（900xxx）按其余规则
    落 0. 与东财真实分域不符，但题材 universe 为 A 股纯股票不可达；
    若日后引入 B 股需在此显式扩展。
    """
    return f"1.{code}" if code.startswith(("6", "11", "51")) else f"0.{code}"


def parse_em_number(value: Any) -> float | None:
    """东财数值字段解析：'-'/None/非有限值 → None（缺失诚实，不用 0 伪装）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
        return amount if math.isfinite(amount) else None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text or text == "-":
            return None
        try:
            amount = float(text)
        except ValueError:
            return None
        return amount if math.isfinite(amount) else None
    return None


def normalize_code(value: Any) -> str:
    """Normalize 股票代码 to a zero-padded 6-digit string, or empty string."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip() if not isinstance(value, int) else str(value)
    if not text.isdigit() or len(text) > 6:
        return ""
    return text.zfill(6)


class EastmoneyFundProvider:
    """东财 push2 主力资金批量 provider（httpx 独立 URL 直连，不走 akshare）。

    为什么不用 akshare 的东财封装：东财接口风控限流严重，必须精确控制请求
    节奏（批量 + 串行 + 最小间隔 + 命中风控立即中止），akshare 封装无法提供
    这些抓手（2026-09-29 用户确认题材主力资金切换东财口径时明确）。

    风控纪律（防封 IP，2026-09-30 二次论断定稿）：

    核心原则：东财语境下服务器压力 ∝ 请求次数，与每批大小几乎无关——
    绝不允许「短间距时间内频繁发起请求」。

    - 全程串行，无并发；
    - 大批少请求：每请求 800 只 secids（URL≈6.9KB，贴近 nginx 8KB 上限；
      全市场约 7 批）——无法一次全市场是 URL 硬限制（5500 只≈50KB 超限），
      分批仅为过 URL 上限，不是减压手段，减压靠批间距；
    - 相邻两次 HTTP 请求发起间隔 >= ``request_interval_seconds``（默认 60s，
      分钟级摊开 + 随机抖动防精确节拍指纹：任意 1 分钟窗口最多 1 个请求）；
    - 全程复用同一 HTTP 连接（Keep-Alive，社区铁律：连接重建频率本身是
      风控指纹，不要每次新建连接）；
    - 调度默认 1800s（30 分钟）一轮，轮内约 6 分钟完成、其余静默
      → 均摊约 0.23 req/min，每小时 <=14 请求；
    - 命中 429/403/5xx/断连立即中止剩余批次（truncated_by 结构化上报），
      调度器据此长冷却（东财默认 1800s），不反复刺激 WAF；
    - 连续 3 批失败（含超时/坏负载）同样中止；
    - 单批超时/坏负载只记批级 failure 并继续（单次抖动≠被封）。

    已知边界：调度器 fetch 超时（asyncio.wait_for）只取消 await，to_thread
    内的同步抓取线程会按自身节流跑完剩余批次（有界：默认 7 批、轮内约
    6-8 分钟；极端 env 如 batch_size=50 可更长），该轮结果被丢弃。下轮与
    僵尸线程重叠时串行节流可能被破坏——东财模式 fetch 预算由调度器保证
    >=600s（6×60~69s 批间距 + 7×15s 超时 ≈ 465-519s）；若通过 env 调大
    批间距/批大小时，需同步调大 QUANT_BOARD_MARKET_FUND_FETCH_TIMEOUT_SECONDS
    （EM 模式实际预算 = max(600, 该值)）。
    """

    # 调度器 status() 的数据源诚实标识（与 batch.source 一致）
    source = FUND_SOURCE_EASTMONEY_MAIN

    def __init__(
        self,
        *,
        universe_provider: Callable[[], list[str]] | None = None,
        client: httpx.Client | None = None,
        now_ms: Callable[[], int] | None = None,
        sleep: Callable[[float], None] | None = None,
        batch_size: int = 800,
        request_interval_seconds: float = 60.0,
        request_timeout_seconds: float = 15.0,
        url: str = EM_QUOTE_URL,
    ) -> None:
        self._universe_provider = universe_provider
        self._client = client
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._sleep = sleep or time.sleep
        self._batch_size = max(1, int(batch_size))
        self._request_interval_seconds = max(0.0, float(request_interval_seconds))
        self.request_timeout_seconds = max(5.0, float(request_timeout_seconds))
        self._url = url
        self._last_request_monotonic: float | None = None
        self._owned_client: httpx.Client | None = None

    def _ensure_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        if self._owned_client is None:
            self._owned_client = httpx.Client(timeout=self.request_timeout_seconds)
        return self._owned_client

    def close(self) -> None:
        if self._owned_client is not None:
            self._owned_client.close()
            self._owned_client = None

    async def fetch_all(
        self,
        *,
        session_date: str,
        codes: list[str] | None = None,
    ) -> EastmoneyFundBatch:
        return await asyncio.to_thread(self._fetch_all_sync, codes, session_date)

    def _fetch_all_sync(
        self,
        codes: list[str] | None,
        session_date: str,
    ) -> EastmoneyFundBatch:
        fetched_at_ms = self._now_ms()
        universe = list(codes) if codes else self._resolve_universe()
        if not universe:
            # universe 缺失（行情缓存未就绪且 Redis 无兜底）：不是空成功，
            # 抛结构化错误让调度器按"本轮无数据原因"暴露，保留 last-good。
            raise EastmoneyFundProviderError("em_universe_unavailable", "no stock universe for eastmoney fund fetch")

        rows: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        request_count = 0
        truncated_by = ""
        consecutive_failures = 0
        for start in range(0, len(universe), self._batch_size):
            batch_codes = universe[start : start + self._batch_size]
            # 无条件节流：首批无基准不等待，后续批等满最小间隔；
            # 时间戳在请求完成后记录（end-to-start 口径，慢响应不背靠背连发）
            self._throttle()
            request_count += 1
            try:
                diff = self._fetch_batch_diff(batch_codes)
            except EastmoneyFundProviderError as error:
                self._last_request_monotonic = time.monotonic()
                failures.append(
                    {
                        "batchStart": start,
                        "batchSize": len(batch_codes),
                        "reason": error.code,
                        "message": str(error)[:200],
                    }
                )
                if error.code in SYSTEMIC_ERRORS:
                    # 命中风控：立即中止，避免封 IP；已成功批次数据照常返回保存
                    truncated_by = error.code
                    break
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_BATCH_FAILURES:
                    truncated_by = error.code
                    break
                continue
            self._last_request_monotonic = time.monotonic()
            consecutive_failures = 0
            batch_rows, batch_failures = self._parse_diff(
                diff,
                session_date=session_date,
                fetched_at_ms=fetched_at_ms,
            )
            rows.extend(batch_rows)
            failures.extend(batch_failures)
        return EastmoneyFundBatch(
            rows=rows,
            failures=failures,
            fetched_at_ms=fetched_at_ms,
            session_date=session_date,
            request_count=request_count,
            truncated_by=truncated_by,
        )

    def _resolve_universe(self) -> list[str]:
        if self._universe_provider is None:
            return []
        try:
            return [str(code) for code in self._universe_provider() if str(code).strip()]
        except Exception:
            logger.exception("eastmoney fund universe provider failed")
            return []

    def _request_headers(self) -> dict[str, str]:
        return {"User-Agent": EM_UA, "Referer": EM_REFERER}

    def _throttle(self) -> None:
        """相邻请求最小间隔 + 随机抖动（对齐社区 em_get 实践：固定节拍也是指纹）。

        首次调用基准为空不等待；时间戳在每批请求**完成后**由调用方记录
        （end-to-start 口径）：慢响应也不会背靠背连发，任意两请求发起间隔
        >= request_interval_seconds，抖动幅度 interval*0.15 内随机
        （抖动仅附加在需要等待的分支：上一批耗时已超 interval 时零抖动立即发，
        默认 60s 间隔 + 15s 超时上限下不可达，仅极端 env 理论存在）。
        """
        if self._last_request_monotonic is not None:
            elapsed = time.monotonic() - self._last_request_monotonic
            wait = self._request_interval_seconds - elapsed
            if wait > 0:
                self._sleep(wait + random.uniform(0.0, self._request_interval_seconds * 0.15))
        # 时间戳由调用方在请求完成后记录（end-to-start 口径），此处不预记

    def _fetch_batch_diff(self, batch_codes: list[str]) -> list[dict[str, Any]]:
        secids = ",".join(build_secid(code) for code in batch_codes)
        params = {
            "fltt": "2",
            "np": "3",
            "invt": "2",
            "ut": EM_UT_TOKEN,
            "secids": secids,
            "fields": EM_FIELDS,
        }
        client = self._ensure_client()
        try:
            # UA/Referer 请求级注入：东财缺 Referer 时风控拒答率明显升高；
            # 注入自定义 client（测试/代理）时同样生效
            response = client.get(self._url, params=params, headers=self._request_headers())
        except httpx.TimeoutException as error:
            raise EastmoneyFundProviderError("em_timeout", str(error)[:200]) from error
        except httpx.HTTPError as error:
            raise EastmoneyFundProviderError("em_upstream_unavailable", str(error)[:200]) from error
        if response.status_code in (429, 403):
            # 东财风控信号：绝不重试/继续，交给调度器熔断冷却
            raise EastmoneyFundProviderError("em_rate_limited", f"HTTP {response.status_code}")
        if response.status_code != 200:
            raise EastmoneyFundProviderError("em_upstream_unavailable", f"HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise EastmoneyFundProviderError("em_invalid_payload", str(error)[:200]) from error
        data = payload.get("data") if isinstance(payload, dict) else None
        diff = data.get("diff") if isinstance(data, dict) else None
        if not isinstance(diff, list):
            # HTTP 200 但 body 非行情结构：常见于被风控拦截（返回空/HTML），按坏负载处理
            raise EastmoneyFundProviderError("em_invalid_payload", "missing data.diff list")
        return diff

    def _parse_diff(
        self,
        diff: list[Any],
        *,
        session_date: str,
        fetched_at_ms: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for index, item in enumerate(diff):
            if not isinstance(item, dict):
                failures.append({"index": index, "code": "", "reason": "not_a_row"})
                continue
            code = normalize_code(item.get("f12"))
            name = str(item.get("f14") or "").strip()
            # zlje 直接取东财 f62 主力净额（主力流入 − 主力流出，元）。
            zlje = parse_em_number(item.get("f62"))
            if not code or zlje is None:
                failures.append(
                    {
                        "index": index,
                        "code": code,
                        "name": name,
                        "reason": "invalid_stock_code_or_zlje",
                    }
                )
                continue
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "zlje": zlje,
                    # ulist 接口无流入/流出分项：诚实缺失，不伪装（旧 akshare 行才有）
                    "inflow": None,
                    "outflow": None,
                    "cddje": parse_em_number(item.get("f66")),
                    "cddjzb": parse_em_number(item.get("f69")),
                    "zljzb": parse_em_number(item.get("f184")),
                    "turnover": parse_em_number(item.get("f6")),
                    "sessionDate": session_date,
                    "tradingDate": session_date,
                    "source": FUND_SOURCE_EASTMONEY_MAIN,
                    "moneyFlowSource": FUND_SOURCE_EASTMONEY_MAIN,
                    "sourceTs": fetched_at_ms,
                }
            )
        return rows, failures


_provider: EastmoneyFundProvider | None = None


def get_eastmoney_fund_provider() -> EastmoneyFundProvider:
    global _provider
    if _provider is None:
        # universe 用腾讯全市场行情缓存（每 300s 刷新，Redis 兜底跨重启），
        # 避免为东财再引入一个"全市场股票列表"上游请求（风控请求预算内能省则省）。
        from backend.market_proxy.quotes import get_market_quotes_cache

        settings = get_settings()
        _provider = EastmoneyFundProvider(
            universe_provider=get_market_quotes_cache().all_codes,
            batch_size=settings.theme_fund_em_batch_size,
            request_interval_seconds=settings.theme_fund_em_request_interval_seconds,
            request_timeout_seconds=min(
                30.0,
                max(5.0, settings.theme_fund_em_request_timeout_seconds),
            ),
        )
    return _provider
