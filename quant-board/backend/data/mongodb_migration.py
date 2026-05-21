from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.data.json_codec import dumps_json_field, loads_json_field


BACKTEST_RESULT_CHUNK_THRESHOLD = 8_000_000
BACKTEST_RESULT_CHUNK_SIZE = 4_000_000


SNAPSHOT_COLLECTIONS = (
    "datasets",
    "snapshot_records",
    "snapshot_frames",
    "snapshot_stock_rows",
    "snapshot_sector_rows",
    "archive_manifests",
)

RESEARCH_SOURCE_COLLECTIONS = (
    "golden_ranktrend_cases",
    "backtest_runs",
    "backtest_trades",
    "backtest_equity_curve",
    "backtest_signals",
    "backtest_quality_reports",
    "optimization_runs",
    "theme_factor_frames",
    "theme_stock_exposures",
    "theme_signals",
    "theme_quality_reports",
)
RESEARCH_GENERATED_COLLECTIONS = ("backtest_result_chunks",)
RESEARCH_COLLECTIONS = (*RESEARCH_SOURCE_COLLECTIONS, *RESEARCH_GENERATED_COLLECTIONS)

THEME_COLLECTIONS = ("themes", "theme_stock_mappings", "theme_metadata")
RUNTIME_COLLECTIONS = ("stock_names", "migration_audit")
JOURNAL_COLLECTIONS = ("trade_journal",)
ALL_COLLECTIONS = (*SNAPSHOT_COLLECTIONS, *RESEARCH_COLLECTIONS, *THEME_COLLECTIONS, *RUNTIME_COLLECTIONS, *JOURNAL_COLLECTIONS)

JSON_FIELD_DEFAULTS: dict[str, tuple[str, Any]] = {
    "quality_flags_json": ("qualityFlags", []),
    "metadata_json": ("metadata", {}),
    "market_stats_json": ("marketStats", {}),
    "sentiment_json": ("sentiment", {}),
    "money_flow_json": ("moneyFlow", {}),
    "indices_json": ("indices", {}),
    "limit_summary_json": ("limitSummary", {}),
    "rotation_summary_json": ("rotationSummary", {}),
    "depth10_json": ("depth10", {}),
    "themes_json": ("themes", []),
    "theme_risk_flags_json": ("themeRiskFlags", []),
    "theme_quality_flags_json": ("themeQualityFlags", []),
    "snapshot_types_json": ("snapshotTypes", []),
    "request_json": ("request", {}),
    "result_json": ("result", {}),
    "input_json": ("input", {}),
    "expected_json": ("expected", {}),
    "fill_detail_json": ("fillDetail", {}),
    "reasons_json": ("reasons", []),
    "risk_flags_json": ("riskFlags", []),
    "theme_reasons_json": ("themeReasons", []),
    "warnings_json": ("warnings", []),
    "issues_json": ("issues", []),
    "stats_json": ("stats", {}),
    "missing_fields_json": ("missingFields", {}),
    "nan_counts_json": ("nanCounts", {}),
    "inf_counts_json": ("infCounts", {}),
    "stock_tags_json": ("stockTags", []),
    "row_counts_json": ("rowCounts", {}),
    "file_hashes_json": ("fileHashes", {}),
}


@dataclass(frozen=True)
class MongoMigrationPlan:
    snapshot_db: Path
    research_db: Path
    theme_db: Path
    stock_json: Path
    target_database: str
    include_research: bool = True


