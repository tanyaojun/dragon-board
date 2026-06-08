from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from backend.data.json_codec import loads_json_field


FUSION_STRATEGY_NAME = "ranktrend_early_big_move_v3_lifecycle_fusion"
DEFAULT_SNAPSHOT_TYPE = "half_hour"
VALID_SNAPSHOT_TYPES = {"half_hour", "quarter_hour"}
VALID_LIFECYCLE_ACTIONS = {"allow", "caution", "veto", "exit_watch"}
VALID_CANDIDATE_TIERS = {"A_MAIN", "B_IGNITION", "C_CROWDED", "D_EXIT_RISK", "N_NEUTRAL"}
TRIGGER_TIERS = {"A_MAIN", "B_IGNITION"}
CHINA_TZ = timezone(timedelta(hours=8))


@dataclass
class FusionLifecycleSegment:
    stock_code: str
    stock_name: str
    entry_signal_snapshot_id: str
    entry_snapshot_id: str
    entry_time: int | None
    entry_trading_date: str | None
    entry_price: float | None
    exit_signal_snapshot_id: str | None = None
    exit_snapshot_id: str | None = None
    exit_time: int | None = None
    exit_trading_date: str | None = None
    exit_price: float | None = None
    holding_bars: int | None = None
    strategy_return_pct: float | None = None
    entry_reason: str | None = None
    exit_reason: str | None = None

    @property
    def is_closed(self) -> bool:
        return bool(self.exit_snapshot_id or self.exit_signal_snapshot_id or self.exit_time is not None)


