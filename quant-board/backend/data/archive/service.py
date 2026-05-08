from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.data.archive.duckdb_query import ArchiveQueryError, DuckDBArchiveQuery
from backend.data.archive.manifest import ARCHIVE_SCHEMA_VERSION, read_manifest, research_archive_id, sha256_file, snapshot_archive_id, write_manifest
from backend.data.archive.object_store import get_object_backup_store
from backend.data.archive.parquet_store import ParquetStore
from backend.data.models import (
    ArchiveManifestModel,
    BacktestEquityCurve,
    BacktestRun,
    BacktestSignal,
    BacktestTrade,
    SnapshotFrameModel,
    SnapshotRecordModel,
    SnapshotSectorRowModel,
    SnapshotStockRowModel,
)
from backend.settings import get_settings


ALLOWED_ARCHIVE_FILENAMES = {
    "records.parquet",
    "frames.parquet",
    "stock_rows.parquet",
    "sector_rows.parquet",
    "trades.parquet",
    "equity_curve.parquet",
    "signals.parquet",
    "manifest.json",
    "archive_index.jsonl",
}


def _remove_known_archive_files(directory: Path) -> list[str]:
    removed: list[str] = []
    for name in ALLOWED_ARCHIVE_FILENAMES:
        path = directory / name
        if path.is_file():
            path.unlink()
            removed.append(str(path))
    return removed


def _publish_known_archive_files(source_dir: Path, target_dir: Path) -> list[str]:
    target_dir.mkdir(parents=True, exist_ok=True)
    _remove_known_archive_files(target_dir)
    published: list[str] = []
    for name in ALLOWED_ARCHIVE_FILENAMES:
        src = source_dir / name
        if src.is_file():
            dest = target_dir / name
            src.replace(dest)
            published.append(str(dest))
    return published


def _safe_archive_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value))


