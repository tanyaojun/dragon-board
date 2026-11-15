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
                                                        segment_of,
                                                        space_leaders_by_segment)
from backend.operations.tdx_daily_bars import fetch_gains10 as _fetch_gains10


def _default_day_change_fetcher(codes: list[str], date: str) -> dict[str, float | None]:
    """当日涨跌幅%（close vs 前一交易日 close）：断板候选跌停剔除用（v12「未跌停」条件）。

    拉不到日线/当日不在轴/前收缺失 → None（调用方不剔除，不猜，fail-visible）。
    2026-11-16：改委托 tdx_daily_bars.covering_day_change_fetcher（覆盖式单源）——
    原实现固定 15 根日线，深历史回填日不在轴 → 恒 None（跌停剔除失效），与 gain10
    是同一坑（11-12 回填清空板块节点档事故的伴生缺陷）。
    """
    from backend.operations.tdx_daily_bars import covering_day_change_fetcher
    try:
        return covering_day_change_fetcher(codes, date)
    except Exception:  # noqa: BLE001 — TDX 异常不阻断（不猜，缺者保留）
        return {c: None for c in codes}


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
                    gain_fetcher=None, day_change_fetcher=None) -> tuple[list[dict] | None, dict]:
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
    排序=当日首封最早→真连板高度→10日涨幅（v12，2026-10-28 用户再裁决）；行另带
    `gain10`（龙一 10 日涨幅，次级排序键/身位披露）与
    `leaderSealedToday`（False=断板反包候选，streak/time 如实 None，ladderFollowers 不可算）、
    `days`/`boards`（区间高度 N天M板：封板龙一=当日韭研 num，断板龙一=最近封板日 num；
    2026-11-12 用户修复节点龙头列未封板高度展示）。
    **仅当日标注链启用**（leaders_for）；基线/历史窗口（build_rows/board_count_history/
    sector_nodes 等）维持 streak 口径——历史样本人群定义不随规则换代漂移，断板反包龙一
    无同构历史锚属如实缺位（预登记 §21.6）。TDX 拉不到涨幅（全候选 None）→ 该板块跳过
    + `meta["spaceErrors"]` 披露（用户裁决 fail-visible，不降级旧规则）。

    **2026-11-13 用户裁决 B 方案（根因修）**：space_mode 候选池每股每日单板块归属
    （首板块约定：当日首个出现板块；当日缺席取最近在池日首板块），eradicates 迁移股
    旧/新板块同时当选龙一（一股两板块龙头、节点判据消费错误龙头、同股同日重复投喂）。
    断板反包本意保留（断板龙一仍留归属板块在列）；classify_board_day 判据表零改动
    （纠正的是其输入）。归属裁决落 `meta["leaderAttribution"]`（version 旗标+multiBoard+
    boardsEmptied 清空板披露），历史档无此键=裁决前口径，不自动重放（重放另裁）。
    **v12 分轨（2026-10-28 用户裁决，预登记 theme-leader-v12 §2.1）**：space_mode 下主板/
    双创各按同一排序键独立取龙一（`space_leaders_by_segment`），每板块 ≤2 行，行带
    `segment`（main/growth）；历史窗口径不加 segment（样本人群不随规则换代）。
    返回 `(rows, meta)`；`rows=None` 表示当日 THS 池缺失（不可二分，fail-visible，调用方自己决定跳过口径）。
    """
    from backend.operations.jev_label_jiuyan import (_jiuyan_days_boards,
                                                       jiuyan_streak_map)

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
    # 2026-11-13 用户裁决 B 方案（根因修）：每股每日单板块归属，首板块约定
    # （_pool_of/_promotion_by_board 同源，不新造口径）：当日在池取当日首个出现
    # 板块；当日缺席取最近在池日首板块（下方往日并集循环新→旧赋值）。 eradicates
    # 「一股两板块龙头」：迁移股不再进旧板块候选池，旧板余下候选另选；断板反包
    # 本意保留（断板龙一仍留归属板块在列）。仅 space_mode 启用，历史 streak 口径
    # 不漂移；多板归属裁决落 meta 披露（fail-visible）。
    attrib: dict[str, str] = {}
    seen_boards: dict[str, list[str]] = {}
    today_sealed_boards: set[str] = set()
    if space_mode:
        for field in doc.get("fields") or []:
            bname = str(field.get("name") or "")
            for st in field.get("stocks") or []:
                code = str(st.get("code") or "")[-6:]
                if code in sealed:
                    today_sealed_boards.add(bname)
                    if bname not in seen_boards.setdefault(code, []):
                        seen_boards[code].append(bname)
                    attrib.setdefault(code, bname)
    boards_of: dict[str, list[dict]] = defaultdict(list)
    zhaban_of: dict[str, int] = defaultdict(int)   # 板块名 → 今日触板未封家数（韭研曾触板−THS炸板二分）
    for field in doc.get("fields") or []:
        bname = str(field.get("name") or "")
        for st in field.get("stocks") or []:
            code = str(st.get("code") or "")[-6:]
            # 只算真实封板股（炸板/触板未封不进梯队）；space_mode 另按单归属过滤（B 方案）
            if code in sealed and (not space_mode or attrib.get(code) == bname):
                _d, _b = _jiuyan_days_boards(st)
                boards_of[bname].append(
                    {"code": code, "name": st.get("name"), "time": st.get("time"),
                     "streak": streaks.get(code),
                     # 区间高度（韭研 num「N天M板」，当日口径）：展示注记用，
                     # 连板语义仍一律 streak（2026-10-16 口径修正不复活）
                     "days": _d, "boards": _b})
            elif (info.get(code) or {}).get("zhaban"):
                zhaban_of[bname] += 1

    # space_mode 候选池：近 `pool_dates` 各日封板池并入同板块候选（断板反包入口）；
    # 昨日池候选 streak/time 如实 None（未封板），今日池候选以今日口径为准（去重今日优先）。
    pool_prev: dict[str, list[dict]] = defaultdict(list)
    if space_mode:
        # P0 修复（code review 2026-10-28）：pool_dates 升序，原顺序遍历 + `not in have`
        # 去重会保留**最旧**池日的 histStreak——多日连板断板股（d-3 首板、d-1 二板、今日断板）
        # height 系统性塌成首板，丢失空间板组资格。改新→旧遍历：先见即最近封板日。
        for pd in reversed(pool_dates or []):
            if not pd or pd == date:
                continue
            p_sealed, _pinfo, _pmeta = sealed_and_info(db, pd, dataset_id)
            if not p_sealed:
                continue
            # v12 定稿：断板候选带最近封板日真连板高度（三种情况均参与空间板判定）
            p_streaks = jiuyan_streak_map(db, pd, dataset_id)
            pdoc = db["jiuyan_action"].find_one({"_id": f"{pd}:final"}, {"fields": 1}) or {}
            for field in pdoc.get("fields") or []:
                bname = str(field.get("name") or "")
                have = {c["code"] for c in pool_prev[bname]}
                for st in field.get("stocks") or []:
                    pcode = str(st.get("code") or "")[-6:]
                    if pcode in p_sealed:
                        # B 方案单归属：当日缺席股取最近在池日首板块（新→旧遍历
                        # 先见即最近）；当日封板股保持今日归属（setdefault 不覆盖）
                        if bname not in seen_boards.setdefault(pcode, []):
                            seen_boards[pcode].append(bname)
                        attrib.setdefault(pcode, bname)
                    if (pcode in p_sealed and pcode not in have
                            and attrib.get(pcode) == bname):
                        _pd, _pb = _jiuyan_days_boards(st)
                        pool_prev[bname].append({"code": pcode, "name": st.get("name"),
                                                 "time": None, "streak": None,
                                                 # 区间高度截至最近封板日 pd（num 当日口径）：
                                                 # 断板龙一「N天M板」展示单源（2026-11-12 用户修复）
                                                 "days": _pd, "boards": _pb,
                                                 "histStreak": p_streaks.get(pcode),
                                                 # v5 预登记 P1（题材周期·龙头弱转强）：最近封板日透出，
                                                 # 消费侧据此算窗位 k=T−S−1（严格 3 日回溯口径）
                                                 "poolDay": pd})
                        have.add(pcode)
        # B 方案归属披露（fail-visible）：多板股候选板块与单归属裁决留痕；
        # 版本旗标区分口径代际（历史档无此键=裁决前口径，不自动重放）
        meta["leaderAttribution"] = {
            "version": "single-board-20261113",
            "multiBoard": [{"code": c, "boards": bs, "chosen": attrib.get(c)}
                           for c, bs in seen_boards.items() if len(bs) > 1],
            # m4 审查修复：今日有封板成员但被归属过滤清空的板块如实披露
            # （该板断板候选不被考虑=既有板块轴设计，不静默丢）
            "boardsEmptied": sorted(b for b in today_sealed_boards
                                    if b not in boards_of)}

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
            # P2-6（review）：整轨全缺 gain10 → 该轨龙一按首封时间降级选出，按轨披露
            for _seg in ("main", "growth"):
                _seg_c = [c for c in cands if segment_of(c["code"]) == _seg]
                if _seg_c and not any(isinstance(c.get("gain10"), (int, float))
                                      for c in _seg_c):
                    meta.setdefault("spaceTrackGaps", {}).setdefault(board, []).append(
                        f"{_seg}轨10日涨幅全缺，龙一按首封时间降级选出（fail-visible）")
            # v12 定稿（用户 2026-10-28 三轮裁决）：height=当日 streak 与近 3 日历史高度取大
            # （真连板/断板反包/断板不反包三种情况均参与空间板判定）；断板不反包且今日
            # 跌停（主板 ≤-9.9%/双创 ≤-19.9%）剔除（「未跌停」条件，fail-visible 披露）
            hist_by_code: dict[str, int] = {}
            for c in pool_prev.get(board, []):
                h = c.get("histStreak")
                if isinstance(h, int):
                    hist_by_code[c["code"]] = max(h, hist_by_code.get(c["code"], h))
            unsealed = [c for c in cands if c["code"] not in today_codes]
            limit_down_excluded: list[str] = []
            if unsealed:
                changes = (day_change_fetcher or _default_day_change_fetcher)(
                    [c["code"] for c in unsealed], date)
                kept_unsealed: set[str] = set()
                for c in unsealed:
                    chg = changes.get(c["code"])
                    seg = segment_of(c["code"])
                    thr = -19.9 if seg == "growth" else -9.9
                    if isinstance(chg, (int, float)) and chg <= thr:
                        limit_down_excluded.append(
                            f"{c.get('name') or c['code']}({chg:+.1f}%)")
                    else:
                        kept_unsealed.add(c["code"])   # 涨跌幅不可考→保留（不猜）
                if limit_down_excluded:
                    meta.setdefault("limitDownExcluded", {})[board] = limit_down_excluded
                cands = [c for c in cands if c["code"] in today_codes
                         or c["code"] in kept_unsealed]
            for c in cands:
                hs = [h for h in (c.get("streak") if c["code"] in today_codes else None,
                                  hist_by_code.get(c["code"])) if isinstance(h, int)]
                c["height"] = max(hs) if hs else None
            # 龙头弱转强口径（2026-11-01 用户裁决）：断板反包候选须真连板高度≥2——
            # 「近池有板」只作跟风股与板块总体弱转强统计口径（反包个股数>昨日数），
            # 首板断板股不构成龙头反包候选（实证：邵阳液压 10-29 首板、10-30 断板
            # 被标断板反包候选，用户判定不对）；高度不可考 → 剔除+披露（不猜）
            kept_cands: list[dict] = []
            low_height_broken: list[str] = []
            for c in cands:
                if c["code"] in today_codes:
                    kept_cands.append(c)
                    continue
                h = c.get("height")
                if isinstance(h, int) and h >= 2:
                    kept_cands.append(c)
                else:
                    low_height_broken.append(
                        f"{c.get('name') or c['code']}(高度{h if h is not None else '不可考'})")
            if low_height_broken:
                meta.setdefault("lowHeightBrokenExcluded", {})[board] = low_height_broken
            cands = kept_cands
            # v12 分轨：主板/双创各取龙一（同一排序键，space_leaders_by_segment 单一实现）
            leaders_iter = [(seg, ld, ld["code"] in sealed)
                            for seg, ld in space_leaders_by_segment(cands)]
        else:
            leaders_iter = [(None, rank_board_stocks(stocks)[0], True)]
        for seg, leader, sealed_today in leaders_iter:
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
                # v12 分轨：segment 仅 space_mode 出（main/growth）；历史窗口径无此字段
                "segment": seg,
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
                # 区间高度 N天M板（封板龙一=当日 num；断板龙一=最近封板日 num）：
                # 节点龙头列未封板时替代旧「断板反包」徽章（2026-11-12 用户裁决）
                "days": (leader.get("days") if space_mode else None),
                "boards": (leader.get("boards") if space_mode else None),
                "leaderSealedToday": sealed_today,
                # v5 预登记 P1：断板龙一最近封板日（窗位由消费侧算）；续板/默认口径为 None
                "poolDay": (leader.get("poolDay") if space_mode else None),
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