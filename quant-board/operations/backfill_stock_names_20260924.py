"""历史名称修复（2026-09-24）：占位名称的入库数据从 stock_names 注册集合回填。

范围：
1. `snapshot_stock_rows`：name ∈ {缺失, "", "-"} 的行 → 按 code 批量回填；
2. `hotlist_sentiment`：turnover.newEntryDetails / eliminatedDetails 的 name 同步修正
   （读-改-写 turnover 字段，其他口径不变，不做全量重算）。

只修名称，不动任何其他字段；查不到注册名的保持原样（fail-visible 不伪造）。
跑法：cd quant-board && PYTHONPATH=. ./.venv/Scripts/python.exe operations/backfill_stock_names_20260924.py
"""
from __future__ import annotations

from pymongo import MongoClient

PLACEHOLDERS = ("", "-")


def _needs_fix(name: str) -> bool:
    return name.strip() in PLACEHOLDERS


def main() -> None:
    client = MongoClient("mongodb://127.0.0.1:27017/")
    db = client["dragon_board_quant"]

    # 注册集合 code→name
    name_by_code: dict[str, str] = {}
    for row in db["stock_names"].find({"active": True}, {"code": 1, "name": 1}):
        name = str(row.get("name") or "").strip()
        code = str(row.get("code") or "").strip()
        if name and name not in PLACEHOLDERS and code:
            name_by_code[code] = name
    print(f"registry names: {len(name_by_code)}", flush=True)

    # 1) 缺失行的 code 分布
    missing_by_code = db["snapshot_stock_rows"].aggregate(
        [
            {"$match": {"name": {"$in": list(PLACEHOLDERS) + [None]}}},
            {"$group": {"_id": "$code", "n": {"$sum": 1}}},
        ]
    )
    fixable = {row["_id"]: row["n"] for row in missing_by_code if row["_id"] in name_by_code}
    unfixable = {row["_id"]: row["n"] for row in missing_by_code if row["_id"] not in name_by_code}
    print(f"stock_rows missing-name codes: fixable={len(fixable)} unfixable={len(unfixable)} "
          f"(rows fixable={sum(fixable.values())}, unfixable={sum(unfixable.values())})", flush=True)

    # 2) 按 code 批量回填 snapshot_stock_rows
    updated_rows = 0
    for index, (code, _) in enumerate(sorted(fixable.items()), 1):
        result = db["snapshot_stock_rows"].update_many(
            {"code": code, "name": {"$in": list(PLACEHOLDERS) + [None]}},
            {"$set": {"name": name_by_code[code]}},
        )
        updated_rows += result.modified_count
        if index % 50 == 0:
            print(f"  rows progress {index}/{len(fixable)}", flush=True)
    print(f"stock_rows updated: {updated_rows}", flush=True)

    # 3) 同步 hotlist_sentiment 换手明细（读-改-写 turnover 字段）
    docs = db["hotlist_sentiment"].find(
        {"turnover.newEntryDetails": {"$exists": True}},
        {"_id": 1, "turnover.newEntryDetails": 1, "turnover.eliminatedDetails": 1},
    )
    docs_updated = 0
    names_fixed = 0
    for doc in docs:
        turnover = doc.get("turnover") or {}
        changed = False
        for kind in ("newEntryDetails", "eliminatedDetails"):
            for entry in turnover.get(kind) or []:
                code = str(entry.get("code") or "")
                if _needs_fix(str(entry.get("name") or "")) and code in name_by_code:
                    entry["name"] = name_by_code[code]
                    changed = True
                    names_fixed += 1
        if changed:
            db["hotlist_sentiment"].update_one(
                {"_id": doc["_id"]}, {"$set": {"turnover": turnover}}
            )
            docs_updated += 1
    print(f"hotlist_sentiment docs updated: {docs_updated} (detail names fixed: {names_fixed})", flush=True)
    print("done.", flush=True)


if __name__ == "__main__":
    main()
