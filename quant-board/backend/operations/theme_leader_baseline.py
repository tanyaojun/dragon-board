# -*- coding: utf-8 -*-
"""板块龙头结构事实取数（2026-10-20，零模型调用）。

从 `scripts/theme_leader_sustain_baseline.py` 上移：**龙头识别与结构事实只有一份实现**，
基线脚本与题材层投喂 runner（`operations/theme_leader_label.py`）共用，禁止第二套。

口径（复用生产单一事实源）：
- 封板 = `jiuyan_board_info` 触板 − THS 炸板池二分，剔 ST/北交所（与涨停复盘同口径）；
- 连板高度 = `jiuyan_streak_map` 真连板（不可算=None）；
- 龙一 = 板块内真连板最高 → 封板时间最早（`theme_leader_ammo.rank_board_stocks`）；
- 结局（仅基线需要）= 次一交易日该股是否仍在封板集合内。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.analysis.hotlist.theme_leader_ammo import rank_board_stocks


def sealed_and_info(db: Any, date: str,
                    dataset_id: str = DEFAULT_DATASET_ID) -> tuple[set[str] | None, dict, dict]:
    """当日封板集合 + 个股 info + meta；THS 池缺失 → (None, {}, meta)（不可二分）。"""
    from backend.operations.jev_label_jiuyan import jiuyan_board_info

    info, meta = jiuyan_board_info(db, date)
    if not meta.get("thsPoolFound"):
        return None, info, meta
    sealed = {c for c, i in info.items() if not i.get("zhaban") and not i.get("excluded")}
    return sealed, info, meta


def day_leader_rows(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                    prev_date: str | None = None) -> tuple[list[dict] | None, dict]:
    """当日各板块龙头的结构事实行（**不含次日结局**）。

    `prev_date` 给出时补 `prevPeers`/`prevBoardN`（昨日同板块其它封板股家数）——承接强度特征。
    返回 `(rows, meta)`；`rows=None` 表示当日 THS 池缺失（不可二分，fail-visible，调用方自己决定跳过口径）。
    """
    from backend.operations.jev_label_jiuyan import jiuyan_streak_map

    sealed, _info, meta = sealed_and_info(db, date, dataset_id)
    if sealed is None:
        return None, meta
    streaks = jiuyan_streak_map(db, date, dataset_id)
    prev_sealed: set[str] | None = None
    if prev_date:
        prev_sealed, _pi, _pm = sealed_and_info(db, prev_date, dataset_id)
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
    boards_of: dict[str, list[dict]] = defaultdict(list)
    for field in doc.get("fields") or []:
        for st in field.get("stocks") or []:
            code = str(st.get("code") or "")[-6:]
            if code in sealed:            # 只算真实封板股（炸板/触板未封不进梯队）
                boards_of[str(field.get("name") or "")].append(
                    {"code": code, "name": st.get("name"), "time": st.get("time"),
                     "streak": streaks.get(code)})
    rows: list[dict] = []
    for board, stocks in boards_of.items():
        if not stocks:
            continue
        ranked = rank_board_stocks(stocks)
        leader = ranked[0]
        others = [s for s in stocks if s["code"] != leader["code"]]
        prev_peers = (sum(1 for s in others if s["code"] in prev_sealed)
                      if prev_sealed is not None else None)
        rows.append({
            "date": date, "board": board,
            "code": leader["code"], "name": leader.get("name"),
            "streak": leader["streak"], "time": leader["time"],
            "boardN": len(stocks), "othersN": len(others),
            # 板内跟风：>=(leader streak-1)
            "ladderFollowers": sum(
                1 for s in others
                if (s["streak"] or 0) >= max(1, (leader["streak"] or 1) - 1)),
            "prevPeers": prev_peers,
            "prevBoardN": (sum(1 for s in stocks if s["code"] in prev_sealed)
                           if prev_sealed is not None else None),
            "peerCodes": [s["code"] for s in others],
        })
    return rows, meta


def build_rows(db: Any, start: str, end: str,
               dataset_id: str = DEFAULT_DATASET_ID) -> dict:
    """窗口内逐交易日构建龙头-日样本（含次日结局 `continued`）。

    与基线脚本口径逐项一致（`today_ths_missing` / `next_ths_missing` /
    `prev_ths_missing_only_for_feature` 三个跳过计数器原样保留）。
    """
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$gte": start, "$lte": end},
         "_id": {"$regex": ":final$"}}, {"tradingDate": 1}) if d.get("tradingDate")})
    rows: list[dict] = []
    skipped: Counter = Counter()
    for i, date in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        prev_date = dates[i - 1] if i > 0 else None
        day_rows, _meta = day_leader_rows(db, date, dataset_id, prev_date)
        if day_rows is None:
            skipped["today_ths_missing"] += 1
            continue
        if prev_date is not None:
            # 计数口径与首版基线一致：按「日期」而非「股票」计（prevPeers=None 的样本仍出，只是缺该特征）
            prev_sealed, _pi, _pm = sealed_and_info(db, prev_date, dataset_id)
            if prev_sealed is None:
                skipped["prev_ths_missing_only_for_feature"] += 1
        sealed2, _info2, _meta2 = sealed_and_info(db, nxt, dataset_id)
        if sealed2 is None:
            skipped["next_ths_missing"] += 1
            continue
        doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
        board_codes = [(str(f.get("name") or ""),
                        [str(st.get("code") or "")[-6:] for st in f.get("stocks") or []])
                       for f in doc.get("fields") or []]
        for row in day_rows:
            codes_here = next((c for b, c in board_codes if b == row["board"]), [])
            row["continued"] = row["code"] in sealed2
            row["boardContinued"] = sum(1 for c in codes_here if c in sealed2)
            row["next"] = nxt
            rows.append(row)
    return {"start": start, "end": end, "dates": dates, "rows": rows,
            "skipped": dict(skipped)}


def trading_dates(db: Any, start: str, end: str) -> list[str]:
    """窗口内韭研 final 文档交易日轴（升序）。"""
    return sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$gte": start, "$lte": end},
         "_id": {"$regex": ":final$"}}, {"tradingDate": 1}) if d.get("tradingDate")})