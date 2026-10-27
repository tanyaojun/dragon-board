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
from backend.analysis.hotlist.theme_leader_ammo import (rank_board_stocks,
                                                        rank_board_stocks_space)
from backend.operations.tdx_daily_bars import fetch_gains10 as _fetch_gains10


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
                    prev_date: str | None = None, *,
                    space_mode: bool = False, pool_dates: list[str] | None = None,
                    gain_fetcher=None) -> tuple[list[dict] | None, dict]:
    """当日各板块龙头的结构事实行（**不含次日结局**）。

    `prev_date` 给出时补 `prevPeers`/`prevBoardN`（昨日同板块其它封板股家数）——承接强度特征；
    2026-10-24c 起另补 `prevTotal`（昨日封板总数，断板分母）/`prevZhabanN`（昨日板内触板未封）。
    2026-10-24c 起每行自带板面扩容字段：`ladderShape`（首板/2板/3板+分布）、`secondStreak`
    （次高连板）、`zhabanN`（今日板内触板未封家数，韭研曾触板−THS炸板二分同口径）。
    2026-10-24d 起另补 `prevStill`（昨日同名板块封板股中今日仍封数，**同名成员口径**）——
    断板 = prevTotal − prevStill 用它算；prevBoardN 是今日成员交集（含昨日他板块迁入股），
    迁移场景下 prevTotal−prevBoardN 会出负数（2026-10-24 review 处置）。

    **space_mode（2026-10-27 用户裁决：龙一=10日涨幅最高，非真连板）**：候选池=当日封板池
    ∪ `pool_dates`（近 3 个交易日）封板池（同板块，覆盖断板反包——空间龙一断板日仍须在列），
    排序=10日涨幅→真连板高度→首封最早；行另带 `gain10`（龙一 10 日涨幅）与
    `leaderSealedToday`（False=断板反包候选，streak/time 如实 None，ladderFollowers 不可算）。
    **仅当日标注链启用**（leaders_for）；基线/历史窗口（build_rows/board_count_history/
    sector_nodes 等）维持 streak 口径——历史样本人群定义不随规则换代漂移，断板反包龙一
    无同构历史锚属如实缺位（预登记 §21.6）。TDX 拉不到涨幅（全候选 None）→ 该板块跳过
    + `meta["spaceErrors"]` 披露（用户裁决 fail-visible，不降级旧规则）。
    返回 `(rows, meta)`；`rows=None` 表示当日 THS 池缺失（不可二分，fail-visible，调用方自己决定跳过口径）。
    """
    from backend.operations.jev_label_jiuyan import jiuyan_streak_map

    sealed, info, meta = sealed_and_info(db, date, dataset_id)
    if sealed is None:
        return None, meta
    streaks = jiuyan_streak_map(db, date, dataset_id)
    prev_sealed: set[str] | None = None
    prev_board_codes: dict[str, set[str]] = defaultdict(set)   # 板块名 → 昨日封板 code 集（精确同名匹配）
    prev_board_zhaban: dict[str, int] = defaultdict(int)   # 板块名 → 昨日触板未封家数
    if prev_date:
        prev_sealed, prev_info, _pm = sealed_and_info(db, prev_date, dataset_id)
        if prev_sealed is not None:
            # 昨日盘面统计与今日同口径（同一份 fields 分组 + 触板二分）；板块名逐日可变，
            # 只做精确匹配（同名才可考，改名板块昨日统计如实不可考，与 S1 序列同哲学）
            prev_doc = db["jiuyan_action"].find_one(
                {"_id": f"{prev_date}:final"},
                {"fields.stocks.code": 1, "fields.name": 1}) or {}
            for field in prev_doc.get("fields") or []:
                bname = str(field.get("name") or "")
                for st in field.get("stocks") or []:
                    pcode = str(st.get("code") or "")[-6:]
                    if pcode in prev_sealed:
                        prev_board_codes[bname].add(pcode)
                    elif (prev_info.get(pcode) or {}).get("zhaban"):
                        prev_board_zhaban[bname] += 1
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
    boards_of: dict[str, list[dict]] = defaultdict(list)
    zhaban_of: dict[str, int] = defaultdict(int)   # 板块名 → 今日触板未封家数（韭研曾触板−THS炸板二分）
    for field in doc.get("fields") or []:
        bname = str(field.get("name") or "")
        for st in field.get("stocks") or []:
            code = str(st.get("code") or "")[-6:]
            if code in sealed:            # 只算真实封板股（炸板/触板未封不进梯队）
                boards_of[bname].append(
                    {"code": code, "name": st.get("name"), "time": st.get("time"),
                     "streak": streaks.get(code)})
            elif (info.get(code) or {}).get("zhaban"):
                zhaban_of[bname] += 1

    # space_mode 候选池：近 `pool_dates` 各日封板池并入同板块候选（断板反包入口）；
    # 昨日池候选 streak/time 如实 None（未封板），今日池候选以今日口径为准（去重今日优先）。
    pool_prev: dict[str, list[dict]] = defaultdict(list)
    if space_mode:
        for pd in (pool_dates or []):
            if not pd or pd == date:
                continue
            p_sealed, _pinfo, _pmeta = sealed_and_info(db, pd, dataset_id)
            if not p_sealed:
                continue
            pdoc = db["jiuyan_action"].find_one({"_id": f"{pd}:final"}, {"fields": 1}) or {}
            for field in pdoc.get("fields") or []:
                bname = str(field.get("name") or "")
                have = {c["code"] for c in pool_prev[bname]}
                for st in field.get("stocks") or []:
                    pcode = str(st.get("code") or "")[-6:]
                    if pcode in p_sealed and pcode not in have:
                        pool_prev[bname].append({"code": pcode, "name": st.get("name"),
                                                 "time": None, "streak": None})
                        have.add(pcode)

    rows: list[dict] = []
    space_errors: dict[str, str] = {}
    for board, stocks in boards_of.items():
        if not stocks:
            continue
        if space_mode:
            today_codes = {s["code"] for s in stocks}
            cands = list(stocks) + [c for c in pool_prev.get(board, [])
                                    if c["code"] not in today_codes]
            gains = (gain_fetcher or _fetch_gains10)([c["code"] for c in cands], date)
            for c in cands:
                c["gain10"] = gains.get(c["code"])
            if not any(isinstance(c.get("gain10"), (int, float)) for c in cands):
                space_errors[board] = "10日涨幅不可算（TDX 日线不可用），板块跳过（fail-visible 裁决）"
                continue
            leader = rank_board_stocks_space(cands)[0]
            sealed_today = leader["code"] in sealed
        else:
            leader = rank_board_stocks(stocks)[0]
            sealed_today = True
        leader_streak = leader["streak"] if sealed_today else None
        leader_time = leader["time"] if sealed_today else None
        others = [s for s in stocks if s["code"] != leader["code"]]
        prev_peers = (sum(1 for s in others if s["code"] in prev_sealed)
                      if prev_sealed is not None else None)
        # 板内梯队形态（2026-10-24c）：首板/2板/3板+ 分布 + 次高连板——深度题 climax 判据
        # 「首板潮/中军成形/高标分化」「龙头高度显著领先」此前只有总数与跟风数两点
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
        second_streak = max((s["streak"] for s in others
                             if isinstance(s["streak"], int)), default=None)
        prev_total = (len(prev_board_codes.get(board, set()))
                      if prev_sealed is not None else None)
        # 断板口径（2026-10-24d）：同名板块成员——昨日同名封板股中今日仍封数。
        # 不用 prevBoardN（今日成员交集，含昨日他板块迁入股）：迁移场景减出负数。
        prev_still = (len(prev_board_codes.get(board, set()) & sealed)
                      if prev_sealed is not None else None)
        rows.append({
            "date": date, "board": board,
            "code": leader["code"], "name": leader.get("name"),
            "streak": leader_streak, "time": leader_time,
            "boardN": len(stocks), "othersN": len(others),
            # 板内跟风：>=(leader streak-1)；龙一未封板（断板反包候选）→ 梯队跟风不可算
            "ladderFollowers": (None if not sealed_today else sum(
                1 for s in others
                if (s["streak"] or 0) >= max(1, (leader_streak or 1) - 1))),
            "prevPeers": prev_peers,
            "prevBoardN": (sum(1 for s in stocks if s["code"] in prev_sealed)
                           if prev_sealed is not None else None),
            # 2026-10-24c 板面扩容：昨日封板总数/断板、今日与昨日板内触板未封、
            # 梯队形态与次高连板（prevBoardN 语义仍是「昨日封板且今日仍封」按今日成员，
            # 叙事行不再把它误写为「昨日封板总数」）；2026-10-24d 增 prevStill（同名成员仍封，
            # 断板=prevTotal−prevStill 恒 ≥0）
            "prevTotal": prev_total,
            "prevStill": prev_still,
            "zhabanN": zhaban_of.get(board, 0),
            "prevZhabanN": (prev_board_zhaban.get(board)
                            if prev_sealed is not None else None),
            "ladderShape": shape,
            "secondStreak": second_streak,
            "peerCodes": [s["code"] for s in others],
            # 板内封板名单（v3 板内解析用：让 L2 计数与 boardN 同口径，不把触板未封混进来）
            "boardCodes": [s["code"] for s in stocks],
            # 2026-10-27 空间龙一规则：10 日涨幅（排序依据）+ 未封板标记（断板反包候选）
            "gain10": (leader.get("gain10") if space_mode else None),
            "leaderSealedToday": sealed_today,
        })
    if space_mode:
        meta["leaderMode"] = "space"
        if space_errors:
            meta["spaceErrors"] = space_errors
    return rows, meta


