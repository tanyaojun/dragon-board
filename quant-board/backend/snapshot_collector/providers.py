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


def _http_post_json(url: str, timeout_s: float, payload: Any = None) -> Any:
    """Perform a POST request and return the parsed JSON body.

    When *payload* is provided it is sent as a JSON-encoded body.
    Raises ``urllib.error.URLError`` or ``ValueError`` on failure.
    """
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
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
            # Eastmoney endpoint uses POST
            body = _http_post_json(url, timeout_s)
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
        """Convert raw proxy response to a list of stock row dicts.

        Supports both legacy field names (c, r, n, p, zdf, etc.) and
        eastmoney native field names (sc, rk).
        """
        items = _extract_items(body)
        rows: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Eastmoney uses "sc", legacy format uses "c"/"code"
            code = str(item.get("sc") or item.get("c") or item.get("code") or "").strip()
            # Strip exchange prefix: SZ000630 → 000630, SH603993 → 603993
            if len(code) >= 8 and code[:2] in ("SZ", "SH", "BJ"):
                code = code[2:]
            if not code:
                continue
            row: dict[str, Any] = {
                "code": code,
                "name": str(item.get("n") or item.get("name") or code),
                "rank": _safe_int(item.get("rk") or item.get("r") or item.get("rank"), len(rows) + 1),
                "price": _safe_float(item.get("p") or item.get("price")),
                "pctChange": _safe_float(item.get("zdf") or item.get("pctChange")),
                "volume": _safe_int(item.get("cjl") or item.get("volume")),
                "amount": _safe_float(item.get("cje") or item.get("amount")),
                "turnover": _safe_float(item.get("hsl") or item.get("turnover")),
                "heat": _safe_float(item.get("hot") or item.get("heat")),
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
# ProxyQuoteProvider
# ═════════════════════════════════════════════════════════════════════════════


class ProxyQuoteProvider:
    """Fetch real-time quotes from the proxy-server EastMoney endpoint.

    Calls ``GET /api/quotes/eastmoney?codes=...`` and returns a dict
    containing ``quotes``, ``depth``, ``money_flow``, and ``market_meta``
    — the same shape as ``BridgeQuoteProvider`` for drop-in compatibility.

    Depth data is not available from this source and will always be an
    empty list.  Money flow fields are extracted from the same EastMoney
    response rows (f62/f66/f69/f184).  Medium net inflow is derived as
    main − super_large − large − small.
    """

    def __init__(self, base_url: str = _DEFAULT_PROXY_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")

    # ── public API ──────────────────────────────────────────────────────

    def collect(
        self,
        codes: list[str] | None = None,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[dict[str, Any], SourceHealth]:
        """Fetch quotes for *codes* from proxy-server EastMoney endpoint.

        Returns ``(data, health)`` where *data* has the same shape as
        ``BridgeQuoteProvider.collect()`` so it can be routed identically
        in ``collect_market_context``.
        """
        start = time.monotonic()
        filtered = [str(c).strip() for c in (codes or []) if str(c).strip()]
        if not filtered:
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="quote_proxy",
                ok=True,
                latency_ms=latency_ms,
                row_count=0,
                captured_at=_iso_now(),
            )
            return {"quotes": [], "depth": [], "money_flow": [], "market_meta": {}}, health

        try:
            codes_param = ",".join(filtered)
            url = (
                f"{self._base_url}/api/quotes/eastmoney"
                f"?codes={urllib.request.quote(codes_param, safe='')}"
            )
            timeout_s = timeout_ms / 1000.0
            body = _http_get_json(url, timeout_s)
            degraded_error = _proxy_degraded_error(body)
            if degraded_error:
                latency_ms = int((time.monotonic() - start) * 1000)
                health = SourceHealth(
                    source="quote_proxy",
                    ok=False,
                    latency_ms=latency_ms,
                    error=degraded_error,
                    captured_at=_iso_now(),
                )
                return {"quotes": [], "depth": [], "money_flow": [], "market_meta": {}}, health

            rows = _extract_eastmoney_diff(body)
            quotes = _eastmoney_rows_to_quotes(rows)
            money_flow = _eastmoney_rows_to_money_flow(rows)

            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="quote_proxy",
                ok=True,
                latency_ms=latency_ms,
                row_count=max(len(quotes), len(money_flow)),
                captured_at=_iso_now(),
            )
            data = {
                "quotes": quotes,
                "depth": [],
                "money_flow": money_flow,
                "market_meta": {},
            }
            return data, health

        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="quote_proxy",
                ok=False,
                latency_ms=latency_ms,
                error=str(exc),
                captured_at=_iso_now(),
            )
            return {"quotes": [], "depth": [], "money_flow": [], "market_meta": {}}, health


