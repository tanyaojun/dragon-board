"""Phase R1：题材轮动度量 + mainTheme 判定链描述性实证（只读，不写库）。

从真实 MongoDB 加载 sector rows（收盘槽）/ stock rows / limitSummary 帧 →
① 轮动度量统计（全窗 + 9 月弱势段切片）
② mainTheme 新旧判定差异分布（新=MainlineScore 判定链，旧=themes[0]）
③ MainlineScore 权重敏感性小扫描（4 组权重对比 Top3 名单差异）
④ 守恒 vs 重复涨停计数失真比对
⑤ 9 月弱势段情绪背景（limitSummary 每日 15:30 帧）
→ JSON 报告输出到 data/reports/。

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_theme_rotation_r1
      [--start 2026-07-06] [--end 2026-09-24]
      [--weak-start 2026-09-01] [--weak-end 2026-09-24]
      [--out data/reports/theme-r1-rotation.json]

资源纪律：只读、无 optimization API、单进程本地计算；题材域研究，
非 ranktrend 决策链，不受 ranktrend 冻结窗守卫约束（题材域冻结纪律
在 Phase 4 verdict 阶段另行建立）。
fail-visible：缺日/缺槽/缺因子如实打标输出，不伪造 0，不中断。
样本量声明：弱势段约 14 个交易日，结论为探索性描述统计，非正式判定。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from backend.analysis.theme.mainline_assignment import (
    DEFAULT_MAINLINE_WEIGHTS,
    assign_main_theme,
    mainline_scores,
)
from backend.analysis.theme.rotation.measures import (
    dedup_limit_count,
    mainline_persistence,
    rank_entropy,
    rotation_speed,
)
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database

DATASET_ID = "dragonboard_live"
TOP_N = 10
CLOSE_SLOTS = ("15:30", "15:00")  # Phase 0：15:30 THS 池最全，15:00 偶发空洞

# 权重敏感性扫描组（研究参数，非生产默认）
WEIGHT_GRID = {
    "default_heat_heavy": DEFAULT_MAINLINE_WEIGHTS,
    "equal": {k: 0.25 for k in DEFAULT_MAINLINE_WEIGHTS},
    "momentum_heavy": {"heatLevel": 0.15, "momentumScore": 0.50, "ztCount": 0.20, "fundScore": 0.15},
    "limit_count_heavy": {"heatLevel": 0.20, "momentumScore": 0.20, "ztCount": 0.45, "fundScore": 0.15},
}


def load_close_slot_series(
    repo: MongoRepository, start: str, end: str
) -> dict[str, Any]:
    """每交易日收盘槽 sector rows 横截面（15:30 优先，回退 15:00，均缺打标）。"""
    res = repo.list_snapshot_sector_rows(
        DATASET_ID, start_date=start, end_date=end, entity_type="hot_theme", sort="asc"
    )
    by_day_slot: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in res["rows"]:
        d, s = str(row.get("tradingDate")), str(row.get("slotTime"))
        by_day_slot.setdefault(d, {}).setdefault(s, []).append(row)
    series: dict[str, dict[str, Any]] = {}
    for d in sorted(by_day_slot):
        slots = by_day_slot[d]
        rows = next((slots[s] for s in CLOSE_SLOTS if s in slots), None)
        if not rows:
            series[d] = {"status": "insufficient", "reason": "close_slot_missing", "rows": []}
            continue
        series[d] = {
            "status": "ok",
            "slot": str(rows[0].get("slotTime")),
            "rows": rows,
        }
    if not series:
        return {"status": "insufficient", "reason": "no_sector_rows", "series": {}}
    return {"status": "ok", "series": series}


def _sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows, key=lambda r: r.get("rank") if isinstance(r.get("rank"), int) else 10**9
    )


def build_top_sets(
    series_inner: dict[str, dict[str, Any]],
) -> tuple[list[set[str]], dict[str, str | None]]:
    """每日 TopN 题材集合与 Top1 主线（缺失日 = 空集合 / None）。

    series_inner: load_close_slot_series 返回值中的 "series" 内层字典。
    """
    tops: list[set[str]] = []
    mainline: dict[str, str | None] = {}
    for d in sorted(series_inner):
        info = series_inner[d]
        if info["status"] != "ok":
            tops.append(set())
            mainline[d] = None
            continue
        ordered = _sorted_rows(info["rows"])
        top = {str(r.get("entityKey")) for r in ordered[:TOP_N] if r.get("entityKey") is not None}
        tops.append(top)
        mainline[d] = str(ordered[0].get("entityKey")) if ordered and ordered[0].get("entityKey") is not None else None
    return tops, mainline


def build_top_counts(series_inner: dict[str, dict[str, Any]]) -> dict[str, int]:
    """每题材进入 TopN 的天数。series_inner 同 build_top_sets。"""
    counts: dict[str, int] = {}
    for info in series_inner.values():
        if info["status"] != "ok":
            continue
        for r in _sorted_rows(info["rows"])[:TOP_N]:
            k = r.get("entityKey")
            if k is not None:
                counts[str(k)] = counts.get(str(k), 0) + 1
    return counts


def slice_series(series: dict[str, Any], start: str, end: str) -> dict[str, Any]:
    return {
        "status": series["status"],
        "series": {d: v for d, v in series["series"].items() if start <= d <= end},
    }


def normalize_theme_names(themes: Any) -> list[str]:
    out: list[str] = []
    for t in themes or []:
        if isinstance(t, dict):
            t = t.get("name") or t.get("id")
        if t:
            out.append(str(t))
    return out


def diff_main_theme(
    repo: MongoRepository, start: str, end: str, series: dict[str, Any]
) -> dict[str, Any]:
    """新旧 mainTheme 判定差异（收盘槽 stock rows：新=判定链，旧=themes[0]）。"""
    res = repo.list_snapshot_stock_rows(
        DATASET_ID,
        start_date=start,
        end_date=end,
        sort="asc",
        fields=[
            "tradingDate", "slotTime", "code", "name", "themes",
            "mainTheme", "boardHeight", "change", "limitUpPool", "reason",
        ],
    )
    by_day: dict[str, list[dict[str, Any]]] = {}
    for r in res["rows"]:
        if str(r.get("slotTime")) in CLOSE_SLOTS:
            by_day.setdefault(str(r.get("tradingDate")), []).append(r)
    days_out: dict[str, Any] = {}
    total = same = fallback_n = tie_n = 0
    for d, srows in sorted(by_day.items()):
        info = series["series"].get(d)
        if not info or info["status"] != "ok":
            continue
        scores = mainline_scores(info["rows"])
        d_total = d_same = 0
        reasons: dict[str, int] = {}
        for r in srows:
            themes = normalize_theme_names(r.get("themes"))
            if not themes:
                continue
            limit_up = bool(r.get("limitUpPool"))
            # 涨停原因文本来自 stock rows 的 reason 字段（THS 涨停池 reasonType 透传）
            reason_text = str(r.get("reason") or "") if limit_up else None
            res_a = assign_main_theme(
                themes, scores,
                reason_text=reason_text,
                fallback_theme=str(r.get("mainTheme") or themes[0]),
            )
            old = str(r.get("mainTheme") or themes[0])
            d_total += 1
            total += 1
            if res_a["mainTheme"] == old:
                d_same += 1
                same += 1
            reasons[res_a["mainThemeReason"]] = reasons.get(res_a["mainThemeReason"], 0) + 1
            if res_a["mainThemeReason"] == "fallback":
                fallback_n += 1
            elif res_a["mainThemeReason"] == "tie_break_reason":
                tie_n += 1
        days_out[d] = {
            "total": d_total,
            "same": d_same,
            "diff_rate": round(1 - d_same / d_total, 4) if d_total else None,
            "reasons": reasons,
        }
    return {
        "days": days_out,
        "overall": {
            "total": total,
            "same": same,
            "diff_rate": round(1 - same / total, 4) if total else None,
            "fallback_count": fallback_n,
            "tie_break_count": tie_n,
        },
    }


def weight_sensitivity(series: dict[str, Any]) -> dict[str, Any]:
    """4 组权重下 Top3 名单的平均日间 Jaccard 重合 + 与默认组名单差异天数。"""
    daily_scores = {
        w_name: {
            d: mainline_scores(info["rows"], weights=w)
            for d, info in series["series"].items()
            if info["status"] == "ok"
        }
        for w_name, w in WEIGHT_GRID.items()
    }
    top3 = {
        w_name: {
            d: [t for t, _ in sorted(sc.items(), key=lambda kv: kv[1].get("score") or -1, reverse=True)[:3]]
            for d, sc in daily_scores[w_name].items()
        }
        for w_name in WEIGHT_GRID
    }
    out: dict[str, Any] = {}
    base = "default_heat_heavy"
    for w_name in WEIGHT_GRID:
        days = sorted(top3[w_name])
        jaccards = [
            len(set(top3[w_name][a]) & set(top3[w_name][b]))
            / max(len(set(top3[w_name][a]) | set(top3[w_name][b])), 1)
            for a, b in zip(days, days[1:])
        ]
        diffs = [len(set(top3[w_name][d]) ^ set(top3[base][d])) for d in days]
        out[w_name] = {
            "top3_mean_jaccard": round(sum(jaccards) / len(jaccards), 4) if jaccards else None,
            "top3_days_diff_from_default": sum(1 for x in diffs if x > 0),
            "n_days": len(days),
        }
    return out


def dedup_limit_stats(
    repo: MongoRepository, start: str, end: str, series: dict[str, Any]
) -> dict[str, Any]:
    """守恒 vs 重复涨停计数（以判定链归属为 owner）。"""
    res = repo.list_snapshot_stock_rows(
        DATASET_ID, start_date=start, end_date=end, sort="asc",
        fields=["tradingDate", "slotTime", "code", "themes", "mainTheme", "limitUpPool"],
    )
    repeat_by_theme: dict[str, set[str]] = {}
    owner: dict[str, str] = {}
    day_map = {d: info for d, info in series["series"].items() if info["status"] == "ok"}
    day_scores = {d: mainline_scores(info["rows"]) for d, info in day_map.items()}
    for r in res["rows"]:
        if str(r.get("slotTime")) not in CLOSE_SLOTS or not r.get("limitUpPool"):
            continue
        themes = normalize_theme_names(r.get("themes"))
        if not themes:
            continue
        res_a = assign_main_theme(
            themes, day_scores.get(str(r.get("tradingDate")), {}), fallback_theme=str(themes[0])
        )
        for t in themes:
            repeat_by_theme.setdefault(t, set()).add(str(r.get("code")))
        if res_a["mainTheme"]:
            owner[str(r.get("code"))] = res_a["mainTheme"]
    return dedup_limit_count(repeat_by_theme, owner)


def sentiment_background(repo: MongoRepository, start: str, end: str) -> list[dict[str, Any]]:
    """弱势段每日 15:30 帧 limitSummary 情绪背景。"""
    out: list[dict[str, Any]] = []
    for doc in repo.db["snapshot_frames"].find(
        {"tradingDate": {"$gte": start, "$lte": end}, "slotTime": "15:30"}
    ).sort("tradingDate", 1):
        ls = doc.get("limitSummary") or {}
        z, cb = ls.get("zhaban") or {}, ls.get("continuousBoards") or {}
        out.append({
            "tradingDate": str(doc.get("tradingDate")),
            "ztCount": z.get("ztCount"),
            "zhaban_rate": z.get("rate"),
            "fengban_rate": z.get("fengbanRate"),
            "max_board": cb.get("maxBoard"),
        })
    return out


def run_stats(series: dict[str, Any]) -> dict[str, Any]:
    inner = series["series"]
    tops, mainline = build_top_sets(inner)
    return {
        "n_days": len([d for d in inner if inner[d]["status"] == "ok"]),
        "missing_days": [d for d in inner if inner[d]["status"] != "ok"],
        "rotation_speed": rotation_speed(tops),
        "mainline_persistence": mainline_persistence(mainline),
        "rank_entropy": rank_entropy(build_top_counts(inner)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-07-06")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--weak-start", default="2026-09-01")
    parser.add_argument("--weak-end", default="2026-09-24")
    parser.add_argument("--out", default="data/reports/theme-r1-rotation.json")
    args = parser.parse_args()

    repo = MongoRepository(get_runtime_mongodb_database())
    full = load_close_slot_series(repo, args.start, args.end)
    if full["status"] != "ok":
        print(json.dumps(full, ensure_ascii=False, indent=2))
        return 2
    weak = slice_series(full, args.weak_start, args.weak_end)

    report = {
        "window": {"start": args.start, "end": args.end, "weak": [args.weak_start, args.weak_end]},
        "full_window": run_stats(full),
        "weak_window": run_stats(weak),
        "main_theme_diff": diff_main_theme(repo, args.start, args.end, full),
        "weight_sensitivity": weight_sensitivity(full),
        "dedup_limit": dedup_limit_stats(repo, args.start, args.end, full),
        "sentiment_background": sentiment_background(repo, args.weak_start, args.weak_end),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    fw, ww, diff = report["full_window"], report["weak_window"], report["main_theme_diff"]["overall"]
    print(f"[full] days={fw['n_days']} missing={fw['missing_days']} rot_speed={fw['rotation_speed'].get('mean')} "
          f"switch_rate={fw['mainline_persistence'].get('switch_rate')} entropy={fw['rank_entropy'].get('normalized')}")
    print(f"[weak] days={ww['n_days']} rot_speed={ww['rotation_speed'].get('mean')} "
          f"switch_rate={ww['mainline_persistence'].get('switch_rate')} entropy={ww['rank_entropy'].get('normalized')}")
    print(f"[mainTheme diff] {diff}")
    print(f"report -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
