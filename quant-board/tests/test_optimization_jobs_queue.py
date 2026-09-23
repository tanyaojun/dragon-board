# -*- coding: utf-8 -*-
"""优化任务队列护栏测试（2026-09-23 内存堆积事故）。

背景：submit_optimization_job 单 worker + 无界队列，每个排队任务持有全量 frames
（约 2-4GB Python 对象），多任务排队即整机换页冻结。护栏：排队数超限直接拒绝，
完成的 future 从登记表移除；服务层在入队失败时把已落库 running 记录收口为 failed。
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import pytest

from backend.optimization import jobs as jobs_mod
from backend.optimization.jobs import MAX_PENDING_JOBS, OptimizationQueueFull


def _pending_future() -> Future[Any]:
    # 未启动的 Future：done()=False 且 running()=False，等价于"在队列里等 worker"
    return Future()


def _stub_payload() -> dict[str, dict[str, Any]]:
    return {"method": "grid"}


def test_pending_over_limit_rejected_without_touching_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_registry = {f"opt_{i}": _pending_future() for i in range(MAX_PENDING_JOBS)}
    monkeypatch.setattr(jobs_mod, "_FUTURES", fake_registry)

    def _fail_submit(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("queue full 时不应再向 executor 提交任务")

    monkeypatch.setattr(jobs_mod, "_EXECUTOR", type("_E", (), {"submit": staticmethod(_fail_submit)}))

    with pytest.raises(OptimizationQueueFull):
        jobs_mod.submit_optimization_job(
            run_id="opt_new",
            frames=[],
            request=_stub_payload(),
            dataset_id="d",
            snapshot_type="half_hour",
            strategy_name="s",
            random_seed=1,
            config_hash="h",
            payload_for_request_json={},
        )


def test_capacity_freed_after_jobs_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    real_executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(jobs_mod, "_FUTURES", {})
    monkeypatch.setattr(jobs_mod, "_EXECUTOR", real_executor)
    monkeypatch.setattr(jobs_mod, "_run_job", lambda *_args: None)

    try:
        futures = []
        for i in range(MAX_PENDING_JOBS):
            futures.append(
                jobs_mod.submit_optimization_job(
                    run_id=f"opt_{i}",
                    frames=[],
                    request=_stub_payload(),
                    dataset_id="d",
                    snapshot_type="half_hour",
                    strategy_name="s",
                    random_seed=1,
                    config_hash="h",
                    payload_for_request_json={},
                )
            )
        for future in futures:
            assert future.result(timeout=5) is None
        # 完成后登记表清空：排队容量恢复
        assert jobs_mod._FUTURES == {}
        jobs_mod.submit_optimization_job(
            run_id="opt_next",
            frames=[],
            request=_stub_payload(),
            dataset_id="d",
            snapshot_type="half_hour",
            strategy_name="s",
            random_seed=1,
            config_hash="h",
            payload_for_request_json={},
        )
        assert jobs_mod._FUTURES["opt_next"].result(timeout=5) is None
    finally:
        real_executor.shutdown(wait=True)


def test_service_marks_run_failed_when_queue_full(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.optimization_service import OptimizationService
    from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

    saved: list[Any] = []

    class _StubRepo:
        def __init__(self) -> None:
            self.last_fields: list[str] | None = None

        def load_frames(
            self,
            dataset_id: str,
            snapshot_type: str = "half_hour",
            start_date: str | None = None,
            end_date: str | None = None,
            include_payload: bool = True,
            fields: list[str] | None = None,
        ) -> list[dict[str, Any]]:
            self.last_fields = fields
            return [
                {
                    "snapshotId": "s1", "type": "half_hour", "timestamp": 1,
                    "tradingDate": "2026-08-01", "slotTime": "10:00",
                    "captureMode": "real_time", "source": "test",
                    "stocks": [{"snapshotId": "s1", "code": "000001", "capitalFlowSource": "ths"}],
                },
                {
                    "snapshotId": "s2", "type": "half_hour", "timestamp": 2,
                    "tradingDate": "2026-08-01", "slotTime": "10:30",
                    "captureMode": "real_time", "source": "test",
                    "stocks": [{"snapshotId": "s2", "code": "000002", "capitalFlowSource": "ths"}],
                },
            ]

        def save_optimization_run(self, run: Any) -> None:
            saved.append(run)

    def _raise_queue_full(**_kwargs: Any) -> None:
        raise OptimizationQueueFull(MAX_PENDING_JOBS)

    monkeypatch.setattr("backend.services.optimization_service.submit_optimization_job", _raise_queue_full)

    stub = _StubRepo()
    service = OptimizationService.__new__(OptimizationService)
    service.repo = stub

    with pytest.raises(OptimizationQueueFull):
        service.run_ranktrend(
            {
                "dataset_id": "dragonboard_live",
                "snapshot_type": "half_hour",
                "method": "random",
                "max_trials": 2,
                "random_seed": 20260430,
            }
        )

    statuses = [run.status for run in saved]
    assert statuses == ["running", "failed"], f"initial running 记录必须在入队失败后收口为 failed，实际落库: {statuses}"
    failure_payload = saved[-1].result_json
    assert "OPTIMIZATION_QUEUE_FULL" in failure_payload
    assert stub.last_fields == list(BACKTEST_RANKTREND_STOCK_FIELDS)
