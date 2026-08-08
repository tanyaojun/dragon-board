from __future__ import annotations
from typing import Any
from backend.core.backtest import (
    DEFAULT_TRADE_CONFIG,
    V5_LIFECYCLE_FUSION_TRADE_DEFAULTS,
)
from backend.data.ingest.quality_gate import evaluate_snapshot_quality



DEFAULT_BACKTEST_STRATEGY_CONFIG = {
    "momentumPeriods": [3, 5, 8, 13, 21],
    "macdFast": 21,
    "macdSlow": 34,
    "macdSignal": 13,
}


V5_LIFECYCLE_FUSION_STRATEGY = "ranktrend_early_big_move_v3_lifecycle_fusion"


def trade_defaults_for_strategy(strategy_name: str) -> dict[str, Any]:
    defaults = dict(DEFAULT_TRADE_CONFIG)
    if strategy_name == V5_LIFECYCLE_FUSION_STRATEGY:
        defaults.update(V5_LIFECYCLE_FUSION_TRADE_DEFAULTS)
    return defaults


BACKTEST_COMPARE_METRICS = {
    "totalReturn",
    "realizedReturn",
    "maxDrawdown",
    "sharpe",
    "winRate",
    "totalTrades",
    "tradeCount",
    "profitFactor",
    "openPositionCount",
}


FATAL_QUALITY_STATS = (
    "invalidCaptureMode",
    "duplicateSnapshotId",
    "nonMonotonicTimestamp",
    "missingCoreFieldCount",
)


def camel_get(payload: dict[str, Any], snake: str, camel: str | None = None, default: Any = None) -> Any:
    if snake in payload:
        return payload[snake]
    camel_key = camel or snake.split("_")[0] + "".join(part.title() for part in snake.split("_")[1:])
    return payload.get(camel_key, default)


MONEY_FLOW_QUALITY_FIELDS = (
    "capitalFlowSource",
    "capital_flow_source",
    "capitalFlowConfidence",
    "capital_flow_confidence",
    "moneyFlowSource",
    "money_flow_source",
    "moneyFlowEstimated",
    "money_flow_estimated",
)


CROSS_MARKET_ZERO_PRICE_PREFIXES = ("001", "003", "006", "007", "009")


def _stock_rows_for_quality(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for frame in frames:
        snapshot_id = frame.get("snapshotId")
        for stock in frame.get("stocks", []):
            row: dict[str, Any] = {"snapshotId": snapshot_id}
            if isinstance(stock, dict):
                row["snapshotId"] = stock.get("snapshotId") or snapshot_id
                for key in ("rowId", "row_id", "code", *MONEY_FLOW_QUALITY_FIELDS):
                    if key in stock:
                        row[key] = stock.get(key)
            rows.append(row)
    return rows


def _price_is_positive(value: Any) -> bool:
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _stock_code(value: Any) -> str:
    code = str(value or "").strip()
    return code.zfill(6) if code.isdigit() else code


def _raw_stock_code(value: Any) -> str:
    return str(value or "").strip()


def _has_zero_quote_shape(stock: dict[str, Any]) -> bool:
    return all(not _price_is_positive(stock.get(key)) for key in ("price", "change", "volume", "turnover"))


def _is_cross_market_zero_price_stock(stock: dict[str, Any], a_share_codes: set[str] | None = None) -> bool:
    if not _has_zero_quote_shape(stock):
        return False
    raw_code = _raw_stock_code(stock.get("code"))
    if raw_code == "000000":
        return True
    if not raw_code.isdigit():
        return False
    if a_share_codes is None:
        return raw_code.startswith(("007", "009"))
    if len(raw_code) != 6:
        return raw_code.startswith(CROSS_MARKET_ZERO_PRICE_PREFIXES)
    return raw_code not in a_share_codes and raw_code.startswith(CROSS_MARKET_ZERO_PRICE_PREFIXES)


def _load_a_share_codes(repo: Any) -> set[str] | None:
    database = getattr(repo, "db", None)
    if database is None:
        return None
    try:
        rows = database["stock_names"].find(
            {"active": True, "market": {"$in": ["SH", "SZ", "BJ"]}},
            {"code": 1},
        )
        return {_stock_code(row.get("code")) for row in rows if row.get("code")}
    except Exception:
        return None


def _prepare_frames_for_backtest(frames: list[dict[str, Any]], snapshot_type: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gate = evaluate_snapshot_quality(frames, _stock_rows_for_quality(frames), snapshot_type=snapshot_type)
    gate_dict = gate.to_dict()
    if gate.passed:
        return frames, gate_dict

    stats = gate.stats or {}
    has_empty_hotlist = int(stats.get("emptyHotlistCount") or 0) > 0
    has_other_fatal = any(int(stats.get(key) or 0) > 0 for key in FATAL_QUALITY_STATS)
    non_empty_frames = [frame for frame in frames if frame.get("stocks")]
    min_snapshot_count = int(stats.get("minSnapshotCount") or 2)

    if not has_empty_hotlist or has_other_fatal or len(non_empty_frames) < min_snapshot_count:
        raise ValueError({"qualityGate": gate_dict})

    dropped_frames = [frame for frame in frames if not frame.get("stocks")]
    gate_dict["runtimeFilter"] = {
        "reason": "empty_hotlist_snapshots_excluded",
        "sourceTargetFrames": len(frames),
        "usableTargetFrames": len(non_empty_frames),
        "droppedEmptyHotlistSnapshots": len(dropped_frames),
        "droppedSnapshotIds": [str(frame.get("snapshotId") or "") for frame in dropped_frames[:50]],
    }
    return non_empty_frames, gate_dict


def _ensure_runtime_filtered_frames_usable(frames: list[dict[str, Any]], quality_gate: dict[str, Any]) -> None:
    stats = quality_gate.get("stats") if isinstance(quality_gate.get("stats"), dict) else {}
    min_snapshot_count = int(stats.get("minSnapshotCount") or 2)
    usable_frames = [frame for frame in frames if frame.get("stocks")]
    if len(usable_frames) >= min_snapshot_count:
        return
    failed_gate = {
        **quality_gate,
        "passed": False,
        "severity": "fail",
        "issues": [
            *(quality_gate.get("issues") or []),
            f"runtime filters left usable snapshots below minimum {min_snapshot_count}: {len(usable_frames)}",
        ],
    }
    raise ValueError({"qualityGate": failed_gate})
