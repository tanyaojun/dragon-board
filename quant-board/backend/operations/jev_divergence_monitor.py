# -*- coding: utf-8 -*-
"""jev 分歧哨兵（W2，辅助线）：规则分链路数据质量的月度独立对照监控。

机理：jev 读的是独立管线（涨停池证据叙事），规则分上游数据代际/源故障会先表现为
两线分歧率跳变（先例：emotionValue 因采集链换血 205/1071 缺失）——哨兵比分数失真早报警。

指标（逐月，槽级 join hotlist_sentiment.rawStage × hotlist_jev_sentiment.sequence_stage）：
  fiveTier  五档一致率（rawStage==sequence_stage）
  twoTier   两档攻防一致率（start/ferment/climax=offense vs ice/retreat=defense）
  retreatSeg 退潮段一致率（规则=retreat 的槽中 jev 也=retreat 的占比，唯一历史高一致段 96%）
告警（预登记 2026-10-01）：五档环比 |Δ|>15pp 或 两档 |Δ|>10pp → 告警行（人工核查规则分上游）。
产物：phase_monitor kind=divergence（_id=divergence:<YYYY-MM>，逐月一档）+ stdout 摘要。
用法：python -m backend.operations.jev_divergence_monitor [--month YYYY-MM]（缺省=全月史重算落库）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_monitor_persistence import persist_divergence

CN2EN = {"启动": "start", "发酵": "ferment", "高潮": "climax", "退潮": "retreat", "冰点": "ice"}
OFFENSE = {"start", "ferment", "climax"}
DEFENSE = {"ice", "retreat"}
ALERT_FIVE_PP = 15.0
ALERT_TWO_PP = 10.0


def load_slots(db) -> list[dict]:
    """槽级 join 行：{date, slot, ruleStage, jevStage}（缺任一侧不入行，计数 fail-visible）。"""
    rule: dict[tuple[str, str], str] = {}
    for doc in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": {"$ne": "EOD"}},
        {"tradingDate": 1, "slotTime": 1, "rawStage": 1},
    ):
        en = CN2EN.get(str(doc.get("rawStage") or ""))
        if en:
            rule[(str(doc.get("tradingDate")), str(doc.get("slotTime")))] = en
    rows = []
    for doc in db["hotlist_jev_sentiment_v2"].find(
        {"kind": "slot", "status": "ok"}, {"tradingDate": 1, "slotTime": 1, "answers.sequence_stage": 1}
    ):
        j = ((doc.get("answers") or {}).get("sequence_stage") or {}).get("choice")
        r = rule.get((str(doc.get("tradingDate")), str(doc.get("slotTime"))))
        if isinstance(j, str) and r:
            rows.append({"date": str(doc.get("tradingDate")), "ruleStage": r, "jevStage": j})
    return rows


def month_metrics(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    five = sum(1 for r in rows if r["ruleStage"] == r["jevStage"])
    two = sum(1 for r in rows if (r["ruleStage"] in OFFENSE) == (r["jevStage"] in OFFENSE))
    ret = [r for r in rows if r["ruleStage"] == "retreat"]
    ret_ok = sum(1 for r in ret if r["jevStage"] == "retreat")
    return {
        "n": n,
        "fiveTier": round(five / n, 4),
        "twoTier": round(two / n, 4),
        "retreatSeg": round(ret_ok / len(ret), 4) if ret else None,
        "retreatN": len(ret),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="jev 分歧哨兵（月度规则分链路质量对照）")
    parser.add_argument("--month", default=None, help="只重算并汇报指定月（缺省=全月史重算落库）")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    rows = load_slots(db)
    by_month: dict[str, list[dict]] = {}
    for r in rows:
        by_month.setdefault(r["date"][:7], []).append(r)
    months = sorted(by_month)
    if not months:
        print("[divergence-monitor] 无可 join 槽（规则或 jev 侧缺失）", file=sys.stderr)
        return 2

    target = args.month
    history: dict[str, dict] = {}
    alerts: list[str] = []
    prev: dict | None = None
    for m in months:
        cur = month_metrics(by_month[m])
        if prev and cur.get("n") and prev.get("n"):
            d5 = (cur["fiveTier"] - prev["fiveTier"]) * 100
            d2 = (cur["twoTier"] - prev["twoTier"]) * 100
            cur["deltaFivePp"] = round(d5, 1)
            cur["deltaTwoPp"] = round(d2, 1)
            if abs(d5) > ALERT_FIVE_PP:
                alerts.append(f"{m}: 五档一致率环比 {d5:+.1f}pp（>|{ALERT_FIVE_PP:.0f}|）——核查规则分上游")
            if abs(d2) > ALERT_TWO_PP:
                alerts.append(f"{m}: 两档一致率环比 {d2:+.1f}pp（>|{ALERT_TWO_PP:.0f}|）——核查规则分上游")
        history[m] = cur
        prev = cur

    persisted = []
    for m in (months if not target else [target]):
        report = {"month": m, "metrics": history[m], "alerts": [a for a in alerts if a.startswith(m)],
                  "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"),
                           "purpose": "jev 分歧哨兵：规则分链路质量月度对照（辅助线，W2）",
                           "alertRule": f"五档环比|Δ|>{ALERT_FIVE_PP:.0f}pp 或 两档|Δ|>{ALERT_TWO_PP:.0f}pp",
                           "baselineNote": "台账旧基线（2026-09，jev 覆盖仅 3 日时点）五档 27.2%/两档 65.8%/退潮段 96%；本月史为 113 日全量重算口径"},
                  "history": history}
        pid = persist_divergence(report)
        persisted.append(f"{m}->{'ok' if pid else 'FAIL'}")

    print(json.dumps({"months": history, "alerts": alerts, "persisted": persisted}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
