# -*- coding: utf-8 -*-
"""SP3+ D1 冷带带内异质性检验（5 带提议的证据门；只读诊断，不动引擎）。

切分：前日 EOD 分 ≤20 → 极弱≤20；20-40 → 弱20-40（切分点 20 为主判据；15/25 为敏感性参考，不参与门判定）。
主证据：帧级池等权 H1（相邻帧共享码）；敏感性：日级 H1（日末帧跨日）。
门（预登记）：切分点 20 下，极弱 vs 弱 逐月 MW/均值差，≥2 个月显著（p<0.05 或 |均值差|≥2%）且同向
→ D1 通过，进入 D2 调仓反事实；不通过 = 5 带提议否定收口。
产物 data/reports/phase-monitor/band5-split.json。
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
OUT = Path("data/reports/phase-monitor/band5-split.json")
CUTS = [15.0, 20.0, 25.0]
GATE_CUT = 20.0


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


def pool_return(prev_prices: dict[str, float], cur_prices: dict[str, float]) -> float | None:
    shared = [c for c in prev_prices if c in cur_prices]
    if len(shared) < 5:
        return None
    rets = [cur_prices[c] / prev_prices[c] - 1 for c in shared]
    return sum(rets) / len(rets)


def main() -> int:
    eod = load_eod_scores("2026-09-30")
    dates = sorted(d for d, s in eod.items() if isinstance(s, (int, float)))
    prev_score = {dates[i]: eod[dates[i - 1]] for i in range(1, len(dates))}

    def cell_of(d: str, cut: float) -> str | None:
        ps = prev_score.get(d)
        if not isinstance(ps, (int, float)) or not (0.0 <= float(ps) < 40.0):
            return None  # 只研究冷带内部
        return "极弱" if ps < cut else "弱"

    rows: list[dict] = []
    day_last: dict[str, dict[str, float]] = {}
    dec = json.JSONDecoder()
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
        cells = {str(cut): cell_of(d, cut) for cut in CUTS}
        if h1 is not None and cells[str(GATE_CUT)] is not None:
            rows.append({"date": d, "month": d[:7], "h1": h1, "cells": cells})
        prev_prices, prev_date = prices, d
        day_last[d] = prices

    # 日级敏感性：日末帧 vs 次日末帧（两日同 cell 才计入）
    ordered = [d for d in dates if d in day_last]
    for i in range(1, len(ordered)):
        d0, d1 = ordered[i - 1], ordered[i]
        c0, c1 = cell_of(d0, GATE_CUT), cell_of(d1, GATE_CUT)
        if c0 is None or c1 is None or c0 != c1:
            continue
        r = pool_return(day_last[d0], day_last[d1])
        if r is not None:
            rows.append({"date": d1, "month": d1[:7], "dayH1": r, "cells": {str(GATE_CUT): c0}})
    day_rows = [r for r in rows if "dayH1" in r]

    def sep(cut: str, month: str | None, key: str) -> dict:
        sel = [r for r in (day_rows if key == "dayH1" else rows)
               if (month is None or r["month"] == month) and r["cells"].get(cut) is not None and key in r]
        a = [r[key] for r in sel if r["cells"][cut] == "极弱"]
        b = [r[key] for r in sel if r["cells"][cut] == "弱"]
        if not a or not b:
            return {"nJi": len(a), "nRuo": len(b)}
        p = mannwhitney_u(a, b)
        diff = round(sum(a) / len(a) - sum(b) / len(b), 5)
        return {"nJi": len(a), "nRuo": len(b),
                "meanJi": round(sum(a) / len(a), 5), "meanRuo": round(sum(b) / len(b), 5),
                "meanDiff": diff, "p": p,
                "significant": bool((p is not None and p < 0.05) or abs(diff) >= 0.02)}

    months = sorted({r["month"] for r in rows})
    primary = {}
    sig_months, dirs = [], set()
    for m in months:
        s = sep(str(GATE_CUT), m, "h1")
        primary[m] = s
        if s.get("significant") and s.get("meanDiff") is not None:
            sig_months.append((m, s))
            dirs.add("ji>ruo" if s["meanDiff"] > 0 else "ruo>ji")
    same_dir = len(dirs) == 1 and len(sig_months) >= 2
    gate_pass = bool(same_dir)

    report = {
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "purpose": "SP3+ D1 冷带带内异质性（切分点 20 主判据；15/25 敏感性）",
                 "gate": "切分点 20：≥2 个月显著且同向 → D2；否则 5 带否定收口",
                 "framesCold": len([r for r in rows if "h1" in r])},
        "gateVerdict": ("通过（进入 D2）：显著月=" + str([m for m, _ in sig_months])
                        if gate_pass else
                        f"不通过：显著月 {len(sig_months)} 个 <2 或方向不一致（{sorted(dirs) or '无'}）→ 5 带提议否定收口"),
        "primaryCut20": {"perMonth": primary, "gatePass": gate_pass,
                         "allWindow": sep(str(GATE_CUT), None, "h1")},
        "dailySensitivityCut20": {"allWindow": sep(str(GATE_CUT), None, "dayH1"),
                                  "perMonth": {m: sep(str(GATE_CUT), m, "dayH1") for m in months}},
        "cutSensitivityAllWindow": {f"cut{c}": sep(str(c), None, "h1") for c in CUTS if str(c) != str(GATE_CUT)},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"gateVerdict": report["gateVerdict"],
                      "primaryCut20": report["primaryCut20"],
                      "allWindowDaily": report["dailySensitivityCut20"]["allWindow"],
                      "cutSensitivity": report["cutSensitivityAllWindow"]},
                     ensure_ascii=False, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
