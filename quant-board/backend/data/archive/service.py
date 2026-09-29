from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.data.archive.manifest import ARCHIVE_SCHEMA_VERSION, write_manifest
from backend.data.archive.object_store import get_object_backup_store
from backend.data.archive.parquet_store import ParquetStore
from backend.core.settings import get_settings


def _safe_archive_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value))


def _strip_mongo_row(row: dict[str, Any]) -> dict[str, Any]:
    """去掉 ``_id`` 并把 bson 原生类型（ObjectId/Decimal128 等）转为字符串。

    parquet 编码层（``_encode_nested_values``）只接受 JSON 原生标量；ObjectId
    带 ``binary`` 属性、Decimal128 带 ``to_decimal``，用鸭子类型兑底不强依赖
    bson 包。datetime 保留（pyarrow 原生支持）。
    """
    clean: dict[str, Any] = {}
    for key, value in row.items():
        if key == "_id":
            continue
        if hasattr(value, "binary") or hasattr(value, "to_decimal"):
            clean[key] = str(value)
        else:
            clean[key] = value
    return clean


def _mongodb_snapshot_rows(
    mongo_db: Any,
    dataset_id: str,
    snapshot_type: str,
    trading_date: str,
) -> dict[str, list[dict[str, Any]]]:
    """从 Mongo 读某 dataset/type/date 的四表行（排序保证 parquet 可重现）。"""
    spec = {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date}
    collections = {
        "records": ("snapshot_records", [("snapshotId", 1)]),
        "frames": ("snapshot_frames", [("snapshotId", 1)]),
        "stockRows": ("snapshot_stock_rows", [("snapshotId", 1), ("code", 1)]),
        "sectorRows": ("snapshot_sector_rows", [("snapshotId", 1), ("entityKey", 1)]),
    }
    rows: dict[str, list[dict[str, Any]]] = {}
    for key, (collection, sort_spec) in collections.items():
        cursor = mongo_db[collection].find(spec).sort(sort_spec)
        rows[key] = [_strip_mongo_row(row) for row in cursor]
    return rows


