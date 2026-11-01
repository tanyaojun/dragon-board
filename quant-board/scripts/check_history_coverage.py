# -*- coding: utf-8 -*-
"""历史覆盖诊断：韭研最近 N 交易日板块 → KPL 名录全集 匹配覆盖率（2026-11-01）。

背景（用户拍板第 3 轮）：韭研→KPL 当日覆盖已清零，目标=历史 108 交易日
90%+ 匹配率。逐日真调 KPL 上游不可行（实测 Type=1+Date 仅支持最近交易日，
更早日期返空）且违反上呼纪律——匹配判定是**名字存在性**，与日期无关，
故 KPL 侧用最近交易日名录全集（一级 241 + 二级 sons）作全集近似。

用法（venv python，纯本地 Mongo 读 + 1 次 KPL 上呼走 TTL 缓存）：
    .venv/Scripts/python.exe scripts/check_history_coverage.py [--days 108] [--json OUT]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.data.repositories import repository_factory  # noqa: E402
from backend.operations.sector_name_check import check_sector_names  # noqa: E402
from backend.operations.jiuyan_store import list_action_dates  # noqa: E402
from backend.services import kpl_ranking_service  # noqa: E402


def build_universe() -> tuple[list[str], str]:
    """KPL 名录全集近似：最近交易日排行（一级 + 二级 sons）+ 指认存在白名单。"""
    import datetime
    d = datetime.date.today().isoformat()
    rk = None
    for i in range(8):
        try:
            r = kpl_ranking_service.get_sector_ranking(d)
        except Exception:
            r = None
        if (r or {}).get("items"):
            rk = r
            break
        d = (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()
    if rk is None:
        raise SystemExit("KPL 名录不可得（最近 7 天均空）")
    names = [it["name"] for it in rk["items"]]
    sons = rk.get("sons") or {}
    for rows in sons.values():
        for row in rows or []:
            n = str((row or {}).get("name") or "").strip()
            if n:
                names.append(n)
    # 用户指认存在白名单（2026-11-01 领域专家逐条确认）：KPL 完整名录大于当日
    # 活跃排行（排行只列当日有封板事件的板块），冷门/事件板块不在 241 内但真实
    # 存在；单一事实源 = sector_name_check.KPL_EXTRA_BOARDS（当日读口同源共用）
    from backend.operations.sector_name_check import KPL_EXTRA_BOARDS
    names += [b for b in KPL_EXTRA_BOARDS if b not in names]
    return names, rk.get("date") or d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=108)
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    names, kpl_date = build_universe()
    print(f"KPL 名录全集近似（档日 {kpl_date}）：{len(names)} 名（一级排行+二级 sons+指认白名单）")

    db = repository_factory.get_runtime_mongodb_database()
    dates = [r["date"] for r in list_action_dates(db)][-args.days:]
    if not dates:
        raise SystemExit("韭研档为空（jiuyan_action 无档），无法诊断")
    print(f"韭研档：{len(dates)} 个交易日（{dates[0]} ~ {dates[-1]}）")

    total = 0
    matched = 0
    way_counter: Counter = Counter()
    board_counter: Counter = Counter()      # 各板块出现次数
    unmatched_counter: Counter = Counter()  # 未匹配板块出现次数
    way_by_board: dict[str, str] = {}
    per_day = []
    for d in dates:
        out = check_sector_names(db, d, kpl_names=names)
        if not out.get("ok"):
            per_day.append({"date": d, "ok": False, "reason": out.get("reason")})
            continue
        n_rows = len(out["rows"])
        n_hit = sum(1 for r in out["rows"] if r["matched"])
        total += n_rows
        matched += n_hit
        for r in out["rows"]:
            b = r["board"]
            board_counter[b] += 1
            way_counter[r["way"]] += 1
            if r["matched"]:
                way_by_board.setdefault(b, r["way"])
            else:
                unmatched_counter[b] += 1
        per_day.append({"date": d, "ok": True, "boards": n_rows, "matched": n_hit})

    print(f"\n历史覆盖（韭研→KPL 名录全集口径）：")
    print(f"  板块总出现 {total} | 匹配 {matched} | 覆盖率 "
          f"{matched / total * 100:.1f}%" if total else "无板块行")
    print(f"  匹配方式分布：{dict(way_counter)}")
    print(f"  行政桶（其他/ST板块 等）不进统计；公告走语义桥参与匹配")
    if unmatched_counter:
        print(f"\n未匹配板块（按出现频次，维护候选优先级）：")
        for b, c in unmatched_counter.most_common(30):
            print(f"  {b}: {c} 天")
    else:
        print("\n未匹配：0（全部覆盖）")

    if args.json_out:
        out_dir = os.path.dirname(args.json_out)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"kplDate": kpl_date, "universeN": len(names),
                       "days": len(dates), "dateRange": [dates[0], dates[-1]],
                       "total": total, "matched": matched,
                       "coverage": round(matched / total, 4) if total else None,
                       "ways": dict(way_counter),
                       "unmatched": dict(unmatched_counter),
                       "unmatchedBoardDays": unmatched_counter.most_common(),
                       "perDay": per_day}, f, ensure_ascii=False, indent=2)
        print(f"\nJSON 归档：{args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
