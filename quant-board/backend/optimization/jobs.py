from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from backend.data.database import SessionLocal
from backend.data.models import BacktestRun, OptimizationRun
from backend.data.repository import Repository
from backend.optimization.runner import OptimizationRunner
from backend.utils import json_dumps, stable_hash


_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quant-optimization")
_FUTURES: dict[str, Future[Any]] = {}


def submit_optimization_job(
    *,
    run_id: str,
    frames: list[dict[str, Any]],
    request: dict[str, Any],
    dataset_id: str,
    snapshot_type: str,
    strategy_name: str,
    random_seed: int,
    config_hash: str,
    payload_for_request_json: dict[str, Any],
    session_factory: Callable[[], Any] = SessionLocal,
) -> Future[Any]:
    future = _EXECUTOR.submit(
        _run_job,
        run_id,
        frames,
        request,
        dataset_id,
        snapshot_type,
        strategy_name,
        random_seed,
        config_hash,
        payload_for_request_json,
        session_factory,
    )
    _FUTURES[run_id] = future
    return future


def get_job_status(run_id: str) -> str | None:
    future = _FUTURES.get(run_id)
    if not future:
        return None
    if future.running():
        return "running"
    if future.done():
        return "completed"
    return "pending"


def _run_job(
    run_id: str,
    frames: list[dict[str, Any]],
    request: dict[str, Any],
    dataset_id: str,
    snapshot_type: str,
    strategy_name: str,
    random_seed: int,
    config_hash: str,
    payload_for_request_json: dict[str, Any],
    session_factory: Callable[[], Any],
) -> None:
    try:
        result = OptimizationRunner().run(frames, request)
        backtest_artifacts = result.pop("backtestArtifacts", []) or []
        with session_factory() as session:
            repo = Repository(session)
            for artifact in backtest_artifacts:
                artifact_request = artifact.get("request") or {}
                artifact_result = artifact.get("result") or {}
                repo.save_backtest_run(
                    BacktestRun(
                        id=str(artifact.get("runId")),
                        dataset_id=dataset_id,
                        strategy_name=strategy_name,
                        snapshot_type=snapshot_type,
                        random_seed=random_seed,
                        config_hash=str(artifact.get("configHash") or stable_hash(artifact_request)),
                        request_json=json_dumps(artifact_request),
                        result_json=json_dumps(artifact_result),
                    )
                )
            repo.save_optimization_run(
                OptimizationRun(
                    id=run_id,
                    dataset_id=dataset_id,
                    strategy_name=strategy_name,
                    method=str(request.get("method") or "grid"),
                    random_seed=random_seed,
                    status="completed",
                    config_hash=config_hash,
                    request_json=json_dumps(payload_for_request_json),
                    result_json=json_dumps(result),
                )
            )
    except Exception as error:
        failure = {
            "status": "failed",
            "error": {
                "code": "OPTIMIZATION_FAILED",
                "message": str(error),
                "details": {"runId": run_id},
            },
        }
        with session_factory() as session:
            Repository(session).save_optimization_run(
                OptimizationRun(
                    id=run_id,
                    dataset_id=dataset_id,
                    strategy_name=strategy_name,
                    method=str(request.get("method") or "grid"),
                    random_seed=random_seed,
                    status="failed",
                    config_hash=config_hash,
                    request_json=json_dumps(payload_for_request_json),
                    result_json=json_dumps(failure),
                )
            )
