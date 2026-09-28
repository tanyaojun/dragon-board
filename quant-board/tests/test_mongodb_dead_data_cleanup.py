from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.operations.mongodb_dead_data_cleanup import (
    COMPACT_CANDIDATE_COLLECTIONS,
    DEAD_COLLECTIONS,
    plan_dead_data_cleanup,
)


class DeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class FakeCollection:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []
        self.dropped = False

    def count_documents(self, query: dict[str, object]) -> int:
        return len(self.find(query))

    def find(self, query: dict[str, object] | None = None) -> list[dict[str, object]]:
        return [row for row in self.rows if _matches(row, query or {})]

    def delete_many(self, query: dict[str, object]) -> DeleteResult:
        before = len(self.rows)
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return DeleteResult(before - len(self.rows))

    def insert_many(self, rows: list[dict[str, object]], ordered: bool = False) -> None:
        assert ordered is False
        self.rows.extend(rows)

    def drop(self) -> None:
        self.rows = []
        self.dropped = True


class FakeMongoDatabase(dict[str, FakeCollection]):
    def __init__(self, initial: dict[str, FakeCollection] | None = None) -> None:
        super().__init__(initial or {})
        self.commands: list[tuple[str, str]] = []

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)

    def command(self, command_name: str, collection_name: str) -> dict[str, object]:
        self.commands.append((command_name, collection_name))
        return {"bytesFreed": 1024}


