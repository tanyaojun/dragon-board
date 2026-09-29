# -*- coding: utf-8 -*-
"""snapshot_analysis 补跑编排单测（2026-09-10）。

背景：analyze 持久化只挂 ingest 路由的 BackgroundTasks，日常采集直写库 → 集合为空，
hotlist 展示状态 join 恒为 0。本测试覆盖补跑编排的选帧/组装/dry-run/失败隔离。
"""
import pytest

from backend.services import snapshot_analysis_backfill as backfill_mod
from backend.services.snapshot_analysis_backfill import (
    backfill_frames,
    build_current_frame,
    normalize_snapshot_types,
    select_recent_frames,
)


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def sort(self, spec):
        key, direction = spec[0]
        self._docs.sort(key=lambda d: str(d.get(key) or ""), reverse=direction < 0)
        return self

    def limit(self, number):
        self._docs = self._docs[:number]
        return self

    def __iter__(self):
        return iter(self._docs)

    def __len__(self):
        return len(self._docs)


class _FakeCollection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    def find(self, query=None, projection=None):
        query = query or {}
        out = []
        for doc in self._docs:
            match = True
            for key, value in query.items():
                if isinstance(value, dict) and "$in" in value:
                    if doc.get(key) not in value["$in"]:
                        match = False
                        break
                elif isinstance(value, dict) and "$gte" in value:
                    if str(doc.get(key) or "") < str(value["$gte"]):
                        match = False
                        break
                elif doc.get(key) != value:
                    match = False
                    break
            if match:
                out.append(doc)
        return _FakeCursor(out)


class _FakeDB:
    def __init__(self, collections=None):
        self._colls = dict(collections or {})

    def __getitem__(self, name):
        return self._colls.setdefault(name, _FakeCollection())


def _frame(snapshot_id, trading_date, slot_time, type_="half_hour"):
    return {
        "datasetId": "ds",
        "snapshotId": snapshot_id,
        "tradingDate": trading_date,
        "slotTime": slot_time,
        "type": type_,
    }


def test_normalize_snapshot_types_defaults_comma_and_invalid():
    assert normalize_snapshot_types(None) == ["half_hour"]
    assert normalize_snapshot_types("daily,half_hour") == ["daily", "half_hour"]
    assert normalize_snapshot_types(["half_hour", "daily"]) == ["half_hour", "daily"]
    with pytest.raises(ValueError):
        normalize_snapshot_types("minute")


def test_select_recent_frames_sorted_desc_and_limited():
    db = _FakeDB(
        {
            "snapshot_frames": _FakeCollection(
                [
                    _frame("half_hour:2026-09-09:15:30", "2026-09-09", "15:30"),
                    _frame("half_hour:2026-09-10:15:30", "2026-09-10", "15:30"),
                    _frame("half_hour:2026-09-10:15:00", "2026-09-10", "15:00"),
                    _frame("daily:2026-09-10:15:30", "2026-09-10", "15:30", type_="daily"),
                ]
            )
        }
    )
    frames = select_recent_frames(db, "ds", ["half_hour"], 2)
    assert [f["snapshotId"] for f in frames] == [
        "half_hour:2026-09-10:15:30",
        "half_hour:2026-09-10:15:00",
    ]
    # limit<=0 且未给 start_date 时不查库
    assert select_recent_frames(db, "ds", ["half_hour"], 0) == []


def test_select_recent_frames_filters_by_start_date():
    db = _FakeDB(
        {
            "snapshot_frames": _FakeCollection(
                [
                    _frame("half_hour:2026-09-08:15:30", "2026-09-08", "15:30"),
                    _frame("half_hour:2026-09-09:15:30", "2026-09-09", "15:30"),
                    _frame("half_hour:2026-09-10:15:30", "2026-09-10", "15:30"),
                ]
            )
        }
    )
    # start_date 为下界（含当日）；limit=0 表示该日期起全部
    frames = select_recent_frames(db, "ds", ["half_hour"], 0, start_date="2026-09-09")
    assert [f["tradingDate"] for f in frames] == ["2026-09-10", "2026-09-09"]

    # start_date 与 limit 组合：从该日期起的最近 N 帧
    limited = select_recent_frames(db, "ds", ["half_hour"], 1, start_date="2026-09-09")
    assert [f["snapshotId"] for f in limited] == ["half_hour:2026-09-10:15:30"]


def test_build_current_frame_attaches_stock_rows():
    db = _FakeDB(
        {
            "snapshot_stock_rows": _FakeCollection(
                [
                    {"snapshotId": "s1", "code": "600000"},
                    {"snapshotId": "s1", "code": "600001"},
                    {"snapshotId": "s2", "code": "600002"},
                ]
            )
        }
    )
    frame = build_current_frame(db, _frame("s1", "2026-09-10", "15:30"))
    assert frame["snapshotId"] == "s1"
    assert frame["tradingDate"] == "2026-09-10"
    assert [row["code"] for row in frame["stocks"]] == ["600000", "600001"]


