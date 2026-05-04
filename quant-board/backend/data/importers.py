from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from backend.settings import get_settings
from backend.utils import read_json_file, stable_hash, utc_now_iso


VALID_SNAPSHOT_TYPES = {"quarter_hour", "half_hour", "hourly", "daily"}


class ImporterError(RuntimeError):
    pass


class SnapshotBundle:
    def __init__(
        self,
        records: list[dict[str, Any]] | None = None,
        frames: list[dict[str, Any]] | None = None,
        stock_rows: list[dict[str, Any]] | None = None,
        sector_rows: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.records = records or []
        self.frames = frames or []
        self.stock_rows = stock_rows or []
        self.sector_rows = sector_rows or []
        self.metadata = metadata or {}

    def fingerprint(self) -> str:
        return stable_hash(
            {
                "records": len(self.records),
                "frames": len(self.frames),
                "stock_rows": len(self.stock_rows),
                "sector_rows": len(self.sector_rows),
                "first_frame": self.frames[0] if self.frames else None,
                "last_frame": self.frames[-1] if self.frames else None,
            }
        )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            item = json.loads(stripped)
            if isinstance(item, dict):
                rows.append(item)
    return rows


def normalize_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
    snapshot_type = raw.get("type") or payload.get("type")
    trading_date = raw.get("tradingDate") or payload.get("tradingDate")
    timestamp = raw.get("timestamp") or payload.get("timestamp")
    if not snapshot_type or not trading_date or not timestamp:
        return None
    slot_time = raw.get("slotTime") or payload.get("slotTime") or ""
    snapshot_id = raw.get("id") or raw.get("snapshotId") or f"{snapshot_type}:{trading_date}:{slot_time or '00:00'}"
    return {
        "id": str(snapshot_id),
        "type": str(snapshot_type),
        "tradingDate": str(trading_date),
        "slotTime": str(slot_time),
        "timestamp": int(float(timestamp)),
        "displayKey": raw.get("displayKey") or payload.get("displayKey") or str(snapshot_id),
        "captureMode": raw.get("captureMode") or payload.get("captureMode") or "real_time",
        "source": raw.get("source") or payload.get("source") or "browser_runtime",
        "payload": payload,
    }


def frame_from_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload") or {}
    hotlist = payload.get("hotlist") if isinstance(payload.get("hotlist"), list) else []
    sectors = payload.get("sectors") if isinstance(payload.get("sectors"), list) else []
    hot_themes = payload.get("hotThemes") if isinstance(payload.get("hotThemes"), list) else []
    return {
        "id": record["id"],
        "snapshotId": record["id"],
        "type": record["type"],
        "tradingDate": record["tradingDate"],
        "slotTime": record["slotTime"],
        "timestamp": record["timestamp"],
        "displayKey": record.get("displayKey", record["id"]),
        "captureMode": record.get("captureMode", "real_time"),
        "source": record.get("source", "browser_runtime"),
        "marketStats": payload.get("marketStats") or payload.get("market") or payload.get("marketData"),
        "sentiment": payload.get("sentiment") or payload.get("breathData") or payload.get("dragonBreath"),
        "moneyFlow": payload.get("moneyFlow"),
        "indices": payload.get("indices"),
        "limitSummary": payload.get("limitSummary") or payload.get("limitPool"),
        "rotationSummary": payload.get("rotationSummary"),
        "payload": payload,
        "stockRowCount": len(hotlist),
        "sectorRowCount": len(sectors) + len(hot_themes),
    }


def stock_rows_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    payload = record.get("payload") or {}
    hotlist = payload.get("hotlist") if isinstance(payload.get("hotlist"), list) else []
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(hotlist):
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or raw.get("stockCode") or raw.get("securityCode") or "").strip()
        if not code:
            continue
        rank = raw.get("rank") or raw.get("compRank") or index + 1
        item = {
            **raw,
            "id": raw.get("id") or f"{record['id']}:{code}",
            "snapshotId": record["id"],
            "type": record["type"],
            "tradingDate": record["tradingDate"],
            "slotTime": record["slotTime"],
            "timestamp": record["timestamp"],
            "captureMode": record.get("captureMode", "real_time"),
            "source": record.get("source", "browser_runtime"),
            "code": code,
            "name": raw.get("name") or code,
            "rank": int(float(rank)),
        }
        rows.append(item)
    rows.sort(key=lambda item: int(item.get("rank") or 999999))
    return rows


