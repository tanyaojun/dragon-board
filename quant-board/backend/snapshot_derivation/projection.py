"""Snapshot ingest payload builder.

Converts a ``SnapshotSlot`` and ``MarketDataContext`` into a bundle dict
accepted by ``backend.data.snapshot_ingest_normalizer.normalize_snapshot_ingest()``.
"""

from __future__ import annotations

import math
from typing import Any

from backend.snapshot_collector.models import MarketDataContext, SnapshotSlot


SECTOR_FACTOR_FIELDS = (
    "heatScore",
    # heatLevel（0-100 rank 百分位相对分）2026-09 落库迁移放行：collector 已透传，
    # 白名单是派生层落库 sector row 的唯一字段准入。
    "heatLevel",
    "momentumScore",
    "breadthScore",
    "fundScore",
    "leadershipScore",
    "correlationScore",
    "crowdingRisk",
    "persistenceScore",
    "rotationState",
    "change",
    "mainNetInflow",
    "volumeRatio",
    "ztCount",
    "leaderCount",
    "themeQualityFlags",
    "metadata",
)

# 股票-题材角色权重与阈值：与 theme_momentum._role_for 的 ROLE_WEIGHTS 语义对齐。
# collector/theme_heat 按涨跌幅计算并落库，供 mainTheme 匹配时被直接信任。
THEME_ROLE_WEIGHTS = {
    "leader": 1.0,
    "core": 0.82,
    "follower": 0.62,
    "independent": 0.38,
    "noise": 0.15,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if math.isfinite(numeric) else default


def _derive_theme_role_fields(stock: dict[str, Any]) -> tuple[str, float, str]:
    """按涨跌幅派生题材角色/贡献/领涨状态：涨停附近=leader、5%=core、>0=follower、<=-5%=noise。"""
    change = _safe_float(stock.get("change"))
    if change >= 9.5:
        role = "leader"
    elif change >= 5.0:
        role = "core"
    elif change > 0:
        role = "follower"
    elif change <= -5.0:
        role = "noise"
    else:
        role = "independent"
    contribution = round(THEME_ROLE_WEIGHTS[role] * 60.0, 2)
    lead_status = "领涨龙头" if role == "leader" else ""
    return role, contribution, lead_status


def _normalize_theme_label(value: Any) -> str:
    name = str(value or "").strip()
    for suffix in ("概念板块", "概念", "板块"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def _derive_pre_close_from_price_change(row: dict[str, Any]) -> None:
    """桥挂降级兜底：由 price + pctChange 反推昨收（缺失时）。"""
    if row.get("preClose") is None:
        price = _safe_float(row.get("price"))
        change = _safe_float(
            row.get("change") if row.get("change") is not None else row.get("pctChange")
        )
        if price > 0 and change is not None and change != -100:
            row["preClose"] = round(price / (1 + change / 100), 4)
    # 反推得到昨收后，补上此前因缺昨收而跳过的涨跌停价
    if row.get("preClose") is not None and not row.get("limitUpPrice") and not row.get("limitDownPrice"):
        derived = _derive_limit_prices(
            row["preClose"],
            str(row.get("code") or ""),
            str(row.get("name") or ""),
        )
        if derived is not None:
            row["limitUpPrice"], row["limitDownPrice"] = derived


def _limit_ratio_for(code: Any, name: Any = "") -> float:
    """A股涨跌停幅度：创业板/科创板 20%、北交所 30%、其余主板 10%（含主板 ST）。

    2026-09 起主板 ST 涨跌幅已改为 ±10%，全市场按所属板块阈值，无 ST 特判
    （与前端 src/utils/common.ts StockUtils 口径一致）。
    """
    value = str(code or "").strip()
    if value.isdigit():
        value = value.zfill(6)
    if value.startswith(("688", "689")):
        return 0.20
    if value.startswith("30"):
        return 0.20
    if value.startswith(("43", "8", "92")):
        return 0.30
    return 0.10


def _derive_limit_prices(
    pre_close: Any,
    code: Any,
    name: Any = "",
) -> tuple[float, float] | None:
    """按交易所规则从昨收派生涨停/跌停价；无效昨收返回 None（保持缺失）。"""
    if (
        isinstance(pre_close, bool)
        or not isinstance(pre_close, (int, float))
        or not math.isfinite(float(pre_close))
        or float(pre_close) <= 0
    ):
        return None
    ratio = _limit_ratio_for(code, name)
    base = float(pre_close)
    return round(base * (1 + ratio), 2), round(base * (1 - ratio), 2)


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) is not None:
            return row.get(key)
    return None


def _depth_book(depth: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    raw_bids = depth.get("bids")
    raw_asks = depth.get("asks")
    if isinstance(raw_bids, list) or isinstance(raw_asks, list):
        bid = _depth_side_from_book(raw_bids)
        ask = _depth_side_from_book(raw_asks)
        return {"bid": bid, "ask": ask} if bid or ask else {}

    bid: list[dict[str, Any]] = []
    ask: list[dict[str, Any]] = []
    for level in range(1, 6):
        bid_price = _first_present(depth, f"bid{level}Price", f"bidPrice{level}")
        bid_volume = _first_present(depth, f"bid{level}Volume", f"bidVol{level}")
        ask_price = _first_present(depth, f"ask{level}Price", f"askPrice{level}")
        ask_volume = _first_present(depth, f"ask{level}Volume", f"askVol{level}")
        if bid_price is not None or bid_volume is not None:
            bid.append({"price": bid_price or 0, "volume": bid_volume or 0})
        if ask_price is not None or ask_volume is not None:
            ask.append({"price": ask_price or 0, "volume": ask_volume or 0})
    return {"bid": bid, "ask": ask} if bid or ask else {}


def _depth_side_from_book(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw[:10]:
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        volume = item.get("volume")
        if price is not None or volume is not None:
            result.append({"price": price or 0, "volume": volume or 0})
    return result


def _derive_amplitude(row: dict[str, Any]) -> float | None:
    high = row.get("high")
    low = row.get("low")
    pre_close = row.get("preClose")
    if not isinstance(high, (int, float)) or not isinstance(low, (int, float)):
        return None
    if not isinstance(pre_close, (int, float)) or pre_close <= 0 or high < low:
        return None
    return round((high - low) / pre_close * 100, 4)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _remove_unavailable_placeholder_zeros(row: dict[str, Any]) -> None:
    volume_ratio_meta = row.get("volumeRatioMeta")
    volume_ratio_source = (
        str(volume_ratio_meta.get("source") or "").strip().lower()
        if isinstance(volume_ratio_meta, dict)
        else ""
    )
    if _finite_number(row.get("volumeRatio")) == 0 and volume_ratio_source == "unavailable":
        row.pop("volumeRatio", None)

    money_flow_source = str(
        row.get("moneyFlowSource") or row.get("capitalFlowSource") or ""
    ).strip().lower()
    if _finite_number(row.get("zlje")) == 0 and money_flow_source in {"", "unknown", "unavailable"}:
        row.pop("zlje", None)
        row.pop("zljzb", None)


def _enrich_stock_rows_from_quotes(
    stock_rows: list[dict[str, Any]],
    quotes: list[dict[str, Any]],
    depth: list[dict[str, Any]],
    money_flow: list[dict[str, Any]],
) -> None:
    """Merge quote and money-flow data into stock rows in-place.

    Only fields that are missing or zero in the stock row are filled from
    the quote.  New fields (totalMarketValue, moneyFlow) are always added
    when available.
    """
    if not quotes and not depth and not money_flow:
        return

    quote_by_code: dict[str, dict[str, Any]] = {}
    for q in quotes:
        code = str(q.get("code") or "").strip()
        if code:
            quote_by_code[code] = {
                **quote_by_code.get(code, {}),
                **{key: value for key, value in q.items() if value is not None},
            }

    flow_by_code: dict[str, dict[str, Any]] = {}
    for mf in money_flow:
        code = str(mf.get("code") or "").strip()
        if code:
            flow_by_code[code] = mf

    depth_by_code: dict[str, dict[str, Any]] = {}
    for item in depth:
        code = str(item.get("code") or "").strip()
        if code:
            depth_by_code[code] = item

    for row in stock_rows:
        code = str(row.get("code") or "").strip()
        if not code:
            continue

        q = quote_by_code.get(code)
        if q:
            quote_name = str(q.get("name") or "").strip()
            current_name = str(row.get("name") or "").strip()
            if quote_name and (not current_name or current_name == code):
                row["name"] = quote_name

            # Override hotlist values with more accurate quote values when
            # the hotlist value is missing or zero.
            for field in ("price", "pctChange", "volume", "amount", "turnover"):
                if not row.get(field):
                    val = q.get(field)
                    if val:
                        row[field] = val
            if row.get("pctChange") is not None:
                row["change"] = row["pctChange"]
            if row.get("amount") is not None:
                row["turnover"] = row["amount"]
            turnover_rate = q.get("turnover")
            if turnover_rate is not None and not row.get("turnoverRate"):
                row["turnoverRate"] = turnover_rate
            volume_ratio = q.get("volumeRatio")
            if volume_ratio is not None and not row.get("volumeRatio"):
                row["volumeRatio"] = volume_ratio
                q_meta = q.get("volumeRatioMeta")
                if isinstance(q_meta, dict) and not row.get("volumeRatioMeta"):
                    row["volumeRatioMeta"] = q_meta
                elif not row.get("volumeRatioMeta"):
                    # quote 层无来源标记：此处 volumeRatio 来自腾讯 f10 兜底，派生层补标记
                    row["volumeRatioMeta"] = {"source": "tencent_f10", "status": "available"}
            # 涨速：python-bridge 计算（compute_quote_speed，60s 窗口），stock row 缺失时填补
            speed = q.get("speed")
            if speed is not None and not row.get("speed"):
                row["speed"] = speed
            for field in ("high", "low", "preClose", "open"):
                value = q.get(field)
                if value is not None and not row.get(field):
                    row[field] = value
            # RankTrend/回测兼容别名：highPrice/lowPrice
            if row.get("high") is not None and not row.get("highPrice"):
                row["highPrice"] = row["high"]
            if row.get("low") is not None and not row.get("lowPrice"):
                row["lowPrice"] = row["low"]
            amplitude = _derive_amplitude(row)
            if amplitude is not None and not row.get("amplitude"):
                row["amplitude"] = amplitude

            # Fields not provided by the hotlist at all
            # PE ratio
            pe = q.get("pe")
            if pe is not None:
                row["pe"] = pe
            # Total market value (from EastMoney f20)
            tmv = q.get("totalMarketValue")
            if tmv is not None:
                row["totalMarketValue"] = tmv
                row["totalMV"] = tmv
            cir_mv = q.get("cirMV")
            if cir_mv is not None:
                row["cirMV"] = cir_mv
            pb = q.get("pb")
            if pb is not None:
                row["pb"] = pb
            for field in ("limitUpPrice", "limitDownPrice"):
                value = q.get(field)
                if value is not None and not row.get(field):
                    row[field] = value
            if row.get("price") is not None and not row.get("lastTradePrice"):
                row["lastTradePrice"] = row["price"]
            if row.get("volume") is not None and not row.get("lastTradeVolume"):
                row["lastTradeVolume"] = row["volume"]

        mf = flow_by_code.get(code)
        if mf:
            row["moneyFlow"] = {k: v for k, v in mf.items() if k != "code"}
            zlje = _finite_number(mf.get("mainNetInflow"))
            if zlje is not None:
                row["zlje"] = zlje
                explicit_ratio = _finite_number(mf.get("mainNetRatio"))
                turnover = _finite_number(row.get("turnover") or row.get("amount"))
                if explicit_ratio is not None:
                    row["zljzb"] = explicit_ratio
                elif turnover is not None and turnover != 0:
                    row["zljzb"] = round(zlje / turnover * 100, 6)
            source = str(mf.get("moneyFlowSource") or "unknown")
            estimated = bool(mf.get("moneyFlowEstimated", source == "estimated_l1"))
            row["moneyFlowSource"] = source
            row["moneyFlowEstimated"] = estimated
            row["capitalFlowSource"] = str(mf.get("capitalFlowSource") or source)
            row["capitalFlowConfidence"] = str(
                mf.get("capitalFlowConfidence") or ("low" if estimated else "unknown")
            )

        d = depth_by_code.get(code)
        if d:
            book = _depth_book(d)
            first_bid = book.get("bid", [{}])[0] if book.get("bid") else {}
            first_ask = book.get("ask", [{}])[0] if book.get("ask") else {}
            bid1_price = _first_present(d, "bid1Price", "bidPrice1") or first_bid.get("price")
            bid1_volume = _first_present(d, "bid1Volume", "bidVol1") or first_bid.get("volume")
            ask1_price = _first_present(d, "ask1Price", "askPrice1") or first_ask.get("price")
            ask1_volume = _first_present(d, "ask1Volume", "askVol1") or first_ask.get("volume")
            if bid1_price is not None:
                row["bid1Price"] = bid1_price
            if bid1_volume is not None:
                row["bid1Volume"] = bid1_volume
            if ask1_price is not None:
                row["ask1Price"] = ask1_price
            if ask1_volume is not None:
                row["ask1Volume"] = ask1_volume
            if book:
                row["depth10"] = book

        # 涨跌停价无上游来源时，按交易所规则从昨收派生（回测撮合约束所需）
        if not row.get("limitUpPrice") and not row.get("limitDownPrice"):
            pre_close = row.get("preClose")
            if pre_close is not None:
                derived = _derive_limit_prices(pre_close, code, str(row.get("name") or ""))
                if derived is not None:
                    row["limitUpPrice"], row["limitDownPrice"] = derived


def build_ingest_payload(
    slot: SnapshotSlot,
    market_context: MarketDataContext,
    *,
    dataset_id: str = "dragonboard_backend_shadow",
    source: str = "quantboard_backend_collector",
    capture_mode: str = "real_time",
    quality_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal ingest payload dict from a slot and market context.

    The returned dict is designed to be used as the ``bundle`` field of
    ``backend.data.schemas.SnapshotIngestRequest``.  It contains ``items``
    (records), ``frames``, ``stockRows``, ``sectorRows``, and collector
    metadata.

    Parameters
    ----------
    slot:
        The target snapshot slot (snapshot_type, trading_date, slot_time, timestamp_ms).
    market_context:
        Raw material collected from providers (stocks, sectors, quotes, depth,
        themes, source_health, market_meta).
    dataset_id:
        Target dataset identifier.  Defaults to the shadow dataset so the
        collector does not accidentally write production data.
    source:
        Value written into every ``source`` field.  Distinguishes backend
        collector snapshots from browser-produced ones.
    capture_mode:
        ``"real_time"`` when captured within the slot window, ``"delayed"``
        otherwise.
    quality_flags:
        Optional list of quality-warning tags recorded alongside the payload.
    """
    snapshot_id = slot.snapshot_id
    rank_provenance = next(
        (
            health.details.get("rankProvenance")
            for health in market_context.source_health
            if isinstance(health.details, dict)
            and isinstance(health.details.get("rankProvenance"), dict)
        ),
        None,
    )
    snapshot_context = (
        market_context.snapshot_context
        if isinstance(market_context.snapshot_context, dict)
        else {}
    )
    market_data = (
        snapshot_context.get("marketData")
        if isinstance(snapshot_context.get("marketData"), dict)
        else market_context.market_meta
    )
    sentiment = snapshot_context.get("breathData")
    indices = market_data.get("indices") if isinstance(market_data, dict) else None
    money_flow_summary = market_data.get("moneyFlow") if isinstance(market_data, dict) else None
    limit_summary = {
        "continuousBoards": market_data.get("limitData"),
        "zhaban": market_data.get("zhaban"),
        "yesterdayZt": market_data.get("yesterdayLimit"),
        "thsPools": market_data.get("thsLimitUpPools"),
    } if isinstance(market_data, dict) else None
    rotation_summary = snapshot_context.get("rotationAnalysis")
    normalized_hotlist = [
        dict(stock) if isinstance(stock, dict) else stock
        for stock in market_context.stocks
    ]
    for stock in normalized_hotlist:
        if isinstance(stock, dict):
            _remove_unavailable_placeholder_zeros(stock)

    # ── Record (item) ─────────────────────────────────────────────────────
    record = {
        "id": snapshot_id,
        "snapshotId": snapshot_id,
        "type": slot.snapshot_type,
        "tradingDate": slot.trading_date,
        "slotTime": slot.slot_time,
        "timestamp": slot.timestamp_ms,
        "displayKey": snapshot_id,
        "captureMode": capture_mode,
        "source": source,
        "payload": {
            "hotlist": normalized_hotlist,
            "sectors": market_context.sectors,
            **snapshot_context,
            "marketStats": market_data,
            "sentiment": sentiment,
            "moneyFlow": money_flow_summary,
            "indices": indices,
            "limitSummary": limit_summary,
            "rotationSummary": rotation_summary,
            "metadata": {"rankProvenance": rank_provenance} if rank_provenance else {},
        },
    }

    # ── Frame ──────────────────────────────────────────────────────────────
    frame = {
        "id": snapshot_id,
        "snapshotId": snapshot_id,
        "type": slot.snapshot_type,
        "tradingDate": slot.trading_date,
        "slotTime": slot.slot_time,
        "timestamp": slot.timestamp_ms,
        "displayKey": snapshot_id,
        "captureMode": capture_mode,
        "source": source,
        "marketStats": market_data,
        "sentiment": sentiment,
        "moneyFlow": money_flow_summary,
        "indices": indices,
        "limitSummary": limit_summary,
        "rotationSummary": rotation_summary,
        "metadata": {"rankProvenance": rank_provenance} if rank_provenance else {},
        "stockRowCount": 0,
        "sectorRowCount": len(market_context.sectors),
    }

    # ── Stock rows ─────────────────────────────────────────────────────────
    stock_rows: list[dict[str, Any]] = []
    sector_by_name = {
        _normalize_theme_label(sector.get("entityName") or sector.get("name") or ""): sector
        for sector in market_context.sectors
        if isinstance(sector, dict)
    }
    for stock in normalized_hotlist:
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("code") or "").strip()
        if not code:
            continue

        row: dict[str, Any] = {
            **stock,
            "id": f"{snapshot_id}:{code}",
            "snapshotId": snapshot_id,
            "type": slot.snapshot_type,
            "tradingDate": slot.trading_date,
            "slotTime": slot.slot_time,
            "timestamp": slot.timestamp_ms,
            "captureMode": capture_mode,
            "source": source,
            "code": code,
            "name": stock.get("name", code),
            "rank": int(float(stock.get("rank") or 0)),
        }

        # Optional camelCase fields carried through when present
        for field in (
            "price",
            "pctChange",
            "volume",
            "amount",
            "turnover",
            "turnoverRate",
            "heat",
            "avgRankNum",
            "avgRank",
            "compRank",
            "platforms",
            "emRank",
            "thsRank",
            "kplRank",
            "tdxRank",
            "xqRank",
            "clsRank",
            "tgbRank",
            "dzhRank",
        ):
            if field in stock:
                row[field] = stock[field]

        if "pctChange" in row:
            row["change"] = row["pctChange"]
        if "amount" in row:
            row["turnover"] = row["amount"]
        if "turnoverRate" not in row and "turnover" in stock:
            row["turnoverRate"] = stock["turnover"]
        if "heat" in row:
            row["hotness"] = row["heat"]

        # Themes from the market_context.themes dict keyed by code
        themes = market_context.themes.get(code)
        if themes is not None:
            row["themes"] = themes
        elif "themes" in stock:
            row["themes"] = stock["themes"]
        row_themes = row.get("themes")
        if isinstance(row_themes, list) and row_themes:
            first_theme = row_themes[0]
            if isinstance(first_theme, dict):
                theme_name = str(first_theme.get("name") or first_theme.get("id") or "").strip()
            else:
                theme_name = str(first_theme or "").strip()
            if theme_name:
                row["sectorLabel"] = theme_name
                row.setdefault("mainTheme", theme_name)

        theme_role, theme_contribution, lead_status = _derive_theme_role_fields(row)
        row.setdefault("themeRole", theme_role)
        row.setdefault("themeContribution", theme_contribution)
        row.setdefault("leadStatus", lead_status)

        # 题材热度/拥挤风险：由该股主题材的 sector factor 派生（无匹配则保持缺失）
        main_theme = row.get("mainTheme")
        if main_theme:
            sector = sector_by_name.get(_normalize_theme_label(main_theme))
            if sector is not None:
                heat = sector.get("heatScore")
                if heat is not None:
                    row.setdefault("themeHeat", heat)
                crowding = _safe_float(sector.get("crowdingRisk"))
                if crowding >= 70:
                    row.setdefault("themeRiskFlags", ["题材拥挤风险高"])

        limit_up = market_context.limit_up.get(code)
        if isinstance(limit_up, dict):
            for field in (
                "limitUpPool",
                "reason",
                "firstZtTime",
                "lastZtTime",
                "boardHeight",
                "highDays",
                "fengdan",
                "maxFengdan",
                "speed",
                "turnoverRate",
                "maxDrawdown",
            ):
                if field in limit_up and limit_up[field] is not None:
                    row[field] = limit_up[field]

        stock_rows.append(row)

    # Enrich stock rows with quote-derived fields
    _enrich_stock_rows_from_quotes(
        stock_rows,
        market_context.quotes,
        market_context.depth,
        market_context.money_flow,
    )
    for row in stock_rows:
        _remove_unavailable_placeholder_zeros(row)
        _derive_pre_close_from_price_change(row)
        # 涨跌停状态标签：限价已知后补 leadStatus（回测 _limit_state 依赖）
        price = _safe_float(row.get("price"))
        limit_up = row.get("limitUpPrice")
        limit_down = row.get("limitDownPrice")
        if price > 0 and limit_up and price >= float(limit_up) * 0.999:
            row["leadStatus"] = "涨停"
        elif price > 0 and limit_down and price <= float(limit_down) * 1.001:
            row["leadStatus"] = "跌停"

    stock_rows.sort(key=lambda r: int(r.get("rank") or 999999))
    frame["stockRowCount"] = len(stock_rows)

    # ── Sector rows ────────────────────────────────────────────────────────
    sector_rows: list[dict[str, Any]] = []
    for sector in market_context.sectors:
        if not isinstance(sector, dict):
            continue
        key = (
            str(sector.get("code") or sector.get("name") or "").strip()
            or f"sector_{len(sector_rows)}"
        )
        entity_type = str(sector.get("entityType") or "sector")

        row = {
            "id": f"{snapshot_id}:{entity_type}:{key}",
            "snapshotId": snapshot_id,
            "type": slot.snapshot_type,
            "tradingDate": slot.trading_date,
            "slotTime": slot.slot_time,
            "timestamp": slot.timestamp_ms,
            "captureMode": capture_mode,
            "source": source,
            "entityType": entity_type,
            "entityKey": str(key),
            "entityName": sector.get("name", str(key)),
            "rank": int(float(sector.get("rank") or len(sector_rows) + 1)),
        }
        for field in SECTOR_FACTOR_FIELDS:
            if field in sector:
                row[field] = sector[field]
        sector_rows.append(row)

    existing_sector_keys = {
        (str(row.get("entityType") or "sector"), str(row.get("entityKey") or ""))
        for row in sector_rows
    }
    context_sector_groups = (
        ("hot_theme", snapshot_context.get("hotThemes")),
        ("hot_theme", snapshot_context.get("themeHeatFactors")),
        (
            "rotation_main_line",
            rotation_summary.get("mainLines") if isinstance(rotation_summary, dict) else None,
        ),
    )
    for entity_type, items in context_sector_groups:
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(
                item.get("id")
                or item.get("themeId")
                or item.get("code")
                or item.get("themeName")
                or item.get("name")
                or ""
            ).strip()
            if not key or (entity_type, key) in existing_sector_keys:
                continue
            name = str(item.get("themeName") or item.get("name") or key)
            sector_rows.append({
                **item,
                "id": f"{snapshot_id}:{entity_type}:{key}",
                "snapshotId": snapshot_id,
                "type": slot.snapshot_type,
                "tradingDate": slot.trading_date,
                "slotTime": slot.slot_time,
                "timestamp": slot.timestamp_ms,
                "captureMode": capture_mode,
                "source": source,
                "entityType": entity_type,
                "entityKey": key,
                "entityName": name,
                "rank": int(float(item.get("rank") or len(sector_rows) + 1)),
            })
            existing_sector_keys.add((entity_type, key))

    frame["sectorRowCount"] = len(sector_rows)

    # ── Bundle ─────────────────────────────────────────────────────────────
    result: dict[str, Any] = {
        "items": [record],
        "frames": [frame],
        "stockRows": stock_rows,
        "sectorRows": sector_rows,
        "datasetId": dataset_id,
        "snapshotId": snapshot_id,
        "captureMode": capture_mode,
        "source": source,
    }

    if quality_flags:
        result["qualityFlags"] = quality_flags

    return result
