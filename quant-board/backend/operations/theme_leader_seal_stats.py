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
import re
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

# v17 续板基础率锚人群起点（live 代，沿 v15 口径另加 status=ok；预登记 v17 §2.4-2）
LIVE_BASE_RATE_START = "2026-10-23"


def live_base_rate(db, before: str) -> dict | None:
    """v17 续板基础率锚（轻量聚合，零 jev 零写入）：个股叙事先验底的单一事实源。

    人群沿 v15 口径另加 status=ok（degraded 无有效判答不入锚；v15 复算路径
    collect_rows 不过滤 status，n/率或有微差——锚以本函数为单一事实源，
    review m2 披露）：docKind≠sector（含 legacy 缺键）、非退位、
    sampleOrigin≠backfill（缺键视同 live，与 collect_rows 同口径）、
    outcomeSealedNextDay 非空、tradingDate ∈ [2026-10-23, before)——**排除当日及
    以后**（重跑历史日不得看见当日/未来结算，防 look-ahead）。封板/断板分组=
    structure.leaderSealedToday（True/False；None=不可考只进总体）。
    find({})+Python 侧过滤：测试假库只支持平坦等值查询（与 fetch_driver_label 同
    哲学）；集合规模百行级，全取成本可忽。无已结算行 → None（锚行整行缺席，
    AGENTS §1.2-8）。
    """
    sealed_n = sealed_ok = broken_n = broken_ok = 0
    total_n = total_ok = 0
    dates: list[str] = []
    for d in db[LEADER_COLLECTION].find({}):
        date = str(d.get("tradingDate") or "")
        if not (LIVE_BASE_RATE_START <= date < before):
            continue
        if d.get("docKind") == "sector" or d.get("leaderSuperseded"):
            continue
        if d.get("status") not in (None, "ok"):
            continue
        if (d.get("sampleOrigin") or "live") != "live":
            continue
        outcome = d.get("outcomeSealedNextDay")
        if outcome is None:
            continue
        dates.append(date)
        total_n += 1
        total_ok += 1 if outcome else 0
        sealed_today = (d.get("structure") or {}).get("leaderSealedToday")
        if sealed_today is True:
            sealed_n += 1
            sealed_ok += 1 if outcome else 0
        elif sealed_today is False:
            broken_n += 1
            broken_ok += 1 if outcome else 0
    if not total_n:
        return None
    return {
        "n": total_n, "ratePct": total_ok / total_n * 100,
        "start": min(dates), "end": max(dates),
        "sealed": ({"n": sealed_n, "ratePct": sealed_ok / sealed_n * 100}
                   if sealed_n else {"n": 0}),
        "broken": ({"n": broken_n, "ratePct": broken_ok / broken_n * 100}
                   if broken_n else {"n": 0}),
    }


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
            # P2-3（2026-11-07 观察指标，登记不下结论）：①insufficient 概率质量（pEst 口径
            # 丢弃该质量，校准时不可见——贫料 hedge 单独看）；②最细同桶率 vs 按连板高度
            # 桶率差（三例+11-06 n=9 显示最细桶系统性高于边际桶，验证幸存者偏差假设）；
            # ③程序侧偏离标记（与 theme_leader_label._anchor_deviation_audit 同口径）
            "insufficientMass": (ans.get("probabilities") or {}).get("insufficient"),
            **_anchor_observation_fields(d.get("narrative"), ans.get("choice")),
        })
    return rows


_ANCHOR_ORDER = ("verylow_lt25", "low_25_45", "mid_45_65", "high_ge65")


def _rate_bucket(rate: float) -> str:
    return ("verylow_lt25" if rate < 25 else "low_25_45" if rate < 45
            else "mid_45_65" if rate < 65 else "high_ge65")


def _anchor_observation_fields(narrative: str | None, choice: str | None) -> dict:
    """从叙事「结构基线」行抽最细同桶率/按连板高度桶率与偏离标记（规则①同口径：
    同桶样本<8 回退高度桶；与 theme_leader_label._anchor_deviation_audit 保持一致）。"""
    out: dict = {"anchorRate": None, "anchorN": None, "heightRate": None,
                 "anchorBucket": None, "anchorDeviation": None}
    if not narrative:
        return out
    # 2026-11-17b：叙事前缀改「同结构」（与 _anchor_deviation_audit 同步）；
    # 本工具按日期窗回放**历史落库叙事**，双前缀兼容旧代档（review m1：
    # 只认新前缀会使旧代档 anchorRate/anchorN 静默归 None，报告缩水无披露）。
    m = re.search(r"结构基线：(?:同桶|同结构)\[[^\]]+\] 历史次日连板率 ([\d.]+)%（(\d+) 样本）", narrative)
    if m:
        out["anchorRate"], out["anchorN"] = float(m.group(1)), int(m.group(2))
    mh = re.search(r"按连板高度\[[^\]]+\] ([\d.]+)%（(\d+) 样本）", narrative)
    if mh:
        out["heightRate"] = float(mh.group(1))
    eff = out["anchorRate"] if (out["anchorRate"] is not None
                                and (out["anchorN"] or 0) >= 8) else out["heightRate"]
    if eff is not None:
        out["anchorBucket"] = _rate_bucket(eff)
        if choice in _ANCHOR_ORDER and choice != out["anchorBucket"]:
            out["anchorDeviation"] = abs(_ANCHOR_ORDER.index(choice) - _ANCHOR_ORDER.index(out["anchorBucket"]))
    return out


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


def anchor_observations(settled: list[dict]) -> dict:
    """P2-3（2026-11-07）：模型校准行为的三个观察维度（非判据、不改 pEst 口径）。

    ①insufficientMassMean：模型意给「证据不足」桶的概率质量均值（pEst 口径丢弃该质量，
    贫料 hedge 在校准里不可见——11-06 n=9 实测 7/9 上升）；②anchorHeightDiffMean：
    最细同桶率 − 按连板高度桶率（两读数都在场时；验证「最细桶幸存者偏差」假设）；
    ③deviationRows/ByBucket：模型档位偏离中枢桶的行数与分布。
    """
    masses = [float(r["insufficientMass"]) for r in settled
              if r.get("insufficientMass") is not None]
    diffs = [r["anchorRate"] - r["heightRate"] for r in settled
             if r.get("anchorRate") is not None and r.get("heightRate") is not None]
    dev = [r for r in settled if r.get("anchorDeviation")]
    return {
        "insufficientMassMean": round(statistics.fmean(masses), 3) if masses else None,
        "insufficientMassN": len(masses),
        "anchorHeightDiffMean": round(statistics.fmean(diffs), 1) if diffs else None,
        "anchorHeightDiffN": len(diffs),
        "deviationRows": len(dev),
        "deviationByBucket": {b: sum(1 for r in dev if r["anchorBucket"] == b)
                              for b in sorted({str(r["anchorBucket"]) for r in dev})},
    }


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
        # P2-3 观察指标（登记不下结论；判据变更走预登记）
        "anchorObservations": anchor_observations(settled),
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
