# -*- coding: utf-8 -*-
"""竞价龙头 pilot 离线评估 + 当日结局回填（**零 jev 调用**，只读库 + 写 outcome 字段）。

结局口径（预登记 auction-leader-vA1 §5）：`outcomeSealedToday` = 当日 daban pool
日档封板成员（单一事实源 `load_day(lane="pool")`）；THS `sealed_and_info` 交叉披露
`outcomeCross`（两源矛盾不仲裁，留痕）；pool 缺 → THS 兜底（outcomeSource=ths）；
双缺 → None 待结算（fail-visible，不计入率）。

验收（≥20 交易日后）：分档真实封板率差 ≥15pp 且 Brier 优于基础率锚；单日只作观察。

用法：
  ./.venv/Scripts/python.exe scripts/auction_leader_pilot_eval.py --date 2026-11-13
  ./.venv/Scripts/python.exe scripts/auction_leader_pilot_eval.py --date 2026-11-13 --write-outcome
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.operations.auction_leader_label import (  # noqa: E402
    COLLECTION, auction_seal_base_rate)
from backend.operations.theme_leader_baseline import sealed_and_info  # noqa: E402

MIDPOINTS = {"high_ge65": 0.75, "mid_45_65": 0.55, "low_25_45": 0.35, "verylow_lt25": 0.125}
ACCEPTANCE_GAP_PP = 15.0
ACCEPTANCE_MIN_TRADING_DAYS = 20


def _db():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    return get_runtime_mongodb_database()


def sealed_sets(db, date: str) -> tuple[set[str] | None, set[str] | None]:
    """(daban pool 封板集合, THS 封板集合)；缺源 → None（不伪装空集）。"""
    pool: set[str] | None = None
    try:
        from backend.services.kpl_daban_archiver import load_day
        payload = load_day(db, date, lane="pool")
        if payload.get("ok") and not payload.get("empty"):
            # 封板口径=pool_state sealed（炸板 broken 不算封板，kpl_lead_service 权威同源）
            pool = {str(it.get("stock_id") or "")[-6:]
                    for it in payload.get("items") or []
                    if isinstance(it, dict) and it.get("pool_state") == "sealed"}
        elif payload.get("ok") and payload.get("empty"):
            pool = set()
    except Exception:  # noqa: BLE001 — 读口异常 → 缺源（fail-visible）
        pool = None
    ths, _info, _meta = sealed_and_info(db, date)
    return pool, ths


def write_outcome(db, date: str) -> dict:
    pool, ths = sealed_sets(db, date)
    col = db[COLLECTION]
    n = settled = pending = cross = 0
    for d in col.find({"tradingDate": date, "docKind": "leader"}):
        code = str(d.get("code") or "")[-6:]
        if not code:
            continue
        n += 1
        if pool is not None:
            outcome, source = code in pool, "daban_pool"
        elif ths is not None:
            outcome, source = code in ths, "ths"
        else:
            outcome, source = None, None
        if outcome is None:
            pending += 1
            continue
        settled += 1
        update = {"outcomeSealedToday": bool(outcome),
                  "outcomeSettledAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "outcomeSource": source}
        if pool is not None and ths is not None:
            same = (code in pool) == (code in ths)
            update["outcomeCross"] = same
            cross += 0 if same else 1
        col.update_one({"_id": d["_id"]}, {"$set": update})
    return {"date": date, "docs": n, "settled": settled, "pending": pending,
            "crossMismatch": cross,
            "poolAvailable": pool is not None, "thsAvailable": ths is not None}


def _metrics(docs: list[dict]) -> dict:
    """单代际指标：分档封板率 + Brier（degraded 已在外层剔除）。"""
    buckets: dict[str, list] = {}
    brier_sum = brier_n = 0
    for d in docs:
        choice = d.get("auctionSealToday") or "insufficient"
        buckets.setdefault(choice, []).append(bool(d.get("outcomeSealedToday")))
        probs = d.get("auctionSealProbabilities") or {}
        total = sum(float(probs.get(k) or 0) for k in MIDPOINTS)
        if total > 0.0001:
            p = sum(float(probs.get(k) or 0) * v for k, v in MIDPOINTS.items()) / total
            y = 1.0 if d.get("outcomeSealedToday") else 0.0
            brier_sum += (p - y) ** 2
            brier_n += 1
    rates = {k: {"n": len(v), "sealedRate": round(sum(v) * 100.0 / len(v), 1)}
             for k, v in buckets.items() if v}
    return {"settledDocs": len(docs), "buckets": rates,
            "brier": round(brier_sum / brier_n, 4) if brier_n else None}


def evaluate(db, date: str) -> dict:
    """单日评估。vA2 B5：题集跨代不可比——输出补 byQuestionSetVersion 分代披露，
    验收聚合（≥20 交易日）必须只消费 byQuestionSetVersion，不得混算 vA1/vA2 模型指标；
    顶层 buckets/brier 为全代混合仅观察（混代日防呆，review N2）。"""
    col = db[COLLECTION]
    all_docs = list(col.find({"tradingDate": date, "docKind": "leader"}))
    degraded_n = sum(1 for d in all_docs if d.get("status") == "degraded")
    # degraded 不得混进模型指标（题材链同款口径）：单独计数透出
    docs = [d for d in all_docs
            if d.get("outcomeSealedToday") is not None
            and d.get("status") in (None, "ok")]
    gens: dict[str, list] = {}
    for d in docs:
        gens.setdefault(str(d.get("questionSetVersion") or "unknown"), []).append(d)
    base = auction_seal_base_rate(db, before=date)
    return {"date": date, **_metrics(docs), "degradedDocs": degraded_n,
            "topLevelCaliber": "all_generations_mixed_observe_only",
            "byQuestionSetVersion": {g: _metrics(ds) for g, ds in sorted(gens.items())},
            "baseRateAnchor": base,
            "acceptanceMinTradingDays": ACCEPTANCE_MIN_TRADING_DAYS,
            "acceptanceGapPp": ACCEPTANCE_GAP_PP}


def main() -> None:
    ap = argparse.ArgumentParser(description="竞价龙头结局回填/评估（零 jev）")
    ap.add_argument("--date", required=True)
    ap.add_argument("--write-outcome", action="store_true")
    args = ap.parse_args()
    db = _db()
    if args.write_outcome:
        res = write_outcome(db, args.date)
        print(f"{args.date} → 当日封板结局：settled={res['settled']} "
              f"pending={res['pending']} crossMismatch={res['crossMismatch']}")
        print(json.dumps(res, ensure_ascii=False))
    print(json.dumps(evaluate(db, args.date), ensure_ascii=False))


if __name__ == "__main__":
    main()