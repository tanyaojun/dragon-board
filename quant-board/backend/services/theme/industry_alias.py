# -*- coding: utf-8 -*-
"""KPL 题材名 ↔ 韭研产业库节点 对照层（治理 P4，2026-10-25）。

用户要求：「KPL 题材名称尽量和 jiuyan 板块保持一致，因为大盘情绪和题材情绪
要综合考量」——落地为**对照桥**而非物理改名：KPL 侧（themes/sector_rows 热度
体系）保持 KPL 官方名，jiuyan 侧（板块节点/情绪面板）保持 jiuyan 名，本层把
两者接起来；物理改名会破坏 KPL 上游对齐（08:30 刷新按官方名覆盖），被否。

引擎与规则照搬 sector_industry_map（板块节点 V3 实证范式，冻结）：
1. 停用词（公告/其他/新股/次新…）直接未收录；
2. 精确同名（归一后）→ exact；
3. 双向包含且唯一 → contains；
4. 双向包含多命中 → multi-union（KPL 粗粒度题材天然跨产业细分，
   如「机器人」→ 国产机器人+特斯拉机器人+机器人零部件+四股机器人）；
5. 其余未收录（fail-visible 标注，不静默丢行）。

方向：`themes`（KPL 251 名录）→ `jiuyan_industry_stocks` 一级节点（108 产业）。
manual 行（--set）不被 rebuild 覆盖。集合 `theme_industry_mapping`：_id=KPL 题材名。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from typing import Any

from backend.operations.jiuyan_theme_store import COLLECTION_INDUSTRY_STOCKS

COLLECTION = "theme_industry_mapping"

# 永不映射的词（对拍防御：防未来产业名漂移误配；与 sector_industry_map 同源）
EXCLUDE_WORDS = {"公告", "其他", "新股", "次新", "ST", "B股", "转债", "其他相关"}


def _normalize(value: Any) -> str:
    name = str(value or "").strip()
    for suffix in ("概念板块", "概念", "板块"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def suggest_for(theme_name: str, industry_names: list[str]) -> dict | None:
    """单题材名映射建议：{matchType, names} 或 None（未收录）。纯函数（V3 同款）。"""
    name = _normalize(theme_name)
    if not name or name in EXCLUDE_WORDS:
        return None
    norm_industries = {_normalize(n): n for n in industry_names}
    if name in norm_industries:
        return {"matchType": "exact", "names": [norm_industries[name]]}
    hits = sorted({orig for nn, orig in norm_industries.items() if nn in name or name in nn})
    if not hits:
        return None
    if len(hits) == 1:
        return {"matchType": "contains", "names": hits}
    return {"matchType": "multi-union", "names": hits}


def level1_industries(db: Any) -> list[dict]:
    """产业库一级节点 [{code, name}]（树缺失=空清单，调用方 fail-visible）。"""
    return [{"code": str(d["_id"]), "name": str(d.get("name") or "")}
            for d in db[COLLECTION_INDUSTRY_STOCKS].find(
                {"level": 1}, {"name": 1, "level": 1})]


def rebuild(db: Any, theme_names: list[str]) -> dict:
    """对 KPL 题材名集合幂等重建 auto 映射（manual 行不动）。返回 diff 摘要。"""
    theme_names = sorted({t for t in theme_names if str(t or "").strip()})
    industries = level1_industries(db)
    if not industries:
        return {"ok": False, "reason": "产业成分库未初始化（先跑 sector_industry_map --stock-tree 侧）",
                "mapped": 0, "unmapped": list(theme_names), "added": [], "changed": []}
    names = [i["name"] for i in industries]
    added: list[str] = []
    changed: list[str] = []
    unmapped: list[str] = []
    for theme_name in theme_names:
        existing = db[COLLECTION].find_one({"_id": theme_name}) or {}
        if existing.get("matchType") == "manual":
            continue
        sug = suggest_for(theme_name, names)
        if sug is None:
            if existing:
                db[COLLECTION].delete_one({"_id": theme_name})
                changed.append(f"-{theme_name}")
            unmapped.append(theme_name)
            continue
        if existing.get("industryNames") == sug["names"] and existing.get("matchType") == sug["matchType"]:
            continue
        if not existing:
            added.append(theme_name)
        else:
            changed.append(theme_name)
        db[COLLECTION].replace_one(
            {"_id": theme_name},
            {"_id": theme_name, "theme": theme_name, "industryNames": sug["names"],
             "matchType": sug["matchType"],
             "mappedAt": existing.get("mappedAt") or _now(), "updatedAt": _now()},
            upsert=True)
    return {"ok": True, "industries": len(industries), "themes": len(theme_names),
            "mapped": len(theme_names) - len(unmapped),
            "added": added, "changed": changed, "unmapped": unmapped}


def manual_set(db: Any, theme_name: str, industry_list: list[str]) -> dict:
    """人工固化映射（产业名须在产业库一级节点）；空清单=删除该行。"""
    industries = level1_industries(db)
    valid = {i["name"] for i in industries}
    for x in industry_list:
        if x not in valid:
            return {"ok": False, "error": f"产业库无此一级节点: {x}"}
    if not industry_list:
        db[COLLECTION].delete_one({"_id": theme_name})
        return {"ok": True, "deleted": theme_name}
    db[COLLECTION].replace_one(
        {"_id": theme_name},
        {"_id": theme_name, "theme": theme_name, "industryNames": industry_list,
         "matchType": "manual", "mappedAt": _now(), "updatedAt": _now()},
        upsert=True)
    return {"ok": True, "theme": theme_name, "industryNames": industry_list}


def mapping_of(db: Any, theme_name: str) -> dict | None:
    doc = db[COLLECTION].find_one({"_id": theme_name})
    if not doc:
        return None
    return {"names": [str(n) for n in doc.get("industryNames") or []],
            "matchType": str(doc.get("matchType") or "")}


def effective_mapping_of(db: Any, theme_name: str) -> dict | None:
    """生效对照：直接映射优先；无映射且属官方背书家族（治理层 familyLinks
    child→parent）时继承父题材对照（matchType 加注 family_inherit）。"""
    direct = mapping_of(db, theme_name)
    if direct is not None:
        return direct
    from backend.services.theme.dict_governance import load_governance

    gov = load_governance(db)
    parent = gov.family_links.get(_normalize(theme_name))
    if parent:
        inherited = mapping_of(db, parent)
        if inherited is not None:
            return {"names": inherited["names"],
                    "matchType": f"family_inherit<{parent}>"}
    return None


def kpl_theme_names(db: Any) -> list[str]:
    """KPL 题材名全集（themes 集合，排除治理层非题材）。"""
    from backend.services.theme.dict_governance import load_governance

    gov = load_governance(db)
    out = []
    for t in db["themes"].find({}, {"name": 1}):
        name = str(t.get("name") or "").strip()
        if name and _normalize(name) not in gov.exclude_names:
            out.append(name)
    return out


def daban_theme_names(db: Any) -> list[str]:
    """打板页题材词表（2026-11-14 竞价试盘页治理闭环新增）：auction_trial_raw 全日档
    rows 的 bk_name 归一去重（去尾部计数括号「半导体(3)」→「半导体」+ _normalize
    去 概念/板块 后缀），排除事件桶停用词（EXCLUDE_WORDS）与治理层非题材。

    背景：themes 名录（252）不覆盖打板页题材词表——P4 桥初建时 48 只未分组股的
    bk_name 仅命中 2（勘察 §6.3 排查结论）。本词表让 rebuild 把打板侧新题材纳入
    同一治理闭环（auto 建桥 / unmapped 披露人工裁决），不再依赖读口运行时实时
    suggest。集合空 → 空清单（调用方 fail-visible，不静默）。"""
    from backend.services.theme.dict_governance import load_governance

    gov = load_governance(db)
    out: set[str] = set()
    # rows 是 code→row 动态 map，dotted projection（rows.bk_name）对 map 键不生效，
    # 整 rows 取回后提取（60 日 × ~百行 × 15 列，量级可控）
    for doc in db["auction_trial_raw"].find({}, {"rows": 1}):
        for row in (doc.get("rows") or {}).values():
            bk = str((row or {}).get("bk_name") or "").strip()
            if not bk:
                continue
            bk = re.sub(r"（[^（]*）$|\([^)]*\)$", "", bk).strip()
            name = _normalize(bk)
            if name and name not in EXCLUDE_WORDS and name not in gov.exclude_names:
                out.add(name)
    return sorted(out)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="KPL 题材名↔韭研产业库对照层（治理 P4）")
    ap.add_argument("--rebuild", action="store_true",
                    help="对 themes 全名录重建 auto 映射（manual 不动）")
    ap.add_argument("--rebuild-daban", dest="rebuild_daban", action="store_true",
                    help="themes 名录 ∪ 打板页题材词表（auction_trial_raw bk_name）重建 auto 映射（manual 不动）")
    ap.add_argument("--set", dest="manual", default=None,
                    help="人工固化：题材名=产业名1,产业名2（空值=删除回 auto）")
    ap.add_argument("--list", action="store_true", help="打印当前映射全表")
    args = ap.parse_args(argv)

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    out: dict[str, Any] = {}
    if args.rebuild:
        out = rebuild(db, kpl_theme_names(db))
    if args.rebuild_daban:
        out = rebuild(db, sorted(set(kpl_theme_names(db)) | set(daban_theme_names(db))))
    if args.manual:
        theme, _, rest = args.manual.partition("=")
        out = manual_set(db, theme.strip(), [x.strip() for x in rest.split(",") if x.strip()])
    if args.list or not (args.rebuild or args.manual):
        rows = list(db[COLLECTION].find({}, {"_id": 0}).sort("_id", 1))
        out["list"] = [{"theme": r["theme"], "matchType": r["matchType"],
                        "industryNames": r.get("industryNames")} for r in rows]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main())
