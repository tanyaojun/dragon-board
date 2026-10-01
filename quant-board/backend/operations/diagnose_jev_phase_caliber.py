# -*- coding: utf-8 -*-
"""T-jev 相位口径对比诊断（用户提议：采用 jev 档位作为相位定义/北极星原料的证据门）。

四口径（两档 offense/defense）：
  C1 rules_prev_eod : 前日 emotionScore ≥60（现行生产定义，champion 输入）
  C2 jev_day_stage  : 前日 jev day_stage 五档映射（start/ferment/climax→offense，ice/retreat→defense）
  C3 jev_day_temp   : 前日 jev eod temperature ≥50
  C4 jev_seq_slot   : 同槽 jev sequence_stage 五档映射（新鲜读，与入场信号同时点证据）
读数：帧级池等权 H1 分离度（逐月+全窗）+ 交易层北极星角色表（C1-C3）。
门（预登记）：C2/C4 全窗区分度 ≥ C1 且逐月方向一致性不劣 → 支持采用 jev 为相位源（另走设计文档修订）；
否则维持规则口径、jev 留披露层。
产物 data/reports/phase-monitor/jev-phase-caliber.json。
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

SUMMARY = Path("data/reports/b-202610/t6-runs-formal/1-summary.json")
FRAMES = Path("data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
OUT = Path("data/reports/phase-monitor/jev-phase-caliber.json")
THRESHOLD = 60.0
TEMP_THRESHOLD = 50.0
OFFENSE = {"start", "ferment", "climax"}


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
    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]
    jev_eod: dict[str, dict] = {}
    jev_slot: dict[tuple[str, str], dict] = {}
    for doc in db["hotlist_jev_sentiment"].find({"status": "ok"}):
        ans = doc.get("answers") or {}
        d, s = str(doc.get("tradingDate") or ""), str(doc.get("slotTime") or "")
        sc = doc.get("scores") or {}
        if doc.get("kind") == "eod" and ans.get("day_stage"):
            jev_eod[d] = {"stage": ans["day_stage"].get("choice"),
                          "temp": (ans.get("day_temperature") or {}).get("score") or sc.get("temperature")}
        elif doc.get("kind") == "slot" and ans.get("sequence_stage"):
            jev_slot[(d, s)] = {"stage": ans["sequence_stage"].get("choice")}

    eod = load_eod_scores("2026-09-30")
    dates = sorted(d for d, s in eod.items() if isinstance(s, (int, float)))
    prev_score = {dates[i]: eod[dates[i - 1]] for i in range(1, len(dates))}
    prev_day = {dates[i]: dates[i - 1] for i in range(1, len(dates))}

    def caliber_labels(d: str, slot: str | None = None) -> dict:
        """四口径两档标签（None=该口径不可定相）。"""
        out: dict[str, str | None] = {}
        ps = prev_score.get(d)
        out["C1_rules_prev_eod"] = ("offense" if isinstance(ps, (int, float)) and ps >= THRESHOLD
                                    else "defense") if isinstance(ps, (int, float)) else None
        pd_ = prev_day.get(d)
        je = jev_eod.get(pd_) if pd_ else None
        out["C2_jev_day_stage"] = (("offense" if je["stage"] in OFFENSE else "defense") if je else None)
        out["C3_jev_day_temp"] = (("offense" if float(je["temp"]) >= TEMP_THRESHOLD else "defense")
                                  if je and isinstance(je.get("temp"), (int, float)) else None)
        js = jev_slot.get((d, str(slot or ""))) if slot else None
        out["C4_jev_seq_slot"] = (("offense" if js["stage"] in OFFENSE else "defense") if js else None)
        return out

    # ① 帧级流式：H1 + 四口径标签
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
        prices = frame_prices(frame)
        if not prices:
            continue
        h1 = pool_return(prev_prices, prices) if (prev_prices is not None and prev_date == d) else None
        if h1 is not None:
            labels = caliber_labels(d, str(frame.get("slotTime") or ""))
            if any(v is not None for v in labels.values()):
                rows.append({"month": d[:7], "h1": h1, "labels": labels})
        prev_prices, prev_date = prices, d

    # ② 帧级分离度逐口径（全窗 + 逐月）
    calibers = ["C1_rules_prev_eod", "C2_jev_day_stage", "C3_jev_day_temp", "C4_jev_seq_slot"]

    def sep(c: str, month: str | None) -> dict:
        sel = [r for r in rows if (month is None or r["month"] == month) and r["labels"].get(c)]
        off = [r["h1"] for r in sel if r["labels"][c] == "offense"]
        dnf = [r["h1"] for r in sel if r["labels"][c] == "defense"]
        if not off or not dnf:
            return {"nOff": len(off), "nDef": len(dnf)}
        return {"nOff": len(off), "nDef": len(dnf),
                "meanOff": round(sum(off) / len(off), 5), "meanDef": round(sum(dnf) / len(dnf), 5),
                "meanDiff": round(sum(off) / len(off) - sum(dnf) / len(dnf), 5),
                "p": mannwhitney_u(off, dnf)}

    months = sorted({r["month"] for r in rows})
    frame_sep = {c: {"allWindow": sep(c, None), "perMonth": {m: sep(c, m) for m in months}} for c in calibers}

    # ③ 交易层北极星角色表（C1-C3，按入场日标签）
    trades = json.loads(SUMMARY.read_text(encoding="utf-8")).get("roundTripTrades") or []
    trade_role = {}
    for c in ("C1_rules_prev_eod", "C2_jev_day_stage", "C3_jev_day_temp"):
        roles: dict[str, list[dict]] = {"offense": [], "defense": []}
        for t in trades:
            lb = caliber_labels(str(t.get("entryTradingDate") or ""))[c]
            if lb:
                roles[lb].append(t)
        out_role = {}
        for role, ts in roles.items():
            rets = [float(t["netReturn"]) for t in ts if isinstance(t.get("netReturn"), (int, float))]
            wins = [r for r in rets if r > 0]
            losses = [r for r in rets if r <= 0]
            pf = round(sum(wins) / abs(sum(losses)), 4) if losses and sum(losses) != 0 else None
            out_role[role] = {"trades": len(rets), "winRate": round(len(wins) / len(rets), 4) if rets else None,
                              "profitFactor": pf, "sumNetReturn": round(sum(rets), 4) if rets else None}
        trade_role[c] = out_role

    # ④ 门判定（预登记）
    def consistency(c: str) -> int:
        dirs = []
        for m in months:
            s = frame_sep[c]["perMonth"][m]
            if s.get("meanDiff") is not None and (s.get("p") is not None and s["p"] < 0.05 or abs(s["meanDiff"]) >= 0.002):
                dirs.append(1 if s["meanDiff"] > 0 else -1)
        return len(dirs) - abs(sum(dirs)) if dirs else -1

    aw = {c: frame_sep[c]["allWindow"] for c in calibers}
    c1_abs = abs(aw["C1_rules_prev_eod"].get("meanDiff") or 0)
    better = {c: (abs(aw[c].get("meanDiff") or 0) >= c1_abs and (aw[c].get("p") is not None and aw[c]["p"] < 0.05))
              for c in ("C2_jev_day_stage", "C3_jev_day_temp", "C4_jev_seq_slot")}
    report = {
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "purpose": "T-jev 相位口径对比（用户提议 jev 档位作相位源的证据门；映射 start/ferment/climax→offense，ice/retreat→defense）",
                 "frames": len(rows)},
        "frameSeparation": frame_sep,
        "tradeLayerRoles": trade_role,
        "gateVerdict": None,
    }
    if better["C2_jev_day_stage"] or better["C4_jev_seq_slot"]:
        report["gateVerdict"] = "jev 口径区分度优于规则口径 → 支持采用 jev 为相位源（须另行修订设计文档 §6/§10.5 边界）"
    else:
        report["gateVerdict"] = "jev 口径未显示区分度优势 → 维持规则口径，jev 留披露层"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"allWindow": aw,
                      "monthlyConsistentMonths": {c: consistency(c) for c in calibers},
                      "tradeRoles_C2": trade_role["C2_jev_day_stage"],
                      "gateVerdict": report["gateVerdict"]}, ensure_ascii=False, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
