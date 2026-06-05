from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.data.json_codec import loads_json_field
from backend.data.mongodb_migration import (
    ALL_COLLECTIONS,
    MongoMigrationPlan,
    apply_mongodb_migration,
    build_mongodb_indexes,
    map_sqlite_row_to_mongo,
    plan_mongodb_migration,
    verify_mongodb_migration,
)


class FakeCollection:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []
        self.indexes: list[dict[str, object]] = []
        self.deleted = False

    def count_documents(self, _filter: dict[str, object]) -> int:
        return len([row for row in self.rows if _matches(row, _filter)])

    def find(self, _filter: dict[str, object] | None = None) -> list[dict[str, object]]:
        return [row for row in self.rows if _matches(row, _filter or {})]

    def index_information(self) -> dict[str, dict[str, object]]:
        return {
            str(item.get("name") or "_".join(f"{key}_{direction}" for key, direction in item["keys"])): {
                "key": item["keys"],
                "unique": item.get("unique", False),
            }
            for item in self.indexes
        }

    def delete_many(self, _filter: dict[str, object]) -> None:
        self.rows.clear()
        self.deleted = True

    def insert_many(self, rows: list[dict[str, object]], ordered: bool = False) -> None:
        assert ordered is False
        self.rows.extend(rows)

    def create_index(self, keys, unique: bool = False, name: str | None = None) -> None:
        self.indexes.append({"keys": list(keys), "unique": unique, "name": name})


class FakeMongoDatabase(dict):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def test_snapshot_mapping_parses_json_and_removes_json_columns() -> None:
    audit: list[dict[str, object]] = []

    doc = map_sqlite_row_to_mongo(
        "snapshot_frames",
        {
            "dataset_id": "dragonboard_live",
            "snapshot_id": "half_hour:2026-05-12:15:00",
            "trading_date": "2026-05-12",
            "slot_time": "15:00",
            "quality_flags_json": '["ok"]',
            "metadata_json": '{"source":"test"}',
            "market_stats_json": '{"up":123}',
            "stock_row_count": 243,
        },
        audit=audit,
    )

    assert doc["datasetId"] == "dragonboard_live"
    assert doc["snapshotId"] == "half_hour:2026-05-12:15:00"
    assert doc["tradingDate"] == "2026-05-12"
    assert doc["slotTime"] == "15:00"
    assert doc["qualityFlags"] == ["ok"]
    assert doc["metadata"] == {"source": "test"}
    assert doc["marketStats"] == {"up": 123}
    assert doc["stockRowCount"] == 243
    assert not any(key.endswith("_json") for key in doc)
    assert audit == []


def test_backtest_run_mapping_uses_compressed_result_contract() -> None:
    doc = map_sqlite_row_to_mongo(
        "backtest_runs",
        {
            "id": "bt_1",
            "dataset_id": "dragonboard_live",
            "request_json": '{"datasetId":"dragonboard_live"}',
            "result_json": '{"signals":[{"code":"000001"}],"totalReturn":0.12}',
        },
    )

    assert doc["id"] == "bt_1"
    assert doc["request"] == {"datasetId": "dragonboard_live"}
    assert "result" not in doc
    assert loads_json_field(str(doc["resultCompressed"]), {}) == {
        "signals": [{"code": "000001"}],
        "totalReturn": 0.12,
    }
    assert doc["resultChunked"] is False
    assert doc["resultChunkCount"] == 0


