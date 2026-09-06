from __future__ import annotations

from typing import Any

from backend.services.theme.hotlist_sentiment_service import (
    HotListSentimentService,
    make_hotlist_sentiment_provider,
)


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = list(rows)

    def sort(self, spec: list[tuple[str, int]]) -> "FakeCursor":
        for key, direction in reversed(spec):
            self.rows.sort(key=lambda row: row.get(key) or 0, reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeReplaceResult:
    matched_count = 0
    modified_count = 0
    upserted_id = "dragonboard_live:half_hour:2026-06-05"


class FakeCollection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    def find(self, query: dict[str, Any] | None = None, projection: dict[str, Any] | None = None) -> FakeCursor:
        query = query or {}
        rows = [row for row in self.rows if self._matches(row, query)]
        if projection:
            projected = []
            for row in rows:
                projected.append({key: row.get(key) for key, enabled in projection.items() if enabled})
            rows = projected
        return FakeCursor(rows)

    def find_one(
        self,
        query: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        rows = list(self.find(query or {}))
        if sort:
            rows = list(FakeCursor(rows).sort(sort))
        return rows[0] if rows else None

    def replace_one(
        self,
        query: dict[str, Any],
        doc: dict[str, Any],
        upsert: bool = False,
    ) -> FakeReplaceResult:
        self.replace_calls.append((query, doc, upsert))
        self.rows = [row for row in self.rows if not self._matches(row, query)]
        self.rows.append(doc)
        return FakeReplaceResult()

    @staticmethod
    def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
        # 相对复制源（test_hotlist_sentiment_backfill.py）的扩展：支持 $ne——
        # list_slot_documents 的 EOD 双条件排除依赖该操作符（计划 B 台账 R1）
        for key, expected in query.items():
            actual = row.get(key)
            if isinstance(expected, dict) and "$in" in expected:
                if actual not in expected["$in"]:
                    return False
            elif isinstance(expected, dict) and "$ne" in expected:
                if actual == expected["$ne"]:
                    return False
            elif actual != expected:
                return False
        return True


class FakeMongoDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {
            "snapshot_frames": FakeCollection(),
            "snapshot_stock_rows": FakeCollection(),
            "hotlist_sentiment": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


def _seed(fake_db) -> None:
    coll = fake_db["hotlist_sentiment"]
    frames = fake_db["snapshot_frames"]
    for date in ("2026-06-04", "2026-06-05"):
        frames.rows.append({"datasetId": "d1", "type": "half_hour", "tradingDate": date,
                            "snapshotId": f"snap-{date}", "slotTime": "15:00", "timestamp": 1})
    for slot, stage in (("10:00", "启动"), ("11:00", "发酵")):
        coll.rows.append({"_id": f"d1:half_hour:2026-06-05:{slot}", "datasetId": "d1",
                          "snapshotType": "half_hour", "tradingDate": "2026-06-05",
                          "slotTime": slot, "stage": stage})
    coll.rows.append({"_id": "d1:half_hour:2026-06-04", "datasetId": "d1",
                      "snapshotType": "half_hour", "tradingDate": "2026-06-04",
                      "slotTime": "EOD", "stage": "退潮"})
    coll.rows.append({"_id": "d1:half_hour:2026-06-05", "datasetId": "d1",
                      "snapshotType": "half_hour", "tradingDate": "2026-06-05",
                      "slotTime": "EOD", "stage": "高潮"})  # 06-06 stale 回退的命中对象


def _make_provider(fake_db, monkeypatch):
    # 原 R2（工厂期绑定）已按 R5 修订：service 改为 provider 首调时惰性获取，
    # monkeypatch 在调用时解析，fake db 注入方式不变
    import backend.services.theme.hotlist_sentiment_service as module

    monkeypatch.setattr(
        module, "get_hotlist_sentiment_service",
        lambda database=None: HotListSentimentService(fake_db),
    )
    return make_hotlist_sentiment_provider("d1", "half_hour")


def test_asof_picks_latest_slot_not_after_frame_time(monkeypatch):
    fake_db = FakeMongoDb()
    _seed(fake_db)
    provider = _make_provider(fake_db, monkeypatch)
    doc, status = provider("2026-06-05", "10:30")
    assert status == "ok" and doc["stage"] == "启动"       # ≤10:30 的最新槽
    doc, status = provider("2026-06-05", "11:30")
    assert status == "ok" and doc["stage"] == "发酵"


def test_asof_falls_back_to_previous_day_eod_stale(monkeypatch):
    fake_db = FakeMongoDb()
    _seed(fake_db)
    provider = _make_provider(fake_db, monkeypatch)
    doc, status = provider("2026-06-05", "09:30")          # 当日无 ≤09:30 槽位 → 回退 06-04 EOD
    assert status == "stale" and doc["stage"] == "退潮"
    doc, status = provider("2026-06-06", "10:00")          # 当日完全无文档 → 回退 06-05 EOD
    assert status == "stale" and doc["stage"] == "高潮"


def test_asof_missing_when_no_data_at_all(monkeypatch):
    fake_db = FakeMongoDb()
    provider = _make_provider(fake_db, monkeypatch)
    doc, status = provider("2026-06-06", "10:00")
    assert doc is None and status == "missing"


def test_asof_slot_order_boundary_not_after(monkeypatch):
    fake_db = FakeMongoDb()
    _seed(fake_db)
    provider = _make_provider(fake_db, monkeypatch)
    doc, status = provider("2026-06-05", "11:00")          # 恰等于槽位时间 → 含该槽
    assert status == "ok" and doc["stage"] == "发酵"


def test_engine_injects_per_frame_docs(monkeypatch):
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    fake_db = FakeMongoDb()
    _seed(fake_db)
    provider = _make_provider(fake_db, monkeypatch)
    engine = RankTrendPythonEngine.__new__(RankTrendPythonEngine)  # 只测 _ensure_hotlist_sentiment
    engine._sentiment_provider = provider

    def frame(date: str, slot: str) -> dict:
        return {"tradingDate": date, "slotTime": slot}

    frames = [frame("2026-06-05", "10:30"), frame("2026-06-05", "11:30"), frame("2026-06-05", "09:30")]
    engine._ensure_hotlist_sentiment(frames, {})
    assert frames[0]["hotlistSentiment"]["stage"] == "启动" and frames[0]["hotlistSentimentStatus"] == "ok"
    assert frames[1]["hotlistSentiment"]["stage"] == "发酵" and frames[1]["hotlistSentimentStatus"] == "ok"
    assert frames[2]["hotlistSentiment"]["stage"] == "退潮" and frames[2]["hotlistSentimentStatus"] == "stale"


def test_engine_provider_exception_marks_missing():
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    engine = RankTrendPythonEngine.__new__(RankTrendPythonEngine)

    def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    engine._sentiment_provider = boom
    frames = [{"tradingDate": "2026-06-05", "slotTime": "10:30"}]
    engine._ensure_hotlist_sentiment(frames, {})
    assert frames[0]["hotlistSentiment"] is None
    assert frames[0]["hotlistSentimentStatus"] == "missing"
    assert "db down" in frames[0]["hotlistSentimentReason"]


def test_provider_factory_binds_service_lazily(monkeypatch):
    # R5（计划 B 回归修复）：工厂期不得触碰 MongoDB——compute_analyze 每个请求都会
    # 构造 engine（ranktrend_routes.compute_analyze），若工厂期即取单例，engine 构造
    # 会在 fake/降级 db 环境直接失败，违反旧合同“provider 惰性获取 service，
    # MongoDB 不可用时由 engine 内部 try/except 降级，不影响 engine 构造与回放”。
    import backend.services.theme.hotlist_sentiment_service as module

    calls = {"n": 0}

    def _lazy_service(database=None):
        calls["n"] += 1
        return HotListSentimentService(FakeMongoDb())

    monkeypatch.setattr(module, "get_hotlist_sentiment_service", _lazy_service)
    provider = make_hotlist_sentiment_provider("d1", "half_hour")
    assert calls["n"] == 0                                  # 工厂期零构造
    provider("2026-06-05", "10:30")
    assert calls["n"] == 1                                  # 首调才构造
    provider("2026-06-06", "10:00")
    assert calls["n"] == 1                                  # 闭包生命周期内复用


def test_provider_factory_survives_unavailable_service(monkeypatch):
    # 单 getter 失败时：工厂期安全，首调才抛（由 engine _ensure_hotlist_sentiment
    # try/except 转为 missing 状态，见 test_engine_provider_exception_marks_missing）
    import pytest

    import backend.services.theme.hotlist_sentiment_service as module

    def _boom(database=None):
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(module, "get_hotlist_sentiment_service", _boom)
    provider = make_hotlist_sentiment_provider("d1", "half_hour")   # 不抛
    with pytest.raises(RuntimeError, match="db unavailable"):
        provider("2026-06-05", "10:30")
