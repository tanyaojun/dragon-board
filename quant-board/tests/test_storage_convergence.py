from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.cli import build_parser
from backend.data.importers import LevelDbIndexedDbImporter
from backend.data.json_codec import COMPRESSED_TEXT_PREFIX, dumps_json_field, loads_json_field
from backend.data.json_compaction import compact_json_fields
from backend.data.legacy_split_migration import migrate_legacy_db
from backend.data.models import BacktestRun, Base, ResearchBase
from backend.data.storage_inspector import inspect_storage
from backend.settings import Settings


def test_json_codec_compresses_large_json_and_reads_plain_or_broken_text() -> None:
    small = {"ok": True}
    assert not dumps_json_field(small).startswith(COMPRESSED_TEXT_PREFIX)
    assert loads_json_field(json.dumps(small), {}) == small

    large = {"items": [{"code": f"{index:06d}", "name": "样本" * 10} for index in range(300)]}
    encoded = dumps_json_field(large)
    assert encoded.startswith(COMPRESSED_TEXT_PREFIX)
    assert len(encoded) < len(json.dumps(large, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    assert loads_json_field(encoded, {}) == large

    broken = f"{COMPRESSED_TEXT_PREFIX}not-base64"
    assert loads_json_field(broken, {"fallback": True}) == {"fallback": True}


def test_inspect_storage_reports_table_counts_and_json_bytes(tmp_path: Path) -> None:
    db_path = tmp_path / "sample.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table items (id integer primary key, payload_json text, name text)")
        conn.execute("insert into items (payload_json, name) values (?, ?)", (json.dumps({"a": 1}), "one"))
        conn.commit()

    report = inspect_storage(tmp_path)

    db_report = next(item for item in report["databases"] if item["name"] == "sample.db")
    assert db_report["tables"]["items"]["rowCount"] == 1
    assert db_report["jsonFields"]["items.payload_json"]["count"] == 1
    assert db_report["jsonFields"]["items.payload_json"]["totalBytes"] > 0


def test_compact_json_fields_dry_run_and_apply(tmp_path: Path) -> None:
    db_path = tmp_path / "compact.db"
    large = {"items": [{"value": "x" * 200} for _ in range(80)]}
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table backtest_runs (id text primary key, result_json text)")
        conn.execute("insert into backtest_runs (id, result_json) values ('bt_1', ?)", (json.dumps(large),))
        conn.commit()

    dry = compact_json_fields(f"sqlite:///{db_path}", apply=False)
    assert dry["applied"] is False
    assert dry["fields"][0]["candidateRows"] == 1
    assert dry["fields"][0]["estimatedBytesAfter"] < dry["fields"][0]["bytesBefore"]

    applied = compact_json_fields(f"sqlite:///{db_path}", apply=True)
    assert applied["applied"] is True
    assert applied["updatedRows"] == 1

    with sqlite3.connect(db_path) as conn:
        encoded = conn.execute("select result_json from backtest_runs where id='bt_1'").fetchone()[0]
    assert encoded.startswith(COMPRESSED_TEXT_PREFIX)
    assert loads_json_field(encoded, {}) == large


def test_research_session_compresses_large_json_before_flush(tmp_path: Path) -> None:
    db_path = tmp_path / "research_guard.db"
    engine = create_engine(f"sqlite:///{db_path}")
    ResearchBase.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    large = {"items": [{"value": "x" * 200} for _ in range(80)]}
    raw = json.dumps(large)

    with Session() as session:
        session.add(
            BacktestRun(
                id="bt_guard",
                dataset_id="dataset",
                request_json="{}",
                result_json=raw,
            )
        )
        session.commit()

    with sqlite3.connect(db_path) as conn:
        stored = conn.execute("select result_json from backtest_runs where id='bt_guard'").fetchone()[0]

    assert stored.startswith(COMPRESSED_TEXT_PREFIX)
    assert loads_json_field(stored, {}) == large


def test_migrate_legacy_db_splits_snapshot_and_research_without_payload_outbox(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    snapshot = tmp_path / "snapshots.db"
    research = tmp_path / "research.db"
    _create_legacy_db(legacy)
    _create_target_dbs(snapshot, research)

    dry = migrate_legacy_db(
        source=legacy,
        snapshot_database_url=f"sqlite:///{snapshot}",
        research_database_url=f"sqlite:///{research}",
        apply=False,
    )
    assert dry["applied"] is False
    assert dry["plan"]["snapshot_records"] == 1
    assert dry["plan"]["backtest_runs"] == 1

    result = migrate_legacy_db(
        source=legacy,
        snapshot_database_url=f"sqlite:///{snapshot}",
        research_database_url=f"sqlite:///{research}",
        apply=True,
    )
    assert result["applied"] is True
    assert result["migrated"]["snapshot_records"] == 1
    assert result["migrated"]["snapshot_stock_rows"] == 1
    assert result["migrated"]["backtest_runs"] == 1

    with sqlite3.connect(snapshot) as conn:
        assert conn.execute("select count(*) from snapshot_records").fetchone()[0] == 1
        assert conn.execute("select count(*) from snapshot_frames").fetchone()[0] == 1
        assert conn.execute("select count(*) from snapshot_stock_rows").fetchone()[0] == 1
        outbox_columns = [row[1] for row in conn.execute("pragma table_info(sync_outbox)").fetchall()]
        assert "payload_json" not in outbox_columns

    with sqlite3.connect(research) as conn:
        assert conn.execute("select count(*) from backtest_runs").fetchone()[0] == 1


def test_cli_exposes_storage_convergence_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["inspect-storage"]).func.__name__ == "cmd_inspect_storage"
    assert parser.parse_args(["compact-json-fields", "--apply"]).apply is True
    args = parser.parse_args(["migrate-legacy-db", "--source", "data/warehouse/quant_board.db", "--apply"])
    assert args.func.__name__ == "cmd_migrate_legacy_db"
    assert args.apply is True
    verify = parser.parse_args(
        ["verify-snapshot-migration", "--dataset-id", "dragonboard_live", "--source-report", "report.json"]
    )
    assert verify.func.__name__ == "cmd_verify_snapshot_migration"


def test_leveldb_importer_parses_dfindexeddb_jsonl_projection_stores() -> None:
    snapshot_id = "half_hour:2026-04-30:10:00"

    stdout = "\n".join(
        [
            _dfindexeddb_record(
                5,
                {
                    "id": snapshot_id,
                    "snapshotId": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-04-30",
                    "slotTime": "10:00",
                    "timestamp": 1777524000000,
                    "displayKey": snapshot_id,
                    "stockRowCount": 1,
                    "sectorRowCount": 1,
                },
            ),
            _dfindexeddb_record(
                6,
                {
                    "id": f"{snapshot_id}:600001",
                    "snapshotId": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-04-30",
                    "slotTime": "10:00",
                    "timestamp": 1777524000000,
                    "code": "600001",
                    "name": "sample",
                    "rank": 1,
                    "themeHeat": {"__type__": "Undefined"},
                    "themes": {
                        "__type__": "JSArray",
                        "values": [{"__type__": "Undefined"}],
                        "properties": {"0": "AI"},
                    },
                },
            ),
            _dfindexeddb_record(
                7,
                {
                    "id": f"{snapshot_id}:hot_theme:AI",
                    "snapshotId": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-04-30",
                    "slotTime": "10:00",
                    "timestamp": 1777524000000,
                    "entityType": "hot_theme",
                    "entityKey": "AI",
                    "entityName": "AI",
                    "rank": 1,
                    "metadata": {"__type__": "Null"},
                },
            ),
            _dfindexeddb_record(
                5,
                {
                    "snapshotId": "index-row",
                    "type": 1,
                    "tradingDate": "2026-04-30",
                    "timestamp": 1777524000000,
                },
            ),
        ]
    )

    bundle = LevelDbIndexedDbImporter()._parse_dfindexeddb_output(stdout)

    assert len(bundle.records) == 1
    assert len(bundle.frames) == 1
    assert len(bundle.stock_rows) == 1
    assert len(bundle.sector_rows) == 1
    assert bundle.records[0]["id"] == snapshot_id
    assert bundle.frames[0]["snapshotId"] == snapshot_id
    assert bundle.stock_rows[0]["code"] == "600001"
    assert bundle.stock_rows[0]["themeHeat"] is None
    assert bundle.stock_rows[0]["themes"] == ["AI"]
    assert bundle.sector_rows[0]["entityKey"] == "AI"
    assert bundle.sector_rows[0]["metadata"] is None


def test_leveldb_importer_uses_venv_dfindexeddb_console_script() -> None:
    command = LevelDbIndexedDbImporter._dfindexeddb_command(Path("source.leveldb"))

    assert Path(command[0]).name in {"dfindexeddb.exe", "dfindexeddb"}
    assert command[1:] == [
        "db",
        "-s",
        "source.leveldb",
        "--format",
        "chrome",
        "--output",
        "jsonl",
        "--use_sequence_number",
        "--load_blobs",
    ]


def test_settings_ignore_legacy_quant_board_database_url(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_BOARD_DATABASE_URL", "sqlite:///data/warehouse/quant_board.db")
    monkeypatch.delenv("QUANT_BOARD_SNAPSHOT_DATABASE_URL", raising=False)
    settings = Settings()
    assert settings.snapshot_database_url.endswith("quant_board_snapshots.db")
    assert "quant_board.db" not in settings.snapshot_database_url


def _dfindexeddb_record(object_store_id: int, value: dict) -> str:
    return json.dumps(
        {
            "__type__": "ChromiumIndexedDBRecord",
            "object_store_id": object_store_id,
            "value": {"__type__": "ObjectStoreDataValue", "value": value},
        }
    )


def _create_target_dbs(snapshot: Path, research: Path) -> None:
    snapshot_engine = create_engine(f"sqlite:///{snapshot}")
    research_engine = create_engine(f"sqlite:///{research}")
    Base.metadata.create_all(bind=snapshot_engine)
    ResearchBase.metadata.create_all(bind=research_engine)
    snapshot_engine.dispose()
    research_engine.dispose()


def _create_legacy_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            create table datasets (
              id text primary key, name text, source_type text, source_path text, db_name text,
              schema_fingerprint text, snapshot_count integer, frame_count integer, stock_row_count integer,
              sector_row_count integer, start_date text, end_date text, snapshot_types_json text,
              metadata_json text, created_at text
            );
            create table snapshot_records (
              id integer primary key autoincrement, dataset_id text, snapshot_id text, type text,
              trading_date text, slot_time text, timestamp integer, display_key text, capture_mode text,
              captured_at integer, data_timestamp integer, delay_ms integer, quality_flags_json text,
              source text, payload_json text
            );
            create table backtest_runs (
              id text primary key, dataset_id text, strategy_name text, strategy_version text,
              snapshot_type text, config_hash text, random_seed integer, status text,
              request_json text, result_json text, created_at text
            );
            create table optimization_runs (
              id text primary key, dataset_id text, strategy_name text, method text,
              config_hash text, random_seed integer, status text, request_json text,
              result_json text, created_at text
            );
            create table golden_ranktrend_cases (
              id text primary key, name text, dataset_id text, input_json text, expected_json text, created_at text
            );
            create table sync_outbox (
              id integer primary key autoincrement, op_type text, dataset_id text, snapshot_id text,
              idempotency_key text, status text, retry_count integer, last_error text,
              next_retry_at text, created_at text, updated_at text, payload_json text
            );
            """
        )
        payload = {
            "type": "half_hour",
            "tradingDate": "2026-04-30",
            "slotTime": "10:00",
            "timestamp": 1777524000000,
            "hotlist": [{"code": "600001", "name": "样本A", "rank": 1, "price": 10.0}],
            "sectors": [{"entityKey": "theme_a", "entityName": "题材A", "rank": 1}],
        }
        conn.execute(
            "insert into datasets values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "dragonboard_live",
                "live",
                "legacy",
                "",
                "DragonBoardData",
                "fp",
                1,
                1,
                1,
                1,
                "2026-04-30",
                "2026-04-30",
                '["half_hour"]',
                "{}",
                "2026-04-30T10:00:00",
            ),
        )
        conn.execute(
            """
            insert into snapshot_records (
              dataset_id, snapshot_id, type, trading_date, slot_time, timestamp, display_key,
              capture_mode, captured_at, data_timestamp, delay_ms, quality_flags_json, source, payload_json
            ) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "dragonboard_live",
                "half_hour:2026-04-30:10:00",
                "half_hour",
                "2026-04-30",
                "10:00",
                1777524000000,
                "half_hour:2026-04-30:10:00",
                "real_time",
                1777524000000,
                1777524000000,
                0,
                "[]",
                "browser_runtime",
                json.dumps(payload),
            ),
        )
        conn.execute(
            "insert into backtest_runs values (?,?,?,?,?,?,?,?,?,?,?)",
            ("bt_1", "dragonboard_live", "rank_trend_candidate", "0.1.0", "half_hour", "cfg", 1, "completed", "{}", "{\"ok\":true}", "2026-04-30T10:00:00"),
        )
        conn.commit()
