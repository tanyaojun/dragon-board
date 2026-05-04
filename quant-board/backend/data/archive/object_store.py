from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.data.archive.manifest import sha256_file
from backend.settings import get_settings


@dataclass
class ObjectBackupStore:
    bucket: str
    prefix: str = "quant-board"
    endpoint_url: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    region: str = "auto"
    client: Any | None = None

    def __post_init__(self) -> None:
        self.prefix = self.prefix.strip("/")
        if self.client is None:
            try:
                import boto3
            except ModuleNotFoundError as exc:
                raise RuntimeError("boto3 is required for object backup; run pip install -r requirements.txt") from exc
            self.client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url or None,
                aws_access_key_id=self.access_key_id or None,
                aws_secret_access_key=self.secret_access_key or None,
                region_name=self.region or "auto",
            )

    def smoke_test(self) -> dict[str, Any]:
        key = self.full_key("__smoke__/archive-smoke.json")
        body = b'{"ok":true}'
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=body)
            read_back = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return {"ok": read_back == body, "write": True, "read": read_back == body, "cleanup": True, "key": key}
        except Exception as exc:
            return {"ok": False, "write": False, "read": False, "cleanup": False, "key": key, "last_error": str(exc)}

    def full_key(self, key: str) -> str:
        key = key.strip("/")
        return f"{self.prefix}/{key}" if self.prefix else key

    def archive_prefix(self, archive_id: str) -> str:
        return self.full_key(f"{archive_id}/")

    def push_archive(self, local_dir: Path) -> dict[str, Any]:
        if not local_dir.is_dir():
            return {"ok": False, "error": {"code": "local_dir_missing", "path": str(local_dir)}}
        archive_id = local_dir.name
        prefix = f"{archive_id}/"
        uploaded: list[dict[str, Any]] = []
        try:
            for file_path in sorted(local_dir.iterdir()):
                if not file_path.is_file():
                    continue
                if file_path.suffix not in (".parquet",) and file_path.name != "manifest.json":
                    continue
                body = file_path.read_bytes()
                key = self.full_key(f"{prefix}{file_path.name}")
                self.client.put_object(Bucket=self.bucket, Key=key, Body=body)
                uploaded.append({"name": file_path.name, "key": key, "bytes": len(body), "sha256": sha256_file(file_path)})
        except Exception as exc:
            for f in uploaded:
                try:
                    self.client.delete_object(Bucket=self.bucket, Key=f["key"])
                except Exception:
                    pass
            return {"ok": False, "error": {"code": "upload_failed", "message": str(exc), "uploaded_before_failure": len(uploaded)}}
        if not uploaded:
            return {"ok": False, "error": {"code": "no_archive_files", "path": str(local_dir)}}
        return {"ok": True, "archiveId": archive_id, "files": uploaded}

    def pull_archive(self, archive_id: str, target_dir: Path) -> dict[str, Any]:
        prefix = self.archive_prefix(archive_id)
        try:
            listed = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        except Exception as exc:
            return {"ok": False, "error": {"code": "list_failed", "message": str(exc)}}
        contents = listed.get("Contents") or []
        if not contents:
            return {"ok": False, "error": {"code": "remote_archive_not_found", "archiveId": archive_id}}
        target_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[dict[str, Any]] = []
        for obj in contents:
            key = obj["Key"]
            filename = key.rsplit("/", 1)[-1]
            if not filename:
                continue
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
            dest = target_dir / filename
            dest.write_bytes(body)
            downloaded.append({"name": filename, "key": key, "bytes": len(body), "sha256": sha256_file(dest)})
        return {"ok": True, "archiveId": archive_id, "files": downloaded}

    def list_archive_keys(self, archive_id: str) -> list[str]:
        prefix = self.archive_prefix(archive_id)
        listed = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        return [obj["Key"] for obj in listed.get("Contents") or []]

    def delete_archive(self, archive_id: str) -> dict[str, Any]:
        prefix = self.archive_prefix(archive_id)
        try:
            listed = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
        except Exception as exc:
            return {"ok": False, "error": {"code": "list_failed", "message": str(exc)}}
        contents = listed.get("Contents") or []
        if not contents:
            return {"ok": True, "archiveId": archive_id, "deleted": 0}
        keys = [obj["Key"] for obj in contents]
        self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": [{"Key": k} for k in keys]})
        return {"ok": True, "archiveId": archive_id, "deleted": len(keys)}


def get_object_backup_store() -> ObjectBackupStore | None:
    settings = get_settings()
    if not settings.object_backup_bucket:
        return None
    return ObjectBackupStore(
        bucket=settings.object_backup_bucket,
        prefix=settings.object_backup_prefix,
        endpoint_url=settings.object_backup_endpoint_url,
        access_key_id=settings.object_backup_access_key_id,
        secret_access_key=settings.object_backup_secret_access_key,
        region=settings.object_backup_region,
    )
