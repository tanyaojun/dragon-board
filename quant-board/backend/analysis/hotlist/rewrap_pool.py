# -*- coding: utf-8 -*-
"""反包板池（rewrap）纯计算层——断板反包/炸板回封市场级口径。

立项预注册：`docs/hotlist-jev/jev-rewrap-factor-preregistration.md`（2026-10-21 用户裁决
1A/2A/3A/4A/5A + 补充「反包板池一日两更 / 复盘页 KPI+明细 / 池内股免投喂承接前日标签」）。

口径（预注册 §3，单一事实源）：
- 断板候选池(D) = (ZT(D-2) ∪ ZT(D-3) ∪ ZT(D-4) ∪ ZT(D-5)) − ZT(D-1)
  （近 5 交易日在板、昨日未板——「昨日应封未封」的观察池）
- 反包家数 fb(D) = 候选池 ∩ 今日名单
- 反包率 = |fb| ÷ |候选池|（池空 → 不可算，不补 0）
- 回封率 = |FAIL(D-1) ∩ 今日名单| ÷ |FAIL(D-1)|（昨日炸板池缺失 → 不可算）
- slot=final → 今日名单=收盘名单（封板口径）；slot=midday → 午盘名单（**触板口径**，
  午盘触板≠封板，与 EOD 不可直接比，消费方必须带口径徽标）

预研结论锚定（预注册 §4）：裸反包计数与当日涨停家数 corr=0.684 强共线 → 跨日比较
一律用率；rewrapRate 与当日 relayIndex corr=0.527（当日锚）。

取数纪律：全部复用既有集合（`jiuyan_action` 名单 / `snapshot_frames` 15:00 帧）；
`zt_codes`/`failed_codes` 是本模块唯一新增读取（与 relay `_pool_of` 同集合同键）。
v1 边界：候选池**未分辨停牌复牌**（TDX 无棒与断板同形，relay 真连板口径同款陷阱），
消费行/卡片必须带「停牌复牌未分辨」注记，不得把候选池读成纯断板池。
"""
from __future__ import annotations

import re
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID

REWRAP_LOOKBACK_DAYS = 5      # 候选池回看窗（前 2~5 个交易日在板）
_RE_NUM = re.compile(r"(\d+)\s*天\s*(\d+)\s*板")


def _strip(code: Any) -> str:
    return str(code or "").strip()[-6:]


def zt_codes(db: Any, date: str, slot: str = "final") -> set[str]:
    """某日韭研名单 code 集合（slot=final 封板口径 / midday 触板口径）。"""
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:{slot}"}, {"fields": 1}) or {}
    out: set[str] = set()
    for fl in doc.get("fields") or []:
        for s in fl.get("stocks") or []:
            c = _strip(s.get("code"))
            if c:
                out.add(c)
    return out


