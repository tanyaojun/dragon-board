from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass
from typing import Any

from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine, get_macd_min_samples
from backend.utils import new_id, stable_hash


DEFAULT_TRADE_CONFIG = {
    "initialCapital": 1000000,
    "maxPositions": 5,
    "positionSize": 0.2,
    "feeRate": 0.0003,
    "stampTaxRate": 0.0005,
    "slippageRate": 0.001,
    "maxHoldingBars": 40,
    "targetHoldingDays": 5.0,
    "enforceT1": True,
    "executionMode": "current_bar",
    "stopLoss": -0.06,
    "takeProfit": 0.12,
    "useOrderBookPrice": True,
    "enforceLimitStatus": True,
    "enforceVolumeLimit": True,
    "enforceOrderBookQueue": True,
    "allowPartialFills": True,
    "volumeParticipationRate": 0.05,
    "orderBookParticipationRate": 0.3,
    "useIntrabarStops": True,
    "intrabarAmbiguity": "stop_first",
}

DEFAULT_STRATEGY_NAME = "rank_trend_candidate"

STRATEGY_DEFINITIONS = [
    {
        "key": DEFAULT_STRATEGY_NAME,
        "label": "RankTrend 候选池",
        "description": "买入 A_MAIN 与连续确认后的 B_IGNITION，是当前正式策略。",
    },
    {
        "key": "hot_top10",
        "label": "热榜 Top10",
        "description": "只用热榜排名前 10 作为朴素对照组，不使用 RankTrend 分层。",
    },
    {
        "key": "a_main_only",
        "label": "A_MAIN only",
        "description": "只买 A_MAIN，衡量主升分层本身的交易贡献。",
    },
    {
        "key": "b_ignition_only",
        "label": "B_IGNITION only",
        "description": "只买连续确认后的 B_IGNITION，衡量点火分层的交易贡献。",
    },
    {
        "key": "a_b_combined",
        "label": "A+B",
        "description": "只买 A_MAIN 与连续确认后的 B_IGNITION，是当前正式策略的核心候选池对照。",
    },
]

SUPPORTED_STRATEGY_NAMES = {definition["key"] for definition in STRATEGY_DEFINITIONS}

CONTROL_STRATEGIES = [
    definition for definition in STRATEGY_DEFINITIONS if definition["key"] != DEFAULT_STRATEGY_NAME
]


def normalize_strategy_name(value: Any = None, default: str = DEFAULT_STRATEGY_NAME) -> str:
    strategy_name = str(value or default).strip()
    if not strategy_name:
        strategy_name = default
    if strategy_name not in SUPPORTED_STRATEGY_NAMES:
        supported = ", ".join(sorted(SUPPORTED_STRATEGY_NAMES))
        raise ValueError(f"unsupported strategyName: {strategy_name}. supported: {supported}")
    return strategy_name


