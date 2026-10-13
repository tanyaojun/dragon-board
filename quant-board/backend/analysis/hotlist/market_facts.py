# -*- coding: utf-8 -*-
"""市场/个股共享事实服务（2026-10-13 原料审计落地批，审计文档
docs/hotlist-jev/jev-direction-material-audit.md）。

定位：**描述统计事实**的单一算法源——jevu 各线（方向 v4/relay/cycle/phase）共用同一算法，
不同时点（as-of slot）各取快照。本服务只算事实，不含任何判断产物；
黑名单（引擎 tiers/finalSignal/compScore、jev 各线答案）一律不在此服务出现。

分层（AGENTS §2.2）：纯计算放 analysis，db 由调用方传入（pymongo 集合即数据访问，
无框架 IO）；TDX 取数壳在 operations（jev_label_jiuyan._daily_bars 同款）。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import THS_KEYS, percentile_rank

FACTS_VERSION = "2026-10-13a"


# ── 帧层时点事实（盘中口径，零未来函数） ─────────────────────────

def frame_market_facts(db: Any, date: str, slot: str,
                       dataset_id: str = "dragonboard_live") -> dict | None:
    """as-of slot 帧的盘面事实快照：涨停/炸板/回撤/连板梯队/最高板/全市场涨跌家数。

    与 operations/jev_label_jiuyan.market_metrics（15:00 收盘口径）同款提取，
    唯一差异=slot 参数化：方向线 11:00 判读取 11:00 帧，不碰 11:30 后帧（防未来函数）。
    数据缺失逐字段 None（fail-visible，不伪造 0）。
    """
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": slot},
        {"limitSummary.zhaban": 1, "limitSummary.continuousBoards": 1,
         "limitSummary.drawdown": 1, "limitSummary.thsPools": 1,
         "limitSummary.sealQuality": 1, "marketStats": 1},
        sort=[("timestamp", -1), ("snapshotId", -1)])
    if not f:
        return None
    ls = (f.get("limitSummary") or {})
    zb = ls.get("zhaban") or {}
    cb = ls.get("continuousBoards") or {}
    dd = ls.get("drawdown") or {}
    ms = f.get("marketStats") or {}
    up, down, flat = ms.get("upCount"), ms.get("downCount"), ms.get("flatCount")
    if not any(isinstance(v, (int, float)) and v for v in (up, down, flat)):
        up = down = flat = None  # 全 0=帧未采集涨跌家数（0 伪装缺失活案例，2026-10-13 11:00 帧实证）
    pools = ((ls.get("thsPools") or {}).get("pools") or {})
    ths_ladder = {k: (pools.get(k) or {}).get("total") for k in THS_KEYS}
    ths_pools = {k: (pools.get(k) or {}).get("total") for k in ("failed", "drawdown", "rushing")}
    sq = ls.get("sealQuality") or {}
    return {
        "slot": slot,
        "ztCount": zb.get("ztCount"), "zhabanCount": zb.get("count"),
        "zhabanRate": zb.get("rate"), "drawdownCount": dd.get("count"),
        "maxBoard": cb.get("maxBoard"),
        "thsLadder": ths_ladder if any(isinstance(v, (int, float)) for v in ths_ladder.values()) else None,
        "thsPools": ths_pools if any(isinstance(v, (int, float)) for v in ths_pools.values()) else None,
        "sealQuality": {k: sq.get(k) for k in ("byzCount", "hardCount", "rottenCount",
                                               "rottenShare", "avgSucRate")} if sq else None,
        "upCount": up, "downCount": down, "flatCount": flat,
    }


def market_zt_series(db: Any, date: str, n: int = 10,
                     dataset_id: str = "dragonboard_live") -> list[tuple[str, int]]:
    """近 n 个历史交易日（严格 < date）的涨停家数序列（各日 15:00 收盘口径）。"""
    dates = sorted({str(f["tradingDate"]) for f in db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "slotTime": "15:00"},
        {"tradingDate": 1}) if f.get("tradingDate")})
    prev = [d for d in dates if d < date][-n:]
    out: list[tuple[str, int]] = []
    for d in prev:
        m = frame_market_facts(db, d, "15:00", dataset_id) or {}
        if isinstance(m.get("ztCount"), (int, float)):
            out.append((d, int(m["ztCount"])))
    return out


def swing_anchor(db: Any, date: str, slot: str, n: int = 10,
                 dataset_id: str = "dragonboard_live") -> dict:
    """摆动锚（与 operations/jev_label_jiuyan.swing_summary_line 同算法）：

    窗口内涨停家数峰值/谷值（日期+距今交易日数）+ 今日 as-of slot 盘中值 +
    较昨日 Δ 与距峰值幅度。今日值用 slot 帧快照（盘中口径），历史值用 15:00 收盘口径。
    """
    vals = market_zt_series(db, date, n, dataset_id)
    cur = frame_market_facts(db, date, slot, dataset_id) or {}
    cur_zt = cur.get("ztCount") if isinstance(cur.get("ztCount"), (int, float)) else None
    if len(vals) < 5 or cur_zt is None:
        return {"ok": False, "reason": "窗口数据不足或当日槽缺失"}
    all_days = vals + [(date, int(cur_zt))]
    ordered = [d for d, _ in all_days]
    peak_d, peak = max(all_days, key=lambda x: (x[1], x[0]))
    trough_d, trough = min(all_days, key=lambda x: (x[1], x[0]))
    peak_ago = len(ordered) - 1 - ordered.index(peak_d)
    trough_ago = len(ordered) - 1 - ordered.index(trough_d)
    return {
        "ok": True, "window": len(all_days), "cur": int(cur_zt),
        "peak": peak, "peakDate": peak_d, "peakAgo": peak_ago,
        "trough": trough, "troughDate": trough_d, "troughAgo": trough_ago,
        "deltaPrev": int(cur_zt) - vals[-1][1], "distPeak": int(cur_zt) - peak,
        "hist": vals,
    }


# ── 个股序列折叠（判据 #1/#2/#9：不让模型从原始槽行心算） ──────────

def fold_attention_series(series_pts: list[dict], prev_days: list[str],
                          cur_day: str, cur_pct: float | None) -> dict:
    """槽级出现序列 → 日终折叠事实（铁律 5：衍生列现算，模型不替算）。

    输入 series_pts=[{d, slot, rank, pct, chg}]（判读点已 append 在尾）。
    输出：每日最后槽 pct（folded）+ 相邻日方向符号（+1/-1/0）+ 反向跳变标记
    （相邻日方向翻转且幅度 ≥ JUMP_MIN_POINTS）+ 连续下跌日计数（含判读日）。
    """
    JUMP_MIN_POINTS = 8.0
    by_day: dict[str, dict] = {}
    for p in series_pts:
        by_day[p["d"]] = p  # 时间升序输入，后写覆盖=每日最后槽
    days = [d for d in prev_days if d in by_day] + ([cur_day] if cur_day in by_day else [])
    folded = [{"d": d, "pct": by_day[d]["pct"], "chg": by_day[d].get("chg")} for d in days]
    directions: list[int] = []
    for i in range(1, len(folded)):
        a, b = folded[i - 1]["pct"], folded[i]["pct"]
        if a is None or b is None:
            directions.append(0)
        else:
            directions.append(1 if b > a else (-1 if b < a else 0))
    jumps = [i for i in range(1, len(directions))
             if directions[i - 1] != 0 and directions[i] == -directions[i - 1]
             and folded[i]["pct"] is not None and folded[i - 1]["pct"] is not None
             and abs(folded[i]["pct"] - folded[i - 1]["pct"]) >= JUMP_MIN_POINTS]
    falling = 0
    for d in reversed(directions):
        if d < 0:
            falling += 1
        else:
            break
    return {"folded": folded, "directions": directions, "jumpIdxs": jumps,
            "consecutiveFalling": falling, "days": days}
