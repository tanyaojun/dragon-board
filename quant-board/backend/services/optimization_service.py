from __future__ import annotations
import gzip
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from sqlalchemy.orm import Session
from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.live_gate_shadow_audit import (
    DEFAULT_SHADOW_VARIANTS,
    _nested_get,
    build_audit_meta,
    classify_hotlist_buy_pattern,
    evaluate_shadow_variants,
    rank_shadow_candidate,
    scan_jump_confidence_thresholds,
    summarize_fusion_gate_misses,
    summarize_first_failure,
    summarize_jump_definition_replays,
)
from backend.analysis.ranktrend.jump_research import build_jump_research_request, summarize_jump_research
from backend.analysis.theme.trend import ThemeTrendConfig, ThemeTrendPythonEngine
from backend.core.backtest import (
    DEFAULT_TRADE_CONFIG,
    V5_LIFECYCLE_FUSION_TRADE_DEFAULTS,
    BacktestEngine,
    TradeSimulator,
    normalize_strategy_name,
)
from backend.data.models.models import BacktestRun, GoldenRankTrendCase, OptimizationRun
from backend.data.ingest.quality_gate import evaluate_snapshot_quality
from backend.data.ingest.json_codec import dumps_json_field, loads_json_field
from backend.data.models.database import SessionLocal
from backend.data.repositories.repository import Repository
from backend.data.repositories.repository_factory import create_repository, storage_source_label
from backend.optimization.jobs import submit_optimization_job
from backend.optimization.runner import OptimizationRunner
from backend.optimization.search_space import candidate_count, select_candidates
from backend.core.utils import json_dumps, json_loads, new_id, read_json_file, stable_hash
from backend.services.shared import (
    DEFAULT_BACKTEST_STRATEGY_CONFIG,
    camel_get,
    _prepare_frames_for_backtest
)


