# -*- coding: utf-8 -*-
"""题材周期 v2 CLI（theme-cycle，2026-10-25）：取数→判定→落库，纯本地零 token。

预登记：docs/hotlist-jev/theme-cycle-v1-preregistration.md（§〇 v2 代际修订：对象=题材≠板块）；
判据在 analysis/hotlist/theme_cycle.py（纯函数，本模块只做单源取数与落库）。

**对象定义（v2，用户裁定）**：题材=外部事件驱动的炒作主题，载体=themes 概念标签+
theme_stock_mappings 成分映射（一股多题材，题材独立聚合重叠计入）；板块=产业链内部驱动，
由板块节点（sector_nodes）覆盖，两维度不互为对照（v1 误用韭研分组为对象已归档重建）。
词典治理单源=theme_dict_governance（role 分层 branch/episode/style/exclude + kword 别名 +
jiuyan 板块对照，用户 2026-10-25 裁定）。

原料单源（预登记 §二）：sealed_and_info（封板集合）、jiuyan_streak_map（真连板）、
day_status_of（龙一续断）、theme_dict_governance+themes+theme_stock_mappings（题材归属）、
snapshot_stock_rows（热榜在榜）、_daily_bars（崩塌注记）。
集合 hotlist_jev_theme_cycle，`_id={date}:THEME_CYCLE`，确定性输出幂等覆盖。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
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
from backend.operations.theme_leader_baseline import sealed_and_info
from backend.analysis.hotlist.theme_leader_ammo import rank_board_stocks
from backend.analysis.hotlist.rewrap_pool import build_rewrap_pool

COLLECTION = "hotlist_jev_theme_cycle"
_KIND = "theme_cycle"
GOV_COLLECTION = "theme_dict_governance"

# 题材行集门槛（预登记 §二.2：当日题材封板 ≥2 家出行；链延续题材例外）
THEME_MIN_BOARD_N = 2


def _theme_map(db: Any) -> dict[str, list[dict[str, Any]]]:
    """{6位code: [{themeId, name, role, jiuyanBoard}]}（全量题材归属，含 style/exclude）。

    治理单源 theme_dict_governance：role 四类全保留（episode/branch 进聚合，
    style/exclude 由 _theme_day_rows 分流披露）；role 缺失（上游新增题材未治理）
    兜底 branch 并由 _gov_missing_n 计数披露。进程内缓存：CLI 子进程短命安全；
    映射每日 08:30 刷新，跨日新进程重读。
    """
    if getattr(_theme_map, "_cache", None) is not None:
        return _theme_map._cache  # type: ignore[attr-defined]
    roles = {d["themeId"]: d for d in db[GOV_COLLECTION].find({"kind": "role"})}
    jy = {d["themeId"]: d["jiuyanBoard"] for d in db[GOV_COLLECTION].find({"kind": "jiuyan"})}
    theme_names = {str(d["id"]): d["name"] for d in db["themes"].find({})}
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in db["theme_stock_mappings"].find({}, {"themeId": 1, "stockCode": 1}):
        tid = str(m.get("themeId"))
        code = str(m.get("stockCode") or "")[-6:]
        if not code or tid not in theme_names:
            continue
        r = roles.get(tid)
        out[code].append({"themeId": tid, "name": theme_names[tid],
                          "role": r.get("role") if r else "branch",
                          "jiuyanBoard": jy.get(tid)})
    _theme_map._cache = dict(out)  # type: ignore[attr-defined]
    return _theme_map._cache  # type: ignore[attr-defined]


def _gov_missing_n(db: Any) -> int:
    """治理 role 覆盖缺口数（themes 中无 role 行的题材数，fail-visible 披露）。"""
    governed = {d["themeId"] for d in db[GOV_COLLECTION].find({"kind": "role"}, {"themeId": 1})}
    return sum(1 for d in db["themes"].find({}, {"id": 1}) if str(d.get("id")) not in governed)


def _theme_day_rows(db: Any, date: str, dataset_id: str,
                    theme_map: dict[str, list[dict[str, Any]]]
                    ) -> tuple[list[dict] | None, dict]:
    """当日题材聚合行（题材独立聚合重叠计入，预登记 §二.2）。

    返回 (rows, meta)；rows=None=THS 池缺失（不可二分）；final 缺失→rows=[]+meta 标志
    （调用方整日 unknown，不伪装）。每行：theme/boardCodes/code(龙一)/name/streak/
    boardN/ladderShape/secondStreak + jiuyanBoard 对照。
    """
    sealed, info, meta = sealed_and_info(db, date, dataset_id)
    if sealed is None:
        return None, meta
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
    stock_info: dict[str, dict] = {}
    for fl in doc.get("fields") or []:
        for st in fl.get("stocks") or []:
            code = str(st.get("code") or "")[-6:]
            if code and code not in stock_info:
                stock_info[code] = {"name": st.get("name"), "time": st.get("time")}
    streaks = jiuyan_streak_map(db, date, dataset_id)
    grouped: dict[str, list[dict]] = defaultdict(list)
    grouped_meta: dict[str, dict] = {}
    unmapped: list[str] = []
    excluded: list[str] = []
    for code in sorted(sealed):
        ts = theme_map.get(code)
        if not ts:
            unmapped.append(code)
            continue
        s = {"code": code, "name": stock_info.get(code, {}).get("name"),
             "time": stock_info.get(code, {}).get("time"), "streak": streaks.get(code)}
        joined = False
        for t in ts:
            if t.get("role") not in ("episode", "branch"):
                continue          # style/exclude 题材不进题材周期聚合（预登记 §二.2）
            grouped[t["name"]].append(s)
            grouped_meta.setdefault(t["name"], t)
            joined = True
        if not joined:
            excluded.append(code)
    rows: list[dict] = []
    for theme in sorted(grouped):
        stocks = grouped[theme]
        ranked = rank_board_stocks(stocks)
        leader = ranked[0]
        others = [s for s in stocks if s["code"] != leader["code"]]
        shape = {"first": 0, "two": 0, "threePlus": 0, "unknown": 0}
        for s in stocks:
            sv = s["streak"]
            if sv is None:
                shape["unknown"] += 1
            elif sv == 1:
                shape["first"] += 1
            elif sv == 2:
                shape["two"] += 1
            else:
                shape["threePlus"] += 1
        meta_row = grouped_meta.get(theme, {})
        rows.append({
            "theme": theme,
            "themeId": meta_row.get("themeId"),
            "role": meta_row.get("role"),
            "jiuyanBoard": meta_row.get("jiuyanBoard"),
            "boardCodes": [s["code"] for s in stocks],
            "code": leader["code"], "name": leader.get("name"),
            "streak": leader["streak"], "time": leader.get("time"),
            "boardN": len(stocks),
            "ladderShape": shape,
            "secondStreak": max((s["streak"] for s in others
                                 if isinstance(s["streak"], int)), default=None),
        })
    meta["unmappedCodes"] = unmapped
    meta["excludedCodes"] = excluded
    return rows, meta


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


def _prev_cycles_of(db: Any, prev_date: str | None
                    ) -> tuple[dict[str, dict], dict[str, set[str]], bool]:
    """昨日周期状态与昨日题材封板集（昨日文档行读；跨日成链唯一来源）。"""
    if not prev_date:
        return {}, {}, False
    doc = db[COLLECTION].find_one({"_id": f"{prev_date}:THEME_CYCLE"},
                                  {"rows.theme": 1, "rows.cycleState": 1,
                                   "rows.todaySealed": 1})
    if not doc:
        return {}, {}, False
    states: dict[str, dict] = {}
    sealed: dict[str, set[str]] = {}
    for r in doc.get("rows") or []:
        t = str(r.get("theme") or "")
        if not t:
            continue
        if isinstance(r.get("cycleState"), dict):
            states[t] = r["cycleState"]
        cs = r.get("todaySealed")
        if isinstance(cs, list):
            sealed[t] = {str(c) for c in cs}
    return states, sealed, True


def _cycle_leader_states(db: Any, date: str, prev_cycles: dict[str, dict],
                         dataset_id: str) -> dict[str, str | None]:
    """昨日各题材周期现任龙一 → 今日 day_status_of（池权威+日线补洞，停牌不算断板）。

    与 sector_nodes._leader_states 同款取数（sealed_and_info 池权威，禁第二套口径）。"""
    out: dict[str, str | None] = {}
    if not prev_cycles:
        return out
    sealed, info, _meta = sealed_and_info(db, date, dataset_id)
    touch = set(info) if info else None
    with bars_need_upto(date):
        for theme, st in prev_cycles.items():
            code = str(st.get("leaderCode") or "")
            if not code:
                out[theme] = None
                continue
            bars = _daily_bars(code)
            adj = _adj_prev_series(date, code, bars) if bars else {}
            out[theme] = day_status_of(code, date, sealed=sealed, touch=touch,
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

    theme_map = _theme_map(db)
    today_rows, meta_today = _theme_day_rows(db, date, dataset_id, theme_map)
    # 审计 P2-2 同款：final 缺失/为空时不伪装「无周期平淡」，同 THS 缺失整日 unknown。
    today_unavailable: str | None = None
    if today_rows is None:
        today_unavailable = "THS 池缺失，封板集合不可二分"
    elif not meta_today.get("jiuyanFinalFound", True):
        today_unavailable = "韭研 final 缺失/为空，封板名单不可考"
        today_rows = None

    prev_cycles, prev_sealed_by_board, prev_found = _prev_cycles_of(db, prev_date)
    streaks = jiuyan_streak_map(db, date, dataset_id)
    hotlist_codes = _hotlist_codes_of(db, date, dataset_id)
    rewrap = build_rewrap_pool(db, date, "final", dataset_id)
    rewrap_codes = set(rewrap.get("rewrapCodes") or [])
    rewrap_pool_n = int(rewrap.get("rewrapN") or 0)

    # 题材行集（预登记 §二.2）：今日 ≥2 家题材 ∪ 昨日已有 cycleState 题材（链延续例外；
    # 今日 1 家的链延续题材照常演化，今日 1 家的新题材不出行）
    today_all = {str(r["theme"]): r for r in (today_rows or [])}
    today_by = {t: r for t, r in today_all.items() if int(r.get("boardN") or 0) >= THEME_MIN_BOARD_N}
    themes = sorted(set(today_by) | set(prev_cycles))

    cycle_leader_states = _cycle_leader_states(db, date, prev_cycles, dataset_id)

    rows: list[dict[str, Any]] = []
    degraded: list[str] = []
    panic_bars: dict[str, float | None] = {}
    for theme in themes:
        trow = today_all.get(theme)
        prev_state = prev_cycles.get(theme)
        if today_rows is None:
            today_codes: list[str] | None = None
        else:
            today_codes = [str(c) for c in (trow or {}).get("boardCodes") or []]
        board_streaks = {c: streaks.get(c) for c in (today_codes or [])}
        leader = None
        if trow and trow.get("code"):
            leader = {"code": str(trow["code"]), "name": trow.get("name"),
                      "streak": trow.get("streak")}
        prev_sealed: set[str] | None
        if not prev_found:
            prev_sealed = None
        else:
            prev_sealed = prev_sealed_by_board.get(theme, set())
        cls = classify_board_cycle(
            prev_state=prev_state, today_codes=today_codes, leader=leader,
            cycle_leader_state=cycle_leader_states.get(theme),
            streaks=board_streaks, prev_sealed=prev_sealed,
            hotlist_codes=hotlist_codes, in_rewrap_pool=rewrap_codes)
        notes = list(cls["notes"])
        if not prev_found and prev_date:
            notes.append("昨日周期文档缺失，周期链断（无周期起步）")
        if trow is None:
            notes.append("今日该题材封板未达门槛/无封板（行由链延续保留）")
        if cls["stage"] in ("weakening", "terminator"):
            elite_codes = [str(c) for c in
                           ((cls.get("cycleState") or {}).get("brokenElite") or [])]
            if elite_codes:
                pending = [c for c in elite_codes if c not in panic_bars]
                if pending:
                    panic_bars.update(_panic_bars_pct(db, date, pending))
                note = panic_note(elite_codes, panic_bars)
                if note:
                    notes.append(note)
        rows.append({
            "theme": theme,
            "themeId": (trow or {}).get("themeId"),
            "role": (trow or {}).get("role"),
            "jiuyanBoard": (trow or {}).get("jiuyanBoard"),
            "stage": cls["stage"], "stageCn": STAGE_LABELS_CN[cls["stage"]],
            "cycleN": cls["cycleN"], "prevStage": cls["prevStage"],
            "leader": cls["leader"], "leaderState": cls["leaderState"],
            "boardN": len(today_codes) if today_codes is not None else None,
            "events": cls["events"],
            "rewrapElite": cls["rewrapElite"], "rewrapPlain": cls["rewrapPlain"],
            "newBenchmark": cls["newBenchmark"],
            "basis": cls["basis"], "notes": notes,
            "todaySealed": today_codes or [],
            "cycleState": cls["cycleState"],
        })

    if today_rows is None:
        degraded.append(f"{date} {today_unavailable}（整日不可判，状态透传）")
        for r in rows:
            r["notes"].append(f"今日不可考根因：{today_unavailable}")
    if not themes:
        degraded.append("今日与昨日窗口内无任何题材记录")
    if today_rows is not None:
        _fill_names(rows, _stock_names_of(db, date))
        unmapped = list(meta_today.get("unmappedCodes") or [])
        excluded = list(meta_today.get("excludedCodes") or [])
        if unmapped:
            degraded.append(f"未映射股 {len(unmapped)} 只（不进题材行）：{'、'.join(unmapped[:10])}"
                            + ("…" if len(unmapped) > 10 else ""))
        if excluded:
            degraded.append(f"仅属 style/exclude 题材股 {len(excluded)} 只（不进题材行）："
                            f"{'、'.join(excluded[:10])}" + ("…" if len(excluded) > 10 else ""))

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
    gov_missing = _gov_missing_n(db)
    batch_at = max((str(d.get("updatedAt") or "")
                    for d in db["theme_stock_mappings"].find({}, {"updatedAt": 1})),
                   default="")
    doc = {"_id": f"{date}:THEME_CYCLE", "kind": _KIND, "tradingDate": date,
           "version": THEME_CYCLE_VERSION, "status": status,
           "computedAt": datetime.now(timezone.utc),
           "marketState": market_state,
           "rows": rows, "degraded": degraded,
           "meta": {"thsFound": today_rows is not None,
                    "prevDate": prev_date, "prevFound": prev_found,
                    "hotlistFound": hotlist_codes is not None,
                    "rewrapPoolN": rewrap_pool_n,
                    "mappingBatchAt": batch_at,
                    "govMissingThemes": gov_missing,
                    "themeMinBoardN": THEME_MIN_BOARD_N,
                    "streakSource": "jiuyan_streak_map"}}
    db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    dist: dict[str, int] = {}
    for r in rows:
        dist[r["stage"]] = dist.get(r["stage"], 0) + 1
    return {"date": date, "status": status, "themes": len(rows),
            "stages": {STAGE_LABELS_CN[k]: v for k, v in sorted(dist.items())},
            "degraded": degraded}


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
    ap = argparse.ArgumentParser(description="题材周期 v2（题材对象·龙头锚状态机，零 token）")
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
