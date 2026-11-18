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

from backend.data.repositories.repository_factory import get_runtime_mongodb_database  # noqa: E402
from backend.analysis.hotlist.leader_wzs import build_leader_wzs
from backend.analysis.hotlist.theme_leader_ammo import segment_of
from backend.operations.jev_label_jiuyan import (jiuyan_streak_map,
                                                 trading_dates_before)
from backend.operations.theme_leader_baseline import (DEFAULT_DATASET_ID,
                                                      day_leader_rows,
                                                      sealed_and_info)
from backend.operations.tdx_daily_bars import (bars_covering,
                                               covering_day_change_fetcher,
                                               fetch_daily_bars,
                                               fetch_gains10,
                                               gain10_from_bars)

COLLECTION = "hotlist_jev_leader_wzs"

# 覆盖式日线单源已下沉 tdx_daily_bars（2026-11-16）：bars_covering /
# covering_day_change_fetcher 改为纯 re-export，消费方 theme_cycle / market_cycle
# 既有导入路径不变；此处不再保留第二套实现。


# 深历史回填用 gain_fetcher（覆盖式）：fetch_gains10 已升级为覆盖式取数（2026-11-16），
# 同签名直接 re-export，theme_cycle / market_cycle 注入点不变。
covering_gain_fetcher = fetch_gains10


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
    # v5.1 三链合一锚定（2026-11-09 用户裁决）：有当日节点档（v5）时龙一行按档过滤
    # （单龙口径全站一致）；无档（深历史回填）保持原推导并如实披露未锚定
    from backend.operations.sector_nodes import ledger_leaders, anchor_rows_to_ledger
    try:
        _ledger = ledger_leaders(db, date)
    except Exception as exc:
        _ledger = None   # 深历史回填/mock 无节点集合：未锚定，不阻断（异常类型留痕）
        leader_meta = dict(leader_meta or {})
        leader_meta["ledgerAnchor"] = {"anchored": False, "error": type(exc).__name__}
    leader_rows, anchor_info = anchor_rows_to_ledger(leader_rows, _ledger)
    # 无条件落痕（P2-7 评审）：anchored/未锚定/剔除/漂移全披露，与 theme_cycle 同语义
    leader_meta = dict(leader_meta or {})
    leader_meta["ledgerAnchor"] = anchor_info
    if gaps:
        leader_meta = dict(leader_meta or {})
        leader_meta.setdefault("dataGaps", [])
        leader_meta["dataGaps"] = list(leader_meta["dataGaps"]) + gaps
    bars_by_code = {c: bar_fn(c, date) for c in sorted(codes)}
    # 2026-11-18 天普案遗留：成员三态单源 day_status_of（停牌≠未封板）。仅池权威
    # 在场日计算：sealed 分支权威，bars 只辨停牌/断板/数据洞，无需除权参考
    # （adj=None 零外呼）；池缺失日保持旧二分＋degraded 留痕（fail-visible）。
    member_states: dict[str, str] | None = None
    if today_sealed is not None:
        from backend.operations.jev_label_jiuyan import day_status_of

        def _bars_list(c: str) -> list[dict] | None:
            b = bars_by_code.get(c)
            if not b:
                return None
            return [{**v, "date": d} for d, v in sorted(b.items())]

        member_states = {
            c: day_status_of(c, date, sealed=today_sealed, touch=set(_info or {}),
                             bars=_bars_list(c), adj=None)
            for c in sorted(codes)}
    return {"pool_days": pool_days, "pool_members": pool_members,
            "streaks_by_day": streaks_by_day, "streaks_today": streaks_today,
            "today_sealed": today_sealed, "leader_rows": leader_rows,
            "leader_meta": leader_meta, "bars_by_code": bars_by_code,
            "member_states": member_states}


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
        bars_by_code=mat["bars_by_code"], segment_fn=segment_of,
        member_states=mat.get("member_states"))
    if meta.get("status") != "degraded" and mat.get("leader_meta"):
        meta["leaderMeta"] = mat["leader_meta"]
    doc = {"_id": date, "tradingDate": date, "status": meta.get("status"),
           "poolRows": rows, "events": events, "meta": meta,
           "generatedAt": datetime.now(timezone.utc).isoformat()}
    old = None if force else db[COLLECTION].find_one(
        {"_id": date}, {"generatedAt": 1, "poolRows": 1, "events": 1, "meta": 1})
    if old:
        # 重跑保留首次生成时间（幂等可对账）；内容变化时补 recomputedAt（review P2：
        # 避免改了数据也对账不出「何时重算」）
        doc["generatedAt"] = old.get("generatedAt")
        changed = ([(r.get("code"), r.get("windowK")) for r in rows]
                   != [(r.get("code"), r.get("windowK")) for r in old.get("poolRows") or []]
                   or [(e.get("type"), e.get("code")) for e in events]
                   != [(e.get("type"), e.get("code")) for e in old.get("events") or []])
        if changed:
            doc["recomputedAt"] = datetime.now(timezone.utc).isoformat()
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


if __name__ == "__main__":   # pragma: no cover — CLI（schedule leaderWzs advisory 步）
    import argparse
    import json as _json
    import sys as _sys

    _ap = argparse.ArgumentParser(description="龙头弱转强单日落库（盘后口径）")
    _ap.add_argument("--day", help="YYYY-MM-DD（缺省=最近韭研 final 日）")
    _args = _ap.parse_args()
    _db = get_runtime_mongodb_database()
    _day = _args.day
    if not _day:
        _docs = _db["jiuyan_action"].find({"_id": {"$regex": ":final$"}},
                                          {"tradingDate": 1})
        _days = sorted(str(d["tradingDate"]) for d in _docs if d.get("tradingDate"))
        _day = _days[-1] if _days else None
    if not _day:
        print(_json.dumps({"ok": False, "error": "无韭研 final，且未给 --day"}))
        _sys.exit(1)
    _doc = build_and_save_leader_wzs(_db, _day)
    print(_json.dumps({"ok": True, "date": _day, "status": _doc.get("status"),
                       "poolRows": len(_doc.get("poolRows") or []),
                       "events": len(_doc.get("events") or [])},
                      ensure_ascii=False))
