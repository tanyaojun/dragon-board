from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select

from backend.data.database import SessionLocal, init_db
from backend.data.models import ArchiveManifestModel, Dataset, SnapshotFrameModel, SnapshotRecordModel, SnapshotSectorRowModel, SnapshotStockRowModel


# ── Fake S3 helpers ────────────────────────────────────────────

class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket: str, Key: str) -> dict[str, object]:
        return {"Body": FakeBody(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket: str, Key: str) -> None:
        self.objects.pop((Bucket, Key), None)

    def delete_objects(self, Bucket: str, Delete: dict[str, object]) -> None:
        for obj in Delete.get("Objects") or []:
            self.objects.pop((Bucket, obj["Key"]), None)

    def list_objects_v2(self, Bucket: str, Prefix: str) -> dict[str, object]:
        matched = [{"Key": key} for (b, key) in self.objects if b == Bucket and key.startswith(Prefix)]
        return {"Contents": matched}


class FailingPutS3Client(FakeS3Client):
    """Fails on the N-th put_object call (1-indexed)."""

    def __init__(self, fail_on_call: int = 2) -> None:
        super().__init__()
        self.fail_on_call = fail_on_call
        self.put_count = 0

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:
        self.put_count += 1
        if self.put_count == self.fail_on_call:
            raise RuntimeError("simulated S3 upload failure")
        super().put_object(Bucket, Key, Body)


class FakeBody:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


# ── DB seeding helpers ─────────────────────────────────────────

def _purge_manifests(session) -> None:
    """Delete all archive manifests to avoid stale data from other test runs (shared DB)."""
    session.execute(delete(ArchiveManifestModel))
    session.commit()


def _seed_snapshot(session) -> str:
    dataset_id = "obj_ds"
    for model in (SnapshotStockRowModel, SnapshotSectorRowModel, SnapshotFrameModel, SnapshotRecordModel, Dataset):
        session.execute(delete(model).where(model.dataset_id == dataset_id) if model is not Dataset else delete(model).where(model.id == dataset_id))
    session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.dataset_id == dataset_id))
    session.commit()
    session.merge(
        Dataset(
            id=dataset_id,
            name="Object DS",
            source_type="test",
            snapshot_count=1,
            frame_count=1,
            stock_row_count=1,
            sector_row_count=1,
            start_date="2026-01-01",
            end_date="2026-01-01",
            snapshot_types_json='["half_hour"]',
        )
    )
    session.add(SnapshotRecordModel(dataset_id=dataset_id, snapshot_id="snap_obj", type="half_hour", trading_date="2026-01-01", timestamp=1))
    session.add(SnapshotFrameModel(dataset_id=dataset_id, snapshot_id="snap_obj", type="half_hour", trading_date="2026-01-01", timestamp=1, stock_row_count=1, sector_row_count=1))
    session.add(SnapshotStockRowModel(dataset_id=dataset_id, row_id="snap_obj:000001", snapshot_id="snap_obj", type="half_hour", trading_date="2026-01-01", timestamp=1, code="000001", name="平安银行", rank=1))
    session.add(SnapshotSectorRowModel(dataset_id=dataset_id, row_id="snap_obj:sector:bank", snapshot_id="snap_obj", type="half_hour", trading_date="2026-01-01", timestamp=1, entity_type="sector", entity_key="bank", entity_name="银行", rank=1))
    session.commit()
    return dataset_id


def _create_archive(session, archive_dir: Path) -> dict:
    from backend.data.archive.service import ArchiveService

    return ArchiveService(session, archive_dir=archive_dir).archive_snapshots(
        dataset_id="obj_ds",
        snapshot_type="half_hour",
        before_trading_date="2026-01-02",
        apply=True,
    )


def _patch_store(monkeypatch, client):
    import backend.data.archive.service as svc_mod

    from backend.data.archive.object_store import ObjectBackupStore

    store = ObjectBackupStore(bucket="test-bucket", prefix="quant-board", client=client)
    monkeypatch.setattr(svc_mod, "get_object_backup_store", lambda: store)
    return store


def _remove_archive_files(local_path: Path) -> None:
    for name in (
        "records.parquet",
        "frames.parquet",
        "stock_rows.parquet",
        "sector_rows.parquet",
        "manifest.json",
    ):
        path = local_path / name
        if path.is_file():
            path.unlink()


# ── Tests ──────────────────────────────────────────────────────

