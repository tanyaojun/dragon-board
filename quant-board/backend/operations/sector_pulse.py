# -*- coding: utf-8 -*-
"""板块节点 V2c 盘中红盘提示（sector-pulse，2026-10-25）：昨日封窗 N10 + 批量实时报价。

预登记：docs/hotlist-jev/sector-nodes-v2c-intraday-preregistration.md（四项用户拍板：
成员=昨日封窗 N10 冻结 / 8000 按需读口 / 弱转强候选优先 / 每日 15:00 帧落库）。
证据基线：sector-agg-replay-study-20261024.md §三（真 N10：早盘分离 +8~13pp 温和、
午后 +18~20pp 强；组内离散大 → 提示列不进节点判定，预登记 §六 冻结）。

- 成员口径：昨日（最近上一交易日）封窗 N10 并集——以昨日为 target 取
  「昨日+最近 9 个池 ok 日」，盘中不变；今日新涨停股不在内（前端注记披露，
  16:20 正式判档链归位）。窗口池直查 `day_leader_rows`（**不走
  `_window_pool_of`**：其 `_POOL_CACHE` 无版本键，审计 2026-10-24 P3 约束
  长驻进程禁用，本模块常驻 8000 读口）。
- 报价：mootdx `client.quotes` 批量（80/批，price/last_close 现成）；客户端复用
  `_tdx_daily_client`（内含 SetupCmd3 握手补丁）；60s 进程内缓存共享上游取数。
- fail-visible：报价不可考（全节点负缓存 / quotes 全批次异常）→ pulse=None+原因；
  成员缺报价计 missingN；全缺统计值 None 不伪 0。
- 15:00 帧：交易日 ≥15:05 首次请求幂等 upsert `hotlist_jev_sector_pulse`
  （`_id={date}:PULSE`），攒前向校准样本；非交易日 / 报价不可考不落帧。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, time
from typing import Any, Callable

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.operations.jev_label_jiuyan import (
    _POSITION_LOCK,
    _tdx_daily_client,
    trading_dates_before,
)
from backend.operations.theme_leader_baseline import day_leader_rows

PULSE_VERSION = "2026-10-25a"
COLLECTION_PULSE = "hotlist_jev_sector_pulse"
COLLECTION_NODES = "hotlist_jev_sector_nodes"
_QUOTES_BATCH = 80          # tdxpy get_security_quotes 单批上限
_CACHE_TTL_SECONDS = 60
_WEAK_CANDIDATE_NODES = {"weakening", "collapse"}

# 60s 读口缓存 {date: (ts, payload)}——多端轮询共享一次上游取数；键含日期，
# 历史日走 stored 帧不进本缓存。窗口池不走 `_POOL_CACHE`（无版本键，审计
# 2026-10-24 P3：长驻进程禁用），本模块每次直查 `day_leader_rows`。
_PULSE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _day_pool_direct(db: Any, date: str, dataset_id: str
                     ) -> dict[str, set[str]] | None:
    """单日 {板块: 封板 code 集}，直查不缓存（与 `_window_pool_of` 同语义的
    无缓存版：THS 池缺失 / final 缺失 → None 不进窗口）。"""
    rows, meta = day_leader_rows(db, date, dataset_id)
    if rows is None or not meta.get("jiuyanFinalFound", True):
        return None
    pool: dict[str, set[str]] = {}
    for r in rows:
        b = str(r.get("board") or "")
        if b:
            pool[b] = {str(c) for c in (r.get("boardCodes") or [])}
    return pool


def _frozen_union(db: Any, today: str, dataset_id: str = DEFAULT_DATASET_ID
                  ) -> tuple[dict[str, set[str]], str | None]:
    """昨日封窗 N10 成员并集：{board: codes} + 根因（昨日交易日不存在时 None）。

    以昨日为 target 取「昨日+最近 9 个池 ok 日」（trading_dates_before 升序
    返回旧→新，须 reversed——同 operations._agg_rows_compute 取窗教训）。
    """
    prevs = trading_dates_before(db, today, 1, dataset_id=dataset_id)
    if not prevs:
        return {}, "无昨日交易日，封窗成员不可考"
    prev = prevs[-1]
    candidates = [prev] + list(reversed(
        trading_dates_before(db, prev, 15, dataset_id=dataset_id)))
    pools: list[tuple[str, dict[str, set[str]]]] = []
    for d in candidates:
        pool = _day_pool_direct(db, d, dataset_id)
        if pool is not None:
            pools.append((d, pool))
        if len(pools) >= 10:
            break
    members: dict[str, set[str]] = {}
    for _d, pool in pools:
        for board, codes in pool.items():
            members.setdefault(board, set()).update(codes)
    return members, None


def _prev_nodes(db: Any, today: str, dataset_id: str = DEFAULT_DATASET_ID
                ) -> dict[str, str]:
    """昨日节点（sector-nodes 文档读口）；昨日文档缺失 → 空 dict（候选层缺位如实降级）。"""
    prevs = trading_dates_before(db, today, 1, dataset_id=dataset_id)
    if not prevs:
        return {}
    doc = db[COLLECTION_NODES].find_one({"_id": f"{prevs[-1]}:SECTOR_NODES"},
                                        {"rows.node": 1, "rows.board": 1})
    if not doc:
        return {}
    return {str(r["board"]): str(r["node"]) for r in doc.get("rows") or []
            if r.get("board") and r.get("node")}


def _fetch_quotes(codes: set[str]) -> dict[str, tuple[float, float]] | None:
    """批量实时报价 {code: (price, last_close)}；不可考 → None。

    None 两种成因（调用方合并披露）：客户端不可用（全节点负缓存）/ 全批次
    quotes 异常且零成交（网络/主站断）。price/last_close ≤0（退市/无效/未开盘
    无昨收）不入表，调用方按缺报价披露；部分批次异常按缺报价披露不整段判死。
    """
    client = _tdx_daily_client()
    if client is None:
        return None
    ordered = sorted(codes)
    out: dict[str, tuple[float, float]] = {}
    batch_error = False
    for i in range(0, len(ordered), _QUOTES_BATCH):
        batch = ordered[i:i + _QUOTES_BATCH]
        try:
            with _POSITION_LOCK:
                df = client.quotes(symbol=batch)
        except Exception:
            batch_error = True
            continue
        if df is None or len(df) == 0:
            continue
        for _, r in df.iterrows():
            try:
                price, last_close = float(r["price"]), float(r["last_close"])
            except (KeyError, TypeError, ValueError):
                continue
            if price > 0 and last_close > 0:
                out[str(r["code"])] = (price, last_close)
    if not out and batch_error:
        return None
    return out


def _pulse_stats(quotes_map: dict[str, tuple[float, float]] | None,
                 codes: set[str]) -> dict[str, Any]:
    """单板块盘中统计（与回放研究 §三 同口径：price/last_close−1）。

    quotes_map=None → 整板块不可考（pulse 本体 None 由调用方置）；全成员缺报价
    → 统计值 None 不伪 0。红盘率=price>last_close 占比（收盘红盘率语义，
    非盘中绿转红——键名沿用落库 redRatio）。
    """
    pcts: list[float] = []
    for code in sorted(codes):
        q = (quotes_map or {}).get(code)
        if q is None:
            continue
        pcts.append((q[0] / q[1] - 1) * 100)
    quoted = len(pcts)
    stats: dict[str, Any] = {"memberN": len(codes), "quotedN": quoted,
                             "missingN": len(codes) - quoted}
    if quoted == 0:
        stats.update({"pctMean": None, "pctMedian": None, "redRatio": None})
        return stats
    ordered = sorted(pcts)
    stats["pctMean"] = round(sum(pcts) / quoted, 2)
    stats["pctMedian"] = round(ordered[quoted // 2] if quoted % 2
                               else (ordered[quoted // 2 - 1]
                                     + ordered[quoted // 2]) / 2, 2)
    stats["redRatio"] = round(sum(1 for p in pcts if p > 0) / quoted, 3)
    return stats


def _evidence_stage(now: datetime) -> str:
    """时点证据段（回放研究 §三：早盘 +8~13pp 温和 / 13:30 后 +18~20pp 强）。"""
    hm = now.strftime("%H:%M")
    if hm < "09:30":
        return "pre_open"       # 盘前报价=昨收，读数无意义
    if hm < "13:30":
        return "early"
    if hm < "15:00":
        return "strong"
    return "closed"


_EVIDENCE_CN = {"pre_open": "盘前（报价=昨收，读数无意义）",
                "early": "早盘（历史证据 +8~13pp，温和）",
                "strong": "午后（历史证据 +18~20pp，强）",
                "closed": "收盘读数（15:00 后）"}


def compute_pulse(db: Any, today: str, dataset_id: str = DEFAULT_DATASET_ID,
                  *, now: datetime | None = None,
                  quotes_fetcher: Callable[[set[str]],
                                           dict[str, tuple[float, float]] | None]
                  | None = None) -> dict[str, Any]:
    """盘中读数全量计算（routes 唯一入口；quotes_fetcher 注入供测试/重放）。

    候选层=昨日节点∈{转弱,退潮}（弱转强候选，置顶）；全量层=封窗 N10 全部板块。
    交易日 ≥15:05 幂等落 15:00 帧（预登记 §五=A 拍板）。
    非交易日当日读数=最近交易日收盘口径（报价停留在收盘价），证据段强制
    closed 并注记——不按钟表误标「早盘/盘前」（2026-10-25 用户验收反馈）。
    """
    now = now or datetime.now()
    stage = _evidence_stage(now)
    meta: dict[str, Any] = {"reason": None, "framesSaved": False}
    try:
        import datetime as _dt
        from backend.snapshot_collector.trading_calendar import is_trading_day_cached
        is_td, td_source = is_trading_day_cached(_dt.date.fromisoformat(today))
        if not is_td:
            stage = "closed"
            meta["tradingDayNote"] = f"今日非交易日（{td_source}），读数为最近交易日收盘口径"
    except Exception as exc:   # 判定不可用：按钟表分段 + 注记（fail-visible）
        meta["tradingDayNote"] = f"交易日判定不可用：{exc}"
    payload: dict[str, Any] = {
        "ok": True, "kind": "sector_pulse", "version": PULSE_VERSION,
        "date": today, "computedAt": now.isoformat(timespec="seconds"),
        "evidenceStage": stage,
        "candidates": [], "all": [],
        "meta": meta,
    }
    members, root = _frozen_union(db, today, dataset_id)
    if root:
        payload["meta"]["reason"] = root
        return payload
    if not members:
        payload["meta"]["reason"] = "昨日封窗无任何池 ok 日，成员集为空"
        return payload
    prev_nodes = _prev_nodes(db, today, dataset_id)
    fetch = quotes_fetcher or _fetch_quotes
    all_codes: set[str] = set()
    for codes in members.values():
        all_codes |= codes
    quotes_map = fetch(all_codes)
    hint_chip = False
    for board in sorted(members):
        codes = members[board]
        if quotes_map is None:
            pulse = None
        else:
            pulse = _pulse_stats(quotes_map, codes)
            if (pulse["pctMean"] is not None and pulse["pctMean"] > 0
                    and (pulse["redRatio"] or 0) >= 0.5):
                hint_chip = True
        entry: dict[str, Any] = {"board": board,
                                 "yesterdayNode": prev_nodes.get(board),
                                 "pulse": pulse}
        payload["all"].append(entry)
        if prev_nodes.get(board) in _WEAK_CANDIDATE_NODES:
            cand = dict(entry)
            cand["hint"] = bool(pulse and pulse.get("pctMean") is not None
                                and pulse["pctMean"] > 0
                                and (pulse.get("redRatio") or 0) >= 0.5)
            payload["candidates"].append(cand)
    if quotes_map is None:
        payload["meta"]["reason"] = ("TDX 盘中报价不可考（全节点不可用负缓存 / "
                                     "quotes 全批次异常且零成交）")
    payload["hintAny"] = hint_chip
    payload["evidenceStageCN"] = _EVIDENCE_CN[payload["evidenceStage"]]
    if quotes_map is None:
        # 报价不可考不落帧：全 None 帧进校准样本集是污染；TDX 恢复后同日再请求
        # 即可正常落帧（幂等同键）。
        payload["meta"]["frameSkip"] = "报价不可考，不落 15:00 帧（校准样本不入 null 帧）"
    else:
        _maybe_save_frame(db, payload, now)
    return payload


def _maybe_save_frame(db: Any, payload: dict[str, Any], now: datetime) -> None:
    """15:00 帧落库（预登记 §五=A）：交易日 ≥15:05 幂等 upsert；非交易日不落。

    收盘后报价停留在收盘价（TDX 行为），computedAt 如实记录取数时刻。
    写库失败不抛（读口展示数据不因次要写库连坐降级），frameSkip 如实披露。
    """
    if payload["evidenceStage"] != "closed":
        return
    if now.time() < time(15, 5):
        payload["meta"]["frameSkip"] = "15:05 前不落帧（预登记 §五）"
        return
    try:
        from backend.snapshot_collector.trading_calendar import is_trading_day_cached
        import datetime as _dt
        is_td, td_source = is_trading_day_cached(
            _dt.date.fromisoformat(payload["date"]))
        if not is_td:
            payload["meta"]["framesSaved"] = False
            payload["meta"]["frameSkip"] = f"非交易日（{td_source}）不落帧"
            return
    except Exception as exc:
        payload["meta"]["frameSkip"] = f"交易日判定不可用：{exc}"
        return
    frame = {k: payload[k] for k in ("kind", "version", "date", "computedAt",
                                     "evidenceStage", "candidates", "all",
                                     "hintAny", "meta") if k in payload}
    frame["_id"] = f"{payload['date']}:PULSE"
    try:
        db[COLLECTION_PULSE].replace_one({"_id": frame["_id"]}, frame, upsert=True)
    except Exception as exc:
        payload["meta"]["framesSaved"] = False
        payload["meta"]["frameSkip"] = f"帧写入失败：{exc}"
        return
    payload["meta"]["framesSaved"] = True


def get_pulse_cached(db: Any, today: str, dataset_id: str = DEFAULT_DATASET_ID,
                     *, now: datetime | None = None) -> dict[str, Any]:
    """60s 缓存壳（routes 调用）：同日 60s 内共享 payload，过期重算。"""
    now = now or datetime.now()
    hit = _PULSE_CACHE.get(today)
    if hit and now.timestamp() - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    payload = compute_pulse(db, today, dataset_id, now=now)
    _PULSE_CACHE[today] = (now.timestamp(), payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    """CLI 冒烟/重放：--day 缺省=今日；历史日只读 stored 帧。"""
    import argparse
    ap = argparse.ArgumentParser(description="V2c 盘中红盘提示（零 token）")
    ap.add_argument("--day", help="目标日（缺省=今天）；历史日读 stored 帧")
    args = ap.parse_args(argv)
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    today = datetime.now().strftime("%Y-%m-%d")
    day = args.day or today
    if day != today:
        frame = db[COLLECTION_PULSE].find_one({"_id": f"{day}:PULSE"})
        print(json.dumps({"ok": True, "source": "stored", "doc": frame},
                         ensure_ascii=False, default=str))
        return 0
    print(json.dumps(get_pulse_cached(db, day), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
