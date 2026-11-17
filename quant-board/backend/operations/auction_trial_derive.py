# -*- coding: utf-8 -*-
"""试盘字段自建派生（kpl_bidding_series 官方 socket 序列 → 试盘语义行）。

背景（2026-11-16 复盘代办 item11「今日必须解决」+ 预登记 §7.7 用户裁决）：
试盘六字段 = WzsLinker 对委买额自采序列的统计（首帧/首加/峰值/末帧），非 KPL
推送字段——我方 kpl_bidding_series（socket pid=8 官方序列，5s tick）可计算同
语义观测值。对拍锚点：11-13 真值 605255 last_amount=8980000 与 MBL col4
（冻结委买额）精确一致 → 委买额同语义。

派生口径（仅消费 roster 实读字段，其余不猜不补 0）：
- jj_percent        = 末帧 bidding_pct（竞价涨幅）
- first/last/max_amount = 首帧/末帧/峰值帧 zt_buy_amount（委买额时序统计）
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

    返回 (rows, state)：rows = dict[code→字段]（与 auction_trial_raw 同形，可直接
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
    # 迟到 tick 防御（2026-11-17 对拍教训）：09:27 后为冻结后/连续竞价 regime，
    # 混入会污染「末帧=竞价冻结值」口径（当日实证：09:32 tick 使 selectedN 1→0）；
    # 旧档已含迟到 tick 时在此过滤（lateTicksFiltered 计数，不静默）。
    from datetime import datetime, timedelta, timezone as _tz
    _CST = _tz(timedelta(hours=8))
    _CUT = 9 * 3600 + 27 * 60
    ticks = []
    for t in all_ticks:
        ts = t.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        dt = datetime.fromtimestamp(ts, _CST)
        if dt.hour * 3600 + dt.minute * 60 + dt.second < _CUT:
            ticks.append(t)
    facts = derive_stock_series_facts(ticks)
    # bk_name 板块 join（同日 MBL raw col11）：缺 bk_name → 桥接失败 → mappedN=0
    # 第三源静默死亡（11-13 真值验证发现的要害，历史验证见测试）
    plates: dict[str, str] = {}
    plate_source_error = None
    try:
        mbl = db[COLLECTION_MBL_RAW].find_one({"_id": date}, {"rows": 1}) or {}
        for c, r in (mbl.get("rows") or {}).items():
            p = str((r or {}).get("plate") or "").strip()
            if p:
                plates[str(c)[-6:]] = p
    except Exception as exc:  # noqa: BLE001 — join 失败结构化留痕，不阻断派生
        plate_source_error = f"mbl_plate_join_failed:{type(exc).__name__}"
    rows: dict[str, dict] = {}
    plate_hit = 0
    for code, f in facts.items():
        first, last, mx = f.get("first"), f.get("last"), f.get("max")
        last_amount = _f((last or {}).get("zt_buy_amount"))
        if not last or last_amount is None or last_amount <= 0:
            continue  # 委买额不可见 → 不在试盘宇宙（如实缺席，不补 0）
        plate = plates.get(str(code)[-6:])
        if plate:
            plate_hit += 1
        rows[code] = {
            "code": code,
            "bk_name": plate,   # 桥接主链靠它；缺 → 板块归属缺席（fail-visible）
            "jj_percent": _f(last.get("bidding_pct")),
            "jj_amount": _f(last.get("bidding_amount")),
            "jj_turnover": _f(last.get("bidding_turnover")),
            "first_amount": _f(first.get("zt_buy_amount")) if first else None,
            "max_amount": _f(mx.get("zt_buy_amount")) if mx else None,
            "last_amount": last_amount,
        }
    if not rows:
        return {}, {**state, "reason": "no_ztbuy_visible"}
    out = {**state, "state": "ok", "n_rows": len(rows),
           "tickN": len(ticks),
           "lateTicksFiltered": len(all_ticks) - len(ticks),
           "plateJoinedN": plate_hit}
    if plate_source_error:
        out["plateSourceError"] = plate_source_error
    if not plates:
        out["plateMissing"] = True   # 板块 join 全缺席（如历史日 MBL raw 无档）
    return rows, out