class ArchiveService:
    def __init__(self, session: Session, *, research_session: Session | None = None, archive_dir: Path | None = None, compression: str | None = None) -> None:
        settings = get_settings()
        self.session = session
        self.research_session = research_session
        self.archive_dir = Path(archive_dir or settings.archive_dir)
        self.compression = compression or settings.archive_parquet_compression

    def archive_snapshots(
        self,
        *,
        dataset_id: str,
        snapshot_type: str,
        before_trading_date: str,
        dry_run: bool = False,
        apply: bool = False,
        max_partitions: int | None = None,
    ) -> dict[str, Any]:
        dates = self._snapshot_candidate_dates(dataset_id, snapshot_type, before_trading_date)
        if max_partitions and max_partitions > 0:
            dates = dates[:max_partitions]
        rows = self._snapshot_rows(dataset_id, snapshot_type, dates)
        row_counts = {key: len(value) for key, value in rows.items()}
        archive_id = (
            snapshot_archive_id(dataset_id, snapshot_type, dates[0])
            if len(dates) == 1
            else snapshot_archive_id(dataset_id, snapshot_type, f"before_{before_trading_date}")
        )
        local_path = self._snapshot_archive_path(dataset_id, snapshot_type, dates[0] if len(dates) == 1 else f"before_{before_trading_date}")
        base = self._response_base(
            archive_id=archive_id,
            scope="snapshots",
            dry_run=dry_run,
            local_path=local_path,
            row_counts={
                "records": row_counts["records"],
                "frames": row_counts["frames"],
                "stockRows": row_counts["stockRows"],
                "sectorRows": row_counts["sectorRows"],
            },
        )
        if dry_run or not apply:
            return base
        if not rows["stockRows"] and not rows["sectorRows"]:
            return {**base, "ok": False, "error": {"code": "archive_empty_table", "message": "no detail rows to archive"}}

        files = self._write_tables(
            local_path,
            {
                "records": rows["records"] or [{"archiveId": archive_id}],
                "frames": rows["frames"] or [{"archiveId": archive_id}],
                "stock_rows": rows["stockRows"],
                "sector_rows": rows["sectorRows"],
            },
        )
        new_hashes = {item["name"]: item["sha256"] for item in files}
        existing = self.get_manifest(archive_id)
        if existing and existing.status in {"verified", "uploaded"}:
            old_hashes = json.loads(existing.file_hashes_json or "{}")
            if new_hashes == old_hashes:
                return {**base, "deduped": True, "status": existing.status}
            if local_path.exists():
                _remove_known_archive_files(local_path)
            return {
                **base,
                "ok": False,
                "status": "archive_hash_conflict",
                "error": {
                    "code": "archive_hash_conflict",
                    "archiveId": archive_id,
                    "message": "existing archive has different file hash",
                },
            }

        manifest_payload = {
            "archiveId": archive_id,
            "scope": "snapshots",
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDates": dates,
            "rowCounts": base["rowCounts"],
            "files": files,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        write_manifest(local_path / "manifest.json", manifest_payload)
        self._upsert_manifest(
            archive_id=archive_id,
            scope="snapshots",
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=dates[0] if len(dates) == 1 else None,
            run_id=None,
            local_path=local_path,
            status="verified",
            row_counts=base["rowCounts"],
            files=files,
        )
        verified = self.verify_archive(archive_id)
        if not verified.get("ok"):
            self._mark_manifest_failed(archive_id, "verify_failed", verified.get("error"))
            return {**base, "ok": False, "status": "verify_failed", "files": files, "error": verified.get("error")}
        deleted = self._delete_snapshot_detail_rows(dataset_id, snapshot_type, dates)
        return {
            **base,
            "status": "verified",
            "files": files,
            "deletedFromSqlite": deleted,
        }

    def restore_archive(self, archive_id: str, *, dry_run: bool = False, apply: bool = False) -> dict[str, Any]:
        manifest = self.get_manifest(archive_id)
        if not manifest:
            return {"ok": False, "error": {"code": "archive_not_found", "archiveId": archive_id}}
        payload = read_manifest(Path(manifest.local_path) / "manifest.json")
        if dry_run or not apply:
            return {"ok": True, "dryRun": True, "archiveId": archive_id, "rowCounts": payload.get("rowCounts") or {}}
        if manifest.scope == "snapshots":
            return self._restore_snapshot_archive(manifest, payload)
        if manifest.scope == "research":
            return self._restore_research_archive(manifest, payload)
        return {"ok": False, "error": {"code": "unsupported_archive_scope", "scope": manifest.scope}}

    def backup_snapshot_day_to_object(
        self,
        *,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        rows = self._snapshot_rows(dataset_id, snapshot_type, [trading_date])
        row_counts = {key: len(value) for key, value in rows.items()}
        safe_dataset_id = _safe_archive_part(dataset_id)
        safe_snapshot_type = _safe_archive_part(snapshot_type)
        safe_trading_date = _safe_archive_part(trading_date)
        archive_id = f"snapshot_backup_{safe_dataset_id}_{safe_snapshot_type}_{safe_trading_date}"
        local_path = self.archive_dir / "backups" / f"dataset_id={safe_dataset_id}" / f"snapshot_type={safe_snapshot_type}" / f"trading_date={safe_trading_date}"
        base = {
            "ok": True,
            "dryRun": dry_run,
            "archiveId": archive_id,
            "scope": "snapshot_backup",
            "source": "sqlite",
            "target": "r2_object_backup",
            "localPath": str(local_path),
            "rowCounts": {
                "records": row_counts["records"],
                "frames": row_counts["frames"],
                "stockRows": row_counts["stockRows"],
                "sectorRows": row_counts["sectorRows"],
            },
            "files": [],
            "deletedFromSqlite": {},
            "errors": [],
        }
        if dry_run:
            return base
        if not rows["stockRows"] and not rows["sectorRows"]:
            return {
                **base,
                "ok": False,
                "error": {"code": "backup_empty_table", "message": "no snapshot detail rows to backup"},
            }
        store = get_object_backup_store()
        if not store:
            return {**base, "ok": False, "error": {"code": "object_backup_not_configured"}}

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
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDates": [trading_date],
            "rowCounts": base["rowCounts"],
            "files": files,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "sqliteRetained": True,
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
        manifest = self.get_manifest(archive_id)
        if manifest:
            manifest.object_key = store.archive_prefix(archive_id)
            manifest.uploaded_at = datetime.now(timezone.utc)
            manifest.status = "uploaded"
            manifest.last_error = None
            self.session.commit()
        return {
            **base,
            "files": files,
            "uploadResult": result,
            "objectKey": store.archive_prefix(archive_id),
        }

    def latest_snapshot_trading_date(self, *, dataset_id: str, snapshot_type: str) -> str | None:
        return self.session.scalar(
            select(SnapshotFrameModel.trading_date)
            .where(SnapshotFrameModel.dataset_id == dataset_id)
            .where(SnapshotFrameModel.type == snapshot_type)
            .group_by(SnapshotFrameModel.trading_date)
            .order_by(SnapshotFrameModel.trading_date.desc())
            .limit(1)
        )

    def archive_research(
        self,
        *,
        run_id: str | None = None,
        older_than_days: int = 30,
        keep_latest_per_group: int = 10,
        dry_run: bool = False,
        apply: bool = False,
    ) -> dict[str, Any]:
        run_ids = [run_id] if run_id else self._research_candidate_run_ids(older_than_days, keep_latest_per_group)
        totals = {"trades": 0, "equityCurve": 0, "signals": 0}
        results = []
        for candidate in run_ids:
            result = self._archive_one_research_run(candidate, dry_run=dry_run, apply=apply)
            results.append(result)
            for key in totals:
                totals[key] += int(result.get("rowCounts", {}).get(key) or 0)
        return {"ok": all(item.get("ok") for item in results), "dryRun": dry_run, "rowCounts": totals, "runs": results}

    def query_archived_stock_rows(self, **filters: Any) -> list[dict[str, Any]]:
        result = self.query_archived_stock_rows_result(**filters)
        if not result.get("ok"):
            raise ArchiveQueryError(result["error"]["code"], result["error"].get("message", "archive query failed"), **{k: v for k, v in result["error"].items() if k not in {"code", "message"}})
        return result["rows"]

    def query_archived_sector_rows(self, **filters: Any) -> list[dict[str, Any]]:
        result = self.query_archived_sector_rows_result(**filters)
        if not result.get("ok"):
            raise ArchiveQueryError(result["error"]["code"], result["error"].get("message", "archive query failed"), **{k: v for k, v in result["error"].items() if k not in {"code", "message"}})
        return result["rows"]

    def query_archived_stock_rows_result(self, **filters: Any) -> dict[str, Any]:
        return self._query_archived_snapshot_table_result("stock_rows", **filters)

    def query_archived_sector_rows_result(self, **filters: Any) -> dict[str, Any]:
        return self._query_archived_snapshot_table_result("sector_rows", **filters)

    def query_archived_research_table(
        self,
        run_id: str,
        table: str,
        *,
        limit: int | None = None,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        manifest = self._latest_manifest(scope="research", run_id=run_id)
        if not manifest:
            return []
        path = Path(manifest.local_path) / f"{table}.parquet"
        if not path.exists():
            return []
        return DuckDBArchiveQuery().read_table(path, table=table, filters=filters or {}, sort="asc", limit=limit, offset=offset)

    def count_archived_research_table(self, run_id: str, table: str, *, filters: dict[str, Any] | None = None) -> int:
        return len(self.query_archived_research_table(run_id, table, filters=filters))

    def retention_cutoff_trading_date(self, *, dataset_id: str, snapshot_types: list[str], keep_trading_days: int) -> str | None:
        query = (
            select(SnapshotFrameModel.trading_date)
            .where(SnapshotFrameModel.dataset_id == dataset_id)
            .where(SnapshotFrameModel.type.in_(snapshot_types))
            .group_by(SnapshotFrameModel.trading_date)
            .order_by(SnapshotFrameModel.trading_date.desc())
        )
        dates = [str(row[0]) for row in self.session.execute(query).all()]
        if len(dates) <= keep_trading_days:
            return None
        return dates[keep_trading_days - 1]

    def get_manifest(self, archive_id: str) -> ArchiveManifestModel | None:
        return self.session.scalar(select(ArchiveManifestModel).where(ArchiveManifestModel.archive_id == archive_id))

    def list_manifests(self, scope: str | None = None) -> list[dict[str, Any]]:
        query = select(ArchiveManifestModel).order_by(ArchiveManifestModel.created_at.desc())
        if scope:
            query = query.where(ArchiveManifestModel.scope == scope)
        return [self._manifest_to_dict(row) for row in self.session.scalars(query)]

    def verify_archive(self, archive_id: str) -> dict[str, Any]:
        manifest = self.get_manifest(archive_id)
        if not manifest:
            return {"ok": False, "error": {"code": "archive_not_found", "archiveId": archive_id}}
        if manifest.scope not in {"snapshots", "research"}:
            return {
                "ok": False,
                "error": {
                    "code": "unsupported_archive_scope",
                    "archiveId": archive_id,
                    "scope": manifest.scope,
                },
            }
        local_path = Path(manifest.local_path)
        manifest_path = local_path / "manifest.json"
        if not manifest_path.is_file():
            return {
                "ok": False,
                "error": {"code": "archive_file_missing", "archiveId": archive_id, "file": "manifest.json"},
            }
        try:
            payload = read_manifest(manifest_path)
        except Exception as exc:
            return {
                "ok": False,
                "error": {"code": "archive_manifest_invalid", "archiveId": archive_id, "message": str(exc)},
            }

        expected_counts = json.loads(manifest.row_counts_json or "{}")
        expected_hashes = json.loads(manifest.file_hashes_json or "{}")
        manifest_files = {
            str(item.get("name")): item
            for item in payload.get("files") or []
            if isinstance(item, dict) and item.get("name")
        }
        required_files = ["manifest.json"] + self._required_archive_files(manifest.scope, expected_counts)
        checked = 0
        for name in required_files:
            path = local_path / name
            if not path.is_file():
                return {
                    "ok": False,
                    "error": {"code": "archive_file_missing", "archiveId": archive_id, "file": name},
                }
            checked += 1
            if name == "manifest.json":
                continue
            actual_hash = sha256_file(path)
            expected_hash = expected_hashes.get(name) or manifest_files.get(name, {}).get("sha256")
            if expected_hash and actual_hash != expected_hash:
                return {
                    "ok": False,
                    "error": {
                        "code": "archive_sha256_mismatch",
                        "archiveId": archive_id,
                        "file": name,
                        "expected": expected_hash,
                        "actual": actual_hash,
                    },
                }
            expected_bytes = manifest_files.get(name, {}).get("bytes")
            if expected_bytes is not None and int(path.stat().st_size) != int(expected_bytes):
                return {
                    "ok": False,
                    "error": {
                        "code": "archive_byte_size_mismatch",
                        "archiveId": archive_id,
                        "file": name,
                        "expected": int(expected_bytes),
                        "actual": int(path.stat().st_size),
                    },
                }

        actual_counts = self._archive_actual_row_counts(manifest.scope, local_path, expected_counts)
        for key, expected in expected_counts.items():
            if int(actual_counts.get(key) or 0) != int(expected or 0):
                return {
                    "ok": False,
                    "error": {
                        "code": "archive_row_count_mismatch",
                        "archiveId": archive_id,
                        "table": key,
                        "expected": int(expected or 0),
                        "actual": int(actual_counts.get(key) or 0),
                    },
                }

        manifest.status = "verified"
        manifest.last_error = None
        self.session.commit()
        return {
            "ok": True,
            "archiveId": archive_id,
            "status": "verified",
            "checkedFiles": checked,
            "rowCounts": expected_counts,
        }

    def push_archive_backup(self, *, limit: int | None = None) -> dict[str, Any]:
        store = get_object_backup_store()
        if not store:
            return {"ok": False, "error": {"code": "object_backup_not_configured"}}
        query = select(ArchiveManifestModel).where(
            ArchiveManifestModel.object_key.is_(None),
            ArchiveManifestModel.status.in_(["local_written", "verified"]),
            ArchiveManifestModel.local_path != "",
        ).order_by(ArchiveManifestModel.created_at.asc())
        if limit and limit > 0:
            query = query.limit(limit)
        manifests = list(self.session.scalars(query))
        if not manifests:
            return {"ok": True, "pushed": 0, "manifests": []}
        results = []
        for manifest in manifests:
            previous_object_key = manifest.object_key
            previous_uploaded_at = manifest.uploaded_at
            previous_status = manifest.status
            manifest.object_key = store.archive_prefix(manifest.archive_id)
            manifest.uploaded_at = datetime.now(timezone.utc)
            index_path = self._append_archive_index(manifest)
            result = store.push_archive(Path(manifest.local_path), archive_id=manifest.archive_id, archive_index_path=index_path)
            if result.get("ok"):
                manifest.status = "uploaded"
                manifest.last_error = None
            else:
                manifest.object_key = previous_object_key
                manifest.uploaded_at = previous_uploaded_at
                manifest.status = previous_status
                manifest.last_error = result.get("error", {}).get("message", str(result))
            self.session.commit()
            results.append({**self._manifest_to_dict(manifest), "uploadResult": result})
        return {"ok": all(item.get("uploadResult", {}).get("ok") for item in results), "pushed": len(results), "manifests": results}

    def pull_archive_backup(self, archive_id: str, *, dry_run: bool = False, apply: bool = False) -> dict[str, Any]:
        import shutil
        import tempfile

        store = get_object_backup_store()
        if not store:
            return {"ok": False, "error": {"code": "object_backup_not_configured"}}
        manifest = self.get_manifest(archive_id)
        if not manifest:
            return {"ok": False, "error": {"code": "archive_not_found", "archiveId": archive_id}}
        if not manifest.object_key:
            return {"ok": False, "error": {"code": "manifest_not_uploaded", "archiveId": archive_id}}
        if dry_run or not apply:
            try:
                keys = store.list_archive_keys(archive_id)
            except Exception as exc:
                return {"ok": False, "error": {"code": "list_failed", "message": str(exc)}}
            return {"ok": True, "dryRun": True, "archiveId": archive_id, "remoteKeys": keys}
        expected_hashes = json.loads(manifest.file_hashes_json or "{}")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp) / archive_id
            result = store.pull_archive(archive_id, tmp_dir)
            if not result.get("ok"):
                manifest.last_error = result.get("error", {}).get("message", str(result))
                self.session.commit()
                return result
            for f in result["files"]:
                if f["name"] in expected_hashes and f["sha256"] != expected_hashes[f["name"]]:
                    manifest.last_error = f"sha256 mismatch for {f['name']}: expected {expected_hashes[f['name']]}, got {f['sha256']}"
                    manifest.status = "hash_mismatch"
                    self.session.commit()
                    return {"ok": False, "error": {"code": "sha256_mismatch", "archiveId": archive_id, "file": f["name"], "expected": expected_hashes[f["name"]], "actual": f["sha256"]}}
            target_dir = self.archive_dir / archive_id
            _publish_known_archive_files(tmp_dir, target_dir)
        manifest.local_path = str(target_dir)
        manifest.status = "verified"
        manifest.last_error = None
        self.session.commit()
        return {**result, "restored": result["files"], "dryRun": False}

    def _append_archive_index(self, manifest: ArchiveManifestModel) -> Path:
        index_path = self.archive_dir / "archive_index.jsonl"
        record = {
            "archiveId": manifest.archive_id,
            "objectKey": manifest.object_key,
            "uploadedAt": manifest.uploaded_at.isoformat() if manifest.uploaded_at else None,
            "byteSize": manifest.byte_size,
        }
        line = json.dumps(record, ensure_ascii=False)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with index_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if index_path.stat().st_size > 500_000:
            lines = index_path.read_text(encoding="utf-8").splitlines()
            index_path.write_text("\n".join(lines[-1000:]) + "\n", encoding="utf-8")
        return index_path

    def _required_archive_files(self, scope: str, row_counts: dict[str, Any]) -> list[str]:
        if scope == "snapshots":
            pairs = (
                ("records", "records.parquet"),
                ("frames", "frames.parquet"),
                ("stockRows", "stock_rows.parquet"),
                ("sectorRows", "sector_rows.parquet"),
            )
        elif scope == "research":
            pairs = (
                ("trades", "trades.parquet"),
                ("equityCurve", "equity_curve.parquet"),
                ("signals", "signals.parquet"),
            )
        else:
            return []
        return [filename for key, filename in pairs if int(row_counts.get(key) or 0) > 0]

    def _archive_actual_row_counts(self, scope: str, local_path: Path, expected_counts: dict[str, Any]) -> dict[str, int]:
        store = ParquetStore(local_path, compression=self.compression)
        if scope == "snapshots":
            table_map = {
                "records": "records",
                "frames": "frames",
                "stockRows": "stock_rows",
                "sectorRows": "sector_rows",
            }
        else:
            table_map = {
                "trades": "trades",
                "equityCurve": "equity_curve",
                "signals": "signals",
            }
        counts: dict[str, int] = {}
        for key, table in table_map.items():
            if key not in expected_counts:
                continue
            path = local_path / f"{table}.parquet"
            counts[key] = len(store.read_table(table)) if path.is_file() else 0
        return counts

    def _snapshot_candidate_dates(self, dataset_id: str, snapshot_type: str, before_trading_date: str) -> list[str]:
        query = (
            select(SnapshotFrameModel.trading_date)
            .where(SnapshotFrameModel.dataset_id == dataset_id)
            .where(SnapshotFrameModel.type == snapshot_type)
            .where(SnapshotFrameModel.trading_date < before_trading_date)
            .group_by(SnapshotFrameModel.trading_date)
            .order_by(SnapshotFrameModel.trading_date.asc())
        )
        return [str(row[0]) for row in self.session.execute(query).all()]

    def _snapshot_rows(self, dataset_id: str, snapshot_type: str, dates: list[str]) -> dict[str, list[dict[str, Any]]]:
        from backend.data.repository import Repository

        if not dates:
            return {"records": [], "frames": [], "stockRows": [], "sectorRows": []}
        repo = Repository(self.session, enable_backup=False)
        records = [
            repo.record_to_dict(row)
            for row in self.session.scalars(
                select(SnapshotRecordModel)
                .where(SnapshotRecordModel.dataset_id == dataset_id)
                .where(SnapshotRecordModel.type == snapshot_type)
                .where(SnapshotRecordModel.trading_date.in_(dates))
                .order_by(SnapshotRecordModel.timestamp.asc())
            )
        ]
        frames = [
            repo.local_frame_to_bundle_dict(row)
            for row in self.session.scalars(
                select(SnapshotFrameModel)
                .where(SnapshotFrameModel.dataset_id == dataset_id)
                .where(SnapshotFrameModel.type == snapshot_type)
                .where(SnapshotFrameModel.trading_date.in_(dates))
                .order_by(SnapshotFrameModel.timestamp.asc())
            )
        ]
        stock_result = repo.list_snapshot_stock_rows(dataset_id, snapshot_type=snapshot_type, start_date=dates[0], end_date=dates[-1], sort="asc")
        sector_result = repo.list_snapshot_sector_rows(dataset_id, snapshot_type=snapshot_type, start_date=dates[0], end_date=dates[-1], sort="asc")
        return {"records": records, "frames": frames, "stockRows": stock_result["rows"], "sectorRows": sector_result["rows"]}

    def _write_tables(self, local_path: Path, tables: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        store = ParquetStore(local_path, compression=self.compression)
        files = []
        for name, rows in tables.items():
            if rows:
                files.append(store.write_table(name, rows))
        return files

    def _delete_snapshot_detail_rows(self, dataset_id: str, snapshot_type: str, dates: list[str]) -> dict[str, int]:
        stock = self.session.execute(
            delete(SnapshotStockRowModel)
            .where(SnapshotStockRowModel.dataset_id == dataset_id)
            .where(SnapshotStockRowModel.type == snapshot_type)
            .where(SnapshotStockRowModel.trading_date.in_(dates))
        )
        sector = self.session.execute(
            delete(SnapshotSectorRowModel)
            .where(SnapshotSectorRowModel.dataset_id == dataset_id)
            .where(SnapshotSectorRowModel.type == snapshot_type)
            .where(SnapshotSectorRowModel.trading_date.in_(dates))
        )
        self.session.commit()
        return {"stockRows": int(stock.rowcount or 0), "sectorRows": int(sector.rowcount or 0)}

    def _restore_snapshot_archive(self, manifest: ArchiveManifestModel, payload: dict[str, Any]) -> dict[str, Any]:
        from backend.data.repository import Repository

        repo = Repository(self.session, enable_backup=False)
        store = ParquetStore(Path(manifest.local_path), compression=self.compression)
        stock_rows = store.read_table("stock_rows")
        sector_rows = store.read_table("sector_rows")
        self.session.add_all([repo._stock_model(str(manifest.dataset_id), item) for item in stock_rows])
        self.session.add_all([repo._sector_model(str(manifest.dataset_id), item) for item in sector_rows])
        self.session.commit()
        return {
            "ok": True,
            "dryRun": False,
            "archiveId": manifest.archive_id,
            "restored": {"stockRows": len(stock_rows), "sectorRows": len(sector_rows)},
            "rowCounts": payload.get("rowCounts") or {},
        }

    def _archive_one_research_run(self, run_id: str, *, dry_run: bool, apply: bool) -> dict[str, Any]:
        from backend.data.repository import Repository

        research_session = self.research_session or self.session
        repo = Repository(research_session, enable_backup=False)
        archive_id = research_archive_id(run_id)
        local_path = self.archive_dir / "research" / f"run_id={run_id}"
        trades = repo.get_backtest_trades(run_id, limit=None)
        equity = repo.get_backtest_equity_curve(run_id)
        signals = repo.get_backtest_signals(run_id, limit=None)
        row_counts = {"trades": len(trades), "equityCurve": len(equity), "signals": len(signals)}
        base = self._response_base(archive_id=archive_id, scope="research", dry_run=dry_run, local_path=local_path, row_counts=row_counts)
        if dry_run or not apply:
            return base
        files = self._write_tables(
            local_path,
            {
                "trades": trades,
                "equity_curve": equity,
                "signals": signals,
            },
        )
        new_hashes = {item["name"]: item["sha256"] for item in files}
        existing = self.get_manifest(archive_id)
        if existing and existing.status in {"verified", "uploaded"}:
            old_hashes = json.loads(existing.file_hashes_json or "{}")
            if new_hashes == old_hashes:
                return {**base, "deduped": True, "status": existing.status}
            if local_path.exists():
                _remove_known_archive_files(local_path)
            return {
                **base,
                "ok": False,
                "status": "archive_hash_conflict",
                "error": {
                    "code": "archive_hash_conflict",
                    "archiveId": archive_id,
                    "message": "existing archive has different file hash",
                },
            }
        write_manifest(
            local_path / "manifest.json",
            {"archiveId": archive_id, "scope": "research", "runId": run_id, "rowCounts": row_counts, "files": files},
        )
        self._upsert_manifest(
            archive_id=archive_id,
            scope="research",
            dataset_id=None,
            snapshot_type=None,
            trading_date=None,
            run_id=run_id,
            local_path=local_path,
            status="verified",
            row_counts=row_counts,
            files=files,
        )
        verified = self.verify_archive(archive_id)
        if not verified.get("ok"):
            self._mark_manifest_failed(archive_id, "verify_failed", verified.get("error"))
            return {**base, "ok": False, "status": "verify_failed", "files": files, "error": verified.get("error")}
        deleted = self._delete_research_detail_rows(run_id)
        return {**base, "status": "verified", "files": files, "deletedFromSqlite": deleted}

    def _restore_research_archive(self, manifest: ArchiveManifestModel, payload: dict[str, Any]) -> dict[str, Any]:
        from backend.data.repository import Repository

        research_session = self.research_session or self.session
        repo = Repository(research_session, enable_backup=False)
        store = ParquetStore(Path(manifest.local_path), compression=self.compression)
        trades = store.read_table("trades")
        equity = store.read_table("equity_curve")
        signals = store.read_table("signals")
        run_id = str(manifest.run_id)
        repo.save_backtest_trades(run_id, trades)
        repo.save_backtest_equity_rows(run_id, equity)
        repo.save_backtest_signal_rows(run_id, signals)
        return {
            "ok": True,
            "archiveId": manifest.archive_id,
            "restored": {"trades": len(trades), "equityCurve": len(equity), "signals": len(signals)},
            "rowCounts": payload.get("rowCounts") or {},
        }

    def _delete_research_detail_rows(self, run_id: str) -> dict[str, int]:
        research_session = self.research_session or self.session
        deleted: dict[str, int] = {}
        for name, model in (
            ("trades", BacktestTrade),
            ("equityCurve", BacktestEquityCurve),
            ("signals", BacktestSignal),
        ):
            result = research_session.execute(delete(model).where(model.backtest_run_id == run_id))
            deleted[name] = int(result.rowcount or 0)
        research_session.commit()
        return deleted

    def _research_candidate_run_ids(self, older_than_days: int, keep_latest_per_group: int) -> list[str]:
        from datetime import timedelta, timezone

        research_session = self.research_session or self.session
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        rows = list(
            research_session.scalars(
                select(BacktestRun)
                .where(BacktestRun.created_at < cutoff)
                .order_by(BacktestRun.created_at.desc(), BacktestRun.id.asc())
            )
        )
        groups: dict[tuple[Any, ...], list[BacktestRun]] = {}
        for row in rows:
            key = (
                row.dataset_id,
                row.strategy_name,
                row.snapshot_type,
                row.strategy_version,
                row.config_hash,
                row.random_seed,
            )
            groups.setdefault(key, []).append(row)
        candidates: list[BacktestRun] = []
        for group_rows in groups.values():
            candidates.extend(group_rows[max(0, keep_latest_per_group):] if keep_latest_per_group > 0 else group_rows)
        candidates.sort(key=lambda row: (row.created_at, row.id))
        return [str(row.id) for row in candidates]

    def _query_archived_snapshot_table(self, table: str, **filters: Any) -> list[dict[str, Any]]:
        result = self._query_archived_snapshot_table_result(table, **filters)
        if not result.get("ok"):
            raise ArchiveQueryError(result["error"]["code"], result["error"].get("message", "archive query failed"), **{k: v for k, v in result["error"].items() if k not in {"code", "message"}})
        return result["rows"]

    def _query_archived_snapshot_table_result(self, table: str, **filters: Any) -> dict[str, Any]:
        dataset_id = filters.get("dataset_id")
        snapshot_type = filters.get("snapshot_type")
        trading_date = filters.get("trading_date")
        start_date = filters.get("start_date")
        end_date = filters.get("end_date")
        before_trading_date = filters.get("before_trading_date")
        query = select(ArchiveManifestModel).where(ArchiveManifestModel.scope == "snapshots").where(ArchiveManifestModel.status.in_(["verified", "uploaded"]))
        if dataset_id:
            query = query.where(ArchiveManifestModel.dataset_id == dataset_id)
        if snapshot_type:
            query = query.where(ArchiveManifestModel.snapshot_type == snapshot_type)
        if trading_date:
            query = query.where(ArchiveManifestModel.trading_date == trading_date)
        if start_date:
            query = query.where((ArchiveManifestModel.trading_date >= start_date) | ArchiveManifestModel.trading_date.is_(None))
        if end_date:
            query = query.where((ArchiveManifestModel.trading_date <= end_date) | ArchiveManifestModel.trading_date.is_(None))
        if before_trading_date:
            query = query.where((ArchiveManifestModel.trading_date < before_trading_date) | ArchiveManifestModel.trading_date.is_(None))
        manifests = list(self.session.scalars(query))
        output: list[dict[str, Any]] = []
        duck = DuckDBArchiveQuery()
        parquet_filters = {
            "snapshotId": filters.get("snapshot_id"),
            "type": snapshot_type,
            "tradingDate": trading_date,
            "code": filters.get("code"),
            "slotTime": filters.get("slot_time"),
            "entityType": filters.get("entity_type"),
            "entityKey": filters.get("entity_key"),
            "__startDate": start_date,
            "__endDate": end_date,
            "__beforeTradingDate": before_trading_date,
        }
        for manifest in manifests:
            path = Path(manifest.local_path) / f"{table}.parquet"
            if not path.exists():
                return {
                    "ok": False,
                    "error": {"code": "archive_file_missing", "archiveId": manifest.archive_id, "file": path.name},
                }
            try:
                output.extend(duck.read_table(path, table=table, filters=parquet_filters, sort=filters.get("sort") or "desc", limit=filters.get("limit")))
            except ArchiveQueryError as exc:
                return {"ok": False, "error": {"archiveId": manifest.archive_id, **exc.to_error()}}
        return {"ok": True, "rows": output, "source": "parquet_archive" if output else "sqlite"}

    def _latest_manifest(self, *, scope: str, run_id: str) -> ArchiveManifestModel | None:
        return self.session.scalar(
            select(ArchiveManifestModel)
            .where(ArchiveManifestModel.scope == scope)
            .where(ArchiveManifestModel.run_id == run_id)
            .where(ArchiveManifestModel.status.in_(["verified", "uploaded"]))
            .order_by(ArchiveManifestModel.created_at.desc())
        )

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
    ) -> ArchiveManifestModel:
        row = self.get_manifest(archive_id) or ArchiveManifestModel(archive_id=archive_id, scope=scope)
        row.dataset_id = dataset_id
        row.snapshot_type = snapshot_type
        row.trading_date = trading_date
        row.run_id = run_id
        row.local_path = str(local_path)
        row.status = status
        row.row_counts_json = json.dumps(row_counts, ensure_ascii=False)
        row.file_hashes_json = json.dumps({item["name"]: item["sha256"] for item in files}, ensure_ascii=False)
        row.byte_size = sum(int(item.get("bytes") or 0) for item in files)
        row.schema_version = ARCHIVE_SCHEMA_VERSION
        self.session.merge(row)
        self.session.commit()
        return row

    def _mark_manifest_failed(self, archive_id: str, status: str, error: Any) -> None:
        row = self.get_manifest(archive_id)
        if not row:
            return
        row.status = status
        row.last_error = json.dumps(error, ensure_ascii=False) if isinstance(error, dict) else str(error)
        self.session.commit()

    def _snapshot_archive_path(self, dataset_id: str, snapshot_type: str, trading_date: str) -> Path:
        return (
            self.archive_dir
            / "snapshots"
            / f"dataset_id={dataset_id}"
            / f"snapshot_type={snapshot_type}"
            / f"trading_date={trading_date}"
        )

    def _response_base(self, *, archive_id: str, scope: str, dry_run: bool, local_path: Path, row_counts: dict[str, int]) -> dict[str, Any]:
        return {
            "ok": True,
            "dryRun": dry_run,
            "archiveId": archive_id,
            "scope": scope,
            "status": "preview" if dry_run else "local_written",
            "source": "sqlite",
            "target": "parquet_local",
            "localPath": str(local_path),
            "rowCounts": row_counts,
            "files": [],
            "deletedFromSqlite": {},
            "errors": [],
        }

    @staticmethod
    def _manifest_to_dict(row: ArchiveManifestModel) -> dict[str, Any]:
        return {
            "archiveId": row.archive_id,
            "scope": row.scope,
            "datasetId": row.dataset_id,
            "snapshotType": row.snapshot_type,
            "tradingDate": row.trading_date,
            "runId": row.run_id,
            "localPath": row.local_path,
            "objectKey": row.object_key,
            "status": row.status,
            "rowCounts": json.loads(row.row_counts_json or "{}"),
            "fileHashes": json.loads(row.file_hashes_json or "{}"),
            "byteSize": row.byte_size,
            "schemaVersion": row.schema_version,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
            "uploadedAt": row.uploaded_at.isoformat() if row.uploaded_at else None,
            "lastError": row.last_error,
        }
