from __future__ import annotations

import importlib
import os
from typing import Any

from .provider import (
    Depth10Book,
    DepthLevel,
    L2ProviderStatus,
    L2Snapshot,
    MoneyFlowFrame,
    TickTrade,
    now_ms,
)


def normalize_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return ""
    return digits[-6:]


def to_qmt_code(code: str) -> str:
    text = str(code or "").strip().upper()
    if "." in text and text.endswith((".SZ", ".SH")):
        return text
    digits = normalize_code(text)
    if not digits:
        return ""
    suffix = "SH" if digits.startswith("6") else "SZ"
    return f"{digits}.{suffix}"


def to_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number else 0.0


def to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def is_qmt_connection_error(text: str) -> bool:
    lower = text.lower()
    return (
        "connect" in lower
        or "not running" in lower
        or "无法连接" in text
        or "xtquant服务" in text
        or "qmt-" in lower
    )


def frame_to_records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        try:
            return list(value.to_dict("records"))
        except Exception:
            return []
    if isinstance(value, dict):
        rows: list[dict[str, Any]] = []
        for key, item in value.items():
            if hasattr(item, "to_dict"):
                rows.extend({"code": key, **row} for row in frame_to_records(item))
            elif isinstance(item, dict):
                rows.append({"code": key, **item})
            elif isinstance(item, list):
                rows.extend([{"code": key, **row} for row in item if isinstance(row, dict)])
        return rows
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def pick(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    lower = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        value = lower.get(key.lower())
        if value not in (None, ""):
            return value
    return default


def extract_side(row: dict[str, Any], side: str) -> list[DepthLevel]:
    price_keys = [f"{side}Price", f"{side}_price", f"{side}Px", f"{side}_px"]
    volume_keys = [f"{side}Volume", f"{side}_volume", f"{side}Vol", f"{side}_vol"]
    levels: list[DepthLevel] = []
    for index in range(1, 11):
        price = to_float(pick(row, *(f"{key}{index}" for key in price_keys)))
        volume = to_float(pick(row, *(f"{key}{index}" for key in volume_keys)))
        if price > 0 or volume > 0:
            levels.append(DepthLevel(price=price, volume=volume))
    return levels


def normalize_depth(row: dict[str, Any]) -> Depth10Book | None:
    code = normalize_code(pick(row, "code", "stock_code", "instrument_id", "symbol"))
    if not code:
        return None
    bids = extract_side(row, "bid")
    asks = extract_side(row, "ask")
    if not bids and not asks:
        return None
    return Depth10Book(
        code=code,
        bids=bids,
        asks=asks,
        sourceTs=to_int(pick(row, "time", "sourceTs", "timestamp")),
        depthLevelCount=min(len(bids), len(asks)),
    )


def normalize_tick(row: dict[str, Any]) -> TickTrade | None:
    code = normalize_code(pick(row, "code", "stock_code", "instrument_id", "symbol"))
    if not code:
        return None
    price = to_float(pick(row, "price", "lastPrice", "trade_price"))
    volume = to_float(pick(row, "volume", "tradeVolume", "trade_volume"))
    if price <= 0 and volume <= 0:
        return None
    amount = to_float(pick(row, "amount", "tradeAmount", "trade_amount"))
    if amount <= 0 and price > 0 and volume > 0:
        amount = price * volume * 100
    side_raw = str(pick(row, "side", "tradeType", "bsFlag", default="")).lower()
    side = "buy" if side_raw in {"b", "buy", "1"} else "sell" if side_raw in {"s", "sell", "2"} else "neutral"
    return TickTrade(
        code=code,
        price=price,
        volume=volume,
        amount=amount,
        side=side,
        tradeTime=str(pick(row, "tradeTime", "time", "datetime", default="")),
        sourceTs=to_int(pick(row, "time", "sourceTs", "timestamp")),
    )


def normalize_money_flow(row: dict[str, Any]) -> MoneyFlowFrame | None:
    code = normalize_code(pick(row, "code", "stock_code", "instrument_id", "symbol"))
    if not code:
        return None
    known_values = [
        pick(row, "zlje", "mainNet", "main_net", "mainNetAmount"),
        pick(row, "zljzb", "mainRatio", "main_net_ratio"),
        pick(row, "cddje", "superNet", "super_net", "superNetAmount"),
        pick(row, "cddjzb", "superRatio", "super_net_ratio"),
        pick(row, "activeAmount", "active_amount", "amount"),
    ]
    if all(value in (None, "") for value in known_values):
        return None
    return MoneyFlowFrame(
        code=code,
        zlje=to_float(known_values[0]),
        zljzb=to_float(known_values[1]),
        cddje=to_float(known_values[2]),
        cddjzb=to_float(known_values[3]),
        activeAmount=to_float(known_values[4]),
        sourceTs=to_int(pick(row, "time", "sourceTs", "timestamp")),
    )


def has_l2_candidate_rows(*raw_values: Any) -> bool:
    return any(frame_to_records(value) for value in raw_values)


class QmtL2Provider:
    def __init__(self, xtdata: Any | None = None, require_official: bool | None = None) -> None:
        self.provider = "qmt"
        self.xtdata = xtdata
        self.import_error = ""
        self.subscribed: set[str] = set()
        self.require_official = (
            os.getenv("QMT_L2_REQUIRE_OFFICIAL", "1").strip().lower() not in {"0", "false", "off", "no"}
            if require_official is None
            else require_official
        )
        if self.xtdata is None:
            try:
                self.xtdata = importlib.import_module("xtquant.xtdata")
            except Exception as error:
                self.import_error = str(error)

    def status(self, status: str, message: str, fallback_active: bool = True) -> L2ProviderStatus:
        return L2ProviderStatus(
            provider=self.provider,
            enabled=not bool(self.import_error),
            status=status,
            message=message,
            lastProbeTs=now_ms(),
            subscribedCount=len(self.subscribed),
            fallbackActive=fallback_active,
        )

    def probe(self, codes: list[str]) -> L2ProviderStatus:
        if self.import_error:
            return self.status("missing_xtquant", self.import_error)
        snapshot = self.poll_snapshot(codes)
        if snapshot.status and snapshot.status.status in {"missing_xtquant", "qmt_not_running", "unknown_error"}:
            return snapshot.status
        if snapshot.depth or snapshot.money_flow or snapshot.ticks:
            depth_count = max((item.depthLevelCount for item in snapshot.depth), default=0)
            return L2ProviderStatus(
                provider=self.provider,
                enabled=True,
                status="ok",
                message="QMT L2 data available",
                lastProbeTs=now_ms(),
                lastDataTs=now_ms(),
                subscribedCount=len(codes),
                depthLevelCount=depth_count,
                fallbackActive=False,
            )
        if snapshot.status and snapshot.status.status == "field_mismatch":
            return snapshot.status
        return self.status("empty_l2_data", "QMT returned no Level2 rows")

    def subscribe(self, codes: list[str]) -> L2ProviderStatus:
        if self.import_error:
            return self.status("missing_xtquant", self.import_error)
        qmt_codes = [to_qmt_code(code) for code in codes if to_qmt_code(code)]
        for code in qmt_codes:
            if code in self.subscribed:
                continue
            try:
                self.xtdata.subscribe_quote(code, period="l2quoteaux", count=1)
                self.xtdata.subscribe_quote(code, period="l2transactioncount", count=1)
                self.subscribed.add(code)
            except Exception as error:
                text = str(error)
                if is_qmt_connection_error(text):
                    return self.status("qmt_not_running", text)
                if "permission" in text.lower() or "right" in text.lower() or "level" in text.lower():
                    return self.status("permission_denied", text)
                return self.status("unknown_error", text)
        return self.status("subscribed", "QMT L2 subscribed", fallback_active=False)

    def poll_snapshot(self, codes: list[str]) -> L2Snapshot:
        if self.import_error:
            status = self.status("missing_xtquant", self.import_error)
            return L2Snapshot(status=status)
        qmt_codes = [to_qmt_code(code) for code in codes if to_qmt_code(code)]
        try:
            depth_raw = self.xtdata.get_market_data_ex([], qmt_codes, period="l2quoteaux", count=1)
            money_raw = self.xtdata.get_market_data_ex([], qmt_codes, period="l2transactioncount", count=1)
        except Exception as error:
            text = str(error)
            if is_qmt_connection_error(text):
                status = self.status("qmt_not_running", text)
            elif "permission" in text.lower() or "right" in text.lower() or "level" in text.lower():
                status = self.status("permission_denied", text)
            else:
                status = self.status("unknown_error", text)
            return L2Snapshot(status=status)

        depth_rows = frame_to_records(depth_raw)
        money_rows = frame_to_records(money_raw)
        depth = [item for item in (normalize_depth(row) for row in depth_rows) if item]
        money_flow = [
            item for item in (normalize_money_flow(row) for row in money_rows) if item
        ]
        ticks = {}
        for tick in [item for item in (normalize_tick(row) for row in money_rows) if item]:
            ticks.setdefault(tick.code, []).append(tick.to_dict())

        depth_count = max((item.depthLevelCount for item in depth), default=0)
        has_raw_l2_rows = bool(depth_rows or money_rows)
        mapped_any = bool(depth or money_flow or ticks)
        status_name = (
            "ok"
            if mapped_any
            else "field_mismatch"
            if has_raw_l2_rows
            else "empty_l2_data"
        )
        message = (
            "QMT L2 data available"
            if mapped_any
            else "QMT returned Level2 rows but no known fields matched"
            if has_raw_l2_rows
            else "QMT returned no Level2 rows"
        )
        status = L2ProviderStatus(
            provider=self.provider,
            enabled=True,
            status=status_name,
            message=message,
            lastProbeTs=now_ms(),
            lastDataTs=now_ms() if mapped_any else 0,
            subscribedCount=len(qmt_codes),
            depthLevelCount=depth_count,
            fallbackActive=not mapped_any,
        )
        return L2Snapshot(
            depth=depth,
            ticks=[{"code": code, "items": items} for code, items in ticks.items()],
            money_flow=money_flow,
            status=status,
        )

    def close(self) -> None:
        self.subscribed.clear()