def sector_rows_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    payload = record.get("payload") or {}
    output: list[dict[str, Any]] = []

    def add_rows(values: Any, entity_type: str) -> None:
        if not isinstance(values, list):
            return
        for index, raw in enumerate(values):
            if not isinstance(raw, dict):
                continue
            key = raw.get("entityKey") or raw.get("id") or raw.get("code") or raw.get("name") or f"{entity_type}_{index}"
            output.append(
                {
                    **raw,
                    "id": raw.get("id") or f"{record['id']}:{entity_type}:{key}",
                    "snapshotId": record["id"],
                    "type": record["type"],
                    "tradingDate": record["tradingDate"],
                    "slotTime": record["slotTime"],
                    "timestamp": record["timestamp"],
                    "captureMode": record.get("captureMode", "real_time"),
                    "source": record.get("source", "browser_runtime"),
                    "entityType": raw.get("entityType") or entity_type,
                    "entityKey": str(key),
                    "entityName": raw.get("entityName") or raw.get("name") or str(key),
                    "rank": int(float(raw.get("rank") or index + 1)),
                }
            )

    add_rows(payload.get("sectors"), "sector")
    add_rows(payload.get("hotThemes"), "hot_theme")
    rotation = payload.get("rotationSummary") or {}
    add_rows(rotation.get("mainLines") if isinstance(rotation, dict) else [], "rotation_main_line")
    return output


class JsonBundleImporter:
    def read(self, source_path: str | Path) -> SnapshotBundle:
        path = Path(source_path)
        if not path.exists():
            raise ImporterError(f"json bundle not found: {path}")
        if path.is_file():
            return self._read_file(path)
        return self._read_dir(path)

    def _read_file(self, path: Path) -> SnapshotBundle:
        payload = read_json_file(path)
        if isinstance(payload, list):
            records = [item for item in (normalize_record(row) for row in payload if isinstance(row, dict)) if item]
            return self._bundle_from_records(records, {"source_file": str(path)})
        if not isinstance(payload, dict):
            raise ImporterError("json bundle root must be object or array")

        if any(key in payload for key in ["records", "snapshots", "frames", "stockRows", "stock_rows"]):
            records = [
                item
                for item in (
                    normalize_record(row)
                    for row in payload.get("records", payload.get("snapshots", []))
                    if isinstance(row, dict)
                )
                if item
            ]
            frames = payload.get("frames", [])
            stock_rows = payload.get("stockRows", payload.get("stock_rows", []))
            sector_rows = payload.get("sectorRows", payload.get("sector_rows", []))
            if not frames and records:
                return self._bundle_from_records(records, payload.get("metadata", {}))
            return SnapshotBundle(
                records=records,
                frames=[row for row in frames if isinstance(row, dict)],
                stock_rows=[row for row in stock_rows if isinstance(row, dict)],
                sector_rows=[row for row in sector_rows if isinstance(row, dict)],
                metadata=payload.get("metadata", {}),
            )

        record = normalize_record(payload)
        return self._bundle_from_records([record], {"source_file": str(path)}) if record else SnapshotBundle()

    def _read_dir(self, path: Path) -> SnapshotBundle:
        manifest = path / "snapshot_manifest.json"
        metadata = read_json_file(manifest) if manifest.exists() else {"source_dir": str(path)}
        records = read_jsonl(path / "snapshot_records.jsonl") or read_jsonl(path / "snapshots.jsonl")
        frames = read_jsonl(path / "snapshot_frames.jsonl")
        stock_rows = read_jsonl(path / "snapshot_stock_rows.jsonl")
        sector_rows = read_jsonl(path / "snapshot_sector_rows.jsonl")
        normalized_records = [item for item in (normalize_record(row) for row in records) if item]
        if normalized_records and (not frames or not stock_rows):
            return self._bundle_from_records(normalized_records, metadata)
        return SnapshotBundle(normalized_records, frames, stock_rows, sector_rows, metadata)

    @staticmethod
    def _bundle_from_records(records: list[dict[str, Any]], metadata: dict[str, Any]) -> SnapshotBundle:
        frames = [frame_from_record(record) for record in records]
        stock_rows: list[dict[str, Any]] = []
        sector_rows: list[dict[str, Any]] = []
        for record in records:
            stock_rows.extend(stock_rows_from_record(record))
            sector_rows.extend(sector_rows_from_record(record))
        return SnapshotBundle(records, frames, stock_rows, sector_rows, metadata)


