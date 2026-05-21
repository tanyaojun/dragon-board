from __future__ import annotations

from backend.data.mongodb_cleanup import plan_mongodb_dataset_cleanup


class DeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class FakeCollection:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []

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


class FakeMongoDatabase(dict[str, FakeCollection]):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def test_mongodb_cleanup_dry_run_preserves_database() -> None:
    db = _seed_database()

    result = plan_mongodb_dataset_cleanup(db, keep_dataset_ids=["dragonboard_live"], apply=False)

    assert result["ok"] is True
    assert result["deleteDatasetIds"] == ["debug_dataset"]
    assert result["counts"]["snapshot_frames"] == 1
    assert result["counts"]["backtest_runs"] == 1
    assert result["counts"]["backtest_result_chunks"] == 1
    assert len(db["datasets"].rows) == 2
    assert len(db["snapshot_frames"].rows) == 2


def test_mongodb_cleanup_apply_deletes_only_non_kept_dataset_and_research_children() -> None:
    db = _seed_database()

    result = plan_mongodb_dataset_cleanup(db, keep_dataset_ids=["dragonboard_live"], apply=True)

    assert result["ok"] is True
    assert result["deleted"]["datasets"] == 1
    assert db["datasets"].rows == [{"id": "dragonboard_live"}]
    assert db["snapshot_frames"].rows == [{"datasetId": "dragonboard_live", "snapshotId": "live-1"}]
    assert db["snapshot_stock_rows"].rows == [{"datasetId": "dragonboard_live", "snapshotId": "live-1"}]
    assert db["backtest_runs"].rows == [{"id": "bt-live", "datasetId": "dragonboard_live"}]
    assert db["backtest_result_chunks"].rows == [{"backtestRunId": "bt-live"}]
    assert db["backtest_signals"].rows == [{"backtestRunId": "bt-live"}]
    assert db["stock_names"].rows == [{"code": "000001"}]
    assert db["themes"].rows == [{"id": "theme-1"}]
    assert db["migration_audit"].rows[-1]["opType"] == "mongodb_dataset_cleanup"


def test_mongodb_cleanup_requires_keep_dataset_ids() -> None:
    result = plan_mongodb_dataset_cleanup(FakeMongoDatabase(), keep_dataset_ids=[], apply=True)

    assert result["ok"] is False
    assert result["error"]["code"] == "missing_keep_dataset_ids"


def test_mongodb_cleanup_cli_parses_as_dry_run_by_default() -> None:
    from backend.cli import build_parser

    args = build_parser().parse_args(["cleanup-mongodb-datasets"])

    assert args.func.__name__ == "cmd_cleanup_mongodb_datasets"
    assert args.keep_dataset_id == ["dragonboard_live"]
    assert args.apply is False


def _seed_database() -> FakeMongoDatabase:
    return FakeMongoDatabase(
        {
            "datasets": FakeCollection([{"id": "dragonboard_live"}, {"id": "debug_dataset"}]),
            "snapshot_records": FakeCollection(
                [
                    {"datasetId": "dragonboard_live", "snapshotId": "live-1"},
                    {"datasetId": "debug_dataset", "snapshotId": "debug-1"},
                ]
            ),
            "snapshot_frames": FakeCollection(
                [
                    {"datasetId": "dragonboard_live", "snapshotId": "live-1"},
                    {"datasetId": "debug_dataset", "snapshotId": "debug-1"},
                ]
            ),
            "snapshot_stock_rows": FakeCollection(
                [
                    {"datasetId": "dragonboard_live", "snapshotId": "live-1"},
                    {"datasetId": "debug_dataset", "snapshotId": "debug-1"},
                ]
            ),
            "snapshot_sector_rows": FakeCollection([{"datasetId": "debug_dataset", "snapshotId": "debug-1"}]),
            "archive_manifests": FakeCollection([{"datasetId": "debug_dataset"}]),
            "backtest_runs": FakeCollection(
                [
                    {"id": "bt-live", "datasetId": "dragonboard_live"},
                    {"id": "bt-debug", "datasetId": "debug_dataset"},
                ]
            ),
            "backtest_trades": FakeCollection([{"backtestRunId": "bt-debug"}]),
            "backtest_result_chunks": FakeCollection([{"backtestRunId": "bt-live"}, {"backtestRunId": "bt-debug"}]),
            "backtest_equity_curve": FakeCollection([{"backtestRunId": "bt-debug"}]),
            "backtest_signals": FakeCollection([{"backtestRunId": "bt-live"}, {"backtestRunId": "bt-debug"}]),
            "backtest_quality_reports": FakeCollection([{"backtestRunId": "bt-debug"}]),
            "golden_ranktrend_cases": FakeCollection([{"datasetId": "debug_dataset"}]),
            "optimization_runs": FakeCollection([{"datasetId": "debug_dataset"}]),
            "theme_factor_frames": FakeCollection([{"datasetId": "debug_dataset"}]),
            "theme_stock_exposures": FakeCollection([{"datasetId": "debug_dataset"}]),
            "theme_signals": FakeCollection([{"datasetId": "debug_dataset"}]),
            "theme_quality_reports": FakeCollection([{"datasetId": "debug_dataset"}]),
            "stock_names": FakeCollection([{"code": "000001"}]),
            "themes": FakeCollection([{"id": "theme-1"}]),
            "theme_stock_mappings": FakeCollection([{"themeId": "theme-1", "stockCode": "000001"}]),
            "theme_metadata": FakeCollection([{"key": "version"}]),
            "migration_audit": FakeCollection([]),
        }
    )


def _matches(row: dict[str, object], query: dict[str, object]) -> bool:
    for key, expected in query.items():
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            continue
        if actual != expected:
            return False
    return True
