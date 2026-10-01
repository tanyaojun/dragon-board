# -*- coding: utf-8 -*-
"""SP3-T3.1 slot 级 as-of 情绪增量检验（证据门）。

对比两口径在同一帧集合上的定相与区分度：
  prev_eod : 前日 EOD 分（现行口径）
  slot     : 同日严格早于当前帧 slot 的最近档 emotionScore（无档回退前日 EOD）
主读数：帧级池等权 H1 的 offense vs defense 分离度（逐月 + 全窗），按口径对照。
门（预登记）：slot 口径区分度不劣于 prev_eod 且至少一月显著更优 → 解锁 source 开关；否则否定收口。
只读；产物 data/reports/phase-monitor/slot-asof-diff.json。
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

from pymongo import MongoClient

from backend.operations.phase_pulse import load_eod_scores

FRAMES = Path("data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
OUT = Path("data/reports/phase-monitor/slot-asof-diff.json")
THRESHOLD = 60.0


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
    # ① slot 分数表：{date: [(slot, score)] 升序}
    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]
    slot_map: dict[str, list[tuple[str, float]]] = {}
    for doc in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour"},
        {"tradingDate": 1, "slotTime": 1, "emotionScore.score": 1},
    ):
        if str(doc.get("slotTime") or "") == "EOD":
            continue
        es = doc.get("emotionScore")
        if isinstance(es, dict) and isinstance(es.get("score"), (int, float)):
            slot_map.setdefault(str(doc.get("tradingDate") or ""), []).append(
                (str(doc.get("slotTime")), float(es["score"])))
    for d in slot_map:
        slot_map[d].sort()

    def slot_asof(d: str, slot: str) -> float | None:
        best = None
        for s, v in slot_map.get(d, []):
            if s < str(slot or ""):
                best = v
            else:
                break
        return best

    eod = load_eod_scores("2026-09-30")
    dates = sorted(d for d, s in eod.items() if isinstance(s, (int, float)))
    prev_score = {dates[i]: eod[dates[i - 1]] for i in range(1, len(dates))}

    # ② 流式帧：H1 + 双口径定相
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
        ps = prev_score.get(d)
        ss = slot_asof(d, str(frame.get("slotTime") or ""))
        if h1 is not None and isinstance(ps, (int, float)) and ss is not None:
            rows.append({"month": d[:7], "h1": h1,
                         "prev_eod": "offense" if ps >= THRESHOLD else "defense",
                         "slot": "offense" if ss >= THRESHOLD else "defense",
                         "agree": (ps >= THRESHOLD) == (ss >= THRESHOLD)})
        prev_prices, prev_date = prices, d

    def sep(key: str, month: str | None) -> dict:
        sel = [r for r in rows if month is None or r["month"] == month]
        off = [r["h1"] for r in sel if r[key] == "offense"]
        dnf = [r["h1"] for r in sel if r[key] == "defense"]
        if not off or not dnf:
            return {"nOff": len(off), "nDef": len(dnf)}
        return {"nOff": len(off), "nDef": len(dnf),
                "meanOff": round(sum(off) / len(off), 5), "meanDef": round(sum(dnf) / len(dnf), 5),
                "meanDiff": round(sum(off) / len(off) - sum(dnf) / len(dnf), 5),
                "p": mannwhitney_u(off, dnf)}

    months = sorted({r["month"] for r in rows})
    agree_rate = round(sum(1 for r in rows if r["agree"]) / len(rows), 4) if rows else None
    report = {
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "threshold": THRESHOLD,
                 "purpose": "SP3-T3.1 slot as-of 增量检验（门=slot 区分度不劣于 prev_eod 且至少一月显著更优）"},
        "agreeRate": agree_rate, "frames": len(rows),
        "allWindow": {"prev_eod": sep("prev_eod", None), "slot": sep("slot", None)},
        "perMonth": {m: {"prev_eod": sep("prev_eod", m), "slot": sep("slot", m)} for m in months},
    }
    # 门判定：slot 全窗 |meanDiff| ≥ prev_eod 且存在一月 slot p<0.05 且方向同向
    aw_s, aw_p = report["allWindow"]["slot"], report["allWindow"]["prev_eod"]
    not_worse = (aw_s.get("meanDiff") is not None and aw_p.get("meanDiff") is not None
                 and abs(aw_s["meanDiff"]) >= abs(aw_p["meanDiff"]))
    better_month = any(
        (v["slot"].get("p") is not None and v["slot"]["p"] < 0.05
         and v["slot"].get("meanDiff", 0) is not None and v["slot"]["meanDiff"] > 0
         and (v["prev_eod"].get("p") is None or v["prev_eod"]["p"] >= 0.05))
        for v in report["perMonth"].values())
    report["gateVerdict"] = ("达标（解锁 source 开关）" if (not_worse and better_month)
                             else "不达标：slot 口径无增量 → SP3-T3.2 否定收口")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"agreeRate": agree_rate, "allWindow": report["allWindow"],
                      "gateVerdict": report["gateVerdict"]}, ensure_ascii=False, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
