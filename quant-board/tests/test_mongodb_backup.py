from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FakeCollection:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        indexes: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.rows = rows or []
        self.indexes = indexes or {"_id_": {"key": [("_id", 1)]}}

    def count_documents(self, _filter: dict[str, Any]) -> int:
        return len(self.rows)

    def find(self, _filter: dict[str, Any]) -> list[dict[str, Any]]:
        return list(self.rows)

    def index_information(self) -> dict[str, dict[str, Any]]:
        return self.indexes


class FakeMongoDatabase(dict[str, FakeCollection]):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


class FakeBody:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return self.payload


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": FakeBody(self.objects[(Bucket, Key)])}

    def list_objects_v2(self, Bucket: str, Prefix: str) -> dict[str, Any]:
        return {
            "Contents": [
                {"Key": key, "Size": len(body)}
                for (bucket, key), body in sorted(self.objects.items())
                if bucket == Bucket and key.startswith(Prefix)
            ]
        }


class FakeObjectStore:
    bucket = "r2-bucket"
    prefix = "quant-board/mongodb-backups"
    endpoint_url = "https://example.r2.cloudflarestorage.com"
    region = "auto"

    def __init__(self) -> None:
        self.client = FakeS3Client()

    def full_key(self, key: str) -> str:
        return f"{self.prefix}/{key.strip('/')}"


def test_full_backup_writes_manifest_and_local_dump_structure(tmp_path: Path) -> None:
    from backend.data.mongodb_backup import MongoBackupService

    db = FakeMongoDatabase(
        {
            "snapshot_frames": FakeCollection(
                [{"snapshotId": "s1"}, {"snapshotId": "s2"}],
                indexes={"dataset_snapshot": {"key": [("datasetId", 1), ("snapshotId", 1)], "unique": True}},
            ),
            "stock_names": FakeCollection([{"code": "000001", "name": "平安银行"}]),
        }
    )
    service = MongoBackupService(
        backup_dir=tmp_path,
        database="dragon_board_quant",
        collections=("snapshot_frames", "stock_names"),
    )

    result = service.create_full_backup(db, backup_id="20260512T150000Z")

    backup_dir = tmp_path / "full" / "backup_id=20260512T150000Z"
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["backupId"] == "20260512T150000Z"
    assert Path(result["localPath"]) == backup_dir
    assert (backup_dir / "dump" / "snapshot_frames.jsonl").is_file()
    assert (backup_dir / "dump" / "stock_names.jsonl").is_file()
    assert (backup_dir / "sha256sums.txt").is_file()
    assert manifest["backupId"] == "20260512T150000Z"
    assert manifest["database"] == "dragon_board_quant"
    assert manifest["createdAt"]
    assert manifest["objectStore"] == "cloudflare_r2"
    assert manifest["verified"] is False
    assert manifest["docCounts"] == {"snapshot_frames": 2, "stock_names": 1}
    assert manifest["collections"]["snapshot_frames"]["docCount"] == 2
    assert manifest["collections"]["snapshot_frames"]["indexHash"]
    assert manifest["collections"]["snapshot_frames"]["fileHash"]
    assert manifest["collections"]["snapshot_frames"]["bytes"] > 0


def test_verify_mongodb_backup_marks_verified_and_writes_sha256sums(tmp_path: Path) -> None:
    from backend.data.mongodb_backup import MongoBackupService

    service = MongoBackupService(
        backup_dir=tmp_path,
        database="dragon_board_quant",
        collections=("snapshot_frames",),
    )
    service.create_full_backup(
        FakeMongoDatabase({"snapshot_frames": FakeCollection([{"snapshotId": "s1"}])}),
        backup_id="20260512T151000Z",
    )

    result = service.verify_backup("20260512T151000Z")

    manifest_path = tmp_path / "full" / "backup_id=20260512T151000Z" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sums = (manifest_path.parent / "sha256sums.txt").read_text(encoding="utf-8")
    assert result["ok"] is True
    assert result["verified"] is True
    assert manifest["verified"] is True
    assert "dump/snapshot_frames.jsonl" in sums