def test_object_store_smoke_uses_single_explicit_key(tmp_path: Path) -> None:
    from backend.data.archive.object_store import ObjectBackupStore

    client = FakeS3Client()
    store = ObjectBackupStore(bucket="bucket", prefix="quant-board", client=client)
    result = store.smoke_test()

    assert result["ok"] is True
    assert client.objects == {}


def test_object_store_push_archive_uploads_parquet_and_manifest(tmp_path: Path) -> None:
    from backend.data.archive.object_store import ObjectBackupStore

    archive_dir = tmp_path / "snapshots_ds_hh_2026-01-01"
    archive_dir.mkdir()
    (archive_dir / "manifest.json").write_text('{"schemaVersion":"archive.v1","fileHashes":{"stock_rows.parquet":"abc"}}', encoding="utf-8")
    (archive_dir / "stock_rows.parquet").write_bytes(b"parquet data")
    (archive_dir / "extra.txt").write_text("should be ignored", encoding="utf-8")

    client = FakeS3Client()
    store = ObjectBackupStore(bucket="bucket", prefix="quant-board", client=client)

    result = store.push_archive(archive_dir)

    assert result["ok"] is True
    assert result["archiveId"] == "snapshots_ds_hh_2026-01-01"
    assert len(result["files"]) == 2
    names = {f["name"] for f in result["files"]}
    assert names == {"manifest.json", "stock_rows.parquet"}
    assert ("bucket", "quant-board/snapshots_ds_hh_2026-01-01/stock_rows.parquet") in client.objects
    assert ("bucket", "quant-board/snapshots_ds_hh_2026-01-01/manifest.json") in client.objects
    assert ("bucket", "quant-board/snapshots_ds_hh_2026-01-01/extra.txt") not in client.objects


