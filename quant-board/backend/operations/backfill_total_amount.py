# -*- coding: utf-8 -*-
"""两市成交额历史回填（TDX 综指 K 线，2026-10-02 用户裁决）。

背景：5-9 月历史帧 indices 无 totalAmount（09-30 才接线），v1 槽文档 evidenceRaw.totalAmount.amount
全 None → 锚的量能坐标（amountYi）死线。数据源=TDX 指数 K 线（上证综指 999999 + 深证综指 399106，
amount=全市场股票成交额元；9/30 沪 6794 亿 vs 上交所官方 6800.23 亿差 0.09%，口径对齐生产
sina realtime 指数口径）。服务器=python-bridge/tdx_hosts.json 81 节点池逐个探测。

写库目标=v1 15:00 槽文档 evidenceRaw.totalAmount.amount（+provenance），不动 vsSamePct/yesterdaySame
（派生字段保持 None，fail-visible），不动 snapshot_frames。幂等：amount 已有效即跳过。

用法（Git Bash）：
  cd quant-board
  ./.venv/Scripts/python.exe -m backend.operations.backfill_total_amount [--apply]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

HOSTS_PATH = Path(r"D:\dragon-board\python-bridge\tdx_hosts.json")
SOURCE = "tdx_index_kline_backfill"


def fetch_amount_map() -> dict[str, float]:
    """TDX 综指日线 → {YYYY-MM-DD: 两市合计成交额元}；多节点探测直至可用。"""
    from mootdx.quotes import Quotes

    pool = json.loads(HOSTS_PATH.read_text(encoding="utf-8"))["candidates"]
    last_err: Exception | None = None
    for h in pool:
        ip, port = h.get("ip"), int(h.get("port") or 7709)
        try:
            client = Quotes.factory(market="std", server=(ip, port), timeout=6, bestip=False)
            sh = client.index_bars(symbol="999999", frequency=9, start=0, offset=150)
            sz = client.index_bars(symbol="399106", frequency=9, start=0, offset=150)
            if len(sh) == 0 or len(sz) == 0:
                last_err = RuntimeError(f"{ip} 空 K 线")
                continue

            def to_map(df) -> dict[str, float]:
                return {f"{int(r['year']):04d}-{int(r['month']):02d}-{int(r['day']):02d}": float(r["amount"])
                        for _, r in df.iterrows()}

            m1, m2 = to_map(sh), to_map(sz)
            dates = sorted(set(m1) & set(m2))
            if not dates:
                last_err = RuntimeError(f"{ip} 无交集日期")
                continue
            return {d: m1[d] + m2[d] for d in dates}
        except Exception as exc:  # 单节点失败换下一个
            last_err = exc
    raise RuntimeError(f"全部 TDX 节点不可用: {last_err}")


def main():
    parser = argparse.ArgumentParser(description="两市成交额历史回填（TDX 综指口径）")
    parser.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    amounts = fetch_amount_map()
    print(f"TDX 综指成交额 {min(amounts)} → {max(amounts)}，{len(amounts)} 交易日")

    docs = list(db["hotlist_jev_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "kind": "slot",
         "slotTime": "15:00"}, {"tradingDate": 1, "evidenceRaw.totalAmount": 1}))
    actions, healthy, nomap = [], [], []
    for doc in docs:
        date = str(doc.get("tradingDate"))
        total = ((doc.get("evidenceRaw") or {}).get("totalAmount") or {}).get("amount")
        if isinstance(total, (int, float)) and total > 0:
            healthy.append(date)
            continue
        if date not in amounts:
            nomap.append(date)
            continue
        actions.append({"docId": doc["_id"], "date": date, "amount": amounts[date]})

    from collections import Counter
    by_month = Counter(a["date"][:7] for a in actions)
    print(f"== 成交额回填计划（{'APPLY' if args.apply else 'DRY-RUN'}）==")
    for a in sorted(actions, key=lambda x: x["date"]):
        print(f"[回填] {a['date']}: 两市 {round(a['amount'] / 1e8, 1)} 亿")
    print(f"[跳过] 已有值 {len(healthy)} 个；[未覆盖] {len(nomap)} 个: {nomap or '无'}")
    print(f"按月: {dict(sorted(by_month.items()))}")
    if args.apply:
        now = time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        n = 0
        for a in actions:
            db["hotlist_jev_sentiment"].update_one(
                {"_id": a["docId"]},
                {"$set": {"evidenceRaw.totalAmount.amount": a["amount"],
                          "evidenceRaw.totalAmount.source": SOURCE,
                          "evidenceRaw.totalAmount.backfilledAt": now}})
            n += 1
        print(f"已写库 {n} 文档（evidenceRaw.totalAmount.amount，source={SOURCE}）")
    else:
        print("dry-run 未写库；确认后加 --apply 执行")


if __name__ == "__main__":
    main()
