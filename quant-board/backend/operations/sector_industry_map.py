# -*- coding: utf-8 -*-
"""action 板块名 → 韭研产业库一级节点 映射（V3-2，板块节点三期全成分增强）。

两套名录（对拍 2026-10-25：近 20 交易日 52 板块名 → 24 自动 / 2 多义 / 26 未收录）：
- action 池板块名 = 市场流式题材名（粗粒度，含「公告/新股」等非产业桶）；
- 产业库 108 一级节点 = AI 维护稳定树（国产机器人/特斯拉机器人…细分）。

规则（冻结，V3 预登记 §映射）：
1. 停用词（公告/其他/新股/次新）直接未收录——防未来产业名漂移误配；
2. 精确同名 → exact；
3. 双向包含且唯一 → contains；
4. 双向包含多命中 → multi-union（全部候选并集——action 粗粒度板块天然跨产业细分，
   如 机器人 → 国产机器人+特斯拉机器人+机器人零部件+四股机器人）；
5. 其余未收录（读数层 fail-visible 标注，不静默丢行）。

manual 行（--set 人工固化）不被 rebuild 覆盖；产业库新增节点后 rebuild 幂等重放，
diff 新增建议（exact/contains/multi-union 扩并集）。
集合 `sector_industry_mapping`：_id=action 板块名。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from typing import Any

from backend.operations.jiuyan_theme_store import COLLECTION_INDUSTRY_STOCKS

COLLECTION = "sector_industry_mapping"

# 永不映射的 action 桶（对拍 2026-10-25 实证全无匹配；防御未来产业名漂移）
EXCLUDE_BOARDS = {"公告", "其他", "新股", "次新", "ST", "B股", "转债"}


def suggest_for(board: str, industry_names: list[str]) -> dict | None:
    """单板块名映射建议：{matchType, codes} 或 None（未收录）。纯函数。"""
    if board in EXCLUDE_BOARDS:
        return None
    if board in industry_names:
        return {"matchType": "exact", "codes": [board]}
    hits = sorted({n for n in industry_names if board in n or n in board})
    if not hits:
        return None
    if len(hits) == 1:
        return {"matchType": "contains", "codes": hits}
    return {"matchType": "multi-union", "codes": hits}


def level1_industries(db: Any) -> list[dict]:
    """产业库一级节点 [{code, name}]（树缺失=空清单，调用方 fail-visible）。"""
    return [{"code": str(d["_id"]), "name": str(d.get("name") or "")}
            for d in db[COLLECTION_INDUSTRY_STOCKS].find(
                {"level": 1}, {"name": 1, "level": 1})]


def rebuild(db: Any, boards: list[str]) -> dict:
    """对板块名集合幂等重建 auto 映射（manual 行不动）。返回 diff 摘要。"""
    # 空串过滤（review P4-3）：set(boards) 计入空串而循环 continue 跳过，
    # mapped 计数会虚增 1
    boards = sorted({b for b in boards if b})
    industries = level1_industries(db)
    names = [i["name"] for i in industries]
    name_by_code = {i["name"]: i["code"] for i in industries}
    if not industries:
        return {"ok": False, "reason": "产业成分库未初始化（先跑 --stock-tree）",
                "mapped": 0, "unmapped": list(boards), "added": [], "changed": []}
    added: list[str] = []
    changed: list[str] = []
    unmapped: list[str] = []
    for board in sorted(set(boards)):
        if not board:
            continue
        existing = db[COLLECTION].find_one({"_id": board}) or {}
        if existing.get("matchType") == "manual":
            continue
        sug = suggest_for(board, names)
        if sug is None:
            if existing:
                db[COLLECTION].delete_one({"_id": board})
                changed.append(f"-{board}")
            unmapped.append(board)
            continue
        codes = [name_by_code[n] for n in sug["codes"]]
        if existing.get("industryCodes") == codes and existing.get("matchType") == sug["matchType"]:
            continue
        if not existing:
            added.append(board)
        else:
            changed.append(board)
        db[COLLECTION].replace_one(
            {"_id": board},
            {"_id": board, "board": board, "industryCodes": codes,
             "industryNames": sug["codes"], "matchType": sug["matchType"],
             "mappedAt": existing.get("mappedAt") or _now(), "updatedAt": _now()},
            upsert=True)
    return {"ok": True, "industries": len(industries), "boards": len(set(boards)),
            "mapped": len(set(boards)) - len(unmapped), "added": added,
            "changed": changed, "unmapped": unmapped}


def manual_set(db: Any, board: str, names_or_codes: list[str]) -> dict:
    """人工固化映射（产业名或 code 均可）；空清单=删除该行（回 auto/未收录）。"""
    industries = level1_industries(db)
    by_name = {i["name"]: i["code"] for i in industries}
    by_code = {i["code"]: i["name"] for i in industries}
    codes, names = [], []
    for x in names_or_codes:
        if x in by_code:
            codes.append(x)
            names.append(by_code[x])
        elif x in by_name:
            codes.append(by_name[x])
            names.append(x)
        else:
            return {"ok": False, "error": f"产业库无此节点: {x}"}
    if not codes:
        db[COLLECTION].delete_one({"_id": board})
        return {"ok": True, "deleted": board}
    db[COLLECTION].replace_one(
        {"_id": board},
        {"_id": board, "board": board, "industryCodes": codes, "industryNames": names,
         "matchType": "manual", "mappedAt": _now(), "updatedAt": _now()},
        upsert=True)
    return {"ok": True, "board": board, "industryCodes": codes, "industryNames": names}


def mapping_of(db: Any, board: str) -> dict | None:
    doc = db[COLLECTION].find_one({"_id": board})
    if not doc:
        return None
    return {"codes": [str(c) for c in doc.get("industryCodes") or []],
            "names": [str(n) for n in doc.get("industryNames") or []],
            "matchType": str(doc.get("matchType") or "")}


def static_members(db: Any, board: str) -> dict:
    """板块的静态全成分并集（映射到的各产业成分去重，同股取关联最强人次）。

    返回 {mapped, codes, industries, batchDates, sharesMedian}；未映射
    {mapped: False, reason}；成分库空批次如实披露（不伪空成功）。
    """
    mp = mapping_of(db, board)
    if not mp:
        return {"mapped": False, "reason": "产业库未收录"}
    best: dict[str, dict] = {}
    industries: list[str] = []
    batch_dates: list[str] = []
    for code in mp["codes"]:
        doc = db[COLLECTION_INDUSTRY_STOCKS].find_one({"_id": code}) or {}
        stocks = doc.get("stocks") or []
        if not stocks:
            continue
        industries.append(f"{doc.get('name') or code}({len(stocks)})")
        batch_dates.append(str(doc.get("batchDate") or "?"))
        for s in stocks:
            c = str(s.get("code") or "")
            if not c:
                continue
            cur = best.get(c)
            if cur is None or (s.get("sharesRange") or -1.0) > (cur.get("sharesRange") or -1.0):
                best[c] = s
    if not best:
        return {"mapped": True, "reason": "映射产业成分快照为空（未拉或空批次）",
                "codes": set(), "industries": mp["names"], "batchDates": []}
    shares = [s["sharesRange"] for s in best.values() if s.get("sharesRange") is not None]
    return {"mapped": True, "codes": set(best), "industries": industries,
            "batchDates": sorted(set(batch_dates)),
            "sharesMedian": round(statistics.median(shares), 2) if shares else None}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _recent_boards(db: Any, days: int = 0) -> list[str]:
    """近 N 个交易日的 action 板块名（rebuild 扫描域）。

    days=0（默认）=全史（review P3-3：只扫近 20 日时，更老板块的 auto 行在
    产业库换名录后会静默残留脏映射；全史文档 ~130 日毫秒级，无成本）。
    """
    from backend.operations.sector_nodes import COLLECTION as NODES_COLLECTION
    cur = db[NODES_COLLECTION].find({}, {"rows.board": 1, "aggExtraRows.board": 1}
                                    ).sort("_id", -1)
    if days:
        cur = cur.limit(days)
    boards: set[str] = set()
    for doc in cur:
        for r in doc.get("rows") or []:
            if r.get("board"):
                boards.add(str(r["board"]))
        for r in doc.get("aggExtraRows") or []:
            if r.get("board"):
                boards.add(str(r["board"]))
    return sorted(boards)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="action 板块名→产业库映射（V3-2）")
    ap.add_argument("--rebuild", action="store_true",
                    help="对近 N 交易日板块名重建 auto 映射（manual 不动）")
    ap.add_argument("--days", type=int, default=0,
                    help="rebuild 扫描域（默认 0=全史，防老 auto 行脏映射残留）")
    ap.add_argument("--set", dest="manual", default=None,
                    help="人工固化：板块名=产业名1,产业名2（空值=删除回 auto）")
    ap.add_argument("--list", action="store_true", help="打印当前映射全表")
    args = ap.parse_args(argv)

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    out: dict[str, Any] = {}
    if args.rebuild:
        boards = _recent_boards(db, args.days)
        out = rebuild(db, boards)
    if args.manual:
        board, _, rest = args.manual.partition("=")
        out = manual_set(db, board.strip(), [x.strip() for x in rest.split(",") if x.strip()])
    if args.list or not (args.rebuild or args.manual):
        rows = list(db[COLLECTION].find({}, {"_id": 0}).sort("_id", 1))
        out["list"] = [{"board": r["board"], "matchType": r["matchType"],
                        "industryNames": r.get("industryNames")}
                       for r in rows]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
