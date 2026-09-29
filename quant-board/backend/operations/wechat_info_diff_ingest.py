# -*- coding: utf-8 -*-
"""微信「个股信息差」入库 runner：发现(--discover)或手动(--url) → 解析 → 匹配代码
→ 直接更新 theme_stock_mappings.stockReason（不建新集合、不存任何抓取元数据）。

写入语义：
- 该集合每股一题材一条（多题材=多条），同一 stockCode 的全部映射条目统一更新；
- 当日信息差文本**前置**进 stockReason，原业务底座描述保留在其后（不毁底座）；
- 幂等：existing 已含当日文本则跳过（内容判重，不引入任何标记词）；
- 集合每日 00:30 由上游刷新重置，本写入天然按日滚动。
"""
from __future__ import annotations

import argparse
import datetime
import re

from backend.operations.wechat_info_diff import (
    SOURCE_NAME,
    article_text,
    discover_latest_article,
    fetch_html,
    parse_info_diff_entries,
    title_month_day,
)


def _db():
    """运行时库入口：经 repository_factory 吃 settings（URI/库名），pytest 下受护栏约束。
    禁止硬编码 MongoClient 直连生产库（2026-09-29 隔离裁决）。"""
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    return get_runtime_mongodb_database()


def match_codes(db, names: list[str]) -> dict[str, str]:
    out = {}
    for name in names:
        hit = db["stock_names"].find_one({"name": name, "type": "stock"}, {"code": 1})
        if hit:
            out[name] = hit["code"]
    return out


def merge_reason(existing: str | None, diff_text: str) -> str:
    """当日信息差前置进 stockReason，原业务底座保留；已含同段文本则原样返回（幂等）。"""
    old = (existing or "").lstrip("；")
    if diff_text in old:
        return old
    return f"{diff_text}；{old}" if old else diff_text


def ingest(db, url: str, date: str, discovery_title: str | None = None) -> dict:
    html = fetch_html(url)
    text = article_text(html)
    entries = parse_info_diff_entries(text)
    if not entries:
        return {"status": "no_entries", "entries": 0, "matched": 0, "unmatched": 0}
    codes = match_codes(db, [e["name"] for e in entries])
    matched = unmatched = 0
    updates: list[tuple] = []
    for e in entries:
        code = codes.get(e["name"])
        if not code:
            unmatched += 1
            continue
        matched += 1
        for doc in db["theme_stock_mappings"].find({"stockCode": code}, {"_id": 1, "stockReason": 1}):
            updates.append((doc["_id"], merge_reason(doc.get("stockReason"), e["reason"])))
    # 先收集后统一写：边遍历游标边改同集合会导致 document move / 游标失效跳文档
    for _id, reason in updates:
        db["theme_stock_mappings"].update_one({"_id": _id}, {"$set": {"stockReason": reason}})
    return {"status": "ok", "entries": len(entries), "matched": matched, "unmatched": unmatched}


def ingest_today_if_published(today_iso: str | None = None) -> dict:
    """采集器调度入口：发现最新一篇 → 标题日期==今天才入库，否则视为"今日未发布"。"""
    today = today_iso or datetime.date.today().isoformat()
    try:
        url, title = discover_latest_article()
        md = title_month_day(title)
        now = datetime.date.today()
        if md != (now.month, now.day):
            return {"status": "not_published", "title": title}
        result = ingest(_db(), url, today, discovery_title=title)
        return {"status": result["status"], "title": title, "entries": result["entries"],
                "matched": result["matched"]}
    except Exception as exc:  # noqa: BLE001 — 调度器要求任何失败都结构化返回
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:200]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="手动提供文章 URL")
    ap.add_argument("--discover", action="store_true", help="搜狗自动发现最新一篇")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    args = ap.parse_args()
    db = _db()
    if args.url:
        result = ingest(db, args.url, args.date)
    elif args.discover:
        url, title = discover_latest_article()
        print(f"发现: {title} -> {url[:80]}")
        result = ingest(db, url, args.date, discovery_title=title)
    else:
        ap.error("需要 --url 或 --discover")
    print(f"[{args.date}] {SOURCE_NAME}: entries={result['entries']} matched={result['matched']} "
          f"unmatched={result['unmatched']} -> theme_stock_mappings.stockReason")