class FakeDumpRunner:
    """记录 mongodump 命令并可模拟失败。"""

    def __init__(self, fail_collections: set[str] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.fail_collections = fail_collections or set()

    def __call__(self, cmd: list[str]) -> int:
        self.commands.append(list(cmd))
        if "--collection" in cmd:
            name = cmd[cmd.index("--collection") + 1]
            if name in self.fail_collections:
                return 2
        return 0


def _seed_database() -> FakeMongoDatabase:
    old_chunked = {
        "id": "bt_old_1",
        "datasetId": "dragonboard_live",
        "resultChunked": True,
        "resultChunkCount": 3,
        "createdAt": datetime(2026, 6, 7, 4, 29),
    }
    new_chunked = {
        "id": "bt_new_1",
        "datasetId": "dragonboard_live",
        "resultChunked": True,
        "resultChunkCount": 2,
        "createdAt": datetime(2026, 9, 10, 8, 0),
    }
    plain = {
        "id": "bt_plain_1",
        "datasetId": "dragonboard_live",
        "resultChunked": False,
        "createdAt": datetime(2026, 6, 8, 9, 0),
    }
    return FakeMongoDatabase(
        {
            "datasets": FakeCollection(
                [
                    {"id": "dragonboard_live"},
                    {"id": "ds_ffa379a00efe47d0"},
                    {"id": "dragonboard_backend_shadow"},
                ]
            ),
            "big_order_attempts": FakeCollection([{"_id": i} for i in range(3)]),
            "big_order_current": FakeCollection([{"_id": 1}]),
            "big_order_revisions": FakeCollection([{"_id": i} for i in range(2)]),
            "live_refresh_attempts": FakeCollection([{"_id": 1}]),
            "live_refresh_rounds": FakeCollection([{"_id": 1}]),
            "live_refresh_state": FakeCollection([{"_id": 1}]),
            "theme_market_rows": FakeCollection([{"_id": 1}]),
            "snapshot_records": FakeCollection(
                [
                    {"snapshotId": "fm-1", "type": "five_minute"},
                    {"snapshotId": "fm-2", "type": "five_minute"},
                    {"snapshotId": "hh-live", "type": "half_hour", "datasetId": "dragonboard_live"},
                ]
            ),
            "snapshot_frames": FakeCollection(
                [
                    {"snapshotId": "fm-1"},
                    {"snapshotId": "hh-live"},
                ]
            ),
            "snapshot_stock_rows": FakeCollection(
                [
                    {"snapshotId": "fm-2", "datasetId": "dragonboard_live"},
                    {"snapshotId": "hh-live", "datasetId": "dragonboard_live"},
                    {"snapshotId": "ds-row", "datasetId": "ds_ffa379a00efe47d0"},
                ]
            ),
            "backtest_runs": FakeCollection([old_chunked, new_chunked, plain]),
            "backtest_result_chunks": FakeCollection(
                [{"backtestRunId": "bt_old_1", "sequence": 0}]
                + [{"backtestRunId": "bt_new_1", "sequence": i} for i in range(2)]
            ),
        }
    )


def test_dead_collections_preview_lists_counts_without_dropping() -> None:
    db = _seed_database()

    result = plan_dead_data_cleanup(db, drop_dead_collections=True, apply=False)

    assert result["ok"] is True
    assert result["apply"] is False
    step = result["steps"]["dropDeadCollections"]
    assert {item["name"] for item in step["collections"]} == set(DEAD_COLLECTIONS)
    assert all(item["count"] > 0 for item in step["collections"])
    assert not any(db[name].dropped for name in DEAD_COLLECTIONS)
    assert len(db["big_order_attempts"].rows) == 3


def test_apply_drops_dead_collections_with_per_collection_dump(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "backend.operations.mongodb_dead_data_cleanup._utc_now_text",
        lambda: "20260916T150000Z",
    )
    db = _seed_database()
    runner = FakeDumpRunner()

    result = plan_dead_data_cleanup(
        db,
        drop_dead_collections=True,
        apply=True,
        dump_runner=runner,
        pre_cleanup_root=tmp_path,
    )

    step = result["steps"]["dropDeadCollections"]
    assert step["ok"] is True
    assert step["dropped"] == sorted(DEAD_COLLECTIONS)
    assert all(db[name].dropped for name in DEAD_COLLECTIONS)
    dumped = {cmd[cmd.index("--collection") + 1] for cmd in runner.commands}
    assert dumped == set(DEAD_COLLECTIONS)
    backup_dir = tmp_path / "pre-cleanup-20260916T150000Z"
    assert backup_dir.is_dir()
    # 审计
    audit = db["migration_audit"].rows[-1]
    assert audit["opType"] == "mongodb_dead_data_cleanup"
    assert audit["steps"]["dropDeadCollections"]["dropped"] == sorted(DEAD_COLLECTIONS)
    assert audit["steps"]["dropDeadCollections"]["backupDir"].endswith("pre-cleanup-20260916T150000Z")


def test_apply_skips_drop_and_reports_when_predump_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "backend.operations.mongodb_dead_data_cleanup._utc_now_text",
        lambda: "20260916T150100Z",
    )
    db = _seed_database()
    runner = FakeDumpRunner(fail_collections={"big_order_current"})

    result = plan_dead_data_cleanup(
        db,
        drop_dead_collections=True,
        apply=True,
        dump_runner=runner,
        pre_cleanup_root=tmp_path,
    )

    step = result["steps"]["dropDeadCollections"]
    assert step["ok"] is False
    assert "big_order_current" in [item["name"] for item in step["failed"]]
    assert db["big_order_current"].dropped is False
    assert len(db["big_order_current"].rows) == 1
    # dump 成功的集合仍被 drop
    assert db["big_order_attempts"].dropped is True


def test_cleanup_datasets_removes_test_residue_and_five_minute_records(tmp_path: Path) -> None:
    db = _seed_database()

    result = plan_dead_data_cleanup(db, cleanup_datasets=True, apply=True, pre_cleanup_root=tmp_path)

    step = result["steps"]["cleanupDatasets"]
    assert step["ok"] is True
    assert step["datasetCleanup"]["deleted"]["datasets"] == 2
    remaining = [row["id"] for row in db["datasets"].rows]
    assert remaining == ["dragonboard_live"]
    # ds 残留行删除
    assert all(row["datasetId"] != "ds_ffa379a00efe47d0" for row in db["snapshot_stock_rows"].rows)
    # five_minute 残留删除：records + 关联 frames/rows
    assert [row["snapshotId"] for row in db["snapshot_records"].rows] == ["hh-live"]
    assert [row["snapshotId"] for row in db["snapshot_frames"].rows] == ["hh-live"]
    assert all(row["snapshotId"] != "fm-2" for row in db["snapshot_stock_rows"].rows)
    audit = db["migration_audit"].rows[-1]
    assert audit["opType"] == "mongodb_dead_data_cleanup"
    assert audit["steps"]["cleanupDatasets"]["fiveMinute"]["deleted"] == {
        "snapshot_records": 2,
        "snapshot_frames": 1,
        "snapshot_stock_rows": 1,
        "snapshot_sector_rows": 0,
    }


