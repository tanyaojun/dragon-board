"""隔日弱转强节点分类（2026-10-21 立项，口径预注册见 docs/hotlist-jev/jev-weak-to-strong-day-study.md）。

单一事实源：语料行（operations/jev_relay_index.weak_to_strong_line）与连板情绪读口
（/api/hotlist-jev/relay-index 的 wzs 字段）共用同一分类器，不写第二份阈值。

判定规则（研究 §1 预注册，确定性计算、零模型结论、不用当日 relayIndex 判形态——循环依赖）：
  弱（T-1）  relayIndex <= 40
  强（T）    relayIndex >= 50 且 Δ >= +10
  结构确认   跌停家数下降 或 涨停家数回升，至少其一
  hit(T)     三者同时满足；continuation(T) = hit(T-1)

节点三态（2026-10-22 用户裁决：列表枚举=弱/弱转强/强；优先级=转换节点>状态）：
  "wzs"     hit=True（命中日 idx 必 ≥50，与强重叠时取转换节点优先）
  "strong"  relayIndex >= 50 且非命中日（命中次日即延续，前端 tooltip 标注全史延续率）
  "weak"    relayIndex <= 40（弱势区状态日，含冰点）
  None      40 < idx < 50 中性区（不标）

fail-visible：任一原料缺失 → hit=False 且 reason 结构化（不伪 0、不静默）。

节点定格（2026-10-22 用户裁决 §6.3，回应「重跑改写节点→判定标准不稳定」）：
  收盘首次落库时定档（settle_day），写入 relay 文档 wzs 字段，此后一次定格：
  重跑只更新叙事/评分，已定格节点不改写（first-write-wins）；未定格日回退现算。
  全史基线/读口/语料行统一从「定格优先、现算兑底」的 classify_series 取数（单一事实源）。
历史回填用一次性 CLI（支持存档 idx override，如 10-20 定档值 50.1 记录于研究档案 §1）。

定档代际绑定（2026-10-22 §6.4 预注册）：定档条目记录 gen=questionSetVersion；
阈值（40/50/Δ10）是在 v7.1 分数分布上预注册的，题集升代全量复跑后旧代定格
对新序列不再有裁决力——_settled_stamps 只采纳 gen=当前代 的定格，代际不匹配
自动回退现算（fail-visible），升代后必须执行 --reset 回填重新定档（旧档先归档）。
"""
from __future__ import annotations

import time
from typing import Any

from backend.analysis.hotlist.jev_relay_ammo import QUESTION_SET_VERSION_RELAY

from backend.analysis.hotlist.market_facts import frame_market_facts

# 预注册阈值（研究 §1；改动须同步 jev-weak-to-strong-day-study.md 并说明）
WEAK_IDX_MAX = 40.0
STRONG_IDX_MIN = 50.0
MIN_IDX_DELTA = 10.0

_BASELINE_CACHE: dict[str, dict] = {}


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
    """涨停家数日序列（15:00 收盘帧口径，一次聚合取每日最新帧；不缓存——
    审查 MF-3：缓存会让常驻进程在盘后新数据落库后继续用陈旧序列定档，错档不可改写）。"""
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
    return out


def _settled_stamps(db: Any) -> dict[str, dict]:
    """已定格节点（relay 文档内嵌 wzs 字段，收盘定档一次定格）。

    代际绑定：只采纳 gen=当前题集代 的定格（无 gen 的历史档视作 v7.1 初代）；
    升代后旧代定格自动失效回退现算，待 --reset 回填重新定档（跨代不可比）。"""
    out: dict[str, dict] = {}
    for doc in db["hotlist_jev_relay_index"].find({}, {"wzs": 1, "tradingDate": 1}):
        w = doc.get("wzs")
        if isinstance(w, dict) and "state" in w:
            if (w.get("gen") or "v7.1") != QUESTION_SET_VERSION_RELAY:
                continue
            d = doc.get("tradingDate") or str(doc["_id"]).split(":")[0]
            out[str(d)] = w
    return out