def _proxy_degraded_error(body: Any) -> str:
    """Return a proxy degraded/error message, or empty string for healthy bodies."""
    if not isinstance(body, dict):
        return ""
    if body.get("ok") is False or body.get("degraded") is True:
        return str(
            body.get("error")
            or body.get("message")
            or body.get("source")
            or "proxy returned degraded response"
        )
    return ""


def _extract_eastmoney_diff(body: Any) -> list[dict[str, Any]]:
    """Extract the ``diff`` list from an EastMoney proxy response."""
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict):
            diff = data.get("diff")
            if isinstance(diff, list):
                return diff
    return []


def _eastmoney_rows_to_quotes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map EastMoney field-coded rows to the internal quote dict format."""
    quotes: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        code = str(item.get("f12") or "").strip()
        if not code:
            continue
        quotes.append({
            "code": code,
            "price": _safe_float(item.get("f2")),
            "pctChange": _safe_float(item.get("f3")),
            "volume": _safe_int(item.get("f6")),
            "amount": _safe_float(item.get("f5")),
            "turnover": _safe_float(item.get("f8")),
            "pe": _safe_float(item.get("f9")),
            "totalMarketValue": _safe_float(item.get("f20")),
        })
    return quotes


def _eastmoney_rows_to_money_flow(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map EastMoney fund-flow fields to the internal money_flow dict format.

    ``mediumNetInflow`` is derived because EastMoney does not expose it directly.
    """
    flows: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        code = str(item.get("f12") or "").strip()
        if not code:
            continue
        main = _safe_float(item.get("f62"))
        super_large = _safe_float(item.get("f66"))
        large = _safe_float(item.get("f69"))
        small = _safe_float(item.get("f184"))
        medium = main - super_large - large - small
        flows.append({
            "code": code,
            "mainNetInflow": main,
            "superLargeNetInflow": super_large,
            "largeNetInflow": large,
            "mediumNetInflow": medium,
            "smallNetInflow": small,
            "moneyFlowSource": "estimated_l1",
            "moneyFlowEstimated": True,
            "capitalFlowConfidence": "low",
        })
    return flows


# ═════════════════════════════════════════════════════════════════════════════
# BridgeQuoteProvider
# ═════════════════════════════════════════════════════════════════════════════


