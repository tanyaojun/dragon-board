from __future__ import annotations

from typing import Any

from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine, get_macd_min_samples
from backend.analysis.theme_support import build_theme_support_index
from backend.core.backtest.evaluator import OutcomeEvaluator
from backend.core.backtest.execution import TradeSimulator
from backend.core.backtest.metrics import _round_or_none, average, share
from backend.core.backtest.strategy import DEFAULT_STRATEGY_NAME, FrameStrategyResult, StrategyInput, get_strategy, normalize_strategy_name


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
        enable_trade_simulation = options.get("enable_trade_simulation", True)
        trade_config = {**(options.get("trade_config") or {}), "entryStrategy": strategy_name}
        control_backtests = (
            self._control_backtests(frames, signals, trade_config)
            if enable_trade_simulation
            else []
        )
        report["controlBacktests"] = control_backtests
        report["researchDiagnostics"] = self._research_diagnostics(
            frames,
            signals,
            control_backtests,
            strategy_name,
            options,
        )
        if enable_trade_simulation:
            report["tradeSimulation"] = TradeSimulator().run(frames, signals, trade_config)
            report["tradeDiagnostics"] = self._trade_diagnostics(report["tradeSimulation"])
            report["strategyDecisions"] = self._record_strategy_decisions(frames, signals, strategy_name, trade_config)
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
        runtime_filter = gate.get("runtimeFilter") if isinstance(gate.get("runtimeFilter"), dict) else {}
        dropped_empty_count = int(runtime_filter.get("droppedEmptyHotlistSnapshots") or 0)
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
        if dropped_empty_count:
            warnings.append(f"本次回测已自动剔除 {dropped_empty_count} 个空热榜快照，仅用可交易快照继续运行。")
        if not has_stable_macd:
            warnings.append("MACD 尚未达到稳定观察窗口，MACD 相关解释只作辅助。")

        severity = "pass"
        empty_only_runtime_filtered = bool(dropped_empty_count and not any(
            int(stats.get(key) or 0) > 0
            for key in ("invalidCaptureMode", "duplicateSnapshotId", "nonMonotonicTimestamp", "missingCoreFieldCount")
        ))
        if (str(gate.get("severity") or "") == "fail" or empty_hotlist_count) and not empty_only_runtime_filtered:
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
            "snapshotCount": int(sample_diagnostics.get("snapshotCount") or 0),
            "sourceSnapshotCount": target_frames,
            "runtimeFilter": runtime_filter,
            "droppedEmptyHotlistSnapshots": dropped_empty_count,
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
        from backend.core.backtest.strategy import CONTROL_STRATEGIES

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
    def _research_diagnostics(
        frames: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        control_backtests: list[dict[str, Any]],
        strategy_name: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        evaluator = OutcomeEvaluator()
        horizons = [1, 2, 5]
        horizon_reports = evaluator.evaluate(frames, signals, horizons).get("horizons") or []
        distribution = evaluator.distribution(signals)
        tiers = ["A_MAIN", "B_IGNITION", "C_CROWDED", "D_EXIT_RISK", "N_NEUTRAL"]

        def grouped_tier_distribution(group_key: str) -> list[dict[str, Any]]:
            groups = sorted({str(signal.get(group_key) or "-") for signal in signals})
            rows: list[dict[str, Any]] = []
            for key in groups:
                subset = [signal for signal in signals if str(signal.get(group_key) or "-") == key]
                total = len(subset)
                tier_counts = {tier: len([signal for signal in subset if signal.get("candidateTier") == tier]) for tier in tiers}
                rows.append({
                    "key": key,
                    "total": total,
                    "share": share(total, len(signals)),
                    "tiers": tier_counts,
                    "tierShares": {tier: share(count, total) for tier, count in tier_counts.items()},
                })
            return rows

        def status_bucket(signal: dict[str, Any]) -> str:
            tier = str(signal.get("candidateTier") or "N_NEUTRAL")
            if tier == "A_MAIN":
                return "主升确认"
            if tier == "B_IGNITION":
                return "点火观察"
            if tier == "C_CROWDED":
                return "高位拥挤"
            if tier == "D_EXIT_RISK":
                return "转弱预警"
            return "新入观察"

        def pick(report: dict[str, Any], key: str) -> list[dict[str, Any]]:
            return [dict(item) for item in report.get(key) or []]

        return {
            "policy": {
                "autoApplyDefaults": False,
                "role": "research_report_only",
                "strategyName": strategy_name,
                "snapshotType": str(options.get("snapshot_type") or options.get("snapshotType") or "half_hour"),
                "randomSeed": options.get("random_seed") or options.get("randomSeed"),
                "notes": [
                    "研究诊断只用于校准候选阈值和展示解释，不自动写回 RankTrend 默认参数。",
                    "RankTrend 核心动量参数变更必须先通过 golden 对齐与样本外验证。",
                ],
            },
            "forwardOutcomeByTier": [
                {
                    "horizon": report.get("horizon"),
                    "byTier": pick(report, "byTier"),
                    "byStage": pick(report, "byStage"),
                    "byRegime": pick(report, "byRegime"),
                    "byTierStage": pick(report, "byTierStage"),
                    "byTierRegime": pick(report, "byTierRegime"),
                }
                for report in horizon_reports
            ],
            "byRegimeTier": grouped_tier_distribution("regime"),
            "byStageTier": grouped_tier_distribution("stage"),
            "byDisplayStatus": [
                {
                    "key": key,
                    "count": len([signal for signal in signals if status_bucket(signal) == key]),
                    "share": share(len([signal for signal in signals if status_bucket(signal) == key]), len(signals)),
                }
                for key in sorted({status_bucket(signal) for signal in signals})
            ],
            "baselineComparisons": [dict(item) for item in control_backtests],
            "warnings": list(dict.fromkeys((distribution.get("warnings") or []) + [
                "对照组和分层诊断只能作为研究线索，不能直接覆盖默认参数。",
            ])),
        }

    @staticmethod
    def _record_strategy_decisions(
        frames: list[dict[str, Any]],
        signals: list[dict[str, Any]],
        strategy_name: str,
        trade_config: dict[str, Any],
    ) -> dict[str, Any]:
        """跑四层策略流水线，记录每帧的候选分层和买卖信号（不改变执行路径）。"""
        strategy = get_strategy(strategy_name)
        signals_by_snapshot: dict[str, list[dict[str, Any]]] = {}
        for s in signals:
            signals_by_snapshot.setdefault(str(s.get("snapshotId") or ""), []).append(s)
        signal_by_key: dict[str, dict[str, Any]] = {}
        for s in signals:
            signal_by_key[f"{s.get('snapshotId')}:{s.get('code')}"] = s

        frame_results: list[FrameStrategyResult] = []
        positions: dict[str, Any] = {}
        tier_counts: dict[str, int] = {tier: 0 for tier in ("A_MAIN", "B_IGNITION", "C_CROWDED", "D_EXIT_RISK", "N_NEUTRAL")}
        signal_counts: dict[str, int] = {"buy": 0, "sell": 0, "hold": 0, "watch": 0}

        for idx, frame in enumerate(frames):
            snapshot_id = str(frame.get("snapshotId") or "")
            frame_signals = signals_by_snapshot.get(snapshot_id, [])
            previous_frame = frames[idx - 1] if idx > 0 else None
            input = StrategyInput(
                frame=frame,
                frame_signals=frame_signals,
                previous_frame=previous_frame,
                signal_by_key=signal_by_key,
                positions=positions,
                strategy_key=strategy_name,
                config=trade_config,
                theme_support_by_code=build_theme_support_index(frame),
            )
            result = strategy.evaluate_frame(input)
            frame_results.append(result)
            for d in result.decisions:
                tier_counts[d.candidate_tier] = tier_counts.get(d.candidate_tier, 0) + 1
                signal_counts[d.signal] = signal_counts.get(d.signal, 0) + 1
                if d.signal == "buy":
                    positions[d.code] = {"entryTier": d.candidate_tier, "entrySnapshotId": snapshot_id}
                elif d.signal == "sell":
                    positions.pop(d.code, None)

        return {
            "strategyKey": strategy_name,
            "strategyLabel": strategy.label,
            "frameCount": len(frame_results),
            "frameResults": [r.to_dict() for r in frame_results],
            "tierDistribution": tier_counts,
            "signalDistribution": signal_counts,
            "totalDecisions": sum(tier_counts.values()),
        }

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
    """Compatibility wrapper for the moved optimization module."""

    def run(self, frames: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, Any]:
        from backend.optimization.runner import OptimizationRunner

        return OptimizationRunner().run(frames, request)
