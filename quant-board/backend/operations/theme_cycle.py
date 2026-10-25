# -*- coding: utf-8 -*-
"""题材周期 v1 CLI（theme-cycle，2026-10-25）：取数→判定→落库，纯本地零 token。

预登记：docs/hotlist-jev/theme-cycle-v1-preregistration.md；判据在
analysis/hotlist/theme_cycle.py（纯函数，本模块只做单源取数与落库）。
原料单源（预登记 §二）：day_leader_rows（板块封板名单/当日龙一）、jiuyan_streak_map
（真连板）、day_status_of（龙一续断，停牌不算断板）、snapshot_stock_rows（当日八合一
热榜在榜，精英过滤证据 A）、_daily_bars（崩塌注记跌幅）、昨日文档 cycleState 跨日成链。
集合 hotlist_jev_theme_cycle，`_id={date}:THEME_CYCLE`，确定性输出幂等覆盖。

与反包池的关系（预登记 §二裁定）：反包=周期成员状态转移（窗口=周期全长），全市场
反包池当日名单（build_rewrap_pool.rewrapCodes）仅作展示徽标 inMarketRewrapPool。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

from backend.analysis.hotlist.theme_cycle import (
    STAGE_LABELS_CN,
    THEME_CYCLE_VERSION,
    classify_board_cycle,
    panic_note,
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
from backend.operations.theme_leader_baseline import day_leader_rows
from backend.analysis.hotlist.rewrap_pool import build_rewrap_pool

COLLECTION = "hotlist_jev_theme_cycle"
_KIND = "theme_cycle"


def _hotlist_codes_of(db: Any, date: str, dataset_id: str) -> set[str] | None:
    """当日八合一热榜在榜 code 集（15:00 half_hour 帧最新 snapshotId → snapshot_stock_rows）。

    None=帧缺失/行集空（热榜不可考，精英判定降级高度代理+注记）；空集=帧 ok 当日无行
    （合法不在榜）。code 归一 6 位（与 jiuyan 名单同规）。"""
    frame = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date,
         "slotTime": "15:00"}, {"snapshotId": 1},
        sort=[("timestamp", -1), ("snapshotId", -1)])
    if not frame or not frame.get("snapshotId"):
        return None
    rows = db["snapshot_stock_rows"].find(
        {"datasetId": dataset_id, "snapshotId": frame["snapshotId"]}, {"code": 1})
    codes = {str(r.get("code") or "")[-6:] for r in rows if r.get("code")}
    return codes if codes else None


def _prev_cycles_of(db: Any, prev_date: str | None) -> tuple[dict[str, dict], dict[str, set[str]], bool]:
    """昨日周期状态与昨日板块封板集（昨日文档行读；跨日成链唯一来源）。

    返回 ({board: cycleState}, {board: 昨日封板 code 集}, prev_found)。"""
    if not prev_date:
        return {}, {}, False
    doc = db[COLLECTION].find_one({"_id": f"{prev_date}:THEME_CYCLE"},
                                  {"rows.board": 1, "rows.cycleState": 1,
                                   "rows.todaySealed": 1})
    if not doc:
        return {}, {}, False
    states: dict[str, dict] = {}
    sealed: dict[str, set[str]] = {}
    for r in doc.get("rows") or []:
        b = str(r.get("board") or "")
        if not b:
            continue
        if isinstance(r.get("cycleState"), dict):
            states[b] = r["cycleState"]
        cs = r.get("todaySealed")
        if isinstance(cs, list):
            sealed[b] = {str(c) for c in cs}
    return states, sealed, True


def _cycle_leader_states(db: Any, date: str, prev_cycles: dict[str, dict],
                         dataset_id: str) -> dict[str, str | None]:
    """昨日各板块周期现任龙一 → 今日 day_status_of（池权威+日线补洞，停牌不算断板 v4）。

    与 sector_nodes._leader_states 同款取数（sealed_and_info 池权威，禁第二套口径）。"""
    from backend.operations.theme_leader_baseline import sealed_and_info

    out: dict[str, str | None] = {}
    if not prev_cycles:
        return out
    sealed, info, _meta = sealed_and_info(db, date, dataset_id)
    # sealed=None（今日 THS 池缺失）交 day_status_of 决策表日线补证，不在此伪造
    touch = set(info) if info else None
    with bars_need_upto(date):
        for board, st in prev_cycles.items():
            code = str(st.get("leaderCode") or "")
            if not code:
                out[board] = None
                continue
            bars = _daily_bars(code)
            adj = _adj_prev_series(date, code, bars) if bars else {}
            out[board] = day_status_of(code, date, sealed=sealed, touch=touch,
                                       bars=bars or None, adj=adj)
    return out


def _panic_bars_pct(db: Any, date: str, codes: list[str]) -> dict[str, float | None]:
    """brokenElite 各股今日涨跌幅 %（崩塌注记；缺 bars → None 不判）。"""
    out: dict[str, float | None] = {}
    with bars_need_upto(date):
        for code in codes:
            bars = _daily_bars(code)
            tgt = [b for b in (bars or []) if str(b.get("date")) == date]
            if not tgt:
                out[code] = None
                continue
            close, prev = tgt[0].get("close"), tgt[0].get("prevClose")
            if isinstance(close, (int, float)) and isinstance(prev, (int, float)) and prev:
                out[code] = round((close - prev) / prev * 100, 2)
            else:
                out[code] = None
    return out


def _stock_names_of(db: Any, date: str) -> dict[str, str]:
    """当日韭研 final 名单 {6位code: name}（补全纯函数层 stocks/leader 的名字展示）。"""
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
    out: dict[str, str] = {}
    for fl in doc.get("fields") or []:
        for st in fl.get("stocks") or []:
            code = str(st.get("code") or "")[-6:]
            if code and st.get("name"):
                out.setdefault(code, str(st["name"]))
    return out


def _fill_names(rows: list[dict[str, Any]], names: dict[str, str]) -> None:
    """行内 stocks/leader 的 name 补全（纯函数层只产 code/streak，名字由本层注入）。"""
    def _fill_stock(s: dict[str, Any]) -> None:
        if not s.get("name") and s.get("code") in names:
            s["name"] = names[s["code"]]

    for r in rows:
        if r.get("leader") is not None:
            _fill_stock(r["leader"])
        for e in r.get("events") or []:
            for s in e.get("stocks") or []:
                _fill_stock(s)
        for key in ("rewrapElite", "rewrapPlain", "newBenchmark"):
            for s in r.get(key) or []:
                _fill_stock(s)


def settle_day(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, Any]:
    """单日计算+落库（幂等覆盖）；昨日 cycleState 从昨日文档行读（回填升序成链）。"""
    prevs = trading_dates_before(db, date, 2, dataset_id=dataset_id)
    prev_date = prevs[-1] if prevs else None

    today_rows, meta_today = day_leader_rows(db, date, dataset_id, prev_date)
    # 审计 P2-2 同款：final 缺失/为空时 day_leader_rows 返回空列表（jiuyanFinalFound=False），
    # 不检查会把全板块伪装成「无周期平淡」——同 THS 缺失一样整日 unknown。
    today_unavailable: str | None = None
    if today_rows is None:
        today_unavailable = "THS 池缺失，封板集合不可二分"
    elif not meta_today.get("jiuyanFinalFound", True):
        today_unavailable = "韭研 final 缺失/为空，板块封板名单不可考"
        today_rows = None

    prev_cycles, prev_sealed_by_board, prev_found = _prev_cycles_of(db, prev_date)
    streaks = jiuyan_streak_map(db, date, dataset_id)
    hotlist_codes = _hotlist_codes_of(db, date, dataset_id)
    # 全市场反包池当日名单（展示徽标 only，预登记 §二）
    rewrap = build_rewrap_pool(db, date, "final", dataset_id)
    rewrap_codes = set(rewrap.get("rewrapCodes") or [])
    rewrap_pool_n = int(rewrap.get("rewrapN") or 0)

    # 板块覆盖 = 今日有封板板块 ∪ 昨日有周期状态板块（转弱计时/终态维持必须连续成链）
    today_by = {str(r["board"]): r for r in (today_rows or [])}
    boards = sorted(set(today_by) | set(prev_cycles))

    cycle_leader_states = _cycle_leader_states(db, date, prev_cycles, dataset_id)

    # 当日龙一名单内行内字段直接可取；崩塌注记 bars 只对 weakening/terminator 行查
    rows: list[dict[str, Any]] = []
    degraded: list[str] = []
    panic_codes_all: set[str] = set()
    panic_bars: dict[str, float | None] = {}
    for board in boards:
        trow = today_by.get(board)
        prev_state = prev_cycles.get(board)
        if today_rows is None:
            today_codes: list[str] | None = None
        else:
            today_codes = [str(c) for c in (trow or {}).get("boardCodes") or []]
        board_streaks = {c: streaks.get(c) for c in (today_codes or [])}
        leader = None
        if trow and trow.get("code"):
            leader = {"code": str(trow["code"]), "name": trow.get("name"),
                      "streak": trow.get("streak")}
        # 昨日板块封板集（反包判定的「昨日未封」；昨日文档缺失 → None 注记降级）
        prev_sealed: set[str] | None
        if not prev_found:
            prev_sealed = None
        else:
            prev_sealed = prev_sealed_by_board.get(board)
            if prev_sealed is None:
                # 昨日文档在但该板块昨日无封板行（含今日新板块）：合法空集
                prev_sealed = set()
        cls = classify_board_cycle(
            prev_state=prev_state, today_codes=today_codes, leader=leader,
            cycle_leader_state=cycle_leader_states.get(board),
            streaks=board_streaks, prev_sealed=prev_sealed,
            hotlist_codes=hotlist_codes, in_rewrap_pool=rewrap_codes)
        notes = list(cls["notes"])
        if not prev_found and prev_date:
            notes.append("昨日周期文档缺失，周期链断（无周期起步）")
        # 恐慌崩塌注记（预登记 §三.4）：weakening/terminator 行的 brokenElite 今日表现
        if cls["stage"] in ("weakening", "terminator"):
            elite_codes = [str(c) for c in
                           ((cls.get("cycleState") or {}).get("brokenElite") or [])]
            if elite_codes:
                pending = [c for c in elite_codes if c not in panic_bars]
                if pending:
                    panic_bars.update(_panic_bars_pct(db, date, pending))
                    panic_codes_all.update(elite_codes)
                note = panic_note(elite_codes, panic_bars)
                if note:
                    notes.append(note)
        rows.append({
            "board": board,
            "stage": cls["stage"], "stageCn": STAGE_LABELS_CN[cls["stage"]],
            "cycleN": cls["cycleN"], "prevStage": cls["prevStage"],
            "leader": cls["leader"], "leaderState": cls["leaderState"],
            "boardN": len(today_codes) if today_codes is not None else None,
            "events": cls["events"],
            "rewrapElite": cls["rewrapElite"], "rewrapPlain": cls["rewrapPlain"],
            "newBenchmark": cls["newBenchmark"],
            "basis": cls["basis"], "notes": notes,
            "sectorNode": None,             # 对照列，读 sector_nodes 文档后挂
            "todaySealed": today_codes or [],   # 次日反包判定「昨日未封」依据
            "cycleState": cls["cycleState"],
        })

    if today_rows is None:
        degraded.append(f"{date} {today_unavailable}（整日不可判，状态透传）")
        for r in rows:
            r["notes"].append(f"今日不可考根因：{today_unavailable}")
    if not boards:
        degraded.append("今日与昨日窗口内无任何板块记录")

    # 名字补全（纯函数层只产 code/streak；final 缺失日如实缺名）
    if today_rows is not None:
        _fill_names(rows, _stock_names_of(db, date))

    # 对照列：同日 sector_nodes 档位（只读展示，判据零消费——预登记 §一）
    try:
        sn = db["hotlist_jev_sector_nodes"].find_one(
            {"_id": f"{date}:SECTOR_NODES"}, {"rows.board": 1, "rows.node": 1}) or {}
        sn_map = {str(r.get("board") or ""): str(r.get("node") or "")
                  for r in sn.get("rows") or []}
        for r in rows:
            r["sectorNode"] = sn_map.get(r["board"])
    except Exception as exc:  # noqa: BLE001 — 对照列降级不连坐主链
        degraded.append(f"sectorNode 对照列读取失败: {type(exc).__name__}: {exc}")

    # 大盘弱转强三态语境列（预登记 §三.4：只展示不做门控）
    market_state: dict[str, Any] | None = None
    try:
        from backend.analysis.hotlist.weak_to_strong import classify_day
        w = classify_day(db, date, dataset_id)
        if w.get("idx") is not None:
            market_state = {"state": w.get("state"), "idx": w.get("idx"),
                            "hit": bool(w.get("hit"))}
    except Exception as exc:  # noqa: BLE001
        degraded.append(f"marketState 语境列读取失败: {type(exc).__name__}: {exc}")

    status = "degraded" if today_rows is None else "ok"
    doc = {"_id": f"{date}:THEME_CYCLE", "kind": _KIND, "tradingDate": date,
           "version": THEME_CYCLE_VERSION, "status": status,
           "computedAt": datetime.now(timezone.utc),
           "marketState": market_state,
           "rows": rows, "degraded": degraded,
           "meta": {"thsFound": today_rows is not None,
                    "prevDate": prev_date, "prevFound": prev_found,
                    "hotlistFound": hotlist_codes is not None,
                    "rewrapPoolN": rewrap_pool_n,
                    "streakSource": "jiuyan_streak_map"}}
    db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    dist: dict[str, int] = {}
    for r in rows:
        dist[r["stage"]] = dist.get(r["stage"], 0) + 1
    return {"date": date, "status": status, "boards": len(rows),
            "stages": {STAGE_LABELS_CN[k]: v for k, v in sorted(dist.items())},
            "degraded": degraded}


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
    ap = argparse.ArgumentParser(description="题材周期 v1（龙头锚四阶段状态机，零 token）")
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


def _recent_final_date(db: Any) -> str | None:
    doc = db["jiuyan_action"].find_one({"_id": {"$regex": ":final$"}},
                                       {"tradingDate": 1},
                                       sort=[("tradingDate", -1)])
    return str(doc.get("tradingDate")) if doc and doc.get("tradingDate") else None


if __name__ == "__main__":
    sys.exit(main())
