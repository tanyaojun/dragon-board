# -*- coding: utf-8 -*-
"""题材周期 v1 CLI（theme-cycle，2026-10-25）：取数→判定→落库，纯本地零 token。

预登记：docs/hotlist-jev/theme-cycle-v1-preregistration.md；判据在
analysis/hotlist/theme_cycle.py（纯函数，本模块只做单源取数与落库）。
单一事实源（预登记 §二）：题材内涨停名单=snapshot_stock_rows 当日最新槽
（mainTheme=题材 ∧ leadStatus=涨停，治理后跟强不跟弱归属）；真连板=jiuyan_streak_map；
龙头续断=day_status_of（停牌不算断板）；人气股池=近 60 交易日 boardHeight≥2 窗口池。
集合 hotlist_jev_theme_cycle，`_id={date}:THEME_CYCLE`，确定性输出幂等覆盖。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.analysis.hotlist.theme_cycle import (
    NEW_BENCHMARK_STREAK,
    POPULAR_STREAK_MIN,
    STAGE_LABELS_CN,
    THEME_CYCLE_VERSION,
    assemble_rows,
)
from backend.operations.jev_label_jiuyan import (
    _adj_prev_series,
    _daily_bars,
    bars_need_upto,
    day_status_of,
    jiuyan_streak_map,
    trading_dates_before,
)
from backend.operations.theme_leader_baseline import sealed_and_info

COLLECTION = "hotlist_jev_theme_cycle"
_KIND = "theme_cycle"
POPULAR_WINDOW_DAYS = 60      # 人气股池扫描深度（预登记 §二，用户裁定④）
POPULAR_BOARD_HEIGHT_MIN = 2  # 曾连板 ≥2（断板不删）

# 人气池逐日缓存（回填升序滑动窗口复用 59/60，性能实测瓶颈项 168s→秒级）：
# 键=交易日（单日 {题材: 曾 boardHeight≥2 涨停 code 集}），随进程消亡——只允许
# backfill CLI / 盘后链子进程消费（同 sector_nodes _POOL_CACHE 消费形态约束）。
_POOL_DAY_CACHE: dict[str, dict[str, set[str]]] = {}


def _ensure_indexes(db: Any) -> None:
    """题材周期查询专用索引（幂等后台建，一次生效）：
    - 当日最新槽定位 + 涨停名单扫描（无 datasetId/type 前缀，现有复合索引用不上）。"""
    db["snapshot_stock_rows"].create_index(
        [("tradingDate", 1), ("leadStatus", 1), ("slotTime", 1)], background=True)


def _day_pool_of(db: Any, date: str) -> dict[str, set[str]]:
    """单日 {题材: boardHeight≥2 涨停 code 集}（进程缓存；THS 封板口径同 _theme_zt_rows）。"""
    if date in _POOL_DAY_CACHE:
        return _POOL_DAY_CACHE[date]
    slot = _latest_slot(db, date)
    out: dict[str, set[str]] = {}
    if slot:
        sealed, _info, _meta = sealed_and_info(db, date, DEFAULT_DATASET_ID)
        if sealed is not None:
            for r in db["snapshot_stock_rows"].find(
                    {"tradingDate": date, "slotTime": slot,
                     "mainTheme": {"$nin": [None, ""]},
                     "boardHeight": {"$gte": POPULAR_BOARD_HEIGHT_MIN}},
                    {"mainTheme": 1, "code": 1}).batch_size(2000):
                code = str(r.get("code") or "")[-6:]
                if code in sealed:
                    theme = str(r["mainTheme"])
                    out.setdefault(theme, set()).add(code)
    _POOL_DAY_CACHE[date] = out
    return out


def _latest_slot(db: Any, date: str) -> str | None:
    """当日 stock rows 最新槽（EOD 定档：15:00/15:30 收盘口径）。"""
    doc = db["snapshot_stock_rows"].find_one(
        {"tradingDate": date, "mainTheme": {"$exists": True}}, {"slotTime": 1},
        sort=[("slotTime", -1)])
    return str(doc["slotTime"]) if doc and doc.get("slotTime") else None


def _theme_zt_rows(db: Any, date: str, slot: str | None) -> dict[str, dict[str, Any]] | None:
    """单日题材→涨停名单行：mainTheme 分组 ∩ THS 封板集合（sealed_and_info 单源）。

    不用 leadStatus 字段过滤——旧代快照（≤2026-08 上旬）该字段为空串，改与板块
    节点同源封板二分（触板−炸板），历史全覆盖；两种口径交集一致（快照池内封板股）。
    返回 {题材: {codes, names, leader, maxStreak, kplZtCount}}；
    THS 池缺失 → None（整日不可考，fail-visible）；无该日 stock rows → {}。
    """
    if not slot:
        return {}
    sealed, _info, _meta = sealed_and_info(db, date, DEFAULT_DATASET_ID)
    if sealed is None:
        return None
    streaks = jiuyan_streak_map(db, date, DEFAULT_DATASET_ID)
    by_theme: dict[str, list[dict[str, Any]]] = {}
    for r in db["snapshot_stock_rows"].find(
            {"tradingDate": date, "slotTime": slot,
             "mainTheme": {"$nin": [None, ""]}},
            {"mainTheme": 1, "code": 1, "name": 1, "firstZtTime": 1,
             "boardHeight": 1}).batch_size(2000):
        code = str(r.get("code") or "")[-6:]
        if code not in sealed:
            continue
        theme = str(r["mainTheme"])
        by_theme.setdefault(theme, []).append({
            "code": code,
            "name": r.get("name"),
            "time": r.get("firstZtTime"),
            "streak": streaks.get(code),
            "boardHeight": r.get("boardHeight"),
        })
    kpl_zt: dict[str, int] = {}
    for r in db["snapshot_sector_rows"].find(
            {"entityType": "hot_theme", "tradingDate": date},
            {"entityName": 1, "ztCount": 1, "timestamp": 1}).sort("timestamp", -1):
        nm = str(r.get("entityName") or "")
        if nm and nm not in kpl_zt and r.get("ztCount") is not None:
            kpl_zt[nm] = int(r["ztCount"])   # 倒序首见=最新帧
    out: dict[str, dict[str, Any]] = {}
    for theme, stocks in by_theme.items():
        codes = {s["code"] for s in stocks if s["code"]}
        ranked = sorted(
            stocks,
            key=lambda s: (-(s["streak"] if isinstance(s["streak"], int) else -1),
                           _time_key(s.get("time")), str(s.get("name") or "")))
        leader = ranked[0] if ranked else None
        out[theme] = {
            "codes": sorted(codes), "names": stocks,
            "leader": leader,
            "maxStreak": max((s["streak"] for s in stocks
                              if isinstance(s["streak"], int)), default=None),
            "kplZtCount": kpl_zt.get(theme),
        }
    return out


def _time_key(t: Any) -> tuple:
    parts = str(t or "").split(":")
    try:
        return (0, int(parts[0]) * 60 + int(parts[1]))
    except (ValueError, IndexError):
        return (1, 0)   # 时间缺失垫底（不猜）


def _popular_pool(db: Any, date: str) -> dict[str, set[str]]:
    """近 60 交易日人气股池：{题材: 曾 boardHeight≥2 涨停 code 集}（断板不删）。

    逐日结果进程缓存（滑动窗口重叠复用）；单日数据缺失（stock rows 断档）如实
    留缺口不插值（fail-visible）。"""
    axis = trading_dates_before(db, date, POPULAR_WINDOW_DAYS,
                                dataset_id=DEFAULT_DATASET_ID)
    out: dict[str, set[str]] = {}
    for d in axis:
        for theme, codes in _day_pool_of(db, d).items():
            out.setdefault(theme, set()).update(codes)
    return out


def _leader_states(db: Any, date: str, prev_by: dict[str, dict[str, Any]],
                   dataset_id: str) -> dict[str, str]:
    """昨日各题材龙头 → 今日状态（day_status_of：停牌不算断板，板块节点同式）。"""
    sealed, info, _meta = sealed_and_info(db, date, dataset_id)
    touch = set(info) if info else None
    out: dict[str, str] = {}
    for theme, row in prev_by.items():
        leader = row.get("leader") or {}
        code = str(leader.get("code") or "")
        if not code:
            continue
        bars = _daily_bars(code)
        adj = _adj_prev_series(date, code, bars) if bars else {}
        out[theme] = day_status_of(code, date, sealed=sealed, touch=touch,
                                   bars=bars or None, adj=adj)
    return out


def _prev_cycle_state(db: Any, prev_date: str | None) -> tuple[dict[str, dict], bool]:
    """昨日周期档 {题材: {stage, weakDays, cycleN}}；昨日文档缺失 → ({}, False)。"""
    if not prev_date:
        return {}, False
    doc = db[COLLECTION].find_one({"_id": f"{prev_date}:THEME_CYCLE"},
                                  {"rows.theme": 1, "rows.stage": 1,
                                   "rows.weakDays": 1, "rows.cycleN": 1})
    if not doc:
        return {}, False
    out = {str(r["theme"]): {"stage": str(r.get("stage")),
                             "weakDays": int(r.get("weakDays") or 0),
                             "cycleN": int(r.get("cycleN") or 1)}
           for r in doc.get("rows") or [] if r.get("theme")}
    return out, True


def _count_history(db: Any, date: str, days: int = 10) -> dict[str, list[tuple[str, int]]]:
    """近 N 日各题材涨停家数序列（严格早于今日，从本集合历史文档读）。"""
    out: dict[str, list[tuple[str, int]]] = {}
    for doc in db[COLLECTION].find(
            {"tradingDate": {"$lt": date}},
            {"tradingDate": 1, "rows.theme": 1, "rows.count": 1}
    ).sort("tradingDate", -1).limit(days):
        d = str(doc.get("tradingDate"))
        for r in doc.get("rows") or []:
            if r.get("theme") and isinstance(r.get("count"), int):
                out.setdefault(str(r["theme"]), []).append((d, int(r["count"])))
    for t in out:
        out[t].sort()   # 升序
    return out


def settle_day(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, Any]:
    """单日计算+落库（幂等覆盖）；昨日档从昨日文档读（回填升序天然成链）。"""
    _ensure_indexes(db)
    prevs = trading_dates_before(db, date, 2, dataset_id=dataset_id)
    prev_date = prevs[-1] if prevs else None

    today_slot = _latest_slot(db, date)
    prev_slot = _latest_slot(db, prev_date) if prev_date else None
    today_raw = _theme_zt_rows(db, date, today_slot)
    prev_raw = _theme_zt_rows(db, prev_date, prev_slot) if prev_date else None
    prev2_slot = _latest_slot(db, prevs[-2]) if len(prevs) >= 2 else None
    prev2_raw = _theme_zt_rows(db, prevs[-2], prev2_slot) if len(prevs) >= 2 else None

    # 今日原料不可考：stock rows 缺失（无槽）或 THS 池缺失（None）→ 整日 unknown（不伪 0）
    today_by = today_raw if (today_slot and today_raw is not None) else None
    prev_by = prev_raw if (prev_date and prev_slot is not None and prev_raw is not None) else None
    prev2_by = prev2_raw if (len(prevs) >= 2 and prev2_slot is not None
                             and prev2_raw is not None) else None

    prev_state_map, prev_doc_found = _prev_cycle_state(db, prev_date)
    count_hist = _count_history(db, date)

    # 反包/新标杆/恐慌/龙头状态（今日有名单才算）
    pool_map = _popular_pool(db, date) if today_by else {}
    rewrap_by: dict[str, list[dict]] = {}
    benchmark_by: dict[str, list[dict]] = {}
    for theme, row in (today_by or {}).items():
        pool = pool_map.get(theme, set())
        row["popularN"] = len(pool)
        row["poolCodes"] = pool
        prev_codes = set((prev_by or {}).get(theme, {}).get("codes") or [])
        # 反包：人气股今日封板且昨日未封（断板反包）
        rewrap = [s for s in row["names"]
                  if s["code"] in pool and s["code"] not in prev_codes]
        row["rewrapCodes"] = rewrap
        # 新标杆：今日名单真连板 ≥3（含老龙续高——标杆语义，预登记 §四.1②）
        row["benchmarkCodes"] = [s for s in row["names"]
                                 if isinstance(s["streak"], int)
                                 and s["streak"] >= NEW_BENCHMARK_STREAK]
        if rewrap:
            rewrap_by[theme] = rewrap
        if row["benchmarkCodes"]:
            benchmark_by[theme] = row["benchmarkCodes"]

    leader_states = ({} if prev_by is None
                     else _leader_states(db, date, prev_by, dataset_id))

    # 恐慌统计（当日 stock rows pctChange 口径——同语义当日跌幅，免逐码日线网络链；
    # 预登记 §四注记已同步回改）：pool 股当日行一次 in 查询按题材分摊
    panic_by: dict[str, dict] = {}
    if today_by:
        all_pool: set[str] = set()
        for row in today_by.values():
            all_pool |= row.get("poolCodes") or set()
        pct_of: dict[str, float] = {}
        if all_pool and today_slot:
            for r in db["snapshot_stock_rows"].find(
                    {"tradingDate": date, "slotTime": today_slot,
                     "code": {"$in": sorted(all_pool)}},
                    {"code": 1, "pctChange": 1}).batch_size(2000):
                p = r.get("pctChange")
                c = str(r.get("code") or "")[-6:]
                if c and isinstance(p, (int, float)) and not isinstance(p, bool):
                    pct_of[c] = float(p)
        for theme, row in today_by.items():
            pool = row.get("poolCodes") or set()
            pcts = [pct_of[c] for c in pool if c in pct_of]
            if pcts:
                panic_by[theme] = {
                    "dtN": sum(1 for p in pcts if p <= -9.8),
                    "medianPct": round(statistics.median(pcts), 2), "n": len(pcts)}

    built = assemble_rows(date=date, today_by=today_by, prev_by=prev_by,
                          prev_date=prev_date, count_hist=count_hist,
                          prev_stage_map=prev_state_map if prev_doc_found else None,
                          prev_state_map=prev_state_map if prev_doc_found else None,
                          leader_states=leader_states,
                          panic_by=panic_by,
                          today_missing_reason=(None if today_by is not None else (
                              "当日 THS 池缺失，封板集合不可二分" if today_slot
                              else "当日 stock rows 缺失")))
    status = "ok" if today_by is not None else "degraded"
    doc = {"_id": f"{date}:THEME_CYCLE", "kind": _KIND, "tradingDate": date,
           "version": THEME_CYCLE_VERSION, "status": status,
           "computedAt": datetime.now(timezone.utc),
           "rows": built["rows"], "degraded": built["degraded"],
           "meta": {"slot": today_slot, "prevDate": prev_date,
                    "prevDocFound": prev_doc_found,
                    "streakSource": "jiuyan_streak_map",
                    "poolWindowDays": POPULAR_WINDOW_DAYS}}
    db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    dist: dict[str, int] = {}
    for r in built["rows"]:
        dist[r["stage"]] = dist.get(r["stage"], 0) + 1
    return {"date": date, "status": status, "themes": len(built["rows"]),
            "stages": {STAGE_LABELS_CN[k]: v for k, v in sorted(dist.items())},
            "degraded": built["degraded"]}


def _recent_final_date(db: Any) -> str | None:
    doc = db["jiuyan_action"].find_one({"_id": {"$regex": ":final$"}},
                                       {"tradingDate": 1},
                                       sort=[("tradingDate", -1)])
    return str(doc.get("tradingDate")) if doc and doc.get("tradingDate") else None


def backfill(db: Any, start: str, end: str,
             dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, Any]:
    """区间回填（升序逐日，昨日档自然成链；确定性输出幂等覆盖）。"""
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$gte": start, "$lte": end},
         "_id": {"$regex": ":final$"}}, {"tradingDate": 1}) if d.get("tradingDate")})
    results = []
    for d in dates:
        results.append(settle_day(db, d, dataset_id))
    ok_n = sum(1 for r in results if r["status"] == "ok")
    return {"start": start, "end": end, "days": len(results), "ok": ok_n,
            "degradedDays": [r["date"] for r in results if r["status"] != "ok"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="题材周期 v1（确定性判定，零 token）")
    ap.add_argument("--day", help="计算并落库单日（缺省=最近韭研 final 日）")
    ap.add_argument("--backfill", action="store_true", help="区间回填（需 --from/--to）")
    ap.add_argument("--from", dest="from_date")
    ap.add_argument("--to", dest="to_date")
    ap.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    args = ap.parse_args(argv)

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    if args.backfill:
        if not (args.from_date and args.to_date):
            print(json.dumps({"ok": False, "error": "backfill 需要 --from 与 --to"},
                             ensure_ascii=False))
            return 2
        out = backfill(db, args.from_date, args.to_date, args.dataset_id)
        out["ok"] = True
        print(json.dumps(out, ensure_ascii=False))
        return 0
    day = args.day or _recent_final_date(db)
    if not day:
        print(json.dumps({"ok": False, "error": "无韭研 final，且未给 --day"},
                         ensure_ascii=False))
        return 2
    out = settle_day(db, day, args.dataset_id)
    out["ok"] = out["status"] == "ok"
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