def share(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def max_drawdown(equity: list[dict[str, Any]]) -> float:
    peak = equity[0]["equity"] if equity else 0
    drawdown = 0.0
    for point in equity:
        peak = max(peak, point["equity"])
        if peak > 0:
            drawdown = min(drawdown, (point["equity"] - peak) / peak)
    return round(drawdown, 4)


def _sample_std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    return math.sqrt(variance)


def short_cycle_sharpe(trades: list[dict[str, Any]], target_holding_days: float = 5.0, trading_days_per_year: int = 252) -> dict[str, Any]:
    returns = [float(trade.get("netReturn") or 0) for trade in trades if trade.get("netReturn") is not None]
    std = _sample_std(returns)
    if len(returns) < 2:
        return {"sharpe": None, "tradeSharpe": None, "avgTradeReturn": None, "tradeReturnStd": None}
    mean = sum(returns) / len(returns)
    if not std or std <= 1e-12:
        return {"sharpe": None, "tradeSharpe": None, "avgTradeReturn": round(mean, 4), "tradeReturnStd": None}
    trade_sharpe = mean / std
    cycle_scale = math.sqrt(trading_days_per_year / max(1.0, target_holding_days))
    return {
        "sharpe": round(trade_sharpe * cycle_scale, 4),
        "tradeSharpe": round(trade_sharpe, 4),
        "avgTradeReturn": round(mean, 4),
        "tradeReturnStd": round(std, 4),
    }


def find_frame_index(frames: list[dict[str, Any]], snapshot_id: str) -> int:
    return next((idx for idx, frame in enumerate(frames) if frame.get("snapshotId") == snapshot_id), -1)


def find_stock(frame: dict[str, Any] | None, code: str) -> dict[str, Any] | None:
    if not frame:
        return None
    return next((row for row in frame.get("stocks", []) if str(row.get("code")) == code), None)


def build_frame_lookup(frames: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "index_by_snapshot_id": {str(frame.get("snapshotId")): idx for idx, frame in enumerate(frames)},
        "stock_by_frame_code": [
            {str(row.get("code")): row for row in frame.get("stocks", []) if row.get("code") is not None}
            for frame in frames
        ],
    }


def percentile(rank: float, total: int) -> float:
    return ((total - rank + 1) / total) * 100 if total else 0.0


class OutcomeEvaluator:
    tiers = ["A_MAIN", "B_IGNITION", "C_CROWDED", "D_EXIT_RISK", "N_NEUTRAL"]

    def distribution(self, signals: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(signals)
        by_tier = [{"key": tier, "count": len([s for s in signals if s["candidateTier"] == tier]), "share": share(len([s for s in signals if s["candidateTier"] == tier]), total)} for tier in self.tiers]
        by_stage = self._group(signals, "stage")
        by_regime = self._group(signals, "regime")
        daily_map: dict[str, Any] = {}
        for signal in signals:
            date = signal.get("tradingDate") or ""
            daily = daily_map.setdefault(
                date,
                {
                    "tradingDate": date,
                    "total": 0,
                    "tiers": {tier: 0 for tier in self.tiers},
                    "regimes": {"strong": 0, "normal": 0, "weak": 0, "retreat": 0},
                },
            )
            daily["total"] += 1
            daily["tiers"][signal["candidateTier"]] += 1
            daily["regimes"][signal["regime"]] += 1
        weak = [s for s in signals if s["regime"] in ("weak", "retreat")]
        weak_ab = [s for s in weak if s["candidateTier"] in ("A_MAIN", "B_IGNITION")]
        warnings = []
        a_share = share(len([s for s in signals if s["candidateTier"] == "A_MAIN"]), total)
        if a_share > 0.1:
            warnings.append(f"A_MAIN 占比 {a_share * 100:.1f}%，高于 10% 验收警戒线")
        if weak and share(len(weak_ab), len(weak)) > 0.12:
            warnings.append("弱市/退潮环境下 A/B 收缩不充分")
        return {
            "totalSignals": total,
            "byTier": by_tier,
            "byStage": by_stage,
            "byRegime": by_regime,
            "daily": sorted(daily_map.values(), key=lambda item: item["tradingDate"]),
            "weakRetreatABShare": share(len(weak_ab), len(weak)),
            "warnings": warnings,
        }

    def evaluate(self, frames: list[dict[str, Any]], signals: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
        lookup = build_frame_lookup(frames)
        reports = [self._horizon(frames, signals, horizon, lookup) for horizon in horizons]
        signal_by_snapshot_code = {f"{s['snapshotId']}:{s['code']}": s for s in signals}
        b_signals = [s for s in signals if s["candidateTier"] == "B_IGNITION"]
        b_to_a = []
        for signal in b_signals:
            idx = lookup["index_by_snapshot_id"].get(str(signal["snapshotId"]), -1)
            next_frame = frames[idx + 1] if idx >= 0 and idx + 1 < len(frames) else None
            next_signal = signal_by_snapshot_code.get(f"{next_frame.get('snapshotId') if next_frame else ''}:{signal['code']}")
            if next_signal and next_signal["candidateTier"] == "A_MAIN":
                b_to_a.append(signal)
        d_signals = [s for s in signals if s["candidateTier"] == "D_EXIT_RISK"]
        d_outcomes = [(s, self._outcome(frames, s, 3, lookup)) for s in d_signals]
        d_decay = [s for s, outcome in d_outcomes if outcome.get("found") and ((outcome.get("rankDelta") or 0) < 0 or (outcome.get("percentileDelta") or 0) < 0)]
        return {
            "horizons": reports,
            "bToATransitionRate": share(len(b_to_a), len(b_signals)),
            "dDecayRate": share(len(d_decay), len(d_signals)),
            "buyBaselineComparison": [
                {
                    "horizon": report["horizon"],
                    "aMain": next((row for row in report["byTier"] if row["groupKey"] == "A_MAIN"), None),
                    "legacyBuy": self._stats("legacyBuy", [(s, self._outcome(frames, s, report["horizon"], lookup)) for s in signals if s["rankTrend"]["decision"]["final"]["signal"] == "buy"]),
                }
                for report in reports
            ],
        }

    def _horizon(self, frames: list[dict[str, Any]], signals: list[dict[str, Any]], horizon: int, lookup: dict[str, Any]) -> dict[str, Any]:
        pairs = [(signal, self._outcome(frames, signal, horizon, lookup)) for signal in signals]
        return {
            "horizon": horizon,
            "byTier": self._group_stats(pairs, lambda s: s["candidateTier"], self.tiers),
            "byStage": self._group_stats(pairs, lambda s: s["stage"]),
            "byRegime": self._group_stats(pairs, lambda s: s["regime"]),
            "byTierStage": self._group_stats(pairs, lambda s: f"{s['candidateTier']}/{s['stage']}"),
            "byTierRegime": self._group_stats(pairs, lambda s: f"{s['candidateTier']}/{s['regime']}"),
        }

    def _outcome(self, frames: list[dict[str, Any]], signal: dict[str, Any], horizon: int, lookup: dict[str, Any]) -> dict[str, Any]:
        code = str(signal["code"])
        entry = lookup["index_by_snapshot_id"].get(str(signal["snapshotId"]), -1)
        future = entry + horizon
        current_frame = frames[entry] if entry >= 0 else None
        future_frame = frames[future] if future < len(frames) else None
        current = lookup["stock_by_frame_code"][entry].get(code) if current_frame else None
        target = lookup["stock_by_frame_code"][future].get(code) if future_frame else None
        if entry < 0 or not current or not target or not current_frame or not future_frame:
            return {"code": signal["code"], "entrySnapshotId": signal["snapshotId"], "horizon": horizon, "found": False, "rankDelta": None, "percentileDelta": None, "priceReturn": None, "maxDrawdown": None, "stayedTop20": False, "stayedTop50": False}
        current_rank = float(current.get("rank") or 0)
        future_rank = float(target.get("rank") or 0)
        entry_price = float(current.get("price") or 0)
        future_price = float(target.get("price") or 0)
        stock_window = [lookup["stock_by_frame_code"][idx].get(code) for idx in range(entry, future + 1)]
        prices = [float((row or {}).get("price") or 0) for row in stock_window]
        prices = [price for price in prices if price > 0]
        return {
            "code": signal["code"],
            "entrySnapshotId": signal["snapshotId"],
            "horizon": horizon,
            "found": True,
            "rankDelta": round(current_rank - future_rank, 2),
            "percentileDelta": round(percentile(future_rank, len(future_frame["stocks"])) - percentile(current_rank, len(current_frame["stocks"])), 2),
            "priceReturn": round((future_price - entry_price) / entry_price, 4) if entry_price > 0 and future_price > 0 else None,
            "maxDrawdown": round((min(prices) - entry_price) / entry_price, 4) if entry_price > 0 and prices else None,
            "stayedTop20": all((row or {}).get("rank", 999) <= 20 for row in stock_window),
            "stayedTop50": all((row or {}).get("rank", 999) <= 50 for row in stock_window),
        }

    def _group(self, signals: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        total = len(signals)
        keys = sorted({str(signal.get(key)) for signal in signals})
        return [{"key": item, "count": len([s for s in signals if str(s.get(key)) == item]), "share": share(len([s for s in signals if str(s.get(key)) == item]), total)} for item in keys]

    def _group_stats(self, pairs: list[tuple[dict[str, Any], dict[str, Any]]], selector, order: list[str] | None = None) -> list[dict[str, Any]]:
        keys = order or sorted({selector(signal) for signal, _ in pairs})
        return [self._stats(key, [(s, o) for s, o in pairs if selector(s) == key]) for key in keys]

    def _stats(self, key: str, items: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
        found = [outcome for _, outcome in items if outcome.get("found")]
        return {
            "groupKey": key,
            "sampleCount": len(items),
            "foundCount": len(found),
            "foundRate": share(len(found), len(items)),
            "avgRankDelta": _round_or_none(average([o["rankDelta"] for o in found if o.get("rankDelta") is not None])),
            "avgPercentileDelta": _round_or_none(average([o["percentileDelta"] for o in found if o.get("percentileDelta") is not None])),
            "avgPriceReturn": _round_or_none(average([o["priceReturn"] for o in found if o.get("priceReturn") is not None])),
            "avgMaxDrawdown": _round_or_none(average([o["maxDrawdown"] for o in found if o.get("maxDrawdown") is not None])),
            "stayedTop20Rate": share(len([o for o in found if o.get("stayedTop20")]), len(found)),
            "stayedTop50Rate": share(len([o for o in found if o.get("stayedTop50")]), len(found)),
        }


def _round_or_none(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _first_number(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = source.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _first_finite(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = source.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


class TradeSimulator:
    def run(self, frames: list[dict[str, Any]], signals: list[dict[str, Any]], config_patch: dict[str, Any] | None = None) -> dict[str, Any]:
        config = {**DEFAULT_TRADE_CONFIG, **(config_patch or {})}
        strategy_key = normalize_strategy_name(config.get("entryStrategy") or config.get("controlStrategy") or config.get("strategyName"))
        config["entryStrategy"] = strategy_key
        execution_mode = self._normalize_execution_mode(config.get("executionMode") or config.get("execution_mode"))
        config["executionMode"] = execution_mode
        signals_by_snapshot: dict[str, list[dict[str, Any]]] = {}
        signal_by_snapshot_code: dict[str, dict[str, Any]] = {}
        for signal in signals:
            signals_by_snapshot.setdefault(signal["snapshotId"], []).append(signal)
            signal_by_snapshot_code[f"{signal['snapshotId']}:{signal['code']}"] = signal
        cash = float(config["initialCapital"])
        positions: dict[str, dict[str, Any]] = {}
        trades: list[dict[str, Any]] = []
        trade_events: list[dict[str, Any]] = []
        equity: list[dict[str, Any]] = []
        skipped_orders: list[dict[str, Any]] = []
        matching_stats = {
            "buyAttempts": 0,
            "sellAttempts": 0,
            "buyFilled": 0,
            "sellFilled": 0,
            "partialFills": 0,
            "blockedByLimit": 0,
            "blockedByLiquidity": 0,
            "snapshotPriceFallbacks": 0,
            "orderBookPricedFills": 0,
            "intrabarStopFills": 0,
            "missingPriceRows": 0,
            "nextBarEntries": 0,
            "nextBarExits": 0,
        }
        for idx, frame in enumerate(frames):
            frame_signals = signals_by_snapshot.get(frame["snapshotId"], [])
            signal_by_code = {signal["code"]: signal for signal in frame_signals}
            execution_signal_by_code = self._execution_signal_by_code(frames, idx, signals_by_snapshot, execution_mode)
            for code, pos in list(positions.items()):
                pos["holdingBars"] += 1
                signal = execution_signal_by_code.get(code)
                if not signal:
                    matching_stats["missingPriceRows"] += 1
                    continue
                fill_signal = self._merge_execution_signal(signal, signal_by_code.get(code), frame, execution_mode)
                quote = self._quote(fill_signal)
                raw_price = float(quote.get("lastPrice") or fill_signal.get("price") or 0)
                if raw_price <= 0:
                    matching_stats["missingPriceRows"] += 1
                    continue
                pos["lastPrice"] = raw_price
                pos["lastSnapshotId"] = frame["snapshotId"]
                pos["lastTime"] = frame["timestamp"]
                pos["lastTradingDate"] = frame.get("tradingDate")
                pos["lastRank"] = signal.get("rank")
                pos["lastSignal"] = signal
                if config.get("enforceT1", True) and str(frame.get("tradingDate") or "") <= str(pos.get("entryTradingDate") or ""):
                    continue
                gross_return = (raw_price - pos["entryPrice"]) / pos["entryPrice"]
                should_exit = signal["candidateTier"] == "D_EXIT_RISK" or (signal["candidateTier"] == "C_CROWDED" and signal["rankTrend"]["strategy"]["momentum"]["acceleration"] <= 0) or signal["rank"] > 50 or pos["holdingBars"] >= config["maxHoldingBars"] or gross_return <= config["stopLoss"] or gross_return >= config["takeProfit"]
                exit_trigger = None
                trigger_price = raw_price
                intrabar = self._intrabar_exit_trigger(pos, quote, config)
                if intrabar:
                    should_exit = True
                    exit_trigger = intrabar["reason"]
                    trigger_price = float(intrabar["price"])
                if not should_exit:
                    continue
                matching_stats["sellAttempts"] += 1
                fill = self._match_order(fill_signal, "sell", int(pos["quantity"]), trigger_price, config)
                if intrabar:
                    fill["trigger"] = "intrabar_stop" if "止损" in exit_trigger else "intrabar_take_profit"
                self._record_fill_stats(fill, matching_stats)
                if not fill["filled"]:
                    skipped_orders.append(self._skipped_order(fill_signal, "sell", int(pos["quantity"]), fill, pos, signal_snapshot_id=signal.get("snapshotId"), execution_mode=execution_mode))
                    continue
                if execution_mode == "next_bar":
                    matching_stats["nextBarExits"] += 1
                exit_price = float(fill["price"])
                quantity = int(fill["quantity"])
                gross_amount = quantity * exit_price
                exit_cost = gross_amount * (config["feeRate"] + config["stampTaxRate"])
                cash += gross_amount - exit_cost
                entry_cost_basis = (float(pos["entryCost"]) / int(pos["quantity"])) * quantity if pos["quantity"] else 0
                profit = gross_amount - exit_cost - entry_cost_basis
                reason = exit_trigger or self._exit_reason(signal, pos, gross_return, config)
                net_return = profit / entry_cost_basis if entry_cost_basis else 0
                explanation = self._signal_explanation(signal, f"卖出：{reason}", pos)
                trade = {"code": code, "name": pos["name"], "entrySnapshotId": pos["entrySnapshotId"], "entrySignalSnapshotId": pos.get("entrySignalSnapshotId") or pos["entrySnapshotId"], "exitSnapshotId": frame["snapshotId"], "exitSignalSnapshotId": signal.get("snapshotId"), "entryTime": pos["entryTime"], "exitTime": frame["timestamp"], "entryTradingDate": pos.get("entryTradingDate"), "exitTradingDate": frame.get("tradingDate"), "entryPrice": pos["entryPrice"], "exitPrice": exit_price, "quantity": quantity, "holdingBars": pos["holdingBars"], "grossReturn": round((exit_price - pos["entryPrice"]) / pos["entryPrice"], 4) if pos["entryPrice"] else 0, "netReturn": round(net_return, 4), "profit": round(profit, 2), "reason": reason, "explanation": explanation, "action": "sell", "price": exit_price, "rank": signal["rank"], "candidateTier": signal.get("candidateTier"), "stage": signal.get("stage"), "regime": signal.get("regime"), "executionMode": execution_mode, "fill": self._public_fill(fill)}
                trades.append(trade)
                trade_events.append({"snapshotId": frame["snapshotId"], "timestamp": frame["timestamp"], "tradingDate": frame.get("tradingDate"), "slotTime": frame.get("slotTime"), "signalSnapshotId": signal.get("snapshotId"), "code": code, "name": pos["name"], "action": "sell", "executionMode": execution_mode, "price": exit_price, "quantity": quantity, "rank": signal["rank"], "reason": reason, "explanation": explanation, "profit": round(profit, 2), "netReturn": trade["netReturn"], "holdingBars": pos["holdingBars"], "candidateTier": signal.get("candidateTier"), "stage": signal.get("stage"), "regime": signal.get("regime"), "confidence": signal.get("confidence"), "fill": self._public_fill(fill)})
                if quantity >= int(pos["quantity"]):
                    del positions[code]
                else:
                    remaining_ratio = (int(pos["quantity"]) - quantity) / int(pos["quantity"])
                    pos["quantity"] = int(pos["quantity"]) - quantity
                    pos["entryAmount"] = float(pos["entryAmount"]) * remaining_ratio
                    pos["entryFee"] = float(pos["entryFee"]) * remaining_ratio
                    pos["entryCost"] = float(pos["entryCost"]) * remaining_ratio
            signal_idx = idx if execution_mode == "current_bar" else idx - 1
            candidate_signals = frame_signals if execution_mode == "current_bar" else list(execution_signal_by_code.values())
            candidates = self._entry_candidates(candidate_signals, frames, signal_idx, signal_by_snapshot_code, positions, strategy_key)
            for signal in candidates:
                if len(positions) >= int(config["maxPositions"]):
                    break
                fill_signal = self._merge_execution_signal(signal, signal_by_code.get(str(signal.get("code"))), frame, execution_mode)
                quote = self._quote(fill_signal)
                raw_price = float(quote.get("lastPrice") or fill_signal.get("price") or 0)
                if raw_price <= 0:
                    matching_stats["missingPriceRows"] += 1
                    continue
                matching_stats["buyAttempts"] += 1
                allocation = min(cash, float(config["initialCapital"]) * float(config["positionSize"]))
                estimated_price = self._quote_price_for_side(quote, "buy", raw_price, config)
                quantity = int((allocation - allocation * config["feeRate"]) / estimated_price / 100) * 100 if estimated_price > 0 else 0
                if quantity <= 0:
                    continue
                fill = self._match_order(fill_signal, "buy", quantity, raw_price, config)
                self._record_fill_stats(fill, matching_stats)
                if not fill["filled"]:
                    skipped_orders.append(self._skipped_order(fill_signal, "buy", quantity, fill, signal_snapshot_id=signal.get("snapshotId"), execution_mode=execution_mode))
                    continue
                if execution_mode == "next_bar":
                    matching_stats["nextBarEntries"] += 1
                entry_price = float(fill["price"])
                quantity = int(fill["quantity"])
                allocation = min(cash, float(config["initialCapital"]) * float(config["positionSize"]))
                max_affordable = int((allocation - allocation * config["feeRate"]) / entry_price / 100) * 100
                quantity = min(quantity, max_affordable)
                if quantity <= 0:
                    continue
                entry_amount = quantity * entry_price
                entry_fee = entry_amount * config["feeRate"]
                used = entry_amount + entry_fee
                cash -= used
                entry_reason = self._entry_reason(signal, frames, signal_idx, signal_by_snapshot_code, strategy_key)
                positions[signal["code"]] = {"code": signal["code"], "name": signal["name"], "entrySnapshotId": frame["snapshotId"], "entrySignalSnapshotId": signal["snapshotId"], "entryTime": frame["timestamp"], "entrySignalTime": signal.get("timestamp"), "entryTradingDate": frame.get("tradingDate"), "entrySignalTradingDate": signal.get("tradingDate"), "entrySlotTime": frame.get("slotTime"), "entryPrice": entry_price, "entryAmount": entry_amount, "entryFee": entry_fee, "entryCost": used, "quantity": quantity, "holdingBars": 0, "entryReason": entry_reason, "entryRank": signal.get("rank"), "entryExecutionRank": fill_signal.get("rank"), "entryCandidateTier": signal.get("candidateTier"), "entryConfidence": signal.get("confidence"), "lastPrice": raw_price, "lastSnapshotId": frame["snapshotId"], "lastTime": frame["timestamp"], "lastTradingDate": frame.get("tradingDate"), "lastRank": fill_signal.get("rank"), "lastSignal": signal, "entryFill": self._public_fill(fill)}
                trade_events.append({"snapshotId": frame["snapshotId"], "timestamp": frame["timestamp"], "tradingDate": frame.get("tradingDate"), "slotTime": frame.get("slotTime"), "signalSnapshotId": signal["snapshotId"], "code": signal["code"], "name": signal["name"], "action": "buy", "executionMode": execution_mode, "price": entry_price, "quantity": quantity, "rank": signal["rank"], "reason": entry_reason, "explanation": self._signal_explanation(signal, f"买入：{entry_reason}"), "candidateTier": signal["candidateTier"], "stage": signal.get("stage"), "regime": signal.get("regime"), "confidence": signal.get("confidence"), "fill": self._public_fill(fill)})
            market_value = sum(pos["quantity"] * float((signal_by_code.get(code) or {}).get("price") or pos.get("lastPrice") or pos["entryPrice"]) for code, pos in positions.items())
            equity.append({"snapshotId": frame["snapshotId"], "timestamp": frame["timestamp"], "tradingDate": frame.get("tradingDate"), "slotTime": frame.get("slotTime"), "equity": round(cash + market_value, 2), "cash": round(cash, 2), "marketValue": round(market_value, 2), "positionCount": len(positions)})
        final_equity = equity[-1]["equity"] if equity else config["initialCapital"]
        wins = [trade for trade in trades if trade["netReturn"] > 0]
        sharpe_metrics = short_cycle_sharpe(trades, target_holding_days=float(config.get("targetHoldingDays") or 5.0))
        open_positions = [self._open_position_snapshot(pos, config) for pos in positions.values()]
        realized_profit = round(sum(float(trade.get("profit") or 0) for trade in trades), 2)
        unrealized_mark_profit = round(sum(float(pos.get("unrealizedMarkProfit") or 0) for pos in open_positions), 2)
        unrealized_exit_cost = round(sum(float(pos.get("estimatedExitCost") or 0) for pos in open_positions), 2)
        unrealized_profit = round(sum(float(pos.get("unrealizedProfit") or 0) for pos in open_positions), 2)
        target_days = float(config.get("targetHoldingDays") or 5.0)
        matching_diagnostics = self._matching_diagnostics(matching_stats, skipped_orders, config)
        notes = ["交易模拟已启用 A 股 T+1、100 股手数、手续费、印花税、滑点、涨跌停可成交检查、盘口价格优先和容量约束；缺少盘口/成交量字段时会在 matchingDiagnostics 中降级说明。", "totalReturn 含未平仓市值；unrealizedProfit 为预估平仓后浮动盈亏，已扣预估卖出手续费和印花税。"]
        if execution_mode == "next_bar":
            notes.insert(0, "executionMode=next_bar：信号按下一快照成交，成交价和可成交性使用下一快照行情。")
        return {"enabled": True, "entryStrategy": strategy_key, "executionMode": execution_mode, "config": config, "totalReturn": round((final_equity - config["initialCapital"]) / config["initialCapital"], 4), "realizedReturn": round(realized_profit / config["initialCapital"], 4), "realizedProfit": realized_profit, "unrealizedMarkProfit": unrealized_mark_profit, "unrealizedExitCost": unrealized_exit_cost, "unrealizedProfit": unrealized_profit, "openPositionCount": len(open_positions), "openPositions": open_positions, **sharpe_metrics, "sharpeMethod": f"trade_return_cycle_{target_days:g}d", "maxDrawdown": max_drawdown(equity), "winRate": share(len(wins), len(trades)), "tradeCount": len(trades), "eventCount": len(trade_events), "skippedOrderCount": len(skipped_orders), "skippedOrders": skipped_orders[:200], "matchingDiagnostics": matching_diagnostics, "trades": trades, "tradeEvents": trade_events, "equityHistory": equity, "equityCurve": equity, "notes": notes}

    @staticmethod
    def _normalize_execution_mode(value: Any) -> str:
        mode = str(value or "current_bar").strip()
        if mode not in {"current_bar", "next_bar"}:
            raise ValueError(f"unsupported executionMode: {mode}. supported: current_bar, next_bar")
        return mode

    @staticmethod
    def _execution_signal_by_code(
        frames: list[dict[str, Any]],
        idx: int,
        signals_by_snapshot: dict[str, list[dict[str, Any]]],
        execution_mode: str,
    ) -> dict[str, dict[str, Any]]:
        if execution_mode == "current_bar":
            snapshot_id = frames[idx].get("snapshotId")
        else:
            if idx <= 0:
                return {}
            snapshot_id = frames[idx - 1].get("snapshotId")
        return {str(signal.get("code")): signal for signal in signals_by_snapshot.get(str(snapshot_id), [])}

    @staticmethod
    def _merge_execution_signal(
        signal: dict[str, Any],
        current_signal: dict[str, Any] | None,
        frame: dict[str, Any],
        execution_mode: str,
    ) -> dict[str, Any]:
        if execution_mode == "current_bar":
            return signal
        if not current_signal:
            return {
                **signal,
                "snapshotId": frame.get("snapshotId"),
                "timestamp": frame.get("timestamp"),
                "tradingDate": frame.get("tradingDate"),
                "slotTime": frame.get("slotTime"),
                "price": None,
                "signalSnapshotId": signal.get("snapshotId"),
                "signalTimestamp": signal.get("timestamp"),
                "signalTradingDate": signal.get("tradingDate"),
            }
        merged = {**signal, **(current_signal or {})}
        merged["signalSnapshotId"] = signal.get("snapshotId")
        merged["signalTimestamp"] = signal.get("timestamp")
        merged["signalTradingDate"] = signal.get("tradingDate")
        merged["snapshotId"] = frame.get("snapshotId")
        merged["timestamp"] = frame.get("timestamp")
        merged["tradingDate"] = frame.get("tradingDate")
        merged["slotTime"] = frame.get("slotTime")
        return merged

    @staticmethod
    def _entry_candidates(frame_signals: list[dict[str, Any]], frames: list[dict[str, Any]], idx: int, by_key: dict[str, dict[str, Any]], positions: dict[str, Any], strategy_key: str = "rank_trend_candidate") -> list[dict[str, Any]]:
        result = []
        previous_frame = frames[idx - 1] if idx > 0 else None
        for signal in frame_signals:
            if signal["code"] in positions:
                continue
            if strategy_key == "hot_top10":
                if signal.get("rank", 999) <= 10 and signal["regime"] != "retreat":
                    result.append(signal)
                continue
            if signal["regime"] == "retreat":
                continue
            if strategy_key == "a_main_only":
                if signal["candidateTier"] == "A_MAIN" and signal["regime"] != "weak":
                    result.append(signal)
                continue
            if strategy_key == "b_ignition_only":
                if TradeSimulator._is_confirmed_b_ignition(signal, previous_frame, by_key):
                    result.append(signal)
                continue
            if signal["candidateTier"] == "A_MAIN" and signal["regime"] != "weak":
                result.append(signal)
            elif signal["candidateTier"] == "B_IGNITION" and strategy_key in ("rank_trend_candidate", "a_b_combined") and TradeSimulator._is_confirmed_b_ignition(signal, previous_frame, by_key):
                result.append(signal)
        return sorted(result, key=lambda item: item.get("confidence", 0), reverse=True)

    @staticmethod
    def _is_confirmed_b_ignition(signal: dict[str, Any], previous_frame: dict[str, Any] | None, by_key: dict[str, dict[str, Any]]) -> bool:
        if signal["candidateTier"] != "B_IGNITION" or not previous_frame:
            return False
        previous_signal = by_key.get(f"{previous_frame['snapshotId']}:{signal['code']}")
        return bool(previous_signal and previous_signal["candidateTier"] == "B_IGNITION")

    @staticmethod
    def _quote(signal: dict[str, Any]) -> dict[str, Any]:
        price = _first_number(signal, "lastTradePrice", "lastPrice", "price", "close", "closePrice")
        return {
            "lastPrice": price,
            "bid1Price": _first_number(signal, "bid1Price", "bidPrice1", "bid1", "buy1Price"),
            "bid1Volume": _first_number(signal, "bid1Volume", "bidVol1", "bid1Vol", "buy1Volume"),
            "ask1Price": _first_number(signal, "ask1Price", "askPrice1", "ask1", "sell1Price"),
            "ask1Volume": _first_number(signal, "ask1Volume", "askVol1", "ask1Vol", "sell1Volume"),
            "volume": _first_number(signal, "volume", "vol", "tradeVolume"),
            "turnover": _first_number(signal, "turnover", "amount", "tradeAmount"),
            "high": _first_number(signal, "high", "highPrice", "dayHigh"),
            "low": _first_number(signal, "low", "lowPrice", "dayLow"),
            "change": _first_finite(signal, "change", "pctChange", "changePct"),
            "limitUpPrice": _first_number(signal, "limitUpPrice", "ztPrice", "upLimitPrice", "涨停价"),
            "limitDownPrice": _first_number(signal, "limitDownPrice", "dtPrice", "downLimitPrice", "跌停价"),
            "fengdan": _first_number(signal, "fengdan", "sealAmount", "limitUpSealAmount"),
        }

    @staticmethod
    def _match_order(signal: dict[str, Any], side: str, requested_quantity: int, reference_price: float, config: dict[str, Any]) -> dict[str, Any]:
        quote = TradeSimulator._quote(signal)
        if requested_quantity <= 0:
            return {"filled": False, "reason": "invalid_quantity", "quantity": 0, "requestedQuantity": requested_quantity}
        last_price = float(quote.get("lastPrice") or reference_price or 0)
        if last_price <= 0:
            return {"filled": False, "reason": "missing_price", "quantity": 0, "requestedQuantity": requested_quantity}
        limit_state = TradeSimulator._limit_state(signal, quote)
        if config.get("enforceLimitStatus", True):
            if side == "buy" and limit_state["atLimitUp"]:
                return {"filled": False, "reason": "limit_up_unbuyable", "quantity": 0, "requestedQuantity": requested_quantity, "limitState": limit_state}
            if side == "sell" and limit_state["atLimitDown"]:
                return {"filled": False, "reason": "limit_down_unsellable", "quantity": 0, "requestedQuantity": requested_quantity, "limitState": limit_state}

        price_source = "snapshot_price"
        snapshot_fallback = False
        raw_price = TradeSimulator._quote_price_for_side(quote, side, last_price, config)
        if config.get("useOrderBookPrice", True):
            if side == "buy" and quote.get("ask1Price"):
                price_source = "ask1"
            elif side == "sell" and quote.get("bid1Price"):
                price_source = "bid1"
            else:
                snapshot_fallback = True
        fill_price = raw_price * (1 + float(config.get("slippageRate") or 0)) if side == "buy" else raw_price * (1 - float(config.get("slippageRate") or 0))

        capacity = requested_quantity
        capacity_reasons: list[str] = []
        if config.get("enforceOrderBookQueue", True):
            book_volume = quote.get("ask1Volume") if side == "buy" else quote.get("bid1Volume")
            if book_volume and book_volume > 0:
                book_capacity = int(float(book_volume) * float(config.get("orderBookParticipationRate") or 0.3) / 100) * 100
                if book_capacity > 0:
                    capacity = min(capacity, book_capacity)
                    capacity_reasons.append("order_book_queue")
        if config.get("enforceVolumeLimit", True):
            volume = quote.get("volume")
            if volume and volume > 0:
                volume_capacity = int(float(volume) * float(config.get("volumeParticipationRate") or 0.05) / 100) * 100
                if volume_capacity > 0:
                    capacity = min(capacity, volume_capacity)
                    capacity_reasons.append("volume_participation")
        if capacity < requested_quantity and not config.get("allowPartialFills", True):
            return {"filled": False, "reason": "liquidity_not_enough", "quantity": 0, "requestedQuantity": requested_quantity, "availableQuantity": capacity, "limitState": limit_state}
        fill_quantity = min(requested_quantity, capacity)
        fill_quantity = int(fill_quantity / 100) * 100
        if fill_quantity <= 0:
            return {"filled": False, "reason": "liquidity_not_enough", "quantity": 0, "requestedQuantity": requested_quantity, "availableQuantity": capacity, "limitState": limit_state}
        return {
            "filled": True,
            "side": side,
            "price": fill_price,
            "rawPrice": raw_price,
            "referencePrice": reference_price,
            "priceSource": price_source,
            "snapshotPriceFallback": snapshot_fallback,
            "quantity": fill_quantity,
            "requestedQuantity": requested_quantity,
            "partial": fill_quantity < requested_quantity,
            "capacityReasons": capacity_reasons,
            "limitState": limit_state,
        }

    @staticmethod
    def _quote_price_for_side(quote: dict[str, Any], side: str, fallback: float, config: dict[str, Any]) -> float:
        if config.get("useOrderBookPrice", True):
            if side == "buy" and quote.get("ask1Price"):
                return float(quote["ask1Price"])
            if side == "sell" and quote.get("bid1Price"):
                return float(quote["bid1Price"])
        return float(fallback or quote.get("lastPrice") or 0)

    @staticmethod
    def _limit_state(signal: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
        last_price = float(quote.get("lastPrice") or 0)
        change = quote.get("change")
        limit_up_price = quote.get("limitUpPrice")
        limit_down_price = quote.get("limitDownPrice")
        lead_status = str(signal.get("leadStatus") or signal.get("limitStatus") or "")
        at_limit_up = bool(signal.get("isLimitUp") or signal.get("limitUp")) or "涨停" in lead_status
        at_limit_down = bool(signal.get("isLimitDown") or signal.get("limitDown")) or "跌停" in lead_status
        if limit_up_price and last_price:
            at_limit_up = at_limit_up or last_price >= float(limit_up_price) * 0.999
        if limit_down_price and last_price:
            at_limit_down = at_limit_down or last_price <= float(limit_down_price) * 1.001
        if change is not None:
            at_limit_up = at_limit_up or float(change) >= TradeSimulator._limit_pct_threshold(str(signal.get("code") or ""), "up")
            at_limit_down = at_limit_down or float(change) <= -TradeSimulator._limit_pct_threshold(str(signal.get("code") or ""), "down")
        return {
            "atLimitUp": at_limit_up,
            "atLimitDown": at_limit_down,
            "limitUpPrice": limit_up_price,
            "limitDownPrice": limit_down_price,
            "change": change,
            "fengdan": quote.get("fengdan"),
        }

    @staticmethod
    def _limit_pct_threshold(code: str, _: str) -> float:
        if code.startswith(("300", "301", "688", "689")):
            return 19.8
        if code.startswith(("8", "4", "9")):
            return 29.8
        return 9.8

    @staticmethod
    def _intrabar_exit_trigger(pos: dict[str, Any], quote: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
        if not config.get("useIntrabarStops", True):
            return None
        entry_price = float(pos.get("entryPrice") or 0)
        if entry_price <= 0:
            return None
        stop_price = entry_price * (1 + float(config.get("stopLoss") or 0))
        take_price = entry_price * (1 + float(config.get("takeProfit") or 0))
        low = quote.get("low")
        high = quote.get("high")
        hit_stop = low is not None and float(low) > 0 and float(low) <= stop_price
        hit_take = high is not None and float(high) > 0 and float(high) >= take_price
        if hit_stop and hit_take:
            if str(config.get("intrabarAmbiguity") or "stop_first") == "take_first":
                return {"reason": "盘中止盈", "price": take_price}
            return {"reason": "盘中止损", "price": stop_price}
        if hit_stop:
            return {"reason": "盘中止损", "price": stop_price}
        if hit_take:
            return {"reason": "盘中止盈", "price": take_price}
        return None

    @staticmethod
    def _record_fill_stats(fill: dict[str, Any], stats: dict[str, int]) -> None:
        if not fill.get("filled"):
            reason = str(fill.get("reason") or "")
            if "limit" in reason:
                stats["blockedByLimit"] += 1
            elif "liquidity" in reason:
                stats["blockedByLiquidity"] += 1
            return
        if fill.get("side") == "buy":
            stats["buyFilled"] += 1
        if fill.get("side") == "sell":
            stats["sellFilled"] += 1
        if fill.get("partial"):
            stats["partialFills"] += 1
        if fill.get("snapshotPriceFallback"):
            stats["snapshotPriceFallbacks"] += 1
        if fill.get("priceSource") in ("bid1", "ask1"):
            stats["orderBookPricedFills"] += 1
        if str(fill.get("trigger") or "").startswith("intrabar"):
            stats["intrabarStopFills"] += 1

    @staticmethod
    def _public_fill(fill: dict[str, Any]) -> dict[str, Any]:
        return {
            "priceSource": fill.get("priceSource"),
            "rawPrice": _round_or_none(fill.get("rawPrice")),
            "price": _round_or_none(fill.get("price")),
            "trigger": fill.get("trigger"),
            "requestedQuantity": fill.get("requestedQuantity"),
            "quantity": fill.get("quantity"),
            "partial": bool(fill.get("partial")),
            "snapshotPriceFallback": bool(fill.get("snapshotPriceFallback")),
            "capacityReasons": fill.get("capacityReasons") or [],
        }

    @staticmethod
    def _skipped_order(signal: dict[str, Any], side: str, quantity: int, fill: dict[str, Any], pos: dict[str, Any] | None = None, signal_snapshot_id: Any = None, execution_mode: str = "current_bar") -> dict[str, Any]:
        return {
            "snapshotId": signal.get("snapshotId"),
            "signalSnapshotId": signal_snapshot_id or signal.get("signalSnapshotId") or signal.get("snapshotId"),
            "timestamp": signal.get("timestamp"),
            "tradingDate": signal.get("tradingDate"),
            "slotTime": signal.get("slotTime"),
            "executionMode": execution_mode,
            "code": signal.get("code"),
            "name": signal.get("name"),
            "side": side,
            "requestedQuantity": quantity,
            "reason": fill.get("reason"),
            "availableQuantity": fill.get("availableQuantity"),
            "rank": signal.get("rank"),
            "candidateTier": signal.get("candidateTier"),
            "positionEntrySnapshotId": (pos or {}).get("entrySnapshotId"),
        }

    @staticmethod
    def _matching_diagnostics(stats: dict[str, int], skipped_orders: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        by_reason: dict[str, int] = {}
        for order in skipped_orders:
            reason = str(order.get("reason") or "unknown")
            by_reason[reason] = by_reason.get(reason, 0) + 1
        warnings = []
        if stats["snapshotPriceFallbacks"]:
            warnings.append(f"{stats['snapshotPriceFallbacks']} 次成交缺少买一/卖一价，已回退为快照价加滑点。")
        if not config.get("enforceOrderBookQueue", True):
            warnings.append("盘口排队约束未启用。")
        if not config.get("enforceVolumeLimit", True):
            warnings.append("成交量参与率约束未启用。")
        if skipped_orders:
            warnings.append(f"{len(skipped_orders)} 笔候选订单因涨跌停、流动性或价格缺失未成交。")
        return {
            **stats,
            "skippedOrderCount": len(skipped_orders),
            "skippedByReason": [{"reason": reason, "count": count} for reason, count in sorted(by_reason.items(), key=lambda item: item[1], reverse=True)],
            "orderBookCoverage": share(stats["orderBookPricedFills"], max(1, stats["buyFilled"] + stats["sellFilled"])),
            "snapshotFallbackRate": share(stats["snapshotPriceFallbacks"], max(1, stats["buyFilled"] + stats["sellFilled"])),
            "notes": [
                "有买一/卖一价时按盘口对手价加滑点成交；缺失时回退到快照价。",
                "涨停默认不可买，跌停默认不可卖；成交数量受盘口量和成交量参与率约束。",
                "盘中高低价字段存在时，止盈止损按高低价触发；同时触发时默认先按止损。"
            ],
            "warnings": warnings,
        }

    @staticmethod
    def _exit_reason(signal: dict[str, Any], pos: dict[str, Any], gross_return: float, config: dict[str, Any]) -> str:
        if signal["candidateTier"] == "D_EXIT_RISK":
            return "D_EXIT_RISK"
        if signal["rank"] > 50:
            return "排名跌出前50"
        if pos["holdingBars"] >= config["maxHoldingBars"]:
            return "到达最大持有快照"
        if gross_return <= config["stopLoss"]:
            return "止损"
        if gross_return >= config["takeProfit"]:
            return "止盈"
        return "拥挤且加速度转弱"

    @staticmethod
    def _entry_reason(signal: dict[str, Any], frames: list[dict[str, Any]] | None = None, idx: int | None = None, by_key: dict[str, dict[str, Any]] | None = None, strategy_key: str = "rank_trend_candidate") -> str:
        if strategy_key == "hot_top10":
            return "对照组：热榜前10入场"
        if strategy_key == "a_main_only":
            return "对照组：A_MAIN 入场"
        if strategy_key == "b_ignition_only":
            return "对照组：B_IGNITION 连续确认入场"
        if strategy_key == "a_b_combined":
            return "对照组：" + ("A_MAIN 入场" if signal["candidateTier"] == "A_MAIN" else "B_IGNITION 连续确认入场")
        if signal["candidateTier"] == "A_MAIN":
            return "A_MAIN 入场"
        if signal["candidateTier"] == "B_IGNITION":
            previous_frame = frames[(idx or 0) - 1] if frames and idx and idx > 0 else None
            previous_signal = by_key.get(f"{previous_frame['snapshotId']}:{signal['code']}") if previous_frame and by_key else None
            if previous_signal:
                return "B_IGNITION 连续确认入场"
            return "B_IGNITION 确认入场"
        return signal["candidateTier"]

    @staticmethod
    def _signal_explanation(signal: dict[str, Any], prefix: str, pos: dict[str, Any] | None = None) -> str:
        rank_trend = signal.get("rankTrend") or {}
        technical = rank_trend.get("technical") or {}
        strategy = rank_trend.get("strategy") or {}
        risk = rank_trend.get("risk") or {}
        decision = rank_trend.get("decision") or {}
        signals = technical.get("signals") or {}
        momentum = technical.get("momentumProfile") or strategy.get("momentum") or {}
        direction = (signals.get("direction") or {}).get("signal", "-")
        acceleration_signal = (signals.get("acceleration") or {}).get("signal", "-")
        zero_cross = (signals.get("zeroCross") or {}).get("signal", "-")
        final_signal = ((decision.get("final") or {}).get("signal")) or "-"
        confidence = signal.get("confidence")
        confidence_text = f"{float(confidence):.1f}" if confidence is not None else "-"
        parts = [
            prefix,
            f"RankTrend={signal.get('candidateTier')}，动作={signal.get('action')}，阶段={signal.get('stage')}，市场={signal.get('regime')}，排名={signal.get('rank')}，信心={confidence_text}",
            f"技术信号：方向={direction}，加速度={acceleration_signal}，零轴={zero_cross}，最终={final_signal}",
        ]
        if momentum:
            parts.append(
                "动量结构："
                f"短{float(momentum.get('short') or 0):+.1f}，"
                f"中{float(momentum.get('mid') or 0):+.1f}，"
                f"长{float(momentum.get('long') or 0):+.1f}，"
                f"加速度{float(momentum.get('acceleration') or 0):+.1f}"
            )
        if risk:
            overheat = risk.get("overheat") or {}
            pressure = risk.get("pressure")
            pressure_text = f"{float(pressure):.2f}" if pressure is not None else "-"
            parts.append(f"风险：过热={overheat.get('signal', '-')}，压力={pressure_text}")
        reasons = strategy.get("reasons") or []
        if reasons:
            parts.append("策略原因：" + "；".join(str(item) for item in reasons[:3]))
        if pos:
            parts.append(f"持有{pos.get('holdingBars', 0)}个快照，入场原因={pos.get('entryReason', '-')}")
        return "。".join(parts)

    @staticmethod
    def _open_position_snapshot(pos: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        last_price = float(pos.get("lastPrice") or pos.get("entryPrice") or 0)
        market_value = pos["quantity"] * last_price
        estimated_exit_cost = market_value * (config["feeRate"] + config["stampTaxRate"])
        unrealized_mark_profit = market_value - float(pos.get("entryCost") or 0)
        unrealized_profit = unrealized_mark_profit - estimated_exit_cost
        return {
            "code": pos["code"],
            "name": pos["name"],
            "entrySnapshotId": pos["entrySnapshotId"],
            "lastSnapshotId": pos.get("lastSnapshotId"),
            "entryTime": pos["entryTime"],
            "lastTime": pos.get("lastTime"),
            "entryTradingDate": pos.get("entryTradingDate"),
            "lastTradingDate": pos.get("lastTradingDate"),
            "entryPrice": pos["entryPrice"],
            "lastPrice": last_price,
            "quantity": pos["quantity"],
            "holdingBars": pos.get("holdingBars", 0),
            "entryRank": pos.get("entryRank"),
            "lastRank": pos.get("lastRank"),
            "entryReason": pos.get("entryReason"),
            "marketValue": round(market_value, 2),
            "entryCost": round(float(pos.get("entryCost") or 0), 2),
            "unrealizedMarkProfit": round(unrealized_mark_profit, 2),
            "unrealizedExitCost": round(estimated_exit_cost, 2),
            "unrealizedProfit": round(unrealized_profit, 2),
            "unrealizedReturn": round(unrealized_profit / float(pos.get("entryCost") or 1), 4),
            "estimatedExitCost": round(estimated_exit_cost, 2),
            "explanation": TradeSimulator._signal_explanation(pos.get("lastSignal") or {}, "未平仓：按最后可见价格盯市", pos) if pos.get("lastSignal") else "未平仓：缺少最新 RankTrend 信号，按入场价附近盯市",
        }


class BacktestEngine:
    def run(self, frames: list[dict[str, Any]], options: dict[str, Any]) -> dict[str, Any]:
        config = RankTrendConfig.from_patch(options.get("strategy_config") or {})
        signals = RankTrendPythonEngine(config).replay(frames, meta={"sampleQuality": "ok", "warnings": []})
        strategy_name = normalize_strategy_name(options.get("strategy_name") or (options.get("trade_config") or {}).get("entryStrategy"))
        evaluator = OutcomeEvaluator()
        distribution = evaluator.distribution(signals)
        forward = evaluator.evaluate(frames, signals, options.get("horizons") or [1, 3, 5, 10])
        sample_diagnostics = self._sample_diagnostics(frames, signals, config)
        macd_diagnostics = self._macd_diagnostics(config, frames)
        data_quality = self._data_quality_summary(options.get("quality_gate"), sample_diagnostics, macd_diagnostics)
        report: dict[str, Any] = {
            "strategyName": strategy_name,
            "strategy_name": strategy_name,
            "signals": signals,
            "distribution": distribution,
            "forwardValidation": forward,
            "sampleDiagnostics": sample_diagnostics,
            "macdDiagnostics": macd_diagnostics,
            "dataQuality": data_quality,
            "warnings": data_quality["warnings"],
        }
        if options.get("enable_trade_simulation", True):
            trade_config = {**(options.get("trade_config") or {}), "entryStrategy": strategy_name}
            report["tradeSimulation"] = TradeSimulator().run(frames, signals, trade_config)
            report["controlBacktests"] = self._control_backtests(frames, signals, trade_config)
            report["tradeDiagnostics"] = self._trade_diagnostics(report["tradeSimulation"])
            report.update({
                "totalReturn": report["tradeSimulation"]["totalReturn"],
                "sharpe": report["tradeSimulation"]["sharpe"],
                "tradeSharpe": report["tradeSimulation"]["tradeSharpe"],
                "avgTradeReturn": report["tradeSimulation"]["avgTradeReturn"],
                "tradeReturnStd": report["tradeSimulation"]["tradeReturnStd"],
                "sharpeMethod": report["tradeSimulation"]["sharpeMethod"],
                "realizedReturn": report["tradeSimulation"]["realizedReturn"],
                "realizedProfit": report["tradeSimulation"]["realizedProfit"],
                "unrealizedMarkProfit": report["tradeSimulation"]["unrealizedMarkProfit"],
                "unrealizedExitCost": report["tradeSimulation"]["unrealizedExitCost"],
                "unrealizedProfit": report["tradeSimulation"]["unrealizedProfit"],
                "openPositionCount": report["tradeSimulation"]["openPositionCount"],
                "openPositions": report["tradeSimulation"]["openPositions"],
                "maxDrawdown": report["tradeSimulation"]["maxDrawdown"],
                "winRate": report["tradeSimulation"]["winRate"],
                "tradeCount": report["tradeSimulation"]["tradeCount"],
                "trades": report["tradeSimulation"]["trades"],
                "tradeEvents": report["tradeSimulation"]["tradeEvents"],
                "equityCurve": report["tradeSimulation"]["equityCurve"],
            })
        return report

    @staticmethod
    def _sample_diagnostics(frames: list[dict[str, Any]], signals: list[dict[str, Any]], config: RankTrendConfig) -> dict[str, Any]:
        required = max(get_macd_min_samples(config), max(config.momentumPeriods or [0]) + 1, 30)
        stable_macd_bars = int(config.macdSlow) + int(config.macdSignal)
        status_counts: dict[str, int] = {"ok": 0, "degraded": 0, "insufficient": 0}
        sample_counts: list[int] = []
        per_day: dict[str, dict[str, Any]] = {}
        for signal in signals:
            quality = (((signal.get("rankTrend") or {}).get("meta") or {}).get("sampleQuality") or {})
            status = str(quality.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            count = int(quality.get("sampleCount") or 0)
            sample_counts.append(count)
            date = str(signal.get("tradingDate") or "")
            row = per_day.setdefault(date, {"tradingDate": date, "total": 0, "ok": 0, "degraded": 0, "insufficient": 0})
            row["total"] += 1
            row[status] = row.get(status, 0) + 1
        total = len(signals)
        first_stable = next((frame for idx, frame in enumerate(frames) if idx + 1 >= stable_macd_bars), None)
        warnings = []
        if status_counts.get("insufficient", 0):
            warnings.append(f"存在 {status_counts['insufficient']} 条样本严重不足信号，不应作为强交易依据。")
        if total and share(status_counts.get("degraded", 0), total) > 0.25:
            warnings.append("degraded 样本占比偏高，早期信号需要谨慎解读。")
        ok_share = share(status_counts.get("ok", 0), total)
        if total and ok_share < 0.6:
            warnings.append(f"样本 OK 占比 {ok_share * 100:.2f}% 偏低，早期信号和 MACD 解释需要降权。")
        if len(frames) < stable_macd_bars:
            warnings.append(f"当前样本 {len(frames)} bars 少于 MACD 稳定观察口径 {stable_macd_bars} bars。")
        return {
            "snapshotCount": len(frames),
            "signalCount": total,
            "requiredTechnicalBars": required,
            "macdMinimumBars": int(config.macdSlow),
            "macdStableObservationBars": stable_macd_bars,
            "firstMacdStableSnapshotId": first_stable.get("snapshotId") if first_stable else None,
            "sampleCountMin": min(sample_counts) if sample_counts else None,
            "sampleCountMax": max(sample_counts) if sample_counts else None,
            "sampleCountAvg": _round_or_none(average(sample_counts)),
            "statusCounts": status_counts,
            "statusShares": {key: share(value, total) for key, value in status_counts.items()},
            "daily": sorted(per_day.values(), key=lambda item: item["tradingDate"]),
            "warnings": warnings,
        }

    @staticmethod
    def _data_quality_summary(quality_gate: dict[str, Any] | None, sample_diagnostics: dict[str, Any], macd_diagnostics: dict[str, Any]) -> dict[str, Any]:
        gate = quality_gate if isinstance(quality_gate, dict) else {}
        stats = gate.get("stats") if isinstance(gate.get("stats"), dict) else {}
        gate_issues = [str(item) for item in (gate.get("issues") or [])]
        sample_warnings = [str(item) for item in (sample_diagnostics.get("warnings") or [])]
        warnings: list[str] = []

        low_hotlist_count = int(stats.get("lowHotlistCount") or 0)
        empty_hotlist_count = int(stats.get("emptyHotlistCount") or 0)
        target_frames = int(stats.get("targetFrames") or sample_diagnostics.get("snapshotCount") or 0)
        ok_share = float((sample_diagnostics.get("statusShares") or {}).get("ok") or 0)
        degraded_share = float((sample_diagnostics.get("statusShares") or {}).get("degraded") or 0)
        has_stable_macd = bool(macd_diagnostics.get("hasStableObservationBars"))

        warnings.extend(gate_issues)
        warnings.extend(sample_warnings)
        if low_hotlist_count:
            threshold = int(stats.get("researchMinHotlistSize") or 20)
            warnings.append(f"存在 {low_hotlist_count} 个低热榜快照（低于 {threshold} 行），横截面分位和候选池排序可信度下降。")
        if empty_hotlist_count:
            warnings.append(f"存在 {empty_hotlist_count} 个空热榜快照，正式研究应重新导入或剔除。")
        if not has_stable_macd:
            warnings.append("MACD 尚未达到稳定观察窗口，MACD 相关解释只作辅助。")

        severity = "pass"
        if str(gate.get("severity") or "") == "fail" or empty_hotlist_count:
            severity = "fail"
        elif warnings:
            severity = "warn"

        research_grade = "research_ready"
        if severity == "fail":
            research_grade = "blocked"
        elif low_hotlist_count or ok_share < 0.6 or not has_stable_macd:
            research_grade = "degraded"

        unique_warnings = list(dict.fromkeys(warnings))
        recommendation = "可以作为正式研究样本。"
        if research_grade == "blocked":
            recommendation = "不建议继续使用该结果验收；请重新导入或剔除空热榜/非法快照后再跑。"
        elif research_grade == "degraded":
            recommendation = "可以用于候选观察，但不要直接据此定参数；优先补齐低热榜快照或扩大样本后复跑。"

        return {
            "severity": severity,
            "researchGrade": research_grade,
            "recommendation": recommendation,
            "qualityGate": gate,
            "snapshotCount": target_frames,
            "lowHotlistCount": low_hotlist_count,
            "emptyHotlistCount": empty_hotlist_count,
            "lowHotlistShare": share(low_hotlist_count, target_frames),
            "hotlistCountMin": stats.get("hotlistCountMin"),
            "hotlistCountAvg": stats.get("hotlistCountAvg"),
            "hotlistCountMax": stats.get("hotlistCountMax"),
            "lowHotlistExamples": stats.get("lowHotlistExamples") or [],
            "sampleOkShare": ok_share,
            "sampleDegradedShare": degraded_share,
            "sampleInsufficientShare": float((sample_diagnostics.get("statusShares") or {}).get("insufficient") or 0),
            "macdStable": has_stable_macd,
            "macdStableObservationBars": macd_diagnostics.get("stableObservationBars"),
            "warnings": unique_warnings,
        }

    @staticmethod
    def _macd_diagnostics(config: RankTrendConfig, frames: list[dict[str, Any]]) -> dict[str, Any]:
        minimum = get_macd_min_samples(config)
        stable = int(config.macdSlow) + int(config.macdSignal)
        return {
            "macdFast": int(config.macdFast),
            "macdSlow": int(config.macdSlow),
            "macdSignal": int(config.macdSignal),
            "minimumBars": minimum,
            "stableObservationBars": stable,
            "snapshotCount": len(frames),
            "hasMinimumBars": len(frames) >= minimum,
            "hasStableObservationBars": len(frames) >= stable,
            "role": "auxiliary_observation_only",
            "note": "MACD 金叉/死叉只作为入场前观察信号，不作为独立买卖触发器。",
        }

    @staticmethod
    def _control_backtests(frames: list[dict[str, Any]], signals: list[dict[str, Any]], trade_config: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for definition in CONTROL_STRATEGIES:
            config = {**trade_config, "entryStrategy": definition["key"]}
            result = TradeSimulator().run(frames, signals, config)
            rows.append({
                "key": definition["key"],
                "label": definition["label"],
                "description": definition["description"],
                "totalReturn": result.get("totalReturn"),
                "realizedReturn": result.get("realizedReturn"),
                "unrealizedProfit": result.get("unrealizedProfit"),
                "sharpe": result.get("sharpe"),
                "maxDrawdown": result.get("maxDrawdown"),
                "winRate": result.get("winRate"),
                "tradeCount": result.get("tradeCount"),
                "openPositionCount": result.get("openPositionCount"),
            })
        return rows

    @staticmethod
    def _trade_diagnostics(simulation: dict[str, Any]) -> dict[str, Any]:
        trades = simulation.get("trades") or []
        events = simulation.get("tradeEvents") or []
        open_positions = simulation.get("openPositions") or []
        profits = [float(trade.get("profit") or 0) for trade in trades]
        by_reason: dict[str, dict[str, Any]] = {}
        by_tier: dict[str, dict[str, Any]] = {}
        holding_bars = [int(trade.get("holdingBars") or 0) for trade in trades]

        def add_group(target: dict[str, dict[str, Any]], key: str, trade: dict[str, Any]) -> None:
            row = target.setdefault(key or "-", {"key": key or "-", "count": 0, "profit": 0.0, "wins": 0})
            row["count"] += 1
            row["profit"] += float(trade.get("profit") or 0)
            if float(trade.get("profit") or 0) > 0:
                row["wins"] += 1

        for trade in trades:
            add_group(by_reason, str(trade.get("reason") or "-"), trade)
            add_group(by_tier, str(trade.get("candidateTier") or "-"), trade)

        best = sorted(trades, key=lambda item: float(item.get("profit") or 0), reverse=True)[:5]
        worst = sorted(trades, key=lambda item: float(item.get("profit") or 0))[:5]

        def finalize(rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {
                    **row,
                    "profit": round(float(row["profit"]), 2),
                    "avgProfit": round(float(row["profit"]) / row["count"], 2) if row["count"] else 0,
                    "winRate": share(int(row["wins"]), int(row["count"])),
                }
                for row in sorted(rows.values(), key=lambda item: abs(float(item["profit"])), reverse=True)
            ]

        return {
            "tradeCount": len(trades),
            "eventCount": len(events),
            "openPositionCount": len(open_positions),
            "profitSum": round(sum(profits), 2),
            "bestTrades": best,
            "worstTrades": worst,
            "byExitReason": finalize(by_reason),
            "byCandidateTier": finalize(by_tier),
            "holdingBars": {
                "min": min(holding_bars) if holding_bars else None,
                "max": max(holding_bars) if holding_bars else None,
                "avg": _round_or_none(average(holding_bars)),
            },
            "openPositions": open_positions,
            "matchingDiagnostics": simulation.get("matchingDiagnostics") or {},
            "skippedOrderCount": simulation.get("skippedOrderCount") or 0,
        }


class Optimizer:
    def run(self, frames: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, Any]:
        random_seed = int(request.get("random_seed") or 0)
        rng = random.Random(random_seed)
        search_space = request.get("search_space") or {}
        if not search_space:
            search_space = {
                "maxPositions": [3, 5, 8],
                "takeProfit": [0.08, 0.12, 0.16],
                "stopLoss": [-0.04, -0.06, -0.08],
            }
        search_space = self._normalize_search_space(search_space)
        candidates = self._candidates(search_space)
        method = str(request.get("method") or "grid").strip().lower()
        if method not in {"grid", "random", "bayesian"}:
            raise ValueError(f"unsupported optimization method: {method}")
        max_trials = max(1, int(request.get("max_trials") or request.get("trials") or 12))
        total_candidate_count = len(candidates)
        if method == "random":
            rng.shuffle(candidates)
        trials = []
        backtest_artifacts = []
        signal_cache: dict[str, list[dict[str, Any]]] = {}
        base_backtest = request.get("backtest") or {}
        base_strategy_config = base_backtest.get("strategy_config") or base_backtest.get("strategyConfig") or {}
        base_trade_config = base_backtest.get("trade_config") or base_backtest.get("tradeConfig") or {}
        strategy_name = normalize_strategy_name(request.get("strategy_name") or request.get("strategyName") or base_backtest.get("strategy_name") or base_backtest.get("strategyName") or base_trade_config.get("entryStrategy") or base_trade_config.get("strategyName"))
        base_ranktrend_config = RankTrendConfig.from_patch(base_strategy_config)
        quality_signals = RankTrendPythonEngine(base_ranktrend_config).replay(frames, meta={"sampleQuality": "ok", "warnings": []})
        data_quality = BacktestEngine._data_quality_summary(
            request.get("quality_gate"),
            BacktestEngine._sample_diagnostics(frames, quality_signals, base_ranktrend_config),
            BacktestEngine._macd_diagnostics(base_ranktrend_config, frames),
        )
        split = self._split_frames(frames, request)
        objective = str(request.get("objective") or "return")
        optimizer_meta: dict[str, Any] = {"name": method}
        if method == "bayesian":
            trials, backtest_artifacts, optimizer_meta = self._run_optuna_trials(
                search_space,
                max_trials,
                random_seed,
                split,
                base_strategy_config,
                base_trade_config,
                strategy_name,
                objective,
                request,
                signal_cache,
            )
            candidates = trials
        else:
            candidates = candidates[:max_trials]
            for index, params in enumerate(candidates, start=1):
                trial, artifacts = self._evaluate_trial(
                    index,
                    params,
                    split,
                    base_strategy_config,
                    base_trade_config,
                    strategy_name,
                    objective,
                    request,
                    signal_cache,
                    source=method,
                )
                trials.append(trial)
                backtest_artifacts.extend(artifacts)
        trials.sort(key=lambda item: (item.get("status") == "completed", self._score_value(item.get("score"))), reverse=True)
        for rank, trial in enumerate(trials, start=1):
            trial["rank"] = rank
        completed_trials = [trial for trial in trials if trial.get("status") == "completed"]
        best = completed_trials[0] if completed_trials else None
        walk_forward = self._walk_forward(
            frames,
            completed_trials,
            request,
            base_strategy_config,
            base_trade_config,
            strategy_name,
            objective,
            signal_cache,
        )
        experiment = self._experiment_summary(split, request, total_candidate_count, len(candidates), trials, best, walk_forward, data_quality)
        return {
            "method": method,
            "optimizer": optimizer_meta["name"],
            "optimizerMeta": optimizer_meta,
            "strategyName": strategy_name,
            "strategy_name": strategy_name,
            "objective": objective,
            "trialCount": len(trials),
            "completedTrialCount": len(completed_trials),
            "failedTrialCount": len(trials) - len(completed_trials),
            "strategyRunCount": len(signal_cache),
            "experiment": experiment,
            "dataQuality": data_quality,
            "overfitRisk": experiment["overfitRisk"],
            "parameterStability": self._parameter_stability(completed_trials),
            "walkForward": walk_forward,
            "best": best,
            "trials": trials,
            "results": trials,
            "warnings": experiment["warnings"],
            "backtestArtifacts": backtest_artifacts,
        }

    def _evaluate_trial(
        self,
        index: int,
        params: dict[str, Any],
        split: dict[str, Any],
        base_strategy_config: dict[str, Any],
        base_trade_config: dict[str, Any],
        strategy_name: str,
        objective: str,
        request: dict[str, Any],
        signal_cache: dict[str, list[dict[str, Any]]],
        source: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        trial_id = f"trial_{index:04d}"
        strategy_config = {**base_strategy_config, **self._to_strategy_config(params)}
        trade_config = {**base_trade_config, **self._to_trade_config(params), "entryStrategy": strategy_name}
        config_hash = stable_hash(
            {
                "dataset_id": request.get("dataset_id"),
                "snapshot_type": request.get("snapshot_type"),
                "strategy_name": strategy_name,
                "strategy_config": strategy_config,
                "trade_config": trade_config,
                "parameters": params,
                "split": split["metadata"],
            }
        )
        try:
            train_eval = self._evaluate_phase(
                "train",
                split["train_frames"],
                split["train_signal_frames"],
                params,
                strategy_config,
                trade_config,
                strategy_name,
                trial_id,
                config_hash,
                request,
                signal_cache,
            )
            validation_eval = None
            if split["validation_frames"]:
                validation_eval = self._evaluate_phase(
                    "validation",
                    split["validation_frames"],
                    split["validation_signal_frames"],
                    params,
                    strategy_config,
                    trade_config,
                    strategy_name,
                    trial_id,
                    config_hash,
                    request,
                    signal_cache,
                )
            score_details = self._score_trial(
                train_eval["simulation"],
                validation_eval["simulation"] if validation_eval else None,
                objective,
                request,
            )
            trial = {
                "trialId": trial_id,
                "trial_id": trial_id,
                "trialIndex": index,
                "source": source,
                "status": "completed",
                "parameters": params,
                "configHash": config_hash,
                "config_hash": config_hash,
                "score": score_details["score"],
                "scoreDetails": score_details,
                "train": self._phase_public(train_eval, objective),
                "validation": self._phase_public(validation_eval, objective) if validation_eval else None,
                "metrics": (validation_eval or train_eval)["metrics"],
                "stability": self._trial_stability(train_eval["metrics"], validation_eval["metrics"] if validation_eval else None, score_details),
            }
            artifacts = [train_eval["artifact"]]
            if validation_eval:
                artifacts.append(validation_eval["artifact"])
        except Exception as error:
            trial = {
                "trialId": trial_id,
                "trial_id": trial_id,
                "trialIndex": index,
                "source": source,
                "status": "failed",
                "parameters": params,
                "configHash": config_hash,
                "config_hash": config_hash,
                "score": -1_000_000_000.0,
                "error": str(error),
            }
            artifacts = []
        return trial, artifacts

    def _run_optuna_trials(
        self,
        search_space: dict[str, list[Any]],
        max_trials: int,
        random_seed: int,
        split: dict[str, Any],
        base_strategy_config: dict[str, Any],
        base_trade_config: dict[str, Any],
        strategy_name: str,
        objective: str,
        request: dict[str, Any],
        signal_cache: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        try:
            import optuna
        except ImportError as error:
            raise ValueError("method=bayesian requires optuna; install quant-board requirements first") from error

        startup_trials = max(1, min(max_trials, int(request.get("startup_trials") or request.get("startupTrials") or min(10, max_trials))))
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        sampler = optuna.samplers.TPESampler(seed=random_seed, n_startup_trials=startup_trials)
        study = optuna.create_study(direction="maximize", sampler=sampler)
        artifacts: list[dict[str, Any]] = []

        def objective_fn(optuna_trial: Any) -> float:
            params = self._suggest_params(optuna_trial, search_space)
            trial, trial_artifacts = self._evaluate_trial(
                optuna_trial.number + 1,
                params,
                split,
                base_strategy_config,
                base_trade_config,
                strategy_name,
                objective,
                request,
                signal_cache,
                source="optuna_tpe",
            )
            trial["optunaTrialNumber"] = optuna_trial.number
            trial["optunaParams"] = dict(optuna_trial.params)
            optuna_trial.set_user_attr("trial", trial)
            artifacts.extend(trial_artifacts)
            if trial.get("status") != "completed":
                return -1_000_000_000.0
            return self._score_value(trial.get("score"))

        study.optimize(objective_fn, n_trials=max_trials, show_progress_bar=False)
        trials = [
            trial.user_attrs["trial"]
            for trial in sorted(study.trials, key=lambda item: item.number)
            if "trial" in trial.user_attrs
        ]
        meta = {
            "name": "optuna_tpe",
            "library": "optuna",
            "sampler": "TPESampler",
            "startupTrials": startup_trials,
            "studyBestValue": study.best_value if trials else None,
        }
        return trials, artifacts, meta

    @staticmethod
    def _normalize_search_space(space: dict[str, Any]) -> dict[str, list[Any]]:
        if not isinstance(space, dict):
            raise ValueError("search_space must be an object")
        normalized: dict[str, list[Any]] = {}
        for key, values in space.items():
            if isinstance(values, dict):
                choices = values.get("choices") or values.get("values")
                if not isinstance(choices, list):
                    raise ValueError(f"search_space.{key} range specs are not supported yet; use a choices list")
                values = choices
            if not isinstance(values, list) or not values:
                raise ValueError(f"search_space.{key} must be a non-empty list")
            normalized[str(key)] = list(values)
        if not normalized:
            raise ValueError("search_space has no optimizable parameters")
        return normalized

    @staticmethod
    def _suggest_params(trial: Any, search_space: dict[str, list[Any]]) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for key, values in search_space.items():
            index = trial.suggest_int(f"{key}__idx", 0, len(values) - 1)
            params[key] = values[index]
        return params

    @staticmethod
    def _candidates(space: dict[str, list[Any]]) -> list[dict[str, Any]]:
        keys = list(space.keys())
        values = [space[key] for key in keys]
        return [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    @staticmethod
    def _to_trade_config(params: dict[str, Any]) -> dict[str, Any]:
        mapped = dict(params)
        mapped.pop("momentumPeriods", None)
        mapped.pop("macdFast", None)
        mapped.pop("macdSlow", None)
        mapped.pop("macdSignal", None)
        if "takeProfitPct" in mapped:
            mapped["takeProfit"] = mapped.pop("takeProfitPct")
        if "stopLossPct" in mapped:
            mapped["stopLoss"] = -abs(float(mapped.pop("stopLossPct")))
        if "initialCash" in mapped:
            mapped["initialCapital"] = mapped.pop("initialCash")
        return mapped

    @staticmethod
    def _to_strategy_config(params: dict[str, Any]) -> dict[str, Any]:
        mapped: dict[str, Any] = {}
        if "momentumPeriods" in params:
            mapped["momentumPeriods"] = params["momentumPeriods"]
        for key in ("macdFast", "macdSlow", "macdSignal"):
            if key in params:
                mapped[key] = params[key]
        return mapped

    @staticmethod
    def _freeze(value: Any) -> str:
        if isinstance(value, dict):
            return "{" + ",".join(f"{key}:{Optimizer._freeze(value[key])}" for key in sorted(value)) + "}"
        if isinstance(value, list):
            return "[" + ",".join(Optimizer._freeze(item) for item in value) + "]"
        return repr(value)

    @staticmethod
    def _score(result: dict[str, Any], objective: str) -> float:
        if objective == "max_drawdown":
            return -abs(float(result.get("maxDrawdown") or 0))
        if objective == "sharpe":
            return float(result.get("sharpe") or 0)
        if objective == "win_rate":
            trade_count = int(result.get("tradeCount") or 0)
            low_trade_penalty = max(0, 3 - trade_count) * 0.05
            return float(result.get("winRate") or 0) - low_trade_penalty
        if objective == "risk_adjusted":
            total_return = float(result.get("totalReturn") or 0)
            drawdown = abs(float(result.get("maxDrawdown") or 0))
            sharpe = float(result.get("sharpe") or 0)
            return total_return - drawdown * 1.5 + sharpe * 0.02
        return float(result.get("totalReturn") or 0)

    @staticmethod
    def _objective_for_phase(objective: str) -> str:
        return "risk_adjusted" if objective == "stability" else objective

    def _score_trial(
        self,
        train_result: dict[str, Any],
        validation_result: dict[str, Any] | None,
        objective: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        phase_objective = self._objective_for_phase(objective)
        train_score = self._score(train_result, phase_objective)
        if not validation_result:
            return {
                "score": round(train_score, 6),
                "objective": objective,
                "trainScore": round(train_score, 6),
                "validationScore": None,
                "generalizationGap": None,
                "overfitPenalty": 0.0,
                "lowTradeCountPenalty": 0.0,
                "overfitRisk": "high",
                "reason": "未设置 validation_range 或自动验证拆分，分数完全来自样本内。",
            }

        validation_score = self._score(validation_result, phase_objective)
        gap = train_score - validation_score
        min_validation_trades = int(request.get("min_validation_trades") or request.get("minValidationTrades") or 3)
        validation_trades = int(validation_result.get("tradeCount") or 0)
        low_trade_penalty = max(0, min_validation_trades - validation_trades) * 0.05
        overfit_penalty = max(0.0, gap) * 0.25
        if objective == "stability":
            base_score = self._score(validation_result, "risk_adjusted")
            score = base_score - overfit_penalty - low_trade_penalty
        else:
            score = validation_score - overfit_penalty - low_trade_penalty

        risk = "low"
        reason = "validation 与 train 表现接近。"
        if validation_trades < min_validation_trades:
            risk = "medium"
            reason = f"validation 交易数 {validation_trades} 低于最低观察数 {min_validation_trades}。"
        if (float(train_result.get("totalReturn") or 0) > 0 and float(validation_result.get("totalReturn") or 0) < 0) or gap > max(0.05, abs(train_score) * 0.75):
            risk = "high"
            reason = "train 明显优于 validation，存在参数贴合样本内的风险。"

        return {
            "score": round(score, 6),
            "objective": objective,
            "phaseObjective": phase_objective,
            "trainScore": round(train_score, 6),
            "validationScore": round(validation_score, 6),
            "generalizationGap": round(gap, 6),
            "overfitPenalty": round(overfit_penalty, 6),
            "lowTradeCountPenalty": round(low_trade_penalty, 6),
            "overfitRisk": risk,
            "reason": reason,
        }

    def _evaluate_phase(
        self,
        phase: str,
        phase_frames: list[dict[str, Any]],
        signal_frames: list[dict[str, Any]],
        params: dict[str, Any],
        strategy_config: dict[str, Any],
        trade_config: dict[str, Any],
        strategy_name: str,
        trial_id: str,
        config_hash: str,
        request: dict[str, Any],
        signal_cache: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        signal_key = self._freeze(
            {
                "phase": phase,
                "first": signal_frames[0].get("snapshotId") if signal_frames else "",
                "last": signal_frames[-1].get("snapshotId") if signal_frames else "",
                "strategy": strategy_config,
            }
        )
        if signal_key not in signal_cache:
            config = RankTrendConfig.from_patch(strategy_config)
            signal_cache[signal_key] = RankTrendPythonEngine(config).replay(signal_frames, meta={"sampleQuality": "ok", "warnings": []})
        phase_snapshot_ids = {str(frame.get("snapshotId")) for frame in phase_frames}
        phase_signals = [signal for signal in signal_cache[signal_key] if str(signal.get("snapshotId")) in phase_snapshot_ids]
        simulation = TradeSimulator().run(phase_frames, phase_signals, trade_config)
        metrics = self._metrics(simulation, len(phase_signals))
        phase_config = RankTrendConfig.from_patch(strategy_config)
        sample_diagnostics = BacktestEngine._sample_diagnostics(phase_frames, phase_signals, phase_config)
        macd_diagnostics = BacktestEngine._macd_diagnostics(phase_config, phase_frames)
        data_quality = BacktestEngine._data_quality_summary(request.get("quality_gate"), sample_diagnostics, macd_diagnostics)
        run_id = new_id("bt")
        artifact_result = {
            "strategyName": strategy_name,
            "strategy_name": strategy_name,
            "phase": phase,
            "optimizationRunId": request.get("optimization_run_id"),
            "trialId": trial_id,
            "trial_id": trial_id,
            "parameters": params,
            "configHash": config_hash,
            "signalCount": len(phase_signals),
            "signals": [],
            "sampleDiagnostics": sample_diagnostics,
            "macdDiagnostics": macd_diagnostics,
            "dataQuality": data_quality,
            "warnings": data_quality["warnings"],
            "tradeSimulation": simulation,
            "tradeDiagnostics": BacktestEngine._trade_diagnostics(simulation),
            "totalReturn": simulation.get("totalReturn"),
            "sharpe": simulation.get("sharpe"),
            "tradeSharpe": simulation.get("tradeSharpe"),
            "avgTradeReturn": simulation.get("avgTradeReturn"),
            "tradeReturnStd": simulation.get("tradeReturnStd"),
            "realizedReturn": simulation.get("realizedReturn"),
            "realizedProfit": simulation.get("realizedProfit"),
            "unrealizedProfit": simulation.get("unrealizedProfit"),
            "openPositionCount": simulation.get("openPositionCount"),
            "maxDrawdown": simulation.get("maxDrawdown"),
            "winRate": simulation.get("winRate"),
            "tradeCount": simulation.get("tradeCount"),
            "trades": simulation.get("trades") or [],
            "tradeEvents": simulation.get("tradeEvents") or [],
            "equityCurve": simulation.get("equityCurve") or [],
            "notes": [
                f"该回测由优化 trial {trial_id} 的 {phase} 分段自动生成。",
                "trial 回测只保存交易模拟追溯信息，不重复保存完整 RankTrend signals。",
            ],
        }
        artifact_request = {
            "dataset_id": request.get("dataset_id"),
            "snapshot_type": request.get("snapshot_type"),
            "strategy_name": strategy_name,
            "random_seed": request.get("random_seed"),
            "phase": phase,
            "optimization_run_id": request.get("optimization_run_id"),
            "trial_id": trial_id,
            "parameters": params,
            "strategy_config": strategy_config,
            "trade_config": trade_config,
            "config_hash": config_hash,
            "range": self._frame_range(phase_frames),
        }
        return {
            "phase": phase,
            "runId": run_id,
            "range": self._frame_range(phase_frames),
            "signalFrameRange": self._frame_range(signal_frames),
            "metrics": metrics,
            "simulation": simulation,
            "artifact": {
                "runId": run_id,
                "phase": phase,
                "trialId": trial_id,
                "configHash": config_hash,
                "request": artifact_request,
                "result": artifact_result,
            },
        }

    def _phase_public(self, phase_eval: dict[str, Any], objective: str) -> dict[str, Any]:
        phase_objective = self._objective_for_phase(objective)
        return {
            "runId": phase_eval["runId"],
            "run_id": phase_eval["runId"],
            "range": phase_eval["range"],
            "signalFrameRange": phase_eval["signalFrameRange"],
            "score": round(self._score(phase_eval["simulation"], phase_objective), 6),
            "metrics": phase_eval["metrics"],
        }

    @staticmethod
    def _metrics(result: dict[str, Any], signal_count: int) -> dict[str, Any]:
        return {
            "entryStrategy": result.get("entryStrategy"),
            "totalReturn": result.get("totalReturn", 0),
            "realizedReturn": result.get("realizedReturn", 0),
            "sharpe": result.get("sharpe"),
            "maxDrawdown": result.get("maxDrawdown", 0),
            "winRate": result.get("winRate", 0),
            "tradeCount": result.get("tradeCount", 0),
            "skippedOrderCount": result.get("skippedOrderCount", 0),
            "openPositionCount": result.get("openPositionCount", 0),
            "signalCount": signal_count,
        }

    @staticmethod
    def _trial_stability(
        train_metrics: dict[str, Any],
        validation_metrics: dict[str, Any] | None,
        score_details: dict[str, Any],
    ) -> dict[str, Any]:
        if not validation_metrics:
            return {
                "overfitRisk": "high",
                "returnGap": None,
                "sharpeGap": None,
                "tradeCountGap": None,
                "reason": "未设置 validation 分段。",
            }
        return {
            "overfitRisk": score_details.get("overfitRisk"),
            "returnGap": _round_or_none(float(train_metrics.get("totalReturn") or 0) - float(validation_metrics.get("totalReturn") or 0)),
            "sharpeGap": _round_or_none(float(train_metrics.get("sharpe") or 0) - float(validation_metrics.get("sharpe") or 0)),
            "tradeCountGap": int(train_metrics.get("tradeCount") or 0) - int(validation_metrics.get("tradeCount") or 0),
            "reason": score_details.get("reason"),
        }

    def _split_frames(self, frames: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, Any]:
        validation_mode = str(request.get("validation_mode") or request.get("validationMode") or "none")
        validation_ratio = self._clamp(float(request.get("validation_ratio") or request.get("validationRatio") or 0.3), 0.05, 0.8)
        warmup_bars = max(0, int(request.get("validation_warmup_bars") or request.get("validationWarmupBars") or request.get("warmup_bars") or 40))
        train_range = self._normalize_range(request.get("train_range") or request.get("trainRange"))
        validation_range = self._normalize_range(request.get("validation_range") or request.get("validationRange"))
        warnings: list[str] = []
        split_mode = validation_mode

        if train_range or validation_range:
            split_mode = "explicit_range"
            validation_frames = self._filter_by_range(frames, validation_range) if validation_range else []
            if train_range:
                train_frames = self._filter_by_range(frames, train_range)
            elif validation_frames:
                validation_start = str(validation_frames[0].get("tradingDate") or "")
                train_frames = [frame for frame in frames if str(frame.get("tradingDate") or "") < validation_start]
            else:
                train_frames = frames
        elif validation_mode in ("auto", "auto_split", "ratio", "chronological"):
            train_frames, validation_frames = self._auto_split(frames, validation_ratio)
            split_mode = "auto_split"
        else:
            train_frames = frames
            validation_frames = []
            split_mode = "none"

        if not train_frames:
            warnings.append("train 分段为空，已回退为全样本训练。")
            train_frames = frames
        if split_mode != "none" and not validation_frames:
            warnings.append("validation 分段为空，本次优化只能按样本内结果排序。")
        if validation_frames and len(validation_frames) < 10:
            warnings.append(f"validation 只有 {len(validation_frames)} 个快照，样本外指标波动会较大。")

        validation_signal_frames = self._with_warmup(frames, validation_frames, warmup_bars)
        metadata = {
            "mode": split_mode,
            "validationRatio": validation_ratio if split_mode == "auto_split" else None,
            "validationWarmupBars": warmup_bars,
            "train": self._frame_range(train_frames),
            "validation": self._frame_range(validation_frames) if validation_frames else None,
            "validationSignalFrames": self._frame_range(validation_signal_frames) if validation_signal_frames else None,
            "hasValidation": bool(validation_frames),
        }
        return {
            "train_frames": train_frames,
            "train_signal_frames": train_frames,
            "validation_frames": validation_frames,
            "validation_signal_frames": validation_signal_frames,
            "metadata": metadata,
            "warnings": warnings,
        }

    @staticmethod
    def _auto_split(frames: list[dict[str, Any]], validation_ratio: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        dates = sorted({str(frame.get("tradingDate") or "") for frame in frames if frame.get("tradingDate")})
        if len(dates) >= 3:
            validation_date_count = max(1, min(len(dates) - 1, math.ceil(len(dates) * validation_ratio)))
            validation_dates = set(dates[-validation_date_count:])
            train_frames = [frame for frame in frames if str(frame.get("tradingDate") or "") not in validation_dates]
            validation_frames = [frame for frame in frames if str(frame.get("tradingDate") or "") in validation_dates]
            return train_frames, validation_frames
        split_index = max(1, min(len(frames) - 1, math.ceil(len(frames) * (1 - validation_ratio)))) if len(frames) > 1 else len(frames)
        return frames[:split_index], frames[split_index:]

    @staticmethod
    def _with_warmup(frames: list[dict[str, Any]], phase_frames: list[dict[str, Any]], warmup_bars: int) -> list[dict[str, Any]]:
        if not phase_frames:
            return []
        first_id = str(phase_frames[0].get("snapshotId"))
        first_index = next((idx for idx, frame in enumerate(frames) if str(frame.get("snapshotId")) == first_id), 0)
        start = max(0, first_index - warmup_bars)
        return frames[start:first_index] + phase_frames

    @staticmethod
    def _normalize_range(value: Any) -> tuple[str | None, str | None] | None:
        if not value:
            return None
        if isinstance(value, dict):
            start = value.get("start") or value.get("startDate") or value.get("from")
            end = value.get("end") or value.get("endDate") or value.get("to")
            return (str(start) if start else None, str(end) if end else None)
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return (str(value[0]) if value[0] else None, str(value[1]) if value[1] else None)
        return None

    @staticmethod
    def _filter_by_range(frames: list[dict[str, Any]], value: tuple[str | None, str | None]) -> list[dict[str, Any]]:
        start, end = value
        result = frames
        if start:
            result = [frame for frame in result if str(frame.get("tradingDate") or "") >= start]
        if end:
            result = [frame for frame in result if str(frame.get("tradingDate") or "") <= end]
        return result

    @staticmethod
    def _frame_range(frames: list[dict[str, Any]]) -> dict[str, Any]:
        if not frames:
            return {"snapshotCount": 0, "startDate": None, "endDate": None, "startSnapshotId": None, "endSnapshotId": None}
        return {
            "snapshotCount": len(frames),
            "startDate": frames[0].get("tradingDate"),
            "endDate": frames[-1].get("tradingDate"),
            "startSnapshotId": frames[0].get("snapshotId"),
            "endSnapshotId": frames[-1].get("snapshotId"),
        }

    def _experiment_summary(
        self,
        split: dict[str, Any],
        request: dict[str, Any],
        total_candidate_count: int,
        executed_candidate_count: int,
        trials: list[dict[str, Any]],
        best: dict[str, Any] | None,
        walk_forward: dict[str, Any] | None = None,
        data_quality: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        warnings = list(split.get("warnings") or [])
        has_validation = bool(split["metadata"].get("hasValidation"))
        has_walk_forward = bool((walk_forward or {}).get("segments"))
        if not has_validation:
            if has_walk_forward:
                overfit_risk = {"level": "medium", "reason": "未设置 validation_range，但已执行 walk-forward 分段复核。"}
            else:
                overfit_risk = {"level": "high", "reason": "未设置 validation_range 或自动拆分，结果只适合找候选参数。"}
                warnings.append("当前优化没有样本外验证，不能直接据此定参数。")
        else:
            best_risk = (((best or {}).get("scoreDetails") or {}).get("overfitRisk") or "medium")
            overfit_risk = {"level": best_risk, "reason": (((best or {}).get("scoreDetails") or {}).get("reason") or "已执行 train/validation 分段验证。")}
        warnings.extend((walk_forward or {}).get("warnings") or [])
        quality = data_quality or {}
        if quality.get("warnings"):
            warnings.extend(str(item) for item in quality.get("warnings") or [])
        if quality.get("researchGrade") in ("blocked", "degraded") and overfit_risk["level"] == "low":
            overfit_risk = {
                "level": "medium",
                "reason": f"{overfit_risk['reason']} 数据质量为 {quality.get('researchGrade')}，优化结论需降权。",
            }
        return {
            "datasetId": request.get("dataset_id"),
            "snapshotType": request.get("snapshot_type"),
            "method": request.get("method"),
            "objective": request.get("objective"),
            "randomSeed": request.get("random_seed"),
            "totalCandidateCount": total_candidate_count,
            "executedCandidateCount": executed_candidate_count,
            "completedTrialCount": len([trial for trial in trials if trial.get("status") == "completed"]),
            "failedTrialCount": len([trial for trial in trials if trial.get("status") == "failed"]),
            "split": split["metadata"],
            "overfitRisk": overfit_risk,
            "walkForward": {
                "enabled": bool((walk_forward or {}).get("enabled")),
                "segmentCount": int((walk_forward or {}).get("segmentCount") or 0),
            },
            "warnings": warnings,
        }

    def _walk_forward(
        self,
        frames: list[dict[str, Any]],
        trials: list[dict[str, Any]],
        request: dict[str, Any],
        base_strategy_config: dict[str, Any],
        base_trade_config: dict[str, Any],
        strategy_name: str,
        objective: str,
        signal_cache: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        config = request.get("walk_forward")
        if config is None:
            config = request.get("walkForward")
        if not config:
            return {"enabled": False}
        if config is True:
            config = {}
        if not isinstance(config, dict):
            raise ValueError("walk_forward must be a boolean or object")
        if config.get("enabled") is False:
            return {"enabled": False}
        dates = sorted({str(frame.get("tradingDate") or "") for frame in frames if frame.get("tradingDate")})
        train_window = max(1, int(config.get("train_window_days") or config.get("trainWindowDays") or min(5, max(1, len(dates) - 1))))
        validation_window = max(1, int(config.get("validation_window_days") or config.get("validationWindowDays") or 1))
        step = max(1, int(config.get("step_days") or config.get("stepDays") or validation_window))
        top_trials = max(1, int(config.get("top_trials") or config.get("topTrials") or min(5, len(trials) or 1)))
        selected_trials = trials[:top_trials]
        if len(dates) < train_window + validation_window:
            return {
                "enabled": True,
                "mode": "rolling_top_trial_reselection",
                "trainWindowDays": train_window,
                "validationWindowDays": validation_window,
                "stepDays": step,
                "topTrials": top_trials,
                "segmentCount": 0,
                "segments": [],
                "aggregate": {"segmentCount": 0},
                "warnings": [f"walk-forward 需要至少 {train_window + validation_window} 个交易日，当前只有 {len(dates)} 个。"],
            }
        segments = []
        for offset in range(0, len(dates) - train_window - validation_window + 1, step):
            train_dates = set(dates[offset:offset + train_window])
            validation_dates = set(dates[offset + train_window:offset + train_window + validation_window])
            train_frames = [frame for frame in frames if str(frame.get("tradingDate") or "") in train_dates]
            validation_frames = [frame for frame in frames if str(frame.get("tradingDate") or "") in validation_dates]
            if not train_frames or not validation_frames:
                continue
            segment_trials = []
            split = {
                "train_frames": train_frames,
                "train_signal_frames": train_frames,
                "validation_frames": validation_frames,
                "validation_signal_frames": self._with_warmup(frames, validation_frames, int(config.get("validation_warmup_bars") or config.get("validationWarmupBars") or 40)),
                "metadata": {
                    "mode": "walk_forward",
                    "train": self._frame_range(train_frames),
                    "validation": self._frame_range(validation_frames),
                    "hasValidation": True,
                },
            }
            for candidate in selected_trials:
                params = candidate.get("parameters") or {}
                segment_trial, _ = self._evaluate_trial(
                    int(str(candidate.get("trialId") or "0").split("_")[-1] or 0),
                    params,
                    split,
                    base_strategy_config,
                    base_trade_config,
                    strategy_name,
                    objective,
                    request,
                    signal_cache,
                    source="walk_forward",
                )
                if segment_trial.get("status") == "completed":
                    segment_trials.append(
                        {
                            "trialId": candidate.get("trialId"),
                            "parameters": params,
                            "trainScore": ((segment_trial.get("scoreDetails") or {}).get("trainScore")),
                            "validationScore": ((segment_trial.get("scoreDetails") or {}).get("validationScore")),
                            "score": segment_trial.get("score"),
                            "trainMetrics": ((segment_trial.get("train") or {}).get("metrics")),
                            "validationMetrics": ((segment_trial.get("validation") or {}).get("metrics")),
                        }
                    )
            segment_trials.sort(key=lambda item: self._score_value(item.get("score")), reverse=True)
            if segment_trials:
                selected = segment_trials[0]
                segments.append(
                    {
                        "segmentId": len(segments) + 1,
                        "trainRange": self._frame_range(train_frames),
                        "validationRange": self._frame_range(validation_frames),
                        "selectedTrialId": selected.get("trialId"),
                        "selectedParameters": selected.get("parameters"),
                        "score": selected.get("score"),
                        "trainScore": selected.get("trainScore"),
                        "validationScore": selected.get("validationScore"),
                        "trainMetrics": selected.get("trainMetrics"),
                        "validationMetrics": selected.get("validationMetrics"),
                        "candidateCount": len(segment_trials),
                        "topTrials": segment_trials[:3],
                    }
                )
        warnings = [] if segments else ["walk-forward 没有生成有效分段，请检查交易日数量和窗口设置。"]
        return {
            "enabled": True,
            "mode": "rolling_top_trial_reselection",
            "trainWindowDays": train_window,
            "validationWindowDays": validation_window,
            "stepDays": step,
            "topTrials": top_trials,
            "segmentCount": len(segments),
            "segments": segments,
            "aggregate": self._walk_forward_aggregate(segments),
            "warnings": warnings,
        }

    @staticmethod
    def _walk_forward_aggregate(segments: list[dict[str, Any]]) -> dict[str, Any]:
        if not segments:
            return {"segmentCount": 0}
        validation_scores = [float(segment.get("validationScore") or 0) for segment in segments]
        returns = [
            float(((segment.get("validationMetrics") or {}).get("totalReturn") or 0))
            for segment in segments
        ]
        sharpes = [
            float(((segment.get("validationMetrics") or {}).get("sharpe") or 0))
            for segment in segments
        ]
        drawdowns = [
            float(((segment.get("validationMetrics") or {}).get("maxDrawdown") or 0))
            for segment in segments
        ]
        return {
            "segmentCount": len(segments),
            "avgValidationScore": round(sum(validation_scores) / len(validation_scores), 6),
            "avgValidationReturn": round(sum(returns) / len(returns), 6),
            "avgValidationSharpe": round(sum(sharpes) / len(sharpes), 6),
            "avgValidationMaxDrawdown": round(sum(drawdowns) / len(drawdowns), 6),
            "positiveReturnSegmentRate": share(len([value for value in returns if value > 0]), len(returns)),
        }

    def _parameter_stability(self, trials: list[dict[str, Any]]) -> dict[str, Any]:
        if not trials:
            return {"topTrialCount": 0, "parameters": [], "warnings": ["没有完成的 trial，无法做参数稳定性分析。"]}
        top_count = max(1, min(5, math.ceil(len(trials) * 0.2)))
        top_trials = trials[:top_count]
        parameter_keys = sorted({key for trial in top_trials for key in (trial.get("parameters") or {}).keys()})
        rows = []
        warnings = []
        for key in parameter_keys:
            values = [(trial.get("parameters") or {}).get(key) for trial in top_trials]
            frozen_counts: dict[str, int] = {}
            for value in values:
                frozen_counts[self._freeze(value)] = frozen_counts.get(self._freeze(value), 0) + 1
            numeric_values = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(float(value))]
            row: dict[str, Any] = {
                "key": key,
                "bestValue": (top_trials[0].get("parameters") or {}).get(key),
                "uniqueCount": len(frozen_counts),
                "topValues": [{"value": value, "count": count} for value, count in sorted(frozen_counts.items(), key=lambda item: item[1], reverse=True)],
            }
            if len(numeric_values) == len(values) and numeric_values:
                row.update(
                    {
                        "min": min(numeric_values),
                        "max": max(numeric_values),
                        "mean": round(sum(numeric_values) / len(numeric_values), 6),
                    }
                )
            if len(frozen_counts) == len(values) and len(values) > 1:
                warnings.append(f"top {top_count} 中 {key} 未形成集中取值。")
            rows.append(row)
        scores = [float(trial.get("score") or 0) for trial in top_trials]
        return {
            "topTrialCount": top_count,
            "topTrialIds": [trial.get("trialId") for trial in top_trials],
            "scoreSpread": round(max(scores) - min(scores), 6) if scores else None,
            "parameters": rows,
            "warnings": warnings,
        }

    @staticmethod
    def _clamp(value: float, lower: float, upper: float) -> float:
        if not math.isfinite(value):
            return lower
        return min(upper, max(lower, value))

    @staticmethod
    def _score_value(value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return -1_000_000_000.0
        return score if math.isfinite(score) else -1_000_000_000.0
