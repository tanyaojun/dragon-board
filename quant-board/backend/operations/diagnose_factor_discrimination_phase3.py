"""Phase 3：D2/D3/F1 逐因子区分度验证 runner（只读，不写业务库，不触发回测）。

六因子同一评估面板（T+1 daily change 等权前向；正因子方向：高分预期 T+1 更好）：
  momentum  = momentumScore 落库值（原始动量基线复算，同窗对照）
  sharpe_20 = 15:00 收盘槽 change 序列 20 日夏普动量（D2 主档，factor_series.sharpe_momentum）
  sharpe_40 = 40 日夏普动量（D2 副档，评估日约 13 天，薄样本如实打标）
  d3_streak = momentumScore Top 五分位连续保持天数（D3，factor_series.top_membership_streak）
  f1_streak = mainNetInflow 连续为正天数（F1，factor_series.positive_streak）
  inflow_lv = mainNetInflow 原始水平（对照"持续性 vs 水平"的增量）

统计（momentum_validation 范式）：五分位 Q5−Q1 与胜率（正因子预期 >0）、逐日 spearman
IC 均值与 IC>0 占比、n<3 打 insufficient_sample、按月分解。
D3 条件视图：momentumScore Top 五分位题材内按 streak 中位数二分的 T+1 差——业界
"动量连续性过滤"的直接检验。

口径声明（task_plan_phase3.md 接口事实）：
  - F1 持久序列源 = daily 行 mainNetInflow（fund_cache 为 Redis 运行态无逐日历史）；
  - D2 夏普动量尺度不变，15:00 change 百分数口径无需换算；
  - 60 日窗口结构性 insufficient（题材序列实测最长 58 天），登记不硬造；
  - d3_streak 与 momentumScore 同源自相关，条件视图是其主消费形态。

用法（非交易时段运行）：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_factor_discrimination_phase3
      [--start 2026-07-06] [--end 2026-09-24]
      [--out data/reports/theme-phase3-factor-discrimination.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.analysis.theme.factor_series import (
    positive_streak,
    sharpe_momentum,
    top_membership_streak,
)
from backend.analysis.theme.rank_ic import spearman_rank_ic
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.backtest_service import _close_slot_rows_by_day

DATASET_ID = "dragonboard_live"
FACTORS = ("momentum", "sharpe_20", "sharpe_40", "d3_streak", "f1_streak", "inflow_lv")


def load_daily_cross_sections(
    repo: MongoRepository, start: str, end: str
) -> tuple[dict[str, dict[str, dict[str, float | None]]], dict[str, str]]:
    """daily hot_theme 收盘横截面 {date: {entityKey: {momentum, change, inflow}}} + 最新展示名。"""
    res = repo.list_snapshot_sector_rows(
        DATASET_ID, start_date=start, end_date=end,
        snapshot_type="daily", entity_type="hot_theme", sort="asc",
    )
    out: dict[str, dict[str, dict[str, float | None]]] = {}
    names: dict[str, str] = {}
    for d, rows in _close_slot_rows_by_day(res.get("rows") or []).items():
        day: dict[str, dict[str, float | None]] = {}
        for row in rows:
            key = row.get("entityKey")
            if key is None:
                continue
            k = str(key)

            def _num(v: Any) -> float | None:
                return float(v) if isinstance(v, (int, float)) else None

            day[k] = {
                "momentum": _num(row.get("momentumScore")),
                "change": _num(row.get("change")),
                "inflow": _num(row.get("mainNetInflow")),
            }
            names[k] = str(row.get("entityName") or k)
        if day:
            out[d] = day
    return out, names


def load_close_slot_changes(
    repo: MongoRepository, start: str, end: str
) -> dict[str, dict[str, float]]:
    """15:00 收盘槽题材 change 序列原料 {entityKey: {date: change（百分数）}}。"""
    seq: dict[str, dict[str, float]] = defaultdict(dict)
    for row in repo.db["snapshot_sector_rows"].find(
        {
            "datasetId": DATASET_ID, "type": "half_hour", "entityType": "hot_theme",
            "slotTime": "15:00", "tradingDate": {"$gte": start, "$lte": end},
            "change": {"$type": "number"},
        },
        {"tradingDate": 1, "entityKey": 1, "change": 1},
    ):
        key = row.get("entityKey")
        chg = row.get("change")
        if key is not None and isinstance(chg, (int, float)):
            seq[str(key)][str(row.get("tradingDate"))] = float(chg)
    return dict(seq)


def build_factor_panels(
    cross_sections: dict[str, dict[str, dict[str, float | None]]],
    close_changes: dict[str, dict[str, float]],
) -> tuple[dict[str, dict[str, dict[str, float | None]]], dict[str, Any]]:
    """逐题材逐日六因子面板 {date: {key: {factor: value}}} + 覆盖统计。"""
    # D2：15:00 序列夏普动量（20 主档 / 40 副档）
    sharpe_20 = {
        k: sharpe_momentum(seq, window=20, min_periods=20) for k, seq in close_changes.items()
    }
    sharpe_40 = {
        k: sharpe_momentum(seq, window=40, min_periods=40) for k, seq in close_changes.items()
    }
    # D3：逐日 momentumScore Top 五分位成员集
    top_by_day: dict[str, set[str]] = {}
    observed_by_day: dict[str, set[str]] = {}
    for d, day in cross_sections.items():
        ranked = sorted(
            (k for k, v in day.items() if v["momentum"] is not None),
            key=lambda k: day[k]["momentum"],
            reverse=True,
        )
        q = max(1, len(ranked) // 5)
        top_by_day[d] = set(ranked[:q])
        observed_by_day[d] = set(ranked)
    # F1 / 水平：逐题材 mainNetInflow 序列
    theme_keys: set[str] = set()
    for day in cross_sections.values():
        theme_keys |= set(day)
    inflow_seq = {
        k: {d: (day.get(k) or {}).get("inflow") for d, day in cross_sections.items()}
        for k in theme_keys
    }
    f1_streak = {k: positive_streak(seq, threshold=0.0) for k, seq in inflow_seq.items()}

    panels: dict[str, dict[str, dict[str, float | None]]] = {}
    for d, day in cross_sections.items():
        panel: dict[str, dict[str, float | None]] = {}
        for k, row in day.items():
            panel[k] = {
                "momentum": row["momentum"],
                "sharpe_20": sharpe_20.get(k, {}).get(d),
                "sharpe_40": sharpe_40.get(k, {}).get(d),
                "d3_streak": None,
                "f1_streak": f1_streak.get(k, {}).get(d),
                "inflow_lv": row["inflow"],
            }
        panels[d] = panel
    streaks = {k: top_membership_streak(top_by_day, observed_by_day, k) for k in theme_keys}
    for d, panel in panels.items():
        for k in panel:
            panel[k]["d3_streak"] = streaks.get(k, {}).get(d)
    coverage = {
        "d3TopDays": len(top_by_day),
        "sharpe20Themes": sum(1 for s in sharpe_20.values() if any(v is not None for v in s.values())),
        "sharpe40Themes": sum(1 for s in sharpe_40.values() if any(v is not None for v in s.values())),
        "inflowThemes": sum(1 for s in f1_streak.values() if any(v is not None for v in s.values())),
    }
    return panels, coverage


def _quintile_spread(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    """按因子值升序五分位：Q5（最高）− Q1 的 T+1 均值差（正因子预期 >0）。"""
    ranked = sorted(pairs, key=lambda kv: kv[0])
    n = len(ranked)
    q = max(1, n // 5)
    q1 = [c for _, c in ranked[:q]]
    q5 = [c for _, c in ranked[-q:]]
    return {"n": n, "q5MinusQ1": sum(q5) / len(q5) - sum(q1) / len(q1)}


def build_daily_stats(
    panels: dict[str, dict[str, dict[str, float | None]]],
    cross_sections: dict[str, dict[str, dict[str, float | None]]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """逐日统计：各因子五分位差 + IC + D3 条件视图。"""
    stats: dict[str, dict[str, Any]] = {}
    flags: list[str] = []
    days = sorted(panels)
    for i, d in enumerate(days):
        if len(cross_sections.get(d) or {}) < 10:
            flags.append(f"thin_cross_section:{d}")
        nxt = days[i + 1] if i + 1 < len(days) else None
        if nxt is None:
            flags.append(f"no_next_day_drop:{d}")
            continue
        nxt_changes = {
            k: v["change"] for k, v in cross_sections[nxt].items() if v["change"] is not None
        }
        panel = panels[d]
        day_stat: dict[str, Any] = {"themeCount": len(panel), "pairedCount": len(nxt_changes)}
        for factor in FACTORS:
            pairs = [
                (row[factor], nxt_changes[k])
                for k, row in panel.items()
                if row[factor] is not None and k in nxt_changes
            ]
            if len(pairs) < 2:
                day_stat[factor] = {"n": len(pairs), "q5MinusQ1": None, "ic": None}
                continue
            spread = _quintile_spread(pairs)
            ic = spearman_rank_ic([p[0] for p in pairs], [p[1] for p in pairs])
            day_stat[factor] = {"n": spread["n"], "q5MinusQ1": spread["q5MinusQ1"], "ic": ic}
        # D3 条件视图：momentumScore Top 五分位内按 streak 中位数二分
        top_keys = [
            k for k, row in panel.items()
            if row["momentum"] is not None and row["d3_streak"] is not None and k in nxt_changes
            and _in_top_quintile(panel, k)
        ]
        if len(top_keys) >= 2:
            med = sorted(panel[k]["d3_streak"] for k in top_keys)[len(top_keys) // 2]
            hi = [nxt_changes[k] for k in top_keys if panel[k]["d3_streak"] >= med]
            lo = [nxt_changes[k] for k in top_keys if panel[k]["d3_streak"] < med]
            if hi and lo:
                day_stat["d3_conditional"] = {
                    "n": len(top_keys),
                    "medianStreak": med,
                    "highAvg": sum(hi) / len(hi),
                    "lowAvg": sum(lo) / len(lo),
                    "diff": sum(hi) / len(hi) - sum(lo) / len(lo),
                }
        stats[d] = day_stat
    return stats, flags


def _in_top_quintile(panel: dict[str, dict[str, float | None]], key: str) -> bool:
    """momentumScore Top 五分位成员判定（与 top_by_day 构建同口径）。"""
    ranked = sorted(
        (k for k, v in panel.items() if v["momentum"] is not None),
        key=lambda k: panel[k]["momentum"],
        reverse=True,
    )
    return key in set(ranked[: max(1, len(ranked) // 5)])


def summarize_factor(day_keys: list[str], stats: dict[str, dict[str, Any]], factor: str) -> dict[str, Any]:
    """一组日的单因子汇总（n<3 打 insufficient_sample；winRate=Q5−Q1>0 占比，方向显式）。"""
    spreads = [stats[d][factor]["q5MinusQ1"] for d in day_keys if stats.get(d, {}).get(factor, {}).get("q5MinusQ1") is not None]
    ics = [stats[d][factor]["ic"] for d in day_keys if stats.get(d, {}).get(factor, {}).get("ic") is not None]
    if not spreads:
        return {"n": 0, "status": "insufficient_sample"}
    return {
        "n": len(spreads),
        "status": "ok" if len(spreads) >= 3 else "insufficient_sample",
        "q5MinusQ1Avg": round(sum(spreads) / len(spreads), 6),
        "posSpreadWinRate": round(sum(1 for x in spreads if x > 0) / len(spreads), 4),
        "icAvg": round(sum(ics) / len(ics), 4) if ics else None,
        "icPositiveShare": round(sum(1 for x in ics if x > 0) / len(ics), 4) if ics else None,
    }


def summarize_conditional(day_keys: list[str], stats: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = [stats[d]["d3_conditional"] for d in day_keys if stats.get(d, {}).get("d3_conditional")]
    if not rows:
        return {"n": 0, "status": "insufficient_sample"}
    return {
        "n": len(rows),
        "status": "ok" if len(rows) >= 3 else "insufficient_sample",
        "diffAvg": round(sum(r["diff"] for r in rows) / len(rows), 6),
        "positiveShare": round(sum(1 for r in rows if r["diff"] > 0) / len(rows), 4),
        "topQuintileSizeAvg": round(sum(r["n"] for r in rows) / len(rows), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 3 逐因子区分度验证 runner")
    parser.add_argument("--start", default="2026-07-06")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--out", default="data/reports/theme-phase3-factor-discrimination.json")
    args = parser.parse_args()

    repo = MongoRepository(get_runtime_mongodb_database())
    cross_sections, names = load_daily_cross_sections(repo, args.start, args.end)
    if not cross_sections:
        print(json.dumps({"status": "insufficient", "reason": "no_theme_cross_sections"}, ensure_ascii=False))
        return 2
    close_changes = load_close_slot_changes(repo, args.start, args.end)
    panels, coverage = build_factor_panels(cross_sections, close_changes)
    stats, flags = build_daily_stats(panels, cross_sections)
    days = sorted(stats)

    flags.append("sharpe_60_structurally_insufficient:series_max_58d")
    by_month: dict[str, list[str]] = defaultdict(list)
    for d in days:
        by_month[d[:7]].append(d)

    report: dict[str, Any] = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "dataset": DATASET_ID,
            "window": {"start": args.start, "end": args.end},
            "hypothesis": "D2 夏普动量 / D3 动量连续性 / F1 资金流持续性的区分度优于原始动量（正因子）",
            "directionNote": "Q5−Q1 预期 >0；posSpreadWinRate=Q5−Q1>0 占比；IC 预期 >0",
            "d2WindowNote": "设计口径 20/60 日；题材 15:00 序列实测最长 58 天 → 60 日结构性 insufficient；40 日档薄样本",
            "f1SourceNote": "daily 行 mainNetInflow（fund_cache 为 Redis 运行态无逐日历史，设计 §5.2 口径修正）",
            "d3SelfCorrNote": "d3_streak 由 momentumScore 排名派生（同源），条件视图为主消费形态",
        },
        "coverage": {
            "evalDays": len(days),
            "crossSectionDays": len(cross_sections),
            "themeNameCount": len(names),
            **coverage,
        },
        "factors": {factor: summarize_factor(days, stats, factor) for factor in FACTORS},
        "d3Conditional": summarize_conditional(days, stats),
        "byMonth": {
            month: {factor: summarize_factor(keys, stats, factor) for factor in FACTORS}
            | {"d3Conditional": summarize_conditional(keys, stats)}
            for month, keys in sorted(by_month.items())
        },
        "dailyStats": {d: stats[d] for d in days},
        "qualityFlags": flags,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"report written: {out_path}")
    for factor in FACTORS:
        row = report["factors"][factor]
        print(
            f"[{factor}] n={row.get('n')} Q5-Q1={row.get('q5MinusQ1Avg')} win={row.get('posSpreadWinRate')} "
            f"IC={row.get('icAvg')} icPos={row.get('icPositiveShare')} {row.get('status')}"
        )
    print(f"[d3Conditional] {report['d3Conditional']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
