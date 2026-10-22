# -*- coding: utf-8 -*-
"""真连板锚参考集合回填（market_true_ladder，2026-10-22 语料口径修复 §2.3 配套）。

背景：slot 级 jev 叙事与近20日锚「最高连板」改真连板口径（THS 连板层五池）。
10-10 起 15:00 帧自带连板层（锚直读帧，零请求）；更早历史日锚样本缺口由本工具
按日查 THS 连板层回填参考集合——**同源采样铁律**：与帧池/现查同一 API 同一口径，
不混采韭研/东财等其他源。

跳过（幂等）：15:00 帧已带连板层（锚直读帧）；参考集合已存该日。
不可算（宁缺毋猜）：任一池缺失/不 ok、全零但当日 zt>0（池未就绪）→ 不落库，
unresolved 如实登记（AGENTS §4.0：「取不到」与「真的 0」是两件事）。

用法：
    python -m backend.operations.backfill_true_ladder --start 2026-09-22 --end 2026-10-09           # 计划（dry）
    python -m backend.operations.backfill_true_ladder --start 2026-09-22 --end 2026-10-09 --apply   # 落库
"""
from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any

LADDER_POOL_KEYS = ("one", "two", "three", "four", "high")
PROVENANCE_SOURCE = "ths_ladder_backfill"


def _frame_ladder_served(frame: dict | None) -> bool:
    """15:00 帧已带可用连板层（锚直读帧，无需参考集合）。"""
    from backend.analysis.hotlist.jev_state import derive_true_ladder_from_pools
    from backend.services.jev.jev_sentiment_compute import _frame_zt_count

    ls = (frame or {}).get("limitSummary") if isinstance((frame or {}).get("limitSummary"), dict) else {}
    ths_pools = ls.get("thsPools") if isinstance(ls.get("thsPools"), dict) else {}
    pools = ths_pools.get("pools") if isinstance(ths_pools.get("pools"), dict) else None
    return derive_true_ladder_from_pools(pools, zt_count=_frame_zt_count(frame)) is not None


def plan_backfill(db: Any, start: str, end: str, fetch) -> tuple[list[dict], int, int, list[str]]:
    """计划回填：返回 (actions, frame_served, already, unresolved)。

    fetch(date8_to_zt: dict[str, int|None]) -> {date8: ladder|None}（已派生，derive 口径）。
    """
    dates = sorted({
        str(r["tradingDate"]) for r in db["snapshot_frames"].find(
            {"datasetId": "dragonboard_live", "type": "half_hour",
             "tradingDate": {"$gte": start, "$lte": end}}, {"tradingDate": 1})
        if r.get("tradingDate")
    })
    need: dict[str, int | None] = {}
    frame_served = already = 0
    for date in dates:
        frame = db["snapshot_frames"].find_one(
            {"datasetId": "dragonboard_live", "type": "half_hour",
             "tradingDate": date, "slotTime": "15:00"}, {"limitSummary": 1})
        if _frame_ladder_served(frame):
            frame_served += 1
            continue
        if db["market_true_ladder"].find_one({"_id": date}) is not None:
            already += 1
            continue
        from backend.services.jev.jev_sentiment_compute import _frame_zt_count

        need[date.replace("-", "")] = _frame_zt_count(frame)
    fetched = fetch(need) if need else {}
    actions: list[dict] = []
    unresolved: list[str] = []
    for date8 in sorted(need):
        ladder = fetched.get(date8)
        if not isinstance(ladder, dict) or not isinstance(ladder.get("maxBoard"), int):
            unresolved.append(f"{date8[:4]}-{date8[4:6]}-{date8[6:]}:THS历史无有效连板层")
            continue
        actions.append({"date": f"{date8[:4]}-{date8[4:6]}-{date8[6:]}", "ladder": ladder})
    return actions, frame_served, already, unresolved


def apply_backfill(db: Any, actions: list[dict]) -> int:
    """落库 market_true_ladder（_id=YYYY-MM-DD，幂等 upsert）。"""
    written = 0
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    for action in actions:
        boards = action["ladder"].get("boards") or {}
        db["market_true_ladder"].update_one(
            {"_id": action["date"]},
            {"$set": {"maxTrueBoard": action["ladder"]["maxBoard"],
                      "boards": {k: int(boards.get(k) or 0) for k in LADDER_POOL_KEYS},
                      "source": PROVENANCE_SOURCE, "fetchedAt": stamp}},
            upsert=True)
        written += 1
    return written


async def _fetch_all(date8_to_zt: dict[str, int | None]) -> dict[str, Any]:
    """单事件循环批量拉取 THS 连板层（逐条 try：单日失败不影响整批）。

    日期间隔 0.8s（2026-10-02 风控复盘：THS 限流返空 200+空 info，高频连发会被静默限流）。
    """
    from backend.analysis.hotlist.jev_state import derive_true_ladder_from_pools
    from backend.market_proxy.limitup import get_limitup_service

    svc = get_limitup_service()
    out: dict[str, Any] = {}
    for i, date8 in enumerate(sorted(date8_to_zt)):
        if i > 0:
            await asyncio.sleep(0.8)
        try:
            body = await svc.get_ths_pools(date8, keys=LADDER_POOL_KEYS)
            pools = body.get("pools") if isinstance(body, dict) else None
            out[date8] = derive_true_ladder_from_pools(pools, zt_count=date8_to_zt[date8])
        except Exception as exc:  # 单日失败随 map 返回，由计划层如实登记
            out[date8] = exc
    return out


def fetch_many(date8_to_zt: dict[str, int | None]) -> dict[str, Any]:
    return asyncio.run(_fetch_all(date8_to_zt))


def main() -> None:
    parser = argparse.ArgumentParser(description="真连板锚参考集合回填（THS 连板层历史，同生产口径）")
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--apply", action="store_true", help="落库（缺省只打印计划）")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    actions, frame_served, already, unresolved = plan_backfill(db, args.start, args.end, fetch_many)
    print(f"窗口 {args.start}..{args.end}：帧已供给 {frame_served} 日（锚直读帧）、"
          f"参考已存 {already} 日（幂等跳过）、计划回填 {len(actions)} 日、不可算 {len(unresolved)} 日")
    for action in actions:
        b = action["ladder"]["boards"]
        print(f"  {action['date']} maxTrueBoard={action['ladder']['maxBoard']} "
              f"(一{b.get('one')} 二{b.get('two')} 三{b.get('three')} 四{b.get('four')} 高{b.get('high')})")
    for item in unresolved:
        print(f"  未解决 {item}")
    if not args.apply:
        print("dry 模式（--apply 落库）")
        return
    written = apply_backfill(db, actions)
    print(f"已写库 market_true_ladder {written} 日（source={PROVENANCE_SOURCE}）")


if __name__ == "__main__":
    main()
