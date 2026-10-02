# -*- coding: utf-8 -*-
"""涨停池证据回填（THS 历史接口重建，与生产同口径）。

背景：9 月 THS 收盘时点间歇失败致 15:00 帧 limitSummary 缺 13/21（根因与采集链止血见
docs/hotlist-jev/jev-sentiment-questionset-review.md §十一）。历史证据经探针实证可由
THS dataapi 按日期完整重建（涨停池+炸板池+连板桶，5 月起可用）；韭研 jiuyan_action
口径差 1.05~1.42 倍且逐日不稳（含 ST/北交所），只作旁证打印，不进数据。

回填目标=v1 15:00 槽文档 hotlist_jev_sentiment 的 evidenceRaw.limit（情绪锚与面板涨停
证据容器的数据源）；不触碰 snapshot_frames 原始帧；只补缺失日，健康日一律跳过
（绝不覆盖真数据）；zhaban 伪 0 防线沿用（ztCount 非 >0 不回填）。

用法（Git Bash）：
  cd quant-board
  ./.venv/Scripts/python.exe -m backend.operations.backfill_limit_evidence \
      --start 2026-09-01 --end 2026-09-30            # 默认 dry-run
  ... --apply                                        # 实际写库
"""
from __future__ import annotations

import argparse
import asyncio
import time

BOARD_KEYS = ("yiban", "erban", "sanban", "sibanPlus")
PROVENANCE_SOURCE = "ths_hist_backfill"


def build_backfill_limit(summary: dict | None) -> dict | None:
    """build_server_limit_summary 输出 → evidenceRaw.limit（同生产 collect_slot_evidence 映射）+ 回填标记。

    伪 0 防线：涨停数非 >0 视为无有效数据，返回 None（fail-visible，不伪造）。
    """
    if not isinstance(summary, dict) or not summary:
        return None
    boards = summary.get("continuousBoards") or {}
    zhaban = summary.get("zhaban") or {}
    zt = zhaban.get("ztCount")
    if not (isinstance(zt, (int, float)) and not isinstance(zt, bool) and zt > 0):
        return None
    return {
        "ztCount": int(zt),
        "maxBoard": boards.get("maxBoard"),
        "boards": {k: boards.get(k) for k in BOARD_KEYS},
        "zhabanCount": zhaban.get("count"),
        "zhabanRate": zhaban.get("rate"),
        "fengbanRate": zhaban.get("fengbanRate"),
        "source": PROVENANCE_SOURCE,
        "backfilledAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }


def _is_valid_zt(zt) -> bool:
    return isinstance(zt, (int, float)) and not isinstance(zt, bool) and zt > 0


def plan_backfill(db, start: str, end: str, fetch_many) -> tuple[list[dict], list[str], list[str]]:
    """逐交易日定回填计划：返回 (回填动作, 健康跳过日, 未解决日)。

    fetch_many(date8_list) → {date8: summary | Exception | None}（单事件循环批量拉取，
    逐条 try 由本函数判定）。summary 口径=build_server_limit_summary。
    """
    dates = sorted({str(r["tradingDate"]) for r in db["snapshot_frames"].find(
        {"datasetId": "dragonboard_live", "type": "half_hour",
         "tradingDate": {"$gte": start, "$lte": end}}, {"tradingDate": 1}) if r.get("tradingDate")})
    actions: list[dict] = []
    healthy: list[str] = []
    unresolved: list[str] = []
    need: list[str] = []
    doc_by_date: dict[str, dict] = {}
    for date in dates:
        doc = db["hotlist_jev_sentiment"].find_one(
            {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "kind": "slot",
             "slotTime": "15:00", "tradingDate": date})
        if doc is None:
            unresolved.append(f"{date}:无v1槽文档")
            continue
        limit = (doc.get("evidenceRaw") or {}).get("limit") or {}
        if _is_valid_zt(limit.get("ztCount")):
            healthy.append(date)
            continue
        need.append(date.replace("-", ""))
        doc_by_date[date] = doc
    summaries = fetch_many(need) if need else {}
    for date, doc in doc_by_date.items():
        result = summaries.get(date.replace("-", ""))
        if isinstance(result, Exception):
            unresolved.append(f"{date}:THS历史拉取失败:{str(result)[:80]}")
            continue
        new_limit = build_backfill_limit(result)
        if new_limit is None:
            unresolved.append(f"{date}:THS历史无有效涨停数据")
            continue
        actions.append({"date": date, "docId": doc["_id"], "limit": new_limit})
    return actions, healthy, unresolved


def apply_backfill(db, actions: list[dict]) -> int:
    """执行写库：$set evidenceRaw.limit（保留同文档 totalAmount 等其他证据字段）。"""
    for a in actions:
        db["hotlist_jev_sentiment"].update_one(
            {"_id": a["docId"]}, {"$set": {"evidenceRaw.limit": a["limit"]}})
    return len(actions)


async def _fetch_all_ths(date8_list: list[str]) -> dict:
    """单事件循环批量拉取 THS 历史池（逐条 try：单日失败不影响整批）。"""
    from backend.market_proxy.limitup import get_limitup_service
    from backend.snapshot_collector.providers import build_server_limit_summary

    svc = get_limitup_service()
    out: dict = {}
    for date8 in date8_list:
        try:
            list_body = await svc.get_limit_up_list(date8)
            pools = await svc.get_ths_pools(date8)
            info = ((list_body.get("data") or {}).get("info") or []) if isinstance(list_body, dict) else []
            if not info:
                out[date8] = None
                continue
            out[date8] = build_server_limit_summary(info, pools if isinstance(pools, dict) else {})
        except Exception as exc:  # 单日失败随 map 返回，由计划层如实登记
            out[date8] = exc
    return out


def fetch_many_ths(date8_list: list[str]) -> dict:
    return asyncio.run(_fetch_all_ths(date8_list))


def _jiuyan_totals(db, start: str, end: str) -> dict[str, int]:
    """旁证：韭研 final 全量名单数（口径差披露用，不进数据）。"""
    out: dict[str, int] = {}
    for d in db["jiuyan_action"].find(
            {"kind": "jiuyan_action", "tradingDate": {"$gte": start, "$lte": end}},
            {"tradingDate": 1, "fields.stocks": 1}):
        out[d["tradingDate"]] = sum(len(f.get("stocks") or []) for f in d.get("fields") or [])
    return out


def main():
    parser = argparse.ArgumentParser(description="涨停池证据回填（THS 历史，同生产口径）")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()

    actions, healthy, unresolved = plan_backfill(db, args.start, args.end, fetch_many_ths)
    jy = _jiuyan_totals(db, args.start, args.end)

    print(f"== 涨停池证据回填计划 {args.start} → {args.end}（{'APPLY' if args.apply else 'DRY-RUN'}）==")
    for a in actions:
        lim = a["limit"]
        print(f"[回填] {a['date']}: zt={lim['ztCount']} maxBoard={lim['maxBoard']} "
              f"zhaban={lim['zhabanRate']}% fengban={lim['fengbanRate']}% "
              f"boards={lim['boards']} | 旁证 jiuyan={jy.get(a['date'], '无')}")
    print(f"[跳过] 健康日 {len(healthy)} 个: {healthy or '无'}")
    print(f"[未解决] {len(unresolved)} 个: {unresolved or '无'}")
    if args.apply:
        n = apply_backfill(db, actions)
        print(f"已写库 {n} 文档（evidenceRaw.limit，标记 source={PROVENANCE_SOURCE}）")
    else:
        print("dry-run 未写库；确认后加 --apply 执行")


if __name__ == "__main__":
    main()
