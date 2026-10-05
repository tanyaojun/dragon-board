# -*- coding: utf-8 -*-
"""方向二：情绪档位切换的门控传播 replay（只读，全程 find，零生产改动）。

来源：GLM-5.3 EOD 规则分研讨（reasoning-corpus-eod-emotion.md §7）方向二，用户裁决执行 2026-10-05。
把 T6 的「放松 ≈293 vs 收紧 ≈144」翻译成逐门迁移矩阵（D_EXIT_RISK / allow_a_main / allow_b_ignition），
并给出对账门（T5 迁移矩阵逐项复现）与锚定门（09-24/09-29 单日核对）。

门语义（engine/runtime.py:474-475 读码为准）：
- D_EXIT_RISK：stage ∈ {退潮, 冰点}
- allow_a_main：stage ∈ {高潮, 发酵} 且 riskLevel ∉ {高, high, HIGH}（riskLevel 缺失按非高，
  与 runtime 一致——fail-open 只在整份 hotlistSentiment 缺失时发生，单字段缺失不触发）
- allow_b_ignition：stage ∈ {高潮, 发酵, 启动}

旧档位投影：legacyCascadeStage 按日因果前缀重放 confirm_stage(slots[:i+1], 2)
（审计 S8 同款，与 emotion_score_stage_adjust_diff.py 对账基准一致）。

已知边界（如实登记，不伪造）：regime state（70/50/30）跨线矩阵需完整 frame 装配
（snapshot_frames 为瘦文档，stocks/analysis 在独立集合）——属全窗 dry-run 装配链，另批；
本脚本只产出 stage 分量 Δ 分布引用（T6 已有）。

用法：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.emotion_score_gate_replay [--json <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from typing import Any

from backend.analysis.hotlist.stage_confirm import confirm_stage

GATES = ("D_EXIT_RISK", "allow_a_main", "allow_b_ignition")
_EXIT_STAGES = ("退潮", "冰点")
_A_MAIN_STAGES = ("高潮", "发酵")
_B_IGNITION_STAGES = ("高潮", "发酵", "启动")
_RISK_HIGH = ("高", "high", "HIGH")

# 对账基准（emotion-score-regime-diff-report.md line 46 / migration-report T5 矩阵）。
# 退潮→发酵 36（≠T6 的 34）与 退潮→高潮 9（T6 枚举遗漏）均已在对账输出中带注记呈现，
# 见 eod-rule-gate-replay-report.md §三（drift=T5 时点后 09-30 恢复重算文档增量）。
EXPECTED_RELAX = {"退潮→启动": 153, "启动→发酵": 88, "退潮→发酵": 36, "启动→高潮": 18}
EXPECTED_TIGHTEN = {"启动→冰点": 123, "启动→退潮": 15, "发酵→启动": 6}
ANCHOR_DAYS = ("2026-09-24", "2026-09-29")


def _gate_states(stage: str, risk_level: Any) -> dict[str, bool]:
    risk_high = str(risk_level or "").strip() in _RISK_HIGH
    return {
        "D_EXIT_RISK": stage in _EXIT_STAGES,
        "allow_a_main": stage in _A_MAIN_STAGES and not risk_high,
        "allow_b_ignition": stage in _B_IGNITION_STAGES,
    }


def _load_slots(db: Any, dataset_id: str, snapshot_type: str) -> list[dict]:
    rows = db["hotlist_sentiment"].find(
        {"datasetId": dataset_id, "snapshotType": snapshot_type, "slotTime": {"$ne": "EOD"}},
        {"_id": 1, "tradingDate": 1, "slotTime": 1, "stage": 1, "legacyCascadeStage": 1, "riskLevel": 1},
    )
    return [dict(r) for r in rows if r.get("tradingDate")]


def _load_eods(db: Any, dataset_id: str, snapshot_type: str) -> list[dict]:
    rows = db["hotlist_sentiment"].find(
        {"datasetId": dataset_id, "snapshotType": snapshot_type, "slotTime": "EOD"},
        {"_id": 1, "tradingDate": 1, "stage": 1, "legacyCascadeStage": 1, "riskLevel": 1},
    )
    return [dict(r) for r in rows if r.get("tradingDate")]


def _old_confirmed_by_day(slots_by_day: dict[str, list[dict]]) -> dict[tuple[str, str], str]:
    """按日前缀重放旧确认投影（审计 S8）：(date, slotTime) -> oldConfirmed。"""
    out: dict[tuple[str, str], str] = {}
    for day, docs in slots_by_day.items():
        seq = [(str(d.get("slotTime")), str(d.get("legacyCascadeStage") or "")) for d in docs]
        for index in range(len(seq)):
            confirmed, _ = confirm_stage(seq[: index + 1], 2)
            if confirmed:
                out[(day, seq[index][0])] = confirmed
    return out


def _gate_migration(docs: list[dict[str, Any]], level: str) -> dict[str, Any]:
    """docs 需含 oldConfirmed/newStage/riskLevel。返回逐门 2×2 矩阵与迁移对计数。"""
    per_gate = {g: Counter() for g in GATES}
    pairs = Counter()
    missing_risk = 0
    skipped = Counter()
    for d in docs:
        old, new = d.get("oldConfirmed"), d.get("newStage")
        if not old or not new:
            skipped[missing_key(d)] += 1
            continue
        if not str(d.get("riskLevel") or "").strip():
            missing_risk += 1
        old_g = _gate_states(old, d.get("riskLevel"))
        new_g = _gate_states(new, d.get("riskLevel"))
        for g in GATES:
            per_gate[g][f"{old_g[g]:d}->{new_g[g]:d}"] += 1
        if old != new:
            pairs[f"{old}→{new}"] += 1
    return {"level": level, "perGate": {g: dict(c) for g, c in per_gate.items()},
            "pairs": dict(pairs), "riskLevelMissing": missing_risk, "skipped": dict(skipped)}


def missing_key(d: dict[str, Any]) -> str:
    if not d.get("oldConfirmed"):
        return "缺legacyCascadeStage"
    return "缺新stage"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="情绪档位切换门控传播 replay（只读）")
    ap.add_argument("--dataset", default="dragonboard_live")
    ap.add_argument("--snapshot-type", default="half_hour")
    ap.add_argument("--json", default=None, help="明细落盘路径")
    args = ap.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    slots = _load_slots(db, args.dataset, args.snapshot_type)
    eods = _load_eods(db, args.dataset, args.snapshot_type)

    slots_by_day: dict[str, list[dict]] = defaultdict(list)
    for d in slots:
        slots_by_day[d["tradingDate"]].append(d)
    for docs in slots_by_day.values():
        docs.sort(key=lambda d: str(d.get("slotTime")))
    old_conf = _old_confirmed_by_day(slots_by_day)

    slot_docs = [{**d, "oldConfirmed": old_conf.get((d["tradingDate"], str(d.get("slotTime")))),
                  "newStage": d.get("stage")} for d in slots]
    eod_docs = [{**d, "oldConfirmed": str(d.get("legacyCascadeStage") or ""),
                 "newStage": d.get("stage")} for d in eods]

    mig_slot = _gate_migration(slot_docs, "slot")
    mig_eod = _gate_migration(eod_docs, "eod")

    # 对账门：迁移对复现（风险无关口径=T6 基准；放松/收紧按门方向语义——D_EXIT 开=收紧、
    # allow 开=放松；与 T6 ≈293/≈144 的风险无关口径对表时按"任一门放松/收紧"归组）
    direction = {"D_EXIT_RISK": ("1->0", "0->1"),
                 "allow_a_main": ("0->1", "1->0"),
                 "allow_b_ignition": ("0->1", "1->0")}
    relax_report, tighten_report = {}, {}
    for pair, n in mig_slot["pairs"].items():
        old, new = pair.split("→")
        old_g, new_g = _gate_states(old, "低"), _gate_states(new, "低")  # 风险无关口径（T6 基准）
        relax = any(f"{int(old_g[g])}->{int(new_g[g])}" == direction[g][0] for g in GATES)
        tighten = any(f"{int(old_g[g])}->{int(new_g[g])}" == direction[g][1] for g in GATES)
        if relax:
            relax_report[pair] = n
        if tighten:
            tighten_report[pair] = n
    relax_total = sum(relax_report.values())
    tighten_total = sum(tighten_report.values())

    print("== 方向二：门控传播 replay（只读）==")
    print(f"槽位 n={len(slot_docs)}（riskLevel 缺失 {mig_slot['riskLevelMissing']}，跳过 {mig_slot['skipped']}）")
    risk_dist = Counter(str(d.get("riskLevel")) for d in slots)
    print(f"riskLevel 分布: {dict(risk_dist)}")
    print(f"按月: {dict(Counter(d['tradingDate'][:7] for d in slots))}")
    print("\n[slot 级逐门迁移 2×2（实际 riskLevel 口径）]")
    for g in GATES:
        print(f"  {g}: {mig_slot['perGate'][g]}")
    if mig_slot["perGate"]["allow_a_main"].get("0->1", 0) == 0:
        print("  ⚠ allow_a_main 全 0->0：riskLevel 恒高使该门事实关闭（死门）——结构性发现，见报告")
    if mig_slot["perGate"]["allow_b_ignition"] == mig_slot["perGate"]["D_EXIT_RISK"]:
        print("  ⚠ allow_b_ignition 与 D_EXIT_RISK 五档语义互为补集（矩阵逐格相同=镜像门）")
    print(f"EOD  n={len(eod_docs)}（riskLevel 缺失 {mig_eod['riskLevelMissing']}，跳过 {mig_eod['skipped']}）")
    print("[EOD 级逐门迁移]")
    for g in GATES:
        print(f"  {g}: {mig_eod['perGate'][g]}")

    print("\n[对账门：门语义放松/收紧迁移对]")
    for pair, n in sorted(relax_report.items(), key=lambda kv: -kv[1]):
        exp = EXPECTED_RELAX.get(pair)
        mark = "✓" if exp == n else (f"（报告基准外，T6 ≈293 未计入）" if exp is None else f"✗ 预期 {exp}")
        print(f"  放松 {pair}: {n} {mark}")
    for pair, n in sorted(tighten_report.items(), key=lambda kv: -kv[1]):
        exp = EXPECTED_TIGHTEN.get(pair)
        mark = "✓" if exp == n else ("（报告基准外）" if exp is None else f"✗ 预期 {exp}")
        print(f"  收紧 {pair}: {n} {mark}")
    print(f"  放松合计 {relax_total}（报告 ≈293）| 收紧合计 {tighten_total}（报告 ≈144）")
    missing_expected = {p: n for p, n in EXPECTED_RELAX.items() if relax_report.get(p) != n}
    missing_expected.update({p: n for p, n in EXPECTED_TIGHTEN.items() if tighten_report.get(p) != n})
    print(f"  对账判定: {'PASS（全部基准对精确复现）' if not missing_expected else f'FAIL {missing_expected}'}")

    print("\n[锚定门：09-24 / 09-29 单日逐槽]")
    for day in ANCHOR_DAYS:
        docs = [d for d in slot_docs if d["tradingDate"] == day]
        eod = next((e for e in eod_docs if e["tradingDate"] == day), None)
        print(f"  -- {day} --")
        for d in docs:
            old_g = _gate_states(d["oldConfirmed"] or "", d.get("riskLevel"))
            new_g = _gate_states(d["newStage"] or "", d.get("riskLevel"))
            changed = [g for g in GATES if old_g[g] != new_g[g]]
            print(f"    {d.get('slotTime')}: 旧={d.get('oldConfirmed')} 新={d.get('newStage')}"
                  f" | 门变化 {changed or '无'}")
        if eod:
            print(f"    EOD: 旧={eod.get('oldConfirmed')} 新={eod.get('newStage')}")

    if args.json:
        payload = {"slot": mig_slot, "eod": mig_eod,
                   "reconcile": {"relax": relax_report, "tighten": tighten_report,
                                 "relaxTotal": relax_total, "tightenTotal": tighten_total,
                                 "missingExpected": missing_expected}}
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1, default=str)
        print(f"\n明细已落 {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