def test_backtest_run_mapping_chunks_oversized_compressed_result(monkeypatch) -> None:
    import backend.data.mongodb_migration as migration

    monkeypatch.setattr(migration, "BACKTEST_RESULT_CHUNK_THRESHOLD", 20)
    monkeypatch.setattr(migration, "BACKTEST_RESULT_CHUNK_SIZE", 10)
    generated: dict[str, list[dict[str, object]]] = {}

    doc = map_sqlite_row_to_mongo(
        "backtest_runs",
        {
            "id": "bt_large",
            "dataset_id": "dragonboard_live",
            "request_json": '{"datasetId":"dragonboard_live"}',
            "result_json": '{"signals":[{"code":"000001","payload":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}',
        },
        generated=generated,
    )

    chunks = generated["backtest_result_chunks"]
    restored = "".join(str(chunk["payload"]) for chunk in chunks)

    assert doc["resultCompressed"] == ""
    assert doc["resultChunked"] is True
    assert doc["resultChunkCount"] == len(chunks)
    assert len(chunks) > 1
    assert [chunk["sequence"] for chunk in chunks] == list(range(len(chunks)))
    assert loads_json_field(restored, {})["signals"][0]["code"] == "000001"


def test_invalid_json_is_audited_and_defaulted() -> None:
    audit: list[dict[str, object]] = []

    doc = map_sqlite_row_to_mongo(
        "snapshot_stock_rows",
        {
            "dataset_id": "dragonboard_live",
            "row_id": "row-1",
            "snapshot_id": "s1",
            "code": "000001",
            "themes_json": "not-json",
            "depth10_json": '{"bid":[1]}',
        },
        audit=audit,
    )

    assert doc["datasetId"] == "dragonboard_live"
    assert doc["rowId"] == "row-1"
    assert doc["snapshotId"] == "s1"
    assert doc["themes"] == []
    assert doc["depth10"] == {"bid": [1]}
    assert len(audit) == 1
    assert audit[0]["collection"] == "snapshot_stock_rows"
    assert audit[0]["field"] == "themes_json"


def test_build_mongodb_indexes_contains_snapshot_and_stock_name_unique_keys() -> None:
    indexes = build_mongodb_indexes()

    assert "migration_audit" in ALL_COLLECTIONS
    assert indexes["snapshot_frames"][0]["keys"] == [("datasetId", 1), ("snapshotId", 1)]
    assert indexes["snapshot_frames"][0]["unique"] is True
    assert indexes["snapshot_stock_rows"][0]["keys"] == [("datasetId", 1), ("rowId", 1)]
    assert "backtest_result_chunks" in ALL_COLLECTIONS
    assert indexes["backtest_result_chunks"][0]["keys"] == [("backtestRunId", 1), ("sequence", 1)]
    assert indexes["backtest_result_chunks"][0]["unique"] is True
    assert indexes["stock_names"][0]["keys"] == [("code", 1)]
    assert indexes["stock_names"][0]["unique"] is True
    assert indexes["migration_audit"][0]["keys"] == [("opType", 1), ("idempotencyKey", 1)]
    assert indexes["migration_audit"][0]["unique"] is True
    assert "hotlist_sentiment" in ALL_COLLECTIONS
    assert indexes["hotlist_sentiment"][0]["keys"] == [
        ("datasetId", 1),
        ("snapshotType", 1),
        ("tradingDate", 1),
    ]
    assert indexes["hotlist_sentiment"][0]["unique"] is True


def test_plan_mongodb_migration_counts_sqlite_sources_and_stock_json(tmp_path: Path) -> None:
    snapshot_db = tmp_path / "snapshots.db"
    research_db = tmp_path / "research.db"
    theme_db = tmp_path / "theme.db"
    stock_json = tmp_path / "stock_code.json"
    stock_json.write_text(
        '[{"code":"000001","name":"平安银行","market":"SZ","type":"stock"}]',
        encoding="utf-8",
    )

    with sqlite3.connect(snapshot_db) as conn:
        conn.executescript(
            """
            create table datasets (id text primary key);
            create table snapshot_records (id integer primary key);
            create table snapshot_frames (id integer primary key);
            create table snapshot_stock_rows (id integer primary key);
            create table snapshot_sector_rows (id integer primary key);
            insert into datasets values ('dragonboard_live');
            insert into snapshot_frames values (1);
            """
        )
    with sqlite3.connect(research_db) as conn:
        conn.executescript(
            """
            create table backtest_runs (id text primary key);
            create table backtest_signals (id integer primary key);
            insert into backtest_runs values ('run-1');
            """
        )
    with sqlite3.connect(theme_db) as conn:
        conn.executescript(
            """
            create table themes (id text primary key);
            create table theme_stock_mappings (id integer primary key);
            create table theme_metadata (key text primary key);
            insert into themes values ('theme-1');
            """
        )

    plan = plan_mongodb_migration(
        MongoMigrationPlan(
            snapshot_db=snapshot_db,
            research_db=research_db,
            theme_db=theme_db,
            stock_json=stock_json,
            target_database="dragon_board_quant",
        )
    )

    assert plan["ok"] is True
    assert plan["targetDatabase"] == "dragon_board_quant"
    assert plan["collections"]["snapshot_frames"]["sourceRows"] == 1
    assert plan["collections"]["backtest_runs"]["sourceRows"] == 1
    assert plan["collections"]["themes"]["sourceRows"] == 1
    assert plan["collections"]["stock_names"]["sourceRows"] == 1
    assert plan["writeMode"] == "dry_run"


