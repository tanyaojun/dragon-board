# -*- coding: utf-8 -*-
"""竞价试盘 raw 全量日档回填（2026-11-14 用户裁决：auction_trial_raw，60 日窗口）。

数据源：WzsLinker 档案缓存读（历史日档案不可变、refresh 对过去日无效——单发/日，
不走 fetch_auction_trial 的陈旧补拉逻辑，零 refresh 发送）。写库：生产集合
auction_trial_raw ∈ dragon_board_quant（persist_trial_raw 同口径：仅 state=ok 落，
空档也是事实；fallback/api_error 跳过并计数，不覆盖已有好档）。

频控预算（红线 9 台账）：历史回补宽预算档 = 1 发/日 × 2s 间隔、无重试循环、
失败结构化记录后继续下一日（断点续跑：已有档缺省跳过，--force 覆盖）。

用法（默认 dry 零外呼，只列窗口计划）：
  ./.venv/Scripts/python.exe scripts/backfill_auction_trial_raw.py
实弹（预算确认门）：
  ... --confirm-budget --days 60
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.repositories.repository_factory import (  # noqa: E402
    get_runtime_mongodb_database,
)
from backend.operations.auction_trial_fetch import (  # noqa: E402
    COLLECTION_TRIAL_RAW, TRIAL_HOST, _http_get_json, parse_trial_payload,
    persist_trial_raw,
)

REQUEST_INTERVAL_SECONDS = 2.0    # 红线 9：请求间隔下限（页面轮询节奏 60s 的保守档）


def process_date(db, date: str, *, force: bool = False) -> dict:
    """单日：取档 → 解析守卫 → 幂等落库。返回结构化结果（不抛）。"""
    if not force and db[COLLECTION_TRIAL_RAW].find_one({"_id": date}):
        return {"date": date, "state": "already_persisted", "skipped": True}
    try:
        data = _http_get_json(f"{TRIAL_HOST}?page=limit_up_bidding&date={date}")
    except Exception as exc:   # noqa: BLE001 — 单发不重试（红线 9），结构化记录
        return {"date": date, "state": f"http_error:{type(exc).__name__}", "skipped": True}
    result = parse_trial_payload(data, date)
    persist = persist_trial_raw(db, date, result)
    return {"date": date, "state": result["state"], "nRows": result.get("n_rows") or 0,
            "persisted": persist.get("persisted", False),
            "persistReason": persist.get("reason"),
            "savedAt": result.get("saved_at")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=60, help="回填窗口（交易日数，默认 60）")
    ap.add_argument("--to", dest="date_to", default=None, help="窗口末日（缺省=最近交易日）")
    ap.add_argument("--force", action="store_true", help="覆盖已有档重拉")
    ap.add_argument("--confirm-budget", action="store_true",
                    help="实弹确认（缺省 dry 只列计划零外呼）")
    args = ap.parse_args()

    db = get_runtime_mongodb_database()
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "_id": {"$regex": ":final$"}}, {"tradingDate": 1})
        if d.get("tradingDate")})
    if args.date_to:
        dates = [d for d in dates if d <= args.date_to]
    window = dates[-args.days:] if args.days > 0 else []
    if not window:
        print("no trading dates in window", file=sys.stderr)
        return 1
    existing = sum(1 for d in window if db[COLLECTION_TRIAL_RAW].find_one({"_id": d}))
    print(f"window {window[0]}..{window[-1]} ({len(window)} 交易日)，"
          f"已有档 {existing}，{'--force 覆盖' if args.force else '缺省跳过'}")
    if not args.confirm_budget:
        print("dry：零外呼，加 --confirm-budget 实弹（预算 ≤1 发/日 × 2s 间隔）")
        return 0
    stats: Counter = Counter()
    for i, d in enumerate(window, 1):
        r = process_date(db, d, force=args.force)
        stats["already" if r.get("skipped") else
              ("ok" if r.get("persisted") else "skip_fail")] += 1
        print(f"[{i}/{len(window)}] {d} {r.get('state')} nRows={r.get('nRows')} "
              f"persisted={r.get('persisted')}"
              + (f" ({r.get('persistReason')})" if r.get("persistReason") else ""))
        if i < len(window) and not r.get("skipped"):
            time.sleep(REQUEST_INTERVAL_SECONDS)
    print(f"汇总：新落 {stats['ok']}，已有跳过 {stats['already']}，"
          f"失败/跳过 {stats['skip_fail']}")
    return 0 if stats["skip_fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
