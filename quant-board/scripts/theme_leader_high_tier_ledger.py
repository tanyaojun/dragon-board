# -*- coding: utf-8 -*-
"""高档（续板概率 高≥65%）个案登记簿（2026-10-26 用户批准；预登记 §21.5）。

背景：高档由组合桶锚决定（同桶历史次日连板率 ≥65% 才该判高档），天然稀发（全史
5 个交易日仅 2 例）——频率派分桶统计攒不快样本，改个案登记：每例登记
「模型判据 + T+1 结局 + 后日 T+2 打板溢价 + 当日市况」，随验收窗逐例积累，
攒到 ≥5 例再评估能否分桶。交易口径=高档是稀发事件信号，逐例审计优于按置信打折。

零 jev 调用、零写入（只读库）；T+1 结局与 T+2 溢价由 theme_leader_pilot_eval
--write-outcome / --write-day2 回填，本簿只读。

用法：
  ./.venv/Scripts/python.exe scripts/theme_leader_high_tier_ledger.py [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COLLECTION = "hotlist_jev_theme_leader_labels"
HIGH_TIER = "high_ge65"
LEDGER_MATURITY_N = 5   # 攒到 ≥5 例再评估分桶（2026-10-26 用户批准的验收口径）
REGIME_KEYS = ("relay_phase", "relay_momentum", "money_effect", "ladder_health")


def build_ledger(db) -> dict:
    """高档样本逐例登记（现任行，退位排除）；市况取当日 relay 判定卡答案。"""
    col = db[COLLECTION]
    docs = [d for d in col.find({})
            if d.get("leaderNextdayContinue") == HIGH_TIER
            and d.get("status") != "skipped" and not d.get("leaderSuperseded")]
    relay_cache: dict[str, dict] = {}
    rows = []
    for d in sorted(docs, key=lambda x: str(x.get("tradingDate"))):
        date = str(d.get("tradingDate"))
        if date not in relay_cache:
            r = db["hotlist_jev_relay_index"].find_one({"_id": f"{date}:RELAY"}) or {}
            relay_cache[date] = r.get("answers") or {}
        ra = relay_cache[date]
        st = d.get("structure") or {}
        ans = (d.get("answers") or {}).get("leader_nextday_continue") or {}
        d2 = d.get("outcomeDay2") or {}
        rows.append({
            "date": date, "code": d.get("code"), "name": d.get("name"),
            "board": d.get("board"), "streak": st.get("streak"),
            "questionSetVersion": d.get("questionSetVersion"),
            "conf": ans.get("confidence"),
            "probHigh": (ans.get("probabilities") or {}).get("high_ge65"),
            "sealedNextDay": d.get("outcomeSealedNextDay"),
            "day2": ({"date": d2.get("date"), "openPct": d2.get("openPct"),
                      "closePct": d2.get("closePct"), "skipped": d2.get("skipped")}
                     if d2 else None),
            "regime": {k: (ra.get(k) or {}).get("choice") for k in REGIME_KEYS},
        })
    known = [r for r in rows if r["sealedNextDay"] is not None]
    premium = [r for r in known if r["sealedNextDay"]
               and isinstance(r["day2"], dict) and r["day2"].get("closePct") is not None]
    return {
        "ok": True,
        "tier": HIGH_TIER,
        "total": len(rows),
        "outcomeKnown": len(known),
        "sealedCount": sum(1 for r in known if r["sealedNextDay"]),
        "day2PremiumKnown": len(premium),
        "meanDay2ClosePct": (sum(r["day2"]["closePct"] for r in premium) / len(premium))
                            if premium else None,
        "maturity": {"n": len(rows), "threshold": LEDGER_MATURITY_N,
                     "readyForBucketing": len(rows) >= LEDGER_MATURITY_N},
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="打印完整 JSON")
    args = ap.parse_args()
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    out = build_ledger(get_runtime_mongodb_database())
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    mean = (f"｜平均后日收盘溢价 {out['meanDay2ClosePct']:+.2f}%"
            if out["meanDay2ClosePct"] is not None else "")
    print(f"高档个案登记簿（{out['tier']}）：共 {out['total']} 例｜结局已知 {out['outcomeKnown']}"
          f"｜续板 {out['sealedCount']}｜后日溢价已知 {out['day2PremiumKnown']}{mean}")
    for r in out["rows"]:
        d2 = r["day2"] or {}
        prem = (f"后日开 {d2['openPct']:+.2f}% / 收 {d2['closePct']:+.2f}%"
                if d2.get("closePct") is not None
                else (str(d2.get("skipped")) if d2.get("skipped") else "溢价未回填"))
        rg = r["regime"] or {}
        outcome = ("续板" if r["sealedNextDay"]
                   else "未续" if r["sealedNextDay"] is not None else "未知")
        print(f"  {r['date']} {str(r['name'] or ''):6s}({r['code']}) "
              f"{str(r['board'] or ''):6s} {r['streak']}板 v={r['questionSetVersion']} "
              f"conf={r['conf']} P(high)={r['probHigh']} 结局={outcome} {prem} "
              f"市况={rg.get('relay_phase')}/{rg.get('relay_momentum')}/{rg.get('money_effect')}")
    m = out["maturity"]
    print(f"分桶成熟度：{m['n']}/{m['threshold']} 例"
          + ("——已达门槛，可评估分桶" if m["readyForBucketing"]
             else "——个案登记阶段，不下统计结论"))


if __name__ == "__main__":
    main()
