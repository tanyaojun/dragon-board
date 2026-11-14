# -*- coding: utf-8 -*-
"""韭研题材语料存储层（集合 `jiuyan_ai_industry`；2026-10-23 v4 换源后单源化）。

单主链：只在 MongoDB `dragon_board_quant`；不建备份/对照集合（历史靠 git + 幂等覆盖）。

事件层（原 `jiuyan_timeline`：投资日历+早报）随 2026-10-23 裁决（方案 A：事件层唯一权威源
=开盘啦，`kpl_theme_store.py`）退役：存储/读取函数删除，集合导出归档后 drop。

`jiuyan_ai_industry`（板块级催化原文 + 热度）
  _id = code（如 "0118"），kind="jiuyan_ai_industry"
  name / level / parentCode / path[] / content(板块级催化原文) / hot /
  contentHash / contentChangedAt（内容变更时刷新，用于「是否新催化」）/ firstSeenAt /
  updatedAt / lastFetchDate

fail-visible：写入异常向上抛（不吞），缺 content 如实留空字符串，不用占位文本冒充催化。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

COLLECTION_INDUSTRY = "jiuyan_ai_industry"
# 题材端点调用计数（额度护栏，2026-10-20）：`_id={fetchDate}`，`calls.{source} = n`。
# 不存凭据，只存计数；失败请求同样计数（服务端已扣额度）。
COLLECTION_API_CALLS = "jiuyan_api_calls"
# 早报日档（2026-11-14 晨间例外复活，只供 09:26 竞价链；与产业树同额度计数器）：
# `_id={date}`，state=ok/not_published/fetch_failed/rate_limited；state=ok 时
# title/content/paragraphs 在场；不复活已 drop 的 jiuyan_timeline 集合。
COLLECTION_MORNING = "jiuyan_morning_report"


def record_api_calls(db: Any, fetch_date: str, sources: tuple[str, ...]) -> dict:
    """累加当日题材端点调用计数（幂等可重入，`$inc` 语义）。返回累加后计数。"""
    if not sources:
        return calls_recorded(db, fetch_date)
    inc = {f"calls.{s}": 1 for s in sources}
    db[COLLECTION_API_CALLS].update_one(
        {"_id": fetch_date},
        {"$inc": inc, "$set": {"lastCallAt": _now()}},
        upsert=True,
    )
    return calls_recorded(db, fetch_date)


def calls_recorded(db: Any, fetch_date: str) -> int:
    """当日题材端点已计调用总数（取不到按 0；缺字段容错）。"""
    doc = db[COLLECTION_API_CALLS].find_one({"_id": fetch_date}, {"calls": 1}) or {}
    return sum(int(v or 0) for v in (doc.get("calls") or {}).values())


def save_morning_report(db: Any, *, fetch_date: str, state: str, title: str = "",
                        content: str = "", paragraphs: list[str] | None = None,
                        token_source: str | None = None,
                        self_heal: dict | None = None) -> dict:
    """早报日档幂等 upsert（`_id={fetch_date}`）。

    - `state="ok"` 档一旦在库**不覆盖**（幂等短路，重跑零 HTTP 由编排层先行短路）；
    - 空 content 不得覆盖已存正文（§4.0：空载荷不覆盖既有事实）；
    - 非 ok 状态档（not_published/fetch_failed/rate_limited）覆盖式更新（供
      corpusState.morningState 按状态披露与下一尝试槽重试）；
    - firstSeenAt/firstSeenDate 首见不覆盖。
    """
    existing = db[COLLECTION_MORNING].find_one({"_id": fetch_date}) or {}
    if existing.get("state") == "ok":
        return {"written": 0, "skipped": True, "reason": "already_ok"}
    if state == "ok" and not str(content or "").strip():
        return {"written": 0, "skipped": True, "reason": "empty_content"}
    quality: dict[str, Any] = {"tokenSource": token_source}
    if self_heal:
        quality["selfHeal"] = self_heal
    doc = {
        "_id": fetch_date, "kind": "jiuyan_morning_report", "date": fetch_date,
        "state": state, "title": str(title or ""), "content": str(content or ""),
        "paragraphs": [str(p) for p in (paragraphs or [])],
        "firstSeenAt": existing.get("firstSeenAt") or _now(),
        "firstSeenDate": existing.get("firstSeenDate") or fetch_date,
        "fetchedAt": _now(), "quality": quality,
    }
    db[COLLECTION_MORNING].replace_one({"_id": fetch_date}, doc, upsert=True)
    return {"written": 1, "state": state}


def get_morning_report(db: Any, *, date: str) -> dict | None:
    """读当日早报日档（无档 → None；digest 据此 morningState=missing）。"""
    return db[COLLECTION_MORNING].find_one({"_id": date})



def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def save_industry_nodes(db: Any, *, fetch_date: str, nodes: list[dict]) -> dict:
    """产业树节点幂等 upsert。返回 {written, contentChanged, withContent, reused}。"""
    written = content_changed = with_content = 0
    for n in nodes:
        code = str(n.get("code") or "")
        if not code:
            continue
        content = n.get("content") or ""
        digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12] if content else None
        existing = db[COLLECTION_INDUSTRY].find_one(
            {"_id": code}, {"contentHash": 1, "firstSeenAt": 1, "name": 1,
                            "contentChangedAt": 1, "contentChangedDate": 1,
                            "content": 1}) or {}
        changed = bool(digest) and digest != existing.get("contentHash")
        # P2 修复（2026-10-20 review）：入站 content 为空但库内非空时保留旧值——
        # 服务端降级 payload（errCode=0 但 content 空）不得把已采证据覆盖成空（§4.0）；
        # timeline 层同口径（it.content or existing.content）。
        if not content and existing.get("content"):
            content = existing["content"]
        doc = {
            "_id": code,
            "kind": "jiuyan_ai_industry",
            "code": code,
            "name": n.get("name") or existing.get("name") or "",
            "level": n.get("level"),
            "parentCode": n.get("parentCode"),
            "path": n.get("path") or [],
            "content": content,
            "contentHash": digest,
            "contentChangedAt": (_now() if changed else None)
            or existing.get("contentChangedAt"),
            "contentChangedDate": (fetch_date if changed else None)
            or existing.get("contentChangedDate"),
            "hot": n.get("hot"),
            "industryUpdateTime": n.get("updateTime"),
            "stockCount": n.get("stockCount"),
            "firstSeenAt": existing.get("firstSeenAt") or _now(),
            "lastFetchDate": fetch_date,
            "updatedAt": _now(),
        }
        db[COLLECTION_INDUSTRY].replace_one({"_id": code}, doc, upsert=True)
        written += 1
        if content:
            with_content += 1
        if changed:
            content_changed += 1
    return {"written": written, "contentChanged": content_changed, "withContent": with_content}


def get_industry_nodes(db: Any) -> list[dict]:
    return list(db[COLLECTION_INDUSTRY].find({}, {
        "code": 1, "name": 1, "level": 1, "parentCode": 1, "path": 1, "content": 1,
        "hot": 1, "contentChangedDate": 1, "industryUpdateTime": 1, "lastFetchDate": 1,
    }))


# ── 全成分快照（V3-1：板块节点三期全成分增强，2026-10-25） ──────────────────
COLLECTION_INDUSTRY_STOCKS = "jiuyan_industry_stocks"


def _stocks_digest(stocks: list[dict]) -> str:
    """成分集指纹（code:sharesRange 排序串），变更检测用。"""
    parts = sorted(f"{s['code']}:{s.get('sharesRange')}" for s in stocks or [])
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def save_industry_stocks(db: Any, *, code: str, name: str, batch_date: str,
                         stocks: list[dict]) -> dict:
    """一级产业成分快照幂等 upsert（`_id=code`）。

    同批次重拉不滚 prevDiff；跨批次记录 prevDiff 摘要（added/removed code 列表），
    不存全量旧版（审计够用、不占库；完整历史不可重放登记为已知局限——读数带
    batchDate 标注口径）。
    """
    existing = db[COLLECTION_INDUSTRY_STOCKS].find_one(
        {"_id": code}, {"batchDate": 1, "stocks": 1, "prevDiff": 1, "changedAt": 1,
                        "prevBatchDate": 1}) or {}
    same_batch = existing.get("batchDate") == batch_date
    digest = _stocks_digest(stocks)
    changed = digest != existing.get("stocksDigest")
    if not existing:
        prev_diff, prev_batch = None, None            # 首批无 prev
    elif same_batch:
        prev_diff = existing.get("prevDiff")
        prev_batch = existing.get("prevBatchDate")
    else:
        old_codes = {s["code"] for s in existing.get("stocks") or []}
        new_codes = {s["code"] for s in stocks}
        prev_diff = {"added": sorted(new_codes - old_codes),
                     "removed": sorted(old_codes - new_codes)}
        prev_batch = existing.get("batchDate")
    doc = {
        "_id": code,
        "kind": "jiuyan_industry_stocks",
        "code": code,
        "name": name,
        "level": 1,
        "batchDate": batch_date,
        "prevBatchDate": prev_batch,
        "stockN": len(stocks),
        "stocks": stocks,
        "stocksDigest": digest,
        "prevDiff": prev_diff,
        "changedAt": (datetime.now().isoformat(timespec="seconds")
                      if changed and not same_batch else existing.get("changedAt")),
        "updatedAt": _now(),
    }
    db[COLLECTION_INDUSTRY_STOCKS].replace_one({"_id": code}, doc, upsert=True)
    return {"written": 1, "stockN": len(stocks), "changed": bool(changed and not same_batch)}


def pending_industry_stock_codes(db: Any, batch_date: str) -> list[dict]:
    """待拉清单（断点续拉）：level=1 节点 − 当日已成功（batchDate==batch_date 且 stockN>0）。

    返回 [{code, name}]（按 code 排序）——产业树缺失/空时如实返回空清单（fail-visible，
    调用方以「0 待拉」+根因披露，不伪成功）。
    """
    nodes = db[COLLECTION_INDUSTRY].find({"level": 1}, {"code": 1, "name": 1})
    done = {d["_id"] for d in db[COLLECTION_INDUSTRY_STOCKS].find(
        {"batchDate": batch_date, "stockN": {"$gt": 0}}, {"_id": 1})}
    return sorted(({"code": str(n["code"]), "name": str(n.get("name") or "")}
                   for n in nodes if n["code"] not in done),
                  key=lambda x: x["code"])


def latest_industry_stocks_batch(db: Any) -> str | None:
    """最新成功批次日期（调度周频守卫用；空库返回 None）。"""
    doc = db[COLLECTION_INDUSTRY_STOCKS].find_one(
        {"stockN": {"$gt": 0}}, sort=[("batchDate", -1)], projection={"batchDate": 1})
    return (doc or {}).get("batchDate")
