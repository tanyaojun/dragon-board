from __future__ import annotations

import itertools
import math
import random
from typing import Any

from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine
from backend.core.backtest import BacktestEngine, TradeSimulator, _round_or_none, normalize_strategy_name, share
from backend.utils import new_id, stable_hash


OPTUNA_METHODS = {"bayesian", "tpe", "optuna_tpe"}


class OptimizationRunner:
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
        if method not in {"grid", "random", *OPTUNA_METHODS}:
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
        if method in OPTUNA_METHODS:
            trials, backtest_artifacts, optimizer_meta = self._run_optuna_trials(
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
        method: str,
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
            raise ValueError(f"method={method} requires optuna; install quant-board requirements first") from error

        startup_trials = max(1, min(max_trials, int(request.get("startup_trials") or request.get("startupTrials") or min(10, max_trials))))
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        if method == "bayesian":
            try:
                import torch  # noqa: F401
            except ImportError as error:
                raise ValueError("method=bayesian requires torch because Optuna GPSampler depends on torch") from error
            sampler = optuna.samplers.GPSampler(seed=random_seed)
            optimizer_name = "optuna_gp"
            sampler_name = "GPSampler"
            trial_source = "optuna_gp"
        else:
            sampler = optuna.samplers.TPESampler(seed=random_seed, n_startup_trials=startup_trials)
            optimizer_name = "optuna_tpe"
            sampler_name = "TPESampler"
            trial_source = "optuna_tpe"
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
                source=trial_source,
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
            "name": optimizer_name,
            "library": "optuna",
            "sampler": sampler_name,
            "startupTrials": startup_trials,
            "studyBestValue": study.best_value if trials else None,
        }
        if method == "bayesian":
            meta["model"] = "gaussian_process"
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
            return "{" + ",".join(f"{key}:{OptimizationRunner._freeze(value[key])}" for key in sorted(value)) + "}"
        if isinstance(value, list):
            return "[" + ",".join(OptimizationRunner._freeze(item) for item in value) + "]"
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
