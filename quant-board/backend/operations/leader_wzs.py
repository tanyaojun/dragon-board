# -*- coding: utf-8 -*-
"""题材周期·龙头弱转强：操作层（原料单源取齐 + 落库 + 覆盖式日线）。

预登记：`docs/hotlist-jev/theme-cycle-leader-wzs-preregistration-20261101.md` P1。
计算口径全在 `analysis/hotlist/leader_wzs.py`（纯函数）；本层只做：
1. 单源取料（THS 池/韭研 final/真连板映射/龙一结构行/TDX 日线），不新增采集；
2. 落库单集合 `hotlist_jev_leader_wzs`（每交易日一文档，upsert 幂等，重跑可回放）；
3. `bars_covering` 覆盖式日线：`fetch_daily_bars` 默认只取最近 15 根，深历史回填
   按日渐进加大 offset 直至覆盖目标日（fail-visible：仍不覆盖如实 None）。

生产写库只入 `dragon_board_quant`；pytest 数据只入 `dragon_board_test`
（conftest 护栏，本层不改变该边界）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.analysis.hotlist.leader_wzs import build_leader_wzs
from backend.analysis.hotlist.theme_leader_ammo import segment_of
from backend.operations.jev_label_jiuyan import (jiuyan_streak_map,
                                                 trading_dates_before)
from backend.operations.theme_leader_baseline import (DEFAULT_DATASET_ID,
                                                      day_leader_rows,
                                                      sealed_and_info)
from backend.operations.tdx_daily_bars import (fetch_daily_bars,
                                               gain10_from_bars)

COLLECTION = "hotlist_jev_leader_wzs"

# 渐进 offset 阶梯：15≈近3周 → 250≈近1年；命中即停（进程内负缓存防重扫）
_BAR_OFFSET_LADDER = (15, 40, 80, 160, 250)


def bars_covering(code: str, end_date: str,
                  min_dates: int = 1) -> dict[str, dict] | None:
    """覆盖 `end_date` 的日线（含其前至少 min_dates 根）；不覆盖 → 最后一次结果。"""
    last: dict[str, dict] | None = None
    for off in _BAR_OFFSET_LADDER:
        bars = fetch_daily_bars(str(code)[-6:], offset=off)
        last = bars
        if bars:
            covered = sorted(d for d in bars if d <= end_date)
            if len(covered) >= min_dates:
                return bars
    return last


def covering_gain_fetcher(codes, end_date: str,
                          window: int = 10) -> dict[str, float | None]:
    """深历史回填用 gain_fetcher：覆盖式取日线再算 10 日涨幅（fail-visible None）。"""
    return {c: gain10_from_bars(bars_covering(c, end_date, min_dates=window + 1),
                                end_date, window) for c in codes}


def _pool_members(db: Any, day: str, dataset_id: str,
                  sealed: set[str]) -> dict[str, dict[str, str | None]]:
    """`day` 封板成员按板块归属（韭研 final ∩ THS 池；与 day_leader_rows 同口径）。"""
    pdoc = db["jiuyan_action"].find_one({"_id": f"{day}:final"}, {"fields": 1}) or {}
    members: dict[str, dict[str, str | None]] = {}
    for field in pdoc.get("fields") or []:
        bname = str(field.get("name") or "")
        for st in field.get("stocks") or []:
            c6 = str(st.get("code") or "")[-6:]
            if c6 in sealed:
                members.setdefault(bname, {})[c6] = st.get("name")
    return members


def collect_materials(db: Any, date: str, dataset_id: str,
                      gain_fetcher=None, day_change_fetcher=None,
                      bars_fetcher=None) -> dict[str, Any]:
    """单源取齐 build_leader_wzs 原料（不新增采集，全部既有链）。

    bars_fetcher(code, date)→bars：缺省 bars_covering 阶梯式；深历史回填应传
    单档大 offset 取数（避免逐档重试，每档一次 TDX 连接）。"""
    bar_fn = bars_fetcher or (lambda c, d: bars_covering(c, d))
    pool_days = trading_dates_before(db, date, 3, dataset_id)
    pool_members: dict[str, dict[str, dict[str, str | None]]] = {}
    streaks_by_day: dict[str, dict[str, int]] = {}
    codes: set[str] = set()
    gaps: list[str] = []
    for s in pool_days:
        sealed, _info, _meta = sealed_and_info(db, s, dataset_id)
        if sealed is None:
            # 池回溯日 THS 缺失：该日封板不可二分 → 空成员+披露（不伪 0，不中断）
            pool_members[s] = {}
            streaks_by_day[s] = {}
            gaps.append(f"{s} THS 池缺失，该回溯日成员不可考")
            continue
        pool_members[s] = _pool_members(db, s, dataset_id, sealed)
        streaks_by_day[s] = jiuyan_streak_map(db, s, dataset_id) or {}
        codes |= {c for m in pool_members[s].values() for c in m}
    today_sealed, _info, _tmeta = sealed_and_info(db, date, dataset_id)
    streaks_today = jiuyan_streak_map(db, date, dataset_id) or {}
    leader_rows, leader_meta = day_leader_rows(
        db, date, dataset_id,
        prev_date=pool_days[-1] if pool_days else None,
        space_mode=True, pool_dates=pool_days,
        gain_fetcher=gain_fetcher, day_change_fetcher=day_change_fetcher)
    if gaps:
        leader_meta = dict(leader_meta or {})
        leader_meta.setdefault("dataGaps", [])
        leader_meta["dataGaps"] = list(leader_meta["dataGaps"]) + gaps
    bars_by_code = {c: bar_fn(c, date) for c in sorted(codes)}
    return {"pool_days": pool_days, "pool_members": pool_members,
            "streaks_by_day": streaks_by_day, "streaks_today": streaks_today,
            "today_sealed": today_sealed, "leader_rows": leader_rows,
            "leader_meta": leader_meta, "bars_by_code": bars_by_code}


def build_and_save_leader_wzs(db: Any, date: str,
                              dataset_id: str = DEFAULT_DATASET_ID, *,
                              gain_fetcher=None, day_change_fetcher=None,
                              bars_fetcher=None,
                              force: bool = False) -> dict[str, Any]:
    """计算 + upsert 单集合文档（每交易日一文档，重跑幂等）；返回落库文档。

    降级（THS 池缺失等）也落痕：status="degraded" + reason（fail-visible，
    照 sector_nodes P2-2 语义，不静默跳过）。
    """
    mat = collect_materials(db, date, dataset_id,
                            gain_fetcher=gain_fetcher,
                            day_change_fetcher=day_change_fetcher,
                            bars_fetcher=bars_fetcher)
    rows, events, meta = build_leader_wzs(
        date, pool_days=mat["pool_days"], today_sealed=mat["today_sealed"],
        pool_members=mat["pool_members"], streaks_by_day=mat["streaks_by_day"],
        streaks_today=mat["streaks_today"], leader_rows=mat["leader_rows"],
        bars_by_code=mat["bars_by_code"], segment_fn=segment_of)
    if meta.get("status") != "degraded" and mat.get("leader_meta"):
        meta["leaderMeta"] = mat["leader_meta"]
    doc = {"_id": date, "tradingDate": date, "status": meta.get("status"),
           "poolRows": rows, "events": events, "meta": meta,
           "generatedAt": datetime.now(timezone.utc).isoformat()}
    if not force:
        old = db[COLLECTION].find_one({"_id": date}, {"generatedAt": 1})
        if old:
            doc["generatedAt"] = old.get("generatedAt")   # 重跑不改时间戳（幂等可对账）
    db[COLLECTION].replace_one({"_id": date}, doc, upsert=True)
    return doc


def window_changes_for(code: str, pool_day: str, date: str) -> list[dict]:
    """盯盘行用：窗内逐日涨跌幅（S<d<T；缺日如实缺失，不插值）。"""
    bars = bars_covering(code, date)
    if not bars:
        return []
    from backend.analysis.hotlist.leader_wzs import _pct_from_bars
    return [{"date": d, "pct": _pct_from_bars(bars, d)}
            for d in sorted(bars) if pool_day < d < date]
