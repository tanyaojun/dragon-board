from __future__ import annotations

from backend.data.mongodb_research_repair import repair_mongodb_research_metadata


class UpdateResult:
    def __init__(self, matched_count: int, modified_count: int) -> None:
        self.matched_count = matched_count
        self.modified_count = modified_count


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

    def update_many(self, query: dict[str, object], update: dict[str, object]) -> UpdateResult:
        matched = 0
        modified = 0
        for row in self.rows:
            if not _matches(row, query):
                continue
            matched += 1
            before = repr(row)
            for key, value in dict(update.get("$set") or {}).items():
                _set_path(row, key, value)
            if repr(row) != before:
                modified += 1
        return UpdateResult(matched, modified)

    def insert_many(self, rows: list[dict[str, object]], ordered: bool = False) -> None:
        assert ordered is False
        self.rows.extend(rows)


class FakeMongoDatabase(dict[str, FakeCollection]):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def test_research_repair_dry_run_reports_without_mutating() -> None:
    db = _seed_database()

    result = repair_mongodb_research_metadata(db, apply=False)

    assert result["ok"] is True
    assert result["apply"] is False
    assert result["counts"]["theme_factor_frames"] == 2
    assert result["counts"]["missingBacktestStatus"] == 2
    assert result["counts"]["optimizationTrialBacktests"] == 1
    assert db["theme_factor_frames"].count_documents({}) == 3
    assert db["backtest_runs"].rows[0]["status"] is None
    assert "artifact_type" not in db["backtest_runs"].rows[1]["request"]


def test_research_repair_apply_deletes_test_theme_rows_and_marks_backtests() -> None:
    db = _seed_database()

    result = repair_mongodb_research_metadata(db, apply=True)

    assert result["ok"] is True
    assert result["deleted"]["theme_factor_frames"] == 2
    assert result["updated"]["backtestStatus"] == 2
    assert result["updated"]["optimizationTrialBacktests"] == 1
    assert db["theme_factor_frames"].rows == [{"datasetId": "dragonboard_live"}]
    assert all(row["status"] == "completed" for row in db["backtest_runs"].rows)
    trial_request = db["backtest_runs"].rows[1]["request"]
    assert trial_request["artifact_type"] == "optimization_trial"
    assert trial_request["artifactType"] == "optimization_trial"
    assert db["backtest_runs"].rows[1]["artifactType"] == "optimization_trial"
    assert db["migration_audit"].rows[-1]["opType"] == "mongodb_research_metadata_repair"


def test_repair_mongodb_research_metadata_cli_parses_as_dry_run_by_default() -> None:
    from backend.cli import build_parser

    args = build_parser().parse_args(["repair-mongodb-research-metadata"])

    assert args.func.__name__ == "cmd_repair_mongodb_research_metadata"
    assert args.apply is False


def _seed_database() -> FakeMongoDatabase:
    return FakeMongoDatabase(
        {
            "theme_factor_frames": FakeCollection(
                [
                    {"datasetId": "ds_test"},
                    {"datasetId": "ds_compress"},
                    {"datasetId": "dragonboard_live"},
                ]
            ),
            "theme_stock_exposures": FakeCollection([{"datasetId": "ds_test"}]),
            "theme_signals": FakeCollection([{"datasetId": "ds_test"}]),
            "theme_quality_reports": FakeCollection([{"datasetId": "ds_test"}, {"datasetId": "ds_v12"}]),
            "backtest_runs": FakeCollection(
                [
                    {"id": "bt_normal", "datasetId": "dragonboard_live", "status": None, "request": {}},
                    {
                        "id": "bt_trial",
                        "datasetId": "dragonboard_live",
                        "request": {"optimization_run_id": "opt_1", "trial_id": "trial_0001"},
                    },
                    {"id": "bt_done", "datasetId": "dragonboard_live", "status": "completed", "request": {}},
                ]
            ),
            "migration_audit": FakeCollection([]),
        }
    )


def _matches(row: dict[str, object], query: dict[str, object]) -> bool:
    for key, expected in query.items():
        if key == "$or":
            return any(_matches(row, item) for item in expected)
        actual = _get_path(row, key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$exists" in expected and (actual is not _MISSING) is not bool(expected["$exists"]):
                return False
            continue
        if actual is _MISSING or actual != expected:
            return False
    return True


_MISSING = object()


def _get_path(row: dict[str, object], key: str) -> object:
    current: object = row
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _set_path(row: dict[str, object], key: str, value: object) -> None:
    current = row
    parts = key.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value