class LevelDbIndexedDbImporter:
    SNAPSHOT_STORE_IDS = {
        2: "records",
        5: "frames",
        6: "stock_rows",
        7: "sector_rows",
    }

    def read(self, source_path: str | Path) -> SnapshotBundle:
        settings = get_settings()
        source = Path(source_path or settings.data_source.profile_indexeddb_path)
        if not source.exists():
            raise ImporterError(f"IndexedDB LevelDB path not found: {source}")

        staging_target = settings.staging_dir / f"leveldb_{utc_now_iso().replace(':', '').replace('-', '')}"
        if source.is_dir():
            shutil.copytree(source, staging_target)
        else:
            staging_target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, staging_target / source.name)

        command = self._dfindexeddb_command(staging_target)
        try:
            proc = subprocess.run(command, check=False, capture_output=True, text=True, timeout=600)
        except FileNotFoundError as exc:
            raise ImporterError("dfindexeddb is not installed; install optional dependencies from requirements-leveldb.txt") from exc
        except subprocess.TimeoutExpired as exc:
            raise ImporterError("dfindexeddb parsing timed out") from exc
        if proc.returncode != 0:
            raise ImporterError(proc.stderr.strip() or "dfindexeddb failed to parse LevelDB")

        decoded = self._parse_dfindexeddb_output(proc.stdout)
        if not decoded.records and not decoded.frames:
            raise ImporterError("dfindexeddb parsed no DragonBoard snapshot records")
        decoded.metadata.update({"staging_path": str(staging_target), "reader": "dfindexeddb"})
        return decoded

    @staticmethod
    def _dfindexeddb_command(source: Path) -> list[str]:
        script_dir = Path(sys.executable).resolve().parent
        candidates = [script_dir / "dfindexeddb.exe", script_dir / "dfindexeddb"]
        executable = next((path for path in candidates if path.exists()), None)
        if executable is None:
            which_result = shutil.which("dfindexeddb")
            executable = Path(which_result) if which_result else None
        if executable is not None:
            command = [str(executable)]
        else:
            command = [sys.executable, "-m", "dfindexeddb.indexeddb.cli"]
        return [
            *command,
            "db",
            "-s",
            str(source),
            "--format",
            "chrome",
            "--output",
            "jsonl",
            "--use_sequence_number",
            "--load_blobs",
        ]

    def _parse_dfindexeddb_output(self, stdout: str) -> SnapshotBundle:
        records: list[dict[str, Any]] = []
        frames: list[dict[str, Any]] = []
        stock_rows: list[dict[str, Any]] = []
        sector_rows: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            candidate = self._unwrap_dfindexeddb_value(item)
            if not isinstance(candidate, dict):
                continue
            candidate = self._normalize_blink_value(candidate)
            store_id = self._object_store_id(item)
            if store_id == 5:
                if self._is_snapshot_frame(candidate):
                    frames.append(candidate)
                continue
            if store_id == 6:
                if self._is_snapshot_child_row(candidate):
                    stock_rows.append(candidate)
                continue
            if store_id == 7:
                if self._is_snapshot_child_row(candidate):
                    sector_rows.append(candidate)
                continue
            record = normalize_record(candidate)
            if record:
                records.append(record)
        if frames:
            frame_ids = {str(frame.get("snapshotId") or frame.get("id") or "") for frame in frames}
            frame_ids.discard("")
            records_by_id = {str(record.get("id") or record.get("snapshotId")): record for record in records}
            for frame in frames:
                snapshot_id = str(frame.get("snapshotId") or frame.get("id") or "")
                if snapshot_id and snapshot_id not in records_by_id:
                    records_by_id[snapshot_id] = {
                        "id": snapshot_id,
                        "snapshotId": snapshot_id,
                        "type": frame.get("type"),
                        "tradingDate": frame.get("tradingDate"),
                        "slotTime": frame.get("slotTime"),
                        "timestamp": frame.get("timestamp"),
                        "displayKey": frame.get("displayKey") or snapshot_id,
                        "captureMode": frame.get("captureMode") or "real_time",
                        "source": frame.get("source") or "browser_runtime",
                        "payload": frame.get("payload") or {},
                    }
            records = [records_by_id[key] for key in sorted(records_by_id)]
            stock_rows = [row for row in stock_rows if str(row.get("snapshotId") or "") in frame_ids]
            sector_rows = [row for row in sector_rows if str(row.get("snapshotId") or "") in frame_ids]
            return SnapshotBundle(
                records=records,
                frames=sorted(frames, key=lambda item: int(float(item.get("timestamp") or 0))),
                stock_rows=stock_rows,
                sector_rows=sector_rows,
                metadata={"raw_output_lines": len(stdout.splitlines()), "source": "indexeddb_leveldb"},
            )
        return JsonBundleImporter._bundle_from_records(records, {"raw_output_lines": len(stdout.splitlines())})

    @staticmethod
    def _unwrap_dfindexeddb_value(item: dict[str, Any]) -> Any:
        value = item.get("value")
        if isinstance(value, dict) and value.get("__type__") == "ObjectStoreDataValue":
            return value.get("value")
        if isinstance(value, dict):
            return value
        return item

    @staticmethod
    def _object_store_id(item: dict[str, Any]) -> int | None:
        raw_id = item.get("object_store_id")
        if raw_id is None:
            key = item.get("key") if isinstance(item.get("key"), dict) else {}
            prefix = key.get("key_prefix") if isinstance(key.get("key_prefix"), dict) else {}
            raw_id = prefix.get("object_store_id")
        try:
            return int(raw_id)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_blink_value(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [cls._normalize_blink_value(item) for item in value]
        if not isinstance(value, dict):
            return value
        marker = value.get("__type__")
        if marker in {"Undefined", "Null"}:
            return None
        if marker == "JSArray":
            values = value.get("values") if isinstance(value.get("values"), list) else []
            properties = value.get("properties") if isinstance(value.get("properties"), dict) else {}
            if properties:
                max_index = len(values) - 1
                numeric_keys: list[tuple[int, Any]] = []
                for key, item in properties.items():
                    try:
                        index = int(key)
                    except (TypeError, ValueError):
                        continue
                    numeric_keys.append((index, item))
                    max_index = max(max_index, index)
                output = [None for _ in range(max_index + 1)]
                for index, item in enumerate(values):
                    output[index] = cls._normalize_blink_value(item)
                for index, item in numeric_keys:
                    output[index] = cls._normalize_blink_value(item)
                return output
            return [cls._normalize_blink_value(item) for item in values]
        return {key: cls._normalize_blink_value(item) for key, item in value.items() if key != "__type__"}

    @staticmethod
    def _is_snapshot_frame(row: dict[str, Any]) -> bool:
        return (
            str(row.get("type") or "") in VALID_SNAPSHOT_TYPES
            and bool(row.get("tradingDate"))
            and bool(row.get("timestamp"))
            and bool(row.get("snapshotId") or row.get("id"))
        )

    @staticmethod
    def _is_snapshot_child_row(row: dict[str, Any]) -> bool:
        return (
            str(row.get("type") or "") in VALID_SNAPSHOT_TYPES
            and bool(row.get("tradingDate"))
            and bool(row.get("timestamp"))
            and bool(row.get("snapshotId"))
            and bool(row.get("id"))
        )


class BrowserBridgeImporter:
    def read(self, source_path: str | Path | None = None) -> SnapshotBundle:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ImporterError("playwright is not installed; run `playwright install chromium` after installing requirements") from exc

        settings = get_settings()
        url = str(source_path or settings.data_source.page_url)
        script = """
        async () => {
          const db = await new Promise((resolve, reject) => {
            const req = indexedDB.open('DragonBoardData');
            req.onerror = () => reject(req.error);
            req.onsuccess = () => resolve(req.result);
          });
          const readAll = (storeName) => new Promise((resolve) => {
            if (!db.objectStoreNames.contains(storeName)) return resolve([]);
            const tx = db.transaction(storeName, 'readonly');
            const req = tx.objectStore(storeName).getAll();
            req.onerror = () => resolve([]);
            req.onsuccess = () => resolve(req.result || []);
          });
          return {
            records: await readAll('snapshots'),
            frames: await readAll('snapshot_frames'),
            stockRows: await readAll('snapshot_stock_rows'),
            sectorRows: await readAll('snapshot_sector_rows')
          };
        }
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            payload = page.evaluate(script)
            browser.close()
        tmp = SnapshotBundle(
            records=[item for item in (normalize_record(row) for row in payload.get("records", [])) if item],
            frames=[row for row in payload.get("frames", []) if isinstance(row, dict)],
            stock_rows=[row for row in payload.get("stockRows", []) if isinstance(row, dict)],
            sector_rows=[row for row in payload.get("sectorRows", []) if isinstance(row, dict)],
            metadata={"reader": "browser_bridge", "page_url": url},
        )
        if tmp.records and (not tmp.frames or not tmp.stock_rows):
            return JsonBundleImporter._bundle_from_records(tmp.records, tmp.metadata)
        return tmp


def read_snapshot_bundle(source_type: str, source_path: str | None) -> SnapshotBundle:
    if source_type == "json_bundle":
        if not source_path:
            raise ImporterError("json_bundle source_path is required")
        return JsonBundleImporter().read(source_path)
    if source_type == "leveldb":
        return LevelDbIndexedDbImporter().read(source_path or "")
    if source_type == "browser_bridge":
        return BrowserBridgeImporter().read(source_path)
    raise ImporterError(f"unsupported source_type: {source_type}")