def test_verify_mongodb_backup_returns_structured_error_on_sha_mismatch(tmp_path: Path) -> None:
    from backend.data.mongodb_backup import MongoBackupService

    service = MongoBackupService(
        backup_dir=tmp_path,
        database="dragon_board_quant",
        collections=("snapshot_frames",),
    )
    service.create_full_backup(
        FakeMongoDatabase({"snapshot_frames": FakeCollection([{"snapshotId": "s1"}])}),
        backup_id="20260512T152000Z",
    )
    dump_file = tmp_path / "full" / "backup_id=20260512T152000Z" / "dump" / "snapshot_frames.jsonl"
    dump_file.write_text('{"tampered":true}\n', encoding="utf-8")

    result = service.verify_backup("20260512T152000Z")

    manifest = json.loads((dump_file.parents[1] / "manifest.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["error"]["code"] == "sha256_mismatch"
    assert result["error"]["file"] == "dump/snapshot_frames.jsonl"
    assert manifest["verified"] is False
    assert manifest["lastError"]["code"] == "sha256_mismatch"


def test_push_mongodb_backup_rejects_unverified_and_uploads_verified_backup(tmp_path: Path) -> None:
    from backend.data.mongodb_backup import MongoBackupService

    store = FakeObjectStore()
    service = MongoBackupService(
        backup_dir=tmp_path,
        database="dragon_board_quant",
        collections=("snapshot_frames",),
        object_store=store,
    )
    service.create_full_backup(
        FakeMongoDatabase({"snapshot_frames": FakeCollection([{"snapshotId": "s1"}])}),
        backup_id="20260512T153000Z",
    )

    rejected = service.push_backup("20260512T153000Z")
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "backup_not_verified"
    assert store.client.objects == {}

    service.verify_backup("20260512T153000Z")
    pushed = service.push_backup("20260512T153000Z")

    assert pushed["ok"] is True
    keys = {key for (_bucket, key) in store.client.objects}
    assert "quant-board/mongodb-backups/full/backup_id=20260512T153000Z/manifest.json" in keys
    assert "quant-board/mongodb-backups/full/backup_id=20260512T153000Z/sha256sums.txt" in keys
    assert "quant-board/mongodb-backups/full/backup_id=20260512T153000Z/dump/snapshot_frames.jsonl" in keys


def test_pull_mongodb_backup_uses_restore_staging_and_dry_run_writes_nothing(tmp_path: Path) -> None:
    from backend.data.mongodb_backup import MongoBackupService

    store = FakeObjectStore()
    source = MongoBackupService(
        backup_dir=tmp_path / "source",
        database="dragon_board_quant",
        collections=("snapshot_frames",),
        object_store=store,
    )
    source.create_full_backup(
        FakeMongoDatabase({"snapshot_frames": FakeCollection([{"snapshotId": "s1"}])}),
        backup_id="20260512T154000Z",
    )
    source.verify_backup("20260512T154000Z")
    source.push_backup("20260512T154000Z")

    target = MongoBackupService(
        backup_dir=tmp_path / "target",
        database="dragon_board_quant",
        collections=("snapshot_frames",),
        object_store=store,
    )
    dry_run = target.pull_backup("20260512T154000Z", dry_run=True)

    assert dry_run["ok"] is True
    assert dry_run["dryRun"] is True
    assert dry_run["restoreTarget"] == "restore-staging"
    assert dry_run["overwritesPrimary"] is False
    assert not (tmp_path / "target" / "restore-staging").exists()

    pulled = target.pull_backup("20260512T154000Z", dry_run=False)

    staging_dir = tmp_path / "target" / "restore-staging" / "backup_id=20260512T154000Z"
    assert pulled["ok"] is True
    assert Path(pulled["restoreStagingPath"]) == staging_dir
    assert (staging_dir / "manifest.json").is_file()
    assert (staging_dir / "dump" / "snapshot_frames.jsonl").is_file()
    assert not (tmp_path / "target" / "full" / "backup_id=20260512T154000Z").exists()


def test_prune_mongodb_local_backups_deletes_only_expired_backup_dirs(tmp_path: Path) -> None:
    from backend.data.mongodb_backup import MongoBackupService

    service = MongoBackupService(
        backup_dir=tmp_path,
        database="dragon_board_quant",
        collections=("snapshot_frames",),
        retention_days=1,
    )
    old = service.create_full_backup(
        FakeMongoDatabase({"snapshot_frames": FakeCollection([{"snapshotId": "old"}])}),
        backup_id="20260510T000000Z",
    )
    fresh = service.create_full_backup(
        FakeMongoDatabase({"snapshot_frames": FakeCollection([{"snapshotId": "fresh"}])}),
        backup_id="20260512T154500Z",
    )
    old_manifest = Path(old["localPath"]) / "manifest.json"
    fresh_manifest = Path(fresh["localPath"]) / "manifest.json"
    old_data = json.loads(old_manifest.read_text(encoding="utf-8"))
    fresh_data = json.loads(fresh_manifest.read_text(encoding="utf-8"))
    old_data["createdAt"] = "2000-01-01T00:00:00Z"
    fresh_data["createdAt"] = "2999-01-01T00:00:00Z"
    old_manifest.write_text(json.dumps(old_data), encoding="utf-8")
    fresh_manifest.write_text(json.dumps(fresh_data), encoding="utf-8")

    dry_run = service.prune_local_backups(dry_run=True)
    applied = service.prune_local_backups(dry_run=False)

    assert [item["backupId"] for item in dry_run["deleted"]] == ["20260510T000000Z"]
    assert [item["backupId"] for item in applied["deleted"]] == ["20260510T000000Z"]
    assert not Path(old["localPath"]).exists()
    assert Path(fresh["localPath"]).exists()


def test_mongodb_backup_cli_commands_parse() -> None:
    from backend.cli import build_parser

    parser = build_parser()

    assert parser.parse_args(["backup-mongodb", "--full"]).func.__name__ == "cmd_backup_mongodb"
    assert (
        parser.parse_args(["verify-mongodb-backup", "--backup-id", "b1"]).func.__name__
        == "cmd_verify_mongodb_backup"
    )
    assert (
        parser.parse_args(["push-mongodb-backup", "--backup-id", "b1"]).func.__name__
        == "cmd_push_mongodb_backup"
    )
    pull_args = parser.parse_args(["pull-mongodb-backup", "--backup-id", "b1", "--dry-run"])
    assert pull_args.func.__name__ == "cmd_pull_mongodb_backup"
    assert pull_args.dry_run is True
    assert parser.parse_args(["list-mongodb-backups"]).func.__name__ == "cmd_list_mongodb_backups"
    assert parser.parse_args(["prune-mongodb-backups", "--dry-run"]).func.__name__ == "cmd_prune_mongodb_backups"
