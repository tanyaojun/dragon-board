from __future__ import annotations

from pathlib import Path


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


class FakeBody:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


def test_object_store_smoke_uses_single_explicit_key(tmp_path: Path) -> None:
    from backend.data.archive.object_store import ObjectBackupStore

    client = FakeS3Client()
    store = ObjectBackupStore(
        bucket="bucket",
        prefix="quant-board",
        client=client,
    )

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
