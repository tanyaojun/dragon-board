from __future__ import annotations

import random
from typing import Any

from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine
from backend.core.backtest import BacktestEngine, normalize_strategy_name
from backend.optimization.experiment import experiment_summary
from backend.optimization.samplers import OptunaSearchRunner
from backend.optimization.search_space import (
    OPTUNA_METHODS,
    SUPPORTED_METHODS,
    candidates,
    default_search_space,
    normalize_search_space,
    score_value,
    search_space_mode,
)
from backend.optimization.stability import parameter_stability
from backend.optimization.trial import TrialExecutor
from backend.optimization.validation import split_frames
from backend.optimization.walk_forward import WalkForwardValidator


class OptimizationRunner:
    """Entry-point orchestrator for one optimization experiment."""

    def __init__(
        self,
        trial_executor: TrialExecutor | None = None,
        optuna_runner: OptunaSearchRunner | None = None,
        walk_forward_validator: WalkForwardValidator | None = None,
    ) -> None:
        self.trial_executor = trial_executor or TrialExecutor()
        self.optuna_runner = optuna_runner or OptunaSearchRunner(self.trial_executor)
        self.walk_forward_validator = walk_forward_validator or WalkForwardValidator(self.trial_executor)

    def run(self, frames: list[dict[str, Any]], request: dict[str, Any]) -> dict[str, Any]:
        random_seed = int(request.get("random_seed") or 0)
        method = str(request.get("method") or "grid").strip().lower()
        if method not in SUPPORTED_METHODS:
            raise ValueError(f"unsupported optimization method: {method}")

        search_space = normalize_search_space(request.get("search_space") or default_search_space())
        search_mode = search_space_mode(search_space)
        candidate_rows = candidates(search_space)
        total_candidate_count = len(candidate_rows)
        max_trials = max(1, int(request.get("max_trials") or request.get("trials") or 12))

        base_backtest = request.get("backtest") or {}
        base_strategy_config = base_backtest.get("strategy_config") or base_backtest.get("strategyConfig") or {}
        base_trade_config = base_backtest.get("trade_config") or base_backtest.get("tradeConfig") or {}
        strategy_name = normalize_strategy_name(
            request.get("strategy_name")
            or request.get("strategyName")
            or base_backtest.get("strategy_name")
            or base_backtest.get("strategyName")
            or base_trade_config.get("entryStrategy")
            or base_trade_config.get("strategyName")
        )
        objective = str(request.get("objective") or "return")
        signal_cache: dict[str, list[dict[str, Any]]] = {}
        data_quality = self._data_quality(frames, request, base_strategy_config)
        split = split_frames(frames, request)

        trials: list[dict[str, Any]]
        backtest_artifacts: list[dict[str, Any]]
        optimizer_meta: dict[str, Any] = {"name": method}
        executed_candidate_count = min(max_trials, total_candidate_count)
        if method in OPTUNA_METHODS:
            trials, backtest_artifacts, optimizer_meta = self.optuna_runner.run(
                method,
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
            executed_candidate_count = len(trials)
        else:
            if method == "random":
                random.Random(random_seed).shuffle(candidate_rows)
            trials, backtest_artifacts = self._run_discrete_candidates(
                candidate_rows[:max_trials],
                method,
                split,
                base_strategy_config,
                base_trade_config,
                strategy_name,
                objective,
                request,
                signal_cache,
            )

        trials.sort(key=lambda item: (item.get("status") == "completed", score_value(item.get("score"))), reverse=True)
        for rank, trial in enumerate(trials, start=1):
            trial["rank"] = rank
        completed_trials = [trial for trial in trials if trial.get("status") == "completed"]
        best = completed_trials[0] if completed_trials else None

        walk_forward = self.walk_forward_validator.run(
            frames,
            completed_trials,
            request,
            base_strategy_config,
            base_trade_config,
            strategy_name,
            objective,
            signal_cache,
        )
        experiment = experiment_summary(
            split,
            request,
            total_candidate_count,
            executed_candidate_count,
            trials,
            best,
            walk_forward,
            data_quality,
        )
        return {
            "method": method,
            "optimizer": optimizer_meta["name"],
            "optimizerMeta": optimizer_meta,
            "searchSpaceMode": search_mode,
            "search_space_mode": search_mode,
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
            "parameterStability": parameter_stability(completed_trials),
            "walkForward": walk_forward,
            "best": best,
            "trials": trials,
            "results": trials,
            "warnings": experiment["warnings"],
            "backtestArtifacts": backtest_artifacts,
        }

    def _run_discrete_candidates(
        self,
        candidate_rows: list[dict[str, Any]],
        method: str,
        split: dict[str, Any],
        base_strategy_config: dict[str, Any],
        base_trade_config: dict[str, Any],
        strategy_name: str,
        objective: str,
        request: dict[str, Any],
        signal_cache: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        trials: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        for index, params in enumerate(candidate_rows, start=1):
            trial, trial_artifacts = self.trial_executor.evaluate(
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
            artifacts.extend(trial_artifacts)
        return trials, artifacts

    @staticmethod
    def _data_quality(
        frames: list[dict[str, Any]],
        request: dict[str, Any],
        base_strategy_config: dict[str, Any],
    ) -> dict[str, Any]:
        base_ranktrend_config = RankTrendConfig.from_patch(base_strategy_config)
        quality_signals = RankTrendPythonEngine(base_ranktrend_config).replay(frames, meta={"sampleQuality": "ok", "warnings": []})
        return BacktestEngine._data_quality_summary(
            request.get("quality_gate"),
            BacktestEngine._sample_diagnostics(frames, quality_signals, base_ranktrend_config),
            BacktestEngine._macd_diagnostics(base_ranktrend_config, frames),
        )
