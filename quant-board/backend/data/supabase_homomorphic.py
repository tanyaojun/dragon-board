from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import time
from typing import Any
from uuid import uuid4

import httpx

from backend.data.models import BacktestRun, Dataset, GoldenRankTrendCase, OptimizationRun
from backend.settings import Settings, get_settings
from backend.utils import json_dumps, json_loads, utc_now_iso


REQUIRED_TABLES = [
    "datasets",
    "snapshot_records",
    "snapshot_frames",
    "snapshot_stock_rows",
    "snapshot_sector_rows",
    "backtest_runs",
    "optimization_runs",
    "golden_ranktrend_cases",
    "sync_outbox",
]

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
UPSERT_CHUNK_SIZE = 100
UPSERT_CHUNK_BYTES = 8 * 1024 * 1024
REQUEST_RETRY_COUNT = 3
COMPRESSED_TEXT_PREFIX = "__qb_gzip_b64__:"
COMPRESSION_THRESHOLD_BYTES = 256 * 1024

REQUIRED_TABLE_COLUMNS = {
    "datasets": {
        "id",
        "name",
        "source_type",
        "source_path",
        "db_name",
        "schema_fingerprint",
        "snapshot_count",
        "frame_count",
        "stock_row_count",
        "sector_row_count",
        "start_date",
        "end_date",
        "snapshot_types_json",
        "metadata_json",
        "created_at",
    },
    "snapshot_records": {
        "id",
        "dataset_id",
        "snapshot_id",
        "type",
        "trading_date",
        "slot_time",
        "timestamp",
        "display_key",
        "capture_mode",
        "source",
        "payload_json",
    },
    "snapshot_frames": {
        "id",
        "dataset_id",
        "snapshot_id",
        "type",
        "trading_date",
        "slot_time",
        "timestamp",
        "capture_mode",
        "source",
        "market_context_json",
        "stock_row_count",
        "sector_row_count",
    },
    "snapshot_stock_rows": {
        "id",
        "dataset_id",
        "row_id",
        "snapshot_id",
        "type",
        "trading_date",
        "slot_time",
        "timestamp",
        "capture_mode",
        "code",
        "name",
        "rank",
        "price",
        "change",
        "volume_ratio",
        "zlje",
        "zljzb",
        "turnover",
        "turnover_rate",
        "payload_json",
    },
    "snapshot_sector_rows": {
        "id",
        "dataset_id",
        "row_id",
        "snapshot_id",
        "type",
        "trading_date",
        "slot_time",
        "timestamp",
        "entity_type",
        "entity_key",
        "entity_name",
        "rank",
        "payload_json",
    },
    "golden_ranktrend_cases": {"id", "name", "dataset_id", "input_json", "expected_json", "created_at"},
    "backtest_runs": {
        "id",
        "dataset_id",
        "strategy_name",
        "strategy_version",
        "snapshot_type",
        "config_hash",
        "random_seed",
        "status",
        "request_json",
        "result_json",
        "created_at",
    },
    "optimization_runs": {
        "id",
        "dataset_id",
        "strategy_name",
        "method",
        "config_hash",
        "random_seed",
        "status",
        "request_json",
        "result_json",
        "created_at",
    },
    "sync_outbox": {
        "id",
        "op_type",
        "dataset_id",
        "snapshot_id",
        "payload_json",
        "idempotency_key",
        "status",
        "retry_count",
        "last_error",
        "next_retry_at",
        "created_at",
        "updated_at",
    },
}


