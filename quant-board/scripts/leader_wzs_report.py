# -*- coding: utf-8 -*-
"""龙头弱转强 P1 回填验收报告生成（v5 预登记 §八验收门）。

读 `hotlist_jev_leader_wzs` 全量文档，产出：
- 事件清单（leaderRebound / benchmarkAdvance）
- 反包/晋级事件次日溢价（TDX 日线 T→T+1 收盘环比；缺 bar 如实缺失）
- 观察池窗位分布（k=0/1/2）
- 与 sector_nodes 弱转强节点（wzs）的一致率/分歧清单
- 数据缺口（degraded 日、日线不可考计数）

数据源声明：TDX 日线**未复权**——次日溢价/窗内涨跌在除权除息日会失真
（连板/高位股为高送转高发群体），溢价表 |pct| 异常极端（如 <−25%）大概率
为除权失真而非真实亏幅，不伪装精确；复权口径待接入后统一重算。

用法：python scripts/leader_wzs_report.py [--out docs/hotlist-jev/leader-wzs-backfill-report-YYYYMMDD.md]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.tdx_daily_bars import fetch_daily_bars


def next_day_pct(code: str, date: str) -> float | None:
    bars = fetch_daily_bars(code, offset=260)
    if not bars or date not in bars:
        return None
    ds = sorted(bars)
    i = ds.index(date)
    if i + 1 >= len(ds):
        return None
    c0, c1 = bars[date].get("close"), bars[ds[i + 1]].get("close")
    if not c0 or not c1:
        return None
    return round((c1 / c0 - 1) * 100, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    db = get_runtime_mongodb_database()
    docs = list(db["hotlist_jev_leader_wzs"].find({}))
    docs.sort(key=lambda d: d["_id"])
    days_ok = [d for d in docs if d.get("status") == "ok"]
    days_deg = [d for d in docs if d.get("status") != "ok"]

    ev_rows: list[tuple[str, dict]] = []
    kdist: Counter[int] = Counter()
    for d in days_ok:
        for r in d.get("poolRows") or []:
            if r.get("windowK") is not None and not r.get("leaderSealedToday"):
                kdist[r["windowK"]] += 1
        for e in d.get("events") or []:
            ev_rows.append((d["_id"], e))

    lines: list[str] = []
    lines.append(f"# 龙头弱转强 P1 回填验收报告（{datetime.now().strftime('%Y-%m-%d')}）\n")
    lines.append(f"- 回填交易日：{len(docs)}（ok {len(days_ok)} / degraded {len(days_deg)}）")
    lines.append(f"- 覆盖区间：{docs[0]['_id']} .. {docs[-1]['_id']}" if docs else "- 无文档")
    lines.append(f"- 观察池行总数：{sum(len(d.get('poolRows') or []) for d in days_ok)}")
    lines.append(f"- 窗位分布（断板池行）：k0={kdist.get(0, 0)}（今日断板提示）/"
                 f"k1={kdist.get(1, 0)} / k2={kdist.get(2, 0)}（末窗）")
    ev_n = Counter(e["type"] for _, e in ev_rows)
    lines.append(f"- 事件：leaderRebound（人气股反包·龙一）={ev_n.get('leaderRebound', 0)}，"
                 f"benchmarkAdvance（标杆晋级）={ev_n.get('benchmarkAdvance', 0)}\n")

    lines.append("## 事件清单与次日溢价\n")
    lines.append("| 日期 | 类型 | 板块 | 轨 | 代码 | 名称 | 窗位/高度 | 次日% |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for d, e in ev_rows:
        code = str(e["code"])
        np_ = next_day_pct(code, d)
        extra = (f"k{e['windowK']}/h{e['height']}" if e["type"] == "leaderRebound"
                 else f"streak{e['streak']}")
        lines.append(f"| {d} | {e['type']} | {e['board']} | {e.get('segment') or '--'} "
                     f"| {code} | {e.get('name') or '--'} | {extra} "
                     f"| {'--' if np_ is None else (f'{np_:+.2f}（疑似除权失真）' if np_ <= -25 else f'{np_:+.2f}')} |")

    lines.append("\n## 与 sector_nodes 弱转强节点的一致率\n")
    node_by_date_board: dict[tuple[str, str], str] = {}
    for d in db["hotlist_jev_sector_nodes"].find({}, {"tradingDate": 1, "rows": 1}):
        did = str(d.get("tradingDate") or "")   # _id 为 "日期:SECTOR_NODES"，取 tradingDate
        for r in d.get("rows") or []:
            if isinstance(r, dict) and r.get("board"):
                node_by_date_board[(did, str(r["board"]))] = str(r.get("node"))
    hit = miss = 0
    divs: list[str] = []
    for d, e in ev_rows:
        node = node_by_date_board.get((d, str(e["board"])))
        if node is None:
            continue
        if node == "wzs":
            hit += 1
        else:
            miss += 1
            divs.append(f"{d} {e['board']} {e['type']} 节点={node}")
    lines.append(f"- 事件日板块节点可考 {hit + miss} 例：与 wzs 同日一致 {hit}，分歧 {miss}"
                 f"（分歧≠错误：节点是第5课板块迹象，事件是第3课新龙事实，P2 状态机联立裁决）")
    for x in divs[:20]:
        lines.append(f"  - {x}")

    lines.append("\n## 数据缺口（fail-visible）\n")
    if days_deg:
        lines.append(f"- degraded {len(days_deg)} 日：" +
                     "，".join(f"{d['_id']}({d['meta'].get('reason', '')[:40]})"
                               for d in days_deg[:15]) +
                     ("…" if len(days_deg) > 15 else ""))
    gap_n = sum(len((d.get("meta") or {}).get("dataGaps") or []) for d in days_ok)
    lh_n = sum(len((d.get("meta") or {}).get("lowHeightExcluded") or []) for d in days_ok)
    ld_n = sum(len((d.get("meta") or {}).get("limitDownExcluded") or []) for d in days_ok)
    lines.append(f"- 窗内数据缺口注记 {gap_n} 条；height<2 跟风剔除 {lh_n} 只次；"
                 f"断板日跌停剔除 {ld_n} 只次")

    out = args.out or f"docs/hotlist-jev/leader-wzs-backfill-report-{datetime.now().strftime('%Y%m%d')}.md"
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