class ArchiveService:
    """归档服务 —— mongodb 单链（R2 快照归档 + mongo manifest 台账）。

    2026-09-29 sqlite 退役：历史 sqlite snapshot/research 归档与 SQLAlchemy
    manifest 台账删除；manifest 统一落在 Mongo ``archive_manifests`` 集合
    （camelCase 字段，与 2026-09 迁移批次落库形状一致）。
    """

    def __init__(
        self,
        mongo_db: Any = None,
        *,
        archive_dir: Path | None = None,
        compression: str | None = None,
    ) -> None:
        settings = get_settings()
        self._mongo_db = mongo_db
        self.archive_dir = Path(archive_dir or settings.archive_dir)
        self.compression = compression or settings.archive_parquet_compression

    @property
    def db(self) -> Any:
        if self._mongo_db is None:
            from backend.data.repositories.repository_factory import get_runtime_mongodb_database

            self._mongo_db = get_runtime_mongodb_database()
        return self._mongo_db

    def backup_mongodb_snapshot_day_to_object(
        self,
        mongo_db: Any,
        *,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """MongoDB 快照日归档到 R2（mongodb 后端生产路径，2026-09-28）。

        按 dataset/type/date 读取 Mongo 四表 → parquet → R2 push → manifest
        登记（scope=snapshot_backup，status=uploaded）。差异与合同：

        * **只归档不删 Mongo**：frames API 无归档回读，删除热数据会让历史窗口
          静默变短；是否清理 Mongo 待归档回读链路就绪后单独决策；
        * 幂等去重：manifest 已 uploaded 的日期直接 skip（推送失败/未上传的
          允许重试）；
        * 当日无帧返回结构化 no_snapshot_frames（诚实暴露，不伪造空归档）。
        """
        rows = _mongodb_snapshot_rows(mongo_db, dataset_id, snapshot_type, trading_date)
        row_counts = {key: len(value) for key, value in rows.items()}
        safe_dataset_id = _safe_archive_part(dataset_id)
        safe_snapshot_type = _safe_archive_part(snapshot_type)
        safe_trading_date = _safe_archive_part(trading_date)
        archive_id = f"snapshot_backup_{safe_dataset_id}_{safe_snapshot_type}_{safe_trading_date}"
        local_path = (
            self.archive_dir
            / "backups"
            / f"dataset_id={safe_dataset_id}"
            / f"snapshot_type={safe_snapshot_type}"
            / f"trading_date={safe_trading_date}"
        )
        base = {
            "ok": True,
            "dryRun": dry_run,
            "archiveId": archive_id,
            "scope": "snapshot_backup",
            "source": "mongodb",
            "target": "r2_object_backup",
            "localPath": str(local_path),
            "rowCounts": {
                "records": row_counts["records"],
                "frames": row_counts["frames"],
                "stockRows": row_counts["stockRows"],
                "sectorRows": row_counts["sectorRows"],
            },
            "files": [],
            "mongoRetained": True,
            "errors": [],
        }
        existing = self.get_manifest(archive_id)
        if existing is not None and existing.get("status") == "uploaded":
            return {**base, "skipped": True, "reason": "already_archived"}
        if dry_run:
            return base
        if not rows["frames"]:
            return {
                **base,
                "ok": False,
                "skipped": True,
                "reason": "no_snapshot_frames",
            }
        if not rows["stockRows"] and not rows["sectorRows"]:
            return {
                **base,
                "ok": False,
                "skipped": True,
                "reason": "backup_empty_table",
            }
        store = get_object_backup_store()
        if not store:
            return {**base, "ok": False, "skipped": True, "reason": "object_backup_not_configured"}

        files = self._write_tables(
            local_path,
            {
                "records": rows["records"] or [{"archiveId": archive_id}],
                "frames": rows["frames"] or [{"archiveId": archive_id}],
                "stock_rows": rows["stockRows"],
                "sector_rows": rows["sectorRows"],
            },
        )
        manifest_payload = {
            "archiveId": archive_id,
            "scope": "snapshot_backup",
            "source": "mongodb",
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDates": [trading_date],
            "rowCounts": base["rowCounts"],
            "files": files,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "mongoRetained": True,
        }
        write_manifest(local_path / "manifest.json", manifest_payload)
        self._upsert_manifest(
            archive_id=archive_id,
            scope="snapshot_backup",
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            run_id=None,
            local_path=local_path,
            status="verified",
            row_counts=base["rowCounts"],
            files=files,
        )
        result = store.push_archive(local_path, archive_id=archive_id)
        if not result.get("ok"):
            self._mark_manifest_failed(archive_id, "verified", result.get("error"))
            return {**base, "ok": False, "files": files, "error": result.get("error")}
        self.db["archive_manifests"].update_one(
            {"archiveId": archive_id},
            {
                "$set": {
                    "objectKey": store.archive_prefix(archive_id),
                    "uploadedAt": datetime.now(timezone.utc).isoformat(),
                    "status": "uploaded",
                    "lastError": None,
                }
            },
        )
        return {
            **base,
            "files": files,
            "uploadResult": result,
            "objectKey": store.archive_prefix(archive_id),
        }

    # ── manifest 台账（Mongo archive_manifests）────────────────────────────

    def get_manifest(self, archive_id: str) -> dict[str, Any] | None:
        return self.db["archive_manifests"].find_one({"archiveId": archive_id})

    def _upsert_manifest(
        self,
        *,
        archive_id: str,
        scope: str,
        dataset_id: str | None,
        snapshot_type: str | None,
        trading_date: str | None,
        run_id: str | None,
        local_path: Path,
        status: str,
        row_counts: dict[str, int],
        files: list[dict[str, Any]],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_manifest(archive_id) or {}
        doc = {
            "archiveId": archive_id,
            "scope": scope,
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
            "runId": run_id,
            "localPath": str(local_path),
            "objectKey": existing.get("objectKey"),
            "status": status,
            "rowCounts": row_counts,
            "fileHashes": {item["name"]: item["sha256"] for item in files},
            "byteSize": sum(int(item.get("bytes") or 0) for item in files),
            "schemaVersion": ARCHIVE_SCHEMA_VERSION,
            "createdAt": existing.get("createdAt") or now,
            "uploadedAt": existing.get("uploadedAt"),
            "lastError": None,
        }
        self.db["archive_manifests"].replace_one({"archiveId": archive_id}, doc, upsert=True)

    def _mark_manifest_failed(self, archive_id: str, status: str, error: Any) -> None:
        self.db["archive_manifests"].update_one(
            {"archiveId": archive_id},
            {
                "$set": {
                    "status": status,
                    "lastError": json.dumps(error, ensure_ascii=False) if isinstance(error, dict) else str(error),
                }
            },
        )

    # ── parquet 落盘 ─────────────────────────────

    def _write_tables(self, local_path: Path, tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        store = ParquetStore(local_path, compression=self.compression)
        files = []
        for name, rows in tables.items():
            if rows:
                files.append(store.write_table(name, rows))
        return files
