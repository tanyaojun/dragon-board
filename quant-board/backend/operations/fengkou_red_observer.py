# -*- coding: utf-8 -*-
"""最强风口红名观察采集器（2026-11-15 用户裁决「先观察再定」，选项 C）。

背景：KPL 最强风口个股强度榜 name_red 标志语义未确认——2026-11-15 实证排除
「涨停 / 昨日涨停 / 近期涨停基因 / 强度排名」（思美传媒 -1.77% 红、中国电影
+10.00% 涨停不红、儒意/光线近三日零涨停记录）；11-13 全天红名 100% 影视传媒系，
疑「当日最强风口板块成分」标记，待 ≥3 交易日观察坐实。

定位：**纯观察采集，不改 vA3 选龙合同**——不进竞价龙头锚人群、不烧 jev、不改
打标链选样（预登记 fengkou-red-name-observation-preregistration-20261115.md）。
盘后一次性拉当日日内多时点快照（Time=HHMM，服务端保留最近交易日日内快照），
落 `kpl_fengkou_red_obs` 日档；T+1 盘后回填红名股次日收盘涨幅（腾讯行情）。

时点合同：09:26~09:31 快照为空（实测，强度榜 09:32 起才有首行）→ 探针时点
0932/0935/1000/1100/1400 + 收盘终档（Time 空）。竞价龙头链 09:26 挂链时点
物理上拿不到红名股，这是「先观察再定」的第二个原因（第一是语义未确认）。

fail-visible（红线 4.0）：个别时点降级只记该时点结构化原因，doc 照写（部分
来源异常不丢已有记录）；全源无数据才不落 doc（返回采集失败）；T+1 回填缺股
记 missingNextDay 不伪造；昨日涨停池缺席记 prevPoolAvailable=false 不猜。

频控预算（红线 9）：观察器模块内无重试循环，每轮 6 发（探针时点各一发，Time 键
互异、30s TTL 缓存键天然区分）；T+1 回填复用 get_auction_snapshot_tencent
（进程内 30s TTL 缓存）；scheduler 层限次退避 ≤2 次/间隔 15 分钟，确定性降级日
（如 login_expired，失败响应不进缓存）第二次运行会重发探针，最坏 12 发/日。
pytest 纪律（红线 7）：get_fengkou 自带 _pytest_guard，
腾讯回填走 _next_day_pct 包装 + 本模块 pytest 护栏，测试全 mock。
"""
from __future__ import annotations

import datetime
import sys
from typing import Any
from zoneinfo import ZoneInfo

from backend.services import kpl_stock_fengkou as _fk

OBS_COLLECTION = "kpl_fengkou_red_obs"

# 日内演变采样时点（HHMM；""=收盘终档）。0932=首行最早实测时点。
_PROBE_TIMES: tuple[str, ...] = ("0932", "0935", "1000", "1100", "1400", "")

_RED_FIELDS = ("stock_id", "name", "change_pct", "strength", "trend_state",
               "main_net", "peak_time")


def _in_pytest() -> bool:
    return "pytest" in sys.modules


def _tencent_next_day_pct(codes: list[str]) -> dict[str, Any]:
    """T+1 收盘涨幅真实现（腾讯行情，≥15:10 调用即收盘口径）。

    pytest 护栏（红线 7）：测试进程禁真实外呼；生产经 _next_day_pct 包装调用，
    测试 monkeypatch _next_day_pct 即可隔离。
    """
    if _in_pytest():
        raise RuntimeError("pytest 禁止真实调用腾讯行情（红线 7）：请 monkeypatch _next_day_pct")
    from backend.services.kpl_ranking_service import get_auction_snapshot_tencent
    snap = get_auction_snapshot_tencent(codes)
    items = snap.get("items") or {}
    return {"ok": bool(snap.get("ok")), "fetchedAt": snap.get("fetchedAt"),
            "pct": {c: (items.get(c) or {}).get("bidding_pct") for c in codes},
            "missingCodes": list(snap.get("missing") or [])}


def _next_day_pct(codes: list[str]) -> dict[str, Any]:
    """可 mock 包装（默认真实现）；run/backfill 统一经此调用。"""
    return _tencent_next_day_pct(codes)


