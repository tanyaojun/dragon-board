from __future__ import annotations

from typing import Any

from backend.core.backtest import share
from backend.optimization.search_space import score_value
from backend.optimization.trial import TrialExecutor
from backend.optimization.validation import frame_range, with_warmup


class WalkForwardValidator:
    def __init__(self, trial_executor: TrialExecutor | None = None) -> None:
        self.trial_executor = trial_executor or TrialExecutor()

    def run(
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
                "validation_signal_frames": with_warmup(frames, validation_frames, int(config.get("validation_warmup_bars") or config.get("validationWarmupBars") or 40)),
                "metadata": {
                    "mode": "walk_forward",
                    "train": frame_range(train_frames),
                    "validation": frame_range(validation_frames),
                    "hasValidation": True,
                },
            }
            for candidate in selected_trials:
                params = candidate.get("parameters") or {}
                segment_trial, _ = self.trial_executor.evaluate(
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
            segment_trials.sort(key=lambda item: score_value(item.get("score")), reverse=True)
            if segment_trials:
                selected = segment_trials[0]
                segments.append(
                    {
                        "segmentId": len(segments) + 1,
                        "trainRange": frame_range(train_frames),
                        "validationRange": frame_range(validation_frames),
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
            "aggregate": aggregate(segments),
            "warnings": warnings,
        }


def aggregate(segments: list[dict[str, Any]]) -> dict[str, Any]:
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
