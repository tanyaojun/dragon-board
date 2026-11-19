# -*- coding: utf-8 -*-
"""试盘字段自建派生（kpl_bidding_series 官方 socket 序列 → 试盘语义行）。

背景（2026-11-16 复盘代办 item11「今日必须解决」+ 预登记 §7.7 用户裁决）：
试盘六字段 = WzsLinker 对委买额自采序列的统计（首帧/首加/峰值/末帧），非 KPL
推送字段——我方 kpl_bidding_series（socket pid=8 官方序列，5s tick）可计算同
语义观测值。对拍锚点：11-13 真值 605255 last_amount=8980000 与 MBL col4
（冻结委买额）精确一致 → 委买额同语义。

派生口径（仅消费 roster 实读字段，其余不猜不补 0）：
- jj_percent = 09:25 撮合开盘涨幅终值权威=KPL 直连盯盘 Type=7（kpl_auction_matched，
  2026-11-19 裁决②全面对齐 App）→ TDX 盘中开盘棒应急兜底（仅披露不作共权威）；
  不回退 MBL/bid/末帧（早退值≠开盘）；jjSource/jjFrozen 逐行披露
- pct0925/p0925（开盘涨幅列）= Type=7 终值 → TDX 盘中开盘棒应急（kpl_bidding_series
  .open_pct，非成员制全宇宙覆盖，archiver 顺带 prev_pct 取数零新增外呼）；3006 退役；
  **不回退 MBL/bid/序列末帧**（成员制掉池股早退值≠开盘，11-16 预登记缺陷定案；
  002652 锚：早退 9.77% vs 真开盘 0.00%）；缺位如实 None + open0925Src 披露
- pct0915 = 竞价涨幅（09:15 竞价，与 09:25 开盘涨幅两时点分列展示）：权威=pid8
  序列首帧 bidding_pct（3006 退役；B 后 ≤09:15:10，3s 粒度披露）；p0915=首帧 price
  （jj915Src=series_first 逐行披露）
- first/last/max_amount = 首帧/末帧/峰值帧 zt_buy_amount（委买额时序统计）
- first_add         = 首笔观测追加委买增量（tick 分笔首正 delta，2026-11-18
  用户裁决：首加额按 tick 分笔计算，非 KPL 推送字段；稀疏采样观测口径，
  与 Wzs 高频自采统计的粒度差登记于 docs §7.12/§7.15）
- start/end_time    = 观测首/末帧 ts（CST HH:MM:SS，≠Wzs 试盘起止语义，披露）
- price/percent     = 末帧 price/pct（竞价观测值）
- circulated_value  = 末帧 real_float（bid 口径实际流通，≠Wzs 历史口径，披露）
- pre_percent       = None（昨涨幅无零外呼本地源：日线需外呼，读侧红线 9 禁；
  如需补齐走采集路径预登记，docs §7.15）
- jj_amount/jj_turnover = 竞价三字段单一投影层（auction_bidding_facts，2026-11-19
  用户裁决）：公布值（留池真 0 保留）→ 掉池股 col10 窗内末帧虚拟观测 → 派生换手；
  净额状态门缺位（未公布 None，不烘 0）；jjAmountSrc/jjTurnoverSrc 逐行披露。
  投影全源读失败 → 旧链（MBL冻结→bid冻结→序列末帧）观测兜底 + legacy_fallback 披露
- pre_percent       = None（roster 链 row_basis → preseal=False → 分母=代码口径
  limit；WzsLinker 昨涨停行 pre_percent=limit，比值数学等价；ST 由 bre.st_name_fix
  名称补正，不依赖 pre_percent 探测）
- universe = 序列内 zt_buy_amount>0 的股（委买额可见 ⊇ 试盘页宇宙，语义偏移
  记录于 docs §7.9；roster 自带 中热×mid50_95×撤减 过滤）
- bk_name = 同日 kpl_morning_bidding_raw col11 板块 join（2026-11-19 裁决 1+2 增
  纯库读回退链：同日 raw → 最近前日 raw 档 → 同日 pid8 bid lane plate；逐股源
  bkNameSrc 披露；板块归属主链靠 bk_name
  桥接：11-13 真值验证无 bk_name → mappedN=0 第三源静默死亡；注入后 mappedN/
  归属/入选与 WzsLinker 真值形态完全等价，见 tests test_historical_equivalence_1113）

终值/撮合权威=KPL 直连盯盘 Type=7（kaipanla，复用 auction_bidding_direct；2026-11-19
用户裁决全直连）；wzslinker 代理退出接入路径（随时断链=单点故障）。过程序列=pid8 socket。
"""
from __future__ import annotations

