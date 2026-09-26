"""Phase 1：情绪相位 × 题材动量有效性验证 runner（设计文档 §6.1 Track 因子线）。

假设：题材动量因子的有效性依赖情绪相位——情绪有利期高动量题材延续占优，
情绪退潮期动量失效或反转。

方法（momentum_validation 范式，探索性）：
  - 样本：daily 收盘横截面（momentumScore 落库值 100% 覆盖），per day 五分位分组；
  - 前向收益：T+1 题材等权 change；统计口径 = Q5−Q1 日均差 / 胜率 / Spearman IC；
  - 条件维 A：market_phase（half_hour 15:00 帧，None 日单列）；
  - 条件维 B：limitSummary 炸板率（sentiment_slots 合并回退取数，中位数分高低组，
    炸板率高=情绪差，方向显式）；maxBoard 为附加诊断；
  - 判定语义：只报告方向与幅度差异，不做显著性检验、不落默认。

fail-visible：相位/情绪缺失日如实单列或计数；组样本 n<3 打 insufficient_sample；
不使用 0 伪装缺失。只读研究 runner（除回测 run 外不写业务库，本 runner 不触发回测）。

用法（非交易时段运行）：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_sentiment_momentum_phase1
      [--dataset dragonboard_live] [--start 2026-07-06] [--end 2026-09-24]
      [--out data/reports/theme-phase1-sentiment-momentum.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

from backend.analysis.theme.rank_ic import spearman_rank_ic
from backend.analysis.theme.sentiment_slots import pick_sentiment_snapshot
from backend.data.repositories.repository_factory import create_repository
from backend.services.backtest_service import _close_slot_rows_by_day

DATASET_ID = "dragonboard_live"


def load_daily_momentum(repo: Any, start: str, end: str) -> dict[str, dict[str, dict[str, float]]]:
    """daily 收盘横截面 {date: {theme: {"momentum": x, "change": y}}}。"""
    res = repo.list_snapshot_sector_rows(
        DATASET_ID, start_date=start, end_date=end,
        snapshot_type="daily", entity_type="hot_theme", sort="asc",
    )
    out: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for d, rows in _close_slot_rows_by_day(res.get("rows") or []).items():
        for row in rows:
            name = str(row.get("entityName") or "")
            mom, chg = row.get("momentumScore"), row.get("change")
            if not name or not isinstance(mom, (int, float)) or not isinstance(chg, (int, float)):
                continue
            out[d][name] = {"momentum": float(mom), "change": float(chg)}
    return dict(out)


def load_market_phase(repo: Any, start: str, end: str) -> dict[str, str | None]:
    """half_hour 15:00 帧 marketPhase（db 直查最小投影，R1 范式）。"""
    out: dict[str, str | None] = {}
    for doc in repo.db["snapshot_frames"].find(
        {
            "datasetId": DATASET_ID, "type": "half_hour", "slotTime": "15:00",
            "tradingDate": {"$gte": start, "$lte": end},
        },
        {"tradingDate": 1, "rotationSummary.marketPhase": 1},
    ):
        rs = doc.get("rotationSummary") or {}
        out[str(doc.get("tradingDate"))] = str(rs.get("marketPhase") or "") or None
    return out


def load_limit_summaries(repo: Any, start: str, end: str) -> dict[str, dict[str, list[tuple[str, Any]]] | Any]:
    """逐日 limitSummary 素材：{"daily1530": ls|None, "halfHourSlots": [(slot, ls)]}。"""
    by_day: dict[str, dict[str, Any]] = defaultdict(lambda: {"daily1530": None, "halfHourSlots": []})
    for doc in repo.db["snapshot_frames"].find(
        {
            "datasetId": DATASET_ID, "type": {"$in": ["daily", "half_hour"]},
            "tradingDate": {"$gte": start, "$lte": end},
        },
        {"tradingDate": 1, "slotTime": 1, "type": 1, "limitSummary": 1},
    ):
        day = by_day[str(doc.get("tradingDate"))]
        if doc.get("type") == "daily" and doc.get("slotTime") == "15:30":
            day["daily1530"] = doc.get("limitSummary")
        elif doc.get("type") == "half_hour":
            day["halfHourSlots"].append((str(doc.get("slotTime")), doc.get("limitSummary")))
    return dict(by_day)


def build_daily_stats(cross_sections: dict[str, dict[str, dict[str, float]]]) -> tuple[dict[str, dict[str, float]], list[str]]:
    """逐日统计：五分位 Q5/Q1 收益差与全横截面 IC；返回 ({date: stats}, qualityFlags)。"""
    stats: dict[str, dict[str, float]] = {}
    flags: list[str] = []
    days = sorted(cross_sections)
    for i, d in enumerate(days):
        themes = cross_sections[d]
        if len(themes) < 10:
            flags.append(f"thin_cross_section:{d}:{len(themes)}")
        ranked = sorted(themes.items(), key=lambda kv: kv[1]["momentum"])
        n = len(ranked)
        q_size = max(1, n // 5)
        next_day = days[i + 1] if i + 1 < len(days) else None
        # T+1 前向收益：当日排名 → 次日 change（末日无次日，整日丢弃）
        if next_day is None:
            flags.append(f"no_next_day_drop:{d}:{n}")
            continue
        nxt = cross_sections[next_day]
        fwd_map = {name: nxt[name]["change"] for name, _ in ranked if name in nxt}
        q1_fwd = [fwd_map[name] for name, _ in ranked[:q_size] if name in fwd_map]
        q5_fwd = [fwd_map[name] for name, _ in ranked[-q_size:] if name in fwd_map]
        pairs_m = [v["momentum"] for name, v in ranked if name in fwd_map]
        pairs_c = [fwd_map[name] for name, v in ranked if name in fwd_map]
        ic = spearman_rank_ic(pairs_m, pairs_c) if len(pairs_m) >= 2 else None
        stats[d] = {
            "themeCount": n,
            "pairedCount": len(fwd_map),
            "q5MinusQ1": sum(q5_fwd) / len(q5_fwd) - sum(q1_fwd) / len(q1_fwd) if q1_fwd and q5_fwd else None,
            "ic": ic,
        }
    return stats, flags


def summarize_group(day_keys: list[str], stats: dict[str, dict[str, float]]) -> dict[str, Any]:
    """一组日度统计的汇总（n<3 打 insufficient_sample）。"""
    diffs = [stats[d]["q5MinusQ1"] for d in day_keys if stats.get(d, {}).get("q5MinusQ1") is not None]
    ics = [stats[d]["ic"] for d in day_keys if stats.get(d, {}).get("ic") is not None]
    out: dict[str, Any] = {"n": len(diffs)}
    if not diffs:
        return {"n": 0, "status": "insufficient_sample", "q5MinusQ1Avg": None, "icAvg": None}
    out.update({
        "status": "ok" if len(diffs) >= 3 else "insufficient_sample",
        "q5MinusQ1Avg": round(sum(diffs) / len(diffs), 6),
        "q5MinusQ1WinRate": round(sum(1 for x in diffs if x > 0) / len(diffs), 4),
        "icAvg": round(sum(ics) / len(ics), 4) if ics else None,
        "icPositiveShare": round(sum(1 for x in ics if x > 0) / len(ics), 4) if ics else None,
    })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 1 情绪相位×题材动量验证 runner")
    parser.add_argument("--dataset", default=DATASET_ID)
    parser.add_argument("--start", default="2026-07-06")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--out", default="data/reports/theme-phase1-sentiment-momentum.json")
    args = parser.parse_args()

    repo = create_repository(None)
    cross_sections = load_daily_momentum(repo, args.start, args.end)
    phase_by_day = load_market_phase(repo, args.start, args.end)
    ls_material = load_limit_summaries(repo, args.start, args.end)
    stats, flags = build_daily_stats(cross_sections)

    # 维 B：情绪快照 + 炸板率中位数分组（高炸板率=情绪差，方向显式）
    snaps = {
        d: pick_sentiment_snapshot(m["daily1530"], m["halfHourSlots"])
        for d, m in ls_material.items()
    }
    rates = [s["zhabanRate"] for s in snaps.values() if s["status"] == "ok" and s["zhabanRate"] is not None]
    boards = [s["maxBoard"] for s in snaps.values() if s["status"] == "ok" and s["maxBoard"] is not None]
    rate_median = median(rates) if rates else None
    board_median = median(boards) if boards else None
    if rate_median is None:
        flags.append("zhaban_rate_unavailable")
    sentiment_group: dict[str, str | None] = {}
    board_group: dict[str, str | None] = {}
    for d in stats:
        snap = snaps.get(d) or {}
        if snap.get("status") != "ok" or snap.get("zhabanRate") is None or rate_median is None:
            sentiment_group[d] = None
        else:
            sentiment_group[d] = "low_zhaban(情绪好)" if snap["zhabanRate"] <= rate_median else "high_zhaban(情绪差)"
        if snap.get("status") != "ok" or snap.get("maxBoard") is None or board_median is None:
            board_group[d] = None
        else:
            board_group[d] = "high_board(情绪好)" if snap["maxBoard"] >= board_median else "low_board(情绪差)"

    # 维 A：相位分组（None 单列 phase_unknown）
    phase_group: dict[str, str | None] = {
        d: phase_by_day.get(d) or ("phase_unknown" if d in phase_by_day else "missing_15h_frame")
        for d in stats
    }

    def group_days(mapping: dict[str, str | None]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for d, key in mapping.items():
            grouped[str(key)].append(d)
        return dict(grouped)

    report: dict[str, Any] = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "dataset": args.dataset,
            "window": {"start": args.start, "end": args.end},
            "hypothesis": "题材动量有效性依赖情绪相位：有利期 Q5 占优、退潮期收敛/反转",
            "forwardReturn": "T+1 题材等权 change（change 为落库百分数单位，Q5-Q1 差与单位相同；IC 无量纲）",
            "zhabanRateMedian": rate_median,
            "maxBoardMedian": board_median,
            "directionNote": "zhabanRate 为负向变量（高=情绪差）；maxBoard 为正向变量",
        },
        "coverage": {
            "tradingDaysWithCrossSection": len(stats),
            "phaseDays": {k: len(v) for k, v in sorted(group_days(phase_group).items())},
            "sentimentDays": {k: len(v) for k, v in sorted(group_days(sentiment_group).items())},
            "sentimentSourceDays": {
                src: sum(1 for s in snaps.values() if s.get("source") == src)
                for src in sorted({str(s.get("source")) for s in snaps.values() if s.get("status") == "ok"})
            },
        },
        "byPhase": {
            key: summarize_group(days, stats) for key, days in sorted(group_days(phase_group).items())
        },
        "byZhabanRate": {
            key: summarize_group(days, stats) for key, days in sorted(group_days(sentiment_group).items())
        },
        "byMaxBoard": {
            key: summarize_group(days, stats) for key, days in sorted(group_days(board_group).items())
        },
        "byMonth": {},
        "dailyStats": {d: stats[d] for d in sorted(stats)},
        "qualityFlags": flags,
    }
    by_month: dict[str, list[str]] = defaultdict(list)
    for d in stats:
        by_month[d[:7]].append(d)
    report["byMonth"] = {m: summarize_group(days, stats) for m, days in sorted(by_month.items())}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"report written: {out_path}")
    for title, section in (("相位", report["byPhase"]), ("炸板率", report["byZhabanRate"]), ("连板高度", report["byMaxBoard"])):
        print(f"== {title} ==")
        for key, row in section.items():
            print(
                f"  {key}: n={row.get('n')} Q5-Q1={row.get('q5MinusQ1Avg')} "
                f"win={row.get('q5MinusQ1WinRate')} IC={row.get('icAvg')} {row.get('status')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