def board_count_history(db: Any, date: str, days: int = 5,
                        dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, list[tuple[str, int]]]:
    """近 `days` 个交易日各板块封板家数序列（S1，2026-10-24b 置信度归因后加）。

    深度/延续题判据要「板块家数扩张中/萎缩」，此前语料只有今日/昨日两点。
    复用 `day_leader_rows`（boardN 与结构行同一实现，不造第二套口径）；THS 池缺失的
    日子整日跳过（如实留缺口，不插值）；板块名逐日未收录 = 该日无该板块（韭研分组
    名逐日可变，只做精确匹配，不做近似拼接——fail-visible）。
    """
    prev_dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$lt": date},
         "_id": {"$regex": ":final$"}}, {"tradingDate": 1}) if d.get("tradingDate")})[-days:]
    out: dict[str, list[tuple[str, int]]] = {}
    for d in prev_dates:
        day_rows, _meta = day_leader_rows(db, d, dataset_id)
        if day_rows is None:
            continue                     # 当日 THS 池缺失：整日缺口
        for r in day_rows:
            out.setdefault(str(r["board"]), []).append((d, int(r["boardN"])))
    return out


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


# ── 同桶隔日连板基线（relay v7 D5 消费；零模型结构事实）─────────────────────
# 实测窗口 2026-08-01~10-19（50 个可二分交易日，341 个板块龙头-日样本；THS 池缺失日
# 如实跳过 14/9 天）——预注册 theme-leader-nextday-preregistration-20261020 §3 表。
# 改表必须重跑 `scripts/theme_leader_sustain_baseline.py` 对账并更新窗口注。
SUSTAIN_WINDOW = "2026-08-01~10-19"
SUSTAIN_OVERALL = (34.3, 341)
SUSTAIN_BY_STREAK = {1: (19.2, 156), 2: (44.4, 90), 3: (46.2, 39), 4: (51.8, 56)}   # 4=4板+
SUSTAIN_BY_BOARD_N = {"1-2": (22.8, 101), "3-4": (29.6, 98), "5-7": (43.0, 79), "8+": (49.2, 63)}
SUSTAIN_BY_SEAL = {"early": (42.4, 210), "mid": (17.9, 67), "late": (29.1, 55)}
# 组合桶（n≥5 才入表；更小样本组合回退单维桶，不外推）
SUSTAIN_COMBOS = {
    ("4+", "8+", "early"): (83.3, 12),
    ("3", "5-7", "early"): (71.4, 7),
    ("4+", "1-2", "early"): (62.5, 8),
    ("2", "5-7", "early"): (55.6, 18),
    ("2", "8+", "early"): (31.3, 16),
}
_SEAL_CN = {"early": "早(≤10:00)", "mid": "中(10:00-13:00)", "late": "晚(>13:00)"}


