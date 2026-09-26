"""Phase 2：拥挤度口径对比 runner（只读，不写业务库，不触发回测）。

四口径（同一评估面板，T+1 题材等权 change 前向）：
  A  = crowdingRisk 落库值（现有瞬时口径：量比溢价+高涨股占比，heat.py _crowding_risk，
       消费侧 75 硬层 + 动量惩罚 60 起扣封顶 15）
  B1 = 题材成交额占采集池比重的 60 日弱占比分位（crowding_percentile.theme_amount_share）
  B2 = 题材成员换手率等权均值的 60 日弱占比分位（theme_turnover_mean）
  BC = B1/B2 等权合成（combine_equal_weight）

核心问题：分位数化拥挤度对"次日退潮"的区分度是否优于瞬时口径——负向因子，
Q5−Q1 预期为负、IC 预期为负（winRate = Q5−Q1<0 的天数占比，方向显式声明）。

口径声明（实测固化，task_plan_phase2.md 接口事实 5/6）：
  - 分母为当日采集池 amount 总和（非真实全市场，池外成员计 0）；
  - theme_stock_mappings 为当前时点快照，回溯带成员重构偏差（探索性对照）；
  - 零覆盖题材（成员全不在当日采集池）当日不可观测 → 不入分位序列（None）。

fail-visible：分位窗口不足日/映射未覆盖题材/缺字段行全部计数落 qualityFlags；
组样本 n<3 打 insufficient_sample；不伪造 0、不省略缺日。

用法（非交易时段运行）：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_crowding_caliber_phase2
      [--start 2026-07-06] [--end 2026-09-24] [--window 60] [--min-periods 10]
      [--out data/reports/theme-phase2-crowding-caliber.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.analysis.theme.crowding_percentile import (
    combine_equal_weight,
    rolling_percentile,
    theme_amount_share,
    theme_turnover_mean,
)
from backend.analysis.theme.rank_ic import spearman_rank_ic
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.backtest_service import _close_slot_rows_by_day

DATASET_ID = "dragonboard_live"
CALIBERS = ("A", "B1", "B2", "BC")
HARD_LAYER_CROWDING = 75.0
HIGH_PRESSURE_PERCENTILE = 90.0


def load_theme_cross_sections(
    repo: MongoRepository, start: str, end: str
) -> tuple[dict[str, dict[str, dict[str, float | None]]], dict[str, str], int]:
    """daily hot_theme 收盘横截面 {date: {entityKey: {crowding, change}}} + 最新展示名。"""
    res = repo.list_snapshot_sector_rows(
        DATASET_ID, start_date=start, end_date=end,
        snapshot_type="daily", entity_type="hot_theme", sort="asc",
    )
    out: dict[str, dict[str, dict[str, float | None]]] = {}
    names: dict[str, str] = {}
    missing_key_rows = 0
    for d, rows in _close_slot_rows_by_day(res.get("rows") or []).items():
        day: dict[str, dict[str, float | None]] = {}
        for row in rows:
            key = row.get("entityKey")
            if key is None:
                missing_key_rows += 1
                continue
            k = str(key)
            crowding = row.get("crowdingRisk")
            chg = row.get("change")
            day[k] = {
                "crowding": float(crowding) if isinstance(crowding, (int, float)) else None,
                "change": float(chg) if isinstance(chg, (int, float)) else None,
            }
            names[k] = str(row.get("entityName") or k)  # 日期升序遍历，后写=最新名（2 个改名主题）
        if day:
            out[d] = day
    return out, names, missing_key_rows


def load_stock_daily(
    repo: MongoRepository, start: str, end: str
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, int]]:
    """daily stock rows 收盘横截面 {date: {amount: {code: v}, turnover: {code: v}}}。"""
    res = repo.list_snapshot_stock_rows(
        DATASET_ID, start_date=start, end_date=end,
        snapshot_type="daily", sort="asc",
        fields=["tradingDate", "slotTime", "code", "amount", "turnoverRate"],
    )
    out: dict[str, dict[str, dict[str, float]]] = {}
    missing = {"no_code": 0, "amount": 0, "turnoverRate": 0}
    for d, rows in _close_slot_rows_by_day(res.get("rows") or []).items():
        amounts: dict[str, float] = {}
        turnovers: dict[str, float] = {}
        for row in rows:
            code = row.get("code")
            if not code:
                missing["no_code"] += 1
                continue
            amt = row.get("amount")
            if isinstance(amt, (int, float)):
                amounts[str(code)] = float(amt)
            else:
                missing["amount"] += 1
            tr = row.get("turnoverRate")
            if isinstance(tr, (int, float)):
                turnovers[str(code)] = float(tr)
            else:
                missing["turnoverRate"] += 1
        if amounts or turnovers:
            out[d] = {"amount": amounts, "turnover": turnovers}
    return out, missing


def load_theme_members(repo: MongoRepository) -> dict[str, set[str]]:
    """theme_stock_mappings 平铺对 → {themeId: set(stockCode)}。"""
    members: dict[str, set[str]] = defaultdict(set)
    for doc in repo.db["theme_stock_mappings"].find({}, {"themeId": 1, "stockCode": 1}):
        tid = doc.get("themeId")
        code = doc.get("stockCode")
        if tid is not None and code:
            members[str(tid)].add(str(code))
    return dict(members)


def build_percentile_series(
    stock_daily: dict[str, dict[str, dict[str, float]]],
    members: dict[str, set[str]],
    *,
    window: int,
    min_periods: int,
) -> tuple[dict[str, dict[str, float | None]], dict[str, dict[str, float | None]]]:
    """逐题材 B1/B2 原料与 60 日分位（历史在全部有 stock rows 的日子上累计，
    零覆盖成员的题材当日不入序列）。"""
    shares_by_theme: dict[str, dict[str, float]] = defaultdict(dict)
    turnover_by_theme: dict[str, dict[str, float]] = defaultdict(dict)
    for d in sorted(stock_daily):
        amounts = stock_daily[d]["amount"]
        turnovers = stock_daily[d]["turnover"]
        amount_keys = set(amounts)
        turnover_keys = set(turnovers)
        if amounts:
            shares = theme_amount_share(amounts, members)
            for tid, share in shares.items():
                if members[tid] & amount_keys:  # 零覆盖 → 当日不可观测，不入历史
                    shares_by_theme[tid][d] = share
        if turnovers:
            tmeans = theme_turnover_mean(turnovers, members)
            for tid, tm in tmeans.items():
                if tm is not None and members[tid] & turnover_keys:
                    turnover_by_theme[tid][d] = tm
    pct_share = {
        tid: rolling_percentile(seq, window=window, min_periods=min_periods)
        for tid, seq in shares_by_theme.items()
    }
    pct_turnover = {
        tid: rolling_percentile(seq, window=window, min_periods=min_periods)
        for tid, seq in turnover_by_theme.items()
    }
    return pct_share, pct_turnover


def _quintile_spread(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    """按因子值升序五分位：Q5（最高/最拥挤）− Q1 的 T+1 均值差（负向因子预期 <0）。"""
    ranked = sorted(pairs, key=lambda kv: kv[0])
    n = len(ranked)
    q = max(1, n // 5)
    q1 = [c for _, c in ranked[:q]]
    q5 = [c for _, c in ranked[-q:]]
    spread = sum(q5) / len(q5) - sum(q1) / len(q1)
    return {"n": n, "q5MinusQ1": spread}


def _two_group_diff(hi: list[float], lo: list[float]) -> dict[str, Any] | None:
    if not hi or not lo:
        return None
    return {
        "nHigh": len(hi), "nLow": len(lo),
        "diff": sum(hi) / len(hi) - sum(lo) / len(lo),
    }


def build_daily_stats(
    cross_sections: dict[str, dict[str, dict[str, float | None]]],
    pct_share: dict[str, dict[str, float | None]],
    pct_turnover: dict[str, dict[str, float | None]],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """逐日统计：各口径五分位差 + IC + 硬层/高压组对照 + 口径间相关。"""
    stats: dict[str, dict[str, Any]] = {}
    flags: list[str] = []
    days = sorted(cross_sections)
    for i, d in enumerate(days):
        themes = cross_sections[d]
        if len(themes) < 10:
            flags.append(f"thin_cross_section:{d}:{len(themes)}")
        nxt = days[i + 1] if i + 1 < len(days) else None
        if nxt is None:
            flags.append(f"no_next_day_drop:{d}:{len(themes)}")
            continue
        nxt_changes = {
            k: v["change"] for k, v in cross_sections[nxt].items() if v["change"] is not None
        }
        bc_by_key = {
            k: combine_equal_weight(
                {d: pct_share.get(k, {}).get(d)},
                {d: pct_turnover.get(k, {}).get(d)},
            )[d]
            for k in themes
        }
        day_stat: dict[str, Any] = {"themeCount": len(themes), "pairedCount": len(nxt_changes)}
        for calib in CALIBERS:
            pairs: list[tuple[float, float]] = []
            for k, row in themes.items():
                if calib == "A":
                    value = row["crowding"]
                elif calib == "B1":
                    value = pct_share.get(k, {}).get(d)
                elif calib == "B2":
                    value = pct_turnover.get(k, {}).get(d)
                else:
                    value = bc_by_key.get(k)
                chg_next = nxt_changes.get(k)
                if value is not None and chg_next is not None:
                    pairs.append((float(value), chg_next))
            if len(pairs) < 2:
                day_stat[calib] = {"n": len(pairs), "q5MinusQ1": None, "ic": None}
                continue
            spread = _quintile_spread(pairs)
            ic = spearman_rank_ic([p[0] for p in pairs], [p[1] for p in pairs])
            day_stat[calib] = {"n": spread["n"], "q5MinusQ1": spread["q5MinusQ1"], "ic": ic}
        # 75 硬层：A>=75 vs 其余的 T+1 均值差（负向因子预期 diff<0）
        hi = [nxt_changes[k] for k, row in themes.items()
              if row["crowding"] is not None and row["crowding"] >= HARD_LAYER_CROWDING and k in nxt_changes]
        lo = [nxt_changes[k] for k, row in themes.items()
              if row["crowding"] is not None and row["crowding"] < HARD_LAYER_CROWDING and k in nxt_changes]
        day_stat["hardLayer75"] = _two_group_diff(hi, lo)
        day_stat["hardLayer75HighCount"] = len(hi)
        # 分位 ≥90 高压组：BC vs 其余（泡沫预警语义对照）
        hi_bc = [nxt_changes[k] for k in themes
                 if isinstance(bc_by_key.get(k), float) and bc_by_key[k] >= HIGH_PRESSURE_PERCENTILE and k in nxt_changes]
        lo_bc = [nxt_changes[k] for k in themes
                 if isinstance(bc_by_key.get(k), float) and bc_by_key[k] < HIGH_PRESSURE_PERCENTILE and k in nxt_changes]
        day_stat["highPressure90"] = _two_group_diff(hi_bc, lo_bc)
        day_stat["highPressure90HighCount"] = len(hi_bc)
        # 口径间横截面相关（是否同一信号）
        for name, other in (("AxB1", pct_share), ("AxB2", pct_turnover)):
            both = [
                (themes[k]["crowding"], other.get(k, {}).get(d))
                for k in themes
                if themes[k]["crowding"] is not None and isinstance(other.get(k, {}).get(d), float)
            ]
            day_stat[name] = spearman_rank_ic([p[0] for p in both], [p[1] for p in both]) if len(both) >= 2 else None
        both_bc = [
            (themes[k]["crowding"], bc_by_key[k]) for k in themes
            if themes[k]["crowding"] is not None and isinstance(bc_by_key.get(k), float)
        ]
        day_stat["AxBC"] = spearman_rank_ic([p[0] for p in both_bc], [p[1] for p in both_bc]) if len(both_bc) >= 2 else None
        stats[d] = day_stat
    return stats, flags


def summarize_caliber(day_keys: list[str], stats: dict[str, dict[str, Any]], calib: str) -> dict[str, Any]:
    """一组日的单口径汇总（n<3 打 insufficient_sample；winRate=Q5−Q1<0 占比，方向显式）。"""
    spreads = [stats[d][calib]["q5MinusQ1"] for d in day_keys if stats.get(d, {}).get(calib, {}).get("q5MinusQ1") is not None]
    ics = [stats[d][calib]["ic"] for d in day_keys if stats.get(d, {}).get(calib, {}).get("ic") is not None]
    if not spreads:
        return {"n": 0, "status": "insufficient_sample"}
    return {
        "n": len(spreads),
        "status": "ok" if len(spreads) >= 3 else "insufficient_sample",
        "q5MinusQ1Avg": round(sum(spreads) / len(spreads), 6),
        "negSpreadWinRate": round(sum(1 for x in spreads if x < 0) / len(spreads), 4),
        "icAvg": round(sum(ics) / len(ics), 4) if ics else None,
        "icNegativeShare": round(sum(1 for x in ics if x < 0) / len(ics), 4) if ics else None,
    }


def summarize_group_stat(day_keys: list[str], stats: dict[str, dict[str, Any]], field: str) -> dict[str, Any]:
    """硬层/高压组逐日 diff 的汇总（组样本不足的日子如实跳过并计数）。"""
    diffs = [stats[d][field]["diff"] for d in day_keys if stats.get(d, {}).get(field)]
    high_counts = [stats[d][f"{field}HighCount"] for d in day_keys if stats.get(d, {}).get(field)]
    if not diffs:
        return {"n": 0, "status": "insufficient_sample", "reason": "no_days_with_both_groups"}
    return {
        "n": len(diffs),
        "status": "ok" if len(diffs) >= 3 else "insufficient_sample",
        "diffAvg": round(sum(diffs) / len(diffs), 6),
        "diffNegativeShare": round(sum(1 for x in diffs if x < 0) / len(diffs), 4),
        "highCountAvg": round(sum(high_counts) / len(high_counts), 2),
        "highCountTotal": sum(high_counts),
    }


def summarize_corr(day_keys: list[str], stats: dict[str, dict[str, Any]], field: str) -> dict[str, Any]:
    vals = [stats[d][field] for d in day_keys if stats.get(d, {}).get(field) is not None]
    if not vals:
        return {"n": 0, "status": "insufficient_sample"}
    return {
        "n": len(vals),
        "status": "ok" if len(vals) >= 3 else "insufficient_sample",
        "avg": round(sum(vals) / len(vals), 4),
        "positiveShare": round(sum(1 for x in vals if x > 0) / len(vals), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2 拥挤度口径对比 runner")
    parser.add_argument("--start", default="2026-07-06")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--min-periods", type=int, default=10)
    parser.add_argument("--out", default="data/reports/theme-phase2-crowding-caliber.json")
    args = parser.parse_args()

    repo = MongoRepository(get_runtime_mongodb_database())
    cross_sections, names, missing_key_rows = load_theme_cross_sections(repo, args.start, args.end)
    if not cross_sections:
        print(json.dumps({"status": "insufficient", "reason": "no_theme_cross_sections"}, ensure_ascii=False))
        return 2
    stock_daily, stock_missing = load_stock_daily(repo, args.start, args.end)
    members = load_theme_members(repo)
    pct_share, pct_turnover = build_percentile_series(
        stock_daily, members, window=args.window, min_periods=args.min_periods,
    )
    stats, flags = build_daily_stats(cross_sections, pct_share, pct_turnover)
    days = sorted(stats)

    unmapped_keys = sorted(k for k in names if k not in members)
    if unmapped_keys:
        flags.append(f"unmapped_theme_keys:{len(unmapped_keys)}")
    pct_none_days = sum(
        1 for tid, seq in pct_share.items() for v in seq.values() if v is None
    )
    flags.append(f"b1_percentile_none_days:{pct_none_days}")

    day_keys_by_month: dict[str, list[str]] = defaultdict(list)
    for d in days:
        day_keys_by_month[d[:7]].append(d)

    report: dict[str, Any] = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "dataset": DATASET_ID,
            "window": {"start": args.start, "end": args.end},
            "percentileWindow": args.window,
            "minPeriods": args.min_periods,
            "hypothesis": "分位数化拥挤度对次日退潮的区分度优于瞬时 crowdingRisk 口径（负向因子）",
            "directionNote": "Q5=最拥挤组；q5MinusQ1 预期为负；negSpreadWinRate=Q5−Q1<0 占比；IC 预期为负",
            "denominatorCaveat": "B1 分母=当日采集池 amount 总和（非真实全市场，池外成员计 0）",
            "mappingCaveat": "theme_stock_mappings 为当前时点快照，回溯带成员重构偏差（探索性对照）",
            "hardLayer": HARD_LAYER_CROWDING,
            "highPressurePercentile": HIGH_PRESSURE_PERCENTILE,
        },
        "coverage": {
            "evalDays": len(days),
            "stockDays": len(stock_daily),
            "themesWithB1History": len(pct_share),
            "themesWithB2History": len(pct_turnover),
            "themeNameCount": len(names),
            "missingKeyRows": missing_key_rows,
            "stockRowMissing": stock_missing,
        },
        "calibers": {
            calib: summarize_caliber(days, stats, calib) for calib in CALIBERS
        },
        "hardLayer75": summarize_group_stat(days, stats, "hardLayer75"),
        "highPressure90": summarize_group_stat(days, stats, "highPressure90"),
        "caliberCrossCorr": {
            field: summarize_corr(days, stats, field)
            for field in ("AxB1", "AxB2", "AxBC")
        },
        "byMonth": {
            month: {calib: summarize_caliber(keys, stats, calib) for calib in CALIBERS}
            | {"hardLayer75": summarize_group_stat(keys, stats, "hardLayer75")}
            for month, keys in sorted(day_keys_by_month.items())
        },
        "dailyStats": {d: stats[d] for d in days},
        "unmappedThemeKeys": {k: names[k] for k in unmapped_keys},
        "qualityFlags": flags,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(f"report written: {out_path}")
    for calib in CALIBERS:
        row = report["calibers"][calib]
        print(
            f"[{calib}] n={row.get('n')} Q5-Q1={row.get('q5MinusQ1Avg')} negWin={row.get('negSpreadWinRate')} "
            f"IC={row.get('icAvg')} icNeg={row.get('icNegativeShare')} {row.get('status')}"
        )
    hl = report["hardLayer75"]
    hp = report["highPressure90"]
    print(f"[hardLayer75] {hl}")
    print(f"[highPressure90] {hp}")
    for field, row in report["caliberCrossCorr"].items():
        print(f"[{field}] {row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
