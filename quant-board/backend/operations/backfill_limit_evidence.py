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


FRAME_FLAG = "limit_summary_backfilled"


def plan_frame_backfill(db, start: str, end: str, fetch_many) -> tuple[list[dict], list[str], list[str]]:
    """15:00 帧 limitSummary 回填计划（仅 15:00——THS 历史=EOD 语义，盘中槽不可重建绝不伪造）。

    返回 (回填动作, 健康跳过日, 未解决日)；动作含完整 limitSummary（含 provenance）。
    """
    frames = list(db["snapshot_frames"].find(
        {"datasetId": "dragonboard_live", "type": "half_hour", "slotTime": "15:00",
         "tradingDate": {"$gte": start, "$lte": end}},
        {"tradingDate": 1, "limitSummary": 1}))
    healthy: list[str] = []
    need: list[str] = []
    frame_by_date: dict[str, dict] = {}
    for f in frames:
        date = str(f.get("tradingDate"))
        zt = ((f.get("limitSummary") or {}).get("zhaban") or {}).get("ztCount")
        if _is_valid_zt(zt):
            healthy.append(date)
            continue
        need.append(date.replace("-", ""))
        frame_by_date[date] = f
    summaries = fetch_many(need) if need else {}
    actions: list[dict] = []
    unresolved: list[str] = []
    for date, frame in frame_by_date.items():
        result = summaries.get(date.replace("-", ""))
        if isinstance(result, Exception):
            unresolved.append(f"{date}:THS历史拉取失败:{str(result)[:80]}")
            continue
        if not isinstance(result, dict) or not result:
            unresolved.append(f"{date}:THS历史无有效涨停数据")
            continue
        summary = {**result, "source": PROVENANCE_SOURCE,
                   "backfilledAt": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")}
        actions.append({"date": date, "frameId": frame["_id"], "summary": summary})
    return actions, healthy, unresolved


def apply_frame_backfill(db, actions: list[dict]) -> int:
    """执行写库：$set limitSummary + $addToSet qualityFlags 标记（不覆盖其他帧字段）。"""
    for a in actions:
        db["snapshot_frames"].update_one(
            {"_id": a["frameId"]},
            {"$set": {"limitSummary": a["summary"]},
             "$addToSet": {"qualityFlags": FRAME_FLAG}})
    return len(actions)


def build_enrich_blocks(summary: dict | None) -> dict | None:
    """THS summary → {drawdown, sealQuality} 富集块（带回填 provenance）；summary 无效返回 None。"""
    if not isinstance(summary, dict) or not summary:
        return None
    dd, sq = summary.get("drawdown"), summary.get("sealQuality")
    if not isinstance(dd, dict) or not isinstance(sq, dict):
        return None
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
    return {
        "drawdown": {**{k: dd.get(k) for k in ("count", "avgDrawdownPct", "deepestDrawdownPct")},
                     "source": PROVENANCE_SOURCE, "backfilledAt": stamp},
        "sealQuality": {**{k: sq.get(k) for k in
                           ("byzCount", "hardCount", "rottenCount", "rottenShare", "avgSucRate")},
                        "source": PROVENANCE_SOURCE, "backfilledAt": stamp},
    }


def plan_enrich(db, start: str, end: str, fetch_many) -> tuple[list[dict], list[dict], int, list[str]]:
    """15:00 帧 + v1 槽文档补 drawdown/sealQuality 富集块（THS 历史源，EOD 语义）。

    跳过：已带 drawdown 块的（幂等）；盘中槽不在目标内（THS 历史=EOD 态，绝不伪造盘中）。
    返回 (帧动作, v1动作, 跳过数, 未解决)。
    """
    frames = list(db["snapshot_frames"].find(
        {"datasetId": "dragonboard_live", "type": "half_hour", "slotTime": "15:00",
         "tradingDate": {"$gte": start, "$lte": end}},
        {"tradingDate": 1, "limitSummary.drawdown": 1}))
    docs = list(db["hotlist_jev_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "kind": "slot",
         "slotTime": "15:00", "tradingDate": {"$gte": start, "$lte": end}},
        {"tradingDate": 1, "evidenceRaw.limit.drawdown": 1}))

    def _has_block(obj, path):
        cur = obj
        for p in path:
            cur = cur.get(p) if isinstance(cur, dict) else None
        return isinstance(cur, dict)

    need: list[str] = []
    frame_by_date: dict[str, dict] = {}
    for f in frames:
        if not _has_block(f.get("limitSummary") or {}, ("drawdown",)):
            need.append(str(f["tradingDate"]))
            frame_by_date[str(f["tradingDate"])] = f
    doc_by_date: dict[str, dict] = {}
    for d in docs:
        if not _has_block((d.get("evidenceRaw") or {}).get("limit") or {}, ("drawdown",)):
            doc_by_date[str(d["tradingDate"])] = d
            if str(d["tradingDate"]) not in need:
                need.append(str(d["tradingDate"]))

    summaries = fetch_many([n.replace("-", "") for n in need]) if need else {}
    frame_actions: list[dict] = []
    doc_actions: list[dict] = []
    unresolved: list[str] = []
    skipped = len(frames) + len(docs) - len(frame_by_date) - len(doc_by_date)
    for date in sorted(set(frame_by_date) | set(doc_by_date)):
        blocks = build_enrich_blocks(summaries.get(date.replace("-", "")))
        if blocks is None:
            unresolved.append(f"{date}:THS历史无有效数据")
            continue
        if date in frame_by_date:
            frame_actions.append({"frameId": frame_by_date[date]["_id"], "date": date, "blocks": blocks})
        if date in doc_by_date:
            doc_actions.append({"docId": doc_by_date[date]["_id"], "date": date, "blocks": blocks})
    return frame_actions, doc_actions, skipped, unresolved