def test_purge_result_chunks_only_removes_old_runs_and_keeps_run_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "backend.operations.mongodb_dead_data_cleanup._utc_now_text",
        lambda: "20260916T150200Z",
    )
    db = _seed_database()
    runner = FakeDumpRunner()

    result = plan_dead_data_cleanup(
        db,
        purge_result_chunks=True,
        apply=True,
        dump_runner=runner,
        pre_cleanup_root=tmp_path,
    )

    step = result["steps"]["purgeResultChunks"]
    assert step["ok"] is True
    assert step["purgedRunIds"] == ["bt_old_1"]
    assert step["deletedChunks"] == 1
    # run 元数据保留
    assert {row["id"] for row in db["backtest_runs"].rows} == {"bt_old_1", "bt_new_1", "bt_plain_1"}
    # 只有旧 run 的 chunks 被删
    assert [row["backtestRunId"] for row in db["backtest_result_chunks"].rows] == ["bt_new_1", "bt_new_1"]
    # 条件 dump 覆盖被删 runIds
    assert any("--query" in cmd for cmd in runner.commands)
    query_arg = next(cmd[cmd.index("--query") + 1] for cmd in runner.commands if "--query" in cmd)
    assert "bt_old_1" in query_arg
    audit = db["migration_audit"].rows[-1]
    assert audit["steps"]["purgeResultChunks"]["purgedRunIds"] == ["bt_old_1"]


def test_dry_run_records_nothing_and_deletes_nothing(tmp_path: Path) -> None:
    db = _seed_database()
    runner = FakeDumpRunner()

    result = plan_dead_data_cleanup(
        db,
        drop_dead_collections=True,
        cleanup_datasets=True,
        purge_result_chunks=True,
        apply=False,
        dump_runner=runner,
        pre_cleanup_root=tmp_path,
    )

    assert result["ok"] is True
    assert result["apply"] is False
    assert runner.commands == []
    assert len(db["migration_audit"].rows) == 0
    assert not any(db[name].dropped for name in DEAD_COLLECTIONS)
    assert len(db["datasets"].rows) == 3


def test_compact_runs_on_row_deletion_targets_after_apply(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "backend.operations.mongodb_dead_data_cleanup._utc_now_text",
        lambda: "20260916T160000Z",
    )
    db = _seed_database()

    result = plan_dead_data_cleanup(
        db,
        cleanup_datasets=True,
        purge_result_chunks=True,
        compact=True,
        apply=True,
        dump_runner=FakeDumpRunner(),
        pre_cleanup_root=tmp_path,
    )

    step = result["steps"]["compact"]
    assert step["ok"] is True
    # 目标 = 行删除涉及但未 drop 的集合；drop 的死集合不进 compact
    assert [item["name"] for item in step["collections"]] == [
        "snapshot_records",
        "snapshot_frames",
        "snapshot_stock_rows",
        "snapshot_sector_rows",
        "backtest_result_chunks",
    ]
    assert all(item["ok"] for item in step["collections"])
    assert db.commands == [
        ("compact", "snapshot_records"),
        ("compact", "snapshot_frames"),
        ("compact", "snapshot_stock_rows"),
        ("compact", "snapshot_sector_rows"),
        ("compact", "backtest_result_chunks"),
    ]
    audit = db["migration_audit"].rows[-1]
    assert audit["steps"]["compact"]["collections"][0]["name"] == "snapshot_records"


def test_compact_dry_run_lists_targets_without_running_command(tmp_path: Path) -> None:
    db = _seed_database()

    result = plan_dead_data_cleanup(
        db,
        purge_result_chunks=True,
        compact=True,
        apply=False,
        pre_cleanup_root=tmp_path,
    )

    step = result["steps"]["compact"]
    assert step["ok"] is True
    assert [item["name"] for item in step["collections"]] == ["backtest_result_chunks"]
    assert db.commands == []