def classify_series(db: Any, dataset_id: str = "dragonboard_live",
                    idx_map: dict[str, float] | None = None) -> dict[str, dict]:
    """全序列逐日分类：{date: {..., "state"}}。定格优先（已定档日用存档节点），
    未定档日回退现算；continuation 链用叠加后的 hit 传导（定格命中传给未定格次日）。

    idx_map 仅供 settle_day 注入本次落库评分复用同一判定逻辑（审查 SF-1：
    消除与 _settle_entry 的平行实现，单源零第二份阈值）；外部调用不传。

    原料缺一日 → 该日 hit=False + reason（'prev_idx_missing' / 'idx_missing' / 'insufficient_history'），
    结构确认项缺失时该侧不参与（两侧全缺 → 'no_structural_confirm'）。
    """
    idx = dict(idx_map) if idx_map is not None else relay_idx_series(db)
    dt = limit_down_series(db)
    zt = zt_series(db, dataset_id)
    dates = sorted(idx)
    live: dict[str, dict] = {}
    for i, d in enumerate(dates):
        confirm: list[str] = []
        if i > 0:
            p = dates[i - 1]
            if dt.get(p) is not None and dt.get(d) is not None and dt[d] < dt[p]:
                confirm.append("dt_down")
            if zt.get(p) is not None and zt.get(d) is not None and zt[d] > zt[p]:
                confirm.append("zt_up")
        if i == 0:
            live[d] = {"hit": False, "continuation": False, "prevIdx": None, "idx": idx[d],
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
        live[d] = {"hit": reason is None, "continuation": False,
                   "prevIdx": idx[p], "idx": idx[d], "confirm": confirm, "reason": reason}
    # 节点三态（优先级=转换节点>状态；研究 §6 落地登记）
    for d in dates:
        i_ = live[d]["idx"]
        live[d]["state"] = ("wzs" if live[d]["hit"]
                            else "strong" if i_ >= STRONG_IDX_MIN
                            else "weak" if i_ <= WEAK_IDX_MAX else None)
    # 定格叠加 + continuation 链（叠加后 hit 传导，重跑不改写已定格节点）
    stamps = _settled_stamps(db)
    out: dict[str, dict] = {}
    for d in dates:
        if d in stamps:
            s = stamps[d]
            out[d] = {"hit": bool(s.get("hit")), "continuation": bool(s.get("continuation")),
                      "prevIdx": s.get("prevIdx"), "idx": s.get("idx"),
                      "confirm": list(s.get("confirm") or []), "reason": s.get("reason"),
                      "state": s.get("state"), "settled": True}
        else:
            out[d] = live[d]
    for j, d in enumerate(dates):
        if d not in stamps:
            out[d]["continuation"] = bool(out[dates[j - 1]]["hit"]) if j > 0 else False
    return out


def classify_day(db: Any, date: str, dataset_id: str = "dragonboard_live") -> dict:
    """单日分类（classify_series 的单日取用；读口/语料行共用，定格优先）。"""
    return classify_series(db, dataset_id).get(date) or {
        "hit": False, "continuation": False, "prevIdx": None, "idx": None,
        "confirm": [], "reason": "no_relay_doc"}


def settle_day(db: Any, date: str, dataset_id: str = "dragonboard_live",
               idx_override: float | None = None, regenerate: bool = False) -> dict | None:
    """收盘定档：以本次落库 relayIndex（或存档 override，如 10-20=50.1）为当日指数。

    幂等 first-write-wins：已定档日直接返回现有存档节点（重跑不改写，判定标准稳定的
    唯一来源）；idx_override 仅限历史回填时引用研究档案存档值，需在档案登记依据。
    regenerate=True 仅供题集升代后重新定档（§6.4）：忽略既有定格重新计算。

    拒绝定档（返回 None，fail-visible 由调用方呈现，审查 MF-2/SF-3）：
    - 无有效收盘评分（degraded/缺 relayIndex）——评分侧未定档，下轮成功后自然定档；
    - 指数条件已满足但结构确认两侧原料不齐（跌停/涨停任一侧缺）——“无确认”不可裁决，
      不得把原料缺失定格成判定未命中。"""
    col = db["hotlist_jev_relay_index"]
    doc = col.find_one({"_id": f"{date}:RELAY"}) or {}
    if not regenerate and isinstance(doc.get("wzs"), dict) and "state" in doc["wzs"]:
        return doc["wzs"]
    idx_val = idx_override if idx_override is not None else doc.get("relayIndex")
    if not isinstance(idx_val, (int, float)) or isinstance(idx_val, bool):
        return None
    # 注入本次落库评分，复用 classify_series 同一判定逻辑（SF-1 单源）
    idx_map = relay_idx_series(db)
    idx_map.pop(date, None)
    idx_map[date] = float(idx_val)
    series = classify_series(db, dataset_id, idx_map=idx_map)
    entry = series.get(date)
    if entry is None:
        return None
    if (entry["prevIdx"] is not None and entry["prevIdx"] <= WEAK_IDX_MAX
            and entry["idx"] is not None and entry["idx"] >= STRONG_IDX_MIN
            and entry["idx"] - entry["prevIdx"] >= MIN_IDX_DELTA and not entry["confirm"]):
        # 指数条件已满足但确认为空：两侧原料必须齐全才能裁决「无确认」
        dates = sorted(series)
        prev = dates[dates.index(date) - 1] if dates.index(date) > 0 else None
        dt = limit_down_series(db)
        zt = zt_series(db, dataset_id)
        dt_known = prev is not None and dt.get(prev) is not None and dt.get(date) is not None
        zt_known = prev is not None and zt.get(prev) is not None and zt.get(date) is not None
        if not (dt_known and zt_known):
            return None
    return {**entry, "gen": QUESTION_SET_VERSION_RELAY,
            "settledAt": time.strftime("%Y-%m-%dT%H:%M:%S")}


def write_settlement(db: Any, date: str, dataset_id: str = "dragonboard_live",
                     idx_override: float | None = None, dry_run: bool = False,
                     reset: bool = False) -> dict | None:
    """写定档（幂等）；dry_run 零写入。返回定档条目；无文档返回 None（fail-visible 由调用方呈现）。

    reset=True 仅供题集升代重放后的重新定档（覆盖旧代定格；调用方须先归档旧档，
    见 §6.4 升代流程）；正常运行路径永远 first-write-wins。"""
    if not db["hotlist_jev_relay_index"].find_one({"_id": f"{date}:RELAY"}):
        return None
    entry = settle_day(db, date, dataset_id, idx_override=idx_override,
                       regenerate=reset)
    if entry is None:
        return None
    if not dry_run:
        db["hotlist_jev_relay_index"].update_one(
            {"_id": f"{date}:RELAY"}, {"$set": {"wzs": entry}})
    return entry


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
