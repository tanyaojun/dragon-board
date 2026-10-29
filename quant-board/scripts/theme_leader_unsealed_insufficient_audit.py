# -*- coding: utf-8 -*-
"""v13 立项候选攒样本审计：未封板场景「证据在场仍答 insufficient」率（只读零写入零 token）。

问题（v12 预登记 §9.8 / v13 草案 2026-10-29）：题面「锚缺失如实对待」被模型读成
insufficient 许可——首批实证 3/15 空档而基线行/空间锚行率值在场。

可程序判定口径（与 v13 草案 §3 一致）：
- 样本：leader doc（docKind="leader"、structure.leaderSealedToday=False，未封板场景）
- 续板题证据在场：narrative「结构基线」行含任一出率桶（`率 xx.x%`）
- 空间题证据在场：narrative「空间锚」行含率值
- empty_with_evidence：对应题 choice=insufficient 且证据行在场（立项统计对象）
- 合规 empty：choice=insufficient 且证据行整体缺席（设计内诚实空档，不计入）

门槛（v13 草案 §3）：样本 ≥30 且 empty_with_evidence 率 ≥10% → 建议立项；<5% → 不立项；
5%~10% 或样本 <30 → 再攒一周复核。

用法：PYTHONPATH=. ./.venv/Scripts/python.exe scripts/theme_leader_unsealed_insufficient_audit.py [--days 10]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from typing import Any

RATE_RE = re.compile(r"\d+(?:\.(?:\d+)?)?%")
# 桶率实測格式两种：「次日连板率 76.5%（N 样本）」与「按板块家数[1-2] 24.4%（N 样本）」——
# 数字后直接跟 %，不能锚定「率 」前缀；基线/锚行内除桶率外无其他百分号语义，
# 行内任意百分比即视为出率（2026-10-29 600838 实测修正）。
BASELINE_PREFIX = "结构基线"
ANCHOR_PREFIX = "空间锚"


def _evidence_lines(narrative: str) -> tuple[bool, bool]:
    """(续板题基线行有率值, 空间题锚行有率值)；行缺失/无率值均=False（不插值）。"""
    baseline = anchor = False
    for line in str(narrative or "").splitlines():
        line = line.strip()
        if line.startswith(BASELINE_PREFIX) and RATE_RE.search(line):
            baseline = True
        elif line.startswith(ANCHOR_PREFIX) and RATE_RE.search(line):
            anchor = True
    return baseline, anchor


def audit(db: Any, days: int | None = None) -> dict:
    query: dict = {"docKind": "leader",
                   "structure.leaderSealedToday": False,
                   "status": "ok"}
    if days:
        import time
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S",
                               time.localtime(time.time() - days * 86400))
        query["computedAt"] = {"$gte": cutoff}
    rows = list(db["hotlist_jev_theme_leader_labels"].find(query, {
        "_id": 1, "questionSetVersion": 1, "computedAt": 1, "narrative": 1,
        "answers": 1, "gate": 1}))
    stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"unsealed_total": 0, "cont_insufficient": 0, "cont_empty_with_ev": 0,
                 "head_insufficient": 0, "head_empty_with_ev": 0,
                 "cont_ev_present": 0, "head_ev_present": 0})
    details: list[dict] = []
    for doc in rows:
        ver = str(doc.get("questionSetVersion") or "?")
        s = stats[ver]
        s["unsealed_total"] += 1
        baseline_ev, anchor_ev = _evidence_lines(doc.get("narrative") or "")
        answers = doc.get("answers") or {}
        cont = (answers.get("leader_nextday_continue") or {}).get("choice")
        head = (answers.get("leader_headroom") or {}).get("choice")
        if baseline_ev:
            s["cont_ev_present"] += 1
        if anchor_ev:
            s["head_ev_present"] += 1
        if cont == "insufficient":
            s["cont_insufficient"] += 1
            if baseline_ev:
                s["cont_empty_with_ev"] += 1
                details.append({"date": str(doc.get("computedAt") or "")[:10],
                                "id": doc.get("_id"), "q": "continue",
                                "ev": "结构基线行有率值仍答 insufficient"})
        if head == "insufficient":
            s["head_insufficient"] += 1
            if anchor_ev:
                s["head_empty_with_ev"] += 1
                details.append({"date": str(doc.get("computedAt") or "")[:10],
                                "id": doc.get("_id"), "q": "headroom",
                                "ev": "空间锚行有率值仍答 insufficient"})
    # 合并两题口径（题次为单位）：证据在场题次 = 基线在场 + 锚在场；空档 = 两题 empty_with_ev 之和
    report = {"window_days": days, "details": details, "byVersion": {}}
    for ver, s in sorted(stats.items()):
        trials = s["cont_ev_present"] + s["head_ev_present"]
        empty = s["cont_empty_with_ev"] + s["head_empty_with_ev"]
        rate = (empty / trials) if trials else None
        verdict = ("样本不足（题次 <30），继续攒"
                   if trials < 30 else
                   ("建议 v13 立项（≥10%）" if rate is not None and rate >= 0.10 else
                    ("再攒一周复核（5%~10%）" if rate is not None and rate >= 0.05 else
                     "不建议立项（<5%）")))
        report["byVersion"][ver] = {**s, "evidence_trials": trials,
                                    "empty_with_evidence": empty,
                                    "rate": round(rate, 4) if rate is not None else None,
                                    "verdict": verdict}
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None, help="只统计最近 N 天（缺省全史）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（默认人类可读）")
    args = ap.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    report = audit(db, days=args.days)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return
    print(f"窗口：最近 {args.days or '全部'} 天；口径=v13 草案 §3（未封板场景）\n")
    for ver, s in report["byVersion"].items():
        print(f"[{ver}] 未封板 doc {s['unsealed_total']} 条 | "
              f"续板题：insufficient {s['cont_insufficient']}（其中证据在场 {s['cont_empty_with_ev']}，"
              f"基线行在场题次 {s['cont_ev_present']}）| "
              f"空间题：insufficient {s['head_insufficient']}（其中证据在场 {s['head_empty_with_ev']}，"
              f"锚行在场题次 {s['head_ev_present']}）")
        print(f"      题次 {s['evidence_trials']}，empty_with_evidence {s['empty_with_evidence']}"
              f"（率 {s['rate']}）→ {s['verdict']}\n")
    for d in report["details"]:
        print(f"  - {d['date']} {d['id']} [{d['q']}] {d['ev']}")


if __name__ == "__main__":
    sys.exit(main())
