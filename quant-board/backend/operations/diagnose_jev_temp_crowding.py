# -*- coding: utf-8 -*-
"""T-jev2 诊断：jev 温度/拥挤分数轴的分带区分度（用户提议 jev 情绪分带阶梯的证据门）。

四口径（连续分 → 样本四分位分带，主读=Q4 vs Q1）：
  slot_temperature 同槽 as-of（1070 冻结槽文档 100% 覆盖）
  slot_crowding    同槽 as-of
  day_temperature  前日 eod as-of（113 eod 文档 100% 覆盖，字段=scores.day_temperature）
  day_crowding     前日 eod as-of
附加：Spearman 秩相关（温度↔拥挤、温度↔同槽 emotionScore、日温↔前日 emotionScore）——检验与
规则分轴的正交性（高相关=影子信号无增量；低相关=独立信息源）。
阈值纪律：分带阈值取样本分位数（LLM 分数标定未知，禁止照抄规则四带——用户裁决 2026-10-01）。
产物 data/reports/phase-monitor/jev-temp-crowding.json。
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pymongo import MongoClient

from backend.operations.phase_pulse import load_eod_scores

FRAMES = Path("data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
OUT = Path("data/reports/phase-monitor/jev-temp-crowding.json")
CALIBERS = ["slot_temperature", "slot_crowding", "day_temperature", "day_crowding"]


def mannwhitney_u(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3 or len(b) < 3:
        return None
    all_v = [(v, 0) for v in a] + [(v, 1) for v in b]
    all_v.sort(key=lambda x: x[0])
    ranks = [0.0] * len(all_v)
    i = 0
    while i < len(all_v):
        j = i
        while j < len(all_v) and all_v[j][0] == all_v[i][0]:
            j += 1
        rank = (i + j - 1) / 2 + 1
        for k in range(i, j):
            ranks[k] = rank
        i = j
    r_a = sum(ranks[k] for k, (_, g) in enumerate(all_v) if g == 0)
    n1, n2 = len(a), len(b)
    u1 = r_a - n1 * (n1 + 1) / 2
    mu, sigma = n1 * n2 / 2, math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    if sigma == 0:
        return None
    return round(2 * (1 - 0.5 * (1 + math.erf(abs((u1 - mu) / sigma) / math.sqrt(2)))), 5)


def spearman(x: list[float], y: list[float]) -> float | None:
    """Spearman 秩相关（秩上 Pearson；并列取平均秩）。样本 <10 → None。"""
    if len(x) != len(y) or len(x) < 10:
        return None

    def ranks(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        out = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j < len(order) and vals[order[j]] == vals[order[i]]:
                j += 1
            avg = (i + j - 1) / 2 + 1
            for k in range(i, j):
                out[order[k]] = avg
            i = j
        return out

    rx, ry = ranks(x), ranks(y)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if vx == 0 or vy == 0:
        return None
    return round(cov / (vx * vy), 4)


def frame_prices(frame: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in frame.get("stocks") or []:
        code = str(row.get("code") or "")
        try:
            p = float(row.get("lastPrice") or row.get("price") or row.get("close") or row.get("closePrice"))
        except (TypeError, ValueError):
            continue
        if p > 0:
            out[code] = p
    return out


def pool_return(prev_prices: dict[str, float], cur_prices: dict[str, float]) -> float | None:
    shared = [c for c in prev_prices if c in cur_prices]
    if len(shared) < 5:
        return None
    rets = [cur_prices[c] / prev_prices[c] - 1 for c in shared]
    return sum(rets) / len(rets)


def quartiles(vals: list[float]) -> tuple[float, float, float]:
    s = sorted(vals)
    n = len(s)

    def q(p: float) -> float:
        idx = min(n - 1, max(0, int(p * (n - 1))))
        return s[idx]

    return q(0.25), q(0.50), q(0.75)


def main() -> int:
    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]
    slot_sc: dict[tuple[str, str], dict] = {}
    for doc in db["hotlist_jev_sentiment_v2"].find({"kind": "slot", "status": "ok"}, {"tradingDate": 1, "slotTime": 1, "scores": 1}):
        sc = doc.get("scores") or {}
        t, c = sc.get("temperature"), sc.get("crowding")
        if isinstance(t, (int, float)) or isinstance(c, (int, float)):
            slot_sc[(str(doc.get("tradingDate")), str(doc.get("slotTime")))] = {
                "slot_temperature": float(t) if isinstance(t, (int, float)) else None,
                "slot_crowding": float(c) if isinstance(c, (int, float)) else None,
            }
    day_sc: dict[str, dict] = {}
    for doc in db["hotlist_jev_sentiment_v2"].find({"kind": "eod", "status": "ok"}, {"tradingDate": 1, "scores": 1}):
        sc = doc.get("scores") or {}
        t, c = sc.get("day_temperature"), sc.get("day_crowding")
        if isinstance(t, (int, float)) or isinstance(c, (int, float)):
            day_sc[str(doc.get("tradingDate"))] = {
                "day_temperature": float(t) if isinstance(t, (int, float)) else None,
                "day_crowding": float(c) if isinstance(c, (int, float)) else None,
            }

    # 规则分轴（同槽 emotionScore + 前日 EOD）——正交性检验用
    rule_slot: dict[tuple[str, str], float] = {}
    for doc in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": {"$ne": "EOD"}},
        {"tradingDate": 1, "slotTime": 1, "emotionScore.score": 1},
    ):
        es = doc.get("emotionScore")
        if isinstance(es, dict) and isinstance(es.get("score"), (int, float)):
            rule_slot[(str(doc.get("tradingDate")), str(doc.get("slotTime")))] = float(es["score"])
    eod = load_eod_scores("2026-09-30")
    dates = sorted(d for d, s in eod.items() if isinstance(s, (int, float)))
    prev_score = {dates[i]: eod[dates[i - 1]] for i in range(1, len(dates))}
    prev_day = {dates[i]: dates[i - 1] for i in range(1, len(dates))}

    # 帧级流式：H1 + 四口径分数 + 规则分数
    dec = json.JSONDecoder()
    rows: list[dict] = []
    with gzip.open(FRAMES, "rt", encoding="utf-8") as f:
        text = f.read()
    idx, n = 0, len(text)
    while idx < n and text[idx] != "[":
        idx += 1
    idx += 1
    prev_prices: dict[str, float] | None = None
    prev_date: str | None = None
    while idx < n:
        while idx < n and text[idx] in " \t\r\n,":
            idx += 1
        if idx >= n or text[idx] == "]":
            break
        frame, end = dec.raw_decode(text, idx)
        idx = end
        d = str(frame.get("tradingDate") or "")
        slot = str(frame.get("slotTime") or "")
        prices = frame_prices(frame)
        if not prices:
            continue
        h1 = pool_return(prev_prices, prices) if (prev_prices is not None and prev_date == d) else None
        if h1 is not None:
            row: dict = {"month": d[:7], "h1": h1}
            ss = slot_sc.get((d, slot))
            if ss:
                row.update(ss)
            pd_ = prev_day.get(d)
            ds = day_sc.get(pd_) if pd_ else None
            if ds:
                row.update(ds)
            rs = rule_slot.get((d, slot))
            if isinstance(rs, (int, float)):
                row["rule_score"] = rs
            if any(k in row for k in CALIBERS):
                rows.append(row)
        prev_prices, prev_date = prices, d

    def spearman_caliber(c: str, other: str, other_map: dict) -> float | None:
        pairs = [(r[c], other_map.get((r.get("_d"), r.get("_s")) if other == "rule" else None, None)) for r in rows]

    # 分带区分度（阈值=本样本四分位，预登记）+ 秩相关
    frame_sep: dict[str, dict] = {}
    for c in CALIBERS:
        sel = [r for r in rows if isinstance(r.get(c), (int, float))]
        vals = [r[c] for r in sel]
        q1, q2, q3 = quartiles(vals)
        bands: dict[str, list[float]] = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
        for r in sel:
            v = r[c]
            key = "Q1" if v <= q1 else "Q2" if v <= q2 else "Q3" if v <= q3 else "Q4"
            bands[key].append(r["h1"])

        def sep(a: list[float], b: list[float]) -> dict:
            if not a or not b:
                return {"nA": len(a), "nB": len(b)}
            return {"nA": len(a), "nB": len(b),
                    "meanA": round(sum(a) / len(a), 5), "meanB": round(sum(b) / len(b), 5),
                    "meanDiff": round(sum(a) / len(a) - sum(b) / len(b), 5),
                    "p": mannwhitney_u(a, b)}

        months = sorted({r["month"] for r in sel})
        per_month = {}
        for m in months:
            ms = [r for r in sel if r["month"] == m]
            mv = [r[c] for r in ms]
            if len(mv) < 12:
                continue
            mq1, _, mq3 = quartiles(mv)
            lo = [r["h1"] for r in ms if r[c] <= mq1]
            hi = [r["h1"] for r in ms if r[c] > mq3]
            s = sep(lo, hi)
            s["month"] = m
            per_month[m] = s
        frame_sep[c] = {
            "thresholds": {"p25": q1, "p50": q2, "p75": q3},
            "coverage": len(sel),
            "q4_vs_q1": sep(bands["Q4"], bands["Q1"]),
            "top_vs_bottom_half": sep([r["h1"] for r in sel if r[c] > q2], [r["h1"] for r in sel if r[c] <= q2]),
            "perMonthQ4vsQ1": per_month,
        }

    # 秩相关：正交性检验
    def collect(c: str, other_key: str, get_other) -> tuple[list[float], list[float]]:
        xs, ys = [], []
        for r in rows:
            if not isinstance(r.get(c), (int, float)):
                continue
            o = get_other(r)
            if isinstance(o, (int, float)):
                xs.append(r[c])
                ys.append(float(o))
        return xs, ys

    correlations: dict[str, float | None] = {}
    xs, ys = collect("slot_temperature", "slot_crowding", lambda r: r.get("slot_crowding"))
    correlations["slotTemp_vs_slotCrowding"] = spearman(xs, ys)
    xs, ys = collect("slot_temperature", "rule", lambda r: r.get("rule_score"))
    correlations["slotTemp_vs_ruleScore_sameSlot"] = spearman(xs, ys)
    xs, ys = collect("slot_crowding", "rule", lambda r: r.get("rule_score"))
    correlations["slotCrowding_vs_ruleScore_sameSlot"] = spearman(xs, ys)
    day_map = prev_day
    xs, ys = [], []
    for d, pd_ in day_map.items():
        ds = day_sc.get(pd_)
        ps = prev_score.get(d)
        if ds and isinstance(ds.get("day_temperature"), (int, float)) and isinstance(ps, (int, float)):
            xs.append(ds["day_temperature"])
            ys.append(float(ps))
    correlations["dayTemp_prev_vs_ruleScore_prevEod"] = spearman(xs, ys)

    report = {
        "meta": {
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "purpose": "T-jev2：jev 温度/拥挤分数轴分带区分度（jev 情绪分带阶梯候选的证据门；阈值=样本分位数，禁抄规则四带）",
            "framesJoined": len(rows),
            "asOf": "slot 口径=同槽；day 口径=前日 eod（字段名勘误：eod 文档实为 scores.day_temperature/day_crowding，此前 C3 误读为未落库）",
        },
        "frameSeparation": frame_sep,
        "correlations": correlations,
        "gateHint": None,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {c: {"q4_vs_q1": frame_sep[c]["q4_vs_q1"], "thresholds": frame_sep[c]["thresholds"]} for c in CALIBERS}
    print(json.dumps({"frameSep": summary, "correlations": correlations}, ensure_ascii=False, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