class BridgeQuoteProvider:
    """Fetch real-time quote snapshot from the python-bridge.

    Calls ``GET /api/quotes/snapshot?codes=...`` (direct mode) or
    ``GET /api/quotes/snapshot`` (pool mode, after ``set_pool()`` was
    called) and returns a dict containing ``quotes``, ``depth``,
    ``money_flow``, and ``market_meta``.

    Phase 2 adds a backend subscription pool so the collector can maintain
    a persistent set of stocks on the bridge without passing codes on every
    request.
    """

    # SourceHealth error attribute key for staleness warnings.
    STALE_KEY = "quote_stale"

    def __init__(
        self,
        base_url: str = _DEFAULT_BRIDGE_BASE_URL,
        *,
        pool_staleness_ms: int = 30000,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._pool_staleness_ms = pool_staleness_ms

    # ── public API ──────────────────────────────────────────────────────

    def set_pool(
        self,
        codes: list[str],
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> dict[str, Any]:
        """Register *codes* as the backend subscription pool on the bridge.

        Calls ``POST /api/quotes/subscriptions``.  Returns a dict with
        ``ok``, ``count``, and any error information.
        """
        try:
            url = f"{self._base_url}/api/quotes/subscriptions"
            payload = json.dumps({"codes": codes}).encode("utf-8")
            timeout_s = timeout_ms / 1000.0
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return {
                "ok": body.get("ok", False),
                "count": body.get("count", 0),
                "codes": body.get("codes", []),
                "setAt": body.get("setAt", 0),
            }
        except Exception as exc:
            return {"ok": False, "count": 0, "error": str(exc)}

    def collect(
        self,
        codes: list[str] | None = None,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        use_pool: bool = False,
    ) -> tuple[dict[str, Any], SourceHealth]:
        """Fetch bridge snapshot for *codes* (or the pool when *use_pool*).

        Returns ``(data, health)`` where *data* is::

            {
                "quotes": [...],
                "depth": [...],
                "money_flow": [...],
                "market_meta": {...},
            }

        When *use_pool* is True the *codes* parameter is ignored and the
        request is sent without a ``codes`` query parameter, letting the
        bridge return cached pool data.

        When the bridge response includes ``"pooled": true`` and the
        ``poolRefreshedAt`` timestamp is older than *pool_staleness_ms*,
        a ``quote_stale`` warning key is added to ``SourceHealth.error``.

        Never raises — errors are captured in the returned ``SourceHealth``.
        """
        start = time.monotonic()
        if not use_pool and not codes:
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
            if use_pool:
                # Pool mode: no codes param, bridge returns cached pool data
                url = f"{self._base_url}/api/quotes/snapshot"
            else:
                codes_param = ",".join(str(c).strip() for c in codes if str(c).strip())
                if not codes_param:
                    raise ValueError("no valid codes after filtering")
                url = (
                    f"{self._base_url}/api/quotes/snapshot"
                    f"?codes={urllib.request.quote(codes_param, safe='')}"
                )

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

            # Phase 2: staleness detection for pool-based responses
            error_msg = ""
            if use_pool and body.get("pooled") is True:
                pool_refreshed_at = body.get("poolRefreshedAt", 0)
                now = int(time.time() * 1000)
                if pool_refreshed_at and (now - pool_refreshed_at) > self._pool_staleness_ms:
                    age_ms = now - pool_refreshed_at
                    error_msg = (
                        f"{self.STALE_KEY}: pool data {age_ms}ms old "
                        f"(refreshedAt={pool_refreshed_at}, staleThresholdMs={self._pool_staleness_ms})"
                    )

            health = SourceHealth(
                source="quote_bridge",
                ok=True,
                latency_ms=latency_ms,
                row_count=row_count,
                error=error_msg,
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
    active_codes = [str(code).strip() for code in codes if str(code).strip()]

    for provider in providers:
        try:
            if isinstance(provider, ProxyHotlistProvider):
                rows, health = provider.collect(timeout_ms=timeout_ms)
                ctx.stocks.extend(rows)
                ctx.source_health.append(health)
                if not active_codes:
                    active_codes = [
                        str(row.get("code") or "").strip()
                        for row in rows
                        if isinstance(row, dict) and str(row.get("code") or "").strip()
                    ]

            elif isinstance(provider, (BridgeQuoteProvider, ProxyQuoteProvider)):
                data, health = provider.collect(active_codes, timeout_ms=timeout_ms)
                if isinstance(data, dict):
                    ctx.quotes.extend(data.get("quotes") or [])
                    ctx.depth.extend(data.get("depth") or [])
                    ctx.money_flow.extend(data.get("money_flow") or [])
                    if data.get("market_meta"):
                        ctx.market_meta.update(data["market_meta"])
                ctx.source_health.append(health)

            elif isinstance(provider, ThemeMappingProvider):
                themes, health = provider.collect(active_codes, timeout_ms=timeout_ms)
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
