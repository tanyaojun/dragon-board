# -*- coding: utf-8 -*-
"""题材龙头「结局=续板」条件统计（只读，无 jev 调用，不写业务库）。

背景（2026-11-04 归因分析，见 docs/hotlist-jev/theme-leader-seal-attribution-20261104.md）：
  relay_page【题材龙头】按「结局=续板」筛选后，需要回答「续板成功的行满足哪些条件」。
  本脚本对 hotlist_jev_theme_leader_labels（剔除 sector doc 与退位行，与
  GET /api/hotlist-jev/theme-leaders 读口同口径）+ hotlist_jev_theme_cycle（P2 状态机）
  做分组续板率与 T+2 溢价统计，并输出模型四桶校准对照。

红线：
  - 只读：不写任何集合；结论只取 sampleOrigin=live（backfill 含语料未来信息，单列对照）。
  - 不调用 jev / 不消费 JEV_CF_TOKEN（§1.7）。
  - 样本量声明：各分组格 n<10 时仅为方向性信号，不得单独作为改判据依据（§1.6）。

用法：
  .venv/Scripts/python.exe -m backend.operations.theme_leader_seal_stats \
      [--start 2026-10-23] [--end 2026-11-03] [--out data/reports/theme-leader/seal-stats.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pymongo import MongoClient

# 四桶桶中心（与 relay_page TL_MIDPOINTS 一致，2026-10-27 口径）
MIDPOINTS = {"high_ge65": 0.75, "mid_45_65": 0.55, "low_25_45": 0.35, "verylow_lt25": 0.125}

LEADER_COLLECTION = "hotlist_jev_theme_leader_labels"
CYCLE_COLLECTION = "hotlist_jev_theme_cycle"


def outcome_key(doc: dict) -> str:
    v = doc.get("outcomeSealedNextDay")
    if v is None:
        return "pending"
    return "sealed" if v else "broken"


def prob_estimate(probabilities: dict | None) -> float | None:
    """四桶概率 + 桶中心 → 点估计（与 relay_page tlProb 同式）；无有效概率返回 None。"""
    probs = probabilities or {}
    parts = [(float(probs.get(k) or 0.0), mid) for k, mid in MIDPOINTS.items()]
    total = sum(p for p, _ in parts)
    if total <= 1e-4:
        return None
    return sum(p * mid for p, mid in parts) / total


def collect_rows(db, start: str | None, end: str | None) -> list[dict]:
    """拉龙头行并 join 板块级深度/延续（v12 拆题）与周期状态，产出扁平统计行。"""
    query: dict = {"docKind": {"$ne": "sector"}, "leaderSuperseded": {"$ne": True}}
    rng: dict = {}
    if start:
        rng["$gte"] = start
    if end:
        rng["$lte"] = end
    if rng:
        query["tradingDate"] = rng
    docs = list(db[LEADER_COLLECTION].find(query))
    sector_docs = {(str(d.get("tradingDate")), str(d.get("board"))): d
                   for d in db[LEADER_COLLECTION].find({"docKind": "sector"})}
    cycle_map = {(str(c.get("tradingDate")), str(c.get("board")),
                  str(c.get("segment") or "main")): c
                 for c in db[CYCLE_COLLECTION].find({})}
    rows: list[dict] = []
    for d in docs:
        ans = (d.get("answers") or {}).get("leader_nextday_continue") or {}
        sec = sector_docs.get((str(d.get("tradingDate")), str(d.get("board"))))
        if sec is not None:
            depth = ((sec.get("answers") or {}).get("theme_speculation_depth") or {}).get("choice")
            contn = ((sec.get("answers") or {}).get("theme_continuation") or {}).get("choice")
        else:
            depth = ((d.get("answers") or {}).get("theme_speculation_depth") or {}).get("choice")
            contn = ((d.get("answers") or {}).get("theme_continuation") or {}).get("choice")
        st = d.get("structure") or {}
        es = d.get("evidenceState") or {}
        cyc = cycle_map.get((str(d.get("tradingDate")), str(d.get("board")),
                             str(d.get("segment") or "main")))
        day2 = d.get("outcomeDay2") or {}
        rows.append({
            "date": str(d.get("tradingDate")),
            "code": str(d.get("code")),
            "board": d.get("board"),
            "ver": str(d.get("questionSetVersion")),
            "origin": d.get("sampleOrigin") or "live",
            "status": d.get("status"),
            "outcome": outcome_key(d),
            "choice": ans.get("choice"),
            "pEst": prob_estimate(ans.get("probabilities")),
            "depth": depth,
            "cont": contn,
            "head": ((d.get("answers") or {}).get("leader_headroom") or {}).get("choice"),
            "cycle": (cyc or {}).get("state"),
            "streak": st.get("streak"),
            "sealedToday": st.get("leaderSealedToday"),
            "gated": bool((d.get("gate") or {}).get("applied")),
            "evidenceMissing": bool(d.get("evidenceMissing")),
            "boardResolved": d.get("evidenceBoardResolved"),
            "nEvents": len(d.get("evidenceEventTitles") or []),
            "nNews": len(d.get("evidenceNewsTitles") or []),
            "kword": len(d.get("evidenceKwordTags") or []),
            "stale": bool(es.get("stale")),
            "day2": day2.get("closePct"),
            "day2Status": day2.get("status"),
        })
    return rows


def seal_rate(rows: list[dict]) -> str:
    s = sum(1 for r in rows if r["outcome"] == "sealed")
    b = sum(1 for r in rows if r["outcome"] == "broken")
    return f"{s}/{s + b} = {s / (s + b) * 100:.1f}%" if s + b else "-"


def group_rate(rows: list[dict], dim: str) -> dict[str, str]:
    by: dict[str, list] = defaultdict(list)
    for r in rows:
        if r[dim]:
            by[str(r[dim])].append(r)
    return {k: seal_rate(v) for k, v in sorted(by.items(), key=lambda kv: -len(kv[1]))}


def calibration(rows: list[dict]) -> dict[str, str]:
    buckets = [(0.65, 1.01, ">=65%"), (0.45, 0.65, "45-65%"),
               (0.25, 0.45, "25-45%"), (0.0, 0.25, "<25%")]
    out: dict[str, str] = {}
    for lo, hi, name in buckets:
        g = [r for r in rows if r["pEst"] is not None and lo <= r["pEst"] < hi]
        mp = (sum(r["pEst"] for r in g) / len(g) * 100) if g else 0.0
        out[name] = f"{seal_rate(g)}  mean_pEst={mp:.1f}%"
    return out


def day2_stats(rows: list[dict]) -> str:
    vals = sorted(v for v in (r["day2"] for r in rows) if isinstance(v, (int, float)))
    if not vals:
        return "-"
    win = sum(1 for v in vals if v > 0) / len(vals) * 100
    return (f"n={len(vals)} mean={statistics.mean(vals):+.2f}% "
            f"median={vals[len(vals) // 2]:+.2f}% win={win:.0f}%")


def build_report(rows: list[dict]) -> dict:
    live = [r for r in rows if r["origin"] == "live"]
    settled = [r for r in live if r["outcome"] != "pending"]
    sealed = [r for r in live if r["outcome"] == "sealed"]
    report: dict = {
        "totalRows": len(rows),
        "liveRows": len(live),
        "liveSettled": len(settled),
        "liveSealRate": seal_rate(settled),
        "backfillSealRate": seal_rate([r for r in rows if r["origin"] != "live"
                                       and r["outcome"] != "pending"]),
        "byVersion": group_rate(settled, "ver"),
        "byChoice": group_rate(settled, "choice"),
        # review 2026-11-05：归因文档 §2 连板高度行需可复算，补 byStreak 分组
        "byStreak": group_rate(settled, "streak"),
        "byDepth": group_rate(settled, "depth"),
        "byContinuation": group_rate(settled, "cont"),
        "byCycle": group_rate(settled, "cycle"),
        "byHeadroom": group_rate(settled, "head"),
        "bySealedToday": {
            f"sealedToday={k}": seal_rate([r for r in settled if r["sealedToday"] == k])
            for k in (True, False, None)},
        "calibration": calibration(settled),
        "evidenceSupply": {
            "evidenceMissing=True": seal_rate([r for r in settled if r["evidenceMissing"]]),
            "boardResolved=False/None": seal_rate(
                [r for r in settled if r["boardResolved"] in (False, None)]),
            "gated=True": seal_rate([r for r in settled if r["gated"]]),
            "nEvents==0": seal_rate([r for r in settled if r["nEvents"] == 0]),
            "nNews==0": seal_rate([r for r in settled if r["nNews"] == 0]),
            "stale=True": seal_rate([r for r in settled if r["stale"]]),
        },
        "day2AllSealed": day2_stats(sealed),
        "day2ByContinuation": {k: day2_stats([r for r in sealed if r["cont"] == k])
                               for k in {r["cont"] for r in sealed if r["cont"]}},
        "day2ByCycle": {k: day2_stats([r for r in sealed if r["cycle"] == k])
                        for k in {r["cycle"] for r in sealed if r["cycle"]}},
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="题材龙头续板条件统计（只读）")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD（含）")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD（含）")
    ap.add_argument("--mongo", default="mongodb://127.0.0.1:27017")
    ap.add_argument("--db", default="dragon_board_quant")
    ap.add_argument("--out", default=None, help="JSON 落盘路径（data/reports/…，可选）")
    args = ap.parse_args()

    db = MongoClient(args.mongo)[args.db]
    rows = collect_rows(db, args.start, args.end)
    report = build_report(rows)
    report["range"] = {"start": args.start, "end": args.end}
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"[saved] {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
