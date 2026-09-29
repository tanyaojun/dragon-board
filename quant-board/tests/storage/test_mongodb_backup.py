from __future__ import annotations

import gzip
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from bson import encode


class FakeDumper:
    """模拟 mongodump：按命令行参数写出 bson.gz + metadata.json 产物。"""

    def __init__(self, docs: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.docs = docs or {}
        self.commands: list[list[str]] = []
        self.fail_collections: set[str] = set()

    def __call__(self, cmd: list[str]) -> int:
        self.commands.append(list(cmd))

        def opt(name: str) -> str:
            return cmd[cmd.index(name) + 1]

        out = Path(opt("--out"))
        db = opt("--db")
        if "--collection" in cmd:
            names = [opt("--collection")]
        else:
            names = sorted(self.docs)
        (out / db).mkdir(parents=True, exist_ok=True)
        for name in names:
            docs = self.docs.get(name, [])
            payload = b"".join(encode(dict(doc)) for doc in docs)
            if name in self.fail_collections:
                payload = payload[: len(payload) // 2]  # 模拟写入中断
            with gzip.open(out / db / f"{name}.bson.gz", "wb") as fh:
                fh.write(payload)
            meta = {"indexes": [], "options": {}}
            (out / db / f"{name}.metadata.json").write_text(
                json.dumps(meta), encoding="utf-8"
            )
        return 0


class FailingRunner:
    """模拟 mongodump 非零退出。"""

    def __init__(self, returncode: int = 2, stderr: str = "boom") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> Any:
        self.commands.append(list(cmd))
        return SimpleNamespace(returncode=self.returncode, stdout="", stderr=self.stderr)


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

    def delete_objects(self, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:
        deleted = []
        for obj in Delete.get("Objects", []):
            key = obj["Key"]
            if (Bucket, key) in self.objects:
                del self.objects[(Bucket, key)]
                deleted.append({"Key": key})
        return {"Deleted": deleted}


class FakeObjectStore:
    bucket = "r2-bucket"
    prefix = "quant-board/mongodb-backups"
    endpoint_url = "https://example.r2.cloudflarestorage.com"
    region = "auto"

    def __init__(self) -> None:
        self.client = FakeS3Client()

    def full_key(self, key: str) -> str:
        return f"{self.prefix}/{key.strip('/')}"


def make_service(tmp_path: Path, dumper: FakeDumper, **overrides: Any) -> Any:
    from backend.data.backup.mongodb_backup import MongoBackupService

    return MongoBackupService(
        backup_dir=tmp_path,
        database="dragon_board_quant",
        mongo_uri="mongodb://127.0.0.1:27017",
        runner=dumper,
        **overrides,
    )


def test_build_mongodump_args_full_and_light() -> None:
    from backend.data.backup.mongodb_backup import build_mongodump_args

    mongodump_bin = Path("C:/tools/mongodump.exe")
    full_cmd = build_mongodump_args(
        mongodump_bin=mongodump_bin,
        mongo_uri="mongodb://127.0.0.1:27017",
        database="dragon_board_quant",
        out_dir=Path("D:/backup/full/backup_id=x/dump"),
    )
    assert full_cmd[0] == str(mongodump_bin)
    assert "--uri" in full_cmd and "mongodb://127.0.0.1:27017" in full_cmd
    assert "--db" in full_cmd and "dragon_board_quant" in full_cmd
    assert "--gzip" in full_cmd
    assert "--collection" not in full_cmd

    light_cmd = build_mongodump_args(
        mongodump_bin=Path("C:/tools/mongodump.exe"),
        mongo_uri="mongodb://127.0.0.1:27017",
        database="dragon_board_quant",
        out_dir=Path("D:/backup/light/backup_id=x/dump"),
        collection="snapshot_stock_rows",
    )
    assert light_cmd[light_cmd.index("--collection") + 1] == "snapshot_stock_rows"
    assert "--gzip" in light_cmd


def test_build_mongorestore_args_rejects_primary_database(tmp_path: Path) -> None:
    from backend.data.backup.mongodb_backup import build_mongorestore_args

    mongorestore_bin = Path("C:/tools/mongorestore.exe")
    dump_root = tmp_path / "dump"
    cmd = build_mongorestore_args(
        mongorestore_bin=mongorestore_bin,
        mongo_uri="mongodb://127.0.0.1:27017",
        dump_dir=dump_root,
        source_database="dragon_board_quant",
        target_database="dragon_board_quant_restore_staging",
        drop=True,
    )
    assert cmd[0] == str(mongorestore_bin)
    assert "--gzip" in cmd
    assert "--nsFrom" in cmd and "dragon_board_quant.*" in cmd
    assert "--nsTo" in cmd and "dragon_board_quant_restore_staging.*" in cmd
    assert "--drop" in cmd
    # positional 必须是 mongodump 的 dump 根目录（含 <db>/ 子目录），
    # 传 <db> 子目录本身会导致 mongorestore 跳过全部文件且返回 0
    assert cmd[-1] == str(dump_root)

    import pytest

    with pytest.raises(ValueError):
        build_mongorestore_args(
            mongorestore_bin=Path("C:/tools/mongorestore.exe"),
            mongo_uri="mongodb://127.0.0.1:27017",
            dump_dir=tmp_path,
            source_database="dragon_board_quant",
            target_database="dragon_board_quant",
            drop=True,
        )


def test_full_backup_v2_writes_mongodump_layout_and_manifest(tmp_path: Path) -> None:
    dumper = FakeDumper(
        {
            "snapshot_frames": [{"snapshotId": "s1"}, {"snapshotId": "s2"}],
            "stock_names": [{"code": "000001", "name": "平安银行"}],
        }
    )
    service = make_service(tmp_path, dumper)

    result = service.create_full_backup(backup_id="20260512T150000Z")

    backup_dir = tmp_path / "full" / "backup_id=20260512T150000Z"
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["backupId"] == "20260512T150000Z"
    assert Path(result["localPath"]) == backup_dir
    assert (backup_dir / "dump" / "dragon_board_quant" / "snapshot_frames.bson.gz").is_file()
    assert (backup_dir / "dump" / "dragon_board_quant" / "stock_names.metadata.json").is_file()
    assert (backup_dir / "sha256sums.txt").is_file()
    assert manifest["schemaVersion"] == "mongodb_backup.v2"
    assert manifest["backupId"] == "20260512T150000Z"
    assert manifest["database"] == "dragon_board_quant"
    assert manifest["strategy"] == "full_dump"
    assert manifest["objectStore"] == "cloudflare_r2"
    assert manifest["verified"] is False
    # 文档数来自 bson.gz 实际解析，与 mongodump 产物一致
    assert manifest["docCounts"] == {"snapshot_frames": 2, "stock_names": 1}
    detail = manifest["collections"]["snapshot_frames"]
    assert detail["docCount"] == 2
    assert detail["file"] == "dump/dragon_board_quant/snapshot_frames.bson.gz"
    assert detail["fileHash"]
    assert detail["bytes"] > 0
    # full 是单次 mongodump 全库调用（不带 --collection）
    assert len(dumper.commands) == 1
    assert "--collection" not in dumper.commands[0]


def test_light_backup_v2_only_dumps_snapshot_collections(tmp_path: Path) -> None:
    dumper = FakeDumper(
        {
            "snapshot_records": [{"snapshotId": "r1"}],
            "snapshot_frames": [{"snapshotId": "s1"}],
            "snapshot_stock_rows": [{"rowId": "w1"}],
            "snapshot_sector_rows": [{"rowId": "z1"}],
        }
    )
    service = make_service(tmp_path, dumper)

    result = service.create_light_backup(backup_id="20260916T073000Z")

    assert result["ok"] is True
    assert result["manifest"]["schemaVersion"] == "mongodb_backup.v2"
    assert result["manifest"]["strategy"] == "light_dump"
    assert len(dumper.commands) == 4
    dumped = {cmd[cmd.index("--collection") + 1] for cmd in dumper.commands}
    assert dumped == {
        "snapshot_records",
        "snapshot_frames",
        "snapshot_stock_rows",
        "snapshot_sector_rows",
    }
    assert set(result["manifest"]["docCounts"]) == dumped


def test_backup_v2_structured_error_when_mongodump_missing(tmp_path: Path) -> None:
    service = make_service(tmp_path, FakeDumper())
    service.mongodump_bin = tmp_path / "missing" / "mongodump.exe"

    result = service.create_full_backup(backup_id="20260512T150100Z")

    assert result["ok"] is False
    assert result["error"]["code"] == "mongodump_missing"
    assert "mongodump" in str(result["error"].get("path", "")) or result["error"].get("path")
    assert not (tmp_path / "full" / "backup_id=20260512T150100Z").exists()


def test_backup_v2_structured_error_on_dump_failure(tmp_path: Path) -> None:
    dumper = FailingRunner(returncode=2, stderr="boom: connection refused")
    service = make_service(tmp_path, dumper)

    result = service.create_full_backup(backup_id="20260512T150200Z")

    assert result["ok"] is False
    assert result["error"]["code"] == "mongodump_failed"
    assert result["error"]["returncode"] == 2
    assert "connection refused" in result["error"]["stderr"]
    assert not (tmp_path / "full" / "backup_id=20260512T150200Z").exists()


def test_verify_v2_rejects_tampered_bson(tmp_path: Path) -> None:
    from backend.data.backup.mongodb_backup import sha256_file

    dumper = FakeDumper({"snapshot_frames": [{"snapshotId": "s1"}]})
    service = make_service(tmp_path, dumper)
    service.create_full_backup(backup_id="20260512T151000Z")

    # 篡改 bson.gz 内容并同步改写 manifest 的 hash/bytes，绕过 sha 校验，
    # 验证 v2 还会按 BSON 边界重数文档数
    bson_path = (
        tmp_path / "full" / "backup_id=20260512T151000Z" / "dump" / "dragon_board_quant" / "snapshot_frames.bson.gz"
    )
    with gzip.open(bson_path, "wb") as fh:
        fh.write(encode({"snapshotId": "s1"}))
        fh.write(encode({"snapshotId": "s2"}))
    manifest_path = bson_path.parents[2] / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["collections"]["snapshot_frames"]["fileHash"] = sha256_file(bson_path)
    manifest["collections"]["snapshot_frames"]["bytes"] = bson_path.stat().st_size
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = service.verify_backup("20260512T151000Z")

    assert result["ok"] is False
    assert result["error"]["code"] == "backup_doc_count_mismatch"
    assert result["error"]["expected"] == 1
    assert result["error"]["actual"] == 2


def test_verify_v1_jsonl_backup_still_supported(tmp_path: Path) -> None:
    from backend.data.backup.mongodb_backup import MongoBackupService, sha256_file

    # 手工构造 v1（JSONL）备份目录，确认旧备份仍可校验
    backup_dir = tmp_path / "full" / "backup_id=20260101T000000Z"
    (backup_dir / "dump").mkdir(parents=True)
    dump_path = backup_dir / "dump" / "snapshot_frames.jsonl.gz"
    rows = ['{"snapshotId": "s1"}\n', '{"snapshotId": "s2"}\n']
    with gzip.open(dump_path, "wt", encoding="utf-8") as fh:
        fh.writelines(rows)
    manifest = {
        "schemaVersion": "mongodb_backup.v1",
        "backupId": "20260101T000000Z",
        "database": "dragon_board_quant",
        "createdAt": "2026-01-01T00:00:00Z",
        "strategy": "full_dump",
        "verified": False,
        "docCounts": {"snapshot_frames": 2},
        "collections": {
            "snapshot_frames": {
                "docCount": 2,
                "file": "dump/snapshot_frames.jsonl.gz",
                "fileHash": sha256_file(dump_path),
                "bytes": dump_path.stat().st_size,
            }
        },
    }
    (backup_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    service = MongoBackupService(
        backup_dir=tmp_path,
        database="dragon_board_quant",
        mongo_uri="mongodb://127.0.0.1:27017",
        runner=FakeDumper(),
    )
    result = service.verify_backup("20260101T000000Z")

    assert result["ok"] is True
    assert result["verified"] is True
    updated = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    assert updated["verified"] is True


def test_push_mongodb_backup_rejects_unverified_and_uploads_verified_backup(tmp_path: Path) -> None:
    dumper = FakeDumper({"snapshot_frames": [{"snapshotId": "s1"}]})
    store = FakeObjectStore()
    service = make_service(tmp_path, dumper, object_store=store)
    service.create_full_backup(backup_id="20260512T153000Z")

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
    assert (
        "quant-board/mongodb-backups/full/backup_id=20260512T153000Z/dump/dragon_board_quant/snapshot_frames.bson.gz"
        in keys
    )


def test_push_backup_prunes_remote_full_backups_beyond_keep_count(tmp_path: Path) -> None:
    dumper = FakeDumper({"snapshot_frames": [{"snapshotId": "s1"}]})
    store = FakeObjectStore()
    service = make_service(tmp_path, dumper, object_store=store, remote_backup_keep=2)
    # 预置 3 个远端旧全量（backup_id 字典序=时间序）
    for bid in ("20260501T000000Z", "20260502T000000Z", "20260503T000000Z"):
        store.client.put_object(
            Bucket=store.bucket,
            Key=store.full_key(f"full/backup_id={bid}/manifest.json"),
            Body=b"{}",
        )

    service.create_full_backup(backup_id="20260504T000000Z")
    service.verify_backup("20260504T000000Z")
    pushed = service.push_backup("20260504T000000Z")

    assert pushed["ok"] is True
    prune = pushed["remotePrune"]
    assert prune["ok"] is True
    assert prune["deletedBackupIds"] == ["20260501T000000Z", "20260502T000000Z"]
    remaining = sorted(
        {key.split("backup_id=")[1].split("/")[0] for (_b, key) in store.client.objects}
    )
    assert remaining == ["20260503T000000Z", "20260504T000000Z"]


def test_push_backup_reports_prune_failure_without_failing_push(tmp_path: Path) -> None:
    from backend.data.backup.mongodb_backup import MongoBackupService  # noqa: F401

    dumper = FakeDumper({"snapshot_frames": [{"snapshotId": "s1"}]})
    store = FakeObjectStore()
    original_list = store.client.list_objects_v2

    def failing_list(*, Bucket: str, Prefix: str) -> dict[str, Any]:
        if Prefix.startswith(store.full_key("full/backup_id=")):
            raise RuntimeError("r2 unreachable")
        return original_list(Bucket=Bucket, Prefix=Prefix)

    store.client.list_objects_v2 = failing_list  # type: ignore[method-assign]
    service = make_service(tmp_path, dumper, object_store=store, remote_backup_keep=4)
    service.create_full_backup(backup_id="20260512T160000Z")
    service.verify_backup("20260512T160000Z")

    pushed = service.push_backup("20260512T160000Z")

    # 上传成功即 push 成功；远端清理失败只结构化报告
    assert pushed["ok"] is True
    assert pushed["remotePrune"]["ok"] is False
    assert pushed["remotePrune"]["error"]["code"] == "list_failed"


def test_pull_mongodb_backup_uses_restore_staging_and_dry_run_writes_nothing(tmp_path: Path) -> None:
    store = FakeObjectStore()
    source = make_service(tmp_path / "source", FakeDumper({"snapshot_frames": [{"snapshotId": "s1"}]}), object_store=store)
    source.create_full_backup(backup_id="20260512T154000Z")
    source.verify_backup("20260512T154000Z")
    source.push_backup("20260512T154000Z")

    target = make_service(tmp_path / "target", FakeDumper(), object_store=store)
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
    assert (staging_dir / "dump" / "dragon_board_quant" / "snapshot_frames.bson.gz").is_file()
    assert not (tmp_path / "target" / "full" / "backup_id=20260512T154000Z").exists()

    verified = target.verify_restore_staging_backup("20260512T154000Z")
    assert verified["ok"] is True
    assert verified["backupId"] == "20260512T154000Z"
    assert verified["checkedFiles"] == 1
    assert verified["docCounts"] == {"snapshot_frames": 1}


def test_restore_backup_runs_mongorestore_and_rejects_primary_target(tmp_path: Path) -> None:
    dumper = FakeDumper({"snapshot_frames": [{"snapshotId": "s1"}]})
    service = make_service(tmp_path, dumper)
    service.create_full_backup(backup_id="20260512T155000Z")
    service.verify_backup("20260512T155000Z")

    restore_calls: list[list[str]] = []

    def fake_restore_runner(cmd: list[str]) -> int:
        restore_calls.append(list(cmd))
        return 0

    service.runner = fake_restore_runner
    result = service.restore_backup(
        "20260512T155000Z",
        target_database="dragon_board_quant_restore_staging",
        drop=True,
    )

    assert result["ok"] is True
    assert len(restore_calls) == 1
    assert "--nsTo" in restore_calls[0]
    assert "dragon_board_quant_restore_staging.*" in restore_calls[0]
    assert "--drop" in restore_calls[0]
    # positional 必须是 dump 根目录（mongorestore 目录模式语义），不是 <db> 子目录
    assert restore_calls[0][-1] == str(tmp_path / "full" / "backup_id=20260512T155000Z" / "dump")

    import pytest

    with pytest.raises(ValueError):
        service.restore_backup("20260512T155000Z", target_database="dragon_board_quant")


def test_prune_mongodb_local_backups_deletes_only_expired_backup_dirs(tmp_path: Path) -> None:
    service = make_service(tmp_path, FakeDumper({"snapshot_frames": [{"snapshotId": "old"}]}), retention_days=1)
    old = service.create_full_backup(backup_id="20260510T000000Z")
    service.create_full_backup(backup_id="20260512T154500Z")
    old_manifest = Path(old["localPath"]) / "manifest.json"
    fresh_manifest = tmp_path / "full" / "backup_id=20260512T154500Z" / "manifest.json"
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
    assert (tmp_path / "full" / "backup_id=20260512T154500Z").exists()


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
    assert (
        parser.parse_args(["verify-mongodb-restore-staging", "--backup-id", "b1"]).func.__name__
        == "cmd_verify_mongodb_restore_staging"
    )
    assert parser.parse_args(["list-mongodb-backups"]).func.__name__ == "cmd_list_mongodb_backups"
    assert parser.parse_args(["prune-mongodb-backups", "--dry-run"]).func.__name__ == "cmd_prune_mongodb_backups"

    restore_args = parser.parse_args(
        ["restore-mongodb-backup", "--backup-id", "b1", "--target-db", "staging_db", "--drop"]
    )
    assert restore_args.func.__name__ == "cmd_restore_mongodb_backup"
    assert restore_args.target_db == "staging_db"
    assert restore_args.drop is True
