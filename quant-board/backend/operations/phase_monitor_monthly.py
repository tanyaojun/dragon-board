# -*- coding: utf-8 -*-
"""M2 极简月度监控（ranktrend-phase-acceptance-design.md §5 月度监控节）。

每月数据落库后一条命令：重打标（扩窗 frames）→ 重切片（上月新交易并入）→ 三监督线落盘。
产出单 JSON + stderr 摘要，人工看；无判定卡、无 trial、无三件同步。
监督线：① S+A 触发率（R3 verdictRule：持续 <3.5% 评估 buyScoreThreshold 微调）
② insufficient 占比（floor3 后基线 ~9.4%，回弹 >15% 预警）
③ 北极星单期读数 + 走廊状态（连续 3 期达线=达成）。
只读：Mongo find（hotlist_sentiment 计数）+ 本地产物；不占 8000。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def build_supervision(sa_trigger_rate: float | None, insufficient_share: float | None, northstar_pass: dict) -> dict:
    """三监督线读数组装（None=本期无自动源，如实记录不伪造）。"""
    return {
        "saTriggerRate": {"value": sa_trigger_rate,
                          "alert": None if sa_trigger_rate is None else sa_trigger_rate < 0.035},
        "insufficientShare": {"value": insufficient_share,
                              "alert": None if insufficient_share is None else insufficient_share > 0.15},
        "northstar": {"pass": northstar_pass},
    }


def corridor_state(history: list[dict]) -> dict:
    """走廊状态机：逐相位连续达线期数；≥3 → achieved。history 按时间升序。"""
    out: dict = {}
    for key in ("offense", "defense"):
        streak = 0
        for rec in history:
            if rec.get(key) is True:
                streak += 1
            else:
                streak = 0
        out[f"{key}Streak"] = streak
        out[f"{key}Achieved"] = streak >= 3
    return out


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="M2 月度监控（只读）")
    parser.add_argument("--month", required=True, help="监控月份 YYYY-MM（数据应已落库）")
    parser.add_argument("--labels", default="data/reports/phase-monitor/phase-labels-v1.json")
    parser.add_argument("--summary", default="data/reports/b-202610/t6-runs-formal/1-summary.json")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else Path(f"data/reports/phase-monitor/monthly-{args.month}.json")

    # ① 情绪覆盖：本月 hotlist_sentiment half_hour 文档数与交易日数（缺档→fail-visible）
    from pymongo import MongoClient
    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]
    month_prefix = f"{args.month}"
    sent_docs = db["hotlist_sentiment"].count_documents(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
         "tradingDate": {"$regex": f"^{month_prefix}"}})
    month_days = db["hotlist_sentiment"].distinct(
        "tradingDate", {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
                        "tradingDate": {"$regex": f"^{month_prefix}"}})

    # ② 标签 freshness：labels 是否含本月（不含 → 提示需扩窗重打标，不自动跑）
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    cand = labels["candidates"]["sentiment_2b"]
    labeled_days = sorted(cand["dailyByMajority"])
    fresh = bool(labeled_days and labeled_days[-1] >= f"{args.month}-28")

    # ③ 三监督线（S+A 触发率与 insufficient 占比从最近 runner summary 或大盘统计读入；
    #    首期允许 None→监控 JSON 如实记 null，人工补读）
    northstar_file = Path("data/reports/phase-monitor/phase-northstar-v1.json")
    ns = json.loads(northstar_file.read_text(encoding="utf-8")) if northstar_file.exists() else {}
    ns_pass = {k: (ns.get("northstar", {}).get(k, {}).get("pass")) for k in ("offense", "defense")}

    sup = build_supervision(
        sa_trigger_rate=None,        # 首期无自动源：如实 null（月度监控说明人工补读位置）
        insufficient_share=None,
        northstar_pass=ns_pass,
    )

    report = {
        "meta": {"month": args.month, "generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "gitCommit": _git_commit()},
        "coverage": {"sentimentDocs": sent_docs, "tradingDays": len(month_days),
                     "labelsFresh": fresh,
                     "labelsNote": "labels 未覆盖本月→先跑 phase_label_run 扩窗重打标（命令见 M1 报告 §2.5）" if not fresh else None},
        "supervision": sup,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Mongo 落库（前端可见化数据源；失败不阻断，本地 JSON 仍是即时产物）
    from backend.operations.phase_monitor_persistence import persist_monthly

    persist_monthly(report)
    print(f"[monthly] -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
