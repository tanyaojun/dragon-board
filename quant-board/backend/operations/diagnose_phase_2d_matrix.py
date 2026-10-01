# -*- coding: utf-8 -*-
"""SP3-T1 2D 矩阵重推导（水平带 × Δ 方向；v2 四带边界；证据门）。

维度：band(prev 严格前日分) × direction(delta = prev − prev2 ≥ deltaUpMin → up，否则 down)。
主证据：帧级池等权 H1（相邻帧共享码）+ H8；敏感性：日级 H1。逐月 up vs down 分离度
（MW + 均值差）——2D 相对 1D 的增量主张 = 带内 Δ 方向可分离。
门（预登记）：任一带 ≥2 个月同向显著（p<0.05 或 |均值差|≥2%）→ 解锁 ladder2d 载体；
全部不达标 = SP3-T2 否定收口。
只读；产物 data/reports/phase-monitor/phase-2d-matrix.json。
"""
from __future__ import annotations

import gzip
import json
import math
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_pulse import load_eod_scores

FRAMES = Path("data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
OUT = Path("data/reports/phase-monitor/phase-2d-matrix.json")
DELTA_UP_MINS = [0.0, 5.0, 10.0, 15.0]


def band_of(score: float) -> str:
    if score < 40.0:
        return "冷10-40"
    if score < 60.0:
        return "弱势40-60"
    if score < 80.0:
        return "强60-80"
    return "极热≥80"


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
    mu = n1 * n2 / 2
    sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    if sigma == 0:
        return None
    z = (u1 - mu) / sigma
    return round(2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2)))), 5)