def test_mongodb_settings_use_backend_only_environment(monkeypatch) -> None:
    from backend.settings import Settings

    monkeypatch.setenv("QUANT_BOARD_MONGODB_URI", "mongodb://localhost:27017")
    monkeypatch.setenv("QUANT_BOARD_MONGODB_DATABASE", "dragon_board_quant")
    monkeypatch.setenv("QUANT_BOARD_MONGODB_CONNECT_TIMEOUT_MS", "1500")
    monkeypatch.setenv("QUANT_BOARD_MONGODB_BACKUP_DIR", "D:/qb-backups")

    settings = Settings()

    assert settings.mongodb_uri == "mongodb://localhost:27017"
    assert settings.mongodb_database == "dragon_board_quant"
    assert settings.mongodb_connect_timeout_ms == 1500
    assert str(settings.mongodb_backup_dir).replace("\\", "/") == "D:/qb-backups"


def test_apply_mongodb_migration_requires_empty_target(tmp_path: Path) -> None:
    snapshot_db, research_db, theme_db, stock_json = _create_minimal_sources(tmp_path)
    fake_db = FakeMongoDatabase({"snapshot_frames": FakeCollection([{"existing": True}])})

    result = apply_mongodb_migration(
        MongoMigrationPlan(snapshot_db, research_db, theme_db, stock_json, "dragon_board_quant"),
        fake_db,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "target_not_empty"
    assert result["writeMode"] == "apply"


def test_apply_mongodb_migration_validates_sources_before_clearing_target(tmp_path: Path) -> None:
    snapshot_db, research_db, theme_db, stock_json = _create_minimal_sources(tmp_path)
    missing_theme_db = tmp_path / "missing_themeDATA.db"
    fake_db = FakeMongoDatabase()
    fake_db["snapshot_frames"].rows.append({"existing": True})

    result = apply_mongodb_migration(
        MongoMigrationPlan(snapshot_db, research_db, missing_theme_db, stock_json, "dragon_board_quant"),
        fake_db,
        replace_confirmed=True,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "source_validation_failed"
    assert fake_db["snapshot_frames"].rows == [{"existing": True}]


def test_apply_mongodb_migration_writes_structured_documents_and_indexes(tmp_path: Path) -> None:
    snapshot_db, research_db, theme_db, stock_json = _create_minimal_sources(tmp_path)
    fake_db = FakeMongoDatabase()

    result = apply_mongodb_migration(
        MongoMigrationPlan(snapshot_db, research_db, theme_db, stock_json, "dragon_board_quant"),
        fake_db,
        replace_confirmed=True,
        batch_size=2,
    )

    assert result["ok"] is True
    assert result["writeMode"] == "apply"
    assert result["collections"]["snapshot_frames"]["insertedRows"] == 1
    assert fake_db["snapshot_frames"].rows[0]["snapshotId"] == "half_hour:2026-05-12:15:00"
    assert fake_db["snapshot_frames"].rows[0]["qualityFlags"] == ["ok"]
    assert not any(key.endswith("_json") for key in fake_db["snapshot_frames"].rows[0])
    assert fake_db["stock_names"].rows[0]["code"] == "000001"
    assert fake_db["snapshot_frames"].indexes


def test_apply_mongodb_migration_deduplicates_stock_names_and_audits_duplicates(tmp_path: Path) -> None:
    snapshot_db, research_db, theme_db, stock_json = _create_minimal_sources(tmp_path)
    stock_json.write_text(
        """
        [
          {"code":"000001","name":"平安银行","market":"SZ","type":"stock"},
          {"code":"000001","name":"平安银行","market":"SZ","type":"stock"}
        ]
        """,
        encoding="utf-8",
    )
    fake_db = FakeMongoDatabase()

    result = apply_mongodb_migration(
        MongoMigrationPlan(snapshot_db, research_db, theme_db, stock_json, "dragon_board_quant"),
        fake_db,
        replace_confirmed=True,
    )

    assert result["ok"] is True
    assert result["collections"]["stock_names"]["sourceRows"] == 2
    assert result["collections"]["stock_names"]["insertedRows"] == 1
    assert fake_db["stock_names"].rows == [
        {
            "code": "000001",
            "name": "平安银行",
            "market": "SZ",
            "type": "stock",
            "nameNormalized": "平安银行",
            "pinyinInitials": "",
            "pinyinFull": "",
            "searchText": "000001 平安银行 SZ stock",
            "active": True,
        }
    ]
    assert result["audit"][0]["collection"] == "stock_names"
    assert result["audit"][0]["reason"] == "duplicate_code"
    assert fake_db["migration_audit"].rows[0]["opType"] == "mongodb_migration"
    assert fake_db["migration_audit"].rows[0]["reason"] == "duplicate_code"


def test_apply_mongodb_migration_can_skip_research_source(tmp_path: Path) -> None:
    snapshot_db, research_db, theme_db, stock_json = _create_minimal_sources(tmp_path)
    fake_db = FakeMongoDatabase()

    result = apply_mongodb_migration(
        MongoMigrationPlan(
            snapshot_db,
            research_db,
            theme_db,
            stock_json,
            "dragon_board_quant",
            include_research=False,
        ),
        fake_db,
        replace_confirmed=True,
    )

    assert result["ok"] is True
    assert result["collections"]["snapshot_frames"]["insertedRows"] == 1
    assert result["collections"]["backtest_runs"]["sourceRows"] == 0
    assert result["collections"]["backtest_runs"]["insertedRows"] == 0
    assert result["collections"]["backtest_runs"]["skipped"] is True
    assert result["collections"]["backtest_runs"]["sourceReadable"] is False
    assert fake_db["snapshot_frames"].rows
    assert fake_db["themes"].rows
    assert fake_db["backtest_runs"].rows == []
    assert fake_db["backtest_runs"].indexes


def test_skip_research_does_not_require_readable_research_db(tmp_path: Path) -> None:
    snapshot_db, research_db, theme_db, stock_json = _create_minimal_sources(tmp_path)
    research_db.write_text("not a sqlite database", encoding="utf-8")
    fake_db = FakeMongoDatabase()

    plan = MongoMigrationPlan(
        snapshot_db,
        research_db,
        theme_db,
        stock_json,
        "dragon_board_quant",
        include_research=False,
    )

    dry_run = plan_mongodb_migration(plan)
    result = apply_mongodb_migration(plan, fake_db, replace_confirmed=True)

    assert dry_run["ok"] is True
    assert dry_run["collections"]["backtest_runs"]["sourceRows"] == 0
    assert dry_run["collections"]["backtest_runs"]["skipped"] is True
    assert dry_run["collections"]["backtest_runs"]["sourceReadable"] is False
    assert result["ok"] is True
    assert result["collections"]["backtest_runs"]["sourceRows"] == 0
    assert result["collections"]["backtest_runs"]["skipped"] is True
    assert result["collections"]["backtest_runs"]["sourceReadable"] is False
    assert fake_db["snapshot_frames"].rows
    assert fake_db["backtest_runs"].rows == []


def test_get_mongodb_database_requires_uri() -> None:
    from backend.data.mongodb_migration import get_mongodb_database

    try:
        get_mongodb_database("", "dragon_board_quant")
    except RuntimeError as exc:
        assert "QUANT_BOARD_MONGODB_URI" in str(exc)
    else:
        raise AssertionError("expected missing MongoDB URI to fail")


def test_mongodb_inspect_and_verify_cli_commands_parse() -> None:
    from backend.cli import build_parser

    parser = build_parser()

    inspect_args = parser.parse_args(["inspect-mongodb"])
    verify_args = parser.parse_args(["verify-mongodb-migration", "--code", "000001", "--code", "600001"])

    assert inspect_args.func.__name__ == "cmd_inspect_mongodb"
    assert verify_args.func.__name__ == "cmd_verify_mongodb_migration"
    assert verify_args.code == ["000001", "600001"]


def test_verify_mongodb_migration_reports_counts_indexes_and_continuity() -> None:
    fake_db = FakeMongoDatabase()
    for name in ALL_COLLECTIONS:
        fake_db[name]
    fake_db["datasets"].rows.append({"id": "dragonboard_live"})
    fake_db["snapshot_frames"].rows.extend(
        [
            {
                "datasetId": "dragonboard_live",
                "snapshotId": "s1",
                "type": "half_hour",
                "tradingDate": "2026-05-11",
                "timestamp": 1,
                "stockRowCount": 1,
            },
            {
                "datasetId": "dragonboard_live",
                "snapshotId": "s2",
                "type": "half_hour",
                "tradingDate": "2026-05-12",
                "timestamp": 2,
                "stockRowCount": 1,
            },
        ]
    )
    fake_db["snapshot_stock_rows"].rows.extend(
        [
            {"datasetId": "dragonboard_live", "snapshotId": "s1", "code": "000001", "rank": 3},
            {"datasetId": "dragonboard_live", "snapshotId": "s2", "code": "000001", "rank": 2},
        ]
    )
    fake_db["snapshot_sector_rows"].rows.extend(
        [
            {"datasetId": "dragonboard_live", "snapshotId": "s1", "rowId": "sector-1"},
            {"datasetId": "dragonboard_live", "snapshotId": "s2", "rowId": "sector-2"},
        ]
    )
    fake_db["stock_names"].rows.append({"code": "000001", "active": True})
    for name, indexes in build_mongodb_indexes().items():
        fake_db[name].indexes.extend(indexes)

    result = verify_mongodb_migration(
        fake_db,
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        codes=["000001"],
    )

    assert result["ok"] is True
    assert result["counts"]["snapshot_frames"] == 2
    assert result["indexes"]["missing"] == []
    assert result["continuity"]["emptyFrames"] == []
    assert result["rankSeries"]["000001"]["snapshotCount"] == 2
    assert result["rankSeries"]["000001"]["missingSnapshots"] == []


def test_verify_mongodb_migration_fails_on_missing_rows_and_indexes() -> None:
    fake_db = FakeMongoDatabase()
    fake_db["snapshot_frames"].rows.append(
        {
            "datasetId": "dragonboard_live",
            "snapshotId": "empty",
            "type": "half_hour",
            "tradingDate": "2026-05-12",
            "timestamp": 1,
            "stockRowCount": 1,
        }
    )

    result = verify_mongodb_migration(
        fake_db,
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        codes=["000001"],
    )

    assert result["ok"] is False
    assert result["indexes"]["missing"]
    assert result["continuity"]["emptyFrames"][0]["snapshotId"] == "empty"
    assert result["rankSeries"]["000001"]["missingSnapshots"] == ["empty"]


def _create_minimal_sources(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    snapshot_db = tmp_path / "snapshots.db"
    research_db = tmp_path / "research.db"
    theme_db = tmp_path / "theme.db"
    stock_json = tmp_path / "stock_code.json"
    stock_json.write_text(
        '[{"code":"000001","name":"平安银行","market":"SZ","type":"stock"}]',
        encoding="utf-8",
    )

    with sqlite3.connect(snapshot_db) as conn:
        conn.executescript(
            """
            create table datasets (
              id text primary key,
              name text,
              snapshot_types_json text
            );
            create table snapshot_records (
              id integer primary key,
              dataset_id text,
              snapshot_id text,
              quality_flags_json text
            );
            create table snapshot_frames (
              id integer primary key,
              dataset_id text,
              snapshot_id text,
              trading_date text,
              slot_time text,
              quality_flags_json text,
              metadata_json text
            );
            create table snapshot_stock_rows (
              id integer primary key,
              dataset_id text,
              row_id text,
              snapshot_id text,
              code text,
              themes_json text
            );
            create table snapshot_sector_rows (
              id integer primary key,
              dataset_id text,
              row_id text,
              snapshot_id text,
              entity_key text,
              metadata_json text
            );
            create table archive_manifests (
              id integer primary key,
              archive_id text,
              row_counts_json text
            );
            insert into datasets values ('dragonboard_live','DragonBoard Live','["half_hour"]');
            insert into snapshot_records values (1,'dragonboard_live','half_hour:2026-05-12:15:00','["ok"]');
            insert into snapshot_frames values (1,'dragonboard_live','half_hour:2026-05-12:15:00','2026-05-12','15:00','["ok"]','{"source":"test"}');
            insert into snapshot_stock_rows values (1,'dragonboard_live','row-1','half_hour:2026-05-12:15:00','000001','["银行"]');
            insert into snapshot_sector_rows values (1,'dragonboard_live','sector-1','half_hour:2026-05-12:15:00','bank','{"level":1}');
            insert into archive_manifests values (1,'archive-1','{"snapshot_stock_rows":1}');
            """
        )
    with sqlite3.connect(research_db) as conn:
        conn.executescript(
            """
            create table golden_ranktrend_cases (id text primary key, input_json text, expected_json text);
            create table backtest_runs (id text primary key, request_json text, result_json text);
            create table backtest_trades (id integer primary key, backtest_run_id text, fill_detail_json text);
            create table backtest_equity_curve (id integer primary key, backtest_run_id text);
            create table backtest_signals (id integer primary key, backtest_run_id text, code text, reasons_json text);
            create table backtest_quality_reports (id integer primary key, backtest_run_id text, warnings_json text);
            create table optimization_runs (id text primary key, request_json text, result_json text);
            create table theme_factor_frames (id integer primary key, dataset_id text, quality_flags_json text);
            create table theme_stock_exposures (id integer primary key, dataset_id text, reasons_json text);
            create table theme_signals (id integer primary key, dataset_id text);
            create table theme_quality_reports (id integer primary key, dataset_id text, issues_json text);
            insert into backtest_runs values ('run-1','{}','{}');
            insert into backtest_signals values (1,'run-1','000001','["reason"]');
            """
        )
    with sqlite3.connect(theme_db) as conn:
        conn.executescript(
            """
            create table themes (id text primary key, name text, zs_code text);
            create table theme_stock_mappings (id integer primary key, theme_id text, stock_code text, stock_tags_json text);
            create table theme_metadata (key text primary key, value text);
            insert into themes values ('theme-1','银行','BK0001');
            insert into theme_stock_mappings values (1,'theme-1','000001','[{"Name":"金融"}]');
            insert into theme_metadata values ('version','v1');
            """
        )
    return snapshot_db, research_db, theme_db, stock_json


def _matches(row: dict[str, object], query: dict[str, object]) -> bool:
    for key, expected in query.items():
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$gte" in expected and actual < expected["$gte"]:
                return False
            if "$lte" in expected and actual > expected["$lte"]:
                return False
            if "$lt" in expected and actual >= expected["$lt"]:
                return False
            continue
        if actual != expected:
            return False
    return True
