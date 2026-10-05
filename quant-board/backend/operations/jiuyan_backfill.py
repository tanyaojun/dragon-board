# -*- coding: utf-8 -*-
"""韭研异动历史回填 CLI（设计 jiuyan-collector-design.md §4）。

用法（quant-board 目录，token 自动走认证链 jiuyan_auth.resolve_auth——浏览器铸造/登录/静态回退）：
  ./.venv/Scripts/python.exe -m backend.operations.jiuyan_backfill --month 2026-09 [--kind final] [--interval 2]
手动传参路径保留（ZCode 浏览器页内 globalThis.nR4xKp7mQa 现铸，需 JIUYAN_SESSION）：
  ./.venv/Scripts/python.exe -m backend.operations.jiuyan_backfill --month 2026-09 --token <hex> --timestamp <ISO>

流程：当月交易日（snapshot_stock_rows 实际日期）逐日 fetch_field → save_action_doc(kind)。
礼貌爬取：逐请求 --interval 秒间隔（默认 2）；若中途 errCode 110 立即中止并提示重试
（fail-visible，不重试不伪造；--skip-existing 可续跑）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jiuyan_store  # noqa: E402
from backend.operations.jiuyan_fetch import fetch_count, fetch_field  # noqa: E402


def month_trading_dates(db, month: str) -> list[str]:
    start, end = f"{month}-01", f"{month}-31"
    rows = db["snapshot_stock_rows"].find(
        {"type": "half_hour", "tradingDate": {"$gte": start, "$lte": end}},
        {"tradingDate": 1})
    return sorted({str(r["tradingDate"]) for r in rows if r.get("tradingDate")})


def resolve_backfill_auth(token_arg: str | None, timestamp_arg: str | None) -> dict:
    """--token/--timestamp 成对给出=手动路径（SESSION 仍取 env）；都缺省=走认证链自动解析。"""
    if bool(token_arg) != bool(timestamp_arg):
        return {"ok": False, "error": "--token 与 --timestamp 必须成对给出，或都不给走自动认证链"}
    if token_arg:
        session = os.environ.get("JIUYAN_SESSION") or ""
        if not session:
            return {"ok": False, "error": "手动 --token 路径缺 JIUYAN_SESSION（.env.local）"}
        return {"ok": True, "session": session, "token": token_arg, "timestamp": timestamp_arg,
                "source": "manual-backfill"}
    from backend.operations.jiuyan_auth import resolve_auth
    return resolve_auth()


def main() -> int:
    parser = argparse.ArgumentParser(description="韭研异动历史回填")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--token", default=None, help="可选：页内现铸 token（与 --timestamp 成对）")
    parser.add_argument("--timestamp", default=None, help="可选：铸 token 时的 timestamp 头（ISO Z）")
    parser.add_argument("--kind", default="final", choices=("final", "midday"))
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--skip-existing", action="store_true", help="跳过该 kind 已落库的日期")
    args = parser.parse_args()

    auth = resolve_backfill_auth(args.token, args.timestamp)
    if not auth.get("ok"):
        print(f"[err] {auth.get('error')}", file=sys.stderr)
        return 2
    session, token, timestamp = auth["session"], auth["token"], auth["timestamp"]
    print(f"[auth] source={auth['source']}")
    if auth["source"] == "manual-backfill" and not jiuyan_store.save_token(
            token=token, timestamp=timestamp, source="manual-backfill"):
        print("[backfill] 警告：Redis 不可用，token 未缓存（本批直接传参可用）")

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    dates = month_trading_dates(db, args.month)
    if not dates:
        print(f"[err] {args.month} 无交易日数据", file=sys.stderr)
        return 2
    print(f"[backfill] {args.month} {len(dates)} 个交易日，kind={args.kind}，间隔 {args.interval}s")
    if args.skip_existing:
        existing = {d["date"] for d in jiuyan_store.list_action_dates(db) if args.kind in d["kinds"]}
        dates = [d for d in dates if d not in existing]
        print(f"[backfill] skip-existing: 剩余 {len(dates)} 日")
        if not dates:
            print("FINAL: 全部已存在")
            return 0

    ok_n = fail_n = 0
    for i, date in enumerate(dates):
        result = fetch_field(date, session_cookie=session, token=token, timestamp=timestamp)
        if result.get("ok"):
            parsed = result["parsed"]
            count_probe = fetch_count_probe(db, date, session=session, token=token, timestamp=timestamp)
            jiuyan_store.save_action_doc(db, date=date, kind=args.kind, parsed=parsed,
                                         counts=count_probe, token_source=str(auth["source"]))
            ok_n += 1
            print(f"[{i + 1}/{len(dates)}] {date} ok 板块{len(parsed['fields'])} 个股{parsed['totalStocks']}"
                  f" 降级{len(parsed['degradedSources'])}")
        else:
            fail_n += 1
            print(f"[{i + 1}/{len(dates)}] {date} FAIL: {result.get('error')}")
            if "110" in str(result.get("error")) or "登录失效" in str(result.get("error")):
                print("[abort] token/会话失效——请重铸 token 后用 --skip-existing 续跑", file=sys.stderr)
                break
        if i < len(dates) - 1:
            time.sleep(args.interval)

    print("FINAL:", json.dumps({"ok": ok_n, "fail": fail_n}, ensure_ascii=False))
    return 0 if fail_n == 0 else 1


def fetch_count_probe(db, date: str, *, session: str, token: str, timestamp: str) -> dict:
    """顺手拉 counts 存档；失败不阻断（fail-visible 计入 quality）。"""
    try:
        probe = fetch_count(date, session_cookie=session, token=token, timestamp=timestamp)
        if probe.get("ok"):
            return {"all": probe.get("all"), "recommend": probe.get("recommend")}
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] count 探针失败: {str(exc)[:80]}", file=sys.stderr)
    return {}


if __name__ == "__main__":
    raise SystemExit(main())
