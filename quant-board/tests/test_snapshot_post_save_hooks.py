# -*- coding: utf-8 -*-
"""快照 after-save 钩子机制与默认钩子单测（2026-09-10）。

覆盖：注册/触发/异常隔离/幂等；默认钩子（缓存失效 + analyze 落库）的分组与跳过条件；
以及数据层 `save_snapshot_ingest` 三个返回点都触发钩子的源码契约。
"""
from pathlib import Path

import pytest

from backend.data.repositories import snapshot_post_save as hooks_mod
from backend.services import snapshot_post_save_hooks as default_hooks


@pytest.fixture(autouse=True)
def _isolated_hooks(monkeypatch):
    """隔离钩子注册表（**不得 clear 全局**）。

    早期版本用 `clear_snapshot_post_save_hooks()` 会把 `backend.main` / `collector_main`
    导入时注册的默认钩子清掉，污染同进程的其它测试（`test_snapshot_read_api` 的
    ingest 缓存失效断言因此失败、`test_ingest_outbox` 批跑 flaky）。
    改用 monkeypatch 替换模块级列表：仅本测试生效，退出后自动恢复原注册表。
    """
    monkeypatch.setattr(hooks_mod, "_hooks", [])


def _kwargs(**overrides):
    payload = {
        "dataset_id": "ds",
        "frames": [
            {
                "snapshotId": "s1",
                "type": "half_hour",
                "tradingDate": "2026-09-10",
                "slotTime": "15:30",
            }
        ],
        "stock_rows": [{"snapshotId": "s1", "code": "600000"}],
        "sector_rows": [],
        "records": [],
        "deduped": False,
        "source": "test",
    }
    payload.update(overrides)
    return payload


def test_registered_hook_receives_payload():
    seen = []
    hooks_mod.register_snapshot_post_save_hook(lambda **kw: seen.append(kw))

    hooks_mod.run_snapshot_post_save_hooks(**_kwargs())

    assert len(seen) == 1
    assert seen[0]["dataset_id"] == "ds"
    assert seen[0]["deduped"] is False
    assert seen[0]["source"] == "test"


def test_no_hooks_is_noop():
    hooks_mod.run_snapshot_post_save_hooks(**_kwargs())  # 不抛异常即通过


def test_hook_failure_does_not_break_others_or_propagate():
    calls = []

    def bad(**kwargs):
        calls.append("bad")
        raise RuntimeError("boom")

    def good(**kwargs):
        calls.append("good")

    hooks_mod.register_snapshot_post_save_hook(bad)
    hooks_mod.register_snapshot_post_save_hook(good)

    hooks_mod.run_snapshot_post_save_hooks(**_kwargs())

    assert calls == ["bad", "good"]  # 异常被吞、后续钩子照跑


def test_register_is_idempotent():
    def hook(**kwargs):
        return None

    hooks_mod.register_snapshot_post_save_hook(hook)
    hooks_mod.register_snapshot_post_save_hook(hook)

    assert len(hooks_mod.registered_snapshot_post_save_hooks()) == 1


def test_default_hooks_register_twice_without_duplication():
    default_hooks.register_default_snapshot_post_save_hooks()
    default_hooks.register_default_snapshot_post_save_hooks()

    assert len(hooks_mod.registered_snapshot_post_save_hooks()) == 2


def test_cache_hook_calls_snapshot_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "backend.data.cache.snapshot_cache.invalidate_snapshot_cache_after_ingest",
        lambda **kw: calls.append(kw),
    )

    default_hooks._invalidate_snapshot_cache_hook(**_kwargs())

    assert len(calls) == 1
    assert calls[0]["dataset_id"] == "ds"


def test_analysis_hook_groups_rows_by_snapshot(monkeypatch):
    submitted = []
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: "DB",
    )
    monkeypatch.setattr(
        "backend.snapshot_collector.analysis_worker.analysis_enabled", lambda: True
    )
    monkeypatch.setattr(
        "backend.snapshot_collector.analysis_worker.submit_frame_analysis",
        lambda **kw: submitted.append(kw) or True,
    )

    default_hooks._persist_snapshot_analysis_hook(
        **_kwargs(
            frames=[
                {
                    "snapshotId": "s1",
                    "type": "half_hour",
                    "tradingDate": "2026-09-10",
                    "slotTime": "15:30",
                },
                {
                    "snapshotId": "s2",
                    "type": "half_hour",
                    "tradingDate": "2026-09-10",
                    "slotTime": "15:00",
                },
            ],
            stock_rows=[
                {"snapshotId": "s1", "code": "600000"},
                {"snapshotId": "s2", "code": "600001"},
            ],
        )
    )

    assert [item["snapshot_id"] for item in submitted] == ["s1", "s2"]
    assert submitted[0]["stock_rows"] == [{"snapshotId": "s1", "code": "600000"}]
    assert submitted[1]["stock_rows"] == [{"snapshotId": "s2", "code": "600001"}]
    assert submitted[0]["db"] == "DB"
    assert submitted[0]["snapshot_type"] == "half_hour"


def test_analysis_hook_skips_deduped_and_disabled(monkeypatch):
    submitted = []
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: "DB",
    )
    monkeypatch.setattr(
        "backend.snapshot_collector.analysis_worker.analysis_enabled", lambda: True
    )
    monkeypatch.setattr(
        "backend.snapshot_collector.analysis_worker.submit_frame_analysis",
        lambda **kw: submitted.append(kw) or True,
    )

    # deduped 帧不重复算
    default_hooks._persist_snapshot_analysis_hook(**_kwargs(deduped=True))
    assert submitted == []

    # 开关关闭时不提交
    monkeypatch.setattr(
        "backend.snapshot_collector.analysis_worker.analysis_enabled", lambda: False
    )
    default_hooks._persist_snapshot_analysis_hook(**_kwargs())
    assert submitted == []


def test_repositories_trigger_hooks_contract():
    """源码契约：**两个** `save_snapshot_ingest` 实现（MongoDB / SQLite）的返回点都触发钩子。

    新增/删除触发点、或新增第三种 repo 实现时，必须同步更新本断言（有意的"改动提示"，
    防止后处理被静默绕过 —— 2026-09-10 就因只挂 MongoDB 实现而漏掉 SQLite 路径，
    被 `test_snapshot_read_api` 的缓存失效断言抓到）。
    """
    repositories = Path(__file__).resolve().parent.parent / "backend" / "data" / "repositories"
    mongo_source = (repositories / "mongo_repository.py").read_text(encoding="utf-8")
    sqlite_source = (repositories / "snapshot_repository.py").read_text(encoding="utf-8")

    assert mongo_source.count("run_snapshot_post_save_hooks(") == 3
    assert sqlite_source.count("run_snapshot_post_save_hooks(") == 3
