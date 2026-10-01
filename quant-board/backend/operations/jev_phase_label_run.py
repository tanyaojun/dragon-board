# -*- coding: utf-8 -*-
"""SP4-T1 labels v3：jev 同槽 sequence_stage → 两档相位标签（落库即冻结；设计 §13 授权）。

用法（quant-board 目录）：
  ./.venv/Scripts/python.exe -m backend.operations.jev_phase_label_run \
      --out data/reports/phase-monitor/phase-labels-jev-v3.json \
      --fallback data/reports/phase-monitor/phase-labels-v2.json

只读 Mongo hotlist_jev_sentiment（kind=slot, status=ok）+ 可选 labels v2 JSON（fallback 段）。
映射（T-jev 预登记）：start/ferment/climax→offense；ice/retreat→defense；缺档/未知档排除并计数
（fail-visible 不伪造）。冻结纪律：LLM 非确定性 → 产物落盘即冻结，覆写必须 --force 且版本号自增。
fallback 语义（SP4-T1.3 预登记）：消费端对标签缺失槽回退 fallbackLabels[date]（规则 v2 前日口径，
source=rules 标记），再缺失→放行（不错杀）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# T-jev 口径对比（jev-phase-caliber.json）预登记映射；改动=显式版本升级
STAGE_TO_TIER = {
    "start": "offense", "ferment": "offense", "climax": "offense",
    "ice": "defense", "retreat": "defense",
}
TIERS = ("offense", "defense")
FALLBACK_SOURCE_TAG = "rules_sentiment_2b_60_prevday"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def tier_of_stage(stage: object) -> str | None:
    """五档→两档映射；未知/缺档 → None（调用方计数排除）。"""
    return STAGE_TO_TIER.get(str(stage or ""))


def build_slot_labels(docs: list[dict]) -> tuple[dict[str, str], dict]:
    """jev 槽位文档 → {date|slot: 两档} 标签与覆盖统计（纯函数）。"""
    labels: dict[str, str] = {}
    stats = {"jevSlotDocs": 0, "okDocs": 0, "used": 0,
             "skippedNotOk": 0, "skippedMissingStage": 0, "skippedUnknownStage": 0}
    days: set[str] = set()
    for doc in docs:
        stats["jevSlotDocs"] += 1
        if str(doc.get("kind") or "") != "slot":
            continue
        if str(doc.get("status") or "") != "ok":
            stats["skippedNotOk"] += 1
            continue
        stats["okDocs"] += 1
        day, slot = str(doc.get("tradingDate") or ""), str(doc.get("slotTime") or "")
        if not day or not slot:
            stats["skippedMissingStage"] += 1
            continue
        choice = ((doc.get("answers") or {}).get("sequence_stage") or {}).get("choice")
        if not str(choice or ""):
            stats["skippedMissingStage"] += 1
            continue
        tier = tier_of_stage(choice)
        if tier is None:
            stats["skippedUnknownStage"] += 1
            continue
        labels[f"{day}|{slot}"] = tier
        days.add(day)
        stats["used"] += 1
    stats["days"] = len(days)
    return labels, stats


def extract_fallback_labels(v2_report: dict) -> dict[str, str]:
    """labels v2（规则口径）→ fallback 段：sentiment_2b dailyByPrevDay（前日定相，as-of 安全）。"""
    cand = (v2_report.get("candidates") or {}).get("sentiment_2b") or {}
    daily = cand.get("dailyByPrevDay") or {}
    return {str(d): str(p) for d, p in daily.items() if p in TIERS}


def next_version(existing_text: str | None) -> int:
    """冻结纪律：已存在产物 → 版本自增；无 → 1。"""
    if not existing_text:
        return 1
    try:
        return int((json.loads(existing_text).get("meta") or {}).get("version") or 0) + 1
    except (ValueError, TypeError):
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="SP4-T1 jev 相位标签（labels v3，只读+冻结落盘）")
    parser.add_argument("--out", required=True, help="输出 JSON 路径")
    parser.add_argument("--fallback", default="", help="labels v2 JSON 路径（规则口径 fallback 段）")
    parser.add_argument("--force", action="store_true", help="覆写已存在产物（版本号自增，冻结纪律）")
    args = parser.parse_args()

    from pymongo import MongoClient

    out = Path(args.out)
    existing = out.read_text(encoding="utf-8") if out.exists() else None
    if existing and not args.force:
        print(f"[jev-label] 产物已存在（冻结）：{out}；覆写需 --force（版本自增）", file=sys.stderr)
        return 2

    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]
    docs = list(db["hotlist_jev_sentiment"].find(
        {"datasetId": "dragonboard_live"},
        {"kind": 1, "status": 1, "tradingDate": 1, "slotTime": 1, "answers.sequence_stage.choice": 1},
    ))
    labels, stats = build_slot_labels(docs)
    print(f"[jev-label] docs={stats['jevSlotDocs']} ok={stats['okDocs']} used={stats['used']} "
          f"days={stats['days']} notOk={stats['skippedNotOk']} missingStage={stats['skippedMissingStage']} "
          f"unknownStage={stats['skippedUnknownStage']}", file=sys.stderr)

    fallback: dict[str, str] = {}
    if args.fallback:
        fb_path = Path(args.fallback)
        if fb_path.exists():
            fallback = extract_fallback_labels(json.loads(fb_path.read_text(encoding="utf-8")))
            print(f"[jev-label] fallback days={len(fallback)} source={FALLBACK_SOURCE_TAG}", file=sys.stderr)
        else:
            print(f"[jev-label] fallback 文件缺失（fail-visible，fallback 段为空）：{fb_path}", file=sys.stderr)

    from collections import Counter

    report = {
        "meta": {
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "gitCommit": _git_commit(),
            "version": next_version(existing),
            "frozen": True,
            "freezeNote": "LLM 非确定性：产物落盘即冻结；重算必须 --force 且版本自增（地图代际纪律）",
            "datasetId": "dragonboard_live",
            "mapping": STAGE_TO_TIER,
            "mappingSource": "T-jev 口径对比（jev-phase-caliber.json，C4 同槽 sequence_stage p=0.0013）",
            "fallbackSource": FALLBACK_SOURCE_TAG if fallback else None,
            "labelTier": "v3-jev-seq-slot",
        },
        "slotLabels": dict(sorted(labels.items())),
        "fallbackLabels": dict(sorted(fallback.items())),
        "coverage": {**stats, "tierDistribution": dict(Counter(labels.values()))},
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[jev-label] v{report['meta']['version']} -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