def frame_prices(frame: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in frame.get("stocks") or []:
        code = str(row.get("code") or "")
        price = row.get("lastPrice") or row.get("price") or row.get("close") or row.get("closePrice")
        try:
            p = float(price)
        except (TypeError, ValueError):
            continue
        if p > 0:
            out[code] = p
    return out


def pool_return(prev_prices: dict[str, float], cur_prices: dict[str, float]) -> tuple[float, int] | None:
    shared = [c for c in prev_prices if c in cur_prices]
    if len(shared) < 5:
        return None
    rets = [cur_prices[c] / prev_prices[c] - 1 for c in shared]
    return sum(rets) / len(rets), len(shared)


def main() -> int:
    eod = load_eod_scores("2026-09-30")
    dates = sorted(d for d, s in eod.items() if isinstance(s, (int, float)))
    score_at = {d: (eod[dates[i - 1]] if i >= 1 else None) for i, d in enumerate(dates)}
    prev2_at = {d: (eod[dates[i - 2]] if i >= 2 else None) for i, d in enumerate(dates)}

    # 每帧：日期 → cell（按 deltaUpMin 各档）+ 池 H1（流式：当前帧 vs 上一帧）
    dec = json.JSONDecoder()
    rows: list[dict] = []  # {date, month, h1, h8(占位后填), cells: {thr: cell}}
    day_last: dict[str, dict[str, float]] = {}
    h8_hist: deque[tuple[str, dict[str, float]]] = deque(maxlen=9)

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
        prices = frame_prices(frame)
        if not prices:
            continue
        h1 = pool_return(prev_prices, prices) if (prev_prices is not None and prev_date == d) else None
        h8 = None
        if len(h8_hist) == 8:
            old_date, old_prices = h8_hist[0]
            if old_date == d:  # 同日第 9 槽 vs 8 槽前（跨 ~1 交易日）
                h8 = pool_return(old_prices, prices)
        ps, p2 = score_at.get(d), prev2_at.get(d)
        cells = {}
        if isinstance(ps, (int, float)) and isinstance(p2, (int, float)):
            delta = float(ps) - float(p2)
            for thr in DELTA_UP_MINS:
                cells[thr] = f"{band_of(float(ps))}|{'up' if delta >= thr else 'down'}"
        if h1 is not None:
            rows.append({"date": d, "month": d[:7], "h1": h1[0], "h8": (h8 or (None,))[0], "cells": cells})
        h8_hist.append((d, prices))
        prev_prices, prev_date = prices, d
        day_last[d] = prices

    # 日级 H1（日末帧 vs 次日末帧）
    ordered_days = [d for d in dates if d in day_last]
    for i in range(1, len(ordered_days)):
        r = pool_return(day_last[ordered_days[i - 1]], day_last[ordered_days[i]])
        for row in rows:
            if row["date"] == ordered_days[i] and r is not None:
                row["dayH1"] = r[0]

    # 聚合：band × threshold × direction（帧 H1 主证据 + 日级敏感性）
    def agg(hkey: str, band: str, thr: float, direction: str) -> dict:
        vals = [r[hkey] for r in rows
                if hkey in r and r["cells"].get(thr) == f"{band}|{direction}"]
        if not vals:
            return {"n": 0}
        return {"n": len(vals), "mean": round(sum(vals) / len(vals), 5),
                "winRate": round(sum(1 for v in vals if v > 0) / len(vals), 4)}

    months = sorted({r["month"] for r in rows})
    band_sep = {}
    gate_hits = []
    for band in ("冷10-40", "弱势40-60", "强60-80", "极热≥80"):
        per_month = []
        all_up, all_down = [], []
        for m in months:
            up = [r["h1"] for r in rows if r["month"] == m and r["cells"].get(0.0) == f"{band}|up" and "h1" in r]
            dn = [r["h1"] for r in rows if r["month"] == m and r["cells"].get(0.0) == f"{band}|down" and "h1" in r]
            p = mannwhitney_u(up, dn)
            diff = round(sum(up) / len(up) - sum(dn) / len(dn), 5) if up and dn else None
            ok = bool(p is not None and p < 0.05 or (diff is not None and abs(diff) >= 0.02))
            direction = ("up" if (up and dn and sum(up) / len(up) > sum(dn) / len(dn)) else
                         "down" if (up and dn) else None)
            per_month.append({"month": m, "nUp": len(up), "nDown": len(dn), "p": p, "meanDiff": diff,
                              "significant": ok, "direction": direction})
            all_up += up
            all_down += dn
        sig_months = [x for x in per_month if x["significant"]]
        dirs = {x["direction"] for x in sig_months if x["direction"]}
        same_dir = len(dirs) == 1 and len(sig_months) >= 2
        band_sep[band] = {
            "perMonth": per_month,
            "allWindow": {"nUp": len(all_up), "nDown": len(all_down),
                          "meanUp": round(sum(all_up) / len(all_up), 5) if all_up else None,
                          "meanDown": round(sum(all_down) / len(all_down), 5) if all_down else None,
                          "p": mannwhitney_u(all_up, all_down)},
            "gate": {"significantMonths": len(sig_months), "sameDirection": same_dir,
                     "pass": bool(same_dir)},
        }
        if same_dir:
            gate_hits.append(band)

    cell_table = {}
    for thr in DELTA_UP_MINS:
        for band in ("冷10-40", "弱势40-60", "强60-80", "极热≥80"):
            for direction in ("up", "down"):
                a = agg("h1", band, thr, direction)
                if a["n"]:
                    cell_table[f"{band}|{direction}|Δ≥{thr}"] = a

    report = {
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "purpose": "SP3-T1 2D 矩阵重推导（v2 四带 × Δ 方向；门=任一带 ≥2 月同向显著）",
                 "frames": len(rows), "deltaUpMinCandidates": DELTA_UP_MINS},
        "bandSeparation": band_sep,
        "gatePassBands": gate_hits,
        "gateVerdict": ("达标（解锁 ladder2d 载体）：" + ",".join(gate_hits)) if gate_hits
                       else "不达标：无任何一带满足 ≥2 月同向显著 → SP3-T2 否定收口",
        "cellTableH1": cell_table,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"gatePassBands": gate_hits, "verdict": report["gateVerdict"],
                      "allWindow": {b: band_sep[b]["allWindow"] for b in band_sep}},
                     ensure_ascii=False, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