import math
from typing import Any

COLLECTION_SERIES = "kpl_bidding_series"
COLLECTION_MBL_RAW = "kpl_morning_bidding_raw"



def _f(v: Any) -> float | None:
    """数值消毒（与 auction_strength.fnum 同口径：NaN/Inf → None，不伪装 0）。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def derive_trial_rows_from_series(db: Any, date: str) -> tuple[dict[str, dict], dict]:
    """序列档 → 试盘语义行（纯库读零外呼零写）。

    返回 (rows, state)：rows = dict[code→字段]（与历史试盘行同形，可直接
    进 trial_strength_roster）；state 结构化透出缺席/降级原因（§4.0）。
    """
    state: dict[str, Any] = {"state": "absent", "source": "kpl_bidding_series_derived"}
    try:
        from backend.services.kpl_daban_archiver import (
            derive_stock_series_facts, load_bidding_series)
        sdoc = load_bidding_series(db, date)
    except Exception as exc:  # noqa: BLE001 — 读失败结构化透出，不阻断调用方
        return {}, {**state, "reason": f"series_read_failed:{type(exc).__name__}"}
    if not sdoc:
        return {}, {**state, "reason": "no_series_archive"}
    all_ticks = sdoc.get("ticks") or []
    # tick 时效窗防御 [09:15, 09:27)（2026-11-17 双教训，档内已污染时保护重导出）：
    # ① 早于 09:15 = 盘前陈旧态（09:00 交易门禁后会话爆发推昨日终态页，污染
    #   first 基线）；② 晚于 09:27 = 冻结后/连续竞价 regime（09:32 tick 使
    #   selectedN 1→0 实证，污染 last 口径）。early/lateTicksFiltered 计数留痕。
    from datetime import datetime, timedelta, timezone as _tz
    _CST = _tz(timedelta(hours=8))
    _LO, _CUT = 9 * 3600 + 15 * 60, 9 * 3600 + 27 * 60
    ticks, n_early, n_late = [], 0, 0
    for t in all_ticks:
        ts = t.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        dt = datetime.fromtimestamp(ts, _CST)
        hm = dt.hour * 3600 + dt.minute * 60 + dt.second
        if hm < _LO:
            n_early += 1
        elif hm >= _CUT:
            n_late += 1
        else:
            ticks.append(t)
    ticks.sort(key=lambda t: t.get("ts") or 0)   # 时序确定（first_add 分笔依赖）
    facts = derive_stock_series_facts(ticks)
    # 逐股有序委买额历史（first_add=首正增量；缺值帧不配对，不猜）
    hist: dict[str, list] = {}
    last_it: dict[str, dict] = {}   # 末帧原始行（real_float 不在 facts 白名单，直读）
    for t in ticks:
        for it in t.get("it") or []:
            sid = str(it.get("s") or "")
            if sid:
                hist.setdefault(sid, []).append(_f(it.get("zt_buy_amount")))
                last_it[sid] = it
    # bk_name 板块 join（同日 MBL raw col11）：缺 bk_name → 桥接失败 → mappedN=0
    # 第三源静默死亡（11-13 真值验证发现的要害，历史验证见测试）
    plates: dict[str, str] = {}
    frozen: dict[str, dict] = {}   # MBL 09:25 冻结终值（竞价涨幅/成交额/换手权威）
    plate_source_error = None
    try:
        mbl = db[COLLECTION_MBL_RAW].find_one({"_id": date}, {"rows": 1}) or {}
        for c, r in (mbl.get("rows") or {}).items():
            c6 = str(c)[-6:]
            p = str((r or {}).get("plate") or "").strip()
            if p:
                plates[c6] = p
            frozen[c6] = {"jj_percent": _f((r or {}).get("bidding_pct")),
                          "jj_amount": _f((r or {}).get("bidding_amount")),
                          "jj_turnover": _f((r or {}).get("bidding_turnover"))}
    except Exception as exc:  # noqa: BLE001 — join 失败结构化留痕，不阻断派生
        plate_source_error = f"mbl_plate_join_failed:{type(exc).__name__}"
    # 2026-11-19 裁决 1+2：bk_name 纯库读回退源①=最近前日 MBL raw 档（09:26 读口
    # 同日 raw 未落库时板块桥接不再静默死亡；_id<date 倒序首条=最近归档日）
    plates_prev: dict[str, str] = {}
    try:
        pm = db[COLLECTION_MBL_RAW].find_one({"_id": {"$lt": date}},
                                             sort=[("_id", -1)],
                                             projection={"rows": 1}) or {}
        for c, r in (pm.get("rows") or {}).items():
            p = str((r or {}).get("plate") or "").strip()
            if p:
                plates_prev[str(c)[-6:]] = p
    except Exception:  # noqa: BLE001 — 回退源失败不阻断（同日源仍可用）
        plates_prev = {}
    # bid 通道 09:25 匹配推送冻结值（MBL 榜外掉池股的官方终值兑底，纯库读）
    bid_frozen: dict[str, dict] = {}
    try:
        pool = db["kpl_daban_pool"].find_one({"_id": date}, {"bid_items": 1}) or {}
        for i in pool.get("bid_items") or []:
            c6 = str((i or {}).get("stock_id") or "")[-6:]
            if c6:
                bid_frozen[c6] = {
                    "jj_percent": _f((i or {}).get("bidding_pct")),
                    "jj_amount": _f((i or {}).get("bidding_amount")),
                    "jj_turnover": _f((i or {}).get("bidding_turnover")),
                    # 2026-11-19 裁决 1+2：bk_name 回退源②=pid8 bid lane plate（pos11）
                    "plate": str((i or {}).get("plate") or "").strip() or None}
    except Exception:  # noqa: BLE001 — bid 读失败不阻断（MBL/序列仍可用）
        bid_frozen = {}
    # 终值权威=KPL 直连盯盘 Type=7（kpl_auction_matched，2026-11-19 裁决②：全面
    # 对齐 App、单主链；wzs 代理退出、3006 退役）。主计划会话预登记探针冻结列映射后
    # 落库；未落库时向前兼容回退应急链（TDX，仅披露不作共权威）。
    # 跨会话合同：rows[code]={pct,price,amount,turnover,end_time}（终值语义，掉池股亦有）。
    matched: dict = {}
    try:
        mdoc = db["kpl_auction_matched"].find_one({"_id": date}, {"rows": 1}) or {}
        matched = mdoc.get("rows") or {}
    except Exception:  # noqa: BLE001 — 读失败不阻断（应急链+披露）
        matched = {}
    # TDX 盘中开盘棒（archiver 顺带 prev_pct 取数落库，2026-11-19）：非成员制
    # 全宇宙开盘涨幅兜底权威；sdoc 全档读已含 open_pct 加字段
    open_bar: dict = sdoc.get("open_pct") or {}
    # 竞价三字段单一投影层（2026-11-19 用户裁决：净额/成交额/换手状态门投影，
    # 纯库读零外呼；jj_percent 链不接投影——开盘涨幅语义独立，见头注）
    trio_facts: dict = {}
    trio_state: dict = {}
    try:
        from backend.operations.auction_bidding_facts import resolve_bidding_trio
        _trio = resolve_bidding_trio(db, date)
        trio_facts, trio_state = _trio["facts"], _trio["state"]
        trio_census = _trio["census"]
    except Exception as exc:  # noqa: BLE001 — 投影失败不阻断（旧链兜底+披露）
        trio_census = {}
        trio_state = {"state": f"trio_failed:{type(exc).__name__}"}

    def _hmss(ts: Any) -> str | None:
        if not isinstance(ts, (int, float)):
            return None
        return datetime.fromtimestamp(ts, _CST).strftime("%H:%M:%S")

    rows: dict[str, dict] = {}
    plate_hit = 0
    plate_src_n: dict = {}
    first_add_n = 0
    float_n = 0
    frozen_n = 0
    open_n = 0
    open_tdx_n = 0
    first0915_n = 0
    for code, f in facts.items():
        first, last, mx = f.get("first"), f.get("last"), f.get("max")
        last_amount = _f((last or {}).get("zt_buy_amount"))
        if not last or last_amount is None or last_amount <= 0:
            continue  # 委买额不可见 → 不在试盘宇宙（如实缺席，不补 0）
        c6p = str(code)[-6:]
        plate = plates.get(c6p)
        bk_src = "mbl_same" if plate else None
        if not plate:
            plate = plates_prev.get(c6p)
            bk_src = "mbl_prev" if plate else None
        if not plate:
            plate = (bid_frozen.get(c6p) or {}).get("plate") or None
            bk_src = "bid_plate" if plate else None
        if plate:
            plate_hit += 1
            plate_src_n[bk_src] = plate_src_n.get(bk_src, 0) + 1
        # 首加额=首笔观测追加委买增量（连续两帧均有限且后>前）
        h = hist.get(code) or []
        first_add = next((b - a for a, b in zip(h, h[1:])
                          if a is not None and b is not None and b > a), None)
        if first_add is not None:
            first_add_n += 1
        rf = _f((last_it.get(code) or {}).get("real_float"))
        if rf is not None:
            float_n += 1
        # trio 投影缺位时旧链（MBL→bid→末帧）观测兜底；fz/bf 仅供该兜底与板块 join
        c6 = str(code)[-6:]
        fz = frozen.get(c6) or {}
        bf = bid_frozen.get(c6) or {}
        ob = open_bar.get(c6) or {}
        mt = matched.get(c6) or {}
        # 开盘涨幅（09:25 撮合开盘）：终值权威=Type=7 → TDX 应急兜底（披露）；
        # 不回退 MBL/bid/末帧（成员制早退值≠开盘，缺陷定案见头注）
        open_pct = _f(mt.get("pct"))
        open_pr = _f(mt.get("price"))
        open_src = "dingpan_postmatch" if open_pct is not None else None
        if open_pct is None:
            open_pct = _f(ob.get("pct"))
            # 半缺位形态防制：仅当 pct 在场才顺带取 price
            if open_pct is not None:
                open_pr = _f(ob.get("price"))
                open_src = "tdx_bar_open"
        if open_src == "dingpan_postmatch":
            open_n += 1
        elif open_src == "tdx_bar_open":
            open_tdx_n += 1
        # jj_percent 与开盘涨幅同链（终值语义独立于 trio 投影，见头注）
        jj_pct = _f(mt.get("pct"))
        jj_src = "dingpan_postmatch" if jj_pct is not None else None
        if jj_pct is None:
            jj_pct = _f(ob.get("pct"))
            jj_src = "tdx_bar_open" if jj_pct is not None else None
        # 竞价成交额/换手：接投影层（公布值→col10 虚拟观测→派生换手；净额状态门
        # 缺位不烘 0）；投影无该股（全源读失败降级）→ 旧链观测兜底 + 披露
        fact = trio_facts.get(c6)
        if _f(mt.get("amount")) is not None or _f(mt.get("turnover")) is not None:
            # Type=7 终值优先（掉池股撮合终值，socket 无此块）
            jj_amt = _f(mt.get("amount"))
            jj_amt_src = "dingpan_postmatch" if jj_amt is not None else None
            jj_tur = _f(mt.get("turnover"))
            jj_tur_src = "dingpan_postmatch" if jj_tur is not None else None
        elif fact is not None:
            jj_amt = fact["bidding_amount"]
            jj_amt_src = fact["bidding_amount_src"]
            jj_tur = fact["bidding_turnover"]
            jj_tur_src = fact["bidding_turnover_src"]
        else:
            jj_amt = fz.get("jj_amount")
            if jj_amt is None:
                jj_amt = bf.get("jj_amount")
            if jj_amt is None:
                jj_amt = _f(last.get("bidding_amount"))
            jj_amt_src = "legacy_fallback" if jj_amt is not None else None
            jj_tur = fz.get("jj_turnover")
            if jj_tur is None:
                jj_tur = bf.get("jj_turnover")
            if jj_tur is None:
                jj_tur = _f(last.get("bidding_turnover"))
            jj_tur_src = "legacy_fallback" if jj_tur is not None else None
        is_frozen = jj_src is not None
        if is_frozen:
            frozen_n += 1
        # 竞价涨幅（09:15 竞价）：权威=pid8 序列首帧（3006 退役，B 后 ≤09:15:10，
        # 3s 粒度披露）；p0915 同取首帧 price
        pct915 = _f(first.get("bidding_pct"))
        src915 = "series_first" if pct915 is not None else None
        if src915 == "series_first":
            first0915_n += 1
        rows[code] = {
            "code": code,
            "bk_name": plate,   # 桥接主链靠它；缺 → 板块归属缺席（fail-visible）
            "bkNameSrc": bk_src,   # 同日 MBL/前日 MBL/pid8 plate/None（裁决 1+2 披露）
            "jj_percent": jj_pct,
            "jj_amount": jj_amt,
            "jj_turnover": jj_tur,
            "jjAmountSrc": jj_amt_src,
            "jjTurnoverSrc": jj_tur_src,
            "jjSource": jj_src,
            "jjFrozen": is_frozen,
            "p0915": _f((first or {}).get("price")), "pct0915": pct915, "jj915Src": src915,
            "p0925": open_pr, "pct0925": open_pct, "open0925Src": open_src,
            "first_amount": _f(first.get("zt_buy_amount")) if first else None,
            "first_add": first_add,
            "max_amount": _f(mx.get("zt_buy_amount")) if mx else None,
            "last_amount": last_amount,
            "start_time": _hmss((first or {}).get("ts")),
            "end_time": (mt.get("end_time") or _hmss(last.get("ts"))),
            "price": _f(last.get("price")),
            "percent": _f(last.get("pct")),
            "circulated_value": rf,
            "pre_percent": None,   # 无零外呼本地源（§7.15，不猜不补 0）
        }
    if not rows:
        return {}, {**state, "reason": "no_ztbuy_visible"}
    out = {**state, "state": "ok", "n_rows": len(rows),
           "tickN": len(ticks),
           "earlyTicksFiltered": n_early, "lateTicksFiltered": n_late,
           "plateJoinedN": plate_hit,
           "firstAddN": first_add_n, "floatJoinedN": float_n,
           "frozenJoinedN": frozen_n,
           "open0925N": open_n, "open0925TdxN": open_tdx_n,
           "open0925MissingN": len(rows) - open_n - open_tdx_n,
           "seriesFirst0915N": first0915_n,
           "trioCensus": trio_census, "trioState": trio_state}
    if plate_source_error:
        out["plateSourceError"] = plate_source_error
    out["plateSrcN"] = plate_src_n   # 逐股板块源计数（裁决 1+2 披露）
    if not plates:
        out["plateMissing"] = True   # 同日 MBL raw 缺席（回退链仍可用，见 plateSrcN）
    return rows, out


def normalize_trial_time(val: object) -> object | None:
    """时间归一化（原 auction_trial_fetch 单源，2026-11-18 raw 退役下沉）：
    HHMMSS→hh:mm:ss；已带冒号原样；不可判原样返回（fail-visible 不猜不丢）。"""
    s = str(val or "").strip()
    if not s:
        return None
    if ":" in s:
        return s
    digits = s.replace(".", "")
    if digits.isdigit() and len(digits) in (5, 6):
        digits = digits.zfill(6)
        return f"{digits[:2]}:{digits[2:4]}:{digits[4:6]}"
    return s


def load_trial_rows(db: Any, date: str) -> tuple[dict[str, dict], dict]:
    """试盘行单实现（读口/leaders 共用）：官方序列派生单主链（2026-11-18
    auction_trial_raw 整集合退役，docs §7.17；无历史档回退）。异常结构化留痕不抛。"""
    try:
        return derive_trial_rows_from_series(db, date)
    except Exception as exc:  # noqa: BLE001 — 派生失败不阻断（fail-visible）
        return {}, {"state": f"derive_failed:{type(exc).__name__}",
                    "source": "kpl_bidding_series_derived"}
