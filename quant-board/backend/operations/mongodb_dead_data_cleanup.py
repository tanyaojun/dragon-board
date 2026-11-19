"""一次性 MongoDB 死数据清理（默认 dry-run，显式 --apply 才执行）。

对应 2026-09-16 冗余清理设计（docs/superpowers/specs/2026-09-16-mongodb-backup-
mongodump-cleanup-design.md 第 6 节），三个独立子步骤：

1. drop 死集合：全仓库（含 git 历史）零代码引用的 7 个集合；drop 前逐集合 mongodump。
2. 数据集残留清理：ds_ffa379a00efe47d0（SQLite 导入测试）、dragonboard_backend_shadow
   （空壳元数据）复用 plan_mongodb_dataset_cleanup；另删 five_minute 单日实验 records
   及其关联 frames/rows。
3. 删旧研究 run（resultChunked 且 createdAt 早于时间边界，默认 2026-09-01，
   可用 --purge-result-chunks-before 覆盖）的 backtest_result_chunks 文档；
   run 元数据保留，读取路径返回结构化 resultPurged 标记。删前按 runId 条件 mongodump。

apply 时产物备份到 data/backups/mongodb/pre-cleanup-<ts>/，结果写 migration_audit
（opType=mongodb_dead_data_cleanup）。数据级行删除由全量兜底备份（backup-mongodb --full）
覆盖，属于第二重保险。
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from backend.core.settings import get_settings
from backend.data.backup.mongodb_backup import build_mongodump_args
from backend.data.migrations.mongodb_cleanup import plan_mongodb_dataset_cleanup

# 死集合：全仓库零代码引用（2026-09-16 审计），drop 前逐集合 mongodump。
DEAD_COLLECTIONS: tuple[str, ...] = (
    "big_order_attempts",
    "big_order_current",
    "big_order_revisions",
    "live_refresh_attempts",
    "live_refresh_rounds",
    "live_refresh_state",
    "theme_market_rows",
)

KEEP_DATASET_IDS = ["dragonboard_live"]

# five_minute 粒度已废止（2026-07-29 单日实验残留），按 type 清理 records 及关联行
FIVE_MINUTE_RECORD_TYPE = "five_minute"
SNAPSHOT_CHILD_COLLECTIONS = (
    "snapshot_records",
    "snapshot_frames",
    "snapshot_stock_rows",
)

# 结果 chunks 只清 2026-06~08 旧研究 run（run 元数据保留，读取返回 resultPurged 标记）
PURGE_RESULT_CHUNKS_BEFORE = datetime(2026, 9, 1)
RESULT_CHUNK_COLLECTION = "backtest_result_chunks"

# 单独 --compact 时（无删除步骤可关联）的默认目标：历史上大规模删除的热点集合
COMPACT_CANDIDATE_COLLECTIONS: tuple[str, ...] = (
    "snapshot_records",
    "snapshot_frames",
    "snapshot_stock_rows",
    "backtest_result_chunks",
    "backtest_signals",
)

DumpRunner = Callable[[list[str]], int]


def _utc_now_text() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def plan_dead_data_cleanup(
    database: Any,
    *,
    drop_dead_collections: bool = False,
    cleanup_datasets: bool = False,
    purge_result_chunks: bool = False,
    purge_result_chunks_before: datetime | None = None,
    compact: bool = False,
    apply: bool = False,
    dump_runner: DumpRunner | None = None,
    pre_cleanup_root: Path | None = None,
) -> dict[str, Any]:
    """预览/执行死数据清理。默认 dry-run；--apply 时先 dump 再删并写审计。

    ``purge_result_chunks_before`` 覆盖 chunks 清理的时间边界（默认
    ``PURGE_RESULT_CHUNKS_BEFORE``=2026-09-01）；边界只作用于 resultChunked
    run 的 createdAt，run 元数据一律保留。
    """
    if not (drop_dead_collections or cleanup_datasets or purge_result_chunks or compact):
        return {
            "ok": False,
            "apply": apply,
            "error": {"code": "no_cleanup_steps_selected"},
        }

    settings = get_settings()
    steps: dict[str, Any] = {}
    if drop_dead_collections:
        steps["dropDeadCollections"] = _preview_dead_collections(database)
    if cleanup_datasets:
        steps["cleanupDatasets"] = _preview_dataset_residue(database)
    if purge_result_chunks:
        steps["purgeResultChunks"] = _preview_result_chunks(
            database, purge_result_chunks_before or PURGE_RESULT_CHUNKS_BEFORE
        )
    if compact:
        steps["compact"] = _preview_compact(
            database,
            drop_dead_collections=drop_dead_collections,
            cleanup_datasets=cleanup_datasets,
            purge_result_chunks=purge_result_chunks,
        )

    if not apply:
        return {"ok": True, "apply": False, "steps": steps}

    backup_root = Path(pre_cleanup_root) if pre_cleanup_root else settings.mongodb_backup_dir
    backup_dir = backup_root / f"pre-cleanup-{_utc_now_text()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for step in steps.values():
        step["backupDir"] = str(backup_dir)

    runner = dump_runner or _make_subprocess_dump_runner()

    if drop_dead_collections:
        steps["dropDeadCollections"] = _apply_drop_dead_collections(
            database, steps["dropDeadCollections"], backup_dir=backup_dir, runner=runner
        )
    if cleanup_datasets:
        steps["cleanupDatasets"] = _apply_cleanup_datasets(database, steps["cleanupDatasets"])
    if purge_result_chunks:
        steps["purgeResultChunks"] = _apply_purge_result_chunks(
            database,
            steps["purgeResultChunks"],
            backup_dir=backup_dir,
            runner=runner,
            mongodump_bin=settings.mongodb_tools_bin / "mongodump.exe",
            mongo_uri=settings.mongodb_uri,
            mongo_database=settings.mongodb_database,
        )
    if compact:
        steps["compact"] = _apply_compact(database, steps["compact"])

    ok = all(bool(step.get("ok")) for step in steps.values())
    database["migration_audit"].insert_many(
        [
            {
                "opType": "mongodb_dead_data_cleanup",
                "idempotencyKey": f"mongodb_dead_data_cleanup:{_utc_now_text()}",
                "createdAt": datetime.now(UTC).replace(tzinfo=None),
                "ok": ok,
                "keepDatasetIds": KEEP_DATASET_IDS,
                "steps": steps,
            }
        ],
        ordered=False,
    )
    return {"ok": ok, "apply": True, "steps": steps}


# --------------------------------------------------------------------- 预览


def _preview_dead_collections(database: Any) -> dict[str, Any]:
    collections = []
    for name in DEAD_COLLECTIONS:
        count = int(database[name].count_documents({}))
        if count > 0:
            collections.append({"name": name, "count": count})
    return {"ok": True, "collections": collections}


def _preview_dataset_residue(database: Any) -> dict[str, Any]:
    dataset_cleanup = plan_mongodb_dataset_cleanup(
        database, keep_dataset_ids=KEEP_DATASET_IDS, apply=False
    )
    five_minute_ids = _five_minute_snapshot_ids(database)
    return {
        "ok": True,
        "datasetCleanup": {
            "deleteDatasetIds": dataset_cleanup["deleteDatasetIds"],
            "counts": dataset_cleanup["counts"],
        },
        "fiveMinute": {
            "snapshotIdCount": len(five_minute_ids),
            "counts": _five_minute_counts(database, five_minute_ids),
        },
    }


def _preview_result_chunks(database: Any, cutoff: datetime | None = None) -> dict[str, Any]:
    before = cutoff or PURGE_RESULT_CHUNKS_BEFORE
    run_ids = _purgeable_run_ids(database, before)
    chunk_count = int(
        database[RESULT_CHUNK_COLLECTION].count_documents({"backtestRunId": {"$in": run_ids}})
    )
    return {
        "ok": True,
        "before": before.isoformat(),
        "purgedRunIds": run_ids,
        "chunkCount": chunk_count,
        "runMetadataKept": True,
    }


# --------------------------------------------------------------------- 执行


def _apply_drop_dead_collections(
    database: Any,
    preview: dict[str, Any],
    *,
    backup_dir: Path,
    runner: DumpRunner,
) -> dict[str, Any]:
    settings = get_settings()
    dumped: dict[str, int] = {}
    dropped: list[str] = []
    failed: list[dict[str, Any]] = []
    for item in preview["collections"]:
        name = str(item["name"])
        cmd = build_mongodump_args(
            mongodump_bin=settings.mongodb_tools_bin / "mongodump.exe",
            mongo_uri=settings.mongodb_uri,
            database=settings.mongodb_database,
            out_dir=backup_dir,
            collection=name,
        )
        returncode = runner(cmd)
        if returncode != 0:
            failed.append({"name": name, "returncode": returncode})
            continue
        dumped[name] = int(item["count"])
        database[name].drop()
        dropped.append(name)
    return {
        "ok": not failed,
        "backupDir": str(backup_dir),
        "dropped": dropped,
        "predumpCounts": dumped,
        **({"failed": failed} if failed else {}),
        "collections": preview["collections"],
    }


def _apply_cleanup_datasets(database: Any, preview: dict[str, Any]) -> dict[str, Any]:
    dataset_cleanup = plan_mongodb_dataset_cleanup(
        database, keep_dataset_ids=KEEP_DATASET_IDS, apply=True
    )
    five_minute_ids = _five_minute_snapshot_ids(database)
    deleted = {"snapshot_records": int(
        database["snapshot_records"].delete_many({"type": FIVE_MINUTE_RECORD_TYPE}).deleted_count
    )}
    for name in ("snapshot_frames", "snapshot_stock_rows"):
        deleted[name] = int(
            database[name].delete_many({"snapshotId": {"$in": five_minute_ids}}).deleted_count
        )
    return {
        "ok": bool(dataset_cleanup.get("ok")),
        "datasetCleanup": {
            "deleteDatasetIds": dataset_cleanup.get("deleteDatasetIds"),
            "deleted": dataset_cleanup.get("deleted"),
        },
        "fiveMinute": {
            "snapshotIdCount": len(five_minute_ids),
            "deleted": deleted,
        },
    }


def _apply_purge_result_chunks(
    database: Any,
    preview: dict[str, Any],
    *,
    backup_dir: Path,
    runner: DumpRunner,
    mongodump_bin: Path,
    mongo_uri: str,
    mongo_database: str,
) -> dict[str, Any]:
    run_ids = list(preview["purgedRunIds"])
    deleted_chunks = 0
    dump_failed = False
    if run_ids:
        cmd = build_mongodump_args(
            mongodump_bin=mongodump_bin,
            mongo_uri=mongo_uri,
            database=mongo_database,
            out_dir=backup_dir,
            collection=RESULT_CHUNK_COLLECTION,
            query={"backtestRunId": {"$in": run_ids}},
        )
        returncode = runner(cmd)
        if returncode != 0:
            return {
                "ok": False,
                "purgedRunIds": [],
                "deletedChunks": 0,
                "error": {
                    "code": "predump_failed",
                    "returncode": returncode,
                },
            }
        result = database[RESULT_CHUNK_COLLECTION].delete_many({"backtestRunId": {"$in": run_ids}})
        deleted_chunks = int(result.deleted_count)
        dump_failed = returncode != 0
    return {
        "ok": not dump_failed,
        "purgedRunIds": run_ids,
        "deletedChunks": deleted_chunks,
        "runMetadataKept": True,
    }


# --------------------------------------------------------------------- compact


def _compact_targets(
    database: Any,
    *,
    drop_dead_collections: bool,
    cleanup_datasets: bool,
    purge_result_chunks: bool,
) -> list[str]:
    """compact 目标 = 行删除涉及但未 drop 的集合（drop 集合由文件释放，无需 compact）；
    单独 --compact 无删除步骤可关联时，对历史大删除热点集合执行。"""
    targets: list[str] = []
    if cleanup_datasets:
        targets.extend(SNAPSHOT_CHILD_COLLECTIONS)
    if purge_result_chunks:
        targets.append(RESULT_CHUNK_COLLECTION)
    if not targets and not drop_dead_collections:
        targets.extend(COMPACT_CANDIDATE_COLLECTIONS)
    return list(dict.fromkeys(targets))


def _preview_compact(
    database: Any,
    *,
    drop_dead_collections: bool,
    cleanup_datasets: bool,
    purge_result_chunks: bool,
) -> dict[str, Any]:
    targets = _compact_targets(
        database,
        drop_dead_collections=drop_dead_collections,
        cleanup_datasets=cleanup_datasets,
        purge_result_chunks=purge_result_chunks,
    )
    return {
        "ok": True,
        "collections": [{"name": name} for name in targets],
    }


def _apply_compact(database: Any, preview: dict[str, Any]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in preview["collections"]:
        name = str(item["name"])
        try:
            command_result = database.command("compact", name)
            results.append(
                {
                    "name": name,
                    "ok": True,
                    "bytesFreed": int(command_result.get("bytesFreed") or 0),
                }
            )
        except Exception as exc:
            results.append({"name": name, "ok": False, "error": str(exc)})
    return {
        "ok": all(item["ok"] for item in results),
        "collections": results,
    }


# --------------------------------------------------------------------- 辅助


def _make_subprocess_dump_runner() -> DumpRunner:
    def run(cmd: list[str]) -> int:
        completed = subprocess.run(cmd, capture_output=True, text=True)
        if completed.returncode != 0:
            print(f"mongodump failed rc={completed.returncode}: {completed.stderr[-500:]}")
        return completed.returncode

    return run


def _five_minute_snapshot_ids(database: Any) -> list[str]:
    return sorted(
        str(row.get("snapshotId") or "")
        for row in database["snapshot_records"].find({"type": FIVE_MINUTE_RECORD_TYPE})
        if row.get("snapshotId")
    )


def _five_minute_counts(database: Any, snapshot_ids: list[str]) -> dict[str, int]:
    counts = {
        "snapshot_records": int(
            database["snapshot_records"].count_documents({"type": FIVE_MINUTE_RECORD_TYPE})
        )
    }
    for name in ("snapshot_frames", "snapshot_stock_rows"):
        counts[name] = int(database[name].count_documents({"snapshotId": {"$in": snapshot_ids}}))
    return counts


def _purgeable_run_ids(database: Any, cutoff: datetime | None = None) -> list[str]:
    before = cutoff or PURGE_RESULT_CHUNKS_BEFORE
    return sorted(
        str(row.get("id") or "")
        for row in database["backtest_runs"].find(
            {"resultChunked": True, "createdAt": {"$lt": before}}
        )
        if row.get("id")
    )