def _probe_once(time_hhmm: str) -> dict[str, Any]:
    """单时点快照 → 结构化探针记录（降级不抛，记 reason/error）。"""
    label = time_hhmm or "final"
    try:
        d = _fk.get_fengkou(time_hhmm=time_hhmm)
    except Exception as exc:  # noqa: BLE001 — 单时点失败不杀整轮（fail-visible）
        return {"time": label, "ok": False, "degraded": True,
                "reason": type(exc).__name__, "error": str(exc)[:200]}
    if not d.get("ok"):
        return {"time": label, "ok": False, "degraded": True,
                "reason": d.get("reason"), "error": d.get("error"),
                "loginExpired": d.get("login_expired")}
    reds = []
    for r in d.get("items") or []:
        if not r.get("name_red"):
            continue
        row = {k: r.get(k) for k in _RED_FIELDS}
        row["boards"] = list(r.get("boards") or [])
        reds.append(row)
    return {"time": label, "ok": True, "day": d.get("day"), "nRows": d.get("n_rows"),
            "redN": len(reds), "reds": reds}


def _prev_pool_names(db: Any, prev_date: str | None) -> set[str] | None:
    """T−1 涨停池成员名集合（池缺席→None，不猜）。"""
    if not prev_date:
        return None
    doc = db["kpl_daban_pool"].find_one({"date": prev_date}, {"items": 1})
    if not doc:
        return None
    return {str(x.get("name")) for x in (doc.get("items") or []) if x.get("name")}


def _next_trading_date(db: Any, date: str, today: str) -> str | None:
    """严格晚于 date 且 ≤ today 的最近快照交易日（无→None，次日未收盘）。"""
    from backend.operations.jev_label_jiuyan import trading_dates_before
    y, m, d = (int(x) for x in today.split("-"))
    tomorrow = (datetime.date(y, m, d) + datetime.timedelta(days=1)).isoformat()
    days = trading_dates_before(db, tomorrow, 30)
    after = [x for x in days if x > date]
    return after[0] if after else None


def _red_union(probes: list[dict], pool_prev: set[str] | None) -> list[dict]:
    """跨时点红名并集（code 键去重；首见/末见时点 + 出现次数 + T−1 在池标记）。"""
    by_code: dict[str, dict] = {}
    for p in probes:
        for r in p.get("reds") or []:
            cur = by_code.get(str(r.get("stock_id")))
            if cur is None:
                cur = {k: r.get(k) for k in ("stock_id", "name")}
                cur["firstTime"] = cur["lastTime"] = p["time"]
                cur["times"] = 0
                by_code[str(r.get("stock_id"))] = cur
            cur["lastTime"] = p["time"]
            cur["times"] += 1
            # 字段随最新一次出现刷新（日内 pct/strength 演变以末见为准）
            for k in ("change_pct", "strength", "trend_state", "main_net",
                      "peak_time", "boards"):
                if r.get(k) is not None:
                    cur[k] = r.get(k)
    out = []
    for cur in by_code.values():
        cur["inPrevPool"] = (None if pool_prev is None
                             else cur.get("name") in pool_prev)
        out.append(cur)
    out.sort(key=lambda x: -(x.get("times") or 0))
    return out


def run_fengkou_red_observation(date: str | None = None, *,
                                dry_run: bool = False, force: bool = False,
                                db: Any = None) -> dict[str, Any]:
    """当日盘后观察主流程：多时点快照 → 日档落库 + 历史 pending 日 T+1 回填。

    dry_run 全程零写入（探针照拉——只读，与既有 ops 语义一致）；幂等：已有当日
    doc 且未 force → skipped；全源无数据 → 不落 doc 返回采集失败（fail-visible）。
    """
    date = date or datetime.datetime.now(
        ZoneInfo("Asia/Shanghai")).date().isoformat()
    if db is None:
        from backend.data.repositories.repository_factory import (
            get_runtime_mongodb_database)
        db = get_runtime_mongodb_database()
    # 幂等先于探针（评审 P2）：已有 doc 且非 force 直接 skipped+backfill，
    # 不白打 6 发上游（scheduler 重试撞上「已写档」场景时零额外调用）
    if not dry_run and not force:
        existing = db[OBS_COLLECTION].find_one({"_id": date})
        if existing:
            return {"ok": True, "date": date, "skipped": "already_observed",
                    "redUnionN": existing.get("redUnionN"),
                    "backfill": _backfill_next_day(db, date)}
    probes = [_probe_once(tm) for tm in _PROBE_TIMES]
    ok_n = sum(1 for p in probes if p.get("ok"))
    if ok_n == 0:
        return {"ok": False, "degraded": True, "date": date,
                "errorCode": "fengkou_red_obs_all_degraded", "probes": probes}
    # 错档护栏（评审 P1）：探针只打实时端点（服务端仅保留最近交易日日内快照），
    # CLI --date 给历史日时载荷 day 会与入参不一致 → 不落 doc，防静默错档污染
    # 「先观察再定」的语义裁决材料（probeDays 结构化透出供人工核对）
    probe_days = {str(p.get("day") or "").replace("-", "")
                  for p in probes if p.get("ok")}
    if probe_days and date.replace("-", "") not in probe_days:
        return {"ok": False, "degraded": True, "date": date,
                "errorCode": "fengkou_red_obs_day_mismatch",
                "probeDays": sorted(probe_days), "probes": probes}
    # T−1 涨停池对照（红名≠涨停假说的直接证伪材料）
    from backend.operations.jev_label_jiuyan import trading_dates_before
    prev_days = trading_dates_before(db, date, 2)
    prev_date = prev_days[-1] if prev_days else None
    pool_prev = _prev_pool_names(db, prev_date)
    red_union = _red_union(probes, pool_prev)
    doc: dict[str, Any] = {
        "_id": date, "date": date,
        "observedAt": datetime.datetime.now().isoformat(timespec="seconds"),
        "prevDate": prev_date,
        "probes": probes,
        "redUnion": red_union,
        "redUnionN": len(red_union),
        "redFinalN": next((p["redN"] for p in probes if p["time"] == "final"), None),
        "quality": {"probeOkN": ok_n, "probeTotalN": len(_PROBE_TIMES),
                    "prevPoolAvailable": pool_prev is not None},
        "nextDay": None,
        "obsState": "pending_next_day",
    }
    backfill = None
    if not dry_run:
        db[OBS_COLLECTION].replace_one({"_id": date}, doc, upsert=True)
        backfill = _backfill_next_day(db, date)
    return {"ok": True, "date": date, "dryRun": dry_run or None,
            "redUnionN": len(red_union), "redFinalN": doc["redFinalN"],
            "quality": doc["quality"], "obsState": doc["obsState"],
            "backfill": backfill}


