# -*- coding: utf-8 -*-
"""T6 新旧档位对 regime 的影响 diff（路线 B，emotion-score-design v3 §5.2）。

消费点：`risk.py:151 score += stage_adjust[phase]`，
REGIME_STAGE_ADJUST = {高潮:8, 发酵:5, 启动:0, 退潮:-6, 冰点:-8}（regime 基准 50）。

方法：stage_adjust 是线性查表——档位序列差值等价映射为 regime 分量差值，因此文档层
逐槽量化即可给出全分布（无需完整 replay；候选分层的传播可在需要时用 dry-run 链复核）：
1. 从重算后文档的 `legacyCascadeStage`（级联截面，审计 S7 全量落库）按日因果重放
   `confirm_stage` 重建旧确认投影（审计 S8）；
2. 逐槽 diff：adjust[新 stage] − adjust[旧确认投影] 全分布 + EOD 层单独统计；
3. 分歧案例明细随 --json 落盘。

只读：全程 find，不写任何 collection。
用法：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.emotion_score_stage_adjust_diff \
      [--json .tmp/emotion-score-stage-adjust-diff.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from typing import Any

from backend.analysis.hotlist.stage_confirm import confirm_stage

# 与 risk.py REGIME_STAGE_ADJUST 保持一致（默认配置路径；c.regimeStageAdjust 覆盖值另行对照）
STAGE_ADJUST = {"高潮": 8.0, "发酵": 5.0, "启动": 0.0, "退潮": -6.0, "冰点": -8.0}


def _load_docs(db: Any, dataset_id: str, snapshot_type: str) -> list[dict]:
    rows = db["hotlist_sentiment"].find(
        {"datasetId": dataset_id, "snapshotType": snapshot_type},
        {"_id": 1, "tradingDate": 1, "slotTime": 1, "anchoredSlotTime": 1,
         "stage": 1, "rawStage": 1, "legacyCascadeStage": 1},
    )
    return [dict(row) for row in rows if row.get("tradingDate")]


def _rebuild_old_confirmed_by_prefix(slots: list[tuple[str, str]]) -> dict[str, str]:
    """逐槽前缀重放 confirm_stage：返回 slotTime -> 该槽时点的旧确认投影。"""
    out: dict[str, str] = {}
    for index in range(len(slots)):
        confirmed, _ = confirm_stage(slots[: index + 1], 2)
        if confirmed:
            out[slots[index][0]] = confirmed
    return out


def _bucket(value: float) -> str:
    if value == 0:
        return "0"
    sign = "+" if value > 0 else "-"
    magnitude = abs(value)
    if magnitude <= 2:
        return f"{sign}≤2"
    if magnitude <= 5:
        return f"{sign}≤5"
    if magnitude <= 8:
        return f"{sign}≤8"
    return f"{sign}>8"


def summarize(diffs: list[dict[str, Any]]) -> dict[str, Any]:
    values = [d["adjustDiff"] for d in diffs]
    buckets = Counter(_bucket(v) for v in values)
    transitions = Counter(f"{d['oldConfirmed']}→{d['newStage']}" for d in diffs if d["adjustDiff"] != 0)
    nonzero = [v for v in values if v != 0]
    return {
        "n": len(values),
        "affected": len(nonzero),
        "affectedRate": round(len(nonzero) / len(values), 4) if values else None,
        "meanDiff": round(sum(values) / len(values), 3) if values else None,
        "maxUp": max(values, default=None),
        "maxDown": min(values, default=None),
        "buckets": dict(sorted(buckets.items())),
        "topTransitions": dict(transitions.most_common(12)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="新旧档位 regime 调整 diff（只读）")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--snapshot-type", default="half_hour")
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    docs = _load_docs(db, args.dataset, args.snapshot_type)

    by_date_slots: dict[str, list[dict]] = defaultdict(list)
    eod_docs: list[dict] = []
    for doc in docs:
        if doc.get("slotTime") == "EOD":
            eod_docs.append(doc)
        else:
            by_date_slots[str(doc["tradingDate"])].append(doc)

    diffs: list[dict[str, Any]] = []
    for date, slot_docs in sorted(by_date_slots.items()):
        slot_docs.sort(key=lambda d: str(d.get("slotTime") or ""))
        # 旧确认投影重建：级联截面序列因果前缀重放（审计 S8；confirmSlots=2 与生产一致）
        legacy_points = [
            (str(d.get("slotTime") or ""), str(d.get("legacyCascadeStage") or ""))
            for d in slot_docs if str(d.get("legacyCascadeStage") or "").strip()
        ]
        old_confirmed = _rebuild_old_confirmed_by_prefix(legacy_points)
        for doc in slot_docs:
            slot = str(doc.get("slotTime") or "")
            new_stage = str(doc.get("stage") or "").strip()
            old_stage = old_confirmed.get(slot)
            if not new_stage or not old_stage:
                continue  # score=None 槽 / 旧投影缺失（不可比，不计入）
            diffs.append({
                "tradingDate": date, "slotTime": slot,
                "oldConfirmed": old_stage, "newStage": new_stage,
                "adjustDiff": round(STAGE_ADJUST[new_stage] - STAGE_ADJUST[old_stage], 2),
            })

    # EOD 层：旧确认投影 = 当日级联序列 + EOD 锚定槽截面一次（因果同 09-24 spec）
    eod_diffs: list[dict[str, Any]] = []
    for eod in eod_docs:
        date = str(eod.get("tradingDate") or "")
        slot_docs = sorted(by_date_slots.get(date, []), key=lambda d: str(d.get("slotTime") or ""))
        anchored = str(eod.get("anchoredSlotTime") or "")
        legacy_points = [
            (str(d.get("slotTime") or ""), str(d.get("legacyCascadeStage") or ""))
            for d in slot_docs
            if str(d.get("slotTime") or "") < anchored and str(d.get("legacyCascadeStage") or "").strip()
        ]
        anchor_stage = str(eod.get("legacyCascadeStage") or "").strip()
        if anchor_stage:
            legacy_points.append((anchored, anchor_stage))
        old_confirmed, _ = confirm_stage(legacy_points, 2)
        new_stage = str(eod.get("stage") or "").strip()
        if old_confirmed and new_stage:
            eod_diffs.append({
                "tradingDate": date, "oldConfirmed": old_confirmed, "newStage": new_stage,
                "adjustDiff": round(STAGE_ADJUST[new_stage] - STAGE_ADJUST[old_confirmed], 2),
            })

    slot_summary = summarize(diffs)
    eod_summary = summarize(eod_diffs)
    print(json.dumps({"slotDiff": slot_summary, "eodDiff": eod_summary}, ensure_ascii=False, indent=1))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"slotDiff": slot_summary, "eodDiff": eod_summary,
                       "slotDiffs": diffs, "eodDiffs": eod_diffs}, fh, ensure_ascii=False, indent=1)
        print(f"[diff] json -> {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