class FusionStrategyProjectionService:
    def __init__(self, repo: Any):
        self.repo = repo

    def build_backtest_projection_response(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return None

        strategy_name = str(getattr(run, "strategy_name", "") or "").strip()
        if strategy_name != FUSION_STRATEGY_NAME:
            raise UnsupportedFusionStrategyError(strategy_name=strategy_name)

        request_payload = _loads_json_maybe(getattr(run, "request_json", {}))
        result_payload = _loads_json_maybe(getattr(run, "result_json", {}))
        trade_simulation = result_payload.get("tradeSimulation") if isinstance(result_payload.get("tradeSimulation"), dict) else {}

        snapshot_type = _normalize_snapshot_type(
            getattr(run, "snapshot_type", None)
            or request_payload.get("snapshotType")
            or request_payload.get("snapshot_type")
        )
        signals = _ensure_dict_rows(result_payload.get("signals"))
        used_repo_signal_fallback = False
        if not signals and hasattr(self.repo, "get_backtest_signals"):
            signals = _ensure_dict_rows(self.repo.get_backtest_signals(run_id, limit=None, offset=0))
            used_repo_signal_fallback = bool(signals)

        trades = _ensure_dict_rows(trade_simulation.get("roundTripTrades"))
        if not trades:
            trades = _ensure_dict_rows(trade_simulation.get("trades"))
        if not trades and used_repo_signal_fallback and hasattr(self.repo, "get_backtest_trades"):
            trades = _ensure_dict_rows(self.repo.get_backtest_trades(run_id, limit=None, offset=0))

        trade_events = _ensure_dict_rows(trade_simulation.get("tradeEvents"))
        open_positions = _ensure_dict_rows(trade_simulation.get("openPositions"))
        max_positions = _extract_max_positions(request_payload, trade_simulation)

        segments = self._build_segments(trades=trades, trade_events=trade_events, open_positions=open_positions)
        rows = self._build_rows(signals=signals, segments=segments, snapshot_type=snapshot_type, max_positions=max_positions)

        return {
            "ok": True,
            "runId": getattr(run, "id", run_id),
            "datasetId": getattr(run, "dataset_id", ""),
            "snapshotType": snapshot_type,
            "strategyName": getattr(run, "strategy_name", "") or FUSION_STRATEGY_NAME,
            "strategyVersion": getattr(run, "strategy_version", "") or "0.1.0",
            "configHash": getattr(run, "config_hash", ""),
            "randomSeed": getattr(run, "random_seed", 0),
            "count": len(rows),
            "rows": rows,
        }

    def _build_segments(
        self,
        *,
        trades: list[dict[str, Any]],
        trade_events: list[dict[str, Any]],
        open_positions: list[dict[str, Any]],
    ) -> list[FusionLifecycleSegment]:
        buy_reasons: dict[tuple[str, str], str] = {}
        sell_reasons: dict[tuple[str, str], str] = {}
        for event in trade_events:
            code = str(event.get("code") or "")
            signal_snapshot_id = str(event.get("signalSnapshotId") or event.get("snapshotId") or "")
            if not code or not signal_snapshot_id:
                continue
            action = str(event.get("action") or "").lower()
            reason = str(event.get("reason") or "").strip()
            if action == "buy" and reason:
                buy_reasons[(code, signal_snapshot_id)] = reason
            if action == "sell" and reason:
                sell_reasons[(code, signal_snapshot_id)] = reason

        grouped: dict[tuple[str, str], FusionLifecycleSegment] = {}
        for trade in sorted(trades, key=_trade_sort_key):
            code = str(trade.get("code") or "")
            if not code:
                continue
            entry_signal_snapshot_id = str(trade.get("entrySignalSnapshotId") or trade.get("entrySnapshotId") or "")
            if not entry_signal_snapshot_id:
                continue
            key = (code, entry_signal_snapshot_id)
            segment = grouped.get(key)
            if segment is None:
                segment = FusionLifecycleSegment(
                    stock_code=code,
                    stock_name=str(trade.get("name") or code),
                    entry_signal_snapshot_id=entry_signal_snapshot_id,
                    entry_snapshot_id=str(trade.get("entrySnapshotId") or entry_signal_snapshot_id),
                    entry_time=_to_int(trade.get("entryTime")),
                    entry_trading_date=_to_str_or_none(trade.get("entryTradingDate")),
                    entry_price=_to_float(trade.get("entryPrice")),
                    entry_reason=buy_reasons.get((code, entry_signal_snapshot_id)),
                )
                grouped[key] = segment

            exit_signal_snapshot_id = _to_str_or_none(trade.get("exitSignalSnapshotId") or trade.get("exitSnapshotId"))
            exit_snapshot_id = _to_str_or_none(trade.get("exitSnapshotId") or trade.get("exitSignalSnapshotId"))
            exit_time = _to_int(trade.get("exitTime"))
            if _segment_exit_is_later(segment, exit_time, exit_signal_snapshot_id):
                segment.exit_signal_snapshot_id = exit_signal_snapshot_id
                segment.exit_snapshot_id = exit_snapshot_id
                segment.exit_time = exit_time
                segment.exit_trading_date = _to_str_or_none(trade.get("exitTradingDate"))
                segment.exit_price = _to_float(trade.get("exitPrice"))
                segment.holding_bars = _to_int(trade.get("holdingBars"))
                segment.strategy_return_pct = _to_float(trade.get("netReturn"))
                segment.exit_reason = (
                    sell_reasons.get((code, exit_signal_snapshot_id or ""))
                    or _to_str_or_none(trade.get("reason"))
                )

        for position in open_positions:
            code = str(position.get("code") or "")
            entry_snapshot_id = str(position.get("entrySnapshotId") or "")
            if not code or not entry_snapshot_id:
                continue
            key = (code, entry_snapshot_id)
            segment = grouped.get(key)
            if segment is None:
                grouped[key] = FusionLifecycleSegment(
                    stock_code=code,
                    stock_name=str(position.get("name") or code),
                    entry_signal_snapshot_id=entry_snapshot_id,
                    entry_snapshot_id=entry_snapshot_id,
                    entry_time=_to_int(position.get("entryTime")),
                    entry_trading_date=_to_str_or_none(position.get("entryTradingDate")),
                    entry_price=_to_float(position.get("entryPrice")),
                    holding_bars=_to_int(position.get("holdingBars")),
                    entry_reason=_to_str_or_none(position.get("entryReason")),
                )
                continue

            segment.stock_name = str(position.get("name") or segment.stock_name or code)
            segment.entry_time = _coalesce(_to_int(position.get("entryTime")), segment.entry_time)
            segment.entry_trading_date = _coalesce(
                _to_str_or_none(position.get("entryTradingDate")),
                segment.entry_trading_date,
            )
            segment.entry_price = _coalesce(_to_float(position.get("entryPrice")), segment.entry_price)
            segment.holding_bars = _coalesce(_to_int(position.get("holdingBars")), segment.holding_bars)
            segment.entry_reason = _coalesce(_to_str_or_none(position.get("entryReason")), segment.entry_reason)
            segment.exit_signal_snapshot_id = None
            segment.exit_snapshot_id = None
            segment.exit_time = None
            segment.exit_trading_date = None
            segment.exit_price = None
            segment.strategy_return_pct = None
            segment.exit_reason = None

        return sorted(grouped.values(), key=lambda item: (item.entry_time or 0, item.stock_code, item.entry_signal_snapshot_id))

    def _build_rows(
        self,
        *,
        signals: list[dict[str, Any]],
        segments: list[FusionLifecycleSegment],
        snapshot_type: str,
        max_positions: int | None,
    ) -> list[dict[str, Any]]:
        ordered_signals = sorted(
            (
                {
                    **signal,
                    "__index": index,
                }
                for index, signal in enumerate(signals)
                if str(signal.get("code") or "").strip()
            ),
            key=_signal_sort_key,
        )
        signal_index_by_snapshot = {
            str(signal.get("snapshotId") or ""): idx
            for idx, signal in enumerate(ordered_signals)
            if signal.get("snapshotId")
        }

        rows: list[dict[str, Any]] = []
        for signal in ordered_signals:
            code = str(signal.get("code") or "")
            snapshot_id = str(signal.get("snapshotId") or "")
            candidate_tier = _normalize_candidate_tier(signal.get("candidateTier"))
            lifecycle_action = _normalize_lifecycle_action(signal)
            segment = self._match_segment(signal=signal, segments=segments)
            strategy_state = self._resolve_strategy_state(
                signal=signal,
                segment=segment,
                candidate_tier=candidate_tier,
                lifecycle_action=lifecycle_action,
            )
            if strategy_state == "idle":
                continue

            frame_time = _coerce_frame_time(signal)
            trigger_at = frame_time
            strategy_entry_at = None
            strategy_exit_at = None
            holding_bars = None
            entry_reason = None
            exit_reason = None
            strategy_entry_price = None
            strategy_exit_price = None
            strategy_return_pct = None
            t_plus_one_unlocked = None

            if segment is not None:
                trigger_at = _format_timestamp(segment.entry_time) or frame_time
                strategy_entry_at = _format_timestamp(segment.entry_time)
                strategy_entry_price = segment.entry_price
                entry_reason = segment.entry_reason
                holding_bars = self._resolve_holding_bars(
                    signal=signal,
                    segment=segment,
                    signal_index_by_snapshot=signal_index_by_snapshot,
                    strategy_state=strategy_state,
                )
                t_plus_one_unlocked = _compute_t_plus_one(
                    entry_trading_date=segment.entry_trading_date,
                    current_trading_date=_to_str_or_none(signal.get("tradingDate")),
                    state=strategy_state,
                )
                if strategy_state == "closed":
                    strategy_exit_at = _format_timestamp(segment.exit_time)
                    strategy_exit_price = segment.exit_price
                    strategy_return_pct = segment.strategy_return_pct
                    exit_reason = segment.exit_reason

            rows.append(
                {
                    "stockCode": code,
                    "stockName": str(signal.get("name") or code),
                    "strategyName": FUSION_STRATEGY_NAME,
                    "snapshotType": snapshot_type,
                    "tradingDate": _to_str_or_none(signal.get("tradingDate")) or "",
                    "snapshotId": snapshot_id,
                    "frameTime": frame_time,
                    "projectionSource": "backtest",
                    "strategyState": strategy_state,
                    "candidateTier": candidate_tier,
                    "lifecycleAction": lifecycle_action,
                    "triggerAt": trigger_at,
                    "strategyEntryAt": strategy_entry_at,
                    "strategyExitAt": strategy_exit_at,
                    "holdingBars": holding_bars,
                    "slotIndex": None,
                    "maxPositions": max_positions,
                    "tPlusOneUnlocked": t_plus_one_unlocked,
                    "entryReason": entry_reason,
                    "exitReason": exit_reason,
                    "strategyEntryPrice": strategy_entry_price,
                    "strategyExitPrice": strategy_exit_price,
                    "strategyReturnPct": strategy_return_pct,
                    "executionOverlay": None,
                }
            )

        return rows

    def _match_segment(
        self,
        *,
        signal: dict[str, Any],
        segments: list[FusionLifecycleSegment],
    ) -> FusionLifecycleSegment | None:
        code = str(signal.get("code") or "")
        snapshot_id = str(signal.get("snapshotId") or "")
        timestamp = _signal_timestamp(signal)
        candidates = [segment for segment in segments if segment.stock_code == code]
        candidates.sort(key=lambda item: (item.entry_time or 0, item.entry_signal_snapshot_id), reverse=True)

        for segment in candidates:
            if snapshot_id and snapshot_id in {
                segment.entry_signal_snapshot_id,
                segment.entry_snapshot_id,
                segment.exit_signal_snapshot_id,
                segment.exit_snapshot_id,
            }:
                return segment
            if timestamp is None or segment.entry_time is None:
                continue
            if timestamp < segment.entry_time:
                continue
            if segment.exit_time is not None and timestamp > segment.exit_time:
                continue
            return segment
        return None

    @staticmethod
    def _resolve_strategy_state(
        *,
        signal: dict[str, Any],
        segment: FusionLifecycleSegment | None,
        candidate_tier: str,
        lifecycle_action: str,
    ) -> str:
        final_signal = _extract_final_signal(signal)
        snapshot_id = str(signal.get("snapshotId") or "")

        if segment is not None:
            if segment.is_closed and snapshot_id in {
                segment.exit_signal_snapshot_id,
                segment.exit_snapshot_id,
            }:
                return "closed"
            if lifecycle_action == "exit_watch" or final_signal == "sell" or candidate_tier == "D_EXIT_RISK":
                return "exit_signaled"
            return "active_holding"

        if candidate_tier in TRIGGER_TIERS and lifecycle_action != "veto":
            return "triggered_wait_entry"
        return "idle"

    @staticmethod
    def _resolve_holding_bars(
        *,
        signal: dict[str, Any],
        segment: FusionLifecycleSegment,
        signal_index_by_snapshot: dict[str, int],
        strategy_state: str,
    ) -> int | None:
        if strategy_state == "closed":
            return segment.holding_bars

        entry_key = segment.entry_signal_snapshot_id or segment.entry_snapshot_id
        current_key = str(signal.get("snapshotId") or "")
        if entry_key in signal_index_by_snapshot and current_key in signal_index_by_snapshot:
            return max(0, signal_index_by_snapshot[current_key] - signal_index_by_snapshot[entry_key])
        return segment.holding_bars


class UnsupportedFusionStrategyError(ValueError):
    def __init__(self, *, strategy_name: str | None):
        super().__init__(strategy_name or "")
        self.strategy_name = strategy_name or ""


def _loads_json_maybe(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return loads_json_field(value, {})
    return {}


def _ensure_dict_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_snapshot_type(value: Any) -> str:
    snapshot_type = str(value or DEFAULT_SNAPSHOT_TYPE).strip() or DEFAULT_SNAPSHOT_TYPE
    if snapshot_type in VALID_SNAPSHOT_TYPES:
        return snapshot_type
    return DEFAULT_SNAPSHOT_TYPE


def _normalize_candidate_tier(value: Any) -> str:
    tier = str(value or "N_NEUTRAL").strip() or "N_NEUTRAL"
    return tier if tier in VALID_CANDIDATE_TIERS else "N_NEUTRAL"


def _normalize_lifecycle_action(signal: dict[str, Any]) -> str:
    cycle = signal.get("rankTrend") if isinstance(signal.get("rankTrend"), dict) else {}
    cycle = cycle.get("cycle") if isinstance(cycle.get("cycle"), dict) else {}
    decision = cycle.get("decision") if isinstance(cycle.get("decision"), dict) else {}
    action = str(decision.get("action") or "").strip()
    if action in VALID_LIFECYCLE_ACTIONS:
        return action

    candidate_tier = _normalize_candidate_tier(signal.get("candidateTier"))
    if candidate_tier == "D_EXIT_RISK":
        return "exit_watch"
    if candidate_tier == "C_CROWDED":
        return "caution"
    if candidate_tier in TRIGGER_TIERS:
        return "allow"
    return "caution"


def _extract_final_signal(signal: dict[str, Any]) -> str:
    rank_trend = signal.get("rankTrend") if isinstance(signal.get("rankTrend"), dict) else {}
    decision = rank_trend.get("decision") if isinstance(rank_trend.get("decision"), dict) else {}
    final = decision.get("final") if isinstance(decision.get("final"), dict) else {}
    return str(final.get("signal") or signal.get("finalSignal") or signal.get("signal") or "hold").strip()


def _signal_timestamp(signal: dict[str, Any]) -> int | None:
    timestamp = _to_int(signal.get("timestamp"))
    if timestamp is not None:
        return timestamp
    fallback = _frame_time_from_fields(signal)
    if fallback is None:
        return None
    return int(fallback.timestamp() * 1000)


def _trade_sort_key(trade: dict[str, Any]) -> tuple[int, int, str]:
    return (
        _to_int(trade.get("entryTime")) or 0,
        _to_int(trade.get("exitTime")) or 0,
        str(trade.get("entrySignalSnapshotId") or trade.get("entrySnapshotId") or ""),
    )


def _signal_sort_key(signal: dict[str, Any]) -> tuple[int, int, str]:
    return (
        _signal_timestamp(signal) or 0,
        int(signal.get("__index") or 0),
        str(signal.get("snapshotId") or ""),
    )


def _segment_exit_is_later(
    segment: FusionLifecycleSegment,
    exit_time: int | None,
    exit_signal_snapshot_id: str | None,
) -> bool:
    if segment.exit_time is None:
        return True
    if exit_time is None:
        return False
    if exit_time != segment.exit_time:
        return exit_time > segment.exit_time
    return bool(exit_signal_snapshot_id and exit_signal_snapshot_id != segment.exit_signal_snapshot_id)


def _extract_max_positions(request_payload: dict[str, Any], trade_simulation: dict[str, Any]) -> int | None:
    trade_config = request_payload.get("tradeConfig") if isinstance(request_payload.get("tradeConfig"), dict) else {}
    config = trade_simulation.get("config") if isinstance(trade_simulation.get("config"), dict) else {}
    value = trade_config.get("maxPositions")
    if value is None:
        value = request_payload.get("maxPositions")
    if value is None:
        value = config.get("maxPositions")
    return _to_int(value)


def _coerce_frame_time(signal: dict[str, Any]) -> str:
    timestamp = _signal_timestamp(signal)
    if timestamp is not None:
        return _format_timestamp(timestamp) or ""
    return ""


def _format_timestamp(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC).astimezone(CHINA_TZ).isoformat()


def _frame_time_from_fields(signal: dict[str, Any]) -> datetime | None:
    trading_date = _to_str_or_none(signal.get("tradingDate"))
    slot_time = _to_str_or_none(signal.get("slotTime"))
    if not trading_date or not slot_time:
        return None
    try:
        return datetime.fromisoformat(f"{trading_date}T{slot_time}:00+08:00")
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_str_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _compute_t_plus_one(
    *,
    entry_trading_date: str | None,
    current_trading_date: str | None,
    state: str,
) -> bool | None:
    if not entry_trading_date or not current_trading_date:
        return True if state == "closed" else None
    return current_trading_date > entry_trading_date or state == "closed"


def _coalesce(value: Any, fallback: Any) -> Any:
    return value if value is not None else fallback