def _backfill_next_day(db: Any, today: str, *,
                       fetcher: Any = None) -> dict[str, Any]:
    """历史 pending 日 T+1 收盘涨幅回填（pending 少量自愈）。

    fetcher 缺省运行时解析 _next_day_pct（评审 P2：避免 def 时绑定原函数对象的
    stale-default 脚枪，monkeypatch 生效）。
    """
    if fetcher is None:
        fetcher = _next_day_pct
    results: list[dict[str, Any]] = []
    for doc in db[OBS_COLLECTION].find({"obsState": "pending_next_day",
                                        "date": {"$lt": today}}):
        date = str(doc.get("date"))
        next_td = _next_trading_date(db, date, today)
        if not next_td:
            results.append({"date": date, "skipped": "next_trading_day_not_closed"})
            continue
        codes = [str(r.get("stock_id")) for r in doc.get("redUnion") or []
                 if r.get("stock_id")]
        if not codes:
            # 空红名日也是事实（红名 0 只），直接结算不回填行情
            db[OBS_COLLECTION].update_one(
                {"_id": date},
                {"$set": {"obsState": "settled",
                          "nextDay": {"date": next_td, "pct": {}, "missing": [],
                                      "redN": 0}}})
            results.append({"date": date, "settled": True, "redN": 0})
            continue
        try:
            snap = fetcher(codes)
        except Exception as exc:  # noqa: BLE001 — 回填失败该日保持 pending（自愈）
            results.append({"date": date, "ok": False,
                            "error": f"{type(exc).__name__}: {exc}"[:200]})
            continue
        pct = snap.get("pct") or {}
        fetched = {c: pct.get(c) for c in codes}
        missing = [c for c, v in fetched.items() if v is None]
        # fail-visible：缺股记 missing 不伪造；可计算部分照常结算
        db[OBS_COLLECTION].update_one(
            {"_id": date},
            {"$set": {"obsState": "settled",
                      "nextDay": {"date": next_td, "pct": fetched,
                                  "missing": missing,
                                  "ok": snap.get("ok"),
                                  "fetchedAt": snap.get("fetchedAt")}}})
        results.append({"date": date, "settled": True, "nextDate": next_td,
                        "pctN": sum(1 for v in fetched.values() if v is not None),
                        "missingN": len(missing)})
    return {"days": results}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="最强风口红名观察采集（先观察再定）")
    ap.add_argument("--date", default=None, help="交易日 YYYY-MM-DD（缺省=今天）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="覆写已有当日 doc")
    args = ap.parse_args()
    out = run_fengkou_red_observation(args.date, dry_run=args.dry_run,
                                      force=args.force)
    print(f"→ {out.get('date')} redUnionN={out.get('redUnionN')} "
          f"obsState={out.get('obsState')} ok={out.get('ok')}"
          + (f" skipped={out.get('skipped')}" if out.get("skipped") else "")
          + (f" error={out.get('errorCode')}" if out.get("errorCode") else ""))