def test_object_store_push_archive_uploads_archive_index(tmp_path: Path) -> None:
    from backend.data.archive.object_store import ObjectBackupStore

    archive_dir = tmp_path / "snapshots_ds_hh_2026-01-01"
    archive_dir.mkdir()
    (archive_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (archive_dir / "stock_rows.parquet").write_bytes(b"parquet data")
    (tmp_path / "archive_index.jsonl").write_text('{"archiveId":"snapshots_ds_hh_2026-01-01"}\n', encoding="utf-8")

    client = FakeS3Client()
    store = ObjectBackupStore(bucket="bucket", prefix="quant-board", client=client)

    result = store.push_archive(archive_dir)

    assert result["ok"] is True
    assert ("bucket", "quant-board/archive_index.jsonl") in client.objects


def test_push_archive_backup_uploads_current_archive_index_entry(tmp_path: Path, monkeypatch) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    client = FakeS3Client()
    with SessionLocal() as session:
        _purge_manifests(session)
        _seed_snapshot(session)
        result = _create_archive(session, tmp_path)
        archive_id = result["archiveId"]
        _patch_store(monkeypatch, client)

        push_result = ArchiveService(session, archive_dir=tmp_path).push_archive_backup(limit=1)

        assert push_result["ok"] is True
        remote_index = client.objects.get(("test-bucket", "quant-board/archive_index.jsonl"))
        assert remote_index is not None
        assert archive_id in remote_index.decode("utf-8")


def test_object_store_pull_archive_downloads_and_verifies(tmp_path: Path) -> None:
    from backend.data.archive.object_store import ObjectBackupStore

    client = FakeS3Client()
    client.put_object("bucket", "quant-board/bt_run1/manifest.json", b'{"ok":true}')
    client.put_object("bucket", "quant-board/bt_run1/trades.parquet", b"trades data")

    store = ObjectBackupStore(bucket="bucket", prefix="quant-board", client=client)

    target = tmp_path / "bt_run1"
    result = store.pull_archive("bt_run1", target)

    assert result["ok"] is True
    assert len(result["files"]) == 2
    assert (target / "manifest.json").read_bytes() == b'{"ok":true}'
    assert (target / "trades.parquet").read_bytes() == b"trades data"


def test_object_store_pull_nonexistent_archive(tmp_path: Path) -> None:
    from backend.data.archive.object_store import ObjectBackupStore

    client = FakeS3Client()
    store = ObjectBackupStore(bucket="bucket", prefix="quant-board", client=client)

    result = store.pull_archive("nonexistent", tmp_path / "nonexistent")

    assert result["ok"] is False
    assert result["error"]["code"] == "remote_archive_not_found"


def test_object_store_delete_archive(tmp_path: Path) -> None:
    from backend.data.archive.object_store import ObjectBackupStore

    client = FakeS3Client()
    client.put_object("bucket", "quant-board/bt_del/manifest.json", b"{}")
    client.put_object("bucket", "quant-board/bt_del/trades.parquet", b"x")

    store = ObjectBackupStore(bucket="bucket", prefix="quant-board", client=client)

    result = store.delete_archive("bt_del")

    assert result["ok"] is True
    assert result["deleted"] == 2
    assert client.objects == {}


# ── New tests (gap fill) ───────────────────────────────────────

def test_push_archive_rolls_back_on_partial_upload_failure(tmp_path: Path) -> None:
    """M2: when put_object fails mid-loop, already-uploaded files are cleaned up."""
    from backend.data.archive.object_store import ObjectBackupStore

    archive_dir = tmp_path / "snapshots_test_2026-01-01"
    archive_dir.mkdir()
    (archive_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (archive_dir / "stock_rows.parquet").write_bytes(b"a")
    (archive_dir / "sector_rows.parquet").write_bytes(b"b")

    client = FailingPutS3Client(fail_on_call=2)
    store = ObjectBackupStore(bucket="bucket", prefix="quant-board", client=client)

    result = store.push_archive(archive_dir)

    assert result["ok"] is False
    assert result["error"]["code"] == "upload_failed"
    assert result["error"]["uploaded_before_failure"] == 1
    assert "simulated S3 upload failure" in result["error"]["message"]
    # The first file should have been cleaned up
    assert client.objects == {}


def test_push_archive_backup_failure_keeps_manifest_verified(tmp_path: Path, monkeypatch) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    client = FailingPutS3Client(fail_on_call=1)
    with SessionLocal() as session:
        _purge_manifests(session)
        _seed_snapshot(session)
        result = _create_archive(session, tmp_path)
        assert result["ok"] is True
        archive_id = result["archiveId"]
        _patch_store(monkeypatch, client)

        push_result = ArchiveService(session, archive_dir=tmp_path).push_archive_backup(limit=1)

        assert push_result["ok"] is False
        manifest = session.scalar(select(ArchiveManifestModel).where(ArchiveManifestModel.archive_id == archive_id))
        assert manifest is not None
        assert manifest.status == "verified"
        assert manifest.object_key is None
        assert manifest.last_error is not None


def test_pull_archive_backup_dry_run_lists_remote_keys_without_local_writes(tmp_path: Path, monkeypatch) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    client = FakeS3Client()
    with SessionLocal() as session:
        _purge_manifests(session)
        _seed_snapshot(session)
        result = _create_archive(session, tmp_path)
        archive_id = result["archiveId"]
        _patch_store(monkeypatch, client)
        pushed = ArchiveService(session, archive_dir=tmp_path).push_archive_backup(limit=1)
        assert pushed["ok"] is True

        local_path = Path(result["localPath"])
        _remove_archive_files(local_path)
        dry_run = ArchiveService(session, archive_dir=tmp_path).pull_archive_backup(archive_id, dry_run=True)

        assert dry_run["ok"] is True
        assert dry_run["dryRun"] is True
        assert dry_run["remoteKeys"]
        assert not (local_path / "manifest.json").exists()


def test_push_archive_rejects_dir_without_parquet_or_manifest(tmp_path: Path) -> None:
    """M2: empty or non-archive directories return ok=False."""
    from backend.data.archive.object_store import ObjectBackupStore

    archive_dir = tmp_path / "junk_dir"
    archive_dir.mkdir()
    (archive_dir / "notes.txt").write_text("not an archive file", encoding="utf-8")

    client = FakeS3Client()
    store = ObjectBackupStore(bucket="bucket", prefix="quant-board", client=client)

    result = store.push_archive(archive_dir)

    assert result["ok"] is False
    assert result["error"]["code"] == "no_archive_files"
    assert client.objects == {}


def test_push_archive_rejects_empty_dir(tmp_path: Path) -> None:
    """push_archive on an empty directory returns ok=False."""
    from backend.data.archive.object_store import ObjectBackupStore

    archive_dir = tmp_path / "empty_dir"
    archive_dir.mkdir()

    client = FakeS3Client()
    store = ObjectBackupStore(bucket="bucket", prefix="quant-board", client=client)

    result = store.push_archive(archive_dir)

    assert result["ok"] is False
    assert result["error"]["code"] == "no_archive_files"


def test_get_object_backup_store_returns_none_when_bucket_unset(monkeypatch) -> None:
    """Factory returns None when object_backup_bucket is empty."""
    monkeypatch.setenv("QUANT_BOARD_OBJECT_BACKUP_BUCKET", "")
    from backend.settings import get_settings
    get_settings.cache_clear()
    from backend.data.archive.object_store import get_object_backup_store

    result = get_object_backup_store()

    assert result is None


def test_pull_archive_backup_detects_sha256_mismatch(tmp_path: Path, monkeypatch) -> None:
    """L1/sha256: pull_archive_backup fails when downloaded file hash != DB record."""
    from backend.data.archive.service import ArchiveService

    init_db()
    client = FakeS3Client()

    with SessionLocal() as session:
        _purge_manifests(session)
        _seed_snapshot(session)
        result = _create_archive(session, tmp_path)
        assert result["ok"] is True
        archive_id = result["archiveId"]

        # Push to fake R2
        store = _patch_store(monkeypatch, client)
        push_result = ArchiveService(session).push_archive_backup(limit=1)
        assert push_result["pushed"] == 1
        assert push_result["ok"] is True

        # Tamper with the uploaded content so sha256 will mismatch
        original = dict(client.objects)
        client.objects.clear()
        for (b, key), _body in original.items():
            client.objects[(b, key)] = b"tampered content"

        # Delete local archive files to force pull from R2.
        local_path = Path(result["localPath"])
        _remove_archive_files(local_path)

        # Pull should detect sha256 mismatch
        pull_result = ArchiveService(session).pull_archive_backup(archive_id, apply=True)

        assert pull_result["ok"] is False
        assert pull_result["error"]["code"] == "sha256_mismatch"

        # Manifest should be marked hash_mismatch
        manifest = session.scalar(select(ArchiveManifestModel).where(ArchiveManifestModel.archive_id == archive_id))
        assert manifest is not None
        assert manifest.status == "hash_mismatch"


def test_push_pull_archive_backup_e2e(tmp_path: Path, monkeypatch) -> None:
    """E2E: archive -> push to R2 -> delete local -> pull from R2 -> verify."""
    from backend.data.archive.service import ArchiveService

    init_db()
    client = FakeS3Client()

    with SessionLocal() as session:
        _purge_manifests(session)
        _seed_snapshot(session)
        result = _create_archive(session, tmp_path)
        assert result["ok"] is True
        archive_id = result["archiveId"]
        local_path = Path(result["localPath"])
        assert local_path.exists()

        # Push to fake R2
        store = _patch_store(monkeypatch, client)
        push_result = ArchiveService(session, archive_dir=tmp_path).push_archive_backup(limit=1)
        assert push_result["pushed"] == 1
        assert push_result["ok"] is True

        # Verify DB state after push
        manifest = session.scalar(select(ArchiveManifestModel).where(ArchiveManifestModel.archive_id == archive_id))
        assert manifest is not None
        assert manifest.status == "uploaded"
        assert manifest.object_key is not None
        assert manifest.object_key.startswith("quant-board/")

        # Delete local archive files.
        _remove_archive_files(local_path)
        assert not any(path.is_file() for path in local_path.iterdir())

        # Pull from fake R2
        pull_result = ArchiveService(session, archive_dir=tmp_path).pull_archive_backup(archive_id, apply=True)

        assert pull_result["ok"] is True
        assert pull_result["dryRun"] is False
        assert len(pull_result["restored"]) >= 2

        # Verify DB state after pull
        manifest = session.scalar(select(ArchiveManifestModel).where(ArchiveManifestModel.archive_id == archive_id))
        assert manifest is not None
        assert manifest.status == "verified"
        assert manifest.last_error is None
        assert manifest.local_path == str(tmp_path / archive_id)

        # Verify local files restored
        restored_path = Path(manifest.local_path)
        assert restored_path.exists()
        restored_files = list(restored_path.iterdir())
        names = {f.name for f in restored_files}
        assert "manifest.json" in names
        assert any(name.endswith(".parquet") for name in names)

        # Verify archive_index.jsonl was appended
        index_path = tmp_path / "archive_index.jsonl"
        assert index_path.exists()
        lines = index_path.read_text(encoding="utf-8").splitlines()
        assert any(archive_id in line for line in lines)
