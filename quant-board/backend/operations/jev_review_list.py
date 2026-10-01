# -*- coding: utf-8 -*-
"""jev 复核工作台清单生成器（W1，辅助线；设计 hotlist-jev-auxiliary-plan.md）。

三类复核项（v1 范围，预登记 2026-10-01）：
  A 分歧仲裁：台账登记 4 个全槽分歧日（09-08/09-14/09-17/09-23）全部槽——规则"启动"
    (40.6-59.7) vs jev 93% 判"退潮"的方向盲争议；
  B 退潮段异议：规则档位∈{retreat,ice} 而 jev sequence_stage∈{start,ferment,climax}；
  C 边界日：EOD 分数距 40/60 边界 ≤3 分的交易日（连续分主定义边界抖动暴露）。

落库 phase_monitor kind=review_items（_id=review:<date>:<slot>:<TYPE>）。重跑幂等：
证据字段刷新、**已有人工裁决（ruling.status≠pending）一律保留不覆盖**。
用法：python -m backend.operations.jev_review_list
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

DIVERGENCE_DAYS = ("2026-09-08", "2026-09-14", "2026-09-17", "2026-09-23")
CN2EN = {"启动": "start", "发酵": "ferment", "高潮": "climax", "退潮": "retreat", "冰点": "ice"}
OFFENSE = {"start", "ferment", "climax"}
DEFENSE = {"ice", "retreat"}
BOUNDARY_EDGES = (40.0, 60.0)
BOUNDARY_TOL = 3.0
FRAMES = Path("data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")


def item_id(date: str, slot: str, item_type: str) -> str:
    return f"review:{date}:{slot}:{item_type}"


def auto_ruling(rule_en: str | None, jev_en: str | None, now: str) -> dict:
    """口径一致（五档字面相等）→ 自动裁决 consistent；否则待人工。纯函数。"""
    if rule_en and jev_en and rule_en == jev_en:
        return {"status": "consistent", "note": "口径一致，系统自动裁决（无需人工）", "ruledAt": now}
    return {"status": "pending", "note": "", "ruledAt": None}


def slopes_of_day(day_scores: dict[str, float]) -> dict[str, float | None]:
    """当日槽分序列 → 每槽斜率（与上一有效槽差；首槽 None）。纯函数。"""
    out: dict[str, float | None] = {}
    prev: float | None = None
    for slot in sorted(day_scores):
        v = day_scores[slot]
        out[slot] = None if prev is None else round(v - prev, 2)
        prev = v
    return out


def build_review_items(
    rule_slots: dict[tuple[str, str], dict],
    jev_slots: dict[tuple[str, str], dict],
    rule_eod_scores: dict[str, float],
    rule_eod_stages: dict[str, str],
    jev_eod_stages: dict[str, str],
    day_rets: dict[str, float],
) -> list[dict]:
    """纯函数：聚合三类复核项。输入为只读快照，输出待落库文档。

    规则与 jev 五档字面一致的项自动裁决 consistent（2026-10-01 用户指令），其余 pending。
    """
    now = datetime.now().isoformat(timespec="seconds")
    items: list[dict] = []
    # 当日斜率表（懒构建）
    slope_tables: dict[str, dict[str, float | None]] = {}

    def slope(date: str, slot: str) -> float | None:
        if date not in slope_tables:
            day_scores = {s: v["score"] for (d, s), v in rule_slots.items()
                          if d == date and isinstance(v.get("score"), (int, float))}
            slope_tables[date] = slopes_of_day(day_scores)
        return slope_tables[date].get(slot)

    for (date, slot), rs in sorted(rule_slots.items()):
        js = jev_slots.get((date, slot))
        if not js:
            continue
        rule_en = CN2EN.get(str(rs.get("stageCn") or ""))
        jev_en = str(js.get("stage") or "")
        if not rule_en or not jev_en:
            continue
        common = {
            "kind": "review_items", "date": date, "slot": slot,
            "rule": {"stage": rule_en, "stageCn": rs.get("stageCn"), "score": rs.get("score"),
                     "slope": slope(date, slot)},
            "jev": {"stage": jev_en, "confidence": js.get("confidence"),
                    "temperature": js.get("temperature")},
            "narrativeHead": js.get("narrativeHead"),
            "dayRet": day_rets.get(date),
        }
        if date in DIVERGENCE_DAYS:
            items.append({**common, "type": "A", "_id": item_id(date, slot, "A"),
                          "ruling": auto_ruling(rule_en, jev_en, now)})
        if rule_en in DEFENSE and jev_en in OFFENSE:
            items.append({**common, "type": "B", "_id": item_id(date, slot, "B"),
                          "ruling": auto_ruling(rule_en, jev_en, now)})

    for date, score in sorted(rule_eod_scores.items()):
        if not isinstance(score, (int, float)):
            continue
        if not any(abs(score - e) <= BOUNDARY_TOL for e in BOUNDARY_EDGES):
            continue
        rule_stage_en = CN2EN.get(rule_eod_stages.get(date) or "")
        jev_day = jev_eod_stages.get(date)
        items.append({
            "_id": item_id(date, "EOD", "C"), "kind": "review_items", "type": "C",
            "date": date, "slot": "EOD",
            "rule": {"score": score, "stage": rule_stage_en,
                     "stageCn": rule_eod_stages.get(date),
                     "nearEdge": next(e for e in BOUNDARY_EDGES if abs(score - e) <= BOUNDARY_TOL)},
            "jev": {"dayStage": jev_day},
            "narrativeHead": None,
            "dayRet": day_rets.get(date),
            "ruling": auto_ruling(rule_stage_en, jev_day, now),
        })
    return items


def merge_preserving_rulings(new_items: list[dict], existing_docs: dict[str, dict]) -> list[dict]:
    """纯函数：重跑时证据刷新、已裁决项的 ruling 原样保留。"""
    out = []
    for item in new_items:
        old = existing_docs.get(item["_id"])
        if old and isinstance(old.get("ruling"), dict) and old["ruling"].get("status") not in (None, "pending"):
            item = {**item, "ruling": old["ruling"]}
        out.append(item)
    return out


def load_day_rets() -> dict[str, float]:
    """frames → 每日全天池收益（首帧→末帧，共享代码≥5 均值）。"""
    text = gzip.open(FRAMES, "rt", encoding="utf-8").read()
    dec = json.JSONDecoder()
    idx = text.index("[") + 1
    frames = []
    while True:
        while idx < len(text) and text[idx] in " \t\r\n,":
            idx += 1
        if idx >= len(text) or text[idx] == "]":
            break
        frame, idx = dec.raw_decode(text, idx)
        frames.append(frame)
    frames.sort(key=lambda f: (str(f.get("tradingDate")), str(f.get("slotTime"))))
    day_prices: dict[str, list[dict[str, float]]] = {}
    for f in frames:
        prices = {}
        for row in f.get("stocks") or []:
            code = str(row.get("code") or "")
            try:
                p = float(row.get("lastPrice") or row.get("price") or row.get("close") or 0)
            except (TypeError, ValueError):
                continue
            if code and p > 0:
                prices[code] = p
        day_prices.setdefault(str(f.get("tradingDate")), []).append(prices)
    rets: dict[str, float] = {}
    for d, ps in day_prices.items():
        if len(ps) < 2:
            continue
        shared = [c for c in ps[0] if c in ps[-1]]
        if len(shared) >= 5:
            rets[d] = round(sum(ps[-1][c] / ps[0][c] - 1 for c in shared) / len(shared), 5)
    return rets


def generate(db) -> dict:
    """读源 → 构建 → 幂等落库（保留裁决）。返回统计。"""
    rule_slots: dict[tuple[str, str], dict] = {}
    rule_eod: dict[str, float] = {}
    rule_eod_stages: dict[str, str] = {}
    for doc in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour"},
        {"tradingDate": 1, "slotTime": 1, "rawStage": 1, "emotionScore.score": 1},
    ):
        es = doc.get("emotionScore")
        score = es.get("score") if isinstance(es, dict) and isinstance(es.get("score"), (int, float)) else None
        slot = str(doc.get("slotTime") or "")
        key = (str(doc.get("tradingDate")), slot)
        if slot == "EOD":
            if score is not None:
                rule_eod[key[0]] = float(score)
            if doc.get("rawStage"):
                rule_eod_stages[key[0]] = str(doc.get("rawStage"))
        else:
            rule_slots[key] = {"stageCn": doc.get("rawStage"), "score": score}

    jev_slots: dict[tuple[str, str], dict] = {}
    jev_eod_stages: dict[str, str] = {}
    for doc in db["hotlist_jev_sentiment"].find(
        {"status": "ok"},
        {"kind": 1, "tradingDate": 1, "slotTime": 1, "scores.temperature": 1,
         "answers.sequence_stage": 1, "answers.day_stage": 1, "narrativeRaw": 1},
    ):
        date, slot = str(doc.get("tradingDate")), str(doc.get("slotTime"))
        answers = doc.get("answers") or {}
        if doc.get("kind") == "slot":
            ss = (answers.get("sequence_stage") or {})
            sc = doc.get("scores") or {}
            jev_slots[(date, slot)] = {
                "stage": ss.get("choice"),
                "confidence": ss.get("confidence"),
                "temperature": sc.get("temperature"),
                "narrativeHead": str(doc.get("narrativeRaw") or "")[:200] or None,
            }
        elif doc.get("kind") == "eod":
            st = (answers.get("day_stage") or {}).get("choice")
            if isinstance(st, str):
                jev_eod_stages[date] = st

    day_rets = load_day_rets()
    items = build_review_items(rule_slots, jev_slots, rule_eod, rule_eod_stages, jev_eod_stages, day_rets)
    existing = {str(d["_id"]): d for d in db["phase_monitor"].find({"kind": "review_items"}, {"_id": 1, "ruling": 1})}
    items = merge_preserving_rulings(items, existing)
    for item in items:
        db["phase_monitor"].replace_one({"_id": item["_id"]}, item, upsert=True)
    from collections import Counter
    by_type = Counter(i["type"] for i in items)
    ruled = sum(1 for i in items if i["ruling"]["status"] != "pending")
    return {"total": len(items), "byType": dict(by_type), "ruledPreserved": ruled,
            "generatedAt": datetime.now().isoformat(timespec="seconds")}


def ensure_review_items(db) -> dict:
    """清单为空时才生成（GET 读口的懒触发）；已有清单直接返回统计。"""
    n = db["phase_monitor"].count_documents({"kind": "review_items"})
    if n:
        from collections import Counter
        docs = list(db["phase_monitor"].find({"kind": "review_items"}, {"type": 1, "ruling.status": 1}))
        return {"total": len(docs), "byType": dict(Counter(d.get("type") for d in docs)),
                "ruledPreserved": sum(1 for d in docs if (d.get("ruling") or {}).get("status") not in (None, "pending")),
                "regenerated": False}
    return {**generate(db), "regenerated": True}


def main() -> int:
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    stats = generate(db)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