def seal_time_bucket(seal_time: Any) -> str | None:
    """封板时间 → 早/中/晚桶（≤10:00 / 10:00-13:00 / >13:00）；不可解析 → None。"""
    parts = str(seal_time or "").split(":")
    try:
        minutes = int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return None
    if minutes <= 600:
        return "early"
    if minutes <= 780:
        return "mid"
    return "late"


def _board_n_bucket(n: Any) -> str | None:
    if not isinstance(n, int):
        return None
    if n >= 8:
        return "8+"
    if n >= 5:
        return "5-7"
    if n >= 3:
        return "3-4"
    return "1-2"


def sustain_baseline_for(streak: Any, board_n: Any, seal_time: Any) -> dict:
    """(真连板高度, 板块家数, 封板时间) → 同桶/单维/总体隔日连板率（查表，零调用）。

    streak 非数（真连板不可算）→ bucketTxt=None，只给总体（不猜桶，§4.0）。
    """
    out: dict[str, Any] = {"window": SUSTAIN_WINDOW, "overall": SUSTAIN_OVERALL,
                           "bucketTxt": None, "combo": None,
                           "byStreak": None, "byBoardN": None, "bySeal": None}
    if not isinstance(streak, int):
        return out
    s_key = min(streak, 4)
    s_txt = "4+" if streak >= 4 else str(streak)
    out["byStreak"] = SUSTAIN_BY_STREAK[s_key]
    b_key = _board_n_bucket(board_n)
    if b_key:
        out["byBoardN"] = SUSTAIN_BY_BOARD_N[b_key]
    seal = seal_time_bucket(seal_time)
    if seal:
        out["bySeal"] = SUSTAIN_BY_SEAL[seal]
    if b_key and seal:
        out["combo"] = SUSTAIN_COMBOS.get((s_txt, b_key, seal))
    out["bucketTxt"] = (f"{s_txt}板｜板块{board_n}家（{b_key}）｜{_SEAL_CN[seal]}封"
                        if b_key and seal else None)
    return out