def apply_enrich(db, frame_actions: list[dict], doc_actions: list[dict]) -> tuple[int, int]:
    """写库：帧 $set limitSummary.drawdown/sealQuality（保留同帧其他块）；v1 文档同理。"""
    for a in frame_actions:
        for block in ("drawdown", "sealQuality"):
            db["snapshot_frames"].update_one(
                {"_id": a["frameId"]}, {"$set": {f"limitSummary.{block}": a["blocks"][block]}})
    for a in doc_actions:
        for block in ("drawdown", "sealQuality"):
            db["hotlist_jev_sentiment"].update_one(
                {"_id": a["docId"]}, {"$set": {f"evidenceRaw.limit.{block}": a["blocks"][block]}})
    return len(frame_actions), len(doc_actions)


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
    parser.add_argument("--frames", action="store_true",
                        help="连带回填 15:00 帧 limitSummary（仅 15:00，EOD 语义匹配）")
    parser.add_argument("--enrich", action="store_true",
                        help="富集模式：为 15:00 帧/v1 槽文档补 drawdown/sealQuality 块（THS 历史，幂等）")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()

    memo: dict = {}

    def fetch_many(date8_list):
        todo = [d for d in date8_list if d not in memo]
        if todo:
            memo.update(fetch_many_ths(todo))
        return {d: memo[d] for d in date8_list}

    actions, healthy, unresolved = plan_backfill(db, args.start, args.end, fetch_many)
    jy = _jiuyan_totals(db, args.start, args.end)

    print(f"== 涨停池证据回填计划 {args.start} → {args.end}（{'APPLY' if args.apply else 'DRY-RUN'}）==")
    for a in actions:
        lim = a["limit"]
        print(f"[回填-v1文档] {a['date']}: zt={lim['ztCount']} maxBoard={lim['maxBoard']} "
              f"zhaban={lim['zhabanRate']}% fengban={lim['fengbanRate']}% "
              f"boards={lim['boards']} | 旁证 jiuyan={jy.get(a['date'], '无')}")
    print(f"[跳过] v1 文档健康日 {len(healthy)} 个: {healthy or '无'}")
    print(f"[未解决] v1 文档 {len(unresolved)} 个: {unresolved or '无'}")

    frame_actions: list[dict] = []
    if args.frames:
        f_actions, f_healthy, f_unresolved = plan_frame_backfill(db, args.start, args.end, fetch_many)
        frame_actions = f_actions
        for a in f_actions:
            s = a["summary"]
            z = s.get("zhaban") or {}
            print(f"[回填-15:00帧] {a['date']}: zt={z.get('ztCount')} maxBoard="
                  f"{(s.get('continuousBoards') or {}).get('maxBoard')} zhaban={z.get('rate')}%")
        print(f"[跳过] 15:00 帧健康日 {len(f_healthy)} 个: {f_healthy or '无'}")
        print(f"[未解决] 15:00 帧 {len(f_unresolved)} 个: {f_unresolved or '无'}")

    if args.enrich:
        e_frames, e_docs, e_skip, e_unresolved = plan_enrich(db, args.start, args.end, fetch_many)
        for a in e_frames:
            dd, sq = a["blocks"]["drawdown"], a["blocks"]["sealQuality"]
            print(f"[富集-帧] {a['date']}: 回撤 {dd.get('count')} 家(均 {dd.get('avgDrawdownPct')}%) "
                  f"烂板 {sq.get('rottenCount')}(率 {sq.get('rottenShare')}) 成功率 {sq.get('avgSucRate')}")
        for a in e_docs:
            print(f"[富集-v1文档] {a['date']}")
        print(f"[跳过] 已有块 {e_skip} 个；[未解决] {len(e_unresolved)} 个: {e_unresolved or '无'}")

    if args.apply:
        n = apply_backfill(db, actions)
        print(f"已写库 v1 文档 {n} 个（evidenceRaw.limit，标记 source={PROVENANCE_SOURCE}）")
        if args.frames:
            nf = apply_frame_backfill(db, frame_actions)
            print(f"已写库 15:00 帧 {nf} 个（limitSummary+qualityFlags[{FRAME_FLAG}]）")
        if args.enrich:
            ef, ed = apply_enrich(db, e_frames, e_docs)
            print(f"已富集 帧 {ef} + v1 文档 {ed}（drawdown/sealQuality 块，source={PROVENANCE_SOURCE}）")
    else:
        print("dry-run 未写库；确认后加 --apply 执行")


if __name__ == "__main__":
    main()
