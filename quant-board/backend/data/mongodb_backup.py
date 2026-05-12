from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from backend.data.archive.object_store import ObjectBackupStore
from backend.data.mongodb_migration import ALL_COLLECTIONS
from backend.settings import get_settings


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


def _json_default(value: Any) -> str:
    return str(value)


def _stable_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    ).encode("utf-8")


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


class MongoBackupService:
    def __init__(
        self,
        *,
        backup_dir: Path,
        database: str,
        collections: Iterable[str] = ALL_COLLECTIONS,
        object_store: Any | None = None,
        retention_days: int = 30,
    ) -> None:
        self.backup_dir = Path(backup_dir)
        self.database = database
        self.collections = tuple(collections)
        self.object_store = object_store
        self.retention_days = max(1, int(retention_days or 30))

    def create_full_backup(self, db: Any, *, backup_id: str | None = None) -> dict[str, Any]:
        backup_id = backup_id or _default_backup_id()
        local_dir = self.full_backup_dir(backup_id)
        if local_dir.exists():
            return {
                "ok": False,
                "backupId": backup_id,
                "error": {"code": "backup_already_exists", "path": str(local_dir)},
            }
        dump_dir = local_dir / "dump"
        dump_dir.mkdir(parents=True)

        collections: dict[str, dict[str, Any]] = {}
        doc_counts: dict[str, int] = {}
        for name in self.collections:
            collection = db[name]
            doc_count = (
                int(collection.count_documents({}))
                if hasattr(collection, "count_documents")
                else 0
            )
            index_info = (
                collection.index_information()
                if hasattr(collection, "index_information")
                else {}
            )
            dump_path = dump_dir / f"{name}.jsonl"
            with dump_path.open("w", encoding="utf-8", newline="\n") as handle:
                cursor = collection.find({}) if hasattr(collection, "find") else []
                for document in cursor:
                    handle.write(
                        json.dumps(
                            document,
                            ensure_ascii=False,
                            sort_keys=True,
                            default=_json_default,
                        )
                    )
                    handle.write("\n")
            file_hash = sha256_file(dump_path)
            byte_size = dump_path.stat().st_size
            doc_counts[name] = doc_count
            collections[name] = {
                "docCount": doc_count,
                "indexHash": sha256_bytes(_stable_json_bytes(index_info)),
                "file": f"dump/{dump_path.name}",
                "fileHash": file_hash,
                "bytes": byte_size,
            }

        manifest = {
            "schemaVersion": "mongodb_backup.v1",
            "backupId": backup_id,
            "database": self.database,
            "createdAt": _utc_now(),
            "gitCommit": "",
            "sourceMongoUriRedacted": "",
            "strategy": "full_dump",
            "objectKey": f"full/backup_id={backup_id}/",
            "objectStore": "cloudflare_r2",
            "bucket": getattr(self.object_store, "bucket", ""),
            "endpointHost": _endpoint_host(getattr(self.object_store, "endpoint_url", "")),
            "verified": False,
            "lastError": None,
            "docCounts": doc_counts,
            "collections": collections,
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

    def verify_backup(self, backup_id: str) -> dict[str, Any]:
        local_dir = self.full_backup_dir(backup_id)
        manifest_result = self._read_manifest(local_dir)
        if not manifest_result["ok"]:
            return manifest_result
        manifest = manifest_result["manifest"]
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
            "manifest": manifest,
        }

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
        return {
            "ok": True,
            "backupId": backup_id,
            "objectStore": "cloudflare_r2",
            "bucket": getattr(self.object_store, "bucket", ""),
            "files": uploaded,
        }

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
            return {"ok": True, "dryRun": dry_run, "retentionDays": self.retention_days, "deleted": [], "kept": []}

        for path in sorted(root.iterdir()):
            if not path.is_dir() or not path.name.startswith("backup_id="):
                continue
            manifest_result = self._read_manifest(path)
            created_at = None
            if manifest_result["ok"]:
                created_at = _parse_backup_time(manifest_result["manifest"].get("createdAt"))
            age_days = (now - created_at).days if created_at else None
            item = {"backupId": path.name.removeprefix("backup_id="), "localPath": str(path), "ageDays": age_days}
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
        files = [
            local_dir / "manifest.json",
            local_dir / "sha256sums.txt",
        ]
        dump_dir = local_dir / "dump"
        if dump_dir.is_dir():
            files.extend(path for path in sorted(dump_dir.iterdir()) if path.is_file())
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
        (local_dir / "sha256sums.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

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
        object_store=object_store if object_store is not None else get_mongodb_object_backup_store(),
        retention_days=settings.mongodb_backup_retention_days,
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
