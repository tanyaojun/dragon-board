"""MongoDB 备份服务（mongodump 引擎，manifest schemaVersion=mongodb_backup.v2）。

2026-09-16 起备份产物从自定义 JSONL.gz 换成 mongodump 原生 bson.gz，
mongorestore 可直接恢复；v1（JSONL）历史备份仍可通过 verify 校验。

产物布局（与 mongodump --gzip 一致）：

    <backup_dir>/full/backup_id=<id>/manifest.json
    <backup_dir>/full/backup_id=<id>/sha256sums.txt
    <backup_dir>/full/backup_id=<id>/dump/<db>/<collection>.bson.gz
    <backup_dir>/full/backup_id=<id>/dump/<db>/<collection>.metadata.json

恢复路径：

    restore-mongodb-backup --backup-id <id> [--target-db <staging 库名>] [--drop]

mongodump/mongorestore 命令构造抽成纯函数（build_mongodump_args /
build_mongorestore_args）供 pytest 直接覆盖；subprocess 执行层保持薄。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlparse

from backend.core.settings import get_settings
from backend.data.archive.object_store import ObjectBackupStore


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_backup_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _endpoint_host(endpoint_url: str) -> str:
    if not endpoint_url:
        return ""
    parsed = urlparse(endpoint_url)
    return parsed.netloc or parsed.path


def _safe_relative_key(prefix: str, key: str) -> Path | None:
    if not key.startswith(prefix):
        return None
    relative = key[len(prefix) :].lstrip("/")
    if not relative:
        return None
    path = Path(relative)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        return None
    return path


# 轻量备份集合：仅当日新增的快照四表。
# 历史快照已由全量备份覆盖，回测结果可重现不需每日备份。
LIGHT_BACKUP_COLLECTIONS: tuple[str, ...] = (
    "snapshot_records",
    "snapshot_frames",
    "snapshot_stock_rows",
    "snapshot_sector_rows",
)

# 恢复默认目标库：禁止把备份恢复回正式库名本身。
DEFAULT_RESTORE_TARGET_DATABASE = "dragon_board_quant_restore_staging"

# 远端保留清理只认标准 backup_id（YYYYMMDDTHHMMSSZ），防误删其它前缀对象
_REMOTE_BACKUP_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")

CommandRunner = Callable[[list[str]], Any]


@dataclass
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def build_mongodump_args(
    *,
    mongodump_bin: Path,
    mongo_uri: str,
    database: str,
    out_dir: Path,
    collection: str | None = None,
    query: dict[str, Any] | None = None,
) -> list[str]:
    """构造 mongodump 命令。collection=None 时全库导出（full），否则单集合（light）。

    query 仅支持可 JSON 序列化的条件（mongodump 要求 strict extended JSON）。
    """
    args = [
        str(mongodump_bin),
        "--uri",
        mongo_uri,
        "--db",
        database,
        "--gzip",
    ]
    if collection:
        args.extend(["--collection", collection])
    if query is not None:
        args.extend(["--query", json.dumps(query, ensure_ascii=False, sort_keys=True)])
    args.extend(["--out", str(out_dir)])
    return args


def build_mongorestore_args(
    *,
    mongorestore_bin: Path,
    mongo_uri: str,
    dump_dir: Path,
    source_database: str,
    target_database: str,
    drop: bool = False,
) -> list[str]:
    """构造 mongorestore 命令；拒绝把备份恢复回源库本身（防误覆盖正式库）。"""
    if target_database == source_database:
        raise ValueError(
            f"拒绝恢复到源库 '{source_database}'；请恢复到 staging 库名（如 {DEFAULT_RESTORE_TARGET_DATABASE}）"
        )
    args = [
        str(mongorestore_bin),
        "--uri",
        mongo_uri,
        "--gzip",
        "--nsFrom",
        f"{source_database}.*",
        "--nsTo",
        f"{target_database}.*",
    ]
    if drop:
        args.append("--drop")
    args.append(str(dump_dir))
    return args


def _run_subprocess(cmd: list[str]) -> CommandResult:
    completed = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _coerce_command_result(value: Any) -> CommandResult:
    if isinstance(value, CommandResult):
        return value
    if isinstance(value, int):
        return CommandResult(returncode=value)
    return CommandResult(
        returncode=int(getattr(value, "returncode", -1)),
        stdout=str(getattr(value, "stdout", "") or ""),
        stderr=str(getattr(value, "stderr", "") or ""),
    )


def count_bson_gz_documents(path: Path) -> int:
    """按 BSON 文档边界（4 字节小端长度前缀）重数 gzip bson 文件中的文档数。

    mongodump 的 metadata.json 不含 count，文档数只能从产物本身解析；
    verify 阶段重数一遍可发现截断/篡改的备份文件。
    """
    count = 0
    buf = bytearray()
    with gzip.open(path, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            buf += chunk
            pos = 0
            size = len(buf)
            while size - pos >= 4:
                doc_len = int.from_bytes(buf[pos : pos + 4], "little")
                if doc_len < 5 or size - pos < doc_len:
                    break
                pos += doc_len
                count += 1
            if pos:
                del buf[:pos]
    return count


class MongoBackupService:
    def __init__(
        self,
        *,
        backup_dir: Path,
        database: str,
        mongo_uri: str,
        mongodump_bin: Path | None = None,
        mongorestore_bin: Path | None = None,
        runner: CommandRunner | None = None,
        collections: Iterable[str] = LIGHT_BACKUP_COLLECTIONS,
        object_store: Any | None = None,
        retention_days: int = 30,
        remote_backup_keep: int = 4,
    ) -> None:
        tools_bin = Path(get_settings().mongodb_tools_bin)
        self.backup_dir = Path(backup_dir)
        self.database = database
        self.mongo_uri = mongo_uri
        self.mongodump_bin = Path(mongodump_bin) if mongodump_bin else tools_bin / "mongodump.exe"
        self.mongorestore_bin = (
            Path(mongorestore_bin) if mongorestore_bin else tools_bin / "mongorestore.exe"
        )
        self.runner = runner
        self.collections = tuple(collections)
        self.object_store = object_store
        self.retention_days = max(1, int(retention_days or 30))
        self.remote_backup_keep = max(1, int(remote_backup_keep or 4))

    # ------------------------------------------------------------------ 备份

    def create_light_backup(self, *, backup_id: str | None = None) -> dict[str, Any]:
        """轻量备份：对快照四表逐集合 mongodump。"""
        return self._create_backup(
            backup_id=backup_id or _default_backup_id(),
            strategy="light_dump",
            collections=self.collections,
        )

    def create_full_backup(self, *, backup_id: str | None = None) -> dict[str, Any]:
        """全量备份：一次 mongodump 全库导出。"""
        return self._create_backup(
            backup_id=backup_id or _default_backup_id(),
            strategy="full_dump",
            collections=None,
        )

    def _create_backup(
        self,
        *,
        backup_id: str,
        strategy: str,
        collections: Iterable[str] | None,
    ) -> dict[str, Any]:
        local_dir = self.full_backup_dir(backup_id)
        if local_dir.exists():
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {"code": "backup_already_exists", "path": str(local_dir)},
            }
        if not self.mongodump_bin.is_file():
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {
                    "code": "mongodump_missing",
                    "path": str(self.mongodump_bin),
                    "hint": "安装 MongoDB Database Tools 或用 QUANT_BOARD_MONGODB_TOOLS_BIN 指定 tools/bin 目录",
                },
            }

        dump_dir = local_dir / "dump"
        dump_dir.mkdir(parents=True)
        collection_names = None if collections is None else tuple(collections)
        commands = [
            build_mongodump_args(
                mongodump_bin=self.mongodump_bin,
                mongo_uri=self.mongo_uri,
                database=self.database,
                out_dir=dump_dir,
                collection=name,
            )
            for name in (collection_names or ())
        ] or [
            build_mongodump_args(
                mongodump_bin=self.mongodump_bin,
                mongo_uri=self.mongo_uri,
                database=self.database,
                out_dir=dump_dir,
            )
        ]
        for cmd in commands:
            result = _coerce_command_result(self._run(cmd))
            if result.returncode != 0:
                _remove_tree(local_dir)
                return {
                    "ok": False,
                    "backupId": backup_id,
                    "error": {
                        "code": "mongodump_failed",
                        "returncode": result.returncode,
                        "stderr": (result.stderr or result.stdout or "").strip()[-2000:],
                    },
                }

        products = self._scan_dump_products(local_dir)
        if not products["collections"]:
            _remove_tree(local_dir)
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {
                    "code": "mongodump_no_output",
                    "path": str(dump_dir / self.database),
                },
            }

        manifest = {
            "schemaVersion": "mongodb_backup.v2",
            "engine": "mongodump",
            "backupId": backup_id,
            "database": self.database,
            "createdAt": _utc_now(),
            "gitCommit": "",
            "sourceMongoUriRedacted": "",
            "strategy": strategy,
            "objectKey": f"full/backup_id={backup_id}/",
            "objectStore": "cloudflare_r2",
            "bucket": getattr(self.object_store, "bucket", ""),
            "endpointHost": _endpoint_host(getattr(self.object_store, "endpoint_url", "")),
            "verified": False,
            "lastError": None,
            "docCounts": products["docCounts"],
            "collections": products["collections"],
        }
        self._write_manifest(local_dir, manifest)
        self._write_sha256sums(local_dir, manifest)
        return {
            "ok": True,
            "backupId": backup_id,
            "database": self.database,
            "localPath": str(local_dir),
            "manifest": manifest,
        }

    def _run(self, cmd: list[str]) -> Any:
        if self.runner is None:
            return _run_subprocess(cmd)
        return self.runner(cmd)

    def _scan_dump_products(self, local_dir: Path) -> dict[str, Any]:
        """扫描 mongodump 产物目录，解析每个 bson.gz 的文档数并计算 sha256。"""
        db_dump_dir = local_dir / "dump" / self.database
        collections: dict[str, dict[str, Any]] = {}
        doc_counts: dict[str, int] = {}
        if db_dump_dir.is_dir():
            for path in sorted(db_dump_dir.glob("*.bson.gz")):
                name = path.name[: -len(".bson.gz")]
                doc_count = count_bson_gz_documents(path)
                doc_counts[name] = doc_count
                collections[name] = {
                    "docCount": doc_count,
                    "file": path.relative_to(local_dir).as_posix(),
                    "fileHash": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
        return {"collections": collections, "docCounts": doc_counts}

    # ------------------------------------------------------------------ 校验

    def verify_backup(self, backup_id: str) -> dict[str, Any]:
        local_dir = self.full_backup_dir(backup_id)
        return self._verify_backup_dir(local_dir, backup_id=backup_id, mark_manifest=True)

    def verify_restore_staging_backup(self, backup_id: str) -> dict[str, Any]:
        staging_dir = self.backup_dir / "restore-staging" / f"backup_id={backup_id}"
        return self._verify_backup_dir(staging_dir, backup_id=backup_id, mark_manifest=False)

    def _verify_backup_dir(
        self, local_dir: Path, *, backup_id: str, mark_manifest: bool
    ) -> dict[str, Any]:
        manifest_result = self._read_manifest(local_dir)
        if not manifest_result["ok"]:
            return manifest_result
        manifest = manifest_result["manifest"]
        schema = str(manifest.get("schemaVersion") or "mongodb_backup.v1")
        # v2=bson.gz 重数文档；v1=JSONL 行数（历史备份兼容路径）
        check_product = (
            self._check_v2_bson_product
            if schema == "mongodb_backup.v2"
            else self._check_v1_jsonl_product
        )
        for collection_name, detail in (manifest.get("collections") or {}).items():
            relative = detail.get("file")
            file_path = local_dir / str(relative or "")
            if not relative or not file_path.is_file():
                return self._mark_verification_failed(
                    local_dir,
                    manifest,
                    {
                        "code": "backup_file_missing",
                        "collection": collection_name,
                        "file": str(relative or ""),
                    },
                )
            actual_hash = sha256_file(file_path)
            expected_hash = str(detail.get("fileHash") or "")
            if actual_hash != expected_hash:
                return self._mark_verification_failed(
                    local_dir,
                    manifest,
                    {
                        "code": "sha256_mismatch",
                        "collection": collection_name,
                        "file": str(relative),
                        "expected": expected_hash,
                        "actual": actual_hash,
                    },
                )
            actual_bytes = file_path.stat().st_size
            expected_bytes = int(detail.get("bytes") or 0)
            if actual_bytes != expected_bytes:
                return self._mark_verification_failed(
                    local_dir,
                    manifest,
                    {
                        "code": "byte_size_mismatch",
                        "collection": collection_name,
                        "file": str(relative),
                        "expected": expected_bytes,
                        "actual": actual_bytes,
                    },
                )
            error = check_product(
                collection_name,
                detail,
                file_path,
                mark_manifest=mark_manifest,
            )
            if error:
                return self._mark_verification_failed(local_dir, manifest, error)

        if mark_manifest:
            manifest["verified"] = True
            manifest["verifiedAt"] = _utc_now()
            manifest["lastError"] = None
            self._write_sha256sums(local_dir, manifest)
            self._write_manifest(local_dir, manifest)
        return {
            "ok": True,
            "backupId": backup_id,
            "database": manifest.get("database"),
            "verified": True,
            "checkedFiles": len(manifest.get("collections") or {}),
            "docCounts": manifest.get("docCounts") or {},
            "manifest": manifest,
        }

    def _check_v2_bson_product(
        self,
        collection_name: str,
        detail: dict[str, Any],
        file_path: Path,
        *,
        mark_manifest: bool,
    ) -> dict[str, Any] | None:
        actual = count_bson_gz_documents(file_path)
        expected = int(detail.get("docCount") or 0)
        if actual == expected:
            return None
        return {
            "code": "backup_doc_count_mismatch" if mark_manifest else "restore_doc_count_mismatch",
            "collection": collection_name,
            "file": str(detail.get("file") or ""),
            "expected": expected,
            "actual": actual,
        }

    def _check_v1_jsonl_product(
        self,
        collection_name: str,
        detail: dict[str, Any],
        file_path: Path,
        *,
        mark_manifest: bool,
    ) -> dict[str, Any] | None:
        actual_rows = _count_jsonl_rows(file_path)
        expected_rows = int(detail.get("docCount") or 0)
        if actual_rows == expected_rows:
            return None
        return {
            "code": "backup_row_count_mismatch" if mark_manifest else "restore_row_count_mismatch",
            "collection": collection_name,
            "file": str(detail.get("file") or ""),
            "expected": expected_rows,
            "actual": actual_rows,
        }

    # ------------------------------------------------------------------ R2 上传/拉回

    def push_backup(self, backup_id: str) -> dict[str, Any]:
        if self.object_store is None:
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {"code": "object_store_not_configured"},
            }
        local_dir = self.full_backup_dir(backup_id)
        manifest_result = self._read_manifest(local_dir)
        if not manifest_result["ok"]:
            return manifest_result
        manifest = manifest_result["manifest"]
        if not manifest.get("verified"):
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {"code": "backup_not_verified", "backupId": backup_id},
            }

        manifest["objectKey"] = f"full/backup_id={backup_id}/"
        manifest["objectStore"] = "cloudflare_r2"
        manifest["bucket"] = getattr(self.object_store, "bucket", "")
        manifest["endpointHost"] = _endpoint_host(getattr(self.object_store, "endpoint_url", ""))
        self._write_manifest(local_dir, manifest)

        uploaded: list[dict[str, Any]] = []
        try:
            for file_path in self._backup_files(local_dir):
                relative = file_path.relative_to(local_dir).as_posix()
                key = self.object_store.full_key(f"full/backup_id={backup_id}/{relative}")
                body = file_path.read_bytes()
                self.object_store.client.put_object(
                    Bucket=self.object_store.bucket,
                    Key=key,
                    Body=body,
                )
                uploaded.append(
                    {
                        "name": relative,
                        "key": key,
                        "bytes": len(body),
                        "sha256": sha256_bytes(body),
                    }
                )
        except Exception as exc:
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {
                    "code": "upload_failed",
                    "message": str(exc),
                    "uploadedBeforeFailure": len(uploaded),
                },
            }
        # 上传成功即视为 push 成功；远端保留清理失败只结构化附报，不影响 push 结论
        return {
            "ok": True,
            "backupId": backup_id,
            "objectStore": "cloudflare_r2",
            "bucket": getattr(self.object_store, "bucket", ""),
            "files": uploaded,
            "remotePrune": self._prune_remote_full_backups(current_backup_id=backup_id),
        }

    def _prune_remote_full_backups(self, *, current_backup_id: str) -> dict[str, Any]:
        """远端只保留最近 remote_backup_keep 份全量（backup_id 字典序=时间序）。"""
        keep = self.remote_backup_keep
        try:
            all_ids = self._remote_full_backup_ids()
        except Exception as exc:
            return {"ok": False, "error": {"code": "list_failed", "message": str(exc)}}
        stale = [bid for bid in sorted(all_ids) if _REMOTE_BACKUP_ID_RE.match(bid)][:-keep]
        deleted_objects = 0
        try:
            for bid in stale:
                prefix = self.object_store.full_key(f"full/backup_id={bid}/")
                listed = self.object_store.client.list_objects_v2(
                    Bucket=self.object_store.bucket,
                    Prefix=prefix,
                )
                keys = [str(item.get("Key") or "") for item in listed.get("Contents") or []]
                keys = [key for key in keys if key]
                if keys:
                    self.object_store.client.delete_objects(
                        Bucket=self.object_store.bucket,
                        Delete={"Objects": [{"Key": key} for key in keys]},
                    )
                deleted_objects += len(keys)
        except Exception as exc:
            return {"ok": False, "error": {"code": "delete_failed", "message": str(exc)}}
        kept = [bid for bid in sorted(all_ids) if bid not in set(stale)]
        return {
            "ok": True,
            "keep": keep,
            "deletedBackupIds": stale,
            "deletedObjects": deleted_objects,
            "keptBackupIds": kept,
        }

    def _remote_full_backup_ids(self) -> list[str]:
        prefix = self.object_store.full_key("full/backup_id=")
        ids: set[str] = set()
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = dict(Bucket=self.object_store.bucket, Prefix=prefix)
            if token:
                kwargs["ContinuationToken"] = token
            listed = self.object_store.client.list_objects_v2(**kwargs)
            for item in listed.get("Contents") or []:
                key = str(item.get("Key") or "")
                if not key.startswith(prefix):
                    continue
                bid = key[len(prefix) :].split("/", 1)[0]
                if bid:
                    ids.add(bid)
            if not listed.get("IsTruncated"):
                break
            token = listed.get("NextContinuationToken")
        return sorted(ids)

    def pull_backup(self, backup_id: str, *, dry_run: bool = True) -> dict[str, Any]:
        if self.object_store is None:
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {"code": "object_store_not_configured"},
            }
        remote_prefix = self.object_store.full_key(f"full/backup_id={backup_id}/")
        try:
            listed = self.object_store.client.list_objects_v2(
                Bucket=self.object_store.bucket,
                Prefix=remote_prefix,
            )
        except Exception as exc:
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {"code": "list_failed", "message": str(exc)},
            }
        contents = listed.get("Contents") or []
        if not contents:
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {"code": "remote_backup_not_found", "backupId": backup_id},
            }
        files = [
            {"key": item.get("Key"), "bytes": item.get("Size", 0)}
            for item in contents
            if item.get("Key")
        ]
        result = {
            "ok": True,
            "backupId": backup_id,
            "dryRun": bool(dry_run),
            "restoreTarget": "restore-staging",
            "overwritesPrimary": False,
            "files": files,
        }
        if dry_run:
            return result

        staging_dir = self.backup_dir / "restore-staging" / f"backup_id={backup_id}"
        staging_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[dict[str, Any]] = []
        for item in contents:
            key = str(item.get("Key") or "")
            relative = _safe_relative_key(remote_prefix, key)
            if relative is None:
                return {
                    "ok": False,
                    "backupId": backup_id,
                    "error": {"code": "unsafe_object_key", "key": key},
                }
            body = self.object_store.client.get_object(
                Bucket=self.object_store.bucket,
                Key=key,
            )["Body"].read()
            target = staging_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            downloaded.append(
                {
                    "name": relative.as_posix(),
                    "key": key,
                    "bytes": len(body),
                    "sha256": sha256_bytes(body),
                }
            )
        return {**result, "files": downloaded, "restoreStagingPath": str(staging_dir)}

    # ------------------------------------------------------------------ 恢复

    def restore_backup(
        self,
        backup_id: str,
        *,
        target_database: str = DEFAULT_RESTORE_TARGET_DATABASE,
        drop: bool = False,
    ) -> dict[str, Any]:
        """mongorestore 恢复备份到目标库；拒绝目标为正式库名本身。"""
        if target_database == self.database:
            raise ValueError(
                f"拒绝恢复到正式库 '{self.database}'；请恢复到 staging 库名（如 {DEFAULT_RESTORE_TARGET_DATABASE}）"
            )
        local_dir = self.full_backup_dir(backup_id)
        manifest_result = self._read_manifest(local_dir)
        if not manifest_result["ok"]:
            return {"backupId": backup_id, **manifest_result}
        manifest = manifest_result["manifest"]
        if not manifest.get("verified"):
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {
                    "code": "backup_not_verified",
                    "hint": "先运行 verify-mongodb-backup 再恢复",
                },
            }
        if not self.mongorestore_bin.is_file():
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {
                    "code": "mongorestore_missing",
                    "path": str(self.mongorestore_bin),
                    "hint": "安装 MongoDB Database Tools 或用 QUANT_BOARD_MONGODB_TOOLS_BIN 指定 tools/bin 目录",
                },
            }
        dump_root = local_dir / "dump"
        db_dump_dir = dump_root / self.database
        if not db_dump_dir.is_dir():
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {"code": "backup_dump_dir_missing", "path": str(db_dump_dir)},
            }
        # mongorestore 目录模式的 positional 必须是 dump 根（含 <db>/ 子目录）；
        # 传 <db> 子目录本身会导致所有文件被跳过且返回 0（2026-09-16 端到端验收教训）
        cmd = build_mongorestore_args(
            mongorestore_bin=self.mongorestore_bin,
            mongo_uri=self.mongo_uri,
            dump_dir=dump_root,
            source_database=self.database,
            target_database=target_database,
            drop=drop,
        )
        result = _coerce_command_result(self._run(cmd))
        if result.returncode != 0:
            return {
                "ok": False,
                "backupId": backup_id,
                "targetDatabase": target_database,
                "error": {
                    "code": "mongorestore_failed",
                    "returncode": result.returncode,
                    "stderr": (result.stderr or result.stdout or "").strip()[-2000:],
                },
            }
        return {
            "ok": True,
            "backupId": backup_id,
            "targetDatabase": target_database,
            "drop": drop,
            "sourceDatabase": self.database,
        }

    # ------------------------------------------------------------------ 列表/清理

    def list_backups(self) -> dict[str, Any]:
        root = self.backup_dir / "full"
        backups: list[dict[str, Any]] = []
        if root.is_dir():
            for path in sorted(root.iterdir()):
                if not path.is_dir() or not path.name.startswith("backup_id="):
                    continue
                backup_id = path.name.removeprefix("backup_id=")
                manifest_result = self._read_manifest(path)
                item = {"backupId": backup_id, "localPath": str(path)}
                if manifest_result["ok"]:
                    manifest = manifest_result["manifest"]
                    item.update(
                        {
                            "database": manifest.get("database"),
                            "createdAt": manifest.get("createdAt"),
                            "schemaVersion": manifest.get("schemaVersion"),
                            "strategy": manifest.get("strategy"),
                            "verified": bool(manifest.get("verified")),
                            "docCounts": manifest.get("docCounts") or {},
                        }
                    )
                else:
                    item["error"] = manifest_result.get("error")
                backups.append(item)
        return {"ok": True, "backups": backups}

    def prune_local_backups(self, *, dry_run: bool = True) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        deleted: list[dict[str, Any]] = []
        kept: list[dict[str, Any]] = []
        root = self.backup_dir / "full"
        if not root.is_dir():
            return {
                "ok": True,
                "dryRun": dry_run,
                "retentionDays": self.retention_days,
                "deleted": [],
                "kept": [],
            }

        for path in sorted(root.iterdir()):
            if not path.is_dir() or not path.name.startswith("backup_id="):
                continue
            manifest_result = self._read_manifest(path)
            created_at = None
            if manifest_result["ok"]:
                created_at = _parse_backup_time(manifest_result["manifest"].get("createdAt"))
            age_days = (now - created_at).days if created_at else None
            item = {
                "backupId": path.name.removeprefix("backup_id="),
                "localPath": str(path),
                "ageDays": age_days,
            }
            if age_days is not None and age_days > self.retention_days:
                deleted.append(item)
                if not dry_run:
                    _remove_tree(path)
            else:
                kept.append(item)
        return {
            "ok": True,
            "dryRun": dry_run,
            "retentionDays": self.retention_days,
            "deleted": deleted,
            "kept": kept,
        }

    def full_backup_dir(self, backup_id: str) -> Path:
        return self.backup_dir / "full" / f"backup_id={backup_id}"

    def _backup_files(self, local_dir: Path) -> list[Path]:
        """上传清单：manifest + sha256sums + dump 下全部产物（bson.gz 与 metadata.json）。"""
        files = [
            local_dir / "manifest.json",
            local_dir / "sha256sums.txt",
        ]
        dump_dir = local_dir / "dump"
        if dump_dir.is_dir():
            files.extend(path for path in sorted(dump_dir.rglob("*")) if path.is_file())
        return [path for path in files if path.is_file()]

    def _read_manifest(self, local_dir: Path) -> dict[str, Any]:
        manifest_path = local_dir / "manifest.json"
        if not manifest_path.is_file():
            return {
                "ok": False,
                "error": {"code": "manifest_missing", "path": str(manifest_path)},
            }
        try:
            return {
                "ok": True,
                "manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
            }
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "error": {"code": "manifest_invalid_json", "message": str(exc)},
            }

    def _write_manifest(self, local_dir: Path, manifest: dict[str, Any]) -> None:
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _write_sha256sums(self, local_dir: Path, manifest: dict[str, Any]) -> None:
        lines = []
        for detail in (manifest.get("collections") or {}).values():
            relative = str(detail.get("file") or "")
            if relative:
                lines.append(f"{detail.get('fileHash')}  {relative}")
        (local_dir / "sha256sums.txt").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )

    def _mark_verification_failed(
        self,
        local_dir: Path,
        manifest: dict[str, Any],
        error: dict[str, Any],
    ) -> dict[str, Any]:
        manifest["verified"] = False
        manifest["lastError"] = error
        self._write_manifest(local_dir, manifest)
        return {
            "ok": False,
            "backupId": manifest.get("backupId"),
            "verified": False,
            "error": error,
        }


def get_mongodb_object_backup_store() -> ObjectBackupStore | None:
    bucket = os.environ.get("QUANT_BOARD_MONGODB_OBJECT_BACKUP_BUCKET", "")
    if not bucket:
        return None
    prefix = os.environ.get(
        "QUANT_BOARD_MONGODB_OBJECT_BACKUP_PREFIX",
        "quant-board/mongodb-backups",
    )
    return ObjectBackupStore(
        bucket=bucket,
        prefix=prefix,
        endpoint_url=os.environ.get("QUANT_BOARD_MONGODB_OBJECT_BACKUP_ENDPOINT_URL", ""),
        access_key_id=os.environ.get("QUANT_BOARD_MONGODB_OBJECT_BACKUP_ACCESS_KEY_ID", ""),
        secret_access_key=os.environ.get("QUANT_BOARD_MONGODB_OBJECT_BACKUP_SECRET_ACCESS_KEY", ""),
        region=os.environ.get("QUANT_BOARD_MONGODB_OBJECT_BACKUP_REGION", "auto"),
    )


def get_mongodb_backup_service(*, object_store: Any | None = None) -> MongoBackupService:
    settings = get_settings()
    return MongoBackupService(
        backup_dir=settings.mongodb_backup_dir,
        database=settings.mongodb_database,
        mongo_uri=settings.mongodb_uri,
        object_store=object_store if object_store is not None else get_mongodb_object_backup_store(),
        retention_days=settings.mongodb_backup_retention_days,
        remote_backup_keep=settings.mongodb_remote_backup_keep,
    )


def _parse_backup_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _remove_tree(path: Path) -> None:
    for child in sorted(path.iterdir(), key=lambda item: len(item.parts), reverse=True):
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink()
    path.rmdir()


def _open_backup_file(path: Path):
    """打开备份文件，自动处理 gzip 压缩（v1 JSONL 兼容路径）。"""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _count_jsonl_rows(path: Path) -> int:
    with _open_backup_file(path) as handle:
        return sum(1 for line in handle if line.strip())
