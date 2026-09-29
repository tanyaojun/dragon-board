from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import nullcontext
from typing import Any, Callable

from backend.data.ingest.json_codec import dumps_json_field
from backend.data.models.models import BacktestRun, OptimizationRun
from backend.data.repositories.repository_factory import create_repository, storage_source_label
from backend.optimization.runner import OptimizationRunner
from backend.core.utils import stable_hash

# 每个 pending 任务都持有全量 frames（生产数据集约 2-4GB Python 对象）。
# 2026-09-23 事故：无界队列堆积多份 frames 副本 → 整机换页冻结行情链。
# 上限 = 执行中 1 + 排队 2，超限直接拒绝（fail-visible，由调用方决定重试）。
MAX_PENDING_JOBS = 2


class OptimizationQueueFull(Exception):
    """优化任务排队数超过 MAX_PENDING_JOBS 时拒绝新任务。"""

    def __init__(self, pending: int) -> None:
        self.pending = pending
        super().__init__(
            f"optimization job queue is full (pending={pending}, limit={MAX_PENDING_JOBS}); "
            "wait for running jobs to finish before submitting"
        )


_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quant-optimization")
_FUTURES: dict[str, Future[Any]] = {}


def _pending_job_count() -> int:
    return sum(1 for future in _FUTURES.values() if not future.done() and not future.running())


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
    session_factory: Callable[[], Any] | None = None,
) -> Future[Any]:
    if _pending_job_count() >= MAX_PENDING_JOBS:
        raise OptimizationQueueFull(_pending_job_count())
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
    # 任务结束后从登记表移除：释放引用，也让排队容量随之恢复
    future.add_done_callback(lambda _done, rid=run_id: _FUTURES.pop(rid, None))
    return future


def get_job_status(run_id: str) -> str | None:
    """返回任务执行态；完成的任务会被移出登记表（终态以仓库记录为准）。"""
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
        with _job_session(session_factory) as session:
            repo = create_repository(session)
            for artifact in backtest_artifacts:
                artifact_request = {
                    **(artifact.get("request") or {}),
                    "artifact_type": "optimization_trial",
                    "artifactType": "optimization_trial",
                }
                artifact_result = artifact.get("result") or {}
                repo.save_backtest_run(
                    BacktestRun(
                        id=str(artifact.get("runId")),
                        dataset_id=dataset_id,
                        strategy_name=strategy_name,
                        snapshot_type=snapshot_type,
                        random_seed=random_seed,
                        status="completed",
                        config_hash=str(artifact.get("configHash") or stable_hash(artifact_request)),
                        request_json=dumps_json_field(artifact_request),
                        result_json=dumps_json_field(artifact_result),
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
                    request_json=dumps_json_field(payload_for_request_json),
                    result_json=dumps_json_field(result),
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
        with _job_session(session_factory) as session:
            create_repository(session).save_optimization_run(
                OptimizationRun(
                    id=run_id,
                    dataset_id=dataset_id,
                    strategy_name=strategy_name,
                    method=str(request.get("method") or "grid"),
                    random_seed=random_seed,
                    status="failed",
                    config_hash=config_hash,
                    request_json=dumps_json_field(payload_for_request_json),
                    result_json=dumps_json_field(failure),
                )
            )


def _job_session(session_factory: Callable[[], Any] | None) -> Any:
    if storage_source_label() == "mongodb":
        return nullcontext(None)
    return session_factory()
