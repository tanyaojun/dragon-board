# -*- coding: utf-8 -*-
"""题材周期状态机操作层（P2 立项 v2，2026-11-02 九裁决）。

取料（Q7:A 双轨）：
- 主算：day_leader_rows(space_mode) 重算（rank_board_stocks_seal v12 复合键，
  与【题材龙头】打标链同源，零 token）；
- 对账：增量日读台账 hotlist_jev_theme_leader_labels 行内结构事实
  （唯一键 (tradingDate, board, segment)，v12 §2.2），code/streak/
  leaderSealedToday 与重算不一致 → cycleReconcileGaps 披露（不静默不覆盖）。

落库：hotlist_jev_theme_cycle，每板块×轨每日一文档（_id={date}:{board}:{segment}），
幂等 upsert。升序重放（状态跨日携带）：单日步进读前一日各板块态。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.data.repositories.repository_factory import get_runtime_mongodb_database  # noqa: E402
from backend.analysis.hotlist.theme_cycle import STATE_LABELS_CN, step_day
from backend.operations.jev_label_jiuyan import trading_dates_before
from backend.operations.leader_wzs import (bars_covering,
                                           covering_day_change_fetcher,
                                           covering_gain_fetcher)
from backend.operations.theme_leader_baseline import day_leader_rows

COLLECTION = "hotlist_jev_theme_cycle"

# Q2=A：龙一 10 日涨幅创近 20 日新高 → gain10(T) > max(gain10(T-19..T-1))，
# 需 30 根日线（T 及其前 29 根）
_GAIN10_HIGH_OFFSET = 40


def _nodes_by_board(db: Any, date: str) -> dict[str, str | None]:
    doc = db["hotlist_jev_sector_nodes"].find_one(
        {"_id": f"{date}:SECTOR_NODES"}, {"rows.board": 1, "rows.node": 1})
    return {str(r.get("board")): r.get("node")
            for r in (doc or {}).get("rows") or [] if r.get("board")}


def _wzs_day(db: Any, date: str) -> dict[str, Any] | None:
    return db["hotlist_jev_leader_wzs"].find_one({"_id": date})


def _pool_boards(wzs_doc: dict[str, Any] | None) -> set[tuple[str, str]]:
    """Q4:A：P1 观察池在位板块×轨（池行 windowK∈{0,1,2} 即全部池行）。"""
    out: set[tuple[str, str]] = set()
    for r in (wzs_doc or {}).get("poolRows") or []:
        out.add((str(r.get("board")), str(r.get("segment") or "main")))
    return out


# 全量回填单档大 offset：一次拉取进程内缓存跨日复用（阶梯式逐档重试每档一次连接）
_BAR_OFFSET = 250


def _gain10_new_high_codes(db: Any, date: str,
                           leader_rows: list[dict]) -> set[str]:
    """Q2=A：龙一 10 日涨幅创近 20 日新高的 code 集合（缺日线如实不算）。"""
    out: set[str] = set()
    for r in leader_rows:
        code = str(r.get("code") or "")
        if not code:
            continue
        bars = bars_covering(code, date, min_dates=30, offsets=(_BAR_OFFSET,))
        if not bars:
            continue
        ds = [d for d in sorted(bars) if d <= date]
        if len(ds) < 21 or ds[-1] != date:
            continue
        closes = [bars[d].get("close") for d in ds]
        if any(not c for c in closes):
            continue
        gains = [closes[i] / closes[i - 10] - 1
                 for i in range(10, len(closes))]
        if len(gains) < 2:
            continue
        if gains[-1] > max(gains[:-1][-19:]):
            out.add(code)
    return out


def _reconcile_with_labels(db: Any, date: str,
                           leader_rows: list[dict]) -> list[str]:
    """Q7:A 双轨对账：重算龙一行 vs 台账行结构事实（漂移披露不覆盖）。"""
    gaps: list[str] = []
    docs = list(db["hotlist_jev_theme_leader_labels"].find(
        {"tradingDate": date, "status": "ok", "leaderSuperseded": {"$ne": True}},
        {"board": 1, "code": 1, "name": 1, "segmentRows": 1, "structure": 1}))
    label_by_key: dict[tuple[str, str], dict] = {}
    for d in docs:
        seg = None
        for sr in d.get("segmentRows") or []:
            if sr.get("code") == d.get("code"):
                seg = sr.get("segment")
                break
        seg = seg or "legacy"
        label_by_key[(str(d.get("board")), str(seg))] = d
    for r in leader_rows:
        key = (str(r.get("board")), str(r.get("segment") or "main"))
        lab = label_by_key.get(key)
        if lab is None:
            continue   # 台账未覆盖该板块/轨（回填样本/门拦截），非漂移
        if str(lab.get("code")) != str(r.get("code")):
            gaps.append(f"{date} {key[0]}({key[1]}): 重算龙一 {r.get('code')} "
                        f"vs 台账 {lab.get('code')}（漂移披露，不覆盖）")
    return gaps


def collect_day_inputs(db: Any, date: str, dataset_id: str,
                       *, reconcile: bool = True) -> dict[str, Any] | None:
    """单日原料（升序重放的一个元素）；龙一行不可算（THS 缺失）→ leaders 空列。"""
    nodes = _nodes_by_board(db, date)
    wzs_doc = _wzs_day(db, date)
    events = [{"board": e["board"], "segment": e.get("segment") or "main",
               "type": e["type"]}
              for e in (wzs_doc or {}).get("events") or []]
    # 深历史回填必传覆盖式 fetcher（默认实现只拉最近 15 根日线，老日期 gain10
    # 全不可算 → 整板块跳过，实证 10-27 前全空）；pool_dates 同 P1 判定链
    # leaders_for 同参（近 3 个封板日）：断板龙一进候选池才能产出
    # leaderSealedToday=False 行（观察窗开启的前提，缺则窗永不开启）
    prev_dates = trading_dates_before(db, date, 3, dataset_id)
    rows, _meta = day_leader_rows(
        db, date, dataset_id, space_mode=True,
        prev_date=prev_dates[-1] if prev_dates else None,
        pool_dates=prev_dates,
        gain_fetcher=lambda codes, end: covering_gain_fetcher(
            codes, end, offsets=(_BAR_OFFSET,)),
        day_change_fetcher=covering_day_change_fetcher)
    if rows is None:
        rows = []
    high_codes = _gain10_new_high_codes(db, date, rows)
    leaders = [{"board": r["board"], "segment": r.get("segment") or "main",
                "code": r["code"], "name": r.get("name"),
                "leaderSealedToday": r.get("leaderSealedToday"),
                "streak": r.get("streak"),
                "gain10NewHigh": r["code"] in high_codes}
               for r in rows]
    return {"date": date, "nodes": nodes, "events": events,
            "leaders": leaders, "pool_boards": _pool_boards(wzs_doc),
            "reconcile_gaps": _reconcile_with_labels(db, date, rows)
            if reconcile else []}


def build_and_save_theme_cycle(db: Any, dates: list[str],
                               dataset_id: str = "dragonboard_live",
                               *, force: bool = False) -> dict[str, Any]:
    """升序重放 dates 并落库（幂等 upsert，每板块×轨每日一文档）。

    重放起点状态取库中 dates[0] 前一交易日已落库态（断点续跑）；无 → None
    （首见定态，Q1=B）。返回汇总。"""
    # 续跑：读首日前一日的库态作为重放起点
    pre_states: dict[tuple[str, str], dict] = {}
    if dates:
        prev_dates = trading_dates_before(db, dates[0], 1, dataset_id)
        if prev_dates:
            for d in db[COLLECTION].find({"tradingDate": prev_dates[0]},
                                         {"board": 1, "segment": 1, "state": 1}):
                pre_states[(str(d["board"]), str(d.get("segment") or "main"))] = d

    inputs = [collect_day_inputs(db, d, dataset_id) for d in dates]

    summary = {"dates": len(dates), "rows": 0, "migrated": 0, "gaps": []}
    states: dict[tuple[str, str], str] = {k: v["state"]
                                          for k, v in pre_states.items()}
    # 续跑恢复窗态：开窗日随文档落痕（windowOpenedOn），无则视为无窗
    windows: dict[tuple[str, str], Any] = {
        k: v["windowOpenedOn"] for k, v in pre_states.items()
        if v.get("windowOpenedOn")}
    for day, inp in zip(dates, inputs):
        if inp is None:
            summary["gaps"].append(f"{day}: 原料不可得（异常）")
            continue
        # 窗满判定基准：{today, T-1, T-2}（开窗日不在此集=差 ≥3 交易日）
        recent_days = {day, *trading_dates_before(db, day, 2, dataset_id)}
        pool = inp["pool_boards"]
        ev_by_key: dict[tuple[str, str], list[str]] = {}
        for e in inp["events"]:
            ev_by_key.setdefault((e["board"], e["segment"]), []).append(e["type"])
        ld_by_key = {(r["board"], r["segment"]): r for r in inp["leaders"]}
        universe = (set(inp["nodes"])
                    | {b for (b, _s) in ld_by_key}
                    | {b for (b, _s) in ev_by_key})
        for board in sorted(universe):
            for segment in sorted({s for (b, s) in ev_by_key if b == board}
                                  | {s for (b, s) in ld_by_key if b == board}
                                  or {"main"}):
                key = (board, segment)
                ld = ld_by_key.get(key)
                in_pool = key in pool
                opened_on = windows.get(key)
                # Q4:A：窗满=断板开窗后交易日差 ≥3（k≥3 出池当日记窗满）；
                # 不以池在位判窗满（池含任意断板股，热门板块池永非空）
                window_full = (opened_on is not None
                               and opened_on not in recent_days)
                window_open = opened_on is not None
                new_state, transition = step_day(
                    states.get(key), node=inp["nodes"].get(board),
                    event_types=ev_by_key.get(key) or [],
                    leader_broken=bool(ld) and ld.get("leaderSealedToday") is False,
                    leader_advanced=bool(ld) and ld.get("leaderSealedToday") is True
                    and isinstance(ld.get("streak"), int) and ld["streak"] >= 2,
                    gain10_new_high=bool(ld and ld.get("gain10NewHigh")),
                    window_open=window_open, window_full=window_full)
                if (bool(ld) and ld.get("leaderSealedToday") is False)                         and new_state == "weakening":
                    windows[key] = day    # 断板开窗（含已在转弱态的再断板）
                if new_state in ("wzs", "mainrise"):
                    windows.pop(key, None)
                states[key] = new_state
                doc = {"_id": f"{day}:{board}:{segment}",
                       "tradingDate": day, "board": board, "segment": segment,
                       "state": new_state,
                       "stateCn": STATE_LABELS_CN.get(new_state, new_state),
                       "prev": transition["from"] if transition else new_state,
                       "migrated": transition is not None,
                       "transition": transition,
                       "evidence": {"node": inp["nodes"].get(board),
                                    "events": ev_by_key.get(key) or [],
                                    "leaderSealedToday": (ld or {}).get("leaderSealedToday"),
                                    "streak": (ld or {}).get("streak"),
                                    "gain10NewHigh": bool(ld and ld.get("gain10NewHigh")) or None,
                                    "inPool": in_pool or None,
                                    "windowFull": window_full or None},
                       "windowOpenedOn": windows.get(key),
                       "cycleReconcileGaps": inp["reconcile_gaps"] or None,
                       "generatedAt": datetime.now(timezone.utc).isoformat()}
                db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
                summary["rows"] += 1
                if transition:
                    summary["migrated"] += 1
        if inp["reconcile_gaps"]:
            summary["gaps"].extend(inp["reconcile_gaps"])
        print(f"[theme-cycle] {day} rows={summary['rows']} migrated={summary['migrated']} "
              f"done={summary['dates'] and dates.index(day) + 1}/{len(dates)}", flush=True)
    return summary


if __name__ == "__main__":   # pragma: no cover — CLI（schedule themeCycle advisory 步）
    import argparse
    import json as _json
    import sys as _sys

    _ap = argparse.ArgumentParser(description="题材周期状态机单日步进（升序链，读前一日库态）")
    _ap.add_argument("--day", help="YYYY-MM-DD（缺省=最近韭研 final 日）")
    _args = _ap.parse_args()
    _db = get_runtime_mongodb_database()
    _day = _args.day
    if not _day:
        _docs = _db["jiuyan_action"].find({"_id": {"$regex": ":final$"}},
                                          {"tradingDate": 1})
        _days = sorted(str(d["tradingDate"]) for d in _docs if d.get("tradingDate"))
        _day = _days[-1] if _days else None
    if not _day:
        print(_json.dumps({"ok": False, "error": "无韭研 final，且未给 --day"}))
        _sys.exit(1)
    _summary = build_and_save_theme_cycle(_db, [_day])
    print(_json.dumps({"ok": True, "date": _day, "rows": _summary["rows"],
                       "migrated": _summary["migrated"],
                       "gaps": len(_summary["gaps"])}, ensure_ascii=False))
