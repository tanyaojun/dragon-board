"""Transitional data-source providers for the backend snapshot collector.

Each provider fetches raw material from one external source and returns
a ``(data, SourceHealth)`` tuple.  Providers never write MongoDB snapshot
collections and never generate ``snapshot_id`` values.

- ``ProxyHotlistProvider`` ── hotlist stocks from the local proxy-server
- ``BridgeQuoteProvider``   ── real-time quotes from the python-bridge
- ``ThemeMappingProvider``  ── code➜theme mapping from MongoDB theme tables
- ``collect_market_context``── assembles all providers into a MarketDataContext
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .models import MarketDataContext, SourceHealth

# ── constants ───────────────────────────────────────────────────────────────

_DEFAULT_PROXY_BASE_URL = "http://127.0.0.1:3000"
_DEFAULT_BRIDGE_BASE_URL = "http://127.0.0.1:8765"
_DEFAULT_TIMEOUT_MS = 5000


# ── helpers ─────────────────────────────────────────────────────────────────


def _iso_now() -> str:
    """ISO-8601 UTC timestamp string for health records."""
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce *value* to int via float, returning *default* on failure."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _http_get_json(url: str, timeout_s: float) -> Any:
    """Perform a GET request and return the parsed JSON body.

    Raises ``urllib.error.URLError`` or ``ValueError`` on failure.
    """
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


# ═════════════════════════════════════════════════════════════════════════════
# ProxyHotlistProvider
# ═════════════════════════════════════════════════════════════════════════════


class ProxyHotlistProvider:
    """Fetch hotlist stock data from the proxy-server (eastmoney endpoint).

    Returns normalized stock rows suitable for ingestion into the snapshot
    pipeline.  Each row carries ``code``, ``name``, ``rank``, ``price``,
    ``pctChange``, ``volume``, ``amount``, ``turnover``, ``heat``.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_PROXY_BASE_URL,
        platform: str = "eastmoney",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._platform = platform

    # ── public API ──────────────────────────────────────────────────────

    def collect(
        self,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[list[dict[str, Any]], SourceHealth]:
        """Fetch hotlist stocks and return ``(stock_rows, health)``.

        Never raises — errors are captured in the returned ``SourceHealth``.
        """
        start = time.monotonic()
        try:
            url = f"{self._base_url}/api/{self._platform}/hot"
            timeout_s = timeout_ms / 1000.0
            body = _http_get_json(url, timeout_s)
            rows = self._normalize(body)
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="hotlist_proxy",
                ok=True,
                latency_ms=latency_ms,
                row_count=len(rows),
                captured_at=_iso_now(),
            )
            return rows, health
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="hotlist_proxy",
                ok=False,
                latency_ms=latency_ms,
                error=str(exc),
                captured_at=_iso_now(),
            )
            return [], health

    # ── internal ────────────────────────────────────────────────────────

    def _normalize(self, body: Any) -> list[dict[str, Any]]:
        """Convert raw proxy response to a list of stock row dicts."""
        items = _extract_items(body)
        rows: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            code = str(item.get("c") or "").strip()
            if not code:
                continue
            row: dict[str, Any] = {
                "code": code,
                "name": str(item.get("n") or code),
                "rank": _safe_int(item.get("r"), len(rows) + 1),
                "price": _safe_float(item.get("p")),
                "pctChange": _safe_float(item.get("zdf")),
                "volume": _safe_int(item.get("cjl")),
                "amount": _safe_float(item.get("cje")),
                "turnover": _safe_float(item.get("hsl")),
                "heat": _safe_float(item.get("hot")),
            }
            rows.append(row)
        return rows


