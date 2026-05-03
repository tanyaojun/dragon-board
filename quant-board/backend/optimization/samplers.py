from __future__ import annotations

from typing import Any

from backend.optimization.search_space import OPTUNA_METHODS, score_value, suggest_params
from backend.optimization.trial import TrialExecutor


class OptunaSearchRunner:
    def __init__(self, trial_executor: TrialExecutor | None = None) -> None:
        self.trial_executor = trial_executor or TrialExecutor()

    def run(
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
        if method not in OPTUNA_METHODS:
            raise ValueError(f"unsupported optuna optimization method: {method}")
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
            params = suggest_params(optuna_trial, search_space)
            trial, trial_artifacts = self.trial_executor.evaluate(
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
            return score_value(trial.get("score"))

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
