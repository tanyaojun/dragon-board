"""指数行情源：本地行情桥（TDX）——指数不再依赖 akshare。

2026-10-19 复盘（用户指令「akshare 被风控限流了，所有经过 akshare 的都要找替代源，
先把指数改成行情桥」）：原 ``indices.MarketOverviewService`` 走
``akshare.stock_zh_index_spot_sina``，新浪限流后盘中/盘外一律挂死（实测每槽吃满 30s
预算，采集帧的 ``indices`` 直接为空，11:30 之后所有帧均缺指数）。

现在的权威源是本地行情桥（``python-bridge``，TDX 主站直连）：

- ``GET http://127.0.0.1:8765/api/quotes/index-snapshot?codes=sh000001,sz399001,...``
- 不经过任何第三方 HTTP，不受 akshare 限流影响；桥自身已有服务器池/延迟优选/重连；
- 指数必须带市场前缀（``sh000001`` 上证指数 vs ``sz000001`` 平安银行），桥侧
  ``normalize_index_code`` 负责保留前缀，这里只透传。

返回结构对齐原 akshare 口径（``MarketOverviewService._normalize`` 的 item 形状），
因此 ``providers.build_server_indices`` 等消费方零改动：code/name/price/change/
changePct/prevClose/open/high/low/volume/amount。
"""

from __future__ import annotations

from typing import Any, Iterable

import httpx

# frame.indices 需要的键位（sh/hs300/zz500/zz1000 + 两市成交额）加展示用指数。
# 顺序固定，便于排障时比对清单。
DEFAULT_INDEX_CODES: tuple[str, ...] = (
    "sh000001",  # 上证指数
    "sz399001",  # 深证成指
    "sh000300",  # 沪深300
    "sh000905",  # 中证500
    "sh000852",  # 中证1000
    "sz399006",  # 创业板指
    "sh000688",  # 科创50
)

# TDX 五档行情不返回指数名称（只有价格/量额），名称在此静态补齐供展示；
# 未登记的代码不带 name，不猜。
INDEX_DISPLAY_NAMES: dict[str, str] = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sh000300": "沪深300",
    "sh000905": "中证500",
    "sh000852": "中证1000",
    "sz399006": "创业板指",
    "sh000688": "科创50",
    "sh000016": "上证50",
    "sz399005": "中小100",
}


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize_bridge_items(
    quotes: Iterable[Any],
    *,
    code_filter: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """行情桥 ``quotes`` → 原 akshare 口径的 items（纯函数，可单测）。"""
    wanted = {str(code).strip().lower() for code in code_filter} if code_filter else None
    items: list[dict[str, Any]] = []
    for row in quotes or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip().lower()
        if not code:
            continue
        if wanted is not None and code not in wanted:
            continue
        price = _number(row.get("lastPrice"))
        prev_close = _number(row.get("preClose"))
        change = _number(row.get("changeAmount"))
        if change == 0.0 and price > 0 and prev_close > 0:
            change = round(price - prev_close, 4)
        change_pct = _number(row.get("changePct"))
        if change_pct == 0.0 and prev_close > 0:
            change_pct = round(change / prev_close * 100, 4)
        item: dict[str, Any] = {
            "code": code,
            "name": INDEX_DISPLAY_NAMES.get(code, ""),
            "price": price,
            "change": change,
            "changePct": change_pct,
            "prevClose": prev_close,
            "open": _number(row.get("open")),
            "high": _number(row.get("high")),
            "low": _number(row.get("low")),
            "volume": _number(row.get("volume")),
            "amount": _number(row.get("amount")),
        }
        if not item["name"]:
            item.pop("name")
        items.append(item)
    return items


async def fetch_index_items(
    *,
    base_url: str,
    codes: Iterable[str] | None = None,
    timeout_s: float = 3.0,
    client: Any = None,
) -> list[dict[str, Any]]:
    """从行情桥取指数 items；空返回按失败抛错（不伪造"成功但没数据"）。

    抛 ``httpx.HTTPError`` / ``RuntimeError`` / ``asyncio.TimeoutError``，由调用方
    ``MarketOverviewService`` 统一转成 last-good + ``stale`` / ``errorCode``（fail-visible）。
    """
    requested = [str(code).strip().lower() for code in (codes or DEFAULT_INDEX_CODES)]
    requested = [code for code in requested if code]
    url = f"{str(base_url).rstrip('/')}/api/quotes/index-snapshot"
    params = {"codes": ",".join(requested)}
    timeout = max(0.05, float(timeout_s))

    if client is not None:
        response = await client.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    else:
        async with httpx.AsyncClient(timeout=timeout) as owned:
            response = await owned.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

    if not isinstance(payload, dict):
        raise RuntimeError("index bridge snapshot returned non-object payload")
    quotes = payload.get("quotes")
    items = normalize_bridge_items(quotes if isinstance(quotes, list) else [], code_filter=requested)
    if not payload.get("ok") or not items:
        detail = str(payload.get("error") or "").strip() or "no rows"
        raise RuntimeError(f"index bridge snapshot unusable: {detail}")
    return items


__all__ = [
    "DEFAULT_INDEX_CODES",
    "INDEX_DISPLAY_NAMES",
    "fetch_index_items",
    "normalize_bridge_items",
]