def _extract_items(body: Any) -> list[Any]:
    """Extract the item list from a variety of proxy response shapes."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        # eastmoney shape: {"data": [...]}
        for key in ("data", "items", "List", "result", "dto"):
            value = body.get(key)
            if isinstance(value, list):
                return value
        # ths shape: {"data": {"stock_list": [...]}}
        data = body.get("data")
        if isinstance(data, dict):
            for key in ("stock_list", "items", "List"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
    return []


# ═════════════════════════════════════════════════════════════════════════════
# BridgeQuoteProvider
# ═════════════════════════════════════════════════════════════════════════════


class BridgeQuoteProvider:
    """Fetch real-time quote snapshot from the python-bridge.

    Calls ``GET /api/quotes/snapshot?codes=...`` and returns a dict
    containing ``quotes``, ``depth``, ``money_flow``, and ``market_meta``.
    """

    def __init__(self, base_url: str = _DEFAULT_BRIDGE_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    # ── public API ──────────────────────────────────────────────────────

    def collect(
        self,
        codes: list[str],
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[dict[str, Any], SourceHealth]:
        """Fetch bridge snapshot for *codes*.

        Returns ``(data, health)`` where *data* is::

            {
                "quotes": [...],
                "depth": [...],
                "money_flow": [...],
                "market_meta": {...},
            }

        Never raises — errors are captured in the returned ``SourceHealth``.
        """
        start = time.monotonic()
        if not codes:
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="quote_bridge",
                ok=True,
                latency_ms=latency_ms,
                row_count=0,
                captured_at=_iso_now(),
            )
            return {"quotes": [], "depth": [], "money_flow": [], "market_meta": {}}, health

        try:
            codes_param = ",".join(str(c).strip() for c in codes if str(c).strip())
            if not codes_param:
                raise ValueError("no valid codes after filtering")

            url = f"{self._base_url}/api/quotes/snapshot?codes={urllib.request.quote(codes_param, safe='')}"
            timeout_s = timeout_ms / 1000.0
            body = _http_get_json(url, timeout_s)

            # Interpret bridge ok flag
            bridge_ok = body.get("ok", True)  # default True when absent
            if not bridge_ok:
                # Build a sensible error message from the body
                error_detail = body.get("error") or f"bridge returned ok=false (subscribedCount={body.get('subscribedCount', 0)})"
                latency_ms = int((time.monotonic() - start) * 1000)
                health = SourceHealth(
                    source="quote_bridge",
                    ok=False,
                    latency_ms=latency_ms,
                    error=str(error_detail),
                    captured_at=_iso_now(),
                )
                return {"quotes": [], "depth": [], "money_flow": [], "market_meta": {}}, health

            quotes = _normalize_quote_list(body.get("quotes"))
            depth = _normalize_depth_list(body.get("depth"))
            money_flow = _normalize_money_flow_list(body.get("moneyFlow"))
            market_meta = _normalize_quote_stats(body.get("quoteStats"))

            latency_ms = int((time.monotonic() - start) * 1000)
            row_count = max(len(quotes), len(depth), len(money_flow))
            health = SourceHealth(
                source="quote_bridge",
                ok=True,
                latency_ms=latency_ms,
                row_count=row_count,
                captured_at=_iso_now(),
            )
            data = {
                "quotes": quotes,
                "depth": depth,
                "money_flow": money_flow,
                "market_meta": market_meta,
            }
            return data, health

        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="quote_bridge",
                ok=False,
                latency_ms=latency_ms,
                error=str(exc),
                captured_at=_iso_now(),
            )
            return {"quotes": [], "depth": [], "money_flow": [], "market_meta": {}}, health


def _normalize_quote_list(raw: Any) -> list[dict[str, Any]]:
    """Coerce raw quotes to a list of dicts with known keys."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        result.append(
            {
                "code": code,
                "price": _safe_float(item.get("price")),
                "pctChange": _safe_float(item.get("pctChange")),
                "volume": _safe_int(item.get("volume")),
                "amount": _safe_float(item.get("amount")),
                "turnover": _safe_float(item.get("turnover")),
            }
        )
    return result


def _normalize_depth_list(raw: Any) -> list[dict[str, Any]]:
    """Coerce raw depth to a list of dicts."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        row: dict[str, Any] = {"code": code}
        for i in range(1, 6):  # up to 5 bid/ask levels
            for prefix in ("bid", "ask"):
                for suffix in ("Price", "Vol"):
                    key = f"{prefix}{suffix}{i}"
                    if key in item:
                        row[key] = item[key]
        # Also copy any top-level depth fields
        for k in ("bidPrice1", "askPrice1", "bidVol1", "askVol1"):
            if k in item:
                row.setdefault(k, item[k])
        result.append(row)
    return result


def _normalize_money_flow_list(raw: Any) -> list[dict[str, Any]]:
    """Coerce raw moneyFlow to a list of dicts."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        result.append(
            {
                "code": code,
                "mainNetInflow": _safe_float(item.get("mainNetInflow")),
                "superLargeNetInflow": _safe_float(item.get("superLargeNetInflow")),
                "largeNetInflow": _safe_float(item.get("largeNetInflow")),
                "mediumNetInflow": _safe_float(item.get("mediumNetInflow")),
                "smallNetInflow": _safe_float(item.get("smallNetInflow")),
            }
        )
    return result


def _normalize_quote_stats(raw: Any) -> dict[str, Any]:
    """Coerce raw quoteStats to a plain dict."""
    if not isinstance(raw, dict):
        return {}
    return {
        "totalVolume": _safe_int(raw.get("totalVolume")),
        "totalAmount": _safe_float(raw.get("totalAmount")),
        "upCount": _safe_int(raw.get("upCount")),
        "downCount": _safe_int(raw.get("downCount")),
        "flatCount": _safe_int(raw.get("flatCount")),
    }


