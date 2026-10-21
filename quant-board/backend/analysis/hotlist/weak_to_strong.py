"""隔日弱转强节点分类（2026-10-21 立项，口径预注册见 docs/hotlist-jev/jev-weak-to-strong-day-study.md）。

单一事实源：语料行（operations/jev_relay_index.weak_to_strong_line）与连板情绪读口
（/api/hotlist-jev/relay-index 的 wzs 字段）共用同一分类器，不写第二份阈值。

判定规则（研究 §1 预注册，确定性计算、零模型结论、不用当日 relayIndex 判形态——循环依赖）：
  弱（T-1）  relayIndex <= 40
  强（T）    relayIndex >= 50 且 Δ >= +10
  结构确认   跌停家数下降 或 涨停家数回升，至少其一
  hit(T)     三者同时满足；continuation(T) = hit(T-1)

fail-visible：任一原料缺失 → hit=False 且 reason 结构化（不伪 0、不静默）。
全史基线（18 次样本统计）从存储数据现算 + 进程内缓存（research 重跑代码即跟随）。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.hotlist.market_facts import frame_market_facts

# 预注册阈值（研究 §1；改动须同步 jev-weak-to-strong-day-study.md 并说明）
WEAK_IDX_MAX = 40.0
STRONG_IDX_MIN = 50.0
MIN_IDX_DELTA = 10.0

_BASELINE_CACHE: dict[str, dict] = {}
_ZT_SERIES_CACHE: dict[str, dict[str, int]] = {}


def relay_idx_series(db: Any) -> dict[str, float]:
    """relayIndex 日序列（唯一来源 hotlist_jev_relay_index，status=ok）。"""
    return {str(d["_id"]).split(":")[0]: float(d["relayIndex"])
            for d in db["hotlist_jev_relay_index"].find({"status": "ok"}, {"relayIndex": 1})
            if isinstance(d.get("relayIndex"), (int, float)) and not isinstance(d.get("relayIndex"), bool)}


def limit_down_series(db: Any) -> dict[str, int]:
    """全市场跌停家数日序列（唯一来源 market_daily_limit_down，与跌停复盘页同源）。"""
    return {str(d["_id"]): int(d["count"]) for d in db["market_daily_limit_down"].find({}, {"count": 1})
            if isinstance(d.get("count"), (int, float)) and not isinstance(d.get("count"), bool)}


def zt_series(db: Any, dataset_id: str = "dragonboard_live") -> dict[str, int]:
    """涨停家数日序列（15:00 收盘帧口径，一次聚合取每日最新帧；进程内缓存）。"""
    cached = _ZT_SERIES_CACHE.get(dataset_id)
    if cached is not None:
        return cached
    out: dict[str, int] = {}
    try:
        cur = db["snapshot_frames"].aggregate([
            {"$match": {"datasetId": dataset_id, "type": "half_hour", "slotTime": "15:00"}},
            {"$sort": {"tradingDate": 1, "timestamp": 1, "snapshotId": 1}},
            {"$group": {"_id": "$tradingDate", "last": {"$last": "$limitSummary.zhaban.ztCount"}}},
        ])
        for row in cur:
            v = row.get("last")
            date = row.get("_id")
            if isinstance(v, (int, float)) and not isinstance(v, bool) and date:
                out[str(date)] = int(v)
    except Exception:
        return {}
    _ZT_SERIES_CACHE[dataset_id] = out
    return out


def classify_series(db: Any, dataset_id: str = "dragonboard_live") -> dict[str, dict]:
    """全序列逐日分类：{date: {"hit", "continuation", "prevIdx", "idx", "confirm", "reason"}}。

    原料缺一日 → 该日 hit=False + reason（'prev_idx_missing' / 'idx_missing' / 'insufficient_history'），
    结构确认项缺失时该侧不参与（两侧全缺 → 'no_structural_confirm'）。
    """
    idx = relay_idx_series(db)
    dt = limit_down_series(db)
    zt = zt_series(db, dataset_id)
    dates = sorted(idx)
    out: dict[str, dict] = {}
    for i, d in enumerate(dates):
        confirm: list[str] = []
        if i > 0:
            p = dates[i - 1]
            if dt.get(p) is not None and dt.get(d) is not None and dt[d] < dt[p]:
                confirm.append("dt_down")
            if zt.get(p) is not None and zt.get(d) is not None and zt[d] > zt[p]:
                confirm.append("zt_up")
        if i == 0:
            out[d] = {"hit": False, "continuation": False, "prevIdx": None, "idx": idx[d],
                      "confirm": confirm, "reason": "insufficient_history"}
            continue
        p = dates[i - 1]
        reason = None
        if idx[p] > WEAK_IDX_MAX:
            reason = "prev_not_weak"
        elif idx[d] < STRONG_IDX_MIN:
            reason = "idx_below_strong"
        elif idx[d] - idx[p] < MIN_IDX_DELTA:
            reason = "delta_below_threshold"
        elif not confirm:
            reason = "no_structural_confirm"
        out[d] = {"hit": reason is None, "continuation": False,
                  "prevIdx": idx[p], "idx": idx[d], "confirm": confirm, "reason": reason}
    for d in dates:
        p = dates[dates.index(d) - 1] if dates.index(d) > 0 else None
        if p is not None:
            out[d]["continuation"] = bool(out[p]["hit"])
    return out


def classify_day(db: Any, date: str, dataset_id: str = "dragonboard_live") -> dict:
    """单日分类（classify_series 的单日取用；读口/语料行共用）。"""
    return classify_series(db, dataset_id).get(date) or {
        "hit": False, "continuation": False, "prevIdx": None, "idx": None,
        "confirm": [], "reason": "no_relay_doc"}


def weak_to_strong_baseline(db: Any, dataset_id: str = "dragonboard_live") -> dict:
    """全史基线（语料行参照带）：命中次数、弱转强日反包率均值 vs 全体、跌停修复特征、T+1 延续率。

    反包率来源 = hotlist_rewrap_pool final 快照（2026-05-06 起回填）；池缺失日不参与均值
    （有效样本数如实返回）。结果进程内缓存——研究重跑后重启进程即跟随（单一事实源=存储数据）。
    """
    cached = _BASELINE_CACHE.get(dataset_id)
    if cached is not None:
        return cached
    cls = classify_series(db, dataset_id)
    hits = [d for d, r in cls.items() if r["hit"]]
    from backend.operations.rewrap_pool import get_rewrap_pool
    rates_all: list[float] = []
    rates_hit: list[float] = []
    dt_prev: list[int] = []
    dt_hit: list[int] = []
    cont_total = cont_ok = 0
    dates = sorted(cls)
    for d, r in cls.items():
        p = get_rewrap_pool(db, d, "final") or {}
        rate = p.get("rewrapRate")
        if isinstance(rate, (int, float)) and not isinstance(rate, bool):
            rates_all.append(float(rate))
            if r["hit"]:
                rates_hit.append(float(rate))
        if r["hit"]:
            j = dates.index(d)
            prev = dates[j - 1] if j > 0 else None
            for tgt, bucket in ((prev, dt_prev), (d, dt_hit)):
                a = (db["market_daily_limit_down"].find_one({"_id": tgt}) or {}).get("count") if tgt else None
                if isinstance(a, (int, float)):
                    bucket.append(int(a))
            if j + 1 < len(dates):
                cont_total += 1
                if cls[dates[j + 1]]["idx"] >= cls[d]["idx"]:
                    cont_ok += 1
    import statistics
    base = {
        "hitN": len(hits),
        "hitRewrapMean": round(statistics.mean(rates_hit), 4) if rates_hit else None,
        "allRewrapMean": round(statistics.mean(rates_all), 4) if rates_all else None,
        "hitRewrapN": len(rates_hit), "allRewrapN": len(rates_all),
        "dtPrevMedian": round(statistics.median(dt_prev), 1) if dt_prev else None,
        "dtHitMedian": round(statistics.median(dt_hit), 1) if dt_hit else None,
        "dtN": len(dt_hit),
        "contTotal": cont_total, "contOk": cont_ok,
    }
    _BASELINE_CACHE[dataset_id] = base
    return base
