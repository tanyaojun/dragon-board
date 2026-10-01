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


def _profit_factor(round_trip_trades: list[dict[str, Any]]) -> float | None:
    """盈亏比 = 盈利交易 profit 总额 / 亏损交易 profit 总额绝对值（阶段 4.1 盈亏比约束）。

    fail-visible：无交易或无亏损（gross_loss<=0）→ None（不伪造 99.99/0 等伪值，
    无亏损本身即满足 profitFactor 验收，由消费方按 None 处理）。
    """
    profits = [float(trade.get("profit") or 0) for trade in round_trip_trades]
    if not profits:
        return None
    gross_profit = sum(profit for profit in profits if profit > 0)
    gross_loss = abs(sum(profit for profit in profits if profit < 0))
    if gross_loss <= 0:
        return None
    return round(gross_profit / gross_loss, 4)


class TradeSimulator:
    @staticmethod
    def _phase_exposure_factor(config: dict[str, Any], trading_date: str) -> float:
        """M3 相位暴露控制研究开关（设计 ranktrend-phase-acceptance-design.md §5 M3 ①；2026-10-01）。

        trade_config["phaseExposureControl"] = {mode: off|reduce_offense|reduce_defense|reduce_band|ladder,
            factor: 0~1, threshold: 60.0, bandLow/bandHigh: 40/60（reduce_band 用）,
            ladder: [[上界, 因子]...] 升序（ladder 用，末条建议 catch-all 上界如 999）,
            eodScores: {date: score}}。
        as-of 纪律：入场日 d 的相位取 eodScores 中**严格早于 d 的最近交易日** EOD 分（前日定相）；
        键缺失/模式 off/无前日/分数缺失 → 1.0 放行（默认关=golden 逐位不变，缺信号不错杀）。
        reduce_offense/reduce_defense：按 threshold 两档相位匹配降仓；
        reduce_band：前日分 ∈ [bandLow, bandHigh) 降仓（C6 弱势带载体，下沿含上沿不含）；
        ladder：阶梯仓位表——取首个 score<上界 的因子，超出全部上界用末条
        （C7 用户确认 ③：[[40,1.0],[60,0.0],[999,0.3]] = 10-40 满 / 40-60 零 / 60+ 三成）。
        factor=0 语义=该相位禁止新开仓（调用方跳过）。
        """
        ctrl = config.get("phaseExposureControl")
        if not isinstance(ctrl, dict):
            return 1.0
        mode = str(ctrl.get("mode") or "off")
        if mode not in ("reduce_offense", "reduce_defense", "reduce_band", "ladder"):
            return 1.0
        eod = ctrl.get("eodScores") or {}
        prev_dates = [d for d in eod if str(d) < str(trading_date)]
        if not prev_dates:
            return 1.0
        score = eod[max(prev_dates)]
        if not isinstance(score, (int, float)):
            return 1.0
        if mode == "reduce_band":
            low = float(ctrl.get("bandLow", 40.0))
            high = float(ctrl.get("bandHigh", 60.0))
            in_band = low <= score < high
            if not in_band:
                return 1.0
        elif mode == "ladder":
            ladder = ctrl.get("ladder") or []
            for entry in ladder:
                try:
                    upper, factor = float(entry[0]), float(entry[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if score < upper:
                    return max(0.0, min(1.0, factor))
            return 1.0 if not ladder else max(0.0, min(1.0, float(ladder[-1][1])))
        else:
            threshold = float(ctrl.get("threshold") or 60.0)  # 2026-10-01 章程 Q1：二档边界 50→60 口径一致
            phase = "offense" if score >= threshold else "defense"
            if mode != f"reduce_{phase}":
                return 1.0
        try:
            return max(0.0, min(1.0, float(ctrl.get("factor", 0.5))))
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _phase_context(config: dict[str, Any], trading_date: str) -> dict[str, Any]:
        """SP1 归因上下文（章程 ranktrend-position-management-charter.md §4 SP1-T2）。

        返回 {prevDate, prevScore, prev2Score, deltaScore, phase, band, factor}，供
        entryPhase 盖戳与 factor 判定共用：
        - prevDate/prevScore：**严格早于 trading_date 的最近交易日键**的 EOD 分（与
          _phase_exposure_factor 同一 as-of；该日缺分→归因字段全 None，不回跳更早有分日）；
        - prev2Score：严格 prevDate 前一交易日分；deltaScore = prevScore − prev2Score（任一缺失→None）；
        - phase：两档 offense ≥ threshold（默认 60，Q1 口径）/ defense；
        - band：四带标签（冷10-40/弱势40-60/强60-80/极热≥80，与 ladder/reduce_band 同一分数轴；
          phase_pulse PULSE_BANDS 仅前三带，本表含极热）；
        - factor：_phase_exposure_factor 同口径（mode off/键缺失→1.0）。
        分数缺失/无前日→对应字段 None（fail-visible 不伪造，不错杀）。
        """
        ctrl = config.get("phaseExposureControl") if isinstance(config, dict) else None
        out: dict[str, Any] = {
            "prevDate": None, "prevScore": None, "prev2Score": None, "deltaScore": None,
            "phase": None, "band": None,
            "factor": TradeSimulator._phase_exposure_factor(config, trading_date),
        }
        if not isinstance(ctrl, dict):
            return out
        eod = ctrl.get("eodScores") or {}
        today = str(trading_date)
        prev_key = max((str(d) for d in eod if str(d) < today), default=None)
        if prev_key is None:
            return out
        out["prevDate"] = prev_key  # as-of 锚定日总是落盘（缺分日可追溯是哪天缺）
        raw = eod.get(prev_key)
        if not isinstance(raw, (int, float)):
            return out  # 缺分日：与 factor 同一严格前日键 → 分数侧全 None（不回跳更早有分日）
        out["prevScore"] = float(raw)
        prev2_key = max((str(d) for d in eod if str(d) < prev_key), default=None)
        raw2 = eod.get(prev2_key) if prev2_key else None
        if isinstance(raw2, (int, float)):
            out["prev2Score"] = float(raw2)
            out["deltaScore"] = round(out["prevScore"] - float(raw2), 2)
        threshold = float(ctrl.get("threshold") or 60.0)
        out["phase"] = "offense" if out["prevScore"] >= threshold else "defense"
        out["band"] = TradeSimulator._band_of_score(out["prevScore"])
        return out

    @staticmethod
    def _exit_tp_multiplier(config: dict[str, Any], entry_trading_date: str) -> float:
        """P2-c 退出端相位耦合研究开关（ranktrend-position-management-plan.md P2-c；2026-10-01）。

        trade_config["phaseExitCoupling"] = {mode: off|cold_tp_widen, multiplier, bandLow/bandHigh,
        eodScores}。冷带（前日分 ∈ [bandLow, bandHigh)，as-of 同暴露开关）入场 → 止盈线 ×multiplier
        （冷带机制=慢牛长持，放宽止盈让利润跑；机制依据=地图文档 §2.1 分带解剖）。
        默认关=1.0（golden 逐位不变）；缺分数放行；multiplier 夹在 [1.0, 3.0]（只放宽不收紧）。
        消费点：pos["exitTpMultiplier"]（开仓时定档、持有期不漂移），止盈判定两处乘用。
        """
        ctrl = config.get("phaseExitCoupling")
        if not isinstance(ctrl, dict):
            return 1.0
        if str(ctrl.get("mode") or "off") != "cold_tp_widen":
            return 1.0
        eod = ctrl.get("eodScores") or {}
        prev_dates = [d for d in eod if str(d) < str(entry_trading_date)]
        if not prev_dates:
            return 1.0
        score = eod[max(prev_dates)]
        if not isinstance(score, (int, float)):
            return 1.0
        low = float(ctrl.get("bandLow", 10.0))
        high = float(ctrl.get("bandHigh", 40.0))
        if not (low <= score < high):
            return 1.0
        try:
            return max(1.0, min(3.0, float(ctrl.get("multiplier", 1.5))))
        except (TypeError, ValueError):
            return 1.0

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
        atr_history_by_code: dict[str, list[tuple[float, float, float]]] = {}
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
            "blockedBySynergyTier": 0,
        }
        for idx, frame in enumerate(frames):
            if TradeSimulator._config_bool(config, "useAtrStops"):
                for stock in frame.get("stocks") or []:
                    stock_code = str(stock.get("code") or "")
                    if not stock_code:
                        continue
                    bar_high = _first_number(stock, "high", "highPrice", "dayHigh")
                    bar_low = _first_number(stock, "low", "lowPrice", "dayLow")
                    bar_close = _first_number(stock, "close", "closePrice", "lastPrice", "lastTradePrice", "price")
                    if bar_high and bar_low and bar_close and bar_high > 0 and bar_low > 0 and bar_close > 0:
                        atr_history_by_code.setdefault(stock_code, []).append((float(bar_high), float(bar_low), float(bar_close)))
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
                # 阶段 B1：启用移动止盈时按 bar high 粘性记录持仓峰值价（默认关闭不维护）。
                if config.get("trailingStopActivateGain") is not None:
                    peak = float(pos.get("peakPrice") or pos.get("entryPrice") or 0)
                    bar_high = quote.get("high")
                    if bar_high is not None and float(bar_high) > 0:
                        peak = max(peak, float(bar_high))
                    pos["peakPrice"] = max(peak, raw_price)
                if config.get("enforceT1", True) and str(frame.get("tradingDate") or "") <= str(pos.get("entryTradingDate") or ""):
                    continue
                # 方向5（阶段6 退出结构研究）：minHoldingBars 强制持有——最小持有期内
                # 跳过所有退出触发（止损/止盈/降档/D_EXIT_RISK/maxHoldingBars），
                # 默认 0 不改变行为；<=0 视为不启用（容忍字符串/负数形态）。
                min_holding_bars = TradeSimulator._min_holding_bars(config)
                if min_holding_bars > 0 and pos["holdingBars"] < min_holding_bars:
                    continue
                gross_return = (raw_price - pos["entryPrice"]) / pos["entryPrice"]
                strategy_exit_reason = None
                atr = TradeSimulator._atr_of(atr_history_by_code.get(code)) if config.get("useAtrStops") else None
                stop_ratio = float(config.get("stopLoss") or -0.06)
                take_ratio = float(config.get("takeProfit") or 0.12)
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
                    synergy_danger_exit = TradeSimulator._synergy_exit_on_danger(config) and TradeSimulator._synergy_tier_of(signal) in ("D", "E")
                    # 对照组/部分帧 signal 可能缺 rankTrend.strategy（信号组装差异），
                    # 缺字段时 acceleration 按 0 处理（不触发 C_CROWDED 加速转弱出场），不阻断回测
                    _crowded_accel = (
                        ((signal.get("rankTrend") or {}).get("strategy") or {}).get("momentum") or {}
                    ).get("acceleration", 0)
                    atr = TradeSimulator._atr_of(atr_history_by_code.get(code)) if TradeSimulator._config_bool(config, "useAtrStops") else None
                    stop_price, take_price, _stop_notes = TradeSimulator._exit_prices(pos, quote, config, atr, gross_return)
                    entry_price = float(pos["entryPrice"] or 0)
                    stop_ratio = (stop_price / entry_price - 1) if entry_price else float(config["stopLoss"])
                    take_ratio = (take_price / entry_price - 1) if entry_price else float(config["takeProfit"])
                    synergy_downgrade_exit = TradeSimulator._synergy_downgrade_exit(pos, signal, config)
                    # 方向6（阶段6 方向2 信号驱动退出去噪）：拆分"价格退出"与"信号驱动退出"。
                    # signalExitDelayBars>0 时，最小持有期内只抑制信号驱动退出（D_EXIT_RISK /
                    # final sell / C_CROWDED 转弱 / rank>50 / synergy 风控），
                    # 价格止损/止盈与 maxHoldingBars 仍立即生效（去噪不硬扛，区别于 minHoldingBars）。
                    max_holding_exit = pos["holdingBars"] >= TradeSimulator._effective_max_holding_bars(pos, config)
                    price_exit = gross_return <= stop_ratio or gross_return >= take_ratio or max_holding_exit
                    # 弱势状态退出（2026-08-16 拐头向下研究立项）：weakStateExit=True 时
                    # D_EXIT_RISK 档位退出（低分位预测反弹，过早离场）替换为"持续弱势状态"退出——
                    # 放量下跌(fall_volume) 或 资金强流出(zljzb < weakStateExitZljzb) 预测继续下跌。
                    d_exit_risk_exit = signal["candidateTier"] == "D_EXIT_RISK"
                    if TradeSimulator._config_bool(config, "weakStateExit"):
                        vp = (signal.get("rankTrend") or {}).get("observation", {}).get("volumePrice") or {}
                        quadrant = str(vp.get("quadrant") or "")
                        zljzb = signal.get("zljzb")
                        weak = quadrant == "fall_volume"
                        if zljzb is not None:
                            try:
                                threshold = float((config or {}).get("weakStateExitZljzb", -5.0))
                                weak = weak or float(zljzb) < threshold
                            except (TypeError, ValueError):
                                pass
                        d_exit_risk_exit = weak
                    signal_exit = (
                        final_signal == "sell"
                        or d_exit_risk_exit
                        or (signal["candidateTier"] == "C_CROWDED" and _crowded_accel <= 0)
                        or TradeSimulator._rank_exit_triggered(signal, pos, config, strategy_key)
                        or synergy_danger_exit
                        or synergy_downgrade_exit
                    )
                    signal_exit_delay = TradeSimulator._signal_exit_delay_bars(config)
                    if signal_exit_delay > 0 and pos["holdingBars"] < signal_exit_delay:
                        signal_exit = False
                    should_exit = price_exit or signal_exit
                # SP2-T2 相位调仓（v1：仅前日带下移入冷→清仓；研究开关默认关；
                # T+1 门与 minHoldingBars 门在本链路之前已过——调仓同样被两门约束）
                if not should_exit and TradeSimulator._phase_rebalance_triggered(config, pos, str(frame.get("tradingDate") or "")):
                    should_exit = True
                    strategy_exit_reason = "相位调仓(入冷清仓)"
                # 阶段 B2 断板事件卖出（全策略生效，默认关闭零行为变化）：
                # 持仓期曾触及涨停（bar high 或现价达 limitUpPrice×0.999 容差，对齐
                # _limit_state 口径；粘性记录，含卖出未成交 bar）且当前 bar 未封板
                # （price < 容差线，或封单 fengdan 归零）→ 卖出 reason="断板"。
                # fengdan 从 fill_signal 原始字段读取：_quote/_first_number 会把 0
                # 归一为 None，而封单归零是有意义的断板信号，不能当缺失（fail-visible）；
                # limitUpPrice 缺失（None/0）时不判定——fail-visible 不误杀。
                if TradeSimulator._config_bool(config, "breakBoardExit"):
                    limit_up_price = float(quote.get("limitUpPrice") or 0)
                    if limit_up_price > 0:
                        touch_level = limit_up_price * 0.999
                        break_board_high = quote.get("high")
                        touched_now = raw_price >= touch_level or (
                            break_board_high is not None and float(break_board_high) >= touch_level
                        )
                        if touched_now:
                            pos["touchedLimitUp"] = True
                        if pos.get("touchedLimitUp") and int(pos.get("holdingBars") or 0) >= int(config.get("breakBoardMinBars") or 1):
                            fengdan_raw = fill_signal.get("fengdan", fill_signal.get("sealAmount"))
                            try:
                                fengdan_value = float(fengdan_raw) if fengdan_raw is not None else None
                            except (TypeError, ValueError):
                                fengdan_value = None
                            still_sealed = raw_price >= touch_level and not (fengdan_value is not None and fengdan_value <= 0)
                            if not still_sealed and not should_exit:
                                should_exit = True
                                strategy_exit_reason = "断板"
                exit_trigger = None
                trigger_price = raw_price
                # 归因优先级声明（评审 P2-1）：同帧若同时触发盘中价格退出与相位调仓，
                # exit_trigger（价格事实）胜出并覆盖 reason——此时 trade 行不带 rebalance 子文档、
                # attribution.rebalanceCount 少计 1，属已知口径而非丂数；
                intrabar = self._intrabar_exit_trigger(pos, quote, config, atr=atr, gross_return=gross_return)
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
                reason = exit_trigger or strategy_exit_reason or self._exit_reason(signal, pos, gross_return, config, stop_ratio=stop_ratio, take_ratio=take_ratio, strategy_key=strategy_key)
                net_return = profit / entry_cost_basis if entry_cost_basis else 0
                explanation = self._signal_explanation(signal, f"卖出：{reason}", pos)
                trade = {"code": code, "name": pos["name"], "entrySnapshotId": pos["entrySnapshotId"], "entrySignalSnapshotId": pos.get("entrySignalSnapshotId") or pos["entrySnapshotId"], "exitSnapshotId": frame["snapshotId"], "exitSignalSnapshotId": signal.get("snapshotId"), "entryTime": pos["entryTime"], "exitTime": frame["timestamp"], "entryTradingDate": pos.get("entryTradingDate"), "exitTradingDate": frame.get("tradingDate"), "entryPrice": pos["entryPrice"], "exitPrice": exit_price, "quantity": quantity, "holdingBars": pos["holdingBars"], "grossReturn": round((exit_price - pos["entryPrice"]) / pos["entryPrice"], 4) if pos["entryPrice"] else 0, "netReturn": round(net_return, 4), "entryCostBasis": round(entry_cost_basis, 2), "profit": round(profit, 2), "reason": reason, "explanation": explanation, "action": "sell", "price": exit_price, "rank": signal["rank"], "candidateTier": signal.get("candidateTier"), "stage": signal.get("stage"), "regime": signal.get("regime"), "entryPhase": pos.get("entryPhase"), "entryAtr": pos.get("entryAtr"), "executionMode": execution_mode, "fill": self._public_fill(fill)}
                if str(reason).startswith("相位调仓"):
                    _rb_from = pos.get("rebalanceFromBand") or (
                        pos.get("entryPhase").get("band") if isinstance(pos.get("entryPhase"), dict) else None)
                    _rb_total = int(pos.get("quantity") or 0)
                    # factor 按实际成交比例（评审 P2-4：清仓部分成交时仓位残留，factor≠0）
                    _rb_factor = round(1 - quantity / _rb_total, 2) if _rb_total else 0.0
                    trade["rebalance"] = {"from": _rb_from, "to": "冷10-40", "factor": _rb_factor}
                trades.append(trade)
                trade_events.append({"snapshotId": frame["snapshotId"], "timestamp": frame["timestamp"], "tradingDate": frame.get("tradingDate"), "slotTime": frame.get("slotTime"), "signalSnapshotId": signal.get("snapshotId"), "code": code, "name": pos["name"], "action": "sell", "executionMode": execution_mode, "price": exit_price, "quantity": quantity, "rank": signal["rank"], "reason": reason, "explanation": explanation, "profit": round(profit, 2), "netReturn": trade["netReturn"], "holdingBars": pos["holdingBars"], "candidateTier": signal.get("candidateTier"), "stage": signal.get("stage"), "regime": signal.get("regime"), "entryPhase": pos.get("entryPhase"), "entryAtr": pos.get("entryAtr"), "confidence": signal.get("confidence"), "fill": self._public_fill(fill)})
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
            candidates = self._entry_candidates(candidate_signals, frames, signal_idx, signal_by_snapshot_code, positions, strategy_key, config)
            synergy_allowed = TradeSimulator._synergy_allowed_tiers(config)
            for signal in candidates:
                if len(positions) >= int(config["maxPositions"]):
                    break
                if synergy_allowed is not None and TradeSimulator._synergy_tier_of(signal) not in synergy_allowed:
                    matching_stats["blockedBySynergyTier"] += 1
                    continue
                fill_signal = self._merge_execution_signal(signal, signal_by_code.get(str(signal.get("code"))), frame, execution_mode)
                quote = self._quote(fill_signal)
                raw_price = float(quote.get("lastPrice") or fill_signal.get("price") or 0)
                if raw_price <= 0:
                    matching_stats["missingPriceRows"] += 1
                    continue
                matching_stats["buyAttempts"] += 1
                allocation = min(cash, float(config["initialCapital"]) * float(config["positionSize"]))
                if TradeSimulator._config_bool(config, "tierPositionScale"):
                    entry_tier = TradeSimulator._synergy_tier_of(signal) or ""
                    allocation *= float((config.get("tierPositionScales") or {}).get(entry_tier, 1.0))
                # M3 相位暴露控制（研究开关，默认关=1.0；factor 0=禁止新开仓）
                phase_factor = TradeSimulator._phase_exposure_factor(config, str(frame.get("tradingDate") or ""))
                if phase_factor <= 0.0:
                    matching_stats["blockedByPhase"] = matching_stats.get("blockedByPhase", 0) + 1
                    continue
                if phase_factor < 1.0:
                    allocation *= phase_factor
                # SP1 归因（章程 T2）：仅 phaseExposureControl 键存在时盖戳（生产默认无键→数值/行为逐位不变）
                entry_phase = (
                    TradeSimulator._phase_context(config, str(frame.get("tradingDate") or ""))
                    if isinstance(config.get("phaseExposureControl"), dict) else None
                )
                entry_atr = (
                    TradeSimulator._atr_of(atr_history_by_code.get(str(signal.get("code"))))
                    if TradeSimulator._config_bool(config, "useAtrStops") else None
                )
                # SP2-T1 per_band 出场参数表：自包含（入场带从本开关 eodScores 严格前日自解，
                # 评审 P0-1 修复：不依赖 phaseExposureControl，单独启用必须能独立工作）；
                # 默认无键 → 空，golden 不变
                exit_overrides = TradeSimulator._exit_coupling_overrides(config, str(frame.get("tradingDate") or ""))
                exit_tp_multiplier = TradeSimulator._exit_tp_multiplier(config, str(frame.get("tradingDate") or ""))
                if isinstance(exit_overrides.get("exitTpMultiplier"), (int, float)):
                    exit_tp_multiplier = float(exit_overrides["exitTpMultiplier"])
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
                positions[signal["code"]] = {"code": signal["code"], "name": signal["name"], "entrySnapshotId": frame["snapshotId"], "entrySignalSnapshotId": signal["snapshotId"], "entryTime": frame["timestamp"], "entrySignalTime": signal.get("timestamp"), "entryTradingDate": frame.get("tradingDate"), "entrySignalTradingDate": signal.get("tradingDate"), "entrySlotTime": frame.get("slotTime"), "entryPrice": entry_price, "entryAmount": entry_amount, "entryFee": entry_fee, "entryCost": used, "quantity": quantity, "holdingBars": 0, "entryReason": entry_reason, "entryRank": signal.get("rank"), "entryAvgRankNum": signal.get("avgRankNum"), "entryExecutionRank": fill_signal.get("rank"), "entryCandidateTier": signal.get("candidateTier"), "entryConfidence": signal.get("confidence"), "entrySynergyTier": TradeSimulator._synergy_tier_of(signal), "entryPhase": entry_phase, "entryAtr": entry_atr, "exitTpMultiplier": exit_tp_multiplier, "exitBreakevenThreshold": exit_overrides.get("exitBreakevenThreshold"), "exitMaxHoldingBars": exit_overrides.get("exitMaxHoldingBars"), "lastPrice": raw_price, "lastSnapshotId": frame["snapshotId"], "lastTime": frame["timestamp"], "lastTradingDate": frame.get("tradingDate"), "lastRank": fill_signal.get("rank"), "lastSignal": signal, "entryFill": self._public_fill(fill)}
                trade_events.append({"snapshotId": frame["snapshotId"], "timestamp": frame["timestamp"], "tradingDate": frame.get("tradingDate"), "slotTime": frame.get("slotTime"), "signalSnapshotId": signal["snapshotId"], "code": signal["code"], "name": signal["name"], "action": "buy", "executionMode": execution_mode, "price": entry_price, "quantity": quantity, "rank": signal["rank"], "reason": entry_reason, "explanation": self._signal_explanation(signal, f"买入：{entry_reason}"), "candidateTier": signal["candidateTier"], "stage": signal.get("stage"), "regime": signal.get("regime"), "entryPhase": entry_phase, "entryAtr": entry_atr, "confidence": signal.get("confidence"), "fill": self._public_fill(fill)})
            market_value = sum(pos["quantity"] * float((signal_by_code.get(code) or {}).get("price") or pos.get("lastPrice") or pos["entryPrice"]) for code, pos in positions.items())
            equity.append({"snapshotId": frame["snapshotId"], "timestamp": frame["timestamp"], "tradingDate": frame.get("tradingDate"), "slotTime": frame.get("slotTime"), "equity": round(cash + market_value, 2), "cash": round(cash, 2), "marketValue": round(market_value, 2), "positionCount": len(positions)})
        final_equity = equity[-1]["equity"] if equity else config["initialCapital"]
        exit_slice_wins = [trade for trade in trades if trade["netReturn"] > 0]
        round_trip_trades = self._round_trip_trades(trades, config)
        round_trip_wins = [trade for trade in round_trip_trades if trade["netReturn"] > 0]
        sharpe_metrics = short_cycle_sharpe(round_trip_trades, target_holding_days=float(config.get("targetHoldingDays") or 5.0))
        profit_factor = _profit_factor(round_trip_trades)
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
        return {"enabled": True, "entryStrategy": strategy_key, "executionMode": execution_mode, "config": config, "totalReturn": round((final_equity - config["initialCapital"]) / config["initialCapital"], 4), "realizedReturn": round(realized_profit / config["initialCapital"], 4), "realizedProfit": realized_profit, "unrealizedMarkProfit": unrealized_mark_profit, "unrealizedExitCost": unrealized_exit_cost, "unrealizedProfit": unrealized_profit, "openPositionCount": len(open_positions), "openPositions": open_positions, **sharpe_metrics, "sharpeMethod": f"trade_return_cycle_{target_days:g}d", "maxDrawdown": max_drawdown(equity), "winRate": share(len(round_trip_wins), len(round_trip_trades)), "tradeCount": len(round_trip_trades), "profitFactor": profit_factor, "roundTripTrades": round_trip_trades, "exitSliceWinRate": share(len(exit_slice_wins), len(trades)), "exitSliceCount": len(trades), "eventCount": len(trade_events), "skippedOrderCount": len(skipped_orders), "skippedOrders": skipped_orders[:200], "matchingDiagnostics": matching_diagnostics, "trades": trades, "tradeEvents": trade_events, "equityHistory": equity, "equityCurve": equity, "notes": notes}

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
    def _min_holding_bars(config: dict[str, Any] | None) -> int:
        """minHoldingBars 解析：容忍 int/字符串/负数形态；<=0 视为不启用（与现状一致）。"""
        value = (config or {}).get("minHoldingBars") or 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _signal_exit_delay_bars(config: dict[str, Any] | None) -> int:
        """signalExitDelayBars 解析：容忍 int/字符串/负数形态；<=0 视为不启用（与现状一致）。"""
        value = (config or {}).get("signalExitDelayBars") or 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _synergy_tier_of(signal: dict[str, Any]) -> str | None:
        """读取 signal.rankTrend.observation.synergy.signalTier（组装下沉后 replay/API 均含）。"""
        return ((((signal or {}).get("rankTrend") or {}).get("observation") or {}).get("synergy") or {}).get("signalTier")

    @staticmethod
    def _synergy_allowed_tiers(config: dict[str, Any] | None) -> set[str] | None:
        """synergyEntryTierMin → 允许档位集合；None 表示不启用（默认，行为与现状一致）。"""
        value = str((config or {}).get("synergyEntryTierMin") or "none").strip().lower()
        if value == "s":
            return {"S"}
        if value == "a":
            return {"S", "A"}
        return None

    @staticmethod
    def _config_bool(config: dict[str, Any] | None, key: str, default: bool = False) -> bool:
        """布尔配置统一解析：容忍 bool 与 "true"/"1"/"yes"/"on" 字符串形态（前端 search_space 提交字符串数组）。"""
        value = (config or {}).get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    @staticmethod
    def _synergy_exit_on_danger(config: dict[str, Any] | None) -> bool:
        """synergyExitOnDanger 布尔判定：容忍 "true"/"1"/"yes" 等字符串形态（配置可能来自 JSON/环境变量）。"""
        value = str((config or {}).get("synergyExitOnDanger") or "").strip().lower()
        return value in ("1", "true", "yes")

    @staticmethod
    def _entry_momentum_confirmed(signal: dict[str, Any], trade_config: dict[str, Any] | None) -> bool:
        """entryMomentumConfirm 入场确认（方向1）：默认 "off" 不改变现状。"""
        mode = str((trade_config or {}).get("entryMomentumConfirm") or "off").strip().lower()
        if mode == "off":
            return True
        if mode == "short_positive":
            rank_trend = signal.get("rankTrend") or {}
            technical = rank_trend.get("technical") or {}
            momentum = TradeSimulator._early_big_move_momentum(signal, rank_trend, technical)
            return TradeSimulator._signal_value(momentum, "short") > 0
        return True

    @staticmethod
    def _is_four_dim_entry_signal(
        signal: dict[str, Any], trade_config: dict[str, Any] | None = None
    ) -> bool:
        """四维信号入场判定（生命周期分层彻底重构方案 A，用户确认 2026-08-16）。

        条件（全部满足才算候选，fail-visible：缺字段 → False 不伪造）：
        1. synergy tier ∈ {S, A}（四维投票方向一致；阶段 3 验收单调 excess 0.088/0.039）；
        2. 资金 zljzb ≥ 0（不流出；量价拐点研究最强组合 0.5460 的资金约束）；
        3. 生命周期非 veto（环境门：一票否决保留，其他生命周期阶段不硬过滤）。
        退出沿用统一逻辑（final sell / D_EXIT_RISK（与弱势状态同帧等效）/ rank 恶化 / 价格止损）。
        生命周期不制造买点、不硬过滤（2026-06-07 审计方向）。
        """
        tier = TradeSimulator._synergy_tier_of(signal)
        if tier not in ("S", "A"):
            return False
        zljzb = signal.get("zljzb")
        if zljzb is None:
            return False
        try:
            if float(zljzb) < 0:
                return False
        except (TypeError, ValueError):
            return False
        lifecycle = (signal.get("rankTrend") or {}).get("observation", {}).get("lifecycle") or {}
        if lifecycle.get("veto"):
            return False
        return True

    @staticmethod
    def _is_trend_reversal_jump_entry_signal(
        signal: dict[str, Any], trade_config: dict[str, Any] | None
    ) -> bool:
        """趋势反转 × jump 新买点候选判定（阶段6，统计分析 commit `3e39b34`）。

        条件（全部满足才算候选，fail-visible：缺字段 → False 不伪造）：
        1. trendReversal.isReversal == True（低位弱转强：当前分位 ≤50 + 此前下行 + 当前回升）；
        2. jump.event == "jump" 且 jump.direction == "buy"（排名跳跃式上升，非 collapse）；
        3. 最新跳跃事件 magnitude >= config.trendReversalJumpMagMin（默认 20）；
        4. jumpFreshness >= config.trendReversalJumpFreshMin（默认 0 = 不要求新鲜度）。
        统计依据：jump buy + mag≥20 → h8 winRate 0.5212（median 转正 +0.0026）；
        再叠加 fresh≥0.5 → 0.5278。两项阈值均可由 trade_config 调。
        """
        rank_trend = signal.get("rankTrend") or {}
        marker = rank_trend.get("trendReversal") or {}
        if not marker.get("isReversal"):
            return False
        jump = rank_trend.get("jump") or {}
        if str(jump.get("event") or "") != "jump" or str(jump.get("direction") or "") != "buy":
            return False
        events = jump.get("events") or []
        if not events:
            return False
        try:
            magnitude = float(events[-1].get("magnitude"))
        except (TypeError, ValueError):
            return False
        mag_min = float((trade_config or {}).get("trendReversalJumpMagMin", 20.0))
        if magnitude < mag_min:
            return False
        freshness = (rank_trend.get("resonance") or {}).get("jumpFreshness")
        fresh_min = float((trade_config or {}).get("trendReversalJumpFreshMin", 0.0))
        if fresh_min > 0:
            try:
                if float(freshness) < fresh_min:
                    return False
            except (TypeError, ValueError):
                return False
        return True

    @staticmethod
    def _atr_of(bars: list[tuple[float, float, float]] | None, period: int = 14) -> float | None:
        """ATR(period)：bars 为 (high, low, close) 列表；样本不足或数据缺失时返回 None（回退固定百分比）。"""
        if not bars or len(bars) < period + 1:
            return None
        trs: list[float] = []
        for i in range(1, len(bars)):
            high, low, prev_close = bars[i][0], bars[i][1], bars[i - 1][2]
            trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        if len(trs) < period:
            return None
        return sum(trs[-period:]) / period

    @staticmethod
    def _exit_prices(
        pos: dict[str, Any],
        quote: dict[str, Any],
        config: dict[str, Any],
        atr: float | None = None,
        gross_return: float | None = None,
    ) -> tuple[float, float, list[str]]:
        """ATR/保本生效后的止损/止盈价（方向3）。返回 (stop_price, take_price, notes)。"""
        entry_price = float(pos.get("entryPrice") or 0)
        stop_price = entry_price * (1 + float(config.get("stopLoss") or -0.06))
        # P2-c 退出耦合：pos.exitTpMultiplier（入场日冷带定档）放宽止盈线；盘中触发与
        # 通用价格退出都经此函数取价——单一 hook 覆盖全部止盈消费点
        take_price = entry_price * (1 + float(config.get("takeProfit") or 0.12) * float(pos.get("exitTpMultiplier") or 1.0))
        notes: list[str] = []
        if TradeSimulator._config_bool(config, "useAtrStops") and atr and atr > 0:
            stop_price = entry_price - float(config.get("atrStopMultiplier") or 2.0) * atr
            take_price = entry_price + float(config.get("atrTakeMultiplier") or 3.0) * atr
            notes.append("atr")
        if TradeSimulator._config_bool(config, "breakevenTrailing") and (
            pos.get("breakevenActivated")
            or (
                gross_return is not None
                and gross_return >= float(
                    pos.get("exitBreakevenThreshold")
                    if pos.get("exitBreakevenThreshold") is not None
                    else (config.get("breakevenThreshold") or 0.02)
                )
            )
        ):
            pos["breakevenActivated"] = True  # 粘性：激活后不回退
            stop_price = max(stop_price, entry_price)
            notes.append("breakeven")
        # 阶段 B1 真·移动止盈：peak（bar high 粘性记录）相对入场涨幅达 activate 后，
        # 止损线抬升至 peak×(1-drawdown)。peak 粘性 → 激活与止损线天然不回退。
        activate_gain = config.get("trailingStopActivateGain")
        if activate_gain is not None:
            peak_price = float(pos.get("peakPrice") or 0)
            drawdown = config.get("trailingStopDrawdown")
            if entry_price > 0 and peak_price > 0 and (peak_price / entry_price - 1) >= float(activate_gain):
                stop_price = max(stop_price, peak_price * (1 - (float(drawdown) if drawdown is not None else 0.5)))
                notes.append("trailing")
        return stop_price, take_price, notes

    @staticmethod
    def _tier_rank(tier: str | None) -> int:
        """synergy 档位排序：S>A>B>C>D>E；未知/缺失返回大值（视为最低档）。"""
        order = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
        if tier is None:
            return 99
        return order.get(str(tier).strip().upper(), 99)

    @staticmethod
    def _tier_downgrade_steps(entry_tier: str | None, current_tier: str | None) -> int:
        """档位相对入场降级步数；正值=降级（A->C=2），负值/零=持平或升级。"""
        return TradeSimulator._tier_rank(current_tier) - TradeSimulator._tier_rank(entry_tier)

    @staticmethod
    def _synergy_downgrade_exit(pos: dict[str, Any], signal: dict[str, Any], config: dict[str, Any] | None) -> bool:
        """synergyExitOnDowngrade（方向4）：持仓档位相对入场降 >= synergyDowngradeSteps 档触发退出。"""
        if not TradeSimulator._config_bool(config, "synergyExitOnDowngrade"):
            return False
        entry_tier = str(pos.get("entrySynergyTier") or "")
        current_tier = TradeSimulator._synergy_tier_of(signal)
        if not entry_tier or not current_tier:
            return False
        steps = TradeSimulator._tier_downgrade_steps(entry_tier, current_tier)
        return steps >= int((config or {}).get("synergyDowngradeSteps") or 2)

    @staticmethod
    def _entry_candidates(
        frame_signals: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        idx: int,
        by_key: dict[str, dict[str, Any]],
        positions: dict[str, Any],
        strategy_key: str = "rank_trend_candidate",
        trade_config: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        result = []
        previous_frame = frames[idx - 1] if idx > 0 else None
        min_jump_confidence = TradeSimulator._trade_min_jump_confidence(trade_config)
        for signal in frame_signals:
            if signal["code"] in positions:
                continue
            if strategy_key == "ranktrend_early_big_move_v3_a_main_risk_filter":
                if TradeSimulator._is_early_big_move_v3_a_main_risk_filter_entry_signal(signal, min_jump_confidence):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v3_b_long_filter":
                if TradeSimulator._is_early_big_move_v3_b_long_filter_entry_signal(signal, min_jump_confidence):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v3_no_lifecycle_gate":
                if TradeSimulator._is_early_big_move_v3_no_lifecycle_gate_entry_signal(signal, min_jump_confidence):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v3_context_probe":
                if TradeSimulator._is_early_big_move_v3_context_probe_entry_signal(signal, min_jump_confidence):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v3_lifecycle_fusion":
                if TradeSimulator._is_early_big_move_v3_lifecycle_fusion_entry_signal(signal, min_jump_confidence):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v3":
                if TradeSimulator._is_early_big_move_v3_entry_signal(signal, min_jump_confidence):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move_v2":
                if TradeSimulator._is_early_big_move_v2_entry_signal(signal, min_jump_confidence):
                    result.append(signal)
                continue
            if strategy_key == "ranktrend_early_big_move":
                if TradeSimulator._is_early_big_move_entry_signal(signal, min_jump_confidence):
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
            final_signal = str((((signal.get("rankTrend") or {}).get("decision") or {}).get("final") or {}).get("signal") or "").strip()
            if final_signal and final_signal != "buy":
                continue
            if strategy_key == "leader_theme_confirmation":
                if signal.get("themeRole") == "leader" and signal["candidateTier"] in {"A_MAIN", "B_IGNITION"}:
                    result.append(signal)
                continue
            # theme_rotation：题材引擎独立信号（rotationState=mainline/inflow 题材资金流入），
            # 与 RankTrend 生命周期分层的 A_MAIN 不同源，不随 A_MAIN 降级（阶段6 业务口径）；
            # 保留题材 A_MAIN/B_IGNITION 入场。R3 变体（chase/hybrid）共用同一进场规则——
            # 变体差异全部在候选池构造层（_theme_execution_signals 的 SG 驱动 tier）。
            if strategy_key in {"theme_rotation", "theme_rotation_chase", "theme_state_hybrid"}:
                if signal["candidateTier"] in {"A_MAIN", "B_IGNITION"} and signal["regime"] != "weak":
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
            if strategy_key == "trend_reversal_jump":
                # 阶段6 趋势反转 × jump 新买点候选：低位弱转强 + 排名跳跃(buy) + 大幅（可选新鲜）。
                # 默认配置（magMin=20/freshMin=0）对应统计分析 h8 winRate 0.5212 组合；
                # 若配置 freshMin>0 则进一步过滤到 0.5278 组合。retreat 退潮不入场。
                if TradeSimulator._is_trend_reversal_jump_entry_signal(signal, trade_config) and signal["regime"] != "retreat":
                    result.append(signal)
                continue
            # 生命周期分层彻底重构（方案 A，用户确认 2026-08-16）：rank_trend_four_dim 研究对照策略——
            # 入场 = synergy S/A（四维投票方向一致）+ 资金 zljzb≥0 + 非生命周期 veto（环境门）；
            # 生命周期不制造买点不硬过滤（6-07 审计方向）；退出沿用统一逻辑（final sell/弱势状态/止损）。
            if strategy_key == "rank_trend_four_dim":
                if TradeSimulator._is_four_dim_entry_signal(signal, trade_config) and signal["regime"] != "retreat":
                    result.append(signal)
                continue
            # 生命周期分层彻底重构（方案 B 落地，用户确认 2026-08-16）：默认策略
            # rank_trend_candidate 入场主轴切换为四维信号×资金——synergy S/A + 资金 zljzb>=0
            # + 非生命周期 veto（环境门）；生命周期不制造买点不硬过滤（6-07 审计方向）。
            # A_MAIN/B_IGNITION 档位不再作为默认入场依据（a_main_only/a_b_combined 对照保留）。
            if strategy_key == "rank_trend_candidate":
                if TradeSimulator._is_four_dim_entry_signal(signal, trade_config) and signal["regime"] != "retreat":
                    result.append(signal)
                continue
            # 阶段6 业务口径（用户决策 2026-08-15）：A_MAIN 高位出货不作为买点，
            # 对照组策略 a_main_only（上文）/ a_b_combined 显式保留 A_MAIN/B_IGNITION 入场供研究对比。
            if signal["candidateTier"] == "A_MAIN" and strategy_key == "a_b_combined" and signal["regime"] != "weak" and TradeSimulator._entry_momentum_confirmed(signal, trade_config):
                result.append(signal)
            elif signal["candidateTier"] == "B_IGNITION" and strategy_key == "a_b_combined" and TradeSimulator._is_confirmed_b_ignition(signal, previous_frame, by_key):
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
    def _trade_min_jump_confidence(trade_config: dict[str, Any] | None) -> float:
        value = (trade_config or {}).get("minJumpConfidence", DEFAULT_TRADE_CONFIG["minJumpConfidence"])
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(DEFAULT_TRADE_CONFIG["minJumpConfidence"])

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
    def _is_early_big_move_entry_signal(signal: dict[str, Any], min_jump_confidence: float) -> bool:
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
        if float(jump.get("confidence") or 0) < min_jump_confidence:
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
    def _is_early_big_move_v2_entry_signal(signal: dict[str, Any], min_jump_confidence: float) -> bool:
        if not TradeSimulator._is_early_big_move_entry_signal(signal, min_jump_confidence):
            return False
        if signal.get("candidateTier") not in {"A_MAIN", "B_IGNITION"}:
            return False
        try:
            change = float(signal.get("change") or 0)
        except (TypeError, ValueError):
            change = 0.0
        return change < 6

    @staticmethod
    def _is_early_big_move_v3_no_lifecycle_gate_entry_signal(signal: dict[str, Any], min_jump_confidence: float) -> bool:
        if not TradeSimulator._is_early_big_move_entry_signal(signal, min_jump_confidence):
            return False
        try:
            change = float(signal.get("change") or 0)
        except (TypeError, ValueError):
            change = 0.0
        return change < 6

    @staticmethod
    def _is_early_big_move_v3_context_probe_entry_signal(signal: dict[str, Any], min_jump_confidence: float) -> bool:
        if TradeSimulator._is_early_big_move_v3_entry_signal(signal, min_jump_confidence):
            return True
        if not TradeSimulator._is_early_big_move_v3_no_lifecycle_gate_entry_signal(signal, min_jump_confidence):
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
    def _is_early_big_move_v3_entry_signal(signal: dict[str, Any], min_jump_confidence: float) -> bool:
        if not TradeSimulator._is_early_big_move_v2_entry_signal(signal, min_jump_confidence):
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
    def _is_early_big_move_v3_lifecycle_fusion_entry_signal(signal: dict[str, Any], min_jump_confidence: float) -> bool:
        if not TradeSimulator._is_early_big_move_v3_entry_signal(signal, min_jump_confidence):
            return False
        return TradeSimulator._lifecycle_decision_action(signal) != "veto"

    @staticmethod
    def _is_early_big_move_v3_a_main_risk_filter_entry_signal(signal: dict[str, Any], min_jump_confidence: float) -> bool:
        if not TradeSimulator._is_early_big_move_v3_entry_signal(signal, min_jump_confidence):
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
    def _is_early_big_move_v3_b_long_filter_entry_signal(signal: dict[str, Any], min_jump_confidence: float) -> bool:
        if not TradeSimulator._is_early_big_move_v3_entry_signal(signal, min_jump_confidence):
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
        if TradeSimulator._lifecycle_decision_action(signal) == "caution":
            decision_reasons = (((signal.get("rankTrend") or {}).get("cycle") or {}).get("decision") or {}).get("reasons") or []
            if any("低可见度" in str(reason) for reason in decision_reasons):
                score -= 0.01
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
        if pos["holdingBars"] >= TradeSimulator._effective_max_holding_bars(pos, config):
            return True, "到达最大持有快照"
        if gross_return <= config["stopLoss"]:
            return True, "止损"
        if gross_return >= float(config["takeProfit"]) * float(pos.get("exitTpMultiplier") or 1.0):
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
        if (
            str(config.get("entryStrategy") or "") == "ranktrend_early_big_move_v3_lifecycle_fusion"
            and gross_return <= 0
            and TradeSimulator._lifecycle_decision_action(signal) in {"veto", "exit_watch"}
        ):
            return True, "生命周期B反对且未盈利"
        rank_trend = signal.get("rankTrend") or {}
        technical = rank_trend.get("technical") or {}
        raw_change = float((rank_trend.get("meta") or {}).get("rawChange") or 0)
        if raw_change < -50 and (technical.get("macd") or {}).get("cross") == "death":
            return True, "排名大幅下降+MACD死叉"
        if int(pos.get("holdingBars") or 0) >= TradeSimulator._effective_max_holding_bars(pos, config):
            return True, "到达最大持有快照"
        return False, None

    @staticmethod
    def _is_confirmed_b_ignition(signal: dict[str, Any], previous_frame: dict[str, Any] | None, by_key: dict[str, dict[str, Any]]) -> bool:
        if signal["candidateTier"] != "B_IGNITION" or not previous_frame:
            return False
        previous_signal = by_key.get(f"{previous_frame['snapshotId']}:{signal['code']}")
        return bool(previous_signal and previous_signal["candidateTier"] == "B_IGNITION")

    @staticmethod
    def _exit_coupling_overrides(config: dict[str, Any], entry_trading_date: str) -> dict[str, Any]:
        """SP2-T1 per_band 出场参数表（章程 §4 SP2-T1；研究开关默认关）。

        trade_config["phaseExitCoupling"] = {mode: off|cold_tp_widen|per_band,
            bands: {四带标签: {tpMultiplier?, breakevenThreshold?, maxHoldingBars?}}, eodScores}。
        per_band：**自包含**——入场带从本开关 eodScores 严格前日自解（评审 P0-1 修复：
        不依赖 phaseExposureControl 的 entryPhase 盖章，单独启用必须能独立工作）；
        入场带命中 bands 表 → 盖 exitTpMultiplier/exitBreakevenThreshold/exitMaxHoldingBars
        （pos 级定档、持有期不漂移，同 cold_tp_widen 模式）；未命中/缺分/模式不符 → {}（golden 不变）。
        夹界：tpMultiplier [0.5, 3.0]、breakevenThreshold [0.0, 0.5]、maxHoldingBars [1, 999]。
        """
        ctrl = config.get("phaseExitCoupling")
        if not isinstance(ctrl, dict) or str(ctrl.get("mode") or "") != "per_band":
            return {}
        eod = ctrl.get("eodScores") or {}
        prev_key = max((str(d) for d in eod if str(d) < str(entry_trading_date)), default=None)
        if prev_key is None:
            return {}
        raw = eod.get(prev_key)
        if not isinstance(raw, (int, float)):
            return {}
        entry_band = TradeSimulator._band_of_score(float(raw))
        rule = (ctrl.get("bands") or {}).get(entry_band)
        if not isinstance(rule, dict):
            return {}
        out: dict[str, Any] = {}
        if isinstance(rule.get("tpMultiplier"), (int, float)):
            out["exitTpMultiplier"] = max(0.5, min(3.0, float(rule["tpMultiplier"])))
        if isinstance(rule.get("breakevenThreshold"), (int, float)):
            out["exitBreakevenThreshold"] = max(0.0, min(0.5, float(rule["breakevenThreshold"])))
        if isinstance(rule.get("maxHoldingBars"), (int, float)):
            out["exitMaxHoldingBars"] = max(1, min(999, int(rule["maxHoldingBars"])))
        return out

    @staticmethod
    def _effective_max_holding_bars(pos: dict[str, Any], config: dict[str, Any]) -> int:
        """SP2-T1：最大持有单一解析点——pos.exitMaxHoldingBars（per_band 盖章）优先，
        回退 config.maxHoldingBars；非法值回退 config（fail-visible 不炸回测）。
        全部 4 处消费点（价格退出/_rank_exit_triggered/_early_big_move 退出/_exit_reason）必须走此函数。"""
        raw = pos.get("exitMaxHoldingBars")
        try:
            if raw is not None and int(raw) > 0:
                return int(raw)
        except (TypeError, ValueError):
            pass
        return int(config.get("maxHoldingBars") or 40)

    @staticmethod
    def _band_of_score(score: float) -> str:
        """四带标签（冷10-40/弱势40-60/强60-80/极热≥80；与 ladder/reduce_band 同一分数轴）。"""
        if score < 40.0:
            return "冷10-40"
        if score < 60.0:
            return "弱势40-60"
        if score < 80.0:
            return "强60-80"
        return "极热≥80"

    @staticmethod
    def _phase_rebalance_triggered(config: dict[str, Any], pos: dict[str, Any], trading_date: str) -> bool:
        """SP2-T2 相位调仓（章程 Q2+方案 α；研究开关默认关）。

        trade_config["phaseRebalance"] = {enabled: bool, eodScores: {date: score},
        actOn: "into_cold_clear", coldEntryExempt: bool}。
        v1 规则（历史反事实验证选定，downgrade-rule-variants.json）：
        仅当前日「前日定相带」下移入 冷10-40 → 清仓；→弱/→强/上移一律不动作
        （强→弱 18 笔证据：不动作 +30.2% 完胜动作）；冷带入场豁免（慢牛区机制）。
        自包含：入场带/当前带都从本开关的 eodScores 严格前日解（不依赖 phaseExposureControl
        的 entryPhase 盖章——调仓臂单独启用时必须能独立工作）；缺分/无前日不动作（不错杀）。
        默认关（无键/enabled 假）= False。T+1 由调用方既有门保证。
        """
        rb = config.get("phaseRebalance")
        if not isinstance(rb, dict) or not rb.get("enabled"):
            return False
        if str(rb.get("actOn") or "into_cold_clear") != "into_cold_clear":
            return False
        eod = rb.get("eodScores") or {}

        def strict_prev_score(anchor: str) -> float | None:
            key = max((str(d) for d in eod if str(d) < anchor), default=None)
            if key is None:
                return None
            raw = eod.get(key)
            return float(raw) if isinstance(raw, (int, float)) else None

        entry_score = strict_prev_score(str(pos.get("entryTradingDate") or ""))
        if entry_score is None:
            return False
        entry_band = TradeSimulator._band_of_score(entry_score)
        if entry_band == "冷10-40" and rb.get("coldEntryExempt", True):
            return False
        cur_score = strict_prev_score(str(trading_date))
        if cur_score is None:
            return False
        if cur_score < 40.0:
            # 自算入场带落盘（评审 P2-3：standalone 臂下 entryPhase 缺失，rebalance 子文档仍可溯源）
            pos["rebalanceFromBand"] = entry_band
            return True
        return False

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
    def _intrabar_exit_trigger(
        pos: dict[str, Any],
        quote: dict[str, Any],
        config: dict[str, Any],
        atr: float | None = None,
        gross_return: float | None = None,
    ) -> dict[str, Any] | None:
        if not config.get("useIntrabarStops", True):
            return None
        entry_price = float(pos.get("entryPrice") or 0)
        if entry_price <= 0:
            return None
        if gross_return is None:
            last_price = float(quote.get("lastPrice") or pos.get("lastPrice") or 0)
            gross_return = (last_price - entry_price) / entry_price if entry_price else 0.0
        stop_price, take_price, _notes = TradeSimulator._exit_prices(pos, quote, config, atr, gross_return)
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
    def _rank_exit_triggered(
        signal: dict[str, Any],
        pos: dict[str, Any] | None,
        config: dict[str, Any] | None,
        strategy_key: str = "rank_trend_candidate",
    ) -> bool:
        """排名恶化退出判定（阶段6 修复：低位弱转强入场用 avgRankNum 相对恶化而非绝对 rank）。

        - rankExitField="rank"（默认）：保持现状 signal.rank > 50（重排序号，子集内跌出前 50）；
        - rankExitField="avgranknum"（trend_reversal_jump 低位入场推荐）：**相对恶化**——
          当前 avgRankNum 比入场时（pos.entryAvgRankNum）恶化超过 avgRankNumExitDelta（默认 20
          个百分点）才退出。avgRankNum 是 0-100 百分位（数值越大 = 排名越靠后），相对增量对
          低位入场（初始 avgRankNum 即偏高）公平；绝对阈值（avgRankNumExitMax）2026-08-16
          实测证伪（wrXpf 0.537→0.469，延迟退出放大亏损）。
        fail-visible：avgranknum 模式缺 pos/entryAvgRankNum/当前 avgRankNum → False（不误杀，
        交其他退出条件判断）。
        """
        field = str((config or {}).get("rankExitField") or "rank").strip().lower()
        if field == "avgranknum":
            entry_avg = (pos or {}).get("entryAvgRankNum")
            current_avg = signal.get("avgRankNum")
            if entry_avg is None or current_avg is None:
                return False
            try:
                delta = float(current_avg) - float(entry_avg)
            except (TypeError, ValueError):
                return False
            try:
                threshold = float((config or {}).get("avgRankNumExitDelta", 20.0))
            except (TypeError, ValueError):
                threshold = 20.0
            return delta > threshold
        return bool(signal.get("rank", 0) > 50)

    @staticmethod
    def _exit_reason(
        signal: dict[str, Any],
        pos: dict[str, Any],
        gross_return: float,
        config: dict[str, Any],
        stop_ratio: float | None = None,
        take_ratio: float | None = None,
        strategy_key: str = "rank_trend_candidate",
    ) -> str:
        final_signal = str((((signal.get("rankTrend") or {}).get("decision") or {}).get("final") or {}).get("signal") or "hold")
        if TradeSimulator._synergy_exit_on_danger(config) and final_signal != "sell" and TradeSimulator._synergy_tier_of(signal) in ("D", "E"):
            return "四维合并档位 D/E 强制卖出"
        if TradeSimulator._synergy_downgrade_exit(pos, signal, config):
            return "档位连续降级退出"
        if final_signal == "sell":
            return "compose_decision 卖出信号"
        if TradeSimulator._config_bool(config, "weakStateExit"):
            vp = (signal.get("rankTrend") or {}).get("observation", {}).get("volumePrice") or {}
            quadrant = str(vp.get("quadrant") or "")
            zljzb = signal.get("zljzb")
            weak = quadrant == "fall_volume"
            if zljzb is not None:
                try:
                    threshold = float((config or {}).get("weakStateExitZljzb", -5.0))
                    weak = weak or float(zljzb) < threshold
                except (TypeError, ValueError):
                    pass
            if weak:
                return "弱势状态退出（放量下跌/资金强流出）"
        if signal["candidateTier"] == "D_EXIT_RISK":
            return "D_EXIT_RISK"
        if TradeSimulator._rank_exit_triggered(signal, pos, config, strategy_key):
            return "排名恶化退出"
        if pos["holdingBars"] >= TradeSimulator._effective_max_holding_bars(pos, config):
            return "到达最大持有快照"
        if gross_return <= (stop_ratio if stop_ratio is not None else config["stopLoss"]):
            return "止损"
        if gross_return >= (take_ratio if take_ratio is not None else float(config["takeProfit"]) * float(pos.get("exitTpMultiplier") or 1.0)):
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
            "entryPhase": pos.get("entryPhase"),
            "entryAtr": pos.get("entryAtr"),
            "marketValue": round(market_value, 2),
            "entryCost": round(float(pos.get("entryCost") or 0), 2),
            "unrealizedMarkProfit": round(unrealized_mark_profit, 2),
            "unrealizedExitCost": round(estimated_exit_cost, 2),
            "unrealizedProfit": round(unrealized_profit, 2),
            "unrealizedReturn": round(unrealized_profit / float(pos.get("entryCost") or 1), 4),
            "estimatedExitCost": round(estimated_exit_cost, 2),
            "explanation": TradeSimulator._signal_explanation(pos.get("lastSignal") or {}, "未平仓：按最后可见价格盯市", pos) if pos.get("lastSignal") else "未平仓：缺少最新 RankTrend 信号，按入场价附近盯市",
        }