def test_backfill_dry_run_does_not_write(monkeypatch):
    db = _FakeDB({"snapshot_stock_rows": _FakeCollection([{"snapshotId": "s1", "code": "600000"}])})
    compute_calls = []
    persist_calls = []

    monkeypatch.setattr(backfill_mod, "MongoRepository", lambda _db: object())
    monkeypatch.setattr(
        backfill_mod,
        "compute_snapshot_analysis",
        lambda repo, dataset_id, snapshot_type, frame: (
            compute_calls.append(snapshot_type)
            or [{"code": "600000", "analysis": {"observation": {"a": 1}, "displayStatus": {"label": "点火观察"}, "cycle": {"stage": "ignition"}}}]
        ),
    )
    monkeypatch.setattr(
        backfill_mod,
        "persist_snapshot_analysis",
        lambda repo, dataset_id, snapshot_id, entries: persist_calls.append(snapshot_id) or len(entries),
    )

    result = backfill_frames(db, "ds", [_frame("s1", "2026-09-10", "15:30")], apply=False)

    assert len(compute_calls) == 1
    assert persist_calls == []  # dry-run 不写库
    assert result["totalWritten"] == 0
    frame = result["frames"][0]
    assert frame["stockRows"] == 1
    assert frame["stocksWithDisplayStatus"] == 1
    assert frame["displayStatusCounts"] == {"点火观察": 1}
    assert frame["cycleStageCounts"] == {"ignition": 1}
    assert frame["applied"] is False


def test_backfill_apply_persists_and_counts(monkeypatch):
    db = _FakeDB({"snapshot_stock_rows": _FakeCollection([{"snapshotId": "s1", "code": "600000"}])})
    persist_calls = []

    monkeypatch.setattr(backfill_mod, "MongoRepository", lambda _db: object())
    monkeypatch.setattr(
        backfill_mod,
        "compute_snapshot_analysis",
        lambda repo, dataset_id, snapshot_type, frame: [
            {"code": "600000", "analysis": {"observation": {"a": 1}}},
            {"code": "600001", "analysis": {"observation": {"a": 1}}},
        ],
    )
    monkeypatch.setattr(
        backfill_mod,
        "persist_snapshot_analysis",
        lambda repo, dataset_id, snapshot_id, entries: persist_calls.append(snapshot_id) or len(entries),
    )

    result = backfill_frames(db, "ds", [_frame("s1", "2026-09-10", "15:30")], apply=True)

    assert persist_calls == ["s1"]
    assert result["totalWritten"] == 2
    assert result["frames"][0]["applied"] is True
    assert result["frames"][0]["written"] == 2


def test_backfill_empty_rows_skips_analyze(monkeypatch):
    db = _FakeDB({"snapshot_stock_rows": _FakeCollection([])})
    called = []
    monkeypatch.setattr(backfill_mod, "MongoRepository", lambda _db: object())
    monkeypatch.setattr(
        backfill_mod,
        "compute_snapshot_analysis",
        lambda *a, **k: called.append(1) or [],
    )

    result = backfill_frames(db, "ds", [_frame("s1", "2026-09-10", "15:30")], apply=True)

    assert called == []  # 无行时不进 analyze
    assert result["frames"][0]["reason"] == "empty_stock_rows"
    assert result["frames"][0]["written"] == 0


def test_backfill_single_frame_failure_does_not_block_others(monkeypatch):
    db = _FakeDB(
        {
            "snapshot_stock_rows": _FakeCollection(
                [
                    {"snapshotId": "s_bad", "code": "600000"},
                    {"snapshotId": "s_ok", "code": "600001"},
                ]
            )
        }
    )
    monkeypatch.setattr(backfill_mod, "MongoRepository", lambda _db: object())

    def fake_compute(repo, dataset_id, snapshot_type, frame):
        if frame["snapshotId"] == "s_bad":
            raise RuntimeError("boom")
        return [{"code": "600001", "analysis": {"observation": {"a": 1}}}]

    monkeypatch.setattr(backfill_mod, "compute_snapshot_analysis", fake_compute)
    monkeypatch.setattr(backfill_mod, "persist_snapshot_analysis", lambda *a, **k: 1)

    result = backfill_frames(
        db,
        "ds",
        [_frame("s_bad", "2026-09-10", "15:00"), _frame("s_ok", "2026-09-10", "15:30")],
        apply=True,
    )

    assert result["frames"][0]["written"] == 0
    assert "analyze_failed" in result["frames"][0]["reason"]
    assert result["frames"][1]["written"] == 1
    assert result["totalWritten"] == 1
