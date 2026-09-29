"""MongoDB 快照日归档到 R2 测试（mongodb 后端生产路径，2026-09-28）。

覆盖（fail-visible 原则）：
- 正常归档：四表 parquet 落盘、R2 push、manifest uploaded、Mongo 行保留不动；
- 幂等去重：manifest 已 uploaded 的日期 skip，不重复 push；
- 推送失败：manifest 留 verified + last_error，结果 ok=False（不伪造成功），
  store 恢复后重试可补上传；
- 当日无帧 / 无明细行：结构化 skip 原因，不写空归档；
- 盘后编排 run_mongodb_snapshot_archive_once：只取严格早于今日的最近交易日，
  单类型失败不阻断其它类型，整体 ok 汇总。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import delete

from backend.data.models.database import SessionLocal, init_db
from backend.data.models.models import ArchiveManifestModel


class FakeCursor(list):
    def sort(self, key_or_list: Any, direction: int | None = None) -> "FakeCursor":
        order = key_or_list if isinstance(key_or_list, list) else [(key_or_list, direction or 1)]
        def row_key(row: dict[str, Any]) -> list[Any]:
            values = []
            for field, _direction in order:
                value = row.get(field)
                values.append("" if value is None else str(value))
            return values
        return FakeCursor(sorted(self, key=row_key))


class FakeCollection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def find(self, spec: dict[str, Any]) -> FakeCursor:
        matched = [row for row in self.rows if _matches(row, spec)]
        return FakeCursor(matched)

    def find_one(self, spec: dict[str, Any], *, sort: list[Any] | None = None, projection: dict[str, Any] | None = None) -> dict[str, Any] | None:
        matched = [row for row in self.rows if _matches(row, spec)]
        if not matched:
            return None
        if sort:
            for field, direction in reversed(sort):
                matched.sort(key=lambda row: str(row.get(field) or ""), reverse=direction < 0)
        row = dict(matched[0])
        if projection:
            keep = {k for k in projection if k != "_id"}
            row = {k: v for k, v in row.items() if k in keep}
        return row


def _matches(row: dict[str, Any], spec: dict[str, Any]) -> bool:
    for key, expected in spec.items():
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$lt" in expected and not (actual is not None and str(actual) < str(expected["$lt"])):
                return False
            if "$gte" in expected and not (actual is not None and str(actual) >= str(expected["$gte"])):
                return False
            if "$lte" in expected and not (actual is not None and str(actual) <= str(expected["$lte"])):
                return False
        elif actual != expected:
            return False
    return True


class FakeMongoDb:
    def __init__(self) -> None:
        self.collections: dict[str, list[dict[str, Any]]] = {
            name: [] for name in (
                "snapshot_records",
                "snapshot_frames",
                "snapshot_stock_rows",
                "snapshot_sector_rows",
            )
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return FakeCollection(self.collections[name])

    def seed_day(self, dataset_id: str, snapshot_type: str, trading_date: str, *, frames: int = 2, stocks: int = 3, sectors: int = 1) -> None:
        for index in range(frames):
            slot = f"10:{index:02d}"
            snapshot_id = f"{snapshot_type}:{trading_date}:{slot}"
            for collection, payload in (
                ("snapshot_frames", {"sectorRowCount": sectors}),
                ("snapshot_records", {}),
            ):
                self.collections[collection].append(
                    {
                        "_id": f"oid-{collection}-{snapshot_id}",
                        "datasetId": dataset_id,
                        "snapshotId": snapshot_id,
                        "type": snapshot_type,
                        "tradingDate": trading_date,
                        "slotTime": slot,
                        **payload,
                    }
                )
            for stock_index in range(stocks):
                self.collections["snapshot_stock_rows"].append(
                    {
                        "_id": f"oid-stock-{snapshot_id}-{stock_index}",
                        "datasetId": dataset_id,
                        "snapshotId": snapshot_id,
                        "type": snapshot_type,
                        "tradingDate": trading_date,
                        "slotTime": slot,
                        "code": f"00000{stock_index}",
                        "name": f"股票{stock_index}",
                        "themes": [{"themeId": "t1"}],
                    }
                )
            for sector_index in range(sectors):
                self.collections["snapshot_sector_rows"].append(
                    {
                        "_id": f"oid-sector-{snapshot_id}-{sector_index}",
                        "datasetId": dataset_id,
                        "snapshotId": snapshot_id,
                        "type": snapshot_type,
                        "tradingDate": trading_date,
                        "slotTime": slot,
                        "entityKey": f"theme_{sector_index}",
                    }
                )


class FakeObjectStore:
    def __init__(self, fail: bool = False) -> None:
        self.pushed: list[str] = []
        self.fail = fail

    def push_archive(self, local_dir: Path, archive_id: str | None = None, archive_index_path: Path | None = None) -> dict[str, Any]:
        if self.fail:
            return {"ok": False, "error": {"code": "upload_failed", "message": "r2 down"}}
        self.pushed.append(str(archive_id))
        return {"ok": True, "archiveId": archive_id, "files": []}

    def archive_prefix(self, archive_id: str) -> str:
        return f"quant-board/{archive_id}/"


def _cleanup_manifests(*archive_ids: str) -> None:
    with SessionLocal() as session:
        session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.archive_id.in_(archive_ids)))
        session.commit()


# ── ArchiveService.backup_mongodb_snapshot_day_to_object ────────────────────


def test_backup_day_writes_parquet_pushes_r2_and_keeps_mongo(tmp_path: Path, monkeypatch: Any) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    archive_id = "snapshot_backup_arch_ds_half_hour_2026-09-25"
    _cleanup_manifests(archive_id)
    store = FakeObjectStore()
    monkeypatch.setattr("backend.data.archive.service.get_object_backup_store", lambda: store)

    db = FakeMongoDb()
    db.seed_day("arch_ds", "half_hour", "2026-09-25", frames=2, stocks=3, sectors=1)

    with SessionLocal() as session:
        result = ArchiveService(session, archive_dir=tmp_path).backup_mongodb_snapshot_day_to_object(
            db, dataset_id="arch_ds", snapshot_type="half_hour", trading_date="2026-09-25"
        )

        assert result["ok"] is True
        assert result["rowCounts"] == {"records": 2, "frames": 2, "stockRows": 6, "sectorRows": 2}
        assert result["mongoRetained"] is True
        # Mongo 数据保留不动（只归档不删）
        assert len(db.collections["snapshot_stock_rows"]) == 6
        # R2 push 一次，manifest uploaded
        assert store.pushed == [archive_id]
        manifest = ArchiveService(session).get_manifest(archive_id)
        assert manifest is not None and manifest.status == "uploaded"
        assert manifest.object_key == f"quant-board/{archive_id}/"

    _cleanup_manifests(archive_id)


def test_backup_day_idempotent_skip_when_already_uploaded(tmp_path: Path, monkeypatch: Any) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    archive_id = "snapshot_backup_arch_ds2_five_minutes_2026-09-24"
    _cleanup_manifests(archive_id)
    store = FakeObjectStore()
    monkeypatch.setattr("backend.data.archive.service.get_object_backup_store", lambda: store)
    db = FakeMongoDb()
    db.seed_day("arch_ds2", "five_minutes", "2026-09-24", frames=1, stocks=2, sectors=0)

    with SessionLocal() as session:
        service = ArchiveService(session, archive_dir=tmp_path)
        first = service.backup_mongodb_snapshot_day_to_object(
            db, dataset_id="arch_ds2", snapshot_type="five_minutes", trading_date="2026-09-24"
        )
        assert first["ok"] is True
        second = service.backup_mongodb_snapshot_day_to_object(
            db, dataset_id="arch_ds2", snapshot_type="five_minutes", trading_date="2026-09-24"
        )
        assert second["ok"] is True
        assert second["skipped"] is True
        assert second["reason"] == "already_archived"

    assert store.pushed == [archive_id]  # 只 push 一次
    _cleanup_manifests(archive_id)


def test_backup_day_push_failure_is_visible_and_retry_succeeds(tmp_path: Path, monkeypatch: Any) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    archive_id = "snapshot_backup_arch_ds3_quarter_hour_2026-09-23"
    _cleanup_manifests(archive_id)
    store = FakeObjectStore(fail=True)
    monkeypatch.setattr("backend.data.archive.service.get_object_backup_store", lambda: store)
    db = FakeMongoDb()
    db.seed_day("arch_ds3", "quarter_hour", "2026-09-23", frames=1, stocks=1, sectors=1)

    with SessionLocal() as session:
        service = ArchiveService(session, archive_dir=tmp_path)
        failed = service.backup_mongodb_snapshot_day_to_object(
            db, dataset_id="arch_ds3", snapshot_type="quarter_hour", trading_date="2026-09-23"
        )
        assert failed["ok"] is False
        assert failed.get("error", {}).get("code") == "upload_failed"
        manifest = service.get_manifest(archive_id)
        assert manifest is not None
        assert manifest.status != "uploaded"
        assert manifest.last_error  # 失败原因落 manifest（fail-visible）

        # store 恢复后重试：同一 archive_id 补上传成功
        store.fail = False
        retried = service.backup_mongodb_snapshot_day_to_object(
            db, dataset_id="arch_ds3", snapshot_type="quarter_hour", trading_date="2026-09-23"
        )
        assert retried["ok"] is True
        assert service.get_manifest(archive_id).status == "uploaded"

    _cleanup_manifests(archive_id)


def test_backup_day_empty_and_no_frame_days_skip_honestly(tmp_path: Path, monkeypatch: Any) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    store = FakeObjectStore()
    monkeypatch.setattr("backend.data.archive.service.get_object_backup_store", lambda: store)
    db = FakeMongoDb()

    with SessionLocal() as session:
        service = ArchiveService(session, archive_dir=tmp_path)
        no_frames = service.backup_mongodb_snapshot_day_to_object(
            db, dataset_id="arch_ds4", snapshot_type="daily", trading_date="2026-09-22"
        )
        assert no_frames["ok"] is False and no_frames["reason"] == "no_snapshot_frames"

    assert store.pushed == []


# ── run_mongodb_snapshot_archive_once（盘后编排）────────────────────────────


def test_after_market_archive_picks_latest_completed_day_per_type(monkeypatch: Any, tmp_path: Path) -> None:
    from backend.operations.schedule import run_mongodb_snapshot_archive_once

    init_db()

    class _StubSettings:
        archive_auto_dataset_id = "arch_sched_ds"
        archive_auto_snapshot_types = "half_hour,five_minutes"
        archive_dir = tmp_path
        archive_parquet_compression = "zstd"

    monkeypatch.setattr("backend.operations.schedule.get_settings", lambda: _StubSettings())
    monkeypatch.setattr("backend.data.archive.service.get_settings", lambda: _StubSettings())

    db = FakeMongoDb()
    db.seed_day("arch_sched_ds", "half_hour", "2026-09-25", frames=1, stocks=2, sectors=1)
    db.seed_day("arch_sched_ds", "half_hour", "2099-01-01", frames=1, stocks=1, sectors=1)  # “今日之后”不应被选
    db.seed_day("arch_sched_ds", "five_minutes", "2026-09-24", frames=2, stocks=2, sectors=0)

    class _RepoFactory:
        @staticmethod
        def get_runtime_mongodb_database() -> FakeMongoDb:
            return db

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory",
        _RepoFactory,
    )
    store = FakeObjectStore()
    monkeypatch.setattr("backend.data.archive.service.get_object_backup_store", lambda: store)

    # 冻结“今日”为 2026-09-26：最近已收盘交易日 half_hour=09-25 / five_minutes=09-24
    class _FakeDatetime:
        def now(self, tz: Any) -> Any:
            import datetime as _dt
            return _dt.datetime(2026, 9, 26, 16, 0, tzinfo=tz)

    monkeypatch.setattr("backend.operations.schedule.datetime", _FakeDatetime())

    archive_ids = {
        "snapshot_backup_arch_sched_ds_half_hour_2026-09-25",
        "snapshot_backup_arch_sched_ds_five_minutes_2026-09-24",
    }
    _cleanup_manifests(*archive_ids)
    try:
        result = run_mongodb_snapshot_archive_once()
        assert result["ok"] is True
        assert result["snapshotTypes"]["half_hour"]["tradingDate"] == "2026-09-25"
        assert result["snapshotTypes"]["five_minutes"]["tradingDate"] == "2026-09-24"
        assert set(store.pushed) == archive_ids

        # 二次运行：全部 already_archived，无新 push
        result2 = run_mongodb_snapshot_archive_once()
        assert result2["ok"] is True
        assert result2["snapshotTypes"]["half_hour"]["reason"] == "already_archived"
        assert len(store.pushed) == 2
    finally:
        _cleanup_manifests(*archive_ids)


def test_after_market_archive_single_type_failure_does_not_block_others(monkeypatch: Any, tmp_path: Path) -> None:
    from backend.operations.schedule import run_mongodb_snapshot_archive_once

    init_db()

    class _StubSettings:
        archive_auto_dataset_id = "arch_sched_ds2"
        archive_auto_snapshot_types = "half_hour,daily"
        archive_dir = tmp_path
        archive_parquet_compression = "zstd"

    monkeypatch.setattr("backend.operations.schedule.get_settings", lambda: _StubSettings())
    monkeypatch.setattr("backend.data.archive.service.get_settings", lambda: _StubSettings())

    db = FakeMongoDb()
    db.seed_day("arch_sched_ds2", "half_hour", "2026-09-25", frames=1, stocks=2, sectors=1)
    # daily 无任何帧 → skipped（no_snapshot_frames），不算失败

    class _RepoFactory:
        @staticmethod
        def get_runtime_mongodb_database() -> FakeMongoDb:
            return db

    monkeypatch.setattr("backend.operations.schedule.repository_factory", _RepoFactory)

    class _FailStore:
        def push_archive(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"ok": False, "error": {"code": "upload_failed"}}

        def archive_prefix(self, archive_id: str) -> str:
            return f"quant-board/{archive_id}/"

    monkeypatch.setattr("backend.data.archive.service.get_object_backup_store", lambda: _FailStore())

    class _FakeDatetime:
        def now(self, tz: Any) -> Any:
            import datetime as _dt
            return _dt.datetime(2026, 9, 26, 16, 0, tzinfo=tz)

    monkeypatch.setattr("backend.operations.schedule.datetime", _FakeDatetime())

    archive_id = "snapshot_backup_arch_sched_ds2_half_hour_2026-09-25"
    _cleanup_manifests(archive_id)
    try:
        result = run_mongodb_snapshot_archive_once()
        # half_hour push 失败 → 整体 ok=False；daily 无帧 → skipped 不阻断
        assert result["ok"] is False
        assert result["snapshotTypes"]["half_hour"]["ok"] is False
        assert result["snapshotTypes"]["daily"]["skipped"] is True
    finally:
        _cleanup_manifests(archive_id)
