from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import time
from typing import Any
from uuid import uuid4

import httpx

from backend.data.models import Dataset
from backend.settings import Settings, get_settings
from backend.utils import json_dumps, json_loads, utc_now_iso


REQUIRED_TABLES = [
    "datasets",
    "snapshot_records",
    "snapshot_frames",
    "snapshot_stock_rows",
    "snapshot_sector_rows",
    "sync_outbox",
]

COMPRESSED_TEXT_PREFIX = "__qb_gzip_b64__:"
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
UPSERT_CHUNK_SIZE = 100
UPSERT_CHUNK_BYTES = 8 * 1024 * 1024
REQUEST_RETRY_COUNT = 3

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
        "captured_at",
        "data_timestamp",
        "delay_ms",
        "quality_flags_json",
        "source",
    },
    "snapshot_frames": {
        "id",
        "dataset_id",
        "snapshot_id",
        "type",
        "trading_date",
        "slot_time",
        "timestamp",
        "display_key",
        "capture_mode",
        "quality_flags_json",
        "delay_ms",
        "source",
        "metadata_json",
        "market_stats_json",
        "sentiment_json",
        "money_flow_json",
        "indices_json",
        "limit_summary_json",
        "rotation_summary_json",
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
        "source",
        "code",
        "name",
        "rank",
        "comp_rank",
        "platforms",
        "avg_rank",
        "avg_rank_num",
        "price",
        "change",
        "volume",
        "turnover",
        "turnover_rate",
        "total_mv",
        "cir_mv",
        "volume_ratio",
        "zlje",
        "zljzb",
        "cddje",
        "cddjzb",
        "pe",
        "pb",
        "depth10_json",
        "bid1_price",
        "bid1_volume",
        "ask1_price",
        "ask1_volume",
        "spread",
        "bid10_total",
        "ask10_total",
        "depth_imbalance",
        "tick_buy_volume",
        "tick_sell_volume",
        "tick_buy_count",
        "tick_sell_count",
        "last_trade_price",
        "last_trade_volume",
        "speed",
        "lead_status",
        "lead_times",
        "lianban_str",
        "fengdan",
        "max_fengdan",
        "popularity",
        "popularity_change",
        "institution_buy",
        "big_money300",
        "themes_json",
        "is_new",
        "first_zt_time",
        "last_zt_time",
        "board_height",
        "high_days",
        "hotness",
        "main_theme",
        "theme_heat",
        "theme_level",
        "rank_change",
        "direction_signal",
        "direction_confidence",
        "acceleration_signal",
        "acceleration_confidence",
        "cross_signal",
        "cross_confidence",
        "final_signal",
        "final_confidence",
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
        "capture_mode",
        "source",
        "entity_type",
        "entity_key",
        "entity_code",
        "entity_name",
        "rank",
        "strength",
        "heat_score",
        "heat_level",
        "change",
        "main_net_inflow",
        "big_money300",
        "institution_buy",
        "volume_ratio",
        "zt_count",
        "leader_count",
        "persistent_days",
        "net_inflow",
        "metadata_json",
    },
    "sync_outbox": {
        "id",
        "op_type",
        "dataset_id",
        "snapshot_id",
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

        return {
            "configured": True,
            "connected": None,
            "schema": "sqlite_homomorphic",
            "last_error": self.last_error,
            "check": "skipped",
            "message": "fast health check skips Supabase network probe; use /api/health?deep=true for schema validation",
        }

    def deep_health(self) -> dict[str, Any]:
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

    def list_rows(self, record_type: str, source: str | None = None, page_size: int = 500) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        if record_type == "qb_dataset":
            return self._select_all("datasets", page_size=page_size, order="created_at.asc")
        if record_type == "qb_snapshot_bundle":
            return self._snapshot_bundle_rows(source or "", page_size=page_size)
        return []

    def get_row(self, record_type: str, display_key: str, source: str | None = None) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        if record_type == "qb_dataset":
            return self._get_single("datasets", {"id": f"eq.{display_key}"})
        if record_type == "qb_snapshot_bundle":
            rows = self._snapshot_bundle_rows(source or "", snapshot_id=display_key)
            return rows[0] if rows else None
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
            "captured_at": _int(item.get("capturedAt") or item.get("captured_at") or item.get("timestamp")),
            "data_timestamp": _int(item.get("dataTimestamp") or item.get("data_timestamp") or item.get("timestamp")),
            "delay_ms": _int(item.get("delayMs") or item.get("delay_ms")),
            "quality_flags_json": json_dumps(item.get("qualityFlags") if isinstance(item.get("qualityFlags"), list) else []),
            "source": str(item.get("source") or "browser_runtime"),
        }

    @staticmethod
    def _frame_to_row(dataset_id: str, item: dict[str, Any]) -> dict[str, Any]:
        market_context = item.get("marketContext") if isinstance(item.get("marketContext"), dict) else {}
        return {
            "dataset_id": dataset_id,
            "snapshot_id": str(item.get("snapshotId") or item.get("snapshot_id") or item.get("id") or ""),
            "type": str(item.get("type") or ""),
            "trading_date": str(item.get("tradingDate") or item.get("trading_date") or ""),
            "slot_time": str(item.get("slotTime") or item.get("slot_time") or ""),
            "timestamp": _int(item.get("timestamp")),
            "display_key": str(item.get("displayKey") or item.get("display_key") or item.get("snapshotId") or item.get("id") or ""),
            "capture_mode": str(item.get("captureMode") or item.get("capture_mode") or "real_time"),
            "quality_flags_json": json_dumps(item.get("qualityFlags") if isinstance(item.get("qualityFlags"), list) else []),
            "delay_ms": _int(item.get("delayMs") or item.get("delay_ms")),
            "source": str(item.get("source") or "browser_runtime"),
            "metadata_json": json_dumps(item.get("metadata") if isinstance(item.get("metadata"), dict) else market_context.get("metadata") or {}),
            "market_stats_json": json_dumps(item.get("marketStats") if isinstance(item.get("marketStats"), dict) else market_context.get("marketStats") or {}),
            "sentiment_json": json_dumps(item.get("sentiment") if isinstance(item.get("sentiment"), dict) else market_context.get("sentiment") or {}),
            "money_flow_json": json_dumps(item.get("moneyFlow") if isinstance(item.get("moneyFlow"), dict) else market_context.get("moneyFlow") or {}),
            "indices_json": json_dumps(item.get("indices") if isinstance(item.get("indices"), dict) else market_context.get("indices") or {}),
            "limit_summary_json": json_dumps(item.get("limitSummary") if isinstance(item.get("limitSummary"), dict) else market_context.get("limitSummary") or {}),
            "rotation_summary_json": json_dumps(item.get("rotationSummary") if isinstance(item.get("rotationSummary"), dict) else market_context.get("rotationSummary") or {}),
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
            "source": str(item.get("source") or "browser_runtime"),
            "code": str(item.get("code") or ""),
            "name": str(item.get("name") or item.get("code") or ""),
            "rank": _int(item.get("rank") or item.get("compRank")),
            "comp_rank": _int(item.get("compRank") or item.get("comp_rank") or item.get("rank")),
            "platforms": _int(item.get("platforms")),
            "avg_rank": item.get("avgRank") or item.get("avg_rank"),
            "avg_rank_num": _float(item.get("avgRankNum") or item.get("avg_rank_num")),
            "price": _float(item.get("price")),
            "change": _float(item.get("change")),
            "volume": _float(item.get("volume")),
            "turnover": _float(item.get("turnover")),
            "turnover_rate": _float(item.get("turnoverRate") or item.get("turnover_rate")),
            "total_mv": _float(item.get("totalMV") or item.get("total_mv")),
            "cir_mv": _float(item.get("cirMV") or item.get("cir_mv")),
            "volume_ratio": _float(item.get("volumeRatio") or item.get("volume_ratio")),
            "zlje": _float(item.get("zlje")),
            "zljzb": _float(item.get("zljzb")),
            "cddje": _float(item.get("cddje")),
            "cddjzb": _float(item.get("cddjzb")),
            "pe": _float(item.get("pe")),
            "pb": _float(item.get("pb")),
            "depth10_json": json_dumps(item.get("depth10") if isinstance(item.get("depth10"), dict) else {}),
            "bid1_price": _float(item.get("bid1Price") or item.get("bid1_price")),
            "bid1_volume": _float(item.get("bid1Volume") or item.get("bid1_volume")),
            "ask1_price": _float(item.get("ask1Price") or item.get("ask1_price")),
            "ask1_volume": _float(item.get("ask1Volume") or item.get("ask1_volume")),
            "spread": _float(item.get("spread")),
            "bid10_total": _float(item.get("bid10Total") or item.get("bid10_total")),
            "ask10_total": _float(item.get("ask10Total") or item.get("ask10_total")),
            "depth_imbalance": _float(item.get("depthImbalance") or item.get("depth_imbalance")),
            "tick_buy_volume": _float(item.get("tickBuyVolume") or item.get("tick_buy_volume")),
            "tick_sell_volume": _float(item.get("tickSellVolume") or item.get("tick_sell_volume")),
            "tick_buy_count": _maybe_int(item.get("tickBuyCount") or item.get("tick_buy_count")),
            "tick_sell_count": _maybe_int(item.get("tickSellCount") or item.get("tick_sell_count")),
            "last_trade_price": _float(item.get("lastTradePrice") or item.get("last_trade_price")),
            "last_trade_volume": _float(item.get("lastTradeVolume") or item.get("last_trade_volume")),
            "speed": _float(item.get("speed")),
            "lead_status": item.get("leadStatus") or item.get("lead_status"),
            "lead_times": _maybe_int(item.get("leadTimes") or item.get("lead_times")),
            "lianban_str": item.get("lianbanStr") or item.get("lianban_str"),
            "fengdan": _float(item.get("fengdan")),
            "max_fengdan": _float(item.get("maxFengdan") or item.get("max_fengdan")),
            "popularity": _float(item.get("popularity")),
            "popularity_change": _float(item.get("popularityChange") or item.get("popularity_change")),
            "institution_buy": _float(item.get("institutionBuy") or item.get("institution_buy")),
            "big_money300": _float(item.get("bigMoney300") or item.get("big_money300")),
            "themes_json": json_dumps(item.get("themes") if isinstance(item.get("themes"), list) else []),
            "is_new": bool(item.get("isNew") if item.get("isNew") is not None else item.get("is_new") or False),
            "first_zt_time": item.get("firstZtTime") or item.get("first_zt_time"),
            "last_zt_time": item.get("lastZtTime") or item.get("last_zt_time"),
            "board_height": _maybe_int(item.get("boardHeight") or item.get("board_height")),
            "high_days": _maybe_int(item.get("highDays") or item.get("high_days")),
            "hotness": _float(item.get("hotness")),
            "main_theme": item.get("mainTheme") or item.get("main_theme"),
            "theme_heat": _float(item.get("themeHeat") or item.get("theme_heat")),
            "theme_level": item.get("themeLevel") or item.get("theme_level"),
            "rank_change": _float(item.get("rankChange") or item.get("rank_change")),
            "direction_signal": item.get("directionSignal") or item.get("direction_signal"),
            "direction_confidence": _float(item.get("directionConfidence") or item.get("direction_confidence")),
            "acceleration_signal": item.get("accelerationSignal") or item.get("acceleration_signal"),
            "acceleration_confidence": _float(item.get("accelerationConfidence") or item.get("acceleration_confidence")),
            "cross_signal": item.get("crossSignal") or item.get("cross_signal"),
            "cross_confidence": _float(item.get("crossConfidence") or item.get("cross_confidence")),
            "final_signal": item.get("finalSignal") or item.get("final_signal"),
            "final_confidence": _float(item.get("finalConfidence") or item.get("final_confidence")),
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
            "capture_mode": str(item.get("captureMode") or item.get("capture_mode") or "real_time"),
            "source": str(item.get("source") or "browser_runtime"),
            "entity_type": entity_type,
            "entity_key": entity_key,
            "entity_code": item.get("entityCode") or item.get("entity_code") or item.get("sectorCode") or item.get("sector_code"),
            "entity_name": str(item.get("entityName") or item.get("entity_name") or item.get("sectorName") or item.get("sector_name") or ""),
            "rank": _int(item.get("rank")),
            "strength": _float(item.get("strength")),
            "heat_score": _float(item.get("heatScore") or item.get("heat_score")),
            "heat_level": item.get("heatLevel") or item.get("heat_level"),
            "change": _float(item.get("change")),
            "main_net_inflow": _float(item.get("mainNetInflow") or item.get("main_net_inflow")),
            "big_money300": _float(item.get("bigMoney300") or item.get("big_money300")),
            "institution_buy": _float(item.get("institutionBuy") or item.get("institution_buy")),
            "volume_ratio": _float(item.get("volumeRatio") or item.get("volume_ratio")),
            "zt_count": _maybe_int(item.get("ztCount") or item.get("zt_count")),
            "leader_count": _maybe_int(item.get("leaderCount") or item.get("leader_count")),
            "persistent_days": _maybe_int(item.get("persistentDays") or item.get("persistent_days")),
            "net_inflow": _float(item.get("netInflow") or item.get("net_inflow")),
            "metadata_json": json_dumps(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
        }

    @staticmethod
    def _record_from_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("snapshot_id"),
            "snapshotId": row.get("snapshot_id"),
            "type": row.get("type"),
            "tradingDate": row.get("trading_date"),
            "slotTime": row.get("slot_time"),
            "timestamp": _int(row.get("timestamp")),
            "displayKey": row.get("display_key"),
            "captureMode": row.get("capture_mode"),
            "capturedAt": _int(row.get("captured_at")),
            "dataTimestamp": _int(row.get("data_timestamp")),
            "delayMs": _int(row.get("delay_ms")),
            "qualityFlags": json_loads(_maybe_decompress(row.get("quality_flags_json") or "[]"), []),
            "source": row.get("source"),
        }

    @staticmethod
    def _frame_from_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("snapshot_id"),
            "snapshotId": row.get("snapshot_id"),
            "timestamp": _int(row.get("timestamp")),
            "tradingDate": row.get("trading_date"),
            "slotTime": row.get("slot_time"),
            "type": row.get("type"),
            "captureMode": row.get("capture_mode"),
            "source": row.get("source"),
            "displayKey": row.get("display_key"),
            "qualityFlags": json_loads(_maybe_decompress(row.get("quality_flags_json") or "[]"), []),
            "delayMs": _int(row.get("delay_ms")),
            "metadata": json_loads(_maybe_decompress(row.get("metadata_json") or "{}"), {}),
            "marketStats": json_loads(_maybe_decompress(row.get("market_stats_json") or "{}"), {}),
            "sentiment": json_loads(_maybe_decompress(row.get("sentiment_json") or "{}"), {}),
            "moneyFlow": json_loads(_maybe_decompress(row.get("money_flow_json") or "{}"), {}),
            "indices": json_loads(_maybe_decompress(row.get("indices_json") or "{}"), {}),
            "limitSummary": json_loads(_maybe_decompress(row.get("limit_summary_json") or "{}"), {}),
            "rotationSummary": json_loads(_maybe_decompress(row.get("rotation_summary_json") or "{}"), {}),
            "stockRowCount": _int(row.get("stock_row_count")),
            "sectorRowCount": _int(row.get("sector_row_count")),
        }

    @staticmethod
    def _stock_from_row(row: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": row.get("row_id"),
            "rowId": row.get("row_id"),
            "snapshotId": row.get("snapshot_id"),
            "type": row.get("type"),
            "tradingDate": row.get("trading_date"),
            "slotTime": row.get("slot_time"),
            "timestamp": _int(row.get("timestamp")),
            "captureMode": row.get("capture_mode"),
            "source": row.get("source"),
            "code": row.get("code"),
            "name": row.get("name"),
            "rank": _int(row.get("rank")),
            "compRank": _int(row.get("comp_rank")),
            "platforms": _int(row.get("platforms")),
            "avgRank": row.get("avg_rank"),
            "avgRankNum": row.get("avg_rank_num"),
            "price": row.get("price"),
            "change": row.get("change"),
            "volume": row.get("volume"),
            "turnover": row.get("turnover"),
            "turnoverRate": row.get("turnover_rate"),
            "totalMV": row.get("total_mv"),
            "cirMV": row.get("cir_mv"),
            "volumeRatio": row.get("volume_ratio"),
            "zlje": row.get("zlje"),
            "zljzb": row.get("zljzb"),
            "cddje": row.get("cddje"),
            "cddjzb": row.get("cddjzb"),
            "pe": row.get("pe"),
            "pb": row.get("pb"),
            "depth10": json_loads(_maybe_decompress(row.get("depth10_json") or "{}"), {}),
            "bid1Price": row.get("bid1_price"),
            "bid1Volume": row.get("bid1_volume"),
            "ask1Price": row.get("ask1_price"),
            "ask1Volume": row.get("ask1_volume"),
            "spread": row.get("spread"),
            "bid10Total": row.get("bid10_total"),
            "ask10Total": row.get("ask10_total"),
            "depthImbalance": row.get("depth_imbalance"),
            "tickBuyVolume": row.get("tick_buy_volume"),
            "tickSellVolume": row.get("tick_sell_volume"),
            "tickBuyCount": row.get("tick_buy_count"),
            "tickSellCount": row.get("tick_sell_count"),
            "lastTradePrice": row.get("last_trade_price"),
            "lastTradeVolume": row.get("last_trade_volume"),
            "speed": row.get("speed"),
            "leadStatus": row.get("lead_status"),
            "leadTimes": row.get("lead_times"),
            "lianbanStr": row.get("lianban_str"),
            "fengdan": row.get("fengdan"),
            "maxFengdan": row.get("max_fengdan"),
            "popularity": row.get("popularity"),
            "popularityChange": row.get("popularity_change"),
            "institutionBuy": row.get("institution_buy"),
            "bigMoney300": row.get("big_money300"),
            "themes": json_loads(_maybe_decompress(row.get("themes_json") or "[]"), []),
            "isNew": bool(row.get("is_new")),
            "firstZtTime": row.get("first_zt_time"),
            "lastZtTime": row.get("last_zt_time"),
            "boardHeight": row.get("board_height"),
            "highDays": row.get("high_days"),
            "hotness": row.get("hotness"),
            "mainTheme": row.get("main_theme"),
            "themeHeat": row.get("theme_heat"),
            "themeLevel": row.get("theme_level"),
            "rankChange": row.get("rank_change"),
            "directionSignal": row.get("direction_signal"),
            "directionConfidence": row.get("direction_confidence"),
            "accelerationSignal": row.get("acceleration_signal"),
            "accelerationConfidence": row.get("acceleration_confidence"),
            "crossSignal": row.get("cross_signal"),
            "crossConfidence": row.get("cross_confidence"),
            "finalSignal": row.get("final_signal"),
            "finalConfidence": row.get("final_confidence"),
        }
        return {key: value for key, value in item.items() if value is not None}

    @staticmethod
    def _sector_from_row(row: dict[str, Any]) -> dict[str, Any]:
        item = {
            "id": row.get("row_id"),
            "rowId": row.get("row_id"),
            "snapshotId": row.get("snapshot_id"),
            "type": row.get("type"),
            "tradingDate": row.get("trading_date"),
            "slotTime": row.get("slot_time"),
            "timestamp": _int(row.get("timestamp")),
            "captureMode": row.get("capture_mode"),
            "source": row.get("source"),
            "entityType": row.get("entity_type"),
            "entityKey": row.get("entity_key"),
            "entityCode": row.get("entity_code"),
            "entityName": row.get("entity_name"),
            "rank": _int(row.get("rank")),
            "strength": row.get("strength"),
            "heatScore": row.get("heat_score"),
            "heatLevel": row.get("heat_level"),
            "change": row.get("change"),
            "mainNetInflow": row.get("main_net_inflow"),
            "bigMoney300": row.get("big_money300"),
            "institutionBuy": row.get("institution_buy"),
            "volumeRatio": row.get("volume_ratio"),
            "ztCount": row.get("zt_count"),
            "leaderCount": row.get("leader_count"),
            "persistentDays": row.get("persistent_days"),
            "netInflow": row.get("net_inflow"),
            "metadata": json_loads(_maybe_decompress(row.get("metadata_json") or "{}"), {}),
        }
        return {key: value for key, value in item.items() if value is not None}

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
                "metadata": frame.get("metadata"),
                "marketStats": frame.get("marketStats"),
                "sentiment": frame.get("sentiment"),
                "moneyFlow": frame.get("moneyFlow"),
                "indices": frame.get("indices"),
                "limitSummary": frame.get("limitSummary"),
                "rotationSummary": frame.get("rotationSummary"),
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


def _maybe_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _maybe_decompress(value: Any) -> str:
    text = str(value or "")
    if not text.startswith(COMPRESSED_TEXT_PREFIX):
        return text
    encoded = text[len(COMPRESSED_TEXT_PREFIX):]
    try:
        return gzip.decompress(base64.b64decode(encoded.encode("ascii"))).decode("utf-8")
    except Exception:
        return text