class SupabaseBackupClient:
    """Supabase REST client for SQLite-homomorphic QuantBoard backup tables."""

    def __init__(self, supabase_url: str, secret_key: str, timeout_seconds: float = 10.0) -> None:
        self.supabase_url = supabase_url.rstrip("/")
        self.secret_key = secret_key
        self.timeout_seconds = timeout_seconds
        self.enabled = bool(self.supabase_url and self.secret_key)
        self.last_error: str | None = None
        self._client: httpx.Client | None = None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SupabaseBackupClient | None:
        settings = settings or get_settings()
        if not settings.backup_mirror_enabled:
            return None
        if not settings.supabase_url or not settings.supabase_secret_key:
            return None
        return cls(settings.supabase_url, settings.supabase_secret_key, settings.backup_timeout_seconds)

    def health(self) -> dict[str, Any]:
        if not self.enabled:
            return {"configured": False, "connected": False, "schema": "sqlite_homomorphic", "last_error": None}

        missing: list[str] = []
        errors: dict[str, str] = {}
        ok, spec = self._request_json("GET", "/rest/v1/")
        definitions = spec.get("definitions") if ok and isinstance(spec, dict) else None
        for table, required_columns in REQUIRED_TABLE_COLUMNS.items():
            if not isinstance(definitions, dict):
                ok, _ = self._request_json("GET", f"/rest/v1/{table}", params={"select": "id", "limit": "1"})
                if not ok:
                    missing.append(table)
                    errors[table] = self.last_error or "unreadable table"
                continue
            definition = definitions.get(table) if isinstance(definitions.get(table), dict) else None
            if not definition:
                missing.append(table)
                errors[table] = f"missing table: {table}"
                continue
            properties = definition.get("properties") if isinstance(definition.get("properties"), dict) else {}
            actual_columns = set(properties.keys())
            missing_columns = sorted(required_columns - actual_columns)
            if missing_columns:
                missing.append(table)
                errors[table] = f"missing columns: {', '.join(missing_columns)}"
        return {
            "configured": True,
            "connected": not missing,
            "schema": "sqlite_homomorphic",
            "required_tables": REQUIRED_TABLES,
            "missing_or_unreadable_tables": missing,
            "table_errors": errors,
            "last_error": next(iter(errors.values()), self.last_error),
        }

    def smoke_test(self) -> dict[str, Any]:
        if not self.enabled:
            return {
                "ok": False,
                "configured": False,
                "connected": False,
                "write": False,
                "read": False,
                "cleanup": False,
                "last_error": None,
            }

        key = f"qb_smoke:{uuid4().hex}"
        now = utc_now_iso()
        row = {
            "op_type": "supabase_smoke",
            "payload_json": json_dumps({"idempotency_key": key, "created_at": now}),
            "idempotency_key": key,
            "status": "pending",
            "retry_count": 0,
            "last_error": None,
            "next_retry_at": None,
            "created_at": now,
            "updated_at": now,
        }
        write_ok = self._upsert_rows("sync_outbox", [row], "idempotency_key")
        found = self.get_row("qb_smoke", key) if write_ok else None
        read_ok = bool(found and found.get("idempotency_key") == key)
        cleanup_ok = False
        if write_ok:
            cleanup_ok, _ = self._request_json(
                "DELETE",
                "/rest/v1/sync_outbox",
                params={"idempotency_key": f"eq.{key}"},
                prefer="return=minimal",
            )
        return {
            "ok": bool(write_ok and read_ok and cleanup_ok),
            "configured": True,
            "connected": bool(write_ok or read_ok),
            "schema": "sqlite_homomorphic",
            "write": write_ok,
            "read": read_ok,
            "cleanup": cleanup_ok,
            "idempotency_key": key,
            "last_error": self.last_error,
        }

    def mirror_dataset_bundle(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
    ) -> bool:
        if not self.enabled:
            return False
        if not self._upsert_rows("datasets", [self._dataset_to_row(dataset)], "id"):
            return False
        if not self._upsert_rows(
            "snapshot_records",
            [self._record_to_row(dataset.id, item) for item in records],
            "dataset_id,snapshot_id",
        ):
            return False
        if not self._upsert_rows(
            "snapshot_frames",
            [self._frame_to_row(dataset.id, item) for item in frames],
            "dataset_id,snapshot_id",
        ):
            return False
        if not self._upsert_rows(
            "snapshot_stock_rows",
            [self._stock_to_row(dataset.id, item) for item in stock_rows],
            "dataset_id,row_id",
        ):
            return False
        return self._upsert_rows(
            "snapshot_sector_rows",
            [self._sector_to_row(dataset.id, item) for item in sector_rows],
            "dataset_id,row_id",
        )

    def mirror_backtest_run(self, run: BacktestRun) -> bool:
        return self._upsert_rows("backtest_runs", [self._backtest_to_row(run)], "id")

    def mirror_optimization_run(self, run: OptimizationRun) -> bool:
        return self._upsert_rows("optimization_runs", [self._optimization_to_row(run)], "id")

    def mirror_golden_case(self, case: GoldenRankTrendCase) -> bool:
        return self._upsert_rows("golden_ranktrend_cases", [self._golden_to_row(case)], "id")

    def list_rows(self, record_type: str, source: str | None = None, page_size: int = 500) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        if record_type == "qb_dataset":
            return self._select_all("datasets", page_size=page_size, order="created_at.asc")
        if record_type == "qb_snapshot_bundle":
            return self._snapshot_bundle_rows(source or "", page_size=page_size)
        if record_type == "qb_backtest_run":
            return self._select_all("backtest_runs", page_size=page_size, order="created_at.asc")
        if record_type == "qb_optimization_run":
            return self._select_all("optimization_runs", page_size=page_size, order="created_at.asc")
        if record_type == "qb_golden_case":
            return self._select_all("golden_ranktrend_cases", page_size=page_size, order="created_at.asc")
        return []

    def get_row(self, record_type: str, display_key: str, source: str | None = None) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        if record_type == "qb_dataset":
            return self._get_single("datasets", {"id": f"eq.{display_key}"})
        if record_type == "qb_snapshot_bundle":
            rows = self._snapshot_bundle_rows(source or "", snapshot_id=display_key)
            return rows[0] if rows else None
        if record_type == "qb_backtest_run":
            return self._get_single("backtest_runs", {"id": f"eq.{display_key}"})
        if record_type == "qb_optimization_run":
            return self._get_single("optimization_runs", {"id": f"eq.{display_key}"})
        if record_type == "qb_golden_case":
            return self._get_single("golden_ranktrend_cases", {"id": f"eq.{display_key}"})
        if record_type == "qb_smoke":
            return self._get_single("sync_outbox", {"idempotency_key": f"eq.{display_key}"})
        return None

    def dataset_from_row(self, row: dict[str, Any]) -> Dataset:
        payload = self._dataset_row_payload(row)
        return Dataset(
            id=str(payload.get("id") or row.get("id") or row.get("display_key") or ""),
            name=str(payload.get("name") or row.get("name") or row.get("display_key") or ""),
            source_type=str(payload.get("source_type") or row.get("source_type") or "supabase_backup"),
            source_path=str(payload.get("source_path") or row.get("source_path") or ""),
            db_name=str(payload.get("db_name") or row.get("db_name") or "DragonBoardData"),
            schema_fingerprint=str(payload.get("schema_fingerprint") or row.get("schema_fingerprint") or ""),
            snapshot_count=int(payload.get("snapshot_count") or row.get("snapshot_count") or 0),
            frame_count=int(payload.get("frame_count") or row.get("frame_count") or 0),
            stock_row_count=int(payload.get("stock_row_count") or row.get("stock_row_count") or 0),
            sector_row_count=int(payload.get("sector_row_count") or row.get("sector_row_count") or 0),
            start_date=payload.get("start_date") or row.get("start_date"),
            end_date=payload.get("end_date") or row.get("end_date"),
            snapshot_types_json=str(
                payload.get("snapshot_types_json")
                or row.get("snapshot_types_json")
                or json_dumps(payload.get("snapshot_types") or [])
            ),
            metadata_json=str(
                payload.get("metadata_json") or row.get("metadata_json") or json_dumps(payload.get("metadata") or {})
            ),
            created_at=_parse_datetime(payload.get("created_at") or row.get("created_at")),
        )

    def backtest_run_from_row(self, row: dict[str, Any]) -> BacktestRun:
        payload = self._record_row_payload(row)
        return BacktestRun(
            id=str(payload.get("id") or row.get("id") or row.get("display_key") or ""),
            dataset_id=str(payload.get("dataset_id") or row.get("dataset_id") or ""),
            strategy_name=str(payload.get("strategy_name") or row.get("strategy_name") or "rank_trend_candidate"),
            strategy_version=str(payload.get("strategy_version") or row.get("strategy_version") or "0.1.0"),
            snapshot_type=str(payload.get("snapshot_type") or row.get("snapshot_type") or "half_hour"),
            config_hash=str(payload.get("config_hash") or row.get("config_hash") or ""),
            random_seed=int(payload.get("random_seed") or row.get("random_seed") or 0),
            status=str(payload.get("status") or row.get("status") or "completed"),
            request_json=_decode_backup_text(payload.get("request_json") or row.get("request_json") or "{}"),
            result_json=_decode_backup_text(payload.get("result_json") or row.get("result_json") or "{}"),
            created_at=_parse_datetime(payload.get("created_at") or row.get("created_at")),
        )

    def optimization_run_from_row(self, row: dict[str, Any]) -> OptimizationRun:
        payload = self._record_row_payload(row)
        return OptimizationRun(
            id=str(payload.get("id") or row.get("id") or row.get("display_key") or ""),
            dataset_id=str(payload.get("dataset_id") or row.get("dataset_id") or ""),
            strategy_name=str(payload.get("strategy_name") or row.get("strategy_name") or "rank_trend_candidate"),
            method=str(payload.get("method") or row.get("method") or "grid"),
            config_hash=str(payload.get("config_hash") or row.get("config_hash") or ""),
            random_seed=int(payload.get("random_seed") or row.get("random_seed") or 0),
            status=str(payload.get("status") or row.get("status") or "completed"),
            request_json=_decode_backup_text(payload.get("request_json") or row.get("request_json") or "{}"),
            result_json=_decode_backup_text(payload.get("result_json") or row.get("result_json") or "{}"),
            created_at=_parse_datetime(payload.get("created_at") or row.get("created_at")),
        )

    def golden_case_from_row(self, row: dict[str, Any]) -> GoldenRankTrendCase:
        payload = self._record_row_payload(row)
        return GoldenRankTrendCase(
            id=str(payload.get("id") or row.get("id") or row.get("display_key") or ""),
            name=str(payload.get("name") or row.get("name") or row.get("display_key") or ""),
            dataset_id=payload.get("dataset_id") or row.get("dataset_id"),
            input_json=_decode_backup_text(payload.get("input_json") or row.get("input_json") or "{}"),
            expected_json=_decode_backup_text(payload.get("expected_json") or row.get("expected_json") or "{}"),
            created_at=_parse_datetime(payload.get("created_at") or row.get("created_at")),
        )

    def frames_from_rows(
        self,
        rows: list[dict[str, Any]],
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        include_payload: bool = True,
    ) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = []
        for row in sorted(rows, key=lambda item: int(item.get("timestamp") or 0)):
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            frame = payload.get("frame") if isinstance(payload.get("frame"), dict) else {}
            if not frame:
                continue
            if str(frame.get("type") or row.get("type") or "") != snapshot_type:
                continue
            trading_date = str(frame.get("tradingDate") or row.get("trading_date") or "")
            if start_date and trading_date < start_date:
                continue
            if end_date and trading_date > end_date:
                continue
            stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
            frame_item = self._frame_bundle_to_read_dict(frame)
            frame_item["stocks"] = [
                self._stock_bundle_to_read_dict(stock, include_payload=include_payload)
                for stock in stocks
                if isinstance(stock, dict)
            ]
            frames.append(frame_item)
        return frames

    def _snapshot_bundle_rows(
        self,
        dataset_id: str,
        *,
        snapshot_id: str | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        if not dataset_id:
            return []
        filters = {"dataset_id": f"eq.{dataset_id}"}
        if snapshot_id:
            filters["snapshot_id"] = f"eq.{snapshot_id}"
        records = self._select_all("snapshot_records", filters=filters, page_size=page_size, order="timestamp.asc")
        frames = self._select_all("snapshot_frames", filters=filters, page_size=page_size, order="timestamp.asc")
        stocks = self._select_all("snapshot_stock_rows", filters=filters, page_size=page_size, order="timestamp.asc,rank.asc")
        sectors = self._select_all("snapshot_sector_rows", filters=filters, page_size=page_size, order="timestamp.asc,rank.asc")

        records_by_snapshot = {str(row.get("snapshot_id") or ""): self._record_from_row(row) for row in records}
        stocks_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in stocks:
            stocks_by_snapshot[str(row.get("snapshot_id") or "")].append(self._stock_from_row(row))
        sectors_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in sectors:
            sectors_by_snapshot[str(row.get("snapshot_id") or "")].append(self._sector_from_row(row))

        bundle_rows: list[dict[str, Any]] = []
        for row in frames:
            frame = self._frame_from_row(row)
            sid = str(frame.get("snapshotId") or "")
            bundle_rows.append(
                {
                    "display_key": sid,
                    "source": dataset_id,
                    "type": frame.get("type"),
                    "trading_date": frame.get("tradingDate"),
                    "slot_time": frame.get("slotTime"),
                    "timestamp": frame.get("timestamp") or 0,
                    "payload": {
                        "datasetId": dataset_id,
                        "snapshotId": sid,
                        "record": records_by_snapshot.get(sid),
                        "frame": frame,
                        "stocks": stocks_by_snapshot.get(sid, []),
                        "sectors": sectors_by_snapshot.get(sid, []),
                    },
                }
            )
        return bundle_rows

    def _select_all(
        self,
        table: str,
        *,
        filters: dict[str, Any] | None = None,
        page_size: int = 500,
        order: str = "id.asc",
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            params: dict[str, Any] = {"select": "*", "order": order, "limit": str(page_size), "offset": str(offset)}
            if filters:
                params.update(filters)
            ok, payload = self._request_json("GET", f"/rest/v1/{table}", params=params)
            if not ok or not isinstance(payload, list) or not payload:
                break
            rows.extend([item for item in payload if isinstance(item, dict)])
            if len(payload) < page_size:
                break
            offset += page_size
        return rows

    def _get_single(self, table: str, filters: dict[str, Any]) -> dict[str, Any] | None:
        params = {"select": "*", "limit": "1", **filters}
        ok, payload = self._request_json("GET", f"/rest/v1/{table}", params=params)
        if not ok or not isinstance(payload, list) or not payload:
            return None
        row = payload[0]
        return row if isinstance(row, dict) else None

    def _delete_rows(self, table: str, filters: dict[str, Any]) -> bool:
        ok, _ = self._request_json("DELETE", f"/rest/v1/{table}", params=filters, prefer="return=minimal")
        return ok

    def _upsert_rows(self, table: str, rows: list[dict[str, Any]], on_conflict: str) -> bool:
        if not self.enabled:
            return False
        if not rows:
            self.last_error = None
            return True
        for chunk in _chunk_rows_by_payload_size(rows, UPSERT_CHUNK_SIZE, UPSERT_CHUNK_BYTES):
            ok, _ = self._request_json(
                "POST",
                f"/rest/v1/{table}",
                params={"on_conflict": on_conflict},
                payload=chunk,
                prefer="resolution=merge-duplicates,return=minimal",
            )
            if not ok:
                return False
        return True

    def _reset_client(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any | None = None,
        prefer: str = "return=representation",
    ) -> tuple[bool, Any | None]:
        if not self.enabled:
            return False, None
        headers = {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
            "User-Agent": "dragon-board-quant-board-backup/2.0",
        }
        for attempt in range(REQUEST_RETRY_COUNT + 1):
            try:
                if self._client is None:
                    self._client = httpx.Client(
                        base_url=self.supabase_url,
                        timeout=httpx.Timeout(self.timeout_seconds, connect=min(10.0, self.timeout_seconds)),
                        headers=headers,
                        follow_redirects=True,
                    )
                response = self._client.request(method, path, params=params, json=payload, headers={"Prefer": prefer})
                response.raise_for_status()
                if not response.content:
                    self.last_error = None
                    return True, None
                self.last_error = None
                return True, response.json()
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else 0
                body = exc.response.text[:1000] if exc.response is not None else ""
                self.last_error = f"{status_code} {exc.response.request.method} {exc.response.url}: {body}"
                if status_code in TRANSIENT_STATUS_CODES and attempt < REQUEST_RETRY_COUNT:
                    self._reset_client()
                    time.sleep(0.75 * (attempt + 1))
                    continue
                return False, None
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                self.last_error = str(exc)
                if attempt < REQUEST_RETRY_COUNT:
                    self._reset_client()
                    time.sleep(0.75 * (attempt + 1))
                    continue
                return False, None
            except Exception as exc:
                self.last_error = str(exc)
                return False, None
        return False, None

    @staticmethod
    def _dataset_to_row(dataset: Dataset) -> dict[str, Any]:
        return {
            "id": dataset.id,
            "name": dataset.name,
            "source_type": dataset.source_type,
            "source_path": dataset.source_path,
            "db_name": dataset.db_name,
            "schema_fingerprint": dataset.schema_fingerprint,
            "snapshot_count": dataset.snapshot_count,
            "frame_count": dataset.frame_count,
            "stock_row_count": dataset.stock_row_count,
            "sector_row_count": dataset.sector_row_count,
            "start_date": dataset.start_date,
            "end_date": dataset.end_date,
            "snapshot_types_json": dataset.snapshot_types_json,
            "metadata_json": dataset.metadata_json,
            "created_at": _datetime_to_iso(dataset.created_at),
        }

    @staticmethod
    def _record_to_row(dataset_id: str, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "dataset_id": dataset_id,
            "snapshot_id": str(item.get("id") or item.get("snapshotId") or ""),
            "type": str(item.get("type") or ""),
            "trading_date": str(item.get("tradingDate") or item.get("trading_date") or ""),
            "slot_time": str(item.get("slotTime") or item.get("slot_time") or ""),
            "timestamp": _int(item.get("timestamp")),
            "display_key": str(item.get("displayKey") or item.get("display_key") or item.get("id") or item.get("snapshotId") or ""),
            "capture_mode": str(item.get("captureMode") or item.get("capture_mode") or "real_time"),
            "source": str(item.get("source") or "browser_runtime"),
            "payload_json": json_dumps(item.get("payload") if isinstance(item.get("payload"), dict) else item),
        }

    @staticmethod
    def _frame_to_row(dataset_id: str, item: dict[str, Any]) -> dict[str, Any]:
        context = {
            "marketStats": item.get("marketStats"),
            "sentiment": item.get("sentiment"),
            "moneyFlow": item.get("moneyFlow"),
            "indices": item.get("indices"),
            "limitSummary": item.get("limitSummary"),
            "rotationSummary": item.get("rotationSummary"),
            "payload": item.get("payload"),
        }
        if isinstance(item.get("marketContext"), dict):
            context.update(item["marketContext"])
        return {
            "dataset_id": dataset_id,
            "snapshot_id": str(item.get("snapshotId") or item.get("snapshot_id") or item.get("id") or ""),
            "type": str(item.get("type") or ""),
            "trading_date": str(item.get("tradingDate") or item.get("trading_date") or ""),
            "slot_time": str(item.get("slotTime") or item.get("slot_time") or ""),
            "timestamp": _int(item.get("timestamp")),
            "capture_mode": str(item.get("captureMode") or item.get("capture_mode") or "real_time"),
            "source": str(item.get("source") or "browser_runtime"),
            "market_context_json": json_dumps(context),
            "stock_row_count": _int(item.get("stockRowCount") or item.get("stock_row_count")),
            "sector_row_count": _int(item.get("sectorRowCount") or item.get("sector_row_count")),
        }

    @staticmethod
    def _stock_to_row(dataset_id: str, item: dict[str, Any]) -> dict[str, Any]:
        row_id = str(item.get("id") or item.get("rowId") or item.get("row_id") or f"{item.get('snapshotId') or item.get('snapshot_id')}:{item.get('code')}")
        return {
            "dataset_id": dataset_id,
            "row_id": row_id,
            "snapshot_id": str(item.get("snapshotId") or item.get("snapshot_id") or ""),
            "type": str(item.get("type") or ""),
            "trading_date": str(item.get("tradingDate") or item.get("trading_date") or ""),
            "slot_time": str(item.get("slotTime") or item.get("slot_time") or ""),
            "timestamp": _int(item.get("timestamp")),
            "capture_mode": str(item.get("captureMode") or item.get("capture_mode") or "real_time"),
            "code": str(item.get("code") or ""),
            "name": str(item.get("name") or item.get("code") or ""),
            "rank": _int(item.get("rank") or item.get("compRank")),
            "price": _float(item.get("price")),
            "change": _float(item.get("change")),
            "volume_ratio": _float(item.get("volumeRatio") or item.get("volume_ratio")),
            "zlje": _float(item.get("zlje")),
            "zljzb": _float(item.get("zljzb")),
            "turnover": _float(item.get("turnover")),
            "turnover_rate": _float(item.get("turnoverRate") or item.get("turnover_rate")),
            "payload_json": json_dumps(item),
        }

    @staticmethod
    def _sector_to_row(dataset_id: str, item: dict[str, Any]) -> dict[str, Any]:
        entity_type = str(item.get("entityType") or item.get("entity_type") or item.get("sectorType") or item.get("sector_type") or "")
        entity_key = str(item.get("entityKey") or item.get("entity_key") or item.get("sectorCode") or item.get("sector_code") or "")
        row_id = str(item.get("id") or item.get("rowId") or item.get("row_id") or f"{item.get('snapshotId') or item.get('snapshot_id')}:{entity_type}:{entity_key}")
        return {
            "dataset_id": dataset_id,
            "row_id": row_id,
            "snapshot_id": str(item.get("snapshotId") or item.get("snapshot_id") or ""),
            "type": str(item.get("type") or ""),
            "trading_date": str(item.get("tradingDate") or item.get("trading_date") or ""),
            "slot_time": str(item.get("slotTime") or item.get("slot_time") or ""),
            "timestamp": _int(item.get("timestamp")),
            "entity_type": entity_type,
            "entity_key": entity_key,
            "entity_name": str(item.get("entityName") or item.get("entity_name") or item.get("sectorName") or item.get("sector_name") or ""),
            "rank": _int(item.get("rank")),
            "payload_json": json_dumps(item),
        }

    @staticmethod
    def _backtest_to_row(run: BacktestRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "dataset_id": run.dataset_id,
            "strategy_name": run.strategy_name,
            "strategy_version": run.strategy_version,
            "snapshot_type": run.snapshot_type,
            "config_hash": run.config_hash,
            "random_seed": run.random_seed,
            "status": run.status,
            "request_json": _encode_backup_text(run.request_json),
            "result_json": _encode_backup_text(run.result_json),
            "created_at": _datetime_to_iso(run.created_at),
        }

    @staticmethod
    def _optimization_to_row(run: OptimizationRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "dataset_id": run.dataset_id,
            "strategy_name": run.strategy_name,
            "method": run.method,
            "config_hash": run.config_hash,
            "random_seed": run.random_seed,
            "status": run.status,
            "request_json": _encode_backup_text(run.request_json),
            "result_json": _encode_backup_text(run.result_json),
            "created_at": _datetime_to_iso(run.created_at),
        }

    @staticmethod
    def _golden_to_row(case: GoldenRankTrendCase) -> dict[str, Any]:
        return {
            "id": case.id,
            "name": case.name,
            "dataset_id": case.dataset_id,
            "input_json": _encode_backup_text(case.input_json),
            "expected_json": _encode_backup_text(case.expected_json),
            "created_at": _datetime_to_iso(case.created_at),
        }

    @staticmethod
    def _record_from_row(row: dict[str, Any]) -> dict[str, Any]:
        payload = json_loads(str(row.get("payload_json") or ""), {})
        payload = dict(payload) if isinstance(payload, dict) else {}
        payload.update(
            {
                "id": row.get("snapshot_id"),
                "snapshotId": row.get("snapshot_id"),
                "type": row.get("type"),
                "tradingDate": row.get("trading_date"),
                "slotTime": row.get("slot_time"),
                "timestamp": _int(row.get("timestamp")),
                "displayKey": row.get("display_key"),
                "captureMode": row.get("capture_mode"),
                "source": row.get("source"),
            }
        )
        return payload

    @staticmethod
    def _frame_from_row(row: dict[str, Any]) -> dict[str, Any]:
        context = json_loads(str(row.get("market_context_json") or ""), {})
        context = context if isinstance(context, dict) else {}
        return {
            "id": row.get("snapshot_id"),
            "snapshotId": row.get("snapshot_id"),
            "timestamp": _int(row.get("timestamp")),
            "tradingDate": row.get("trading_date"),
            "slotTime": row.get("slot_time"),
            "type": row.get("type"),
            "captureMode": row.get("capture_mode"),
            "source": row.get("source"),
            "marketStats": context.get("marketStats"),
            "sentiment": context.get("sentiment"),
            "moneyFlow": context.get("moneyFlow"),
            "indices": context.get("indices"),
            "limitSummary": context.get("limitSummary"),
            "rotationSummary": context.get("rotationSummary"),
            "payload": context.get("payload"),
            "stockRowCount": _int(row.get("stock_row_count")),
            "sectorRowCount": _int(row.get("sector_row_count")),
        }

    @staticmethod
    def _stock_from_row(row: dict[str, Any]) -> dict[str, Any]:
        payload = json_loads(str(row.get("payload_json") or ""), {})
        payload = dict(payload) if isinstance(payload, dict) else {}
        payload.update(
            {
                "id": row.get("row_id"),
                "rowId": row.get("row_id"),
                "snapshotId": row.get("snapshot_id"),
                "type": row.get("type"),
                "tradingDate": row.get("trading_date"),
                "slotTime": row.get("slot_time"),
                "timestamp": _int(row.get("timestamp")),
                "captureMode": row.get("capture_mode"),
                "code": row.get("code"),
                "name": row.get("name"),
                "rank": _int(row.get("rank")),
                "price": row.get("price"),
                "change": row.get("change"),
                "volumeRatio": row.get("volume_ratio"),
                "zlje": row.get("zlje"),
                "zljzb": row.get("zljzb"),
                "turnover": row.get("turnover"),
                "turnoverRate": row.get("turnover_rate"),
            }
        )
        return payload

    @staticmethod
    def _sector_from_row(row: dict[str, Any]) -> dict[str, Any]:
        payload = json_loads(str(row.get("payload_json") or ""), {})
        payload = dict(payload) if isinstance(payload, dict) else {}
        payload.update(
            {
                "id": row.get("row_id"),
                "rowId": row.get("row_id"),
                "snapshotId": row.get("snapshot_id"),
                "type": row.get("type"),
                "tradingDate": row.get("trading_date"),
                "slotTime": row.get("slot_time"),
                "timestamp": _int(row.get("timestamp")),
                "entityType": row.get("entity_type"),
                "entityKey": row.get("entity_key"),
                "entityName": row.get("entity_name"),
                "rank": _int(row.get("rank")),
            }
        )
        return payload

    @staticmethod
    def _frame_bundle_to_read_dict(frame: dict[str, Any]) -> dict[str, Any]:
        return {
            "snapshotId": frame.get("snapshotId") or frame.get("id"),
            "timestamp": _int(frame.get("timestamp")),
            "tradingDate": frame.get("tradingDate") or "",
            "slotTime": frame.get("slotTime") or "",
            "type": frame.get("type") or "",
            "captureMode": frame.get("captureMode") or "real_time",
            "source": frame.get("source") or "browser_runtime",
            "marketContext": {
                "marketStats": frame.get("marketStats"),
                "sentiment": frame.get("sentiment"),
                "moneyFlow": frame.get("moneyFlow"),
                "indices": frame.get("indices"),
                "limitSummary": frame.get("limitSummary"),
                "rotationSummary": frame.get("rotationSummary"),
                "payload": frame.get("payload"),
            },
            "stocks": [],
        }

    @staticmethod
    def _stock_bundle_to_read_dict(stock: dict[str, Any], include_payload: bool = True) -> dict[str, Any]:
        if include_payload:
            return dict(stock)
        return {
            "code": stock.get("code"),
            "name": stock.get("name"),
            "rank": stock.get("rank"),
            "price": stock.get("price"),
            "change": stock.get("change"),
            "volumeRatio": stock.get("volumeRatio"),
            "zlje": stock.get("zlje"),
            "zljzb": stock.get("zljzb"),
            "turnover": stock.get("turnover"),
            "turnoverRate": stock.get("turnoverRate"),
        }

    @staticmethod
    def _dataset_row_payload(row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        dataset = payload.get("dataset") if isinstance(payload.get("dataset"), dict) else None
        return dataset if isinstance(dataset, dict) else row

    @staticmethod
    def _record_row_payload(row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if isinstance(payload.get("run"), dict):
            return payload["run"]
        if isinstance(payload.get("case"), dict):
            return payload["case"]
        return row


def _chunk_rows(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _chunk_rows_by_payload_size(
    rows: list[dict[str, Any]],
    max_rows: int,
    max_payload_bytes: int,
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 2
    for row in rows:
        row_bytes = len(json_dumps(row).encode("utf-8")) + 1
        if current and (len(current) >= max_rows or current_bytes + row_bytes > max_payload_bytes):
            chunks.append(current)
            current = []
            current_bytes = 2
        current.append(row)
        current_bytes += row_bytes
    if current:
        chunks.append(current)
    return chunks


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
    return datetime.utcnow()


def _datetime_to_iso(value: datetime | None) -> str:
    if not value:
        return utc_now_iso()
    if value.tzinfo is None:
        return value.replace(microsecond=0).isoformat() + "Z"
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _encode_backup_text(value: Any) -> str:
    text = str(value or "")
    raw = text.encode("utf-8")
    if len(raw) < COMPRESSION_THRESHOLD_BYTES or text.startswith(COMPRESSED_TEXT_PREFIX):
        return text
    compressed = gzip.compress(raw, compresslevel=6)
    return COMPRESSED_TEXT_PREFIX + base64.b64encode(compressed).decode("ascii")


def _decode_backup_text(value: Any) -> str:
    text = str(value or "")
    if not text.startswith(COMPRESSED_TEXT_PREFIX):
        return text
    encoded = text[len(COMPRESSED_TEXT_PREFIX) :]
    try:
        return gzip.decompress(base64.b64decode(encoded.encode("ascii"))).decode("utf-8")
    except Exception:
        return text
