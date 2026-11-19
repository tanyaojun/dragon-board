"""MongoDB 测试库构建与卫生工具：dragon_board_quant -> dragon_board_test。

模式（--mode）：
  structure（默认）  不 dump：按生产库在线结构在测试库重建「空集合+索引」+ 基础参照集合
                     全量播种（REFERENCE_COLLECTIONS，约 4MB）；中间产物（frames/records/
                     stock_rows/analysis/backtest 子树等）一律不克隆。
  datasets           定向子集克隆：--datasets a,b [--collections c1,c2]；按集合循环
                     mongodump --query（datasetId/id 字段映射，backtest 子表经 runs 关联），
                     逐集合 archive + restore --drop；--skip-dump=当日同名 per-collection
                     archive 存在则只重放。
  full               全量 dump + restore --drop（历史行为；--skip-dump 复用当日全量 archive）。

附加：
  --prune-residue [--keep-datasets a,b] [--execute]
                     测试库卫生：删除 datasetId 不在 keep 列表的 dataset 文档、各 dataset 键控
                     集合行、backtest runs 及其子表行。默认 dry-run 只统计，--execute 才删。

安全：目标库永远不得是生产库；pytest 进程内拒绝执行（get_mongodb_database 护栏之外的第二道）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCE_DB = "dragon_board_quant"
TARGET_DB = "dragon_board_test"

assert TARGET_DB != SOURCE_DB, "目标库不得等于源库"
assert TARGET_DB != "dragon_board_quant", "目标库不得是生产库"

# 生产库 29 集合（research-20260929-testdb-slim.md A.1 盘点）；structure 模式仍以在线
# list_collection_names 为准， offline 时用本清单兜底，差异打印告警。
PROD_COLLECTIONS = [
    "archive_manifests",
    "backtest_equity_curve",
    "backtest_quality_reports",
    "backtest_result_chunks",
    "backtest_runs",
    "backtest_signals",
    "backtest_trades",
    "datasets",
    "golden_ranktrend_cases",
    "hotlist_sentiment",
    "migration_audit",
    "optimization_runs",
    "snapshot_analysis",
    "snapshot_collector_runs",
    "snapshot_frames",
    "snapshot_records",
    "snapshot_stock_rows",
    "stock_names",
    "theme_metadata",
    "theme_stock_mappings",
    "themes",
    "trade_journal",
]

# datasets 模式的查询字段映射；不在映射内的集合视为非 dataset 键控（跳过并提示）。
DATASET_FIELD = {c: "datasetId" for c in PROD_COLLECTIONS}
DATASET_FIELD["datasets"] = "id"
# backtest 子表按 backtestRunId 关联 runs，datasets 模式单独处理。
BACKTEST_CHILDREN = ["backtest_signals", "backtest_trades", "backtest_equity_curve", "backtest_quality_reports"]

# structure 模式下从源库整体播种的基础参照集合（非 dataset 键控、体积小、业务/测试的
# 名称与映射底表）。用户裁决：瘦身=删中间产物，基础数据集必须保留。
REFERENCE_COLLECTIONS = [
    "stock_names",
    "themes",
    "theme_stock_mappings",
    "theme_metadata",
    "golden_ranktrend_cases",
]


def _mongo(uri: str):
    import pymongo

    return pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)


def _run_tool(exe: Path, args: list[str]) -> None:
    subprocess.run([str(exe), *args], check=True)


def mode_structure(settings, uri: str) -> int:
    client = _mongo(uri)
    source = client[SOURCE_DB]
    target = client[TARGET_DB]
    live = sorted(source.list_collection_names())
    missing = sorted(set(live) ^ set(PROD_COLLECTIONS))
    if missing:
        print(f"告警：在线集合与 PROD_COLLECTIONS 清单差异 {missing}，以在线为准")
    if not live:
        live = sorted(PROD_COLLECTIONS)
        print("源库不可读或为空，按 PROD_COLLECTIONS 兜底重建")
    for name in live:
        coll = source[name]
        if name in target.list_collection_names():
            target[name].drop()
        target.create_collection(name)
        idx_defs = [ix for ix in coll.list_indexes() if ix["name"] != "_id_"]
        for ix in idx_defs:
            kwargs: dict = {"name": ix["name"]}
            if ix.get("unique"):
                kwargs["unique"] = True
            if ix.get("sparse"):
                kwargs["sparse"] = True
            if "expireAfterSeconds" in ix:
                kwargs["expireAfterSeconds"] = ix["expireAfterSeconds"]
            if "partialFilterExpression" in ix:
                kwargs["partialFilterExpression"] = ix["partialFilterExpression"]
            target[name].create_index(list(ix["key"].items()), **kwargs)
        print(f"  重建空集合 {name}（索引 {len(idx_defs)} 个）")
    for name in REFERENCE_COLLECTIONS:
        if name not in live:
            print(f"  跳过参照集合 {name}（源库不存在）")
            continue
        docs = list(source[name].find({}))
        if docs:
            target[name].insert_many(docs)
        print(f"  播种参照集合 {name}：{len(docs)} docs")
    client.close()
    print(f"完成：{TARGET_DB} 重建为「空结构+基础参照」（{len(live)} 集合，参照集合 {len(REFERENCE_COLLECTIONS)} 个已播种）")
    return 0


def mode_datasets(settings, uri: str, tools_bin: Path, datasets: list[str], collections: list[str], skip_dump: bool) -> int:
    if not datasets:
        print("datasets 模式必须提供 --datasets", file=sys.stderr)
        return 1
    mongodump = tools_bin / "mongodump.exe"
    mongorestore = tools_bin / "mongorestore.exe"
    backup_dir = settings.mongodb_backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    client = _mongo(uri)
    source = client[SOURCE_DB]

    run_ids: list[str] = []
    if any(c in BACKTEST_CHILDREN or c == "backtest_runs" for c in collections):
        run_ids = [doc["id"] for doc in source["backtest_runs"].find({"datasetId": {"$in": datasets}}, {"id": 1})]
        print(f"关联 backtest runs：{len(run_ids)} 个")

    for name in collections:
        if name in BACKTEST_CHILDREN:
            if not run_ids:
                print(f"  跳过 {name}（无关联 runs）")
                continue
            query = {"backtestRunId": {"$in": run_ids}}
        elif name in DATASET_FIELD:
            query = {DATASET_FIELD[name]: {"$in": datasets}}
        else:
            print(f"  跳过 {name}（非 dataset 键控集合）")
            continue
        archive = backup_dir / f"{SOURCE_DB}_to_{TARGET_DB}_{name}_{datetime.now():%Y%m%d}.archive.gz"
        if not (skip_dump and archive.exists()):
            print(f"[dump] {name} -> {archive.name}", flush=True)
            _run_tool(
                mongodump,
                [f"--uri={uri}", f"--db={SOURCE_DB}", f"--collection={name}",
                 f"--query={json.dumps(query)}", "--gzip", f"--archive={archive}"],
            )
        print(f"[restore] {name} -> {TARGET_DB}", flush=True)
        _run_tool(
            mongorestore,
            [f"--uri={uri}", "--gzip", f"--archive={archive}",
             f"--nsInclude={SOURCE_DB}.{name}",
             f"--nsFrom={SOURCE_DB}.*", f"--nsTo={TARGET_DB}.*", "--drop"],
        )
        # 注意：--nsFrom/--nsTo 只负责改名不过滤；定向恢复必须配合 --nsInclude，
        # 否则会把整卷 archive 灌进目标库（2026-09-29 实测事故）。
    client.close()
    print("完成：datasets 定向克隆")
    return 0


def mode_full(settings, uri: str, tools_bin: Path, skip_dump: bool) -> int:
    mongodump = tools_bin / "mongodump.exe"
    mongorestore = tools_bin / "mongorestore.exe"
    settings.mongodb_backup_dir.mkdir(parents=True, exist_ok=True)
    archive = settings.mongodb_backup_dir / f"{SOURCE_DB}_to_{TARGET_DB}_{datetime.now():%Y%m%d}.archive.gz"
    if not skip_dump:
        print(f"[1/2] mongodump {SOURCE_DB} -> {archive.name}（gzip archive，11.8GB 数据约几分钟）", flush=True)
        _run_tool(mongodump, [f"--uri={uri}", f"--db={SOURCE_DB}", "--gzip", f"--archive={archive}"])
    else:
        print(f"[1/2] 复用已有 archive：{archive}", flush=True)
        if not archive.exists():
            print(f"archive 不存在：{archive}，请先不带 --skip-dump 执行", file=sys.stderr)
            return 1
    print(f"[2/2] mongorestore -> {TARGET_DB}（--drop 幂等重建）", flush=True)
    _run_tool(
        mongorestore,
        [f"--uri={uri}", "--gzip", f"--archive={archive}",
         f"--nsFrom={SOURCE_DB}.*", f"--nsTo={TARGET_DB}.*", "--drop", "--numParallelCollections=2"],
    )
    print(f"完成：{SOURCE_DB} -> {TARGET_DB}", flush=True)
    return 0


def prune_residue(settings, uri: str, keep: list[str], execute: bool) -> int:
    client = _mongo(uri)
    db = client[TARGET_DB]
    total = 0
    plan: list[tuple[str, dict, int]] = []
    # 1) dataset 键控集合（基础参照集合不参与残留清理，与 structure 播种口径一致）
    for name, field in DATASET_FIELD.items():
        if name in REFERENCE_COLLECTIONS:
            continue
        coll = db[name]
        q = {field: {"$exists": True, "$nin": keep}} if keep else {field: {"$exists": True}}
        n = coll.count_documents(q)
        if n:
            plan.append((name, q, n))
    # 2) backtest 子树：先按 datasetId 圈出待删 runs，再删子表
    runs_q = {"datasetId": {"$exists": True, "$nin": keep}} if keep else {"datasetId": {"$exists": True}}
    doomed_runs = [doc["id"] for doc in db["backtest_runs"].find(runs_q, {"id": 1})]
    for name in BACKTEST_CHILDREN:
        coll = db[name]
        n = coll.count_documents({"backtestRunId": {"$in": doomed_runs}})
        if n:
            plan.append((name, {"backtestRunId": {"$in": doomed_runs}}, n))
    for name, q, n in plan:
        print(f"  {'DELETE' if execute else 'DRY'} {name}: {n} docs  <- {q}")
        total += n
    if execute:
        for name, q, _n in plan:
            result = db[name].delete_many(q)
            if result.deleted_count:
                print(f"  deleted {name}: {result.deleted_count}")
        if doomed_runs:
            r = db["backtest_runs"].delete_many({"id": {"$in": doomed_runs}})
            print(f"  deleted backtest_runs: {r.deleted_count}")
            total += r.deleted_count
        print(f"完成：共删除 {total} docs（keep={keep or '∅'}）")
    else:
        print(f"dry-run：待删 {total} docs；确认后加 --execute。keep 列表={keep or '∅'}")
    client.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="构建/维护 pytest 测试库 dragon_board_test")
    parser.add_argument("--mode", choices=["structure", "datasets", "full"], default="structure")
    parser.add_argument("--datasets", default="", help="逗号分隔 datasetId 列表（datasets 模式）")
    parser.add_argument("--collections", default="", help="逗号分隔集合名（datasets 模式，默认全部 dataset 键控集合）")
    parser.add_argument("--skip-dump", action="store_true", help="full=复用当日全量 archive；datasets=当日 per-collection archive 只重放")
    parser.add_argument("--prune-residue", action="store_true", help="卫生子命令：删除非 keep dataset 的残留")
    parser.add_argument("--keep-datasets", default="", help="prune 保留的 datasetId（逗号分隔，默认空）")
    parser.add_argument("--execute", action="store_true", help="prune-residue 实际删除（默认 dry-run）")
    args = parser.parse_args()

    import os

    if os.environ.get("PYTEST_CURRENT_TEST"):
        print("pytest 进程内禁止执行测试库重建", file=sys.stderr)
        return 1

    from backend.core.settings import get_settings

    settings = get_settings()
    uri = settings.mongodb_uri or "mongodb://127.0.0.1:27017"
    tools_bin = Path(settings.mongodb_tools_bin)

    if args.prune_residue:
        keep = [x for x in args.keep_datasets.split(",") if x]
        return prune_residue(settings, uri, keep, args.execute)

    if args.mode == "structure":
        return mode_structure(settings, uri)
    if args.mode == "datasets":
        collections = [x for x in args.collections.split(",") if x] or [c for c in PROD_COLLECTIONS if c in DATASET_FIELD]
        return mode_datasets(settings, uri, tools_bin, [x for x in args.datasets.split(",") if x], collections, args.skip_dump)
    return mode_full(settings, uri, tools_bin, args.skip_dump)


if __name__ == "__main__":
    raise SystemExit(main())
