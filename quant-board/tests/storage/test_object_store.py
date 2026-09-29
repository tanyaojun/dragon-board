"""ObjectBackupStore（R2/S3 对象存储适配层）纯合同测试。

2026-09-29 sqlite 归档链退役：原 test_object_backup.py 中依赖 sqlite
ArchiveService 的 push/pull 编排用例随链删除，本文件保留对象存储适配层
自身的纯合同（smoke/push/pull/delete/回滚/拒绝条件）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


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
    from backend.core.settings import get_settings
    get_settings.cache_clear()
    from backend.data.archive.object_store import get_object_backup_store

    result = get_object_backup_store()

    assert result is None
