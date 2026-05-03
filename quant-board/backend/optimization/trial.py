from __future__ import annotations

from typing import Any

from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine
from backend.core.backtest import BacktestEngine, TradeSimulator
from backend.optimization import objective
from backend.optimization.search_space import freeze, to_strategy_config, to_trade_config
from backend.optimization.validation import frame_range
from backend.utils import new_id, stable_hash


class TrialExecutor:
    def evaluate(
        self,
        index: int,
        params: dict[str, Any],
        split: dict[str, Any],
        base_strategy_config: dict[str, Any],
        base_trade_config: dict[str, Any],
        strategy_name: str,
        objective_name: str,
        request: dict[str, Any],
        signal_cache: dict[str, list[dict[str, Any]]],
        source: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        trial_id = f"trial_{index:04d}"
        strategy_config = {**base_strategy_config, **to_strategy_config(params)}
        trade_config = {**base_trade_config, **to_trade_config(params), "entryStrategy": strategy_name}
        config_hash = stable_hash(
            {
                "dataset_id": request.get("dataset_id"),
                "snapshot_type": request.get("snapshot_type"),
                "strategy_name": strategy_name,
                "strategy_version": request.get("strategy_version") or request.get("strategyVersion"),
                "method": request.get("method"),
                "random_seed": request.get("random_seed"),
                "search_space": request.get("search_space"),
                "strategy_config": strategy_config,
                "trade_config": trade_config,
                "parameters": params,
                "split": split["metadata"],
            }
        )
        try:
            train_eval = self.evaluate_phase(
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
                validation_eval = self.evaluate_phase(
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
            score_details = objective.score_trial(
                train_eval["simulation"],
                validation_eval["simulation"] if validation_eval else None,
                objective_name,
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
                "train": objective.phase_public(train_eval, objective_name),
                "validation": objective.phase_public(validation_eval, objective_name) if validation_eval else None,
                "metrics": (validation_eval or train_eval)["metrics"],
                "stability": objective.trial_stability(train_eval["metrics"], validation_eval["metrics"] if validation_eval else None, score_details),
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

    def evaluate_phase(
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
        signal_key = freeze(
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
        metrics = self.metrics(simulation, len(phase_signals))
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
            "range": frame_range(phase_frames),
        }
        return {
            "phase": phase,
            "runId": run_id,
            "range": frame_range(phase_frames),
            "signalFrameRange": frame_range(signal_frames),
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

    @staticmethod
    def metrics(result: dict[str, Any], signal_count: int) -> dict[str, Any]:
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
