# -*- coding: utf-8 -*-
"""采集链路 analyze worker 单测（2026-09-10）。

覆盖：提交后调用 analyze、单帧异常不阻断 worker、开关关闭不提交、队列满不阻塞，
以及 collector service 接入点的源码契约（实跑验证见 api-cli.md 的上线核对口径）。
"""
import time
from pathlib import Path

import pytest

from backend.snapshot_collector import analysis_worker


@pytest.fixture(autouse=True)
def _clean_worker(monkeypatch):
    analysis_worker.reset_for_tests()
    monkeypatch.delenv(analysis_worker.ENV_ENABLED, raising=False)
    yield
    analysis_worker.reset_for_tests()


def _submit(**overrides):
    payload = {
        "db": object(),
        "dataset_id": "ds",
        "snapshot_id": "half_hour:2026-09-10:15:30",
        "snapshot_type": "half_hour",
        "trading_date": "2026-09-10",
        "slot_time": "15:30",
        "stock_rows": [{"code": "600000"}],
    }
    payload.update(overrides)
    return analysis_worker.submit_frame_analysis(**payload)


def test_submit_runs_analyze_and_records_stats(monkeypatch):
    calls = []

    def fake_analyze(task):
        calls.append(task["snapshotId"])
        return 7

    monkeypatch.setattr(analysis_worker, "_analyze_task", fake_analyze)

    assert _submit() is True
    assert analysis_worker.flush(5.0) is True
    assert calls == ["half_hour:2026-09-10:15:30"]
    stats = analysis_worker.stats()
    assert stats["submitted"] == 1
    assert stats["written"] == 1
    assert stats["lastWritten"] == 7
    assert stats["failed"] == 0


def test_analyze_failure_does_not_break_worker(monkeypatch):
    calls = []

    def flaky_analyze(task):
        calls.append(task["snapshotId"])
        if len(calls) == 1:
            raise RuntimeError("boom")
        return 2

    monkeypatch.setattr(analysis_worker, "_analyze_task", flaky_analyze)

    assert _submit(snapshot_id="s_bad") is True
    assert _submit(snapshot_id="s_ok") is True
    assert analysis_worker.flush(5.0) is True

    stats = analysis_worker.stats()
    assert calls == ["s_bad", "s_ok"]  # 异常后仍继续处理后续任务
    assert stats["failed"] == 1
    assert stats["written"] == 1
    assert "boom" in str(stats["lastError"])


def test_disabled_env_does_not_submit(monkeypatch):
    monkeypatch.setenv(analysis_worker.ENV_ENABLED, "0")
    assert analysis_worker.analysis_enabled() is False
    assert _submit() is False
    assert analysis_worker.stats()["submitted"] == 0


def test_empty_rows_or_ids_are_not_submitted():
    assert _submit(stock_rows=[]) is False
    assert _submit(snapshot_id="") is False
    assert _submit(dataset_id="") is False
    assert analysis_worker.stats()["submitted"] == 0


def test_queue_full_drops_without_blocking(monkeypatch):
    started = []

    def slow_analyze(task):
        started.append(task["snapshotId"])
        time.sleep(0.6)
        return 1

    monkeypatch.setattr(analysis_worker, "_analyze_task", slow_analyze)

    results = [_submit(snapshot_id=f"s{i}") for i in range(analysis_worker.QUEUE_MAXSIZE + 4)]
    # 至少一次被拒（队列有界），且 submit 始终不阻塞
    assert False in results
    assert analysis_worker.stats()["dropped"] >= 1
    analysis_worker.flush(10.0)


def test_analyze_task_builds_current_frame_with_stocks(monkeypatch):
    captured = {}

    def fake_persist(repo, dataset_id, snapshot_id, snapshot_type, frame):
        captured.update(
            {
                "repo": repo,
                "dataset_id": dataset_id,
                "snapshot_id": snapshot_id,
                "snapshot_type": snapshot_type,
                "frame": frame,
            }
        )
        return 3

    monkeypatch.setattr(
        "backend.data.repositories.mongo_repository.MongoRepository",
        lambda db: ("repo", db),
    )
    monkeypatch.setattr(
        "backend.services.snapshot_analysis_service.analyze_snapshot_and_persist",
        fake_persist,
    )

    written = analysis_worker._analyze_task(
        {
            "db": "DB",
            "datasetId": "ds",
            "snapshotId": "s1",
            "snapshotType": "half_hour",
            "tradingDate": "2026-09-10",
            "slotTime": "15:30",
            "stockRows": [{"code": "600000"}, {"code": "600001"}],
        }
    )

    assert written == 3
    frame = captured["frame"]
    # current_frame 必须含 stocks 行（ranktrend_routes 读 current_frame["stocks"]）
    assert [row["code"] for row in frame["stocks"]] == ["600000", "600001"]
    assert frame["snapshotId"] == "s1"
    assert frame["tradingDate"] == "2026-09-10"
    assert frame["slotTime"] == "15:30"
    assert frame["type"] == "half_hour"
    assert captured["repo"] == ("repo", "DB")


def test_collector_service_submits_after_save_contract():
    """源码契约：service.run_once 在采集成功后提交 analyze（防回退）。

    真实链路（采集 → 落库 → 面板可见）由 api-cli.md 的上线核对口径在实跑中验证，
    此处只锁"接入点存在且不阻断"这一结构事实。
    """
    source = (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "snapshot_collector"
        / "service.py"
    ).read_text(encoding="utf-8")

    # 2026-09-10 起：service **不再直连** analyze worker —— 触发点已下移到数据层
    # `save_snapshot_ingest` 的共享 after-save 钩子（ingest 路由与 collector 路径统一）。
    assert "submit_frame_analysis(" not in source
    assert "from backend.snapshot_collector.analysis_worker import" not in source
    assert "save_snapshot_ingest" in source  # 仍走数据层保存 → 钩子在那里触发
