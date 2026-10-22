# -*- coding: utf-8 -*-
"""反包板池持久层——一日两更（午盘 12:30 触板口径 / 盘后 16:00 封板口径）。

2026-10-21 用户裁决（jev-rewrap-factor-preregistration.md §6-R2 + 补充需求）：
- 池更新挂在打标主循环入口（`jev_label_jiuyan.run()` 每个 date 先更池再打标）：
  12:30 午盘链自然更新 `{date}:midday`、16:00 盘后链自然更新 `{date}:final`——
  一日两次、幂等可重入；`--dry-run` 不写（零写入纪律）。
- 集合 `hotlist_rewrap_pool` 是**落库快照/审计口径**（含 generatedAt，可追溯「当时看到的池」）；
  计算单一事实源 = `analysis/hotlist/rewrap_pool.build_rewrap_pool`（读方随时可现算，
  快照缺失/陈旧不阻断读口，fail-visible 注记）。
- 池内反包股免投喂承接前日标签（`jev_label_jiuyan` 消费），承接守卫见该模块
  `_rewrap_carry_one`（答案缺失/题集代际不符/前标 freshness∈{unclear, fresh_catalyst}
  → 回落全量实判，不静默降级）。
"""
from __future__ import annotations

import time
from typing import Any

from backend.analysis.hotlist.rewrap_pool import build_rewrap_pool
from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID

COLLECTION = "hotlist_rewrap_pool"


def update_rewrap_pool(db: Any, date: str, slot: str = "final",
                       dataset_id: str = DEFAULT_DATASET_ID) -> dict:
    """构建并 upsert 当日 `{date}:{slot}` 池快照（幂等，返回落库文档）。

    附带 `ratePct20d`（近 20 交易日反包率分位，更新时一次算好落库——读口/KPI 卡
    直接透传，避免每次读口重算 20 日序列）。"""
    from backend.analysis.hotlist.rewrap_pool import rewrap_rate_series, percentile_of
    pool = build_rewrap_pool(db, date, slot, dataset_id)
    pool["ratePct20d"] = percentile_of(
        [r for _, r in rewrap_rate_series(db, date, 20, dataset_id)], pool.get("rewrapRate"))
    doc = dict(pool)
    doc["_id"] = f"{date}:{slot}"
    doc["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return doc


def get_rewrap_pool(db: Any, date: str, slot: str = "final") -> dict | None:
    """读取池快照（可能为 None=未更新；消费方应回落现算并注记，不冒充）。"""
    return db[COLLECTION].find_one({"_id": f"{date}:{slot}"})


def backfill_rewrap_pool(db: Any, start: str, end: str,
                         slots: tuple[str, ...] = ("final",),
                         dry_run: bool = False,
                         dataset_id: str = DEFAULT_DATASET_ID) -> dict:
    """历史回填池快照（幂等 upsert；2026-10-21 用户问询后补的批量入口）。

    日期轴 = 区间内存在 `{date}:final` 的韭研交易日（与打标主循环同源查询）。
    midday 槽硬门：只回填 `midday_source_state` 判定「真午盘」的名单（fetchedAt 落午盘窗）——
    实测 2026-10-14/16/19/20 的 midday 文档是收盘后补写的，拿它算「触板口径」等于
    把收盘数据冒充午盘（AGENTS §4.0），一律 skip 并给 reason，不补写。
    dry_run=True 零写入（只报各日可算性）。结果逐日结构化（fail-visible：missing 标志随档）。"""
    from backend.analysis.hotlist.rewrap_pool import build_rewrap_pool
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$gte": start, "$lte": end},
         "_id": {"$regex": ":final$"}}, {"tradingDate": 1}) if d.get("tradingDate")})
    results: list[dict] = []
    written = skipped = 0
    for date in dates:
        for slot in slots:
            if slot == "midday":
                from backend.operations.jev_label_jiuyan import midday_source_state
                state = midday_source_state(db, date)
                if not state["ok"]:
                    results.append({"date": date, "slot": slot, "written": False,
                                    "reason": state["reason"]})
                    skipped += 1
                    continue
            if dry_run:
                doc = build_rewrap_pool(db, date, slot, dataset_id)
            else:
                doc = update_rewrap_pool(db, date, slot, dataset_id)
            results.append({"date": date, "slot": slot, "written": not dry_run,
                            "candidate": doc.get("candidateN"), "rewrap": doc.get("rewrapN"),
                            "rewrapRate": doc.get("rewrapRate"), "missing": doc.get("missing")})
            written += 0 if dry_run else 1
    return {"ok": True, "start": start, "end": end, "slots": list(slots),
            "dryRun": dry_run, "dates": len(dates), "written": written,
            "skipped": skipped, "results": results}
