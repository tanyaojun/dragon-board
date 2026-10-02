# -*- coding: utf-8 -*-
"""采集主链同步后处理（2026-09-15 重构）：落帧 → analyze 落库 → 槽位情绪 → 当日 EOD。

背景（根因，用户裁决）：analyze 产物落库此前挂在写路径之外（先是只挂 ingest 路由、
2026-09-10 起为数据层钩子 + 后台 worker 异步），与 collector 落帧之间存在时序空窗 →
槽位情绪 join 恒 miss（fallback 长期化）、盘中 EOD 首算落在空窗内则全天固化坏口径。
重构后 analyze 是采集主链自身的原子步骤：每步失败只记 warning（fail-visible），
绝不阻断采集与后续步骤。
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.hotlist.test_hotlist_sentiment_backfill import FakeCollection, FakeMongoDb


class FakeRepo:
    """save_snapshot_ingest 把帧/行写进 .db（模拟 Mongo 真实落库），供后处理链取数。"""

    def __init__(self) -> None:
        self.db = FakeMongoDb()
        self.runs: list[dict[str, Any]] = []

    def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
        return False

    def save_snapshot_ingest(self, dataset_dict, records, frames, stock_rows, sector_rows, **kwargs):
        # 真实 save_snapshot_ingest 落库时会补 datasetId（bundle 帧不带），此处对齐
        dataset_id = dataset_dict.get("id") if isinstance(dataset_dict, dict) else None
        for frame in frames:
            row = dict(frame)
            row.setdefault("datasetId", dataset_id)
            self.db["snapshot_frames"].rows.append(row)
        for row in stock_rows:
            item = dict(row)
            item.setdefault("datasetId", dataset_id)
            self.db["snapshot_stock_rows"].rows.append(item)
        return {"status": "completed", "deduped": False}

    def insert_run(self, run: dict[str, Any]) -> None:
        self.runs.append(run)


def _make_service(monkeypatch, repo: FakeRepo, analyze_impl):
    from backend.data.ingest.snapshot_ingest_normalizer import normalize_snapshot_ingest
    from backend.snapshot_collector.models import MarketDataContext, SourceHealth
    from backend.snapshot_collector.service import SnapshotCollectorService

    monkeypatch.setattr(
        "backend.services.snapshot_analysis_service.analyze_snapshot_and_persist", analyze_impl
    )
    ctx = MarketDataContext(
        stocks=[
            {
                "code": "000001",
                "name": "平安银行",
                "rank": 1,
                "preClose": 10.0,
                "price": 10.5,
                "volume": 1000,
            }
        ],
        source_health=[SourceHealth(source="startup_bundle", ok=True, row_count=1)],
    )

    async def fake_collect(providers, codes, timeout_ms=None):
        return ctx

    from backend.snapshot_collector.quality_gate import QualityResult

    def ok_quality(**kwargs):
        return QualityResult(ok=True, blocking_issues=[], warnings=[], source_counts={"ok": 1, "failed": 0})

    return SnapshotCollectorService(
        repo,
        collect_fn=fake_collect,
        normalize_fn=normalize_snapshot_ingest,
        quality_fn=ok_quality,
        theme_heat_service=None,
    )


def _run_slot(service, slot_time: str = "10:00", snapshot_type: str = "half_hour"):
    from backend.snapshot_collector.models import CollectorRunRequest

    return asyncio.run(
        service.arun_once(
            CollectorRunRequest(
                dataset_id="dragonboard_live",
                snapshot_type=snapshot_type,
                trading_date="2026-09-15",
                slot_time=slot_time,
                dry_run=False,
            )
        )
    )


def _golden_analyze(repo: FakeRepo):
    """fake analyze：记录调用并把 displayStatus 产物写进 snapshot_analysis（模拟真实落库）。"""

    def impl(mock_repo, dataset_id, snapshot_id, snapshot_type, frame):
        repo.db["snapshot_analysis"].rows.append(
            {
                "datasetId": dataset_id,
                "snapshotId": snapshot_id,
                "code": "000001",
                "analysis": {"displayStatus": {"stage": "ignition", "label": "点火"}},
            }
        )
        return 1

    impl.calls = []
    return impl


def _slot_doc(db: FakeMongoDb, slot: str) -> dict[str, Any] | None:
    for row in db["hotlist_sentiment"].rows:
        if row.get("slotTime") == slot:
            return row
    return None


def test_post_persist_chain_runs_analyze_slot_sentiment_and_eod(monkeypatch):
    repo = FakeRepo()
    analyze = _golden_analyze(repo)
    service = _make_service(monkeypatch, repo, analyze)

    result = _run_slot(service)

    assert result.status == "completed"
    # 1) analyze 产物随采集主链同步落库
    assert repo.db["snapshot_analysis"].rows, "analyze 必须在采集主链内同步落库"
    assert repo.db["snapshot_analysis"].rows[0]["snapshotId"] == "half_hour:2026-09-15:10:00"
    # 2) 槽位情绪文档 join 命中（不再有异步空窗）
    slot_doc = _slot_doc(repo.db, "10:00")
    assert slot_doc is not None, "槽位情绪文档必须随采集链写入"
    source = slot_doc["metrics"]["statusSourceCounts"]
    assert source["displayStatus"] >= 1 and source["fallback"] == 0
    # 3) 当日 EOD 同步刷新为最新帧口径（读口直读，无需 lazy compute）
    eod_docs = [r for r in repo.db["hotlist_sentiment"].rows if r.get("slotTime") == "EOD"]
    assert eod_docs, "EOD 文档必须随采集链刷新"
    assert eod_docs[0]["snapshotId"] == "half_hour:2026-09-15:10:00"
    eod_source = eod_docs[0]["metrics"]["statusSourceCounts"]
    assert eod_source["displayStatus"] >= 1 and eod_source["fallback"] == 0


def test_post_persist_chain_survives_analyze_failure(monkeypatch):
    repo = FakeRepo()

    def broken_analyze(mock_repo, dataset_id, snapshot_id, snapshot_type, frame):
        raise RuntimeError("analyze boom")

    service = _make_service(monkeypatch, repo, broken_analyze)

    result = _run_slot(service)

    assert result.status == "completed", "analyze 失败不得阻断采集"
    assert repo.db["snapshot_analysis"].rows == []
    # 情绪照算：join miss → fallback 带 fail-visible warning（不伪造 golden）
    slot_doc = _slot_doc(repo.db, "10:00")
    assert slot_doc is not None
    source = slot_doc["metrics"]["statusSourceCounts"]
    assert source["displayStatus"] == 0 and source["fallback"] >= 1
    # 2026-09-24 诊断与业务提示分离：join miss 标注随 diagnostics（fail-visible），不混业务 warnings
    assert any("displayStatus" in item for item in slot_doc.get("diagnostics", []))
    assert repo.runs, "run doc 已记录"
    assert any("analysis" in w for w in (repo.runs[-1].get("warnings") or [])), (
        "analyze 失败必须进 run doc warnings（fail-visible）"
    )


def test_post_persist_chain_analyze_disabled_by_env(monkeypatch):
    monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_ANALYSIS_ENABLED", "0")
    repo = FakeRepo()
    analyze = _golden_analyze(repo)
    service = _make_service(monkeypatch, repo, analyze)

    result = _run_slot(service)

    assert result.status == "completed"
    assert repo.db["snapshot_analysis"].rows == [], "开关关闭时跳过 analyze"
    slot_doc = _slot_doc(repo.db, "10:00")
    assert slot_doc is not None, "情绪计算照常（join miss → fallback 可见）"


def test_post_persist_chain_skipped_when_deduped(monkeypatch):
    repo = FakeRepo()

    def deduped_save(dataset_dict, records, frames, stock_rows, sector_rows, **kwargs):
        return {"status": "deduped", "deduped": True}

    analyze = _golden_analyze(repo)
    service = _make_service(monkeypatch, repo, analyze)
    repo.save_snapshot_ingest = deduped_save  # type: ignore[method-assign]

    result = _run_slot(service)

    assert result.status == "deduped"
    assert repo.db["snapshot_analysis"].rows == [], "deduped 帧不重复算 analyze"
    assert repo.db["hotlist_sentiment"].rows == [], "deduped 帧不重复写情绪文档"


def test_ingest_analyze_task_groups_frames_and_swallows_failure(monkeypatch):
    """ingest 路由的 analyze 后处理（BackgroundTasks 同步执行）：逐帧分析、失败只记日志。"""
    from backend.main import _analyze_ingested_snapshots

    calls: list[tuple[str, str]] = []

    def fake_analyze(mock_repo, dataset_id, snapshot_id, snapshot_type, frame):
        calls.append((dataset_id, snapshot_id))
        if snapshot_id == "s_bad":
            raise RuntimeError("boom")
        return 1

    monkeypatch.setattr("backend.main.analyze_snapshot_and_persist", fake_analyze)
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )

    frames = [
        {"snapshotId": "s1", "type": "half_hour", "tradingDate": "2026-09-15", "slotTime": "10:00"},
        {"snapshotId": "s_bad", "type": "half_hour", "tradingDate": "2026-09-15", "slotTime": "10:30"},
        {"snapshotId": "s_no_rows", "type": "half_hour", "tradingDate": "2026-09-15", "slotTime": "11:00"},
    ]
    rows = [
        {"snapshotId": "s1", "code": "600000"},
        {"snapshotId": "s_bad", "code": "600001"},
    ]

    _analyze_ingested_snapshots("ds", frames, rows)  # 不得抛异常

    assert [sid for _, sid in calls] == ["s1", "s_bad"], "逐帧分析；无行的帧跳过；失败被吞掉"


# ── 后处理链第 4 步：jev 情绪（2026-10-02 用户裁决 V1 退役：half_hour→槽级 / daily→EOD）──


def _mock_chain_jev_v2_ok(monkeypatch):
    import backend.services.jev.jev_sentiment_compute as v2_module

    envelope = {"result": {"state": "Completed", "result": {
        "model": "jev-1.13.0",
        "answers": {
            "frame_stage": {"type": "choice", "choice": "start", "probabilities": {"start": 0.6}},
            "sequence_stage": {"type": "choice", "choice": "start", "probabilities": {"start": 0.6}},
            "temperature": {"type": "score", "score": 5, "legend": {"0": 1, "11": 1}},
            "crowding": {"type": "choice", "choice": "no_crowding",
                         "probabilities": {"no_crowding": 0.5}},
        },
        "usage": {"input_tokens": 900, "output_tokens": 100}}}, "success": True}

    def fake_call(account_id, api_token, state, questions, model="typesafe/jev", timeout=60):
        return envelope, 900

    monkeypatch.setattr(v2_module, "call_jev", fake_call)


def test_post_persist_jev_slot_written_when_enabled(monkeypatch):
    monkeypatch.setenv("JEV_CF_TOKEN", "test-token")
    _mock_chain_jev_v2_ok(monkeypatch)
    repo = FakeRepo()
    service = _make_service(monkeypatch, repo, _golden_analyze(repo))

    result = _run_slot(service)

    assert result.status == "completed"
    docs = repo.db["hotlist_jev_sentiment"].rows
    assert len(docs) == 1 and docs[0]["kind"] == "slot"
    assert docs[0]["_id"] == "dragonboard_live:half_hour:2026-09-15:10:00"
    assert docs[0]["status"] == "ok" and docs[0]["origin"] == "collector"
    assert not any("hotlist_jev" in w for w in (repo.runs[-1].get("warnings") or []))


def test_post_persist_jev_failure_only_warns(monkeypatch):
    monkeypatch.setenv("JEV_CF_TOKEN", "test-token")
    import backend.services.jev.jev_sentiment_compute as v2_module

    def broken_call(*args, **kwargs):
        raise RuntimeError("jev boom")

    monkeypatch.setattr(v2_module, "call_jev", broken_call)
    repo = FakeRepo()
    service = _make_service(monkeypatch, repo, _golden_analyze(repo))

    result = _run_slot(service)

    assert result.status == "completed", "jev v2 失败不得阻断采集"
    # 前三步产物完好
    assert _slot_doc(repo.db, "10:00") is not None
    assert any("hotlist_jev_failed" in w for w in (repo.runs[-1].get("warnings") or []))


def test_post_persist_jev_skips_five_minutes(monkeypatch):
    monkeypatch.setenv("JEV_CF_TOKEN", "test-token")
    _mock_chain_jev_v2_ok(monkeypatch)
    repo = FakeRepo()
    service = _make_service(monkeypatch, repo, _golden_analyze(repo))

    result = _run_slot(service, slot_time="09:35", snapshot_type="five_minutes")

    assert result.status == "completed"
    assert repo.db["hotlist_jev_sentiment"].rows == [], "five_minutes 不触发 jev"