class OptimizationService:
    def __init__(self, session: Session | None):
        self.repo = create_repository(session)

    def run_ranktrend(self, payload: dict[str, Any], wait: bool = False) -> dict[str, Any]:
        dataset_id, snapshot_type, strategy_name, run_frames, request, payload_for_request_json = self._build_request(payload)
        if ((request.get("quality_gate") or {}).get("researchGrade")) == "blocked":
            raise ValueError({"qualityGate": request.get("quality_gate"), "reason": "data quality blocked optimization"})
        run_id = str(request["optimization_run_id"])
        config_hash = stable_hash({key: value for key, value in request.items() if key != "optimization_run_id"})
        initial = OptimizationRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            method=request["method"],
            random_seed=request["random_seed"],
            status="running",
            config_hash=config_hash,
            request_json=dumps_json_field(payload_for_request_json),
            result_json=dumps_json_field({"status": "running", "runId": run_id}),
        )
        self.repo.save_optimization_run(initial)
        if wait:
            return self._run_sync(
                run_id,
                dataset_id,
                snapshot_type,
                strategy_name,
                run_frames,
                request,
                payload_for_request_json,
                config_hash,
            )
        submit_optimization_job(
            run_id=run_id,
            frames=run_frames,
            request=request,
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            strategy_name=strategy_name,
            random_seed=request["random_seed"],
            config_hash=config_hash,
            payload_for_request_json=payload_for_request_json,
        )
        return {
            "id": run_id,
            "runId": run_id,
            "run_id": run_id,
            "status": "running",
            "method": request["method"],
            "strategyName": strategy_name,
            "randomSeed": request["random_seed"],
        }

    def run_theme_trend(self, payload: dict[str, Any], wait: bool = False) -> dict[str, Any]:
        """执行题材趋势策略参数优化（grid/random 搜索）。

        wait 参数保留用于与 run_ranktrend 接口对齐；当前 MVP 始终同步执行。
        后续可扩展异步路径。
        """
        from backend.optimization.search_space import (
            theme_confluence_search_space,
            theme_parameter_groups,
            theme_search_space,
            normalize_search_space,
            select_candidates,
        )
        from backend.optimization.objective import score_theme_trend

        dataset_id = str(camel_get(payload, "dataset_id", "datasetId", ""))
        snapshot_type = str(camel_get(payload, "snapshot_type", "snapshotType", "half_hour"))
        strategy_name = str(camel_get(payload, "strategy_name", "strategyName", "theme_rotation"))
        search_profile = str(camel_get(payload, "search_profile", "searchProfile", "theme_trend"))
        method = str(camel_get(payload, "method", default="random"))
        objective = str(camel_get(payload, "objective", default="stability"))
        random_seed = int(camel_get(payload, "random_seed", "randomSeed", 20260430))
        max_trials = max(1, int(camel_get(payload, "trials", default=12)))

        frames = self.repo.load_frame_bundles(dataset_id, snapshot_type=snapshot_type)
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")

        param_grid_input = camel_get(payload, "parameter_grid", "parameterGrid", {}) or {}
        search_space = normalize_search_space(
            param_grid_input
            if param_grid_input
            else (theme_confluence_search_space() if search_profile == "theme_confluence" else theme_search_space())
        )

        run_id = new_id("opt")
        config_hash = stable_hash({k: v for k, v in payload.items() if k != "parameterGrid"})

        trial_results: list[dict[str, Any]] = []
        total_candidates = candidate_count(search_space)
        trial_params_list = select_candidates(search_space, max_trials, method, random_seed)

        trial_errors: list[dict[str, Any]] = []
        for trial_idx, trial_params in enumerate(trial_params_list):
            try:
                config = ThemeTrendConfig.from_patch({
                    k: v for k, v in trial_params.items()
                })
                engine_result = ThemeTrendPythonEngine().replay_sequence(frames, config=config)
                score = score_theme_trend(engine_result, objective)
                trial_results.append({
                    "trialId": trial_idx,
                    "params": {k: v for k, v in trial_params.items()},
                    "score": score,
                    "themeCount": len(engine_result.get("factors", [])),
                    "mainlineCount": sum(1 for f in engine_result.get("factors", []) if f.get("lifecycle") == "mainline"),
                    "engineFactors": engine_result.get("factors", [])[:50],
                })
            except Exception as exc:
                trial_errors.append({
                    "trialId": trial_idx,
                    "params": {k: v for k, v in trial_params.items()},
                    "error": str(exc)[:200],
                })

        trial_results.sort(key=lambda t: t["score"], reverse=True)
        best = trial_results[0] if trial_results else {}

        result_payload = {
            "runId": run_id,
            "method": method,
            "objective": objective,
            "searchProfile": search_profile,
            "supportedParameterGroups": theme_parameter_groups(search_profile),
            "candidateCount": total_candidates,
            "trials": len(trial_results),
            "trialErrors": trial_errors,
            "best": best,
            "trialList": trial_results[:50],
        }

        opt_run = OptimizationRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            method=method,
            random_seed=random_seed,
            status="completed" if trial_results else "failed",
            config_hash=config_hash,
            request_json=dumps_json_field(payload),
            result_json=dumps_json_field(result_payload),
        )
        self.repo.save_optimization_run(opt_run)

        return {
            "id": run_id,
            "runId": run_id,
            "status": opt_run.status,
            "method": method,
            "strategyName": strategy_name,
            "analysisMode": "theme_trend",
            "searchProfile": search_profile,
            "supportedParameterGroups": theme_parameter_groups(search_profile),
            "candidateCount": total_candidates,
            "randomSeed": random_seed,
            "best": best,
            "trialCount": len(trial_results),
        }

    def run_theme_confluence(self, payload: dict[str, Any], wait: bool = False) -> dict[str, Any]:
        request = {
            **payload,
            "strategy_name": camel_get(payload, "strategy_name", "strategyName", "hotlist_theme_confluence"),
            "strategyName": camel_get(payload, "strategy_name", "strategyName", "hotlist_theme_confluence"),
            "search_profile": "theme_confluence",
            "searchProfile": "theme_confluence",
        }
        result = self.run_theme_trend(request, wait=wait)
        result["analysisMode"] = "theme_confluence"
        result["strategyName"] = str(request["strategyName"])
        result["searchProfile"] = "theme_confluence"
        return result

    def run_ranktrend_jump_research(self, payload: dict[str, Any]) -> dict[str, Any]:
        research_payload = build_jump_research_request(payload)
        dataset_id, snapshot_type, strategy_name, run_frames, request, payload_for_request_json = self._build_request(research_payload)
        if ((request.get("quality_gate") or {}).get("researchGrade")) == "blocked":
            raise ValueError({"qualityGate": request.get("quality_gate"), "reason": "data quality blocked jump research"})
        run_id = str(request["optimization_run_id"])
        config_hash = stable_hash({key: value for key, value in request.items() if key != "optimization_run_id"})
        result = OptimizationRunner().run(run_frames, request)
        summary = summarize_jump_research(
            result,
            fill_fallback_mode=str((research_payload.get("backtest") or {}).get("trade_config", {}).get("fillFallbackMode") or "fallback_penalized"),
        )
        backtest_artifacts = result.pop("backtestArtifacts", []) or []
        for artifact in backtest_artifacts:
            artifact_request = {
                **(artifact.get("request") or {}),
                "artifact_type": "ranktrend_jump_research_trial",
                "artifactType": "ranktrend_jump_research_trial",
            }
            self.repo.save_backtest_run(
                BacktestRun(
                    id=str(artifact.get("runId")),
                    dataset_id=dataset_id,
                    strategy_name=strategy_name,
                    snapshot_type=snapshot_type,
                    random_seed=request["random_seed"],
                    status="completed",
                    config_hash=str(artifact.get("configHash") or stable_hash(artifact_request)),
                    request_json=dumps_json_field(artifact_request),
                    result_json=dumps_json_field(artifact.get("result") or {}),
                )
            )
        result["researchSummary"] = summary
        run = OptimizationRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            method=request["method"],
            random_seed=request["random_seed"],
            status="completed",
            config_hash=config_hash,
            request_json=dumps_json_field(payload_for_request_json),
            result_json=dumps_json_field(result),
        )
        self.repo.save_optimization_run(run)
        return {
            "id": run_id,
            "runId": run_id,
            "run_id": run_id,
            "status": "completed",
            "analysisMode": "ranktrend_jump_research",
            "strategyName": strategy_name,
            "method": request["method"],
            "randomSeed": request["random_seed"],
            "configHash": config_hash,
            "summary": summary,
            "result": result,
            **result,
        }

    def _build_request(self, payload: dict[str, Any]) -> tuple[str, str, str, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        dataset_id = str(camel_get(payload, "dataset_id", "datasetId", ""))
        snapshot_type = str(camel_get(payload, "snapshot_type", "snapshotType", "half_hour"))
        base_backtest = camel_get(payload, "backtest", default={}) or {}
        base_trade_config = base_backtest.get("trade_config") or base_backtest.get("tradeConfig") or {}
        base_strategy_config = {
            **DEFAULT_BACKTEST_STRATEGY_CONFIG,
            **(base_backtest.get("strategy_config") or base_backtest.get("strategyConfig") or {}),
        }
        payload_strategy_name = camel_get(payload, "strategy_name", "strategyName", None)
        strategy_name = normalize_strategy_name(
            payload_strategy_name
            if payload_strategy_name is not None
            else base_backtest.get("strategy_name")
            or base_backtest.get("strategyName")
            or base_trade_config.get("entryStrategy")
            or base_trade_config.get("controlStrategy")
            or base_trade_config.get("strategyName")
        )
        frames = self.repo.load_frames(dataset_id, snapshot_type=snapshot_type, include_payload=True)
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")
        run_frames, quality_gate = _prepare_frames_for_backtest(frames, snapshot_type)
        search_space = camel_get(payload, "search_space", "searchSpace")
        if not search_space:
            search_space = camel_get(payload, "parameter_grid", "parameterGrid", {})
        request = {
            "method": str(payload.get("method", "grid")).strip().lower(),
            "random_seed": int(camel_get(payload, "random_seed", "randomSeed", 20260430)),
            "max_trials": int(camel_get(payload, "max_trials", "trials", 12)),
            "objective": payload.get("objective", "return"),
            "search_space": search_space,
            "strategy_name": strategy_name,
            "strategy_version": camel_get(payload, "strategy_version", "strategyVersion", "0.1.0"),
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "quality_gate": quality_gate,
            "validation_mode": camel_get(payload, "validation_mode", "validationMode", "none"),
            "validation_ratio": float(camel_get(payload, "validation_ratio", "validationRatio", 0.3)),
            "validation_warmup_bars": int(camel_get(payload, "validation_warmup_bars", "validationWarmupBars", 40)),
            "train_range": camel_get(payload, "train_range", "trainRange", None),
            "validation_range": camel_get(payload, "validation_range", "validationRange", None),
            "walk_forward": camel_get(payload, "walk_forward", "walkForward", None),
            "backtest": {**base_backtest, "strategy_name": strategy_name, "strategy_config": base_strategy_config},
        }
        run_id = new_id("opt")
        request["optimization_run_id"] = run_id
        payload_for_request_json = {**payload, **request}
        return dataset_id, snapshot_type, strategy_name, run_frames, request, payload_for_request_json

    def _run_sync(
        self,
        run_id: str,
        dataset_id: str,
        snapshot_type: str,
        strategy_name: str,
        run_frames: list[dict[str, Any]],
        request: dict[str, Any],
        payload_for_request_json: dict[str, Any],
        config_hash: str,
    ) -> dict[str, Any]:
        result = OptimizationRunner().run(run_frames, request)
        backtest_artifacts = result.pop("backtestArtifacts", []) or []
        for artifact in backtest_artifacts:
            artifact_request = {
                **(artifact.get("request") or {}),
                "artifact_type": "optimization_trial",
                "artifactType": "optimization_trial",
            }
            artifact_result = artifact.get("result") or {}
            self.repo.save_backtest_run(
                BacktestRun(
                    id=str(artifact.get("runId")),
                    dataset_id=dataset_id,
                    strategy_name=strategy_name,
                    snapshot_type=snapshot_type,
                    random_seed=request["random_seed"],
                    status="completed",
                    config_hash=str(artifact.get("configHash") or stable_hash(artifact_request)),
                    request_json=dumps_json_field(artifact_request),
                    result_json=dumps_json_field(artifact_result),
                )
            )
        run = OptimizationRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            method=request["method"],
            random_seed=request["random_seed"],
            status="completed",
            config_hash=config_hash,
            request_json=dumps_json_field(payload_for_request_json),
            result_json=dumps_json_field(result),
        )
        self.repo.save_optimization_run(run)
        return {"id": run_id, "runId": run_id, "run_id": run_id, "status": "completed", "result": result, **result}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_optimization_run(run_id)
        if not run:
            return None
        result = loads_json_field(run.result_json, {})
        status = run.status or result.get("status") or "completed"
        if status != "completed":
            return {
                "id": run.id,
                "runId": run.id,
                "datasetId": run.dataset_id,
                "strategyName": run.strategy_name,
                "method": run.method,
                "randomSeed": run.random_seed,
                "configHash": run.config_hash,
                "status": status,
                "createdAt": run.created_at.isoformat(),
                "result": result,
                **(result if isinstance(result, dict) else {}),
            }
        return {
            "id": run.id,
            "runId": run.id,
            "datasetId": run.dataset_id,
            "strategyName": run.strategy_name,
            "method": run.method,
            "randomSeed": run.random_seed,
            "configHash": run.config_hash,
            "status": status,
            "createdAt": run.created_at.isoformat(),
            "result": result,
            **result,
        }