# ═════════════════════════════════════════════════════════════════════════════
# ThemeMappingProvider
# ═════════════════════════════════════════════════════════════════════════════


class ThemeMappingProvider:
    """Map stock codes to theme/plate lists via the MongoDB theme repository.

    The repository object must expose a ``get_stock_themes(code: str) -> dict``
    method whose return value contains a ``"themes"`` key with a list of
    ``{"id": str, "name": str}`` dicts.
    """

    def __init__(self, theme_repository: Any) -> None:
        self._repo = theme_repository

    # ── public API ──────────────────────────────────────────────────────

    def collect(
        self,
        codes: list[str],
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[dict[str, list[str]], SourceHealth]:
        """Map *codes* to their theme name lists.

        Returns ``({code: [theme_name, ...]}, health)``.

        Per-code errors are tolerated and produce empty theme lists for that
        code.  The provider only reports ``ok=False`` when **every** requested
        code failed (or a catastrophic error occurred outside the per-code
        loop).
        """
        start = time.monotonic()
        if not codes:
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="theme_mapping",
                ok=True,
                latency_ms=latency_ms,
                row_count=0,
                captured_at=_iso_now(),
            )
            return {}, health

        try:
            result: dict[str, list[str]] = {}
            failed_count = 0
            first_error: str = ""
            for code in codes:
                key = str(code).strip()
                if not key:
                    result[key or code] = []
                    failed_count += 1
                    continue
                try:
                    stock_data = self._repo.get_stock_themes(key)
                    theme_items = stock_data.get("themes", [])
                    if isinstance(theme_items, list):
                        themes = [
                            str(t.get("name") or t.get("id") or "")
                            for t in theme_items
                            if isinstance(t, dict)
                        ]
                    else:
                        themes = []
                    result[key] = themes
                except Exception as exc:
                    result[key] = []
                    failed_count += 1
                    if not first_error:
                        first_error = str(exc)

            latency_ms = int((time.monotonic() - start) * 1000)
            all_failed = failed_count == len(codes) and len(codes) > 0
            error_msg = ""
            if all_failed:
                error_msg = first_error or "all requested codes failed to map themes"
            health = SourceHealth(
                source="theme_mapping",
                ok=not all_failed,
                latency_ms=latency_ms,
                row_count=len(result) - failed_count,
                error=error_msg,
                captured_at=_iso_now(),
            )
            return result, health

        except Exception as exc:
            # Catastrophic error outside the per-code loop (e.g. repo init failed)
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="theme_mapping",
                ok=False,
                latency_ms=latency_ms,
                error=str(exc),
                captured_at=_iso_now(),
            )
            return {}, health


# ═════════════════════════════════════════════════════════════════════════════
# Collector orchestrator
# ═════════════════════════════════════════════════════════════════════════════


def collect_market_context(
    providers: list[Any],
    codes: list[str],
    *,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
) -> MarketDataContext:
    """Collect data from all *providers* and assemble a ``MarketDataContext``.

    Each provider is called with either ``.collect(timeout_ms=...)`` or
    ``.collect(codes, timeout_ms=...)`` depending on its type.  The
    ``MarketDataContext`` aggregates all returned data rows and health
    records.

    Provider routing
    ----------------
    * ``ProxyHotlistProvider`` → ``ctx.stocks``
    * ``BridgeQuoteProvider``   → ``ctx.quotes``, ``ctx.depth``, ``ctx.market_meta``
    * ``ThemeMappingProvider``  → ``ctx.themes``

    Unknown provider types are silently ignored.
    """
    ctx = MarketDataContext()

    for provider in providers:
        try:
            if isinstance(provider, ProxyHotlistProvider):
                rows, health = provider.collect(timeout_ms=timeout_ms)
                ctx.stocks.extend(rows)
                ctx.source_health.append(health)

            elif isinstance(provider, BridgeQuoteProvider):
                data, health = provider.collect(codes, timeout_ms=timeout_ms)
                if isinstance(data, dict):
                    ctx.quotes.extend(data.get("quotes") or [])
                    ctx.depth.extend(data.get("depth") or [])
                    if data.get("market_meta"):
                        ctx.market_meta.update(data["market_meta"])
                ctx.source_health.append(health)

            elif isinstance(provider, ThemeMappingProvider):
                themes, health = provider.collect(codes, timeout_ms=timeout_ms)
                if isinstance(themes, dict):
                    ctx.themes.update(themes)
                ctx.source_health.append(health)

        except Exception as exc:
            # A provider raised unexpectedly — record it as a failed health
            health = SourceHealth(
                source=getattr(provider, "__class__", type(provider)).__name__,
                ok=False,
                error=str(exc),
                captured_at=_iso_now(),
            )
            ctx.source_health.append(health)

    return ctx
