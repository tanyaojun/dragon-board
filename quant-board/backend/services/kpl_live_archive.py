# -*- coding: utf-8 -*-
"""直播日归档 `kpl_live_daily` 共享 merge-union 写口 + 晨间归档（竞价龙头链 vA1）。

单写者语义（预登记 auction-leader-vA1 A7）：merge_live_archive 为**唯一实现**，
晨间（09:26 job）与 17:30 标注链（get_live_for_label）两调用点共用；按 item id
union（同 id 新取优先），commutative、幂等——17:30 全量取数不再覆盖晨间归档
（旧 replace_one 会把 09:15 竞价推送条目抹掉，st=60 窗午后未必含晨间条）。
其余字段（含 auctionPush 投影）原样保留，只更新 items/notice/itemCount/fetchedAt。

频控预算（红线 9）：晨间 1 次 HTTP/日（get_live_commentary st=60，15s TTL 已有），
不新增轮询/订阅；失败 fail-visible 结构化返回，不阻断调用方。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

LIVE_ARCHIVE_COLLECTION = "kpl_live_daily"


def merge_live_archive(db: Any, date: str, payload: dict) -> dict[str, Any]:
    """直播 payload merge-union 入日档；返回合并后 {items, notice, itemCount}。

    payload = get_live_commentary 归一产物（items ts 降序）；空 items 不写档
    （fail-visible：取数空不覆盖既有归档）。
    """
    items_new = [it for it in (payload.get("items") or []) if isinstance(it, dict)]
    col = db[LIVE_ARCHIVE_COLLECTION]
    old = col.find_one({"_id": str(date)}) or {}
    if not items_new:
        return {"items": old.get("items") or [], "notice": old.get("notice"),
                "itemCount": len(old.get("items") or []), "merged": False}
    merged: dict[str, dict] = {}
    for it in (old.get("items") or []) + items_new:
        key = str(it.get("id") or f"{it.get('ts')}:{it.get('comment')}")
        merged[key] = it                    # 新取同 id 优先（修订条覆盖旧文本）
    items = sorted(merged.values(), key=lambda r: r.get("ts") or 0, reverse=True)
    keep = {k: v for k, v in old.items()
            if k not in ("_id", "items", "notice", "itemCount", "fetchedAt")}
    doc = {"_id": str(date), "items": items,
           "notice": payload.get("notice") or old.get("notice"),
           "itemCount": len(items),
           "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), **keep}
    col.replace_one({"_id": str(date)}, doc, upsert=True)
    return {"items": items, "notice": doc["notice"], "itemCount": len(items),
            "merged": True}


def archive_morning_live(db: Any, date: str, *,
                         fetcher: Callable[..., dict] | None = None) -> dict[str, Any]:
    """晨间直播归档 + 竞价推送 roster 投影（09:26 job 调用；1 次 HTTP/日）。

    返回 {ok, pushState: ok|missing|fetch_failed, rosterN, entryN, reason?}；
    roster 落 `kpl_live_daily.auctionPush`（投影层，单一事实源仍为 items）。
    推送缺席 → pushState=missing + auctionPush 留痕（stocks=[]），不伪造名单。
    """
    from backend.analysis.hotlist.auction_push import (
        parse_auction_push, select_push_entries)
    if fetcher is None:
        from backend.services.kpl_ranking_service import get_live_commentary
        fetcher = get_live_commentary
    try:
        payload = fetcher(st=100)   # 2026-11-13 裁决：窗须覆盖 09:15 竞价播报（st=60 午后仅到 09:51）
    except Exception as exc:  # noqa: BLE001 — 晨间取数失败不阻断挂链（fail-visible）
        logger.warning("morning live fetch failed date=%s: %s", date, exc)
        return {"ok": False, "pushState": "fetch_failed", "rosterN": 0, "entryN": 0,
                "reason": f"fetch_failed: {exc}"}
    if not payload.get("ok"):
        return {"ok": False, "pushState": "fetch_failed", "rosterN": 0, "entryN": 0,
                "reason": str(payload.get("reason") or "payload_not_ok")}
    merged = merge_live_archive(db, date, payload)
    entries = select_push_entries(merged["items"], date)
    roster = parse_auction_push(entries)
    state = {"ok": True,
             "pushState": "ok" if roster["stocks"] else "missing",
             "rosterN": len(roster["stocks"]), "entryN": len(entries)}
    db[LIVE_ARCHIVE_COLLECTION].update_one(
        {"_id": str(date)},
        {"$set": {"auctionPush": {**roster,
                                  "archivedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}}},
        upsert=True)
    return state


def load_auction_push(db: Any, date: str) -> dict[str, Any] | None:
    """读口：当日竞价推送 roster 投影（无档/无投影 → None，调用方 fail-visible）。"""
    doc = db[LIVE_ARCHIVE_COLLECTION].find_one({"_id": str(date)}) or {}
    push = doc.get("auctionPush")
    return push if isinstance(push, dict) else None