def failed_codes(db: Any, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> tuple[set[str], bool]:
    """某日 THS 炸板池 code 集合；(空集, False)=池缺失（fail-visible，不冒充）。

    取数单源 = relay `_ths_pool_items`（带 timestamp/snapshotId 倒序，同日多帧重采取新；
    审查 SF3：禁第二套帧读取实现）。"""
    from backend.operations.jev_relay_index import _ths_pool_items
    items, found = _ths_pool_items(db, date, dataset_id, "failed")
    return {_strip(it.get("code")) for it in items if it.get("code")}, found


def _num_of(text: Any) -> tuple[int | None, int | None]:
    """韭研 num「N天M板」→ (days, boards)；num=None/空 → (None, None)（首板口径）。"""
    m = _RE_NUM.search(str(text or ""))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _prev_axis(db: Any, date: str, dataset_id: str) -> list[str]:
    """date 之前 REWRAP_LOOKBACK_DAYS 个交易日（升序）。"""
    from backend.operations.jev_label_jiuyan import trading_dates_before
    return trading_dates_before(db, date, REWRAP_LOOKBACK_DAYS, dataset_id=dataset_id)


def build_rewrap_pool(db: Any, date: str, slot: str = "final",
                      dataset_id: str = DEFAULT_DATASET_ID) -> dict:
    """反包板池构建（纯函数，db 只读）。

    返回 {tradingDate, slot, caliber, candidateN, candidate: {code: 详情}, rewrapCodes,
    rewrapN, rewrapRate, prevFailedFound, prevFailedN, resealCodes, resealN, resealRate,
    missing: {…fail 标志}}。候选池空/昨日炸板池缺失等情况一律显式 missing 标志，
    不补 0、不冒充（AGENTS §4.0）。"""
    axis = _prev_axis(db, date, dataset_id)          # 升序 prev 交易日（≤5）
    today_codes = zt_codes(db, date, slot)
    # 候选池：前 2~5 交易日在板（axis[-2] 及更早），昨日（axis[-1]）未板；
    # 顺手记录各股窗口内最大区间高度 M（单遍扫描，禁每股×每日重复查询）
    in_board_prev: dict[str, dict] = {}              # code → 最近一次在板信息
    if len(axis) >= 2:
        prev_day_codes = zt_codes(db, axis[-1], "final")
        for i, d in enumerate(axis[:-1]):            # axis[-1] 是昨日（必须未板）
            doc = db["jiuyan_action"].find_one({"_id": f"{d}:final"}, {"fields": 1}) or {}
            for fl in doc.get("fields") or []:
                for s in fl.get("stocks") or []:
                    c = _strip(s.get("code"))
                    if not c:
                        continue
                    _, m = _num_of(s.get("num"))
                    cur = in_board_prev.get(c)
                    if cur is None:
                        in_board_prev[c] = {"prevLastDate": d, "seenDates": [d], "prevMaxBoards": m or 1}
                    else:
                        cur["prevLastDate"] = d        # 升序遍历 → 末次赋值即最近在板日
                        cur["seenDates"].append(d)
                        cur["prevMaxBoards"] = max(cur["prevMaxBoards"], m or 1)
        candidate = {c: info for c, info in in_board_prev.items() if c not in prev_day_codes}
    else:
        candidate = {}
    # 昨日 final 名单缺失 → 「昨日未板」不可验，候选池会静默膨胀（审查 SF4）：
    # 反包率/反包家数置不可算，missing 显式标志（不补 0 不冒充）
    prev_day_doc = (db["jiuyan_action"].find_one({"_id": f"{axis[-1]}:final"}, {"_id": 1})
                    if axis else None)
    prev_final_missing = bool(axis) and prev_day_doc is None
    if prev_final_missing:
        candidate = {}
    rewrap_codes = sorted(candidate.keys() & today_codes) if (axis and not prev_final_missing) else []
    rewrap_rate = (len(rewrap_codes) / len(candidate)) if (axis and candidate and not prev_final_missing) else None
    # 回封率（昨日炸板池今日回封）
    prev_date = axis[-1] if axis else None
    prev_failed, prev_failed_found = (set(), False)
    if prev_date:
        prev_failed, prev_failed_found = failed_codes(db, prev_date, dataset_id)
    reseal_codes = sorted(prev_failed & today_codes) if prev_failed_found else []
    reseal_rate = (len(reseal_codes) / len(prev_failed)) if (prev_failed_found and prev_failed) else None
    # 明细（今日名单口径字段 + 候选池回溯字段）
    today_doc = db["jiuyan_action"].find_one({"_id": f"{date}:{slot}"}, {"fields": 1}) or {}
    today_info: dict[str, dict] = {}
    for fl in today_doc.get("fields") or []:
        for s in fl.get("stocks") or []:
            c = _strip(s.get("code"))
            if c and c not in today_info:
                days, boards = _num_of(s.get("num"))
                today_info[c] = {"name": s.get("name"), "num": s.get("num"),
                                 "days": days, "boards": boards, "time": s.get("time"),
                                 "board": fl.get("name")}
    stocks = []
    for c in rewrap_codes:
        info = candidate[c]
        row = dict(today_info.get(c) or {"name": None, "num": None, "days": None,
                                         "boards": None, "time": None, "board": None})
        row.update({"code": c, "prevLastDate": info["prevLastDate"],
                    "prevMaxBoards": info.get("prevMaxBoards"),
                    "prevSeenDates": info["seenDates"],
                    "breakDays": (len(axis) - axis.index(info["prevLastDate"]) - 1 if axis else None),
                    "reseal": c in reseal_codes})
        stocks.append(row)
    missing = {
        "axis_short": len(axis) < 2,           # 交易日轴不足（候选池不可定义）
        "today_list_empty": not today_codes,   # 今日名单为空
        "prev_failed_missing": not prev_failed_found and bool(prev_date),
        "prev_final_missing": prev_final_missing,  # 昨日名单缺失（候选池不可验，审查 SF4）
    }
    return {
        "tradingDate": date, "slot": slot,
        "caliber": "sealed" if slot == "final" else "touched",
        "axis": axis, "candidateN": len(candidate), "candidate": candidate,
        "rewrapCodes": rewrap_codes, "rewrapN": len(rewrap_codes),
        "rewrapRate": round(rewrap_rate, 4) if rewrap_rate is not None else None,
        "prevFailedFound": prev_failed_found, "prevFailedN": len(prev_failed),
        "resealCodes": reseal_codes, "resealN": len(reseal_codes) if prev_failed_found else None,
        "resealRate": round(reseal_rate, 4) if reseal_rate is not None else None,
        "missing": missing, "stocks": stocks,
    }


def rewrap_rate_series(db: Any, date: str, n: int = 20,
                       dataset_id: str = DEFAULT_DATASET_ID) -> list[tuple[str, float | None]]:
    """date 之前 n 个交易日的反包率序列（升序；不含当日；供近 20 日分位）。"""
    from backend.operations.jev_label_jiuyan import trading_dates_before
    out: list[tuple[str, float | None]] = []
    for d in trading_dates_before(db, date, n, dataset_id=dataset_id):
        pool = build_rewrap_pool(db, d, "final", dataset_id)
        out.append((d, pool["rewrapRate"]))
    return out


def percentile_of(series: list[float | None], value: float | None) -> int | None:
    """value 在序列（忽略 None）中的分位（0-100）；样本不足或 value 缺 → None。"""
    vals = sorted(v for v in series if v is not None)
    if value is None or len(vals) < 5:
        return None
    below = sum(1 for v in vals if v <= value)
    return round(below / len(vals) * 100)
