# -*- coding: utf-8 -*-
"""存量 EOD 语料代际打标（2026-10-22 日级语料修复配套，additive-only）。

背景：72 篇存量 EOD 文档在日级语料修复前生成，`evidenceRaw=None`，无法从当前帧复现
（07-01 15:00 帧在 EOD 生成后又被回填）。本工具不改写叙事/答案/证据，只加两个字段：

- `corpusCaliberVersion`：`legacy_unversioned`（无 questionSetVersion，07–08 月）
  或 `v2.5_pre_eod_fix`（有 v2.5 戳、语料仍是修复前结构）；
- `evidenceRawUnavailable=true`：明确「历史证据未落档」，不伪造 evidenceRaw。

幂等：已带 `corpusCaliberVersion` 或已有 `evidenceRaw` 的新代文档一律跳过。

用法：
    python -m backend.operations.tag_eod_corpus_caliber --dry-run   # 缺省只打印计划
    python -m backend.operations.tag_eod_corpus_caliber --apply     # 落库
"""
from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

LEGACY_TAG = "legacy_unversioned"


def _tag_for(doc: dict) -> str | None:
    if doc.get("corpusCaliberVersion"):
        return None
    if doc.get("evidenceRaw") is not None:
        return None  # 新代文档已自带证据，不冒充「不可用」
    version = doc.get("questionSetVersion")
    return f"{version}_pre_eod_fix" if version else LEGACY_TAG


def plan_tags(db: Any, dataset_id: str = "dragonboard_live") -> dict:
    """返回 {total, toTag, byTag, updates}；updates=[{_id,tradingDate,set}]。"""
    docs = list(db["hotlist_jev_sentiment"].find(
        {"kind": "eod", "datasetId": dataset_id}))
    updates: list[dict] = []
    for doc in docs:
        tag = _tag_for(doc)
        if tag is None:
            continue
        updates.append({
            "_id": doc.get("_id"),
            "tradingDate": doc.get("tradingDate"),
            "set": {"corpusCaliberVersion": tag, "evidenceRawUnavailable": True},
        })
    return {
        "total": len(docs),
        "toTag": len(updates),
        "byTag": dict(Counter(row["set"]["corpusCaliberVersion"] for row in updates)),
        "updates": updates,
    }


def apply_tags(db: Any, updates: list[dict]) -> int:
    written = 0
    for row in updates:
        result = db["hotlist_jev_sentiment"].update_one(
            {"_id": row["_id"]}, {"$set": row["set"]})
        written += int(getattr(result, "modified_count", 0) or 0)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="存量 EOD 语料代际打标（additive-only）")
    parser.add_argument("--dataset-id", default="dragonboard_live")
    parser.add_argument("--apply", action="store_true", help="落库（缺省只打印计划）")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    plan = plan_tags(db, dataset_id=args.dataset_id)
    print(f"dataset={args.dataset_id} EOD 文档 {plan['total']} 篇，待打标 {plan['toTag']} 篇；"
          f"分代 {plan['byTag']}")
    for row in plan["updates"]:
        print(f"  {row['tradingDate']} {row['_id']} → {row['set']['corpusCaliberVersion']}")
    if not args.apply:
        print("dry 模式（--apply 落库；只加 corpusCaliberVersion/evidenceRawUnavailable）")
        return
    written = apply_tags(db, plan["updates"])
    print(f"已打标 {written} 篇（幂等重跑应显示待打标 0）")


if __name__ == "__main__":
    main()