def test_compact_alone_uses_candidate_collection_list(tmp_path: Path) -> None:
    db = _seed_database()

    result = plan_dead_data_cleanup(db, compact=True, apply=True, pre_cleanup_root=tmp_path)

    step = result["steps"]["compact"]
    assert step["ok"] is True
    assert {item["name"] for item in step["collections"]} == set(COMPACT_CANDIDATE_COLLECTIONS)
    assert len(db.commands) == len(COMPACT_CANDIDATE_COLLECTIONS)


def test_compact_failure_is_structured_and_marks_step_failed(tmp_path: Path) -> None:
    db = _seed_database()

    def failing_command(command_name: str, collection_name: str) -> dict[str, object]:
        raise RuntimeError("compact interrupted")

    db.command = failing_command  # type: ignore[method-assign]

    result = plan_dead_data_cleanup(db, compact=True, apply=True, pre_cleanup_root=tmp_path)

    step = result["steps"]["compact"]
    assert step["ok"] is False
    assert all(item["ok"] is False for item in step["collections"])
    assert all("compact interrupted" in item["error"] for item in step["collections"])
    assert result["ok"] is False


def test_dead_data_cleanup_cli_parses_dry_run_by_default() -> None:
    from backend.cli import build_parser

    args = build_parser().parse_args(
        ["cleanup-mongodb-dead-data", "--drop-dead-collections", "--cleanup-datasets"]
    )

    assert args.func.__name__ == "cmd_cleanup_mongodb_dead_data"
    assert args.drop_dead_collections is True
    assert args.cleanup_datasets is True
    assert args.purge_result_chunks is False
    assert args.compact is False
    assert args.apply is False


def test_dead_data_cleanup_cli_parses_compact_flag() -> None:
    from backend.cli import build_parser

    args = build_parser().parse_args(["cleanup-mongodb-dead-data", "--compact"])

    assert args.compact is True
    assert args.apply is False


def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$lt" in expected and not (actual is not None and actual < expected["$lt"]):
                return False
        elif actual != expected:
            return False
    return True

def test_purge_result_chunks_cutoff_is_overridable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "backend.operations.mongodb_dead_data_cleanup._utc_now_text",
        lambda: "20260928T080000Z",
    )
    db = _seed_database()
    runner = FakeDumpRunner()

    # 默认边界 2026-09-01：只清 bt_old_1；边界推到 2026-10-01 后 bt_new_1 一并清
    default_result = plan_dead_data_cleanup(
        db, purge_result_chunks=True, apply=False, pre_cleanup_root=tmp_path
    )
    assert default_result["steps"]["purgeResultChunks"]["purgedRunIds"] == ["bt_old_1"]
    assert default_result["steps"]["purgeResultChunks"]["before"] == "2026-09-01T00:00:00"

    extended = plan_dead_data_cleanup(
        db,
        purge_result_chunks=True,
        purge_result_chunks_before=datetime(2026, 10, 1),
        apply=True,
        dump_runner=runner,
        pre_cleanup_root=tmp_path,
    )
    step = extended["steps"]["purgeResultChunks"]
    assert step["ok"] is True
    assert step["purgedRunIds"] == ["bt_new_1", "bt_old_1"]
    assert step["deletedChunks"] == 3
    # run 元数据保留，chunks 全清
    assert [row["backtestRunId"] for row in db["backtest_result_chunks"].rows] == []
    assert {row["id"] for row in db["backtest_runs"].rows} == {"bt_old_1", "bt_new_1", "bt_plain_1"}
    query_arg = next(cmd[cmd.index("--query") + 1] for cmd in runner.commands if "--query" in cmd)
    assert "bt_new_1" in query_arg


def test_dead_data_cleanup_cli_parses_purge_cutoff() -> None:
    from backend.cli import build_parser

    args = build_parser().parse_args(
        ["cleanup-mongodb-dead-data", "--purge-result-chunks", "--purge-result-chunks-before", "2026-09-25"]
    )
    assert args.purge_result_chunks is True
    assert args.purge_result_chunks_before == "2026-09-25"
