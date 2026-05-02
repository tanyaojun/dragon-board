from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from backend.data.models import BacktestRun, Dataset, GoldenRankTrendCase, OptimizationRun
from backend.settings import Settings, get_settings
from backend.utils import json_dumps, json_loads, utc_now_iso

BACKUP_RECORD_TYPE = "daily"
BACKUP_CAPTURE_MODE = "real_time"
ALLOWED_SNAPSHOT_TYPES = {"quarter_hour", "half_hour", "hourly", "daily", "five_minute"}
ALLOWED_CAPTURE_MODES = {"real_time", "delayed", "restored"}


class SupabaseBackupClient:
    """Mirror QuantBoard records into the existing Supabase snapshots table.

    Supabase currently has only the DragonBoard snapshot tables exposed through
    REST. QuantBoard-specific rows therefore use typed payload records in
    snapshots instead of requiring a destructive cloud schema rebuild.
    """

    def __init__(self, supabase_url: str, secret_key: str, timeout_seconds: float = 10.0) -> None:
        self.supabase_url = supabase_url.rstrip("/")
        self.secret_key = secret_key
        self.timeout_seconds = timeout_seconds
        self.enabled = bool(self.supabase_url and self.secret_key)
        self.last_error: str | None = None

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
            return {"configured": False, "connected": False, "last_error": None}
        ok, _ = self._request_json("GET", "/rest/v1/snapshots", params={"select": "id", "limit": "1"})
        return {"configured": True, "connected": ok, "last_error": self.last_error}

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
        display_key = f"qb_smoke_{uuid4().hex}"
        row = {
            "type": BACKUP_RECORD_TYPE,
            "trading_date": datetime.utcnow().strftime("%Y-%m-%d"),
            "slot_time": "",
            "timestamp": _datetime_to_millis(datetime.utcnow()),
            "display_key": display_key,
            "capture_mode": BACKUP_CAPTURE_MODE,
            "source": "quant_board_smoke",
            "quality_flags": {"kind": "qb_smoke"},
            "payload": {"displayKey": display_key, "createdAt": utc_now_iso()},
        }
        write_ok, _ = self._request_json("POST", "/rest/v1/snapshots", payload=[row])
        read_ok = False
        cleanup_ok = False
        if write_ok:
            found = self.get_row("qb_smoke", display_key, source="quant_board_smoke")
            read_ok = bool(found and found.get("display_key") == display_key)
        if write_ok:
            cleanup_ok, _ = self._request_json(
                "DELETE",
                "/rest/v1/snapshots",
                params={
                    "quality_flags->>kind": "eq.qb_smoke",
                    "source": "eq.quant_board_smoke",
                    "display_key": f"eq.{display_key}",
                },
            )
        return {
            "ok": bool(write_ok and read_ok and cleanup_ok),
            "configured": True,
            "connected": bool(write_ok or read_ok),
            "write": write_ok,
            "read": read_ok,
            "cleanup": cleanup_ok,
            "display_key": display_key,
            "last_error": self.last_error,
        }

    def list_rows(self, record_type: str, source: str | None = None, page_size: int = 500) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            params: dict[str, Any] = {
                "select": "*",
                "quality_flags->>kind": f"eq.{record_type}",
                "order": "id.asc",
                "limit": str(page_size),
                "offset": str(offset),
            }
            if source is not None:
                params["source"] = f"eq.{source}"
            ok, payload = self._request_json("GET", "/rest/v1/snapshots", params=params)
            if not ok or not isinstance(payload, list) or not payload:
                break
            rows.extend([item for item in payload if isinstance(item, dict)])
            if len(payload) < page_size:
                break
            offset += page_size
        return rows

    def get_row(self, record_type: str, display_key: str, source: str | None = None) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        params: dict[str, Any] = {
            "select": "*",
            "quality_flags->>kind": f"eq.{record_type}",
            "display_key": f"eq.{display_key}",
            "order": "id.desc",
            "limit": "1",
        }
        if source is not None:
            params["source"] = f"eq.{source}"
        ok, payload = self._request_json("GET", "/rest/v1/snapshots", params=params)
        if not ok or not isinstance(payload, list) or not payload:
            return None
        row = payload[0]
        return row if isinstance(row, dict) else None

    def replace_rows(self, record_type: str, source: str, rows: list[dict[str, Any]], display_key: str | None = None) -> bool:
        if not self.enabled:
            return False
        delete_params: dict[str, Any] = {
            "quality_flags->>kind": f"eq.{record_type}",
            "source": f"eq.{source}",
        }
        if display_key is not None:
            delete_params["display_key"] = f"eq.{display_key}"
        ok, _ = self._request_json("DELETE", "/rest/v1/snapshots", params=delete_params)
        if not ok:
            return False
        if not rows:
            return True
        normalized_rows = [self._normalize_backup_row(record_type, row) for row in rows]
        for chunk in _chunk_rows(normalized_rows, 100):
            ok, _ = self._request_json("POST", "/rest/v1/snapshots", payload=chunk)
            if not ok:
                return False
        return True

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
        dataset_payload = self._dataset_payload(dataset)
        summary = {
            "kind": "dataset",
            "recordCount": len(records),
            "frameCount": len(frames),
            "stockRowCount": len(stock_rows),
            "sectorRowCount": len(sector_rows),
        }
        manifest_row = {
            "type": BACKUP_RECORD_TYPE,
            "trading_date": dataset.start_date or dataset.end_date or "",
            "slot_time": "",
            "timestamp": _datetime_to_millis(dataset.created_at),
            "display_key": dataset.id,
            "capture_mode": BACKUP_CAPTURE_MODE,
            "source": dataset.id,
            "quality_flags": summary,
            "payload": {"dataset": dataset_payload, "summary": summary},
        }
        frames_by_snapshot: dict[str, dict[str, Any]] = {
            str(frame.get("snapshotId") or frame.get("id") or ""): frame
            for frame in frames
            if isinstance(frame, dict)
        }
        records_by_snapshot: dict[str, dict[str, Any]] = {
            str(record.get("id") or record.get("snapshotId") or ""): record
            for record in records
            if isinstance(record, dict)
        }
        stocks_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in stock_rows:
            if not isinstance(row, dict):
                continue
            snapshot_id = str(row.get("snapshotId") or row.get("snapshot_id") or "")
            if snapshot_id:
                stocks_by_snapshot[snapshot_id].append(row)
        sectors_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in sector_rows:
            if not isinstance(row, dict):
                continue
            snapshot_id = str(row.get("snapshotId") or row.get("snapshot_id") or "")
            if snapshot_id:
                sectors_by_snapshot[snapshot_id].append(row)

        bundle_rows: list[dict[str, Any]] = []
        for frame in sorted(frames, key=lambda item: int(item.get("timestamp") or 0) if isinstance(item, dict) else 0):
            if not isinstance(frame, dict):
                continue
            snapshot_id = str(frame.get("snapshotId") or frame.get("id") or "")
            if not snapshot_id:
                continue
            bundled_frame = frames_by_snapshot.get(snapshot_id, frame)
            row = {
                "type": _backup_snapshot_type(str(bundled_frame.get("type") or "")),
                "trading_date": str(bundled_frame.get("tradingDate") or ""),
                "slot_time": str(bundled_frame.get("slotTime") or ""),
                "timestamp": int(bundled_frame.get("timestamp") or 0),
                "display_key": snapshot_id,
                "capture_mode": _backup_capture_mode(str(bundled_frame.get("captureMode") or "")),
                "source": dataset.id,
                "quality_flags": {
                    "kind": "snapshot_bundle",
                    "dataset_id": dataset.id,
                    "snapshot_id": snapshot_id,
                    "stock_count": len(stocks_by_snapshot.get(snapshot_id, [])),
                    "sector_count": len(sectors_by_snapshot.get(snapshot_id, [])),
                },
                "payload": {
                    "datasetId": dataset.id,
                    "snapshotId": snapshot_id,
                    "record": records_by_snapshot.get(snapshot_id),
                    "frame": bundled_frame,
                    "stocks": stocks_by_snapshot.get(snapshot_id, []),
                    "sectors": sectors_by_snapshot.get(snapshot_id, []),
                },
            }
            bundle_rows.append(row)

        if not self.replace_rows("qb_dataset", dataset.id, [manifest_row], display_key=dataset.id):
            return False
        return self.replace_rows("qb_snapshot_bundle", dataset.id, bundle_rows)

    def mirror_backtest_run(self, run: BacktestRun) -> bool:
        if not self.enabled:
            return False
        payload = self._backtest_payload(run)
        row = {
            "type": BACKUP_RECORD_TYPE,
            "trading_date": "",
            "slot_time": "",
            "timestamp": _datetime_to_millis(run.created_at),
            "display_key": run.id,
            "capture_mode": BACKUP_CAPTURE_MODE,
            "source": run.dataset_id,
            "quality_flags": {"kind": "backtest_run", "dataset_id": run.dataset_id},
            "payload": {"run": payload},
        }
        return self.replace_rows("qb_backtest_run", run.dataset_id, [row], display_key=run.id)

    def mirror_optimization_run(self, run: OptimizationRun) -> bool:
        if not self.enabled:
            return False
        payload = self._optimization_payload(run)
        row = {
            "type": BACKUP_RECORD_TYPE,
            "trading_date": "",
            "slot_time": "",
            "timestamp": _datetime_to_millis(run.created_at),
            "display_key": run.id,
            "capture_mode": BACKUP_CAPTURE_MODE,
            "source": run.dataset_id,
            "quality_flags": {"kind": "optimization_run", "dataset_id": run.dataset_id},
            "payload": {"run": payload},
        }
        return self.replace_rows("qb_optimization_run", run.dataset_id, [row], display_key=run.id)

    def mirror_golden_case(self, case: GoldenRankTrendCase) -> bool:
        if not self.enabled:
            return False
        payload = self._golden_payload(case)
        source = str(case.dataset_id or "")
        row = {
            "type": BACKUP_RECORD_TYPE,
            "trading_date": "",
            "slot_time": "",
            "timestamp": _datetime_to_millis(case.created_at),
            "display_key": case.id,
            "capture_mode": BACKUP_CAPTURE_MODE,
            "source": source,
            "quality_flags": {"kind": "golden_case", "dataset_id": case.dataset_id},
            "payload": {"case": payload},
        }
        return self.replace_rows("qb_golden_case", source, [row], display_key=case.id)

    def dataset_from_row(self, row: dict[str, Any]) -> Dataset:
        dataset_payload = self._dataset_row_payload(row)
        return Dataset(
            id=str(dataset_payload.get("id") or row.get("display_key") or ""),
            name=str(dataset_payload.get("name") or row.get("display_key") or ""),
            source_type=str(dataset_payload.get("source_type") or "supabase_backup"),
            source_path=str(dataset_payload.get("source_path") or ""),
            db_name=str(dataset_payload.get("db_name") or "DragonBoardData"),
            schema_fingerprint=str(dataset_payload.get("schema_fingerprint") or ""),
            snapshot_count=int(dataset_payload.get("snapshot_count") or 0),
            frame_count=int(dataset_payload.get("frame_count") or 0),
            stock_row_count=int(dataset_payload.get("stock_row_count") or 0),
            sector_row_count=int(dataset_payload.get("sector_row_count") or 0),
            start_date=dataset_payload.get("start_date"),
            end_date=dataset_payload.get("end_date"),
            snapshot_types_json=json_dumps(dataset_payload.get("snapshot_types") or []),
            metadata_json=json_dumps(dataset_payload.get("metadata") or {}),
            created_at=_parse_datetime(dataset_payload.get("created_at") or row.get("created_at")),
        )

    def backtest_run_from_row(self, row: dict[str, Any]) -> BacktestRun:
        payload = self._record_row_payload(row)
        return BacktestRun(
            id=str(payload.get("id") or row.get("display_key") or ""),
            dataset_id=str(payload.get("dataset_id") or ""),
            strategy_name=str(payload.get("strategy_name") or "rank_trend_candidate"),
            strategy_version=str(payload.get("strategy_version") or "0.1.0"),
            snapshot_type=str(payload.get("snapshot_type") or "half_hour"),
            config_hash=str(payload.get("config_hash") or ""),
            random_seed=int(payload.get("random_seed") or 0),
            status=str(payload.get("status") or "completed"),
            request_json=str(payload.get("request_json") or "{}"),
            result_json=str(payload.get("result_json") or "{}"),
            created_at=_parse_datetime(payload.get("created_at") or row.get("created_at")),
        )

    def optimization_run_from_row(self, row: dict[str, Any]) -> OptimizationRun:
        payload = self._record_row_payload(row)
        return OptimizationRun(
            id=str(payload.get("id") or row.get("display_key") or ""),
            dataset_id=str(payload.get("dataset_id") or ""),
            strategy_name=str(payload.get("strategy_name") or "rank_trend_candidate"),
            method=str(payload.get("method") or "grid"),
            config_hash=str(payload.get("config_hash") or ""),
            random_seed=int(payload.get("random_seed") or 0),
            status=str(payload.get("status") or "completed"),
            request_json=str(payload.get("request_json") or "{}"),
            result_json=str(payload.get("result_json") or "{}"),
            created_at=_parse_datetime(payload.get("created_at") or row.get("created_at")),
        )

    def golden_case_from_row(self, row: dict[str, Any]) -> GoldenRankTrendCase:
        payload = self._record_row_payload(row)
        return GoldenRankTrendCase(
            id=str(payload.get("id") or row.get("display_key") or ""),
            name=str(payload.get("name") or row.get("display_key") or ""),
            dataset_id=payload.get("dataset_id"),
            input_json=str(payload.get("input_json") or "{}"),
            expected_json=str(payload.get("expected_json") or "{}"),
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
            frame_item = self._frame_to_dict(frame)
            frame_item["stocks"] = [self._stock_to_dict(stock, include_payload=include_payload) for stock in stocks if isinstance(stock, dict)]
            frames.append(frame_item)
        return frames

    @staticmethod
    def _frame_to_dict(frame: dict[str, Any]) -> dict[str, Any]:
        return {
            "snapshotId": frame.get("snapshotId") or frame.get("id"),
            "timestamp": int(frame.get("timestamp") or 0),
            "tradingDate": frame.get("tradingDate") or "",
            "slotTime": frame.get("slotTime") or "",
            "type": frame.get("type") or "",
            "captureMode": frame.get("captureMode") or "real_time",
            "source": frame.get("source") or "browser_runtime",
            "marketContext": frame.get("marketContext") or {},
            "stocks": [],
        }

    @staticmethod
    def _stock_to_dict(stock: dict[str, Any], include_payload: bool = True) -> dict[str, Any]:
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
    def _dataset_payload(dataset: Dataset) -> dict[str, Any]:
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
            "snapshot_types": json_loads(dataset.snapshot_types_json, []),
            "metadata": json_loads(dataset.metadata_json, {}),
            "created_at": dataset.created_at.isoformat() if dataset.created_at else utc_now_iso(),
        }

    @staticmethod
    def _backtest_payload(run: BacktestRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "dataset_id": run.dataset_id,
            "strategy_name": run.strategy_name,
            "strategy_version": run.strategy_version,
            "snapshot_type": run.snapshot_type,
            "config_hash": run.config_hash,
            "random_seed": run.random_seed,
            "status": run.status,
            "request_json": run.request_json,
            "result_json": run.result_json,
            "created_at": run.created_at.isoformat() if run.created_at else utc_now_iso(),
        }

    @staticmethod
    def _optimization_payload(run: OptimizationRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "dataset_id": run.dataset_id,
            "strategy_name": run.strategy_name,
            "method": run.method,
            "config_hash": run.config_hash,
            "random_seed": run.random_seed,
            "status": run.status,
            "request_json": run.request_json,
            "result_json": run.result_json,
            "created_at": run.created_at.isoformat() if run.created_at else utc_now_iso(),
        }

    @staticmethod
    def _golden_payload(case: GoldenRankTrendCase) -> dict[str, Any]:
        return {
            "id": case.id,
            "name": case.name,
            "dataset_id": case.dataset_id,
            "input_json": case.input_json,
            "expected_json": case.expected_json,
            "created_at": case.created_at.isoformat() if case.created_at else utc_now_iso(),
        }

    @staticmethod
    def _dataset_row_payload(row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        dataset = payload.get("dataset") if isinstance(payload.get("dataset"), dict) else payload
        return dataset if isinstance(dataset, dict) else {}

    @staticmethod
    def _record_row_payload(row: dict[str, Any]) -> dict[str, Any]:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        if isinstance(payload.get("run"), dict):
            return payload["run"]
        if isinstance(payload.get("case"), dict):
            return payload["case"]
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _normalize_backup_row(record_type: str, row: dict[str, Any]) -> dict[str, Any]:
        output = dict(row)
        quality_flags = output.get("quality_flags") if isinstance(output.get("quality_flags"), dict) else {}
        output["quality_flags"] = {**quality_flags, "kind": record_type}
        output["type"] = _backup_snapshot_type(str(output.get("type") or ""))
        output["capture_mode"] = _backup_capture_mode(str(output.get("capture_mode") or ""))
        return output

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any | None = None,
    ) -> tuple[bool, Any | None]:
        if not self.enabled:
            return False, None
        headers = {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
            "User-Agent": "dragon-board-quant-board-backup/1.0",
        }
        try:
            with httpx.Client(base_url=self.supabase_url, timeout=self.timeout_seconds, headers=headers, follow_redirects=True) as client:
                response = client.request(method, path, params=params, json=payload)
                response.raise_for_status()
                if not response.content:
                    return True, None
                return True, response.json()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:1000] if exc.response is not None else ""
            self.last_error = f"{exc.response.status_code} {exc.response.request.method} {exc.response.url}: {body}"
            return False, None
        except Exception as exc:
            self.last_error = str(exc)
            return False, None


def get_backup_client() -> SupabaseBackupClient | None:
    return SupabaseBackupClient.from_settings()


def _chunk_rows(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _backup_snapshot_type(value: str) -> str:
    return value if value in ALLOWED_SNAPSHOT_TYPES else BACKUP_RECORD_TYPE


def _backup_capture_mode(value: str) -> str:
    return value if value in ALLOWED_CAPTURE_MODES else BACKUP_CAPTURE_MODE


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
    return datetime.utcnow()


def _datetime_to_millis(value: datetime | None) -> int:
    if not value:
        return 0
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return int(value.timestamp() * 1000)
