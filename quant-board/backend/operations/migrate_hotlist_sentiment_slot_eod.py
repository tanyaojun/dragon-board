"""一次性迁移：存量 hotlist_sentiment EOD 文档 slotTime → "EOD" 哨兵 + drop 旧唯一索引。

识别规则：_id 恰好 3 段（dataset:snapshot_type:date）= EOD 形态；
槽位文档 _id 4 段不动。幂等（已是 "EOD" 的不更新）。
部署硬约束：旧三元组唯一索引 datasetId_1_snapshotType_1_tradingDate_1 必须 drop——
MongoDB create_index 不会自动替换键集不同的唯一索引，旧索引残留时同日第二槽
upsert 会被旧索引拒绝。索引名若与预期不符（命名差异），从 list_indexes 输出人工确认。
用法：cd quant-board && .venv/Scripts/python.exe -m backend.operations.migrate_hotlist_sentiment_slot_eod [--dry-run] [--skip-index-drop]
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

LEGACY_UNIQUE_INDEX_NAME = "datasetId_1_snapshotType_1_tradingDate_1"


def migrate_eod_slot_time(mongo_db: Any, dry_run: bool = False) -> dict[str, Any]:
    coll = mongo_db["hotlist_sentiment"]
    matched = updated = 0
    for row in coll.find({}):
        doc_id = str(row.get("_id") or "")
        if doc_id.count(":") != 2:
            continue  # 槽位文档（4 段）或异常形态不动
        matched += 1
        if str(row.get("slotTime") or "") == "EOD":
            continue
        updated += 1
        if not dry_run:
            coll.update_one({"_id": doc_id}, {"$set": {"slotTime": "EOD"}})
    return {"matched": matched, "updated": updated, "dryRun": dry_run}


def drop_legacy_unique_index(mongo_db: Any) -> dict[str, Any]:
    """drop 旧三元组唯一索引（容错：不存在/命名差异时返回 reason 不抛错）。"""
    coll = mongo_db["hotlist_sentiment"]
    try:
        coll.drop_index(LEGACY_UNIQUE_INDEX_NAME)
        return {"dropped": LEGACY_UNIQUE_INDEX_NAME}
    except Exception as exc:
        return {"dropped": None, "reason": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="hotlist_sentiment EOD slotTime 哨兵迁移")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-index-drop", action="store_true", help="仅迁移数据，不动索引")
    args = parser.parse_args()
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    mongo_db = get_runtime_mongodb_database()
    result = migrate_eod_slot_time(mongo_db, dry_run=args.dry_run)
    print({"migration": result}, file=sys.stderr)
    if not args.skip_index_drop and not args.dry_run:
        print({"indexDrop": drop_legacy_unique_index(mongo_db)}, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
