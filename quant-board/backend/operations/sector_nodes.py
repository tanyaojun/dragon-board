# -*- coding: utf-8 -*-
"""板块节点 v1 CLI（sector-nodes，2026-10-24）：取数→判定→落库，纯本地零 token。

预登记：docs/hotlist-jev/sector-nodes-v1-preregistration.md；判据在
analysis/hotlist/sector_nodes.py（纯函数，本模块只做单源取数与落库）。
单一事实源（预登记 §二）：day_leader_rows（家数/龙一/梯队/断板/炸板面）、
board_count_history（家数序列）、_promotion_stats（晋级链，relay_structure 同款）、
day_status_of（龙头续断，停牌不算断板 v4）、board_count_history 21 日分位锚。
集合 hotlist_jev_sector_nodes，`_id={date}:SECTOR_NODES`，确定性输出幂等覆盖。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

from backend.analysis.hotlist.sector_nodes import (
    NODE_LABELS_CN,
    SECTOR_NODE_VERSION,
    assemble_rows,
)
from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.operations.jev_label_jiuyan import (
    _adj_prev_series,
    _daily_bars,
    bars_need_upto,
    day_status_of,
    jiuyan_streak_map,
    trading_dates_before,
)
from backend.analysis.hotlist.sector_agg import (
    AGG_VERSION,
    aggregate_day,
    assemble_agg_rows,
)
from backend.operations.jev_relay_index import _promotion_stats
from backend.operations.theme_leader_baseline import (
    board_count_history,
    day_leader_rows,
    sealed_and_info,
)

COLLECTION = "hotlist_jev_sector_nodes"
_KIND = "sector_nodes"


def _prev_nodes_of(db: Any, prev_date: str | None) -> dict[str, str] | None:
    """昨日节点（doc 读口）；昨日文档缺失 → None（弱转强不贴标，注记）。"""
    if not prev_date:
        return None
    doc = db[COLLECTION].find_one({"_id": f"{prev_date}:SECTOR_NODES"}, {"rows.node": 1,
                                                                        "rows.board": 1})
    if not doc:
        return None
    return {str(r["board"]): str(r["node"]) for r in doc.get("rows") or []
            if r.get("board") and r.get("node")}


def _promotion_by_board(db: Any, prev_date: str | None, date: str,
                        dataset_id: str) -> dict[str, Any]:
    """晋级链按板块归属（relay_structure 同款：prev pool 首个板块口径）。

    promGe2 = 晋级股中今日真连板 ≥2 的家数（主升判据「二板以上晋级」）。
    """
    if not prev_date:
        return {"ok": False, "reason": "无昨日交易日", "byBoard": {}, "ge2ByBoard": {}}
    stats = _promotion_stats(db, prev_date, date, dataset_id)
    if not stats.get("ok"):
        return {"ok": False, "reason": stats.get("reason") or "晋级率不可算",
                "byBoard": {}, "ge2ByBoard": {}}
    prev_pool = stats["prev_pool"]
    streaks = jiuyan_streak_map(db, date, dataset_id)
    by_board: dict[str, int] = {}
    ge2_by_board: dict[str, int] = {}
    for c in stats["promoted"]:
        board = (prev_pool.get(c) or {}).get("board")
        if not board:
            continue
        by_board[board] = by_board.get(board, 0) + 1
        if isinstance(streaks.get(c), int) and streaks[c] >= 2:
            ge2_by_board[board] = ge2_by_board.get(board, 0) + 1
    return {"ok": True, "byBoard": by_board, "ge2ByBoard": ge2_by_board}


def _leader_states(db: Any, date: str, prev_rows: list[dict[str, Any]] | None,
                   dataset_id: str) -> dict[str, str]:
    """昨日各板块龙一 → 今日状态（day_status_of：停牌不算断板，v4）。"""
    if not prev_rows:
        return {}
    sealed, info, _meta = sealed_and_info(db, date, dataset_id)
    # sealed=None（今日 THS 池缺失）交 day_status_of 决策表日线补证，不在此伪造
    touch = set(info) if info else None
    out: dict[str, str] = {}
    for r in prev_rows:
        board = str(r.get("board") or "")
        # day_leader_rows 行形状平铺：龙一 code 就是行自身 code（非嵌套 leader.code）
        code = str(r.get("code") or "")
        if not board or not code:
            continue
        bars = _daily_bars(code)
        adj = _adj_prev_series(date, code, bars) if bars else {}
        out[board] = day_status_of(code, date, sealed=sealed, touch=touch,
                                   bars=bars or None, adj=adj)
    return out


# V2 影子聚合的窗口池进程缓存（键 (date, dataset_id)）：回填升序成链时
# 相邻 settle_day 的窗口日高度重叠，逐日只新增 1 次 day_leader_rows。
# 消费形态约束（审计 2026-10-24 P3）：缓存键不含源数据版本——final 被重采覆写后
# 本进程内池是旧值。当前只允许短命子进程消费（backfill CLI / 盘后链 sectorNodes
# 步，缓存随进程消亡）；若未来把 settle_day 挂进 8000 长驻进程（如进程内 rerun
# API），必须先加版本键或改直查（防复刻 2026-10-23 源文档版本戳事故）。
_POOL_CACHE: dict[tuple[str, str], dict[str, set[str]] | None] = {}


def _window_pool_of(db: Any, date: str, dataset_id: str) -> dict[str, set[str]] | None:
    """单日 {板块: 封板 code 集}；THS 池缺失 / final 缺失（空列表）→ None（不进窗口）。"""
    key = (date, dataset_id)
    if key in _POOL_CACHE:
        return _POOL_CACHE[key]
    rows, meta = day_leader_rows(db, date, dataset_id)
    pool: dict[str, set[str]] | None = None
    if rows is not None and meta.get("jiuyanFinalFound", True):
        pool = {}
        for r in rows:
            b = str(r.get("board") or "")
            if b:
                pool[b] = {str(c) for c in (r.get("boardCodes") or [])}
    _POOL_CACHE[key] = pool
    return pool


def _agg_rows_compute(db: Any, date: str, dataset_id: str) -> list[dict[str, Any]]:
    """V2 聚合行全量计算（预登记 sector-nodes-v2-aggregate §二/§三）。

    窗口 = 今日（若池 ok）+ 最近 10 个池 ok 交易日（trading_dates_before 候选里过滤）；
    统计日行情棒独立于韭研池（节点 degraded 不停算聚合——聚合与节点判定解耦，
    且 v2 判档在先，必须先于 assemble_rows 算好）。
    """
    # trading_dates_before 升序返回（旧→新）——窗口要「今日+最近 10 个池 ok 日」，
    # 必须 reverse 成新→旧再截断（首版未 reverse 实测取成最旧 9 日，2026-10-24 回填抓出）
    candidates = [date] + list(reversed(
        trading_dates_before(db, date, 15, dataset_id=dataset_id)))
    pool_list: list[tuple[str, dict[str, set[str]]]] = []
    for d in candidates:
        pool = _window_pool_of(db, d, dataset_id)
        if pool is not None:
            pool_list.append((d, pool))
        if len(pool_list) >= 10:
            break
    if not pool_list:
        return []
    members_all: set[str] = set()
    for _d, pool in pool_list:
        for codes in pool.values():
            members_all |= codes
    bars_by_code: dict[str, list[dict[str, Any]]] = {}
    with bars_need_upto(date):
        for code in sorted(members_all):
            bars_by_code[code] = _daily_bars(code)
    return assemble_agg_rows(target_date=date, window_pool=pool_list,
                             bars_by_code=bars_by_code)


def _agg_mount(agg_rows: list[dict[str, Any]],
               rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """额外行 = N10 并集中不在当日判档行集的板块（aggExtraRows，不扩行集不进 nodeDist）。"""
    boards = {str(r.get("board") or "") for r in rows}
    return [ar for ar in agg_rows if ar["board"] not in boards]


# V3 静态全成分聚合（2026-10-25，板块节点三期）：与 aggN10 同式同棒链
# （aggregate_day 复用），成员=映射产业全成分并集（sector_industry_map）。
# 已知局限：产业库为活库无历史——历史回填日读到的是「当前批次成分」的前视口径，
# 行级 batchDates 披露成分批次；影子列不进判据（同 V2 范式）。
AGG_STATIC_VERSION = "2026-10-25a"


def _static_rows_compute(db: Any, date: str, boards: list[str]) -> dict[str, dict[str, Any]]:
    """{板块: aggStatic}。未映射（产业库未收录）/空成分快照如实标注，不伪 0。

    映射/成分库读取异常落行级 reason（影子列不连坐节点主链，§4.0 fail-visible）。
    """
    from backend.operations.sector_industry_map import static_members
    if not boards:
        return {}
    members_by_board: dict[str, dict[str, Any]] = {}
    for b in boards:
        try:
            members_by_board[b] = static_members(db, b)
        except Exception as exc:  # noqa: BLE001 — 影子列降级，主链照常
            members_by_board[b] = {"mapped": False,
                                   "reason": f"映射读取失败: {type(exc).__name__}: {exc}"}
    all_codes: set[str] = set()
    for m in members_by_board.values():
        if m.get("mapped") and m.get("codes"):
            all_codes |= m["codes"]
    bars_by_code: dict[str, list[dict[str, Any]]] = {}
    if all_codes:
        with bars_need_upto(date):
            for code in sorted(all_codes):
                bars_by_code[code] = _daily_bars(code)
    out: dict[str, dict[str, Any]] = {}
    for board in boards:
        m = members_by_board[board]
        if not m.get("mapped") or not m.get("codes"):
            out[board] = {"mapped": bool(m.get("mapped")),
                          "reason": m.get("reason") or "成分集为空"}
            continue
        stats = aggregate_day(target_date=date, members=m["codes"],
                              bars_by_code=bars_by_code, window_days=0)
        out[board] = {"mapped": True, **stats,
                      "industries": m["industries"], "batchDates": m["batchDates"],
                      "sharesMedian": m["sharesMedian"]}
    return out


def settle_day(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, Any]:
    """单日计算+落库（幂等覆盖）；昨日节点从昨日文档读（回填升序天然成链）。"""
    prevs = trading_dates_before(db, date, 2, dataset_id=dataset_id)
    prev_date = prevs[-1] if prevs else None
    prev2_date = prevs[-2] if len(prevs) >= 2 else None

    today_rows, meta_today = day_leader_rows(db, date, dataset_id, prev_date)
    prev_rows, _pmeta = day_leader_rows(db, prev_date, dataset_id) if prev_date else (None, None)
    prev2_rows, _p2meta = (day_leader_rows(db, prev2_date, dataset_id)
                           if prev2_date else (None, None))

    prom = _promotion_by_board(db, prev_date, date, dataset_id)
    leader_status = _leader_states(db, date, prev_rows, dataset_id)
    count_hist = board_count_history(db, date, days=21, dataset_id=dataset_id)
    prev_nodes = _prev_nodes_of(db, prev_date)
    # v2：聚合先行（判档消费 aggN10——条款 1 资金先手分支/条款 2 防守注记）
    agg_rows = _agg_rows_compute(db, date, dataset_id)
    agg_by_board = {str(ar["board"]): ar["aggN10"] for ar in agg_rows}

    # 审计 P2-2：day_leader_rows 只因 THS 池缺失返回 None；韭研 final 缺失/为空时
    # 返回空列表（jiuyanFinalFound=False）——不检查会把窗口内全板块伪装成「0 家冰点」。
    # final 不可考与 THS 不可考同款降级（unknown+家数 None），只改本层不改共享单源。
    today_unavailable_reason: str | None = None
    if today_rows is None:
        today_unavailable_reason = "THS 池缺失，封板集合不可二分"
    elif not meta_today.get("jiuyanFinalFound", True):
        today_unavailable_reason = "韭研 final 缺失/为空，板块家数不可考"
        today_rows = None
    built = assemble_rows(date=date, today_rows=today_rows, prev_rows=prev_rows,
                          prev_date=prev_date, prev2_rows=prev2_rows,
                          prev2_date=prev2_date, count_hist=count_hist,
                          prom=prom, leader_status=leader_status,
                          prev_nodes=prev_nodes,
                          today_unavailable_reason=today_unavailable_reason,
                          agg_by_board=agg_by_board)
    status = "degraded" if today_rows is None else "ok"
    # 聚合挂载（判档已用）+ 额外行（N10 独有板块，不进 nodeDist）
    agg_extra = _agg_mount(agg_rows, built["rows"])
    for r in built["rows"]:
        m = agg_by_board.get(str(r.get("board") or ""))
        if m is not None:
            r["aggN10"] = m
    # V3-3：静态全成分聚合挂全部行（判档行 + aggExtra 行——「未收录」本身是观察信息）
    static_boards = sorted(({str(r.get("board") or "") for r in built["rows"]}
                            | {str(ar.get("board") or "") for ar in agg_extra}) - {""})
    static_by_board = _static_rows_compute(db, date, static_boards)
    for r in built["rows"]:
        r["aggStatic"] = static_by_board.get(str(r.get("board") or ""),
                                             {"mapped": False, "reason": "未计算"})
    for ar in agg_extra:
        ar["aggStatic"] = static_by_board.get(str(ar.get("board") or ""),
                                              {"mapped": False, "reason": "未计算"})
    static_mapped = sum(1 for v in static_by_board.values() if v.get("mapped"))
    doc = {"_id": f"{date}:SECTOR_NODES", "kind": _KIND, "tradingDate": date,
           "version": SECTOR_NODE_VERSION, "status": status,
           "computedAt": datetime.now(timezone.utc),
           "rows": built["rows"], "degraded": built["degraded"],
           "aggExtraRows": agg_extra,
           "meta": {"thsFound": today_rows is not None,
                    "prevDate": prev_date, "prev2Date": prev2_date,
                    "promOk": bool(prom.get("ok")),
                    "aggVersion": AGG_VERSION,
                    "aggExtraCount": len(agg_extra),
                    "aggStaticVersion": AGG_STATIC_VERSION,
                    "staticMapped": static_mapped,
                    "staticUnmapped": len(static_by_board) - static_mapped,
                    "streakSource": "jiuyan_streak_map"}}
    db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    dist: dict[str, int] = {}
    for r in built["rows"]:
        dist[r["node"]] = dist.get(r["node"], 0) + 1
    return {"date": date, "status": status, "boards": len(built["rows"]),
            "nodes": {NODE_LABELS_CN[k]: v for k, v in sorted(dist.items())},
            "degraded": built["degraded"]}


def _recent_final_date(db: Any) -> str | None:
    doc = db["jiuyan_action"].find_one({"_id": {"$regex": ":final$"}},
                                       {"tradingDate": 1},
                                       sort=[("tradingDate", -1)])
    return str(doc.get("tradingDate")) if doc and doc.get("tradingDate") else None


def backfill(db: Any, start: str, end: str,
             dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, Any]:
    """区间回填（升序逐日，昨日文档自然成链；确定性输出幂等覆盖）。"""
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$gte": start, "$lte": end},
         "_id": {"$regex": ":final$"}}, {"tradingDate": 1}) if d.get("tradingDate")})
    results = []
    for d in dates:
        results.append(settle_day(db, d, dataset_id))
    ok_n = sum(1 for r in results if r["status"] == "ok")
    return {"start": start, "end": end, "days": len(results), "ok": ok_n,
            "degradedDays": [r["date"] for r in results if r["status"] != "ok"],
            "results": results}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="板块节点 v1（确定性判定，零 token）")
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
