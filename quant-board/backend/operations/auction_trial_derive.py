# -*- coding: utf-8 -*-
"""试盘字段自建派生（kpl_bidding_series 官方 socket 序列 → 试盘语义行）。

背景（2026-11-16 复盘代办 item11「今日必须解决」+ 预登记 §7.7 用户裁决）：
试盘六字段 = WzsLinker 对委买额自采序列的统计（首帧/首加/峰值/末帧），非 KPL
推送字段——我方 kpl_bidding_series（socket pid=8 官方序列，5s tick）可计算同
语义观测值。对拍锚点：11-13 真值 605255 last_amount=8980000 与 MBL col4
（冻结委买额）精确一致 → 委买额同语义。

派生口径（仅消费 roster 实读字段，其余不猜不补 0）：
- jj_percent = 09:25 存档开盘涨幅权威（3006 现有流归档 kpl_auction_price，
  2026-11-18 用户裁决：真 09:25=撮合开盘，掉池股亦有；p0925/pct0925 全披露）；
  缺位逐层回退 MBL→bid→序列末帧（jjSource/jjFrozen 逐行披露）
- pct0915 = 竞价涨幅（09:15 竞价，2026-11-18 用户裁决与 09:25 开盘涨幅两时点
  分列展示）：权威=存档 s0915；缺档回退序列首帧 bidding_pct 观测值
  （jj915Src=open0915_archive/series_first 逐行披露；p0915 仅存档在场时有值）
- first/last/max_amount = 首帧/末帧/峰值帧 zt_buy_amount（委买额时序统计）
- first_add         = 首笔观测追加委买增量（tick 分笔首正 delta，2026-11-18
  用户裁决：首加额按 tick 分笔计算，非 KPL 推送字段；稀疏采样观测口径，
  与 Wzs 高频自采统计的粒度差登记于 docs §7.12/§7.15）
- start/end_time    = 观测首/末帧 ts（CST HH:MM:SS，≠Wzs 试盘起止语义，披露）
- price/percent     = 末帧 price/pct（竞价观测值）
- circulated_value  = 末帧 real_float（bid 口径实际流通，≠Wzs 历史口径，披露）
- pre_percent       = None（昨涨幅无零外呼本地源：日线需外呼，读侧红线 9 禁；
  如需补齐走采集路径预登记，docs §7.15）
- jj_amount         = 末帧 bidding_amount（竞价成交额，board_amt Σ口径）
- jj_turnover       = 末帧 bidding_turnover
- pre_percent       = None（roster 链 row_basis → preseal=False → 分母=代码口径
  limit；WzsLinker 昨涨停行 pre_percent=limit，比值数学等价；ST 由 bre.st_name_fix
  名称补正，不依赖 pre_percent 探测）
- universe = 序列内 zt_buy_amount>0 的股（委买额可见 ⊇ 试盘页宇宙，语义偏移
  记录于 docs §7.9；roster 自带 中热×mid50_95×撤减 过滤）
- bk_name = 同日 kpl_morning_bidding_raw col11 板块 join（板块归属主链靠 bk_name
  桥接：11-13 真值验证无 bk_name → mappedN=0 第三源静默死亡；注入后 mappedN/
  归属/入选与 WzsLinker 真值形态完全等价，见 tests test_historical_equivalence_1113）

WzsLinker（api-auction.php 非官方代理端点）降级为迁移期回退源：明日窗内双源
对拍（表进 docs §7.9）通过后删除采集路径（单主链红线，回退靠 git）。
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
                    "jj_turnover": _f((i or {}).get("bidding_turnover"))}
    except Exception:  # noqa: BLE001 — bid 读失败不阻断（MBL/序列仍可用）
        bid_frozen = {}
    # 09:15/09:25 价格+涨幅存档（3006 现有流，2026-11-18 用户裁决）：09:25=真撮合开盘
    # 涨幅权威（掉池股亦有）；09:15 同存供审计。无档→回退旧链并披露缺席。
    ap15: dict = {}
    ap25: dict = {}
    try:
        from backend.services.kpl_daban_archiver import load_auction_price
        ap = load_auction_price(db, date) or {}
        ap15 = ap.get("s0915") or {}
        ap25 = ap.get("s0925") or {}
    except Exception:  # noqa: BLE001 — 读失败不阻断（回退旧链+披露）
        ap15, ap25 = {}, {}

    def _hmss(ts: Any) -> str | None:
        if not isinstance(ts, (int, float)):
            return None
        return datetime.fromtimestamp(ts, _CST).strftime("%H:%M:%S")

    rows: dict[str, dict] = {}
    plate_hit = 0
    first_add_n = 0
    float_n = 0
    frozen_n = 0
    open_n = 0
    for code, f in facts.items():
        first, last, mx = f.get("first"), f.get("last"), f.get("max")
        last_amount = _f((last or {}).get("zt_buy_amount"))
        if not last or last_amount is None or last_amount <= 0:
            continue  # 委买额不可见 → 不在试盘宇宙（如实缺席，不补 0）
        plate = plates.get(str(code)[-6:])
        if plate:
            plate_hit += 1
        # 首加额=首笔观测追加委买增量（连续两帧均有限且后>前）
        h = hist.get(code) or []
        first_add = next((b - a for a, b in zip(h, h[1:])
                          if a is not None and b is not None and b > a), None)
        if first_add is not None:
            first_add_n += 1
        rf = _f((last_it.get(code) or {}).get("real_float"))
        if rf is not None:
            float_n += 1
        # 竞价三字段：09:25 冻结终值优先（MBL→bid；掉池股序列尾帧陈旧≠终值），
        # 缺位逐字段回退末帧观测值
        c6 = str(code)[-6:]
        a15 = ap15.get(c6) or {}
        a25 = ap25.get(c6) or {}
        fz = frozen.get(c6) or {}
        bf = bid_frozen.get(c6) or {}
        # 权威=09:25 存档开盘涨幅；缺位逐层回退 MBL→bid→序列末帧（披露 jjSource）
        jj_pct = _f(a25.get("pct"))
        jj_src = "open0925_archive" if jj_pct is not None else None
        if jj_pct is None:
            jj_pct = fz.get("jj_percent")
            jj_src = "mbl_frozen" if jj_pct is not None else None
        if jj_pct is None:
            jj_pct = bf.get("jj_percent")
            jj_src = "bid_frozen" if jj_pct is not None else None
        if jj_pct is None:
            jj_pct = _f(last.get("bidding_pct"))
            jj_src = "series_last"
        jj_amt = fz.get("jj_amount")
        if jj_amt is None:
            jj_amt = bf.get("jj_amount")
        if jj_amt is None:
            jj_amt = _f(last.get("bidding_amount"))
        jj_tur = fz.get("jj_turnover")
        if jj_tur is None:
            jj_tur = bf.get("jj_turnover")
        if jj_tur is None:
            jj_tur = _f(last.get("bidding_turnover"))
        is_frozen = jj_src != "series_last"
        if is_frozen:
            frozen_n += 1
        if jj_src == "open0925_archive":
            open_n += 1
        # 竞价涨幅（09:15 竞价）：权威=存档 s0915；缺档回退序列首帧观测值（时点披露）
        pct915 = _f(a15.get("pct"))
        src915 = "open0915_archive" if pct915 is not None else None
        if pct915 is None:
            pct915 = _f(first.get("bidding_pct"))
            src915 = "series_first" if pct915 is not None else None
        rows[code] = {
            "code": code,
            "bk_name": plate,   # 桥接主链靠它；缺 → 板块归属缺席（fail-visible）
            "jj_percent": jj_pct,
            "jj_amount": jj_amt,
            "jj_turnover": jj_tur,
            "jjSource": jj_src,
            "jjFrozen": is_frozen,
            "p0915": _f(a15.get("price")), "pct0915": pct915, "jj915Src": src915,
            "p0925": _f(a25.get("price")), "pct0925": _f(a25.get("pct")),
            "first_amount": _f(first.get("zt_buy_amount")) if first else None,
            "first_add": first_add,
            "max_amount": _f(mx.get("zt_buy_amount")) if mx else None,
            "last_amount": last_amount,
            "start_time": _hmss((first or {}).get("ts")),
            "end_time": _hmss(last.get("ts")),
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
           "open0925N": open_n, "open0925MissingN": len(rows) - open_n}
    if plate_source_error:
        out["plateSourceError"] = plate_source_error
    if not plates:
        out["plateMissing"] = True   # 板块 join 全缺席（如历史日 MBL raw 无档）
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
