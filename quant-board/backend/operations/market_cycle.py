# -*- coding: utf-8 -*-
"""第4课·市场情绪周期：操作层（P1 事件流，原料单源取齐 + 落库 + 回填）。

预登记：`docs/hotlist-jev/market-cycle-preregistration-20261112.md` P1。计算口径全在
`analysis/hotlist/market_cycle.py`（纯函数）；本层只做：
1. 单源取料（THS 池/韭研 final/真连板映射/TDX 日线/既有命运 helper），不新增采集；
2. 落库单集合 `hotlist_jev_market_cycle`（每交易日一文档，upsert 幂等，重跑可回放）；
3. 深历史回填复用 `leader_wzs.bars_covering`/`covering_*_fetcher`（覆盖式日线单源）。

命运计算单源 = `jev_relay_index._pool_of/_status_map/_close_pct`（池权威 + 日线补洞，
停牌不算断板 v4）；排序键单源 = `analysis/hotlist/market_cycle.rank_market_space`（v13 市场接力口径 height 主键；题材链仍 v12 `theme_leader_ammo.space_leaders_by_segment`）。
生产写库只入 `dragon_board_quant`；pytest 只入 `dragon_board_test`（conftest 护栏）。
P1 产事件流（anchor/ceiling/events）；P2 增状态机（state/transition/daysInState，输入=事件流
only）与并列参照（reference：relayPhase/relayIndex/大盘wzs/规则五档同日只读快照，不进判据）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.analysis.hotlist import market_cycle as mc
from backend.analysis.hotlist.theme_leader_ammo import segment_of
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.jev_label_jiuyan import (_jiuyan_days_boards,
                                                 jiuyan_streak_map,
                                                 trading_dates_before)
from backend.operations.jev_relay_index import _close_pct, _pool_of, _status_map
from backend.operations.leader_wzs import (covering_day_change_fetcher,
                                           covering_gain_fetcher)
from backend.operations.theme_leader_baseline import (DEFAULT_DATASET_ID,
                                                      sealed_and_info)
from backend.operations.tdx_daily_bars import fetch_gains10

COLLECTION = "hotlist_jev_market_cycle"


def _final_stocks(db: Any, date: str) -> list[dict]:
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
    out: list[dict] = []
    seen: set[str] = set()
    for field in doc.get("fields") or []:
        for st in field.get("stocks") or []:
            c6 = str(st.get("code") or "")[-6:]
            if c6 and c6 not in seen:
                seen.add(c6)
                out.append(st)
    return out


def compute_anchor(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID, *,
                   gain_fetcher=None, day_change_fetcher=None,
                   pool_dates: list[str] | None = None) -> tuple[dict | None, dict]:
    """当日市场空间龙一（两轨）+ meta。THS 池缺失 → (None, degraded meta)。

    候选池 = 今日封板 ∪ 近 3 日封板（全市场，断板高高度龙头在锚内）；断板候选 histStreak=
    最近封板日真连板（甲口径），poolDay=最近封板日。enrichment 与排序走纯函数层
    （prepare_market_candidates / pick_market_leaders，v13 市场接力口径 height 主键单源
    rank_market_space；gain10 仅作锚展示，选取与之无关）。
    """
    today_sealed, _info, _meta = sealed_and_info(db, date, dataset_id)
    if today_sealed is None:
        return None, {"status": "degraded",
                      "reason": "当日 THS 池缺失，封板不可二分（fail-visible）"}
    pool_dates = pool_dates if pool_dates is not None else trading_dates_before(
        db, date, 3, dataset_id)
    streaks_today = jiuyan_streak_map(db, date, dataset_id) or {}

    cands: list[dict] = []
    have: set[str] = set()
    for st in _final_stocks(db, date):
        c6 = str(st.get("code") or "")[-6:]
        if c6 in today_sealed and c6 not in have:
            d, b = _jiuyan_days_boards(st)
            cands.append({"code": c6, "name": st.get("name"), "time": st.get("time"),
                          "streak": streaks_today.get(c6), "days": d, "boards": b})
            have.add(c6)
    # 近 3 日封板池（断板反包入口）：v13(甲) histStreak=最近封板日真连板，
    # poolDay=最近封板日（E4 窗起点）；days/boards 区间高度截至最近封板日（展示单源）。
    # 新→旧遍历，首个出现日=最近封板日，取该日 streak（更早封板日不覆盖）。
    # 真连板含尾盘回封补证（_sealed_codes 2026-11-12 修复），回封日不误断链、不高估重置。
    pool_seen: dict[str, dict] = {}
    for pd in reversed(pool_dates):
        if not pd or pd == date:
            continue
        p_sealed, _pi, _pm = sealed_and_info(db, pd, dataset_id)
        if not p_sealed:
            continue
        p_streaks = jiuyan_streak_map(db, pd, dataset_id) or {}
        for st in _final_stocks(db, pd):
            c6 = str(st.get("code") or "")[-6:]
            if c6 not in p_sealed or c6 in have or c6 in pool_seen:
                continue
            d, b = _jiuyan_days_boards(st)
            pool_seen[c6] = {"name": st.get("name"), "days": d, "boards": b,
                             "poolDay": pd, "histStreak": p_streaks.get(c6)}
    for c6, info in pool_seen.items():
        cands.append({"code": c6, "name": info["name"], "time": None,
                      "streak": None, "days": info["days"], "boards": info["boards"],
                      "histStreak": info["histStreak"], "poolDay": info["poolDay"]})
        have.add(c6)

    meta: dict[str, Any] = {"status": "ok", "poolDays": list(pool_dates)}
    if not cands:
        meta["reason"] = "当日无封板候选（fail-visible）"
        return {}, meta
    gains = (gain_fetcher or fetch_gains10)([c["code"] for c in cands], date)
    for c in cands:
        c["gain10"] = gains.get(c["code"])
    # v13 市场接力口径：龙一按 height 主键选出，与 gain10 无关（gain10 仅作锚展示+可忽略
    # 次级键）；gain10 全缺不降级、无需 spaceTrackGaps 披露（锚 gain10=None 自明，fail-visible）。
    unsealed = [c["code"] for c in cands if c["code"] not in today_sealed]
    changes = (day_change_fetcher or covering_day_change_fetcher)(unsealed, date) \
        if unsealed else {}
    kept, prep_meta = mc.prepare_market_candidates(cands, today_sealed, changes)
    meta.update(prep_meta)
    leaders = mc.pick_market_leaders(kept)

    anchors: dict[str, dict] = {}
    for seg, ld in leaders.items():
        sealed_today = ld["code"] in today_sealed
        anchors[seg] = {
            "code": ld["code"], "name": ld.get("name"), "segment": seg,
            "streak": ld.get("streak") if sealed_today else None,
            "time": ld.get("time") if sealed_today else None,
            "gain10": ld.get("gain10"), "height": ld.get("height"),
            "days": ld.get("days"), "boards": ld.get("boards"),
            "poolDay": ld.get("poolDay"), "leaderSealedToday": sealed_today,
        }
    return anchors, meta


def _ceiling_window(db: Any, date: str, dataset_id: str) -> list[dict]:
    """近 N 日天花板序列（升序，不含今日）。供 E1 参照 + E2 v2 持续段判定。"""
    window_dates = trading_dates_before(db, date, mc.CEILING_WINDOW, dataset_id)
    window: list[dict] = []
    for d in window_dates:
        cb = mc.ceiling_from_streaks(jiuyan_streak_map(db, d, dataset_id) or {})
        window.append({"date": d, "maxBoard": cb["maxBoard"]})
    return window


def _fate(db: Any, code: str, day: str, prev_day: str | None,
          dataset_id: str, pool_cache: dict) -> dict:
    """单日命运 {pct, status}（命运单源 _close_pct + _status_map）。"""
    pct = _close_pct(code, prev_day, day) if prev_day else None
    if day not in pool_cache:
        pool_cache[day] = _pool_of(db, day)
    status_map, _found = _status_map(db, day, pool_cache[day], {code}, dataset_id)
    return {"pct": pct, "status": status_map.get(code)}


def _anchor_fates(db: Any, date: str, anchors_prev: dict | None,
                  axis: list[str], dataset_id: str) -> dict:
    """昨日龙一（两轨）的今日/昨日命运 + 企稳窗（供 E3/E4）。"""
    out: dict[str, dict] = {}
    if not anchors_prev or date not in axis:
        return out
    ti = axis.index(date)
    yesterday = axis[ti - 1] if ti >= 1 else None
    daybefore = axis[ti - 2] if ti >= 2 else None
    pool_cache: dict[str, dict] = {}
    for track, anchor in anchors_prev.items():
        code = anchor["code"]
        fate_today = _fate(db, code, date, yesterday, dataset_id, pool_cache)
        fate_yest = _fate(db, code, yesterday, daybefore, dataset_id, pool_cache) \
            if yesterday else {"pct": None, "status": None}
        entry = {"anchor": {**anchor, "statusYesterday": fate_yest.get("status")},
                 "fate_today": fate_today, "fate_yesterday": fate_yest,
                 "stabilize_window": None}
        # 企稳窗：断板日 day0=poolDay 次一交易日；day1/day2，末日==date 才成窗
        pd_ = anchor.get("poolDay")
        if pd_ and pd_ in axis:
            pi = axis.index(pd_)
            if pi + 3 < len(axis) and axis[pi + 3] == date:
                day0, day1 = axis[pi + 1], axis[pi + 2]
                f1 = _fate(db, code, day1, day0, dataset_id, pool_cache)
                entry["stabilize_window"] = [
                    {"date": day1, "pct": f1["pct"], "status": f1["status"]},
                    {"date": date, "pct": fate_today["pct"], "status": fate_today["status"]}]
        out[track] = entry
    return out


def _breakthrough_stocks(db: Any, date: str, streaks_today: dict,
                         max_board: int) -> list[dict]:
    """今日最高板股（突破主体）+ 板型/一字注记（板型单源 stock_board_shape_line）。"""
    from backend.operations.jev_label_jiuyan import (_prev_close_of_date,
                                                     stock_board_shape_line)
    names = {str(st.get("code") or "")[-6:]: st.get("name")
             for st in _final_stocks(db, date)}
    out: list[dict] = []
    for code, sk in streaks_today.items():
        if isinstance(sk, int) and sk == max_board:
            shape = stock_board_shape_line(date, code, names.get(code),
                                           _prev_close_of_date(date, code))
            out.append({"code": code, "name": names.get(code),
                        "segment": segment_of(code), "streak": sk,
                        "boardShape": shape,
                        "oneWord": mc.one_word_from_shape(shape)})
    return sorted(out, key=lambda r: r["code"])


def _reference_snapshot(db: Any, date: str, dataset_id: str, *, include_relay: bool = True) -> dict:
    """并列参照同日只读快照（裁决 1A：无预设权威，不进判据，仅前端对照）。

    relayPhase/relayIndex/大盘wzs 单源 hotlist_jev_relay_index {date}:RELAY；规则五档单源
    hotlist_sentiment EOD（stage/emotionScore.score）。缺→None（fail-visible）。参照属辅助
    观测，读取异常不得阻断核心周期计算（不阻断红线），故容错留 None。
    """
    ref: dict[str, Any] = {"relayPhase": None, "relayIndex": None,
                           "marketWzs": None, "ruleStage": None, "ruleScore": None}
    if include_relay:
        try:
            rdoc = db["hotlist_jev_relay_index"].find_one({"_id": f"{date}:RELAY"}) or {}
            ref["relayPhase"] = rdoc.get("relayPhase")
            ref["relayIndex"] = rdoc.get("relayIndex")
            ref["marketWzs"] = rdoc.get("wzs")
        except Exception:  # noqa: BLE001 — 参照辅助，缺失不阻断
            pass
    try:
        sdoc = db["hotlist_sentiment"].find_one(
            {"datasetId": dataset_id, "snapshotType": "half_hour",
             "slotTime": "EOD", "tradingDate": date}) or {}
        ref["ruleStage"] = sdoc.get("stage")
        ref["ruleScore"] = (sdoc.get("emotionScore") or {}).get("score")
    except Exception:  # noqa: BLE001
        pass
    return ref


def refresh_reference(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict | None:
    """v8 解环（Option A）：relay 落库后补刷 market_cycle 并列参照（单日轻量）。

    market_cycle 确定性步在 relay 之前（defer_reference），relay 参照暂缺；本函数在 relay
    之后读当日 relay 档 + EOD，$set reference（事件/锚/天花板/态不动）。doc 缺失→None（不阻断）。
    """
    doc = db[COLLECTION].find_one({"_id": f"{date}:MARKET_CYCLE"})
    if not doc:
        return None
    ref = _reference_snapshot(db, date, dataset_id)
    db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": {"reference": ref}})
    return ref


def settle_day(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID, *,
               gain_fetcher=None, day_change_fetcher=None,
               prev_anchors: dict | None = None, prev_state: str | None = None,
               prev_days_in_state: int = 0, force: bool = False,
               defer_reference: bool = False) -> dict:
    """计算 + upsert 单集合文档（每交易日一文档，重跑幂等）；返回落库文档。

    prev_anchors 缺省 → 现算昨日龙一（单日运行）；回填逐日携带前一日 anchor 省重算。
    降级（THS 池缺失等）也落痕：status=degraded + reason（fail-visible，不静默跳过）。
    """
    anchors, ameta = compute_anchor(db, date, dataset_id,
                                    gain_fetcher=gain_fetcher,
                                    day_change_fetcher=day_change_fetcher)
    streaks_today = jiuyan_streak_map(db, date, dataset_id) or {}
    ceiling_today = mc.ceiling_from_streaks(streaks_today)
    window = _ceiling_window(db, date, dataset_id)
    axis = trading_dates_before(db, date, 30, dataset_id) + [date]
    if prev_anchors is None and len(axis) >= 2:
        prev_anchors, _pm = compute_anchor(db, axis[-2], dataset_id,
                                           gain_fetcher=gain_fetcher,
                                           day_change_fetcher=day_change_fetcher)
    fates = _anchor_fates(db, date, prev_anchors, axis, dataset_id)

    events: list[dict] = []
    meta: dict[str, Any] = {"status": ameta.get("status"), "anchorMeta": ameta}
    # E1/E2 只依赖韭研真连板（与 THS 池无关）→ THS 降级时仍产出可算部分（评审#1，§4.0
    # 部分来源失败不得连带阻断可计算部分）；E3/E4 需锚+命运，THS 缺时不可判。
    bt_stocks = (_breakthrough_stocks(db, date, streaks_today, ceiling_today["maxBoard"])
                 if isinstance(ceiling_today["maxBoard"], int) else [])
    e1 = mc.detect_breakthrough(date, ceiling_today["maxBoard"], window, bt_stocks)
    if e1:
        events.append(e1)
    # E2 v2（用户裁决 2026-11-12 改门）：空间高度持续打不开（maxBoard≤4 连续≥2日）。
    # 持续段从天花板序列算（window 升序不含今日 + 今日）；maxBoard None 断链 fail-visible。
    maxboards = [w["maxBoard"] for w in window] + [ceiling_today["maxBoard"]]
    e2 = mc.detect_compress(date, ceiling_today["maxBoard"],
                            mc.compress_low_streak(maxboards))
    if e2:
        events.append(e2)
    if ameta.get("status") == "degraded":
        meta["reason"] = ameta.get("reason")
        meta.setdefault("dataGaps", []).append(
            "THS 池缺失，E3/E4 锚不可判（E1/E2 独立韭研仍产出，fail-visible）")
    else:
        if not prev_anchors:
            meta.setdefault("dataGaps", []).append(
                "昨日锚不可得，E3/E4 不可判（fail-visible）")   # 评审#5
        for track, f in fates.items():
            e3 = mc.detect_collapse(date, track, f["anchor"],
                                    f["fate_today"], f["fate_yesterday"])
            if e3:
                events.append(e3)
            e4 = mc.detect_tolerance(date, track, f["anchor"],
                                     f["fate_today"], f["stabilize_window"])
            if e4:
                events.append(e4)
    # 暖机 keyed on 有效参照数（评审#4）：日历窗可能深于韭研史，有效 refs 才决定参照完整度。
    valid_refs = sum(1 for w in window if isinstance(w["maxBoard"], int))
    if valid_refs < mc.CEILING_WINDOW:
        meta.setdefault("dataGaps", []).append(
            f"天花板有效参照不足 {mc.CEILING_WINDOW} 日（实得 {valid_refs}）：暖机期如实披露")

    # P2 状态机（输入=事件流 only；参照不进判据，裁决 1A）。单日运行缺 prev_state →
    # 读前一交易日库态；回填逐日携带（首日前无库态 → step_day 首日 init，Q6=A）。
    warmup = valid_refs < mc.CEILING_WINDOW
    if prev_state is None and len(axis) >= 2:
        pdoc = db[COLLECTION].find_one({"_id": f"{axis[-2]}:MARKET_CYCLE"},
                                       {"state": 1, "daysInState": 1})
        if pdoc and pdoc.get("state"):
            prev_state = pdoc["state"]
            prev_days_in_state = pdoc.get("daysInState") or 0
    new_state, transition = mc.step_day(prev_state, events=events, date=date, warmup=warmup)
    days_in_state = 1 if transition is not None else prev_days_in_state + 1
    # v8 解环（Option A）：defer_reference=True 时 relay 尚未落库（market_cycle 确定性步在
    # relay 之前），relay 参照留 None，盘后链 relay 后由 refresh_reference 补刷。
    reference = _reference_snapshot(db, date, dataset_id, include_relay=not defer_reference)

    doc = {"_id": f"{date}:MARKET_CYCLE", "tradingDate": date,
           "version": mc.MARKET_CYCLE_VERSION, "status": meta.get("status"),
           "anchor": anchors or {}, "ceiling": {**ceiling_today,
                                                "prevCeiling20": max(
                                                    (w["maxBoard"] for w in window
                                                     if isinstance(w["maxBoard"], int)),
                                                    default=None),
                                                "windowDays": len(window),
                                                "prevWindowValidDays": valid_refs},
           "events": events, "state": new_state, "transition": transition,
           "daysInState": days_in_state, "reference": reference, "meta": meta,
           "generatedAt": datetime.now(timezone.utc).isoformat()}
    old = None if force else db[COLLECTION].find_one({"_id": doc["_id"]},
                                                     {"generatedAt": 1, "events": 1})
    if old:
        doc["generatedAt"] = old.get("generatedAt")
        if ([(e.get("type"), e.get("code")) for e in events]
                != [(e.get("type"), e.get("code")) for e in old.get("events") or []]):
            doc["recomputedAt"] = datetime.now(timezone.utc).isoformat()
    db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return doc


def backfill(db: Any, start: str, end: str, dataset_id: str = DEFAULT_DATASET_ID,
             *, offsets: tuple[int, ...] | None = None, force: bool = False) -> list[dict]:
    """区间逐日回填（升序，携带前一日 anchor 省重算）；覆盖式日线深历史取数。"""
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"_id": {"$regex": ":final$"}}, {"tradingDate": 1})
        if d.get("tradingDate") and start <= str(d["tradingDate"]) <= end})
    gf = lambda codes, d: covering_gain_fetcher(codes, d, offsets=offsets)  # noqa: E731
    cf = lambda codes, d: covering_day_change_fetcher(codes, d, offsets=offsets)  # noqa: E731
    prev_anchors: dict | None = None
    prev_state: str | None = None
    prev_days = 0
    docs: list[dict] = []
    for d in dates:
        doc = settle_day(db, d, dataset_id, gain_fetcher=gf, day_change_fetcher=cf,
                         prev_anchors=prev_anchors, prev_state=prev_state,
                         prev_days_in_state=prev_days, force=force)
        prev_anchors = doc.get("anchor") or None
        prev_state = doc.get("state")
        prev_days = doc.get("daysInState") or 0
        docs.append(doc)
        print(f"[market-cycle] {d} status={doc.get('status')} "
              f"state={doc.get('state')} days={doc.get('daysInState')} "
              f"events={len(doc.get('events') or [])} "
              f"maxBoard={doc.get('ceiling', {}).get('maxBoard')}")
    return docs


def replay_state(db: Any, start: str, end: str,
                 dataset_id: str = DEFAULT_DATASET_ID) -> list[dict]:
    """P2 历史态重放：对已落库事件流跑状态机（不重取 TDX，秒级）。

    状态机是事件流的纯函数（mc.replay），与 settle_day 内联计算同源同果；本通道仅把
    state/transition/daysInState/reference 补写进既有 doc（事件/锚/天花板不动）。升序全量
    重放保证首日起链一致；warmup=天花板窗<20（Q6 披露）。
    """
    docs = sorted((d for d in db[COLLECTION].find({})
                   if d.get("tradingDate") and start <= str(d["tradingDate"]) <= end),
                  key=lambda d: str(d["tradingDate"]))
    days = [{"date": str(d["tradingDate"]), "events": d.get("events") or [],
             "warmup": ((d.get("ceiling") or {}).get("prevWindowValidDays")
                        if (d.get("ceiling") or {}).get("prevWindowValidDays") is not None
                        else (d.get("ceiling") or {}).get("windowDays", 0)) < mc.CEILING_WINDOW}
            for d in docs]
    rows = mc.replay(days)
    for d, row in zip(docs, rows):
        ref = _reference_snapshot(db, str(d["tradingDate"]), dataset_id)
        db[COLLECTION].update_one({"_id": d["_id"]}, {"$set": {
            "state": row["state"], "transition": row["transition"],
            "daysInState": row["daysInState"], "reference": ref}})
    return rows


def recompress_and_replay(db: Any, start: str, end: str,
                          dataset_id: str = DEFAULT_DATASET_ID) -> list[dict]:
    """E2 v2 改门历史重算（用户裁决 2026-11-12）：从已落库 ceiling.maxBoard 序列重算空间
    压缩事件 + 全量重放状态机（不重取 TDX/韭研，秒级）。

    与 settle_day 的 E2 v2 同源（同调 mc.compress_low_streak + mc.detect_compress）；数据源
    为已落库天花板事实（=jiuyan 派生），E1/E3/E4 事件不动。须从区间首日起全量重放保证
    持续段与首日起链一致。逐日补写 events/state/transition/daysInState/reference/version。
    """
    docs = sorted((d for d in db[COLLECTION].find({})
                   if d.get("tradingDate") and start <= str(d["tradingDate"]) <= end),
                  key=lambda d: str(d["tradingDate"]))
    maxboards: list = []
    state: str | None = None
    days_in = 0
    rows: list[dict] = []
    for d in docs:
        dt = str(d["tradingDate"])
        mb = (d.get("ceiling") or {}).get("maxBoard")
        maxboards.append(mb)
        e2 = mc.detect_compress(dt, mb, mc.compress_low_streak(maxboards))
        events = [e for e in (d.get("events") or []) if e.get("type") != "spaceCompress"]
        if e2:
            events.append(e2)
        ceil = d.get("ceiling") or {}
        valid = ceil.get("prevWindowValidDays")
        warmup = (valid if valid is not None else ceil.get("windowDays", 0)) < mc.CEILING_WINDOW
        new_state, transition = mc.step_day(state, events=events, date=dt, warmup=warmup)
        days_in = 1 if transition is not None else days_in + 1
        ref = _reference_snapshot(db, dt, dataset_id)
        db[COLLECTION].update_one({"_id": d["_id"]}, {"$set": {
            "events": events, "state": new_state, "transition": transition,
            "daysInState": days_in, "reference": ref, "version": mc.MARKET_CYCLE_VERSION}})
        rows.append({"date": dt, "state": new_state, "e2": bool(e2), "maxBoard": mb})
        state = new_state
    return rows


if __name__ == "__main__":   # pragma: no cover — CLI（盘后链 P2 挂链前的手动/回填入口）
    import argparse
    import json as _json
    import sys as _sys

    _ap = argparse.ArgumentParser(description="市场情绪周期（第4课 P1 事件流 + P2 状态机，盘后口径）")
    _ap.add_argument("--day", help="YYYY-MM-DD 单日落库（缺省=最近韭研 final 日）")
    _ap.add_argument("--backfill", action="store_true", help="区间回填（须 --from --to）")
    _ap.add_argument("--replay-state", dest="replay_state", action="store_true",
                     help="P2：对已落库事件流重放状态机（不重取 TDX，须 --from --to）")
    _ap.add_argument("--recompress", action="store_true",
                     help="E2 v2 改门：从已落库天花板重算压缩事件+重放态（不重取 TDX，须 --from --to）")
    _ap.add_argument("--from", dest="start", help="回填起日 YYYY-MM-DD")
    _ap.add_argument("--to", dest="end", help="回填止日 YYYY-MM-DD")
    _ap.add_argument("--offset", type=int, default=None,
                     help="深历史日线单档 offset（如 250≈近一年；缺省阶梯式）")
    _ap.add_argument("--force", action="store_true", help="幂等覆盖（重算已 ok 日）")
    _ap.add_argument("--defer-reference", dest="defer_reference", action="store_true",
                     help="v8 解环：确定性步在 relay 前，relay 参照留 None 待补刷（单日）")
    _ap.add_argument("--refresh-reference", dest="refresh_reference", action="store_true",
                     help="v8 解环：relay 落库后补刷当日 reference（须 --day）")
    _ap.add_argument("--dataset-id", dest="dataset_id", default=DEFAULT_DATASET_ID)
    _args = _ap.parse_args()
    _db = get_runtime_mongodb_database()
    _offsets = (_args.offset,) if _args.offset else None
    if _args.refresh_reference:
        if not _args.day:
            print(_json.dumps({"ok": False, "error": "--refresh-reference 须 --day"}))
            _sys.exit(1)
        _ref = refresh_reference(_db, _args.day, _args.dataset_id)
        print(_json.dumps({"ok": _ref is not None, "date": _args.day,
                           "refreshed": _ref is not None,
                           "relayIndex": (_ref or {}).get("relayIndex")}, ensure_ascii=False))
    elif _args.recompress:
        if not (_args.start and _args.end):
            print(_json.dumps({"ok": False, "error": "--recompress 须 --from --to"}))
            _sys.exit(1)
        from collections import Counter as _Counter
        _rows = recompress_and_replay(_db, _args.start, _args.end, _args.dataset_id)
        print(_json.dumps({"ok": True, "days": len(_rows),
                           "states": dict(_Counter(r["state"] for r in _rows)),
                           "compressDays": sum(1 for r in _rows if r["e2"])},
                          ensure_ascii=False))
    elif _args.replay_state:
        if not (_args.start and _args.end):
            print(_json.dumps({"ok": False, "error": "--replay-state 须 --from --to"}))
            _sys.exit(1)
        from collections import Counter as _Counter
        _rows = replay_state(_db, _args.start, _args.end, _args.dataset_id)
        print(_json.dumps({"ok": True, "days": len(_rows),
                           "states": dict(_Counter(r["state"] for r in _rows))},
                          ensure_ascii=False))
    elif _args.backfill:
        if not (_args.start and _args.end):
            print(_json.dumps({"ok": False, "error": "--backfill 须 --from --to"}))
            _sys.exit(1)
        # 回填前置检查（2026-11-16 事故裁决，报告型）：其回填链自带 covering
        # fetchers（v13 gain10 全缺不降级），不设档阻断，只透出上游存档状态。
        from backend.operations.backfill_preflight import market_cycle_preflight
        _dates = sorted({str(d["tradingDate"]) for d in _db["jiuyan_action"].find(
            {"_id": {"$regex": ":final$"}}, {"tradingDate": 1})
            if d.get("tradingDate") and _args.start <= str(d["tradingDate"]) <= _args.end})
        _pre = market_cycle_preflight(_db, _dates, _args.dataset_id,
                                      allow_unhealthy=False)
        _pre["proceed"] = True
        print(_json.dumps({"preflight": _pre}, ensure_ascii=False))
        _docs = backfill(_db, _args.start, _args.end, _args.dataset_id,
                         offsets=_offsets, force=_args.force)
        _ev = sum(len(d.get("events") or []) for d in _docs)
        print(_json.dumps({"ok": True, "days": len(_docs), "events": _ev},
                          ensure_ascii=False))
    else:
        _day = _args.day
        if not _day:
            _days = sorted(str(d["tradingDate"]) for d in _db["jiuyan_action"].find(
                {"_id": {"$regex": ":final$"}}, {"tradingDate": 1}) if d.get("tradingDate"))
            _day = _days[-1] if _days else None
        if not _day:
            print(_json.dumps({"ok": False, "error": "无韭研 final，且未给 --day"}))
            _sys.exit(1)
        _doc = settle_day(_db, _day, _args.dataset_id, force=_args.force,
                          defer_reference=_args.defer_reference)
        print(_json.dumps({"ok": True, "date": _day, "status": _doc.get("status"),
                           "events": len(_doc.get("events") or []),
                           "anchor": {k: v.get("name") for k, v in
                                      (_doc.get("anchor") or {}).items()}},
                          ensure_ascii=False))