def build_mongodb_indexes() -> dict[str, list[dict[str, Any]]]:
    return {
        "datasets": [
            {"keys": [("id", 1)], "unique": True},
            {"keys": [("sourceType", 1), ("createdAt", -1)]},
        ],
        "snapshot_records": [
            {"keys": [("datasetId", 1), ("snapshotId", 1)], "unique": True},
            {"keys": [("datasetId", 1), ("type", 1), ("tradingDate", 1), ("timestamp", 1)]},
            {"keys": [("datasetId", 1), ("captureMode", 1), ("tradingDate", 1)]},
        ],
        "snapshot_frames": [
            {"keys": [("datasetId", 1), ("snapshotId", 1)], "unique": True},
            {"keys": [("datasetId", 1), ("type", 1), ("tradingDate", 1), ("timestamp", 1)]},
            {"keys": [("datasetId", 1), ("type", 1), ("timestamp", 1)]},
        ],
        "snapshot_stock_rows": [
            {"keys": [("datasetId", 1), ("rowId", 1)], "unique": True},
            {"keys": [("datasetId", 1), ("snapshotId", 1), ("rank", 1)]},
            {"keys": [("datasetId", 1), ("type", 1), ("tradingDate", 1), ("timestamp", 1), ("rank", 1)]},
            {
                "keys": [
                    ("datasetId", 1),
                    ("type", 1),
                    ("tradingDate", 1),
                    ("slotTime", 1),
                    ("captureMode", 1),
                    ("timestamp", 1),
                    ("rank", 1),
                ]
            },
            {"keys": [("datasetId", 1), ("code", 1), ("type", 1), ("tradingDate", 1), ("timestamp", 1)]},
            {"keys": [("datasetId", 1), ("code", 1), ("timestamp", 1)]},
        ],
        "snapshot_sector_rows": [
            {"keys": [("datasetId", 1), ("rowId", 1)], "unique": True},
            {"keys": [("datasetId", 1), ("snapshotId", 1), ("rank", 1)]},
            {"keys": [("datasetId", 1), ("snapshotId", 1), ("timestamp", 1), ("rank", 1)]},
            {"keys": [("datasetId", 1), ("entityType", 1), ("entityKey", 1), ("tradingDate", 1)]},
            {
                "keys": [
                    ("datasetId", 1),
                    ("entityType", 1),
                    ("entityKey", 1),
                    ("type", 1),
                    ("tradingDate", 1),
                    ("timestamp", 1),
                ]
            },
            {"keys": [("datasetId", 1), ("type", 1), ("tradingDate", 1), ("timestamp", 1), ("rank", 1)]},
        ],
        "backtest_runs": [
            {"keys": [("id", 1)], "unique": True},
            {"keys": [("datasetId", 1), ("strategyName", 1), ("snapshotType", 1), ("createdAt", -1)]},
            {"keys": [("status", 1), ("createdAt", -1)]},
        ],
        "backtest_result_chunks": [
            {"keys": [("backtestRunId", 1), ("sequence", 1)], "unique": True},
        ],
        "backtest_trades": [
            {"keys": [("backtestRunId", 1), ("code", 1)]},
            {"keys": [("backtestRunId", 1), ("entryTime", 1)]},
        ],
        "backtest_equity_curve": [{"keys": [("backtestRunId", 1), ("timestamp", 1)]}],
        "backtest_signals": [
            {"keys": [("backtestRunId", 1), ("snapshotId", 1)]},
            {"keys": [("backtestRunId", 1), ("code", 1)]},
            {"keys": [("backtestRunId", 1), ("signal", 1)]},
            {"keys": [("backtestRunId", 1), ("sequence", 1)]},
            {"keys": [("backtestRunId", 1), ("candidateTier", 1), ("regime", 1), ("sequence", 1)]},
        ],
        "backtest_quality_reports": [{"keys": [("backtestRunId", 1)]}],
        "optimization_runs": [
            {"keys": [("id", 1)], "unique": True},
            {"keys": [("datasetId", 1), ("strategyName", 1), ("createdAt", -1)]},
        ],
        "theme_factor_frames": [
            {
                "keys": [("datasetId", 1), ("snapshotId", 1), ("strategyVersion", 1), ("configHash", 1), ("themeId", 1)],
                "unique": True,
            }
        ],
        "theme_stock_exposures": [
            {
                "keys": [
                    ("datasetId", 1),
                    ("snapshotId", 1),
                    ("strategyVersion", 1),
                    ("configHash", 1),
                    ("code", 1),
                    ("themeId", 1),
                ],
                "unique": True,
            }
        ],
        "theme_signals": [
            {
                "keys": [("datasetId", 1), ("snapshotId", 1), ("strategyVersion", 1), ("configHash", 1), ("themeId", 1)],
                "unique": True,
            }
        ],
        "theme_quality_reports": [
            {
                "keys": [("datasetId", 1), ("snapshotType", 1), ("strategyVersion", 1), ("configHash", 1), ("randomSeed", 1)],
                "unique": True,
            }
        ],
        "themes": [{"keys": [("id", 1)], "unique": True}],
        "theme_stock_mappings": [
            {"keys": [("themeId", 1), ("stockCode", 1)], "unique": True},
            {"keys": [("stockCode", 1)]},
        ],
        "theme_metadata": [{"keys": [("key", 1)], "unique": True}],
        "stock_names": [
            {"keys": [("code", 1)], "unique": True},
            {"keys": [("active", 1), ("market", 1), ("type", 1), ("code", 1)]},
            {"keys": [("active", 1), ("code", 1)]},
            {"keys": [("active", 1), ("pinyinInitials", 1)]},
            {"keys": [("active", 1), ("nameNormalized", 1)]},
        ],
        "archive_manifests": [
            {"keys": [("archiveId", 1)], "unique": True},
            {"keys": [("scope", 1), ("status", 1)]},
            {"keys": [("datasetId", 1), ("snapshotType", 1), ("tradingDate", 1)]},
        ],
        "migration_audit": [
            {"keys": [("opType", 1), ("idempotencyKey", 1)], "unique": True},
            {"keys": [("opType", 1), ("createdAt", -1)]},
        ],
        "trade_journal": [
            {"keys": [("id", 1)], "unique": True},
            {"keys": [("stockCode", 1), ("tradeTime", -1)]},
            {"keys": [("tradeType", 1), ("createdAt", -1)]},
            {"keys": [("linkedEntryId", 1)]},
            {"keys": [("status", 1), ("createdAt", -1)]},
            {"keys": [("stockCode", 1), ("status", 1), ("createdAt", -1)]},
            {"keys": [("modelResult", 1), ("createdAt", -1)]},
            {"keys": [("executionResult", 1), ("createdAt", -1)]},
        ],
    }


def map_sqlite_row_to_mongo(
    collection: str,
    row: sqlite3.Row | dict[str, Any],
    *,
    audit: list[dict[str, object]] | None = None,
    generated: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    source = dict(row)
    document: dict[str, Any] = {}
    for key, value in source.items():
        if key == "id" and collection in {
            "snapshot_records",
            "snapshot_frames",
            "snapshot_stock_rows",
            "snapshot_sector_rows",
            "backtest_trades",
            "backtest_equity_curve",
            "backtest_signals",
            "backtest_quality_reports",
            "theme_factor_frames",
            "theme_stock_exposures",
            "theme_signals",
            "theme_quality_reports",
            "theme_stock_mappings",
            "archive_manifests",
        }:
            if collection == "backtest_signals":
                document["sequence"] = value
            else:
                document["legacyId"] = value
            continue
        if key in JSON_FIELD_DEFAULTS:
            target_key, fallback = JSON_FIELD_DEFAULTS[key]
            parsed = _parse_json_field(
                collection,
                key,
                value,
                fallback,
                audit=audit,
            )
            if collection == "backtest_runs" and key == "result_json":
                result_compressed = dumps_json_field(parsed)
                chunks = _backtest_result_chunks(str(source.get("id") or ""), result_compressed)
                if chunks and generated is not None:
                    document["resultCompressed"] = ""
                    document["resultChunked"] = True
                    document["resultChunkCount"] = len(chunks)
                    generated.setdefault("backtest_result_chunks", []).extend(chunks)
                else:
                    document["resultCompressed"] = result_compressed
                    document["resultChunked"] = False
                    document["resultChunkCount"] = 0
            else:
                document[target_key] = parsed
            continue
        document[_camel_case(key)] = value
    return document


def _backtest_result_chunks(run_id: str, result_compressed: str) -> list[dict[str, Any]]:
    if len(result_compressed.encode("utf-8")) <= BACKTEST_RESULT_CHUNK_THRESHOLD:
        return []
    return [
        {
            "backtestRunId": run_id,
            "sequence": index,
            "payload": result_compressed[start : start + BACKTEST_RESULT_CHUNK_SIZE],
        }
        for index, start in enumerate(range(0, len(result_compressed), BACKTEST_RESULT_CHUNK_SIZE))
    ]


def map_stock_name_to_mongo(item: dict[str, Any]) -> dict[str, Any]:
    code = str(item.get("code") or "").strip()
    name = str(item.get("name") or "").strip()
    market = str(item.get("market") or "").strip().upper()
    stock_type = str(item.get("type") or "").strip() or "stock"
    name_normalized = "".join(name.split())
    return {
        "code": code,
        "name": name,
        "market": market,
        "type": stock_type,
        "nameNormalized": name_normalized,
        "pinyinInitials": str(item.get("pinyinInitials") or "").strip().lower(),
        "pinyinFull": str(item.get("pinyinFull") or "").strip().lower(),
        "searchText": " ".join(part for part in [code, name_normalized, market, stock_type] if part),
        "active": True,
    }


def plan_mongodb_migration(plan: MongoMigrationPlan) -> dict[str, Any]:
    collections: dict[str, dict[str, Any]] = {}
    for path, names in [
        (plan.snapshot_db, SNAPSHOT_COLLECTIONS),
        (plan.theme_db, THEME_COLLECTIONS),
    ]:
        tables = _sqlite_tables(path)
        for name in names:
            collections[name] = {
                "source": str(path),
                "sourceRows": _sqlite_count(path, name) if name in tables else 0,
                "exists": name in tables,
            }

    if plan.include_research:
        research_tables = _sqlite_tables(plan.research_db)
        for name in RESEARCH_SOURCE_COLLECTIONS:
            collections[name] = {
                "source": str(plan.research_db),
                "sourceRows": _sqlite_count(plan.research_db, name) if name in research_tables else 0,
                "exists": name in research_tables,
                "skipped": False,
                "sourceReadable": True,
            }
        for name in RESEARCH_GENERATED_COLLECTIONS:
            collections[name] = {
                "source": "generated",
                "sourceRows": 0,
                "exists": True,
                "skipped": False,
                "sourceReadable": True,
            }
    else:
        for name in RESEARCH_COLLECTIONS:
            collections[name] = {
                "source": str(plan.research_db),
                "sourceRows": 0,
                "exists": plan.research_db.exists(),
                "skipped": True,
                "sourceReadable": False,
            }

    stock_rows = _load_stock_json(plan.stock_json)
    collections["stock_names"] = {
        "source": str(plan.stock_json),
        "sourceRows": len(stock_rows),
        "exists": plan.stock_json.exists(),
    }

    return {
        "ok": True,
        "targetDatabase": plan.target_database,
        "writeMode": "dry_run",
        "collections": collections,
        "indexes": build_mongodb_indexes(),
    }


def inspect_mongodb_database(database: Any) -> dict[str, Any]:
    collections: dict[str, dict[str, Any]] = {}
    for name in ALL_COLLECTIONS:
        collection = database[name]
        index_info = collection.index_information() if hasattr(collection, "index_information") else {}
        collections[name] = {
            "count": int(collection.count_documents({})),
            "indexes": sorted(str(key) for key in index_info.keys()),
        }
    return {
        "ok": True,
        "collections": collections,
    }


def verify_mongodb_migration(
    database: Any,
    *,
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    codes: list[str] | None = None,
) -> dict[str, Any]:
    counts = {name: int(database[name].count_documents({})) for name in ALL_COLLECTIONS}
    indexes = _verify_mongodb_indexes(database)
    frames = list(
        database["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": snapshot_type}
        )
    )
    frames.sort(key=lambda row: (str(row.get("tradingDate") or ""), int(row.get("timestamp") or 0), str(row.get("snapshotId") or "")))
    snapshot_ids = [str(row.get("snapshotId") or "") for row in frames if row.get("snapshotId")]
    empty_frames = _find_empty_snapshot_frames(database, dataset_id, frames)
    rank_series = _verify_rank_series(database, dataset_id, snapshot_ids, codes or [])
    ok = not indexes["missing"] and not empty_frames and all(not item["missingSnapshots"] for item in rank_series.values())
    return {
        "ok": ok,
        "datasetId": dataset_id,
        "snapshotType": snapshot_type,
        "counts": counts,
        "indexes": indexes,
        "continuity": {
            "frameCount": len(frames),
            "emptyFrames": empty_frames,
            "firstTradingDate": frames[0].get("tradingDate") if frames else None,
            "lastTradingDate": frames[-1].get("tradingDate") if frames else None,
        },
        "rankSeries": rank_series,
    }


def apply_mongodb_migration(
    plan: MongoMigrationPlan,
    database: Any,
    *,
    replace_confirmed: bool = False,
    batch_size: int = 1000,
) -> dict[str, Any]:
    source_errors = _validate_migration_sources(plan)
    if source_errors:
        return {
            "ok": False,
            "targetDatabase": plan.target_database,
            "writeMode": "apply",
            "error": {
                "code": "source_validation_failed",
                "sources": source_errors,
            },
        }

    non_empty = _non_empty_collections(database, ALL_COLLECTIONS)
    if non_empty and not replace_confirmed:
        return {
            "ok": False,
            "targetDatabase": plan.target_database,
            "writeMode": "apply",
            "error": {
                "code": "target_not_empty",
                "collections": non_empty,
                "message": "target MongoDB database is not empty; pass replace_confirmed=True to replace it",
            },
        }

    for name in ALL_COLLECTIONS:
        database[name].delete_many({})

    audit: list[dict[str, object]] = []
    results: dict[str, dict[str, Any]] = {}
    for path, names in [
        (plan.snapshot_db, SNAPSHOT_COLLECTIONS),
        (plan.theme_db, THEME_COLLECTIONS),
    ]:
        tables = _sqlite_tables(path)
        for name in names:
            if name not in tables:
                results[name] = {"source": str(path), "sourceRows": 0, "insertedRows": 0, "exists": False}
                continue
            inserted = _copy_sqlite_table_to_mongo(
                path,
                name,
                database[name],
                audit=audit,
                batch_size=batch_size,
            )
            results[name] = {
                "source": str(path),
                "sourceRows": inserted,
                "insertedRows": inserted,
                "exists": True,
            }

    if plan.include_research:
        research_tables = _sqlite_tables(plan.research_db)
        for name in RESEARCH_SOURCE_COLLECTIONS:
            if name not in research_tables:
                results[name] = {"source": str(plan.research_db), "sourceRows": 0, "insertedRows": 0, "exists": False}
                continue
            generated: dict[str, list[dict[str, Any]]] = {}
            inserted = _copy_sqlite_table_to_mongo(
                plan.research_db,
                name,
                database[name],
                audit=audit,
                batch_size=batch_size,
                generated=generated,
            )
            results[name] = {
                "source": str(plan.research_db),
                "sourceRows": inserted,
                "insertedRows": inserted,
                "exists": True,
            }
            for generated_name, rows in generated.items():
                _insert_batches(database[generated_name], rows, batch_size=batch_size)
                current = results.setdefault(
                    generated_name,
                    {
                        "source": "generated",
                        "sourceRows": 0,
                        "insertedRows": 0,
                        "exists": True,
                    },
                )
                current["insertedRows"] = int(current["insertedRows"]) + len(rows)
        for name in RESEARCH_GENERATED_COLLECTIONS:
            results.setdefault(
                name,
                {
                    "source": "generated",
                    "sourceRows": 0,
                    "insertedRows": 0,
                    "exists": True,
                },
            )
    else:
        for name in RESEARCH_COLLECTIONS:
            results[name] = {
                "source": str(plan.research_db),
                "sourceRows": 0,
                "insertedRows": 0,
                "exists": plan.research_db.exists(),
                "skipped": True,
                "sourceReadable": False,
            }

    raw_stock_rows = _load_stock_json(plan.stock_json)
    stock_rows = _dedupe_stock_names([map_stock_name_to_mongo(item) for item in raw_stock_rows], audit=audit)
    _insert_batches(database["stock_names"], stock_rows, batch_size=batch_size)
    results["stock_names"] = {
        "source": str(plan.stock_json),
        "sourceRows": len(raw_stock_rows),
        "insertedRows": len(stock_rows),
        "exists": plan.stock_json.exists(),
    }

    _persist_migration_audit(database["migration_audit"], audit, batch_size=batch_size)
    _create_indexes(database)
    return {
        "ok": True,
        "targetDatabase": plan.target_database,
        "writeMode": "apply",
        "collections": results,
        "audit": audit,
    }


def _verify_mongodb_indexes(database: Any) -> dict[str, Any]:
    missing: list[dict[str, Any]] = []
    present: dict[str, list[str]] = {}
    for collection_name, expected_indexes in build_mongodb_indexes().items():
        collection = database[collection_name]
        index_info = collection.index_information() if hasattr(collection, "index_information") else {}
        normalized = [_normalize_index_detail(detail) for detail in index_info.values()]
        present[collection_name] = sorted(str(key) for key in index_info.keys())
        for expected in expected_indexes:
            expected_key = list(expected["keys"])
            expected_unique = bool(expected.get("unique", False))
            if not any(item["keys"] == expected_key and (not expected_unique or item["unique"]) for item in normalized):
                missing.append(
                    {
                        "collection": collection_name,
                        "keys": expected_key,
                        "unique": expected_unique,
                    }
                )
    return {"missing": missing, "present": present}


def _normalize_index_detail(detail: dict[str, Any]) -> dict[str, Any]:
    keys = detail.get("key") or detail.get("keys") or []
    return {
        "keys": [tuple(item) for item in keys],
        "unique": bool(detail.get("unique", False)),
    }


def _find_empty_snapshot_frames(database: Any, dataset_id: str, frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    empty: list[dict[str, Any]] = []
    for frame in frames:
        snapshot_id = str(frame.get("snapshotId") or "")
        if not snapshot_id:
            continue
        stock_count = int(
            database["snapshot_stock_rows"].count_documents(
                {"datasetId": dataset_id, "snapshotId": snapshot_id}
            )
        )
        if stock_count == 0:
            empty.append(
                {
                    "snapshotId": snapshot_id,
                    "tradingDate": frame.get("tradingDate"),
                    "slotTime": frame.get("slotTime"),
                    "declaredStockRowCount": int(frame.get("stockRowCount") or 0),
                }
            )
    return empty


def _verify_rank_series(
    database: Any,
    dataset_id: str,
    snapshot_ids: list[str],
    codes: list[str],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for code in codes:
        query = {"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}, "code": code}
        rows = list(database["snapshot_stock_rows"].find(query))
        seen = {str(row.get("snapshotId") or "") for row in rows}
        result[code] = {
            "snapshotCount": len(rows),
            "missingSnapshots": [snapshot_id for snapshot_id in snapshot_ids if snapshot_id not in seen],
        }
    return result


def _validate_migration_sources(plan: MongoMigrationPlan) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for path, names, label in [
        (plan.snapshot_db, SNAPSHOT_COLLECTIONS, "snapshot_db"),
        (plan.theme_db, THEME_COLLECTIONS, "theme_db"),
    ]:
        if not path.is_file():
            errors.append({"source": label, "path": str(path), "code": "file_missing"})
            continue
        try:
            tables = _sqlite_tables(path)
        except sqlite3.Error as exc:
            errors.append({"source": label, "path": str(path), "code": "sqlite_unreadable", "message": str(exc)})
            continue
        missing_tables = [name for name in names if name not in tables]
        if missing_tables:
            errors.append(
                {
                    "source": label,
                    "path": str(path),
                    "code": "tables_missing",
                    "tables": missing_tables,
                }
            )
    if plan.include_research:
        path = plan.research_db
        if not path.is_file():
            errors.append({"source": "research_db", "path": str(path), "code": "file_missing"})
        else:
            try:
                tables = _sqlite_tables(path)
            except sqlite3.Error as exc:
                errors.append({"source": "research_db", "path": str(path), "code": "sqlite_unreadable", "message": str(exc)})
            else:
                missing_tables = [name for name in RESEARCH_SOURCE_COLLECTIONS if name not in tables]
                if missing_tables:
                    errors.append(
                        {
                            "source": "research_db",
                            "path": str(path),
                            "code": "tables_missing",
                            "tables": missing_tables,
                        }
                    )
    if not plan.stock_json.is_file():
        errors.append({"source": "stock_json", "path": str(plan.stock_json), "code": "file_missing"})
    else:
        try:
            _load_stock_json(plan.stock_json)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({"source": "stock_json", "path": str(plan.stock_json), "code": "json_unreadable", "message": str(exc)})
    return errors


def get_mongodb_database(
    uri: str,
    database_name: str,
    *,
    connect_timeout_ms: int = 2000,
    server_selection_timeout_ms: int = 2000,
) -> Any:
    if not uri:
        raise RuntimeError("QUANT_BOARD_MONGODB_URI is required for MongoDB migration apply mode")
    try:
        from pymongo import MongoClient
    except ImportError as exc:  # pragma: no cover - depends on deployment environment
        raise RuntimeError("pymongo is required for MongoDB migration apply mode") from exc

    client = MongoClient(
        uri,
        connectTimeoutMS=connect_timeout_ms,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
    )
    client.admin.command("ping")
    return client[database_name]


def _parse_json_field(
    collection: str,
    field: str,
    value: Any,
    fallback: Any,
    *,
    audit: list[dict[str, object]] | None,
) -> Any:
    parsed = loads_json_field(value, None)
    if parsed is None and value not in (None, "", "null"):
        if audit is not None:
            audit.append(
                {
                    "collection": collection,
                    "field": field,
                    "rawValue": str(value),
                    "reason": "invalid_json",
                }
            )
        return _copy_default(fallback)
    if parsed is None:
        return _copy_default(fallback)
    return parsed


def _copy_default(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.loads(json.dumps(value, ensure_ascii=False))
    return value


def _camel_case(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _sqlite_tables(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
        return {
            str(row[0])
            for row in conn.execute("select name from sqlite_master where type='table'").fetchall()
        }


def _sqlite_count(path: Path, table: str) -> int:
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
        return int(conn.execute(f'select count(*) from "{table}"').fetchone()[0])


def _load_stock_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, list) else []


def _dedupe_stock_names(
    rows: list[dict[str, Any]],
    *,
    audit: list[dict[str, object]],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("code") or "")
        if not code:
            audit.append({"collection": "stock_names", "reason": "missing_code", "row": row})
            continue
        if code in seen:
            audit.append({"collection": "stock_names", "reason": "duplicate_code", "code": code, "row": row})
            continue
        seen.add(code)
        result.append(row)
    return result


def _persist_migration_audit(collection: Any, audit: list[dict[str, object]], *, batch_size: int) -> None:
    if not audit:
        return
    created_at = datetime.now(UTC).replace(tzinfo=None).isoformat()
    rows = []
    for index, item in enumerate(audit, start=1):
        rows.append(
            {
                "opType": "mongodb_migration",
                "idempotencyKey": f"{item.get('collection', 'unknown')}:{item.get('reason', 'unknown')}:{item.get('code', index)}:{index}",
                "createdAt": created_at,
                **item,
            }
        )
    _insert_batches(collection, rows, batch_size=batch_size)


def _non_empty_collections(database: Any, collection_names: tuple[str, ...]) -> list[dict[str, Any]]:
    non_empty: list[dict[str, Any]] = []
    for name in collection_names:
        count = int(database[name].count_documents({}))
        if count:
            non_empty.append({"collection": name, "count": count})
    return non_empty


def _copy_sqlite_table_to_mongo(
    path: Path,
    table: str,
    collection: Any,
    *,
    audit: list[dict[str, object]],
    batch_size: int,
    generated: dict[str, list[dict[str, Any]]] | None = None,
) -> int:
    inserted = 0
    batch: list[dict[str, Any]] = []
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute(f'select * from "{table}"'):
            batch.append(map_sqlite_row_to_mongo(table, row, audit=audit, generated=generated))
            if len(batch) >= batch_size:
                _insert_batches(collection, batch, batch_size=batch_size)
                inserted += len(batch)
                batch = []
    if batch:
        _insert_batches(collection, batch, batch_size=batch_size)
        inserted += len(batch)
    return inserted


def _insert_batches(collection: Any, rows: list[dict[str, Any]], *, batch_size: int) -> None:
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        if batch:
            collection.insert_many(batch, ordered=False)


def _create_indexes(database: Any) -> None:
    for collection_name, indexes in build_mongodb_indexes().items():
        collection = database[collection_name]
        for index in indexes:
            keys = index["keys"]
            unique = bool(index.get("unique", False))
            name = "_".join(f"{key}_{direction}" for key, direction in keys)
            collection.create_index(keys, unique=unique, name=name)
