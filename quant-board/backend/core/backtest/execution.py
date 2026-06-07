from __future__ import annotations

from typing import Any

from backend.core.backtest.config import DEFAULT_TRADE_CONFIG
from backend.core.backtest.metrics import (
    _first_finite,
    _first_number,
    _round_or_none,
    average,
    max_drawdown,
    share,
    short_cycle_sharpe,
)
from backend.core.backtest.strategy import normalize_strategy_name


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
                    if strategy_key in {
                        "ranktrend_early_big_move_v2",
                        "ranktrend_early_big_move_v3",
                        "ranktrend_early_big_move_v3_no_lifecycle_gate",
                        "ranktrend_early_big_move_v3_context_probe",
                        "ranktrend_early_big_move_v3_lifecycle_fusion",
                        "ranktrend_early_big_move_v3_a_main_risk_filter",
                        "ranktrend_early_big_move_v3_b_long_filter",
                    }:
                        pos["hotlistMissingBars"] = int(pos.get("hotlistMissingBars") or 0) + 1
                    signal = self._position_price_signal(frame, code, pos)
                    if not signal:
                        matching_stats["missingPriceRows"] += 1
                        continue
                elif strategy_key in {
                    "ranktrend_early_big_move_v2",
                    "ranktrend_early_big_move_v3",
                    "ranktrend_early_big_move_v3_no_lifecycle_gate",
                    "ranktrend_early_big_move_v3_context_probe",
                    "ranktrend_early_big_move_v3_lifecycle_fusion",
                    "ranktrend_early_big_move_v3_a_main_risk_filter",
                    "ranktrend_early_big_move_v3_b_long_filter",
                }:
                    pos["hotlistMissingBars"] = 0
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
                strategy_exit_reason = None
                if strategy_key == "ranktrend_jump":
                    should_exit, strategy_exit_reason = self._ranktrend_jump_exit_decision(signal, pos, gross_return, config)
                elif strategy_key in {
                    "ranktrend_early_big_move_v2",
                    "ranktrend_early_big_move_v3",
                    "ranktrend_early_big_move_v3_no_lifecycle_gate",
                    "ranktrend_early_big_move_v3_context_probe",
                    "ranktrend_early_big_move_v3_lifecycle_fusion",
                    "ranktrend_early_big_move_v3_a_main_risk_filter",
                    "ranktrend_early_big_move_v3_b_long_filter",
                }:
                    should_exit, strategy_exit_reason = self._ranktrend_early_big_move_v2_exit_decision(signal, pos, gross_return, config)
                else:
                    final_signal = ((((signal.get("rankTrend") or {}).get("decision") or {}).get("final") or {}).get("signal") or "hold")
                    should_exit = (final_signal == "sell" or signal["candidateTier"] == "D_EXIT_RISK" or (signal["candidateTier"] == "C_CROWDED" and signal["rankTrend"]["strategy"]["momentum"]["acceleration"] <= 0) or signal["rank"] > 50 or pos["holdingBars"] >= config["maxHoldingBars"] or gross_return <= config["stopLoss"] or gross_return >= config["takeProfit"])
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
                reason = exit_trigger or strategy_exit_reason or self._exit_reason(signal, pos, gross_return, config)
                net_return = profit / entry_cost_basis if entry_cost_basis else 0
                explanation = self._signal_explanation(signal, f"卖出：{reason}", pos)
                trade = {"code": code, "name": pos["name"], "entrySnapshotId": pos["entrySnapshotId"], "entrySignalSnapshotId": pos.get("entrySignalSnapshotId") or pos["entrySnapshotId"], "exitSnapshotId": frame["snapshotId"], "exitSignalSnapshotId": signal.get("snapshotId"), "entryTime": pos["entryTime"], "exitTime": frame["timestamp"], "entryTradingDate": pos.get("entryTradingDate"), "exitTradingDate": frame.get("tradingDate"), "entryPrice": pos["entryPrice"], "exitPrice": exit_price, "quantity": quantity, "holdingBars": pos["holdingBars"], "grossReturn": round((exit_price - pos["entryPrice"]) / pos["entryPrice"], 4) if pos["entryPrice"] else 0, "netReturn": round(net_return, 4), "entryCostBasis": round(entry_cost_basis, 2), "profit": round(profit, 2), "reason": reason, "explanation": explanation, "action": "sell", "price": exit_price, "rank": signal["rank"], "candidateTier": signal.get("candidateTier"), "stage": signal.get("stage"), "regime": signal.get("regime"), "executionMode": execution_mode, "fill": self._public_fill(fill)}
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
        exit_slice_wins = [trade for trade in trades if trade["netReturn"] > 0]
        round_trip_trades = self._round_trip_trades(trades, config)
        round_trip_wins = [trade for trade in round_trip_trades if trade["netReturn"] > 0]
        sharpe_metrics = short_cycle_sharpe(round_trip_trades, target_holding_days=float(config.get("targetHoldingDays") or 5.0))
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
        return {"enabled": True, "entryStrategy": strategy_key, "executionMode": execution_mode, "config": config, "totalReturn": round((final_equity - config["initialCapital"]) / config["initialCapital"], 4), "realizedReturn": round(realized_profit / config["initialCapital"], 4), "realizedProfit": realized_profit, "unrealizedMarkProfit": unrealized_mark_profit, "unrealizedExitCost": unrealized_exit_cost, "unrealizedProfit": unrealized_profit, "openPositionCount": len(open_positions), "openPositions": open_positions, **sharpe_metrics, "sharpeMethod": f"trade_return_cycle_{target_days:g}d", "maxDrawdown": max_drawdown(equity), "winRate": share(len(round_trip_wins), len(round_trip_trades)), "tradeCount": len(round_trip_trades), "roundTripTrades": round_trip_trades, "exitSliceWinRate": share(len(exit_slice_wins), len(trades)), "exitSliceCount": len(trades), "eventCount": len(trade_events), "skippedOrderCount": len(skipped_orders), "skippedOrders": skipped_orders[:200], "matchingDiagnostics": matching_diagnostics, "trades": trades, "tradeEvents": trade_events, "equityHistory": equity, "equityCurve": equity, "notes": notes}

    @staticmethod
    def _round_trip_trades(trades: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for trade in trades:
            key = (str(trade.get("entrySignalSnapshotId") or trade.get("entrySnapshotId") or ""), str(trade.get("code") or ""))
            groups.setdefault(key, []).append(trade)

        result: list[dict[str, Any]] = []
        for rows in groups.values():
            first = rows[0]
            last = rows[-1]
            quantity = sum(int(row.get("quantity") or 0) for row in rows)
            profit = round(sum(float(row.get("profit") or 0) for row in rows), 2)
            entry_cost = sum(float(row.get("entryCostBasis") or 0) for row in rows)
            exit_amount = sum(float(row.get("exitPrice") or 0) * int(row.get("quantity") or 0) for row in rows)
            net_return = profit / entry_cost if entry_cost else 0
            exit_price = exit_amount / quantity if quantity else float(last.get("exitPrice") or 0)
            result.append({
                **first,
                "exitSnapshotId": last.get("exitSnapshotId"),
                "exitSignalSnapshotId": last.get("exitSignalSnapshotId"),
                "exitTime": last.get("exitTime"),
                "exitTradingDate": last.get("exitTradingDate"),
                "exitPrice": round(exit_price, 4),
                "quantity": quantity,
                "holdingBars": max(int(row.get("holdingBars") or 0) for row in rows),
                "grossReturn": round((exit_price - float(first.get("entryPrice") or 0)) / float(first.get("entryPrice") or 1), 4),
                "netReturn": round(net_return, 4),
                "entryCostBasis": round(entry_cost, 2),
                "profit": profit,
                "reason": last.get("reason"),
                "explanation": f"按入场回合归并：{len(rows)} 个卖出片段",
                "price": round(exit_price, 4),
                "rank": last.get("rank"),
                "candidateTier": last.get("candidateTier"),
                "stage": last.get("stage"),
                "regime": last.get("regime"),
                "executionMode": last.get("executionMode"),
                "fill": last.get("fill"),
                "exitSliceCount": len(rows),
                "exitSliceProfits": [row.get("profit") for row in rows],
                "exitSliceNetReturns": [row.get("netReturn") for row in rows],
            })
        return result

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
    def _position_price_signal(frame: dict[str, Any], code: str, pos: dict[str, Any]) -> dict[str, Any] | None:
        for stock in frame.get("stocks") or []:
            if str(stock.get("code") or "") != str(code):
                continue
            price = _first_number(stock, "lastTradePrice", "lastPrice", "price", "close", "closePrice")
            if not price or price <= 0:
                return None
            return {
                **stock,
                "snapshotId": frame.get("snapshotId"),
                "timestamp": frame.get("timestamp"),
                "tradingDate": frame.get("tradingDate"),
                "slotTime": frame.get("slotTime"),
                "code": code,
                "name": stock.get("name") or pos.get("name") or "",
                "rank": pos.get("lastRank") or pos.get("entryRank") or 999,
                "candidateTier": pos.get("entryCandidateTier"),
                "stage": (pos.get("lastSignal") or {}).get("stage"),
                "regime": (pos.get("lastSignal") or {}).get("regime"),
                "confidence": pos.get("entryConfidence"),
                "rankTrend": {},
                "price": price,
            }
        return None

    @staticmethod
    def _entry_candidates(frame_signals: list[dict[str, Any]], frames: list[dict[str, Any]], idx: int, by_key: dict[str, dict[str, Any]], positions: dict[str, Any], strategy_key: str = "rank_trend_candidate") -> list[dict[str, Any]]:
        result = []
        previous_frame = frames[idx - 1] if idx > 0 else None
        for signal in frame_signals:
            if signal["code"] in positions:
                continue
            if strategy_key == "ranktrend_early_big_move_v3_a_main_risk_filter":
                if TradeSimulator._is_early_big_move_v3_a_main_risk_filter_entry_signal(signal):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v3_b_long_filter":
                if TradeSimulator._is_early_big_move_v3_b_long_filter_entry_signal(signal):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v3_no_lifecycle_gate":
                if TradeSimulator._is_early_big_move_v3_no_lifecycle_gate_entry_signal(signal):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v3_context_probe":
                if TradeSimulator._is_early_big_move_v3_context_probe_entry_signal(signal):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v3_lifecycle_fusion":
                if TradeSimulator._is_early_big_move_v3_lifecycle_fusion_entry_signal(signal):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v3":
                if TradeSimulator._is_early_big_move_v3_entry_signal(signal):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v2":
                if TradeSimulator._is_early_big_move_v2_entry_signal(signal):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move":
                if TradeSimulator._is_early_big_move_entry_signal(signal):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_jump":
                if TradeSimulator._is_jump_entry_signal(signal):
                    result.append(signal)
                continue
            if strategy_key == "hot_top10":
                if signal.get("rank", 999) <= 10 and signal["regime"] != "retreat":
                    result.append(signal)
                continue
            if signal["regime"] == "retreat":
                continue
            final_signal = str((((signal.get("rankTrend") or {}).get("decision") or {}).get("final") or {}).get("signal") or "hold")
            if final_signal != "buy":
                continue
            if strategy_key == "leader_theme_confirmation":
                if signal.get("themeRole") == "leader" and signal["candidateTier"] in {"A_MAIN", "B_IGNITION"}:
                    result.append(signal)
                continue
            if strategy_key == "hotlist_theme_confluence":
                if signal.get("candidateTier") in {"A_MAIN", "B_IGNITION"} and signal.get("themeConfluenceScore", 0) >= 75 and signal.get("themeRole") != "noise":
                    result.append(signal)
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
        if strategy_key in {
            "ranktrend_early_big_move",
            "ranktrend_early_big_move_v2",
            "ranktrend_early_big_move_v3",
            "ranktrend_early_big_move_v3_no_lifecycle_gate",
            "ranktrend_early_big_move_v3_context_probe",
            "ranktrend_early_big_move_v3_lifecycle_fusion",
            "ranktrend_early_big_move_v3_a_main_risk_filter",
            "ranktrend_early_big_move_v3_b_long_filter",
        }:
            return sorted(result, key=TradeSimulator._early_big_move_score, reverse=True)
        return sorted(result, key=lambda item: item.get("confidence", 0), reverse=True)

    @staticmethod
    def _signal_value(container: dict[str, Any], key: str) -> float:
        value = container.get(key)
        if isinstance(value, dict):
            value = value.get("value") or value.get("score") or value.get("signalValue")
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _early_big_move_value(key: str, *containers: dict[str, Any]) -> float:
        for container in containers:
            if not isinstance(container, dict) or key not in container:
                continue
            value = container.get(key)
            if isinstance(value, dict):
                value = value.get("value") if "value" in value else value.get("signalValue")
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return 0.0

    @staticmethod
    def _early_big_move_momentum(signal: dict[str, Any], rank_trend: dict[str, Any], technical: dict[str, Any]) -> dict[str, Any]:
        momentum = technical.get("momentumProfile")
        if isinstance(momentum, dict):
            return momentum
        strategy_momentum = ((rank_trend.get("strategy") or {}).get("momentum") or {})
        if isinstance(strategy_momentum, dict):
            return strategy_momentum
        signal_momentum = signal.get("momentum")
        return signal_momentum if isinstance(signal_momentum, dict) else {}

    @staticmethod
    def _is_early_big_move_entry_signal(signal: dict[str, Any]) -> bool:
        rank_trend = signal.get("rankTrend") or {}
        jump = rank_trend.get("jump") or {}
        technical = rank_trend.get("technical") or {}
        signals = technical.get("signals") or {}
        momentum = TradeSimulator._early_big_move_momentum(signal, rank_trend, technical)
        top_level = {
            "short": signal.get("short"),
            "mid": signal.get("mid"),
            "long": signal.get("long"),
            "acceleration": signal.get("acceleration"),
            "accDelta": signal.get("accDelta"),
        }
        if jump.get("direction") != "buy":
            return False
        if float(jump.get("confidence") or 0) < 90:
            return False
        if TradeSimulator._early_big_move_value("short", signals, momentum, top_level) <= 0:
            return False
        if TradeSimulator._early_big_move_value("mid", signals, momentum, top_level) <= 0:
            return False
        if TradeSimulator._early_big_move_value("long", signals, momentum, top_level) <= 0:
            return False
        acceleration = TradeSimulator._early_big_move_value("acceleration", signals, momentum, top_level)
        acc_delta = TradeSimulator._early_big_move_value("accDelta", signals, momentum, top_level)
        if acceleration < 10 and acc_delta < 8:
            return False
        if TradeSimulator._limit_state(signal, TradeSimulator._quote(signal))["atLimitUp"]:
            return False
        return True

    @staticmethod
    def _is_early_big_move_v2_entry_signal(signal: dict[str, Any]) -> bool:
        if not TradeSimulator._is_early_big_move_entry_signal(signal):
            return False
        if signal.get("candidateTier") not in {"A_MAIN", "B_IGNITION"}:
            return False
        try:
            change = float(signal.get("change") or 0)
        except (TypeError, ValueError):
            change = 0.0
        return change < 6

    @staticmethod
    def _is_early_big_move_v3_no_lifecycle_gate_entry_signal(signal: dict[str, Any]) -> bool:
        if not TradeSimulator._is_early_big_move_entry_signal(signal):
            return False
        try:
            change = float(signal.get("change") or 0)
        except (TypeError, ValueError):
            change = 0.0
        return change < 6

    @staticmethod
    def _is_early_big_move_v3_context_probe_entry_signal(signal: dict[str, Any]) -> bool:
        if TradeSimulator._is_early_big_move_v3_entry_signal(signal):
            return True
        if not TradeSimulator._is_early_big_move_v3_no_lifecycle_gate_entry_signal(signal):
            return False
        if signal.get("candidateTier") in {"A_MAIN", "B_IGNITION"}:
            return False
        cycle = (signal.get("rankTrend") or {}).get("cycle") or {}
        entry_advice = cycle.get("entryAdvice") or {}
        if not bool(entry_advice.get("allowed")):
            return False
        if str(entry_advice.get("bias") or "") != "preferred":
            return False
        if str(cycle.get("stage") or signal.get("stage") or "") != "ignition":
            return False
        if str(cycle.get("transition") or "") != "cooling->ignition":
            return False
        rank_trend = signal.get("rankTrend") or {}
        technical = rank_trend.get("technical") or {}
        signals = technical.get("signals") or {}
        momentum = TradeSimulator._early_big_move_momentum(signal, rank_trend, technical)
        mid = TradeSimulator._early_big_move_value("mid", signals, momentum, {"mid": signal.get("mid")})
        long_value = TradeSimulator._early_big_move_value("long", signals, momentum, {"long": signal.get("long")})
        zero_cross = (signals.get("zeroCross") or {}).get("signal")
        return mid >= 18 and long_value >= 8 and zero_cross == "buy"

    @staticmethod
    def _is_early_big_move_v3_entry_signal(signal: dict[str, Any]) -> bool:
        if not TradeSimulator._is_early_big_move_v2_entry_signal(signal):
            return False
        if signal.get("candidateTier") == "A_MAIN":
            return True
        rank_trend = signal.get("rankTrend") or {}
        technical = rank_trend.get("technical") or {}
        signals = technical.get("signals") or {}
        momentum = TradeSimulator._early_big_move_momentum(signal, rank_trend, technical)
        mid = TradeSimulator._early_big_move_value("mid", signals, momentum, {"mid": signal.get("mid")})
        zero_cross = (signals.get("zeroCross") or {}).get("signal")
        return mid >= 20 and zero_cross == "buy"

    @staticmethod
    def _lifecycle_decision_action(signal: dict[str, Any]) -> str:
        cycle = (signal.get("rankTrend") or {}).get("cycle") or {}
        decision = cycle.get("decision") or {}
        return str(decision.get("action") or "")

    @staticmethod
    def _is_early_big_move_v3_lifecycle_fusion_entry_signal(signal: dict[str, Any]) -> bool:
        if not TradeSimulator._is_early_big_move_v3_entry_signal(signal):
            return False
        return TradeSimulator._lifecycle_decision_action(signal) != "veto"

    @staticmethod
    def _is_early_big_move_v3_a_main_risk_filter_entry_signal(signal: dict[str, Any]) -> bool:
        if not TradeSimulator._is_early_big_move_v3_entry_signal(signal):
            return False
        if signal.get("candidateTier") != "A_MAIN":
            return True
        rank_trend = signal.get("rankTrend") or {}
        technical = rank_trend.get("technical") or {}
        signals = technical.get("signals") or {}
        momentum = TradeSimulator._early_big_move_momentum(signal, rank_trend, technical)
        long_value = TradeSimulator._early_big_move_value("long", signals, momentum, {"long": signal.get("long")})
        try:
            change = float(signal.get("change") or 0)
        except (TypeError, ValueError):
            change = 0.0
        if signal.get("regime") == "weak" and long_value < 10:
            return False
        if change < 0:
            return False
        return True

    @staticmethod
    def _is_early_big_move_v3_b_long_filter_entry_signal(signal: dict[str, Any]) -> bool:
        if not TradeSimulator._is_early_big_move_v3_entry_signal(signal):
            return False
        if signal.get("candidateTier") != "B_IGNITION":
            return True
        rank_trend = signal.get("rankTrend") or {}
        technical = rank_trend.get("technical") or {}
        signals = technical.get("signals") or {}
        momentum = TradeSimulator._early_big_move_momentum(signal, rank_trend, technical)
        long_value = TradeSimulator._early_big_move_value("long", signals, momentum, {"long": signal.get("long")})
        return long_value >= 10

    @staticmethod
    def _early_big_move_score(signal: dict[str, Any]) -> float:
        rank_trend = signal.get("rankTrend") or {}
        jump = rank_trend.get("jump") or {}
        technical = rank_trend.get("technical") or {}
        signals = technical.get("signals") or {}
        momentum = TradeSimulator._early_big_move_momentum(signal, rank_trend, technical)
        top_level = {
            "acceleration": signal.get("acceleration"),
            "accDelta": signal.get("accDelta"),
        }
        score = float(jump.get("confidence") or 0)
        if signal.get("stage") in {"expansion", "ignition"}:
            score += 30
        if signal.get("candidateTier") in {"A_MAIN", "B_IGNITION"}:
            score += 25
        change = float(signal.get("change") or 0)
        if 3 <= change <= 8.5:
            score += 20
        if (signals.get("direction") or {}).get("signal") == "buy":
            score += 10
        if (signals.get("zeroCross") or {}).get("signal") == "buy":
            score += 5
        if (technical.get("macd") or {}).get("cross") == "golden":
            score += 5
        score += min(20, max(0, TradeSimulator._early_big_move_value("acceleration", signals, momentum, top_level)))
        return score

    @staticmethod
    def _is_jump_entry_signal(signal: dict[str, Any]) -> bool:
        rank_trend = signal.get("rankTrend") or {}
        jump = rank_trend.get("jump") or {}
        technical = rank_trend.get("technical") or {}
        signals = technical.get("signals") or {}
        if jump.get("event") != "jump" or jump.get("direction") != "buy" or not jump.get("sustained"):
            return False
        if (signals.get("direction") or {}).get("signal") != "buy":
            return False
        if (signals.get("acceleration") or {}).get("signal") != "buy":
            return False
        if float(signal.get("change") or 0) <= 0:
            return False
        if TradeSimulator._limit_state(signal, TradeSimulator._quote(signal))["atLimitUp"]:
            return False
        if (technical.get("macd") or {}).get("cross") != "golden":
            return False
        return float(jump.get("confidence") or 0) >= 85

    @staticmethod
    def _ranktrend_jump_exit_decision(
        signal: dict[str, Any],
        pos: dict[str, Any],
        gross_return: float,
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        rank_trend = signal.get("rankTrend") or {}
        jump = rank_trend.get("jump") or {}
        technical = rank_trend.get("technical") or {}
        if jump.get("event") == "jump" and jump.get("direction") == "sell" and jump.get("sustained"):
            return True, f"排名持续崩塌(jump={float(jump.get('magnitude') or 0):.1f}pct)"
        if (technical.get("macd") or {}).get("cross") == "death":
            return True, "MACD 死叉"
        raw_change = float((rank_trend.get("meta") or {}).get("rawChange") or 0)
        if raw_change < -80:
            return True, f"排名大幅下降({raw_change:.0f})"
        if pos["holdingBars"] >= config["maxHoldingBars"]:
            return True, "到达最大持有快照"
        if gross_return <= config["stopLoss"]:
            return True, "止损"
        if gross_return >= config["takeProfit"]:
            return True, "止盈"
        return False, None

    @staticmethod
    def _ranktrend_early_big_move_v2_exit_decision(
        signal: dict[str, Any],
        pos: dict[str, Any],
        gross_return: float,
        config: dict[str, Any],
    ) -> tuple[bool, str | None]:
        if int(pos.get("hotlistMissingBars") or 0) >= 3:
            return True, "退出热榜连续3个bar"
        if gross_return <= float(config.get("stopLoss") or -0.05):
            return True, "止损"
        rank_trend = signal.get("rankTrend") or {}
        technical = rank_trend.get("technical") or {}
        raw_change = float((rank_trend.get("meta") or {}).get("rawChange") or 0)
        if raw_change < -50 and (technical.get("macd") or {}).get("cross") == "death":
            return True, "排名大幅下降+MACD死叉"
        if int(pos.get("holdingBars") or 0) >= int(config.get("maxHoldingBars") or 40):
            return True, "到达最大持有快照"
        return False, None

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
                if str(config.get("fillFallbackMode") or "fallback_penalized") in {"blocked_fill", "strict_fill"}:
                    return {
                        "filled": False,
                        "reason": "missing_order_book_quote",
                        "quantity": 0,
                        "requestedQuantity": requested_quantity,
                        "limitState": limit_state,
                    }
                snapshot_fallback = True
        slippage = float(config.get("slippageRate") or 0)
        if snapshot_fallback and str(config.get("fillFallbackMode") or "fallback_penalized") == "fallback_penalized":
            slippage += float(config.get("fallbackSlippageRate") or 0)
        fill_price = raw_price * (1 + slippage) if side == "buy" else raw_price * (1 - slippage)

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
        final_signal = str((((signal.get("rankTrend") or {}).get("decision") or {}).get("final") or {}).get("signal") or "hold")
        if final_signal == "sell":
            return "compose_decision 卖出信号"
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
        if strategy_key == "ranktrend_early_big_move_v3_a_main_risk_filter":
            if signal.get("candidateTier") == "B_IGNITION":
                return "早期大肉V3 A_MAIN风险过滤研究：B_IGNITION 沿用V3二次确认"
            return "早期大肉V3 A_MAIN风险过滤研究：A_MAIN 通过假主升过滤"
        if strategy_key == "ranktrend_early_big_move_v3_b_long_filter":
            if signal.get("candidateTier") == "B_IGNITION":
                return "早期大肉V3 B_IGNITION长周期过滤研究：B_IGNITION 长周期动量确认"
            return "早期大肉V3 B_IGNITION长周期过滤研究：A_MAIN 沿用V3"
        if strategy_key == "ranktrend_early_big_move_v3_no_lifecycle_gate":
            return "早期大肉V3无生命周期硬门槛研究：高置信jump + 多周期动量同步 + 加速度抬升"
        if strategy_key == "ranktrend_early_big_move_v3_context_probe":
            if signal.get("candidateTier") in {"A_MAIN", "B_IGNITION"}:
                return f"早期大肉V3路径探针：沿用V3主干 {signal.get('candidateTier')}"
            return "早期大肉V3路径探针：preferred 非A/B 早期结构候选"
        if strategy_key == "ranktrend_early_big_move_v3_lifecycle_fusion":
            return f"早期大肉V3生命周期融合：{signal.get('candidateTier')} 通过A结构且B未否决"
        if strategy_key == "ranktrend_early_big_move_v3":
            if signal.get("candidateTier") == "B_IGNITION":
                return "早期大肉V3入场：B_IGNITION + 高置信jump + 中周期动量确认 + 零轴同步转正"
            return f"早期大肉V3入场：{signal.get('candidateTier')} + 高置信jump + 多周期动量同步"
        if strategy_key == "ranktrend_early_big_move_v2":
            return f"早期大肉V2入场：{signal.get('candidateTier')} + 高置信jump + 多周期动量同步"
        if signal["candidateTier"] == "A_MAIN":
            return "A_MAIN 入场 (finalSignal 确认)"
        if signal["candidateTier"] == "B_IGNITION":
            previous_frame = frames[(idx or 0) - 1] if frames and idx and idx > 0 else None
            previous_signal = by_key.get(f"{previous_frame['snapshotId']}:{signal['code']}") if previous_frame and by_key else None
            if previous_signal:
                return "B_IGNITION 连续确认入场 (finalSignal 确认)"
            return "B_IGNITION 确认入场 (finalSignal 确认)"
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
