# -*- coding: utf-8 -*-
"""微信「个股信息差」入库 runner：发现(--discover)或手动(--url) → 解析 → 匹配 → stock_info_diff。

用法（Git Bash）：
  ./.venv/Scripts/python.exe -u -m backend.operations.wechat_info_diff_ingest --discover
  ./.venv/Scripts/python.exe -u -m backend.operations.wechat_info_diff_ingest \
      --url "https://mp.weixin.qq.com/s/xxxx" --date 2026-09-28

存储：stock_info_diff（_id={date}:{code}，unmatched 用 {date}:un:{idx}；meta 文档 _id={date}:_meta）。
stock_rows 不动（槽级快照 + Supabase 同构契约）；消费端（jev 驱动打标/研究）按 code join。
"""
from __future__ import annotations

import argparse
import datetime
import time

from pymongo import MongoClient

from backend.operations.wechat_info_diff import (
    SOURCE_NAME,
    article_text,
    discover_latest_article,
    fetch_html,
    parse_info_diff_entries,
)


def match_codes(names: list[str]) -> dict[str, str]:
    db = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)["dragon_board_quant"]
    out = {}
    for name in names:
        hit = db["stock_names"].find_one({"name": name, "type": "stock"}, {"code": 1})
        if hit:
            out[name] = hit["code"]
    return out


def ingest(url: str, date: str, discovery_title: str | None = None):
    db = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)["dragon_board_quant"]
    col = db["stock_info_diff"]
    html = fetch_html(url)
    text = article_text(html)
    entries = parse_info_diff_entries(text)
    codes = match_codes([e["name"] for e in entries])
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    source = f"{SOURCE_NAME}（搜狗发现）" if discovery_title else SOURCE_NAME

    meta = {"_id": f"{date}:_meta", "tradingDate": date, "sourceName": source, "sourceUrl": url,
            "articleTitle": discovery_title or "", "entries": len(entries),
            "matched": sum(1 for e in entries if e["name"] in codes),
            "unmatched": sum(1 for e in entries if e["name"] not in codes),
            "rawText": text[:20000], "status": "ok" if entries else "no_entries", "createdAt": now}
    col.replace_one({"_id": meta["_id"]}, meta, upsert=True)

    un_idx = 0
    for e in entries:
        code = codes.get(e["name"])
        _id = f"{date}:{code}" if code else f"{date}:un:{un_idx}"
        if not code:
            un_idx += 1
        col.replace_one({"_id": _id}, {
            "_id": _id, "tradingDate": date, "code": code, "name": e["name"],
            "reasonText": e["reason"], "matchStatus": "matched" if code else "unmatched",
            "sourceName": source, "sourceUrl": url, "createdAt": now}, upsert=True)
    print(f"[{date}] entries={len(entries)} matched={meta['matched']} unmatched={meta['unmatched']} -> stock_info_diff")
    for e in entries:
        mark = codes.get(e["name"], "unmatched")
        print(f"  {e['name']:8} -> {mark:8} | {e['reason'][:50]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="手动提供文章 URL")
    ap.add_argument("--discover", action="store_true", help="搜狗自动发现最新一篇")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    args = ap.parse_args()
    if args.url:
        ingest(args.url, args.date)
    elif args.discover:
        url, title = discover_latest_article()
        print(f"发现: {title} -> {url[:80]}")
        m = __import__("re").search(r"(\d{1,2})\.(\d{1,2})个股信息差", title)
        date = args.date
        if m:
            date = f"{datetime.date.today().year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        ingest(url, date, discovery_title=title)
    else:
        ap.error("需要 --url 或 --discover")
