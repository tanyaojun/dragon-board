"""因子口径收敛批 TaskB：区分度与边际贡献研究 runner（只读，不写业务库）。

回答三件事（设计 `docs/theme-module/2026-09-27-themetrend-factor-convergence-design.md`）：
  1. 联动度/持续性（含 D3 对照口径）在 v12 六维合成分之上是否仍有边际信息
     （marginal_spearman_ic：候选秩对基准秩 OLS 残差后与 T+1 的秩相关）；
  2. 数值先验通道 ablation：v12 六维合成分 vs 动量 v2 score 的区分度对比
     （rotationScore 需引擎逐槽回放，登记 Phase 4 前置，本 runner 不含）；
  3. 动量 v2 综合分与子维度的逐维度区分度（供"替换还是并列"终判参考）。

口径：
  - 横截面 = daily 类型收盘槽 sector rows（15:30 优先/15:00 回退，R1 锚点）；
  - forward = 同题材 T+1 change（百分数单位，末日整日丢弃）；
  - D3 = momentumScore 日截面 Top 五分位成员连续保持计数（factor_series.top_membership_streak）；
  - v12 基准合成分 = 落库字段按 v12 权重重构（heat 缺失按 0 计并计数，近似口径）；
  - crowding 分位与 v2 取自 theme_daily_factors（Task1/A 生产回填）。

fail-visible：缺失字段成对剔除不伪造；分位/维度不足按 None 参与统计并计数。

用法（非交易时段）：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_theme_factor_marginal
      [--start 2026-07-06] [--end 2026-09-24]
      [--out data/reports/theme-factor-marginal.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.analysis.theme.factor_series import top_membership_streak
from backend.analysis.theme.rank_ic import marginal_spearman_ic, spearman_rank_ic
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.data.repositories.theme_daily_factor_repository import ThemeDailyFactorRepository
from backend.services.backtest_service import _close_slot_rows_by_day

DATASET_ID = "dragonboard_live"
V12_WEIGHTS = {
    "heat": 0.25,
    "momentum": 0.25,
    "breadth": 0.15,
    "fund": 0.15,
    "leadership": 0.20,
    "crowding": -0.15,
}
CANDIDATES = (
    "correlationScore",
    "persistenceScore",
    "d3Streak",
    "heatLevelStreak",
    "crowdingPercentile",
    "v2Score",
    "v2NearHigh",
    "v2WindowMomentum",
    "v2Breadth",
    "v2FlowVolume",
)


def load_cross_sections(
    repo: MongoRepository, start: str, end: str
) -> dict[str, dict[str, dict[str, Any]]]:
    """daily 收盘槽题材横截面 {date: {themeKey: 字段字典}}，双键（entityKey/entityName）。"""
    res = repo.list_snapshot_sector_rows(
        DATASET_ID, start_date=start, end_date=end,
        snapshot_type="daily", entity_type="hot_theme", sort="asc",
    )
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for d, rows in _close_slot_rows_by_day(res.get("rows") or []).items():
        day: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = row.get("entityKey") or row.get("entityName")
            if not key:
                continue
            day[str(key)] = {
                "entityName": str(row.get("entityName") or ""),
                "change": _f(row.get("change")),
                "heatLevel": _f(row.get("heatLevel")),
                "momentumScore": _f(row.get("momentumScore")),
                "breadthScore": _f(row.get("breadthScore")),
                "fundScore": _f(row.get("fundScore")),
                "leadershipScore": _f(row.get("leadershipScore")),
                "crowdingRisk": _f(row.get("crowdingRisk")),
                "correlationScore": _f(row.get("correlationScore")),
                "persistenceScore": _f(row.get("persistenceScore")),
            }
        if day:
            out[d] = day
    return out


def _f(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def load_stored_factors(
    repo: ThemeDailyFactorRepository, start: str, end: str
) -> dict[str, dict[str, dict[str, Any]]]:
    """theme_daily_factors → {date: {themeKey: {crowdingPercentile, v2*}}}（双键索引）。"""
    out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    missing_v2 = 0
    for doc in repo.list_range(DATASET_ID, start, end):
        factors = doc.get("factors") if isinstance(doc.get("factors"), dict) else {}
        v2 = factors.get("momentumV2") if isinstance(factors.get("momentumV2"), dict) else {}
        payload = {
            "crowdingPercentile": _f(factors.get("crowdingPercentile")),
            "heatLevelStreak": _f(factors.get("heatLevelStreak")),
            "v2Score": _f(v2.get("score")),
            "v2NearHigh": _f(v2.get("nearHigh")),
            "v2WindowMomentum": _f(v2.get("windowMomentum")),
            "v2Breadth": _f(v2.get("breadth")),
            "v2FlowVolume": _f(v2.get("flowVolume")),
        }
        if v2.get("score") is None:
            missing_v2 += 1
        d = str(doc.get("tradingDate"))
        for key in {str(doc.get("themeId") or ""), str(doc.get("themeName") or "")} - {""}:
            out[d][key] = payload
    return dict(out), missing_v2


def build_d3_streaks(
    cross_sections: dict[str, dict[str, dict[str, Any]]], top_ratio: float = 0.2
) -> dict[str, dict[str, int | None]]:
    """D3：逐日 momentumScore Top 五分位成员的连续保持计数 {date: {themeKey: streak}}。"""
    top_by_day: dict[str, set[str]] = {}
    observed_by_day: dict[str, set[str]] = {}
    for d, themes in cross_sections.items():
        scored = [
            (key, row["momentumScore"]) for key, row in themes.items()
            if row["momentumScore"] is not None
        ]
        observed_by_day[d] = {key for key, _ in scored}
        ranked = sorted(scored, key=lambda kv: -kv[1])
        top_n = max(1, int(len(ranked) * top_ratio))
        top_by_day[d] = {key for key, _ in ranked[:top_n]}
    streaks: dict[str, dict[str, int | None]] = {}
    for key in observed_by_day and sorted({k for day in observed_by_day.values() for k in day}):
        streaks[key] = top_membership_streak(top_by_day, observed_by_day, key)
    return streaks


def build_v12_composite(row: dict[str, Any]) -> float:
    """v12 六维合成分（落库字段重构，heat 缺失按 0 计——近似口径，与 trend.py 消费一致）。"""
    heat = row["heatLevel"] if row["heatLevel"] is not None else 0.0
    return (
        heat * V12_WEIGHTS["heat"]
        + (row["momentumScore"] or 0.0) * V12_WEIGHTS["momentum"]
        + (row["breadthScore"] or 0.0) * V12_WEIGHTS["breadth"]
        + (row["fundScore"] or 0.0) * V12_WEIGHTS["fund"]
        + (row["leadershipScore"] or 0.0) * V12_WEIGHTS["leadership"]
        + (row["crowdingRisk"] or 0.0) * V12_WEIGHTS["crowding"]
    )


def _quintile_spread(pairs: list[tuple[float, float]]) -> dict[str, Any]:
    ranked = sorted(pairs, key=lambda kv: kv[0])
    n = len(ranked)
    q = max(1, n // 5)
    q1 = [c for _, c in ranked[:q]]
    q5 = [c for _, c in ranked[-q:]]
    return {"n": n, "q5MinusQ1": sum(q5) / len(q5) - sum(q1) / len(q1)}


def main() -> int:
    parser = argparse.ArgumentParser(description="因子口径收敛批 TaskB：边际贡献研究 runner")
    parser.add_argument("--start", default="2026-07-06")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--out", default="data/reports/theme-factor-marginal.json")
    args = parser.parse_args()

    db = get_runtime_mongodb_database()
    repo = MongoRepository(db)
    factor_repo = ThemeDailyFactorRepository(db)

    cross_sections = load_cross_sections(repo, args.start, args.end)
    if not cross_sections:
        print(json.dumps({"status": "insufficient", "reason": "no_theme_cross_sections"}, ensure_ascii=False))
        return 2
    stored, missing_v2 = load_stored_factors(factor_repo, args.start, args.end)
    streaks = build_d3_streaks(cross_sections)

    flags: list[str] = []
    if missing_v2:
        flags.append(f"v2_score_missing_docs:{missing_v2}")

    days = sorted(cross_sections)
    # 逐日候选面板：{date: {themeKey: {candidate: value|None, baseline, forward}}}
    panel: dict[str, dict[str, dict[str, Any]]] = {}
    for i, d in enumerate(days):
        nxt = days[i + 1] if i + 1 < len(days) else None
        for key, row in cross_sections[d].items():
            forward = cross_sections[nxt][key]["change"] if nxt and key in cross_sections[nxt] else None
            stored_row = stored.get(d, {}).get(key) or {}
            entry: dict[str, Any] = {
                "baseline": build_v12_composite(row),
                "forward": forward,
                "correlationScore": row["correlationScore"],
                "persistenceScore": row["persistenceScore"],
                "d3Streak": (streaks.get(key) or {}).get(d),
                "heatLevelStreak": stored_row.get("heatLevelStreak"),
                "crowdingPercentile": stored_row.get("crowdingPercentile"),
                "v2Score": stored_row.get("v2Score"),
                "v2NearHigh": stored_row.get("v2NearHigh"),
                "v2WindowMomentum": stored_row.get("v2WindowMomentum"),
                "v2Breadth": stored_row.get("v2Breadth"),
                "v2FlowVolume": stored_row.get("v2FlowVolume"),
            }
            panel.setdefault(d, {})[key] = entry

    def evaluate(candidate: str, use_marginal: bool) -> dict[str, Any]:
        day_ics: list[float] = []
        day_marginal_ics: list[float] = []
        spreads: list[float] = []
        by_month: dict[str, list[float]] = defaultdict(list)
        for d in sorted(panel):
            entries = panel[d]
            values = [e.get(candidate) for e in entries.values()]
            baselines = [e["baseline"] for e in entries.values()]
            forwards = [e["forward"] for e in entries.values()]
            paired = [(v, b, f) for v, b, f in zip(values, baselines, forwards) if v is not None and f is not None]
            if len(paired) >= 5:
                ic = spearman_rank_ic([p[0] for p in paired], [p[2] for p in paired])
                if ic is not None:
                    day_ics.append(ic)
                    by_month[d[:7]].append(ic)
                spread = _quintile_spread([(p[0], p[2]) for p in paired])
                if spread["n"] >= 5:
                    spreads.append(spread["q5MinusQ1"])
            if use_marginal:
                mic = marginal_spearman_ic(values, baselines, forwards)
                if mic is not None:
                    day_marginal_ics.append(mic)

        def _avg(xs: list[float]) -> float | None:
            return round(sum(xs) / len(xs), 6) if xs else None

        month_summary = {
            month: {
                "n": len(ics),
                "icAvg": _avg(ics),
                "icNegativeShare": round(sum(1 for x in ics if x < 0) / len(ics), 4) if ics else None,
            }
            for month, ics in sorted(by_month.items())
        }
        return {
            "icDays": len(day_ics),
            "icAvg": _avg(day_ics),
            "icNegativeShare": round(sum(1 for x in day_ics if x < 0) / len(day_ics), 4) if day_ics else None,
            "q5q1Avg": _avg(spreads),
            "marginalIcDays": len(day_marginal_ics),
            "marginalIcAvg": _avg(day_marginal_ics),
            "byMonth": month_summary,
        }

    report: dict[str, Any] = {
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "dataset": DATASET_ID,
            "window": {"start": args.start, "end": args.end},
            "hypothesis": "联动/持续/D3/拥挤分位/动量v2 在 v12 六维合成分之上是否仍有边际信息；先验通道 v12合成分 vs v2Score",
            "baselineNote": "v12 基准合成分由落库字段按 v12 权重重构（heat 缺失按 0 计，近似口径）",
            "directionNote": "change 为百分数单位；Q5=因子值最高组；rotationScore 需引擎逐槽回放，登记 Phase 4 前置不含于此",
        },
        "coverage": {
            "evalDays": len(days),
            "themeKeys": len({key for day in panel.values() for key in day}),
            "storedFactorDocs": sum(len(day) for day in stored.values()),
        },
        "candidates": {name: evaluate(name, use_marginal=True) for name in CANDIDATES},
        "priorChannel": {
            "v12Composite": evaluate("baseline", use_marginal=False),
            "momentumV2Score": evaluate("v2Score", use_marginal=False),
        },
        "qualityFlags": flags,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"report written: {out_path}")
    header = f"{'candidate':<18}{'icAvg':>9}{'icNeg':>7}{'q5q1':>9}{'mIC':>9}{'mDays':>6}"
    print(header)
    for name, row in report["candidates"].items():
        print(
            f"{name:<18}{str(row['icAvg']):>9}{str(row['icNegativeShare']):>7}"
            f"{str(row['q5q1Avg']):>9}{str(row['marginalIcAvg']):>9}{row['marginalIcDays']:>6}"
        )
    pc = report["priorChannel"]
    print(f"[priorChannel] v12Composite ic={pc['v12Composite']['icAvg']} | v2Score ic={pc['momentumV2Score']['icAvg']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
