# -*- coding: utf-8 -*-
"""SP3-T4 转折点 corroborate 披露诊断（只读；披露不进控制面——章程 §3.3）。

问题：炸板率/连板高度/涨停家数在带转移（→弱/→冷）前 1-3 日是否系统性异常？
数据：frames marketContext.limitSummary（当日最后含 limitSummary 的帧，优先 15:00 后；
缺帧日 insufficient 计数——沿 diagnose_theme_rotation_r1 先例）。
转移日集合：gen7 基线 54 笔持仓期内「前日定相带首次下移」（与 downgrade-rule-variants 同源逻辑）。
产物 data/reports/phase-monitor/phase-turning-points.json。
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_pulse import load_eod_scores

SUMMARY = Path("data/reports/b-202610/t6-runs-formal/1-summary.json")
FRAMES = Path("data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
OUT = Path("data/reports/phase-monitor/phase-turning-points.json")


def band_of(score: float) -> str:
    if score < 40.0:
        return "冷10-40"
    if score < 60.0:
        return "弱势40-60"
    if score < 80.0:
        return "强60-80"
    return "极热≥80"


def extract_metrics(ls: dict) -> dict | None:
    try:
        zb = ls.get("zhaban") or {}
        cb = ls.get("continuousBoards") or {}
        rate = float(zb.get("rate")) if zb.get("rate") is not None else None
        max_board = 0
        for k in (1, 2, 3):
            if int(cb.get(f"board{k}") or 0) > 0:
                max_board = k
        if int(cb.get("board4plus") or 0) > 0:
            max_board = 4
        zt = sum(int(cb.get(f"board{k}") or 0) for k in (1, 2, 3)) + int(cb.get("board4plus") or 0)
        return {"bombRate": rate, "maxBoard": max_board, "ztCount": zt}
    except (TypeError, ValueError):
        return None


def stream_daily_metrics(path: Path) -> tuple[dict[str, dict], list[str]]:
    """{date: metrics}（当日最后含 limitSummary 的帧）；缺日列表由调用方按 dates 集合推。"""
    dec = json.JSONDecoder()
    out: dict[str, dict] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        text = f.read()
    idx, n = 0, len(text)
    while idx < n and text[idx] != "[":
        idx += 1
    idx += 1
    while idx < n:
        while idx < n and text[idx] in " \t\r\n,":
            idx += 1
        if idx >= n or text[idx] == "]":
            break
        frame, end = dec.raw_decode(text, idx)
        idx = end
        if not isinstance(frame, dict):
            continue
        slot = str(frame.get("slotTime") or "")
        if slot not in ("15:00", "15:30"):
            continue  # 只看尾盘帧（日内炸板率噪声大）
        ls = (frame.get("marketContext") or {}).get("limitSummary")
        if not ls:
            continue
        m = extract_metrics(ls)
        if m is None:
            continue
        out[str(frame.get("tradingDate") or "")] = m  # 后写覆盖：15:30 优先于 15:00
    return out


def main() -> int:
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    eod = load_eod_scores("2026-09-30")
    dates = sorted(d for d, s in eod.items() if isinstance(s, (int, float)))
    prev_score = {dates[i]: eod[dates[i - 1]] for i in range(1, len(dates))}
    metrics = stream_daily_metrics(FRAMES)
    insufficient = [d for d in dates if d not in metrics]

    # 转移日集合（与 downgrade-rule-variants 同源逻辑）
    transitions: list[dict] = []
    for t in summary.get("roundTripTrades") or []:
        ed, xd = str(t.get("entryTradingDate") or ""), str(t.get("exitTradingDate") or "")
        pe = prev_score.get(ed)
        if not isinstance(pe, (int, float)):
            continue
        entry_band = band_of(float(pe))
        for d in dates:
            if d <= ed or d > xd:
                continue
            b = band_of(float(prev_score[d]))
            if b != entry_band:
                transitions.append({"entryBand": entry_band, "to": b, "date": d, "code": t.get("code")})
                break
    trans_by_target: dict[str, list[str]] = {}
    for x in transitions:
        trans_by_target.setdefault(x["to"], []).append(x["date"])

    # 基线：全部有指标日的读数
    base_bomb = [m["bombRate"] for m in metrics.values() if m["bombRate"] is not None]
    base_zt = [m["ztCount"] for m in metrics.values()]
    base_mb = [m["maxBoard"] for m in metrics.values()]
    baseline = {
        "days": len(metrics), "insufficientDays": len(insufficient),
        "bombRate": {"mean": round(sum(base_bomb) / len(base_bomb), 2) if base_bomb else None,
                     "gt40Count": sum(1 for v in base_bomb if v > 40)},
        "ztCount": {"mean": round(sum(base_zt) / len(base_zt), 1) if base_zt else None},
        "maxBoard": {"mean": round(sum(base_mb) / len(base_mb), 2) if base_mb else None},
    }

    def pre_readings(target: str) -> dict:
        ds = trans_by_target.get(target, [])
        pre = {"bombRate": [], "ztCount": [], "maxBoard": [], "bombGt40Within3d": 0}
        rows = []
        for td in sorted(set(ds)):
            i = dates.index(td) if td in dates else None
            if i is None:
                continue
            window = [metrics[x] for x in dates[max(0, i - 3):i] if x in metrics]
            if not window:
                rows.append({"date": td, "insufficient": True})
                continue
            brs = [w["bombRate"] for w in window if w["bombRate"] is not None]
            pre["bombRate"] += brs
            pre["ztCount"] += [w["ztCount"] for w in window]
            pre["maxBoard"] += [w["maxBoard"] for w in window]
            if any(b > 40 for b in brs):
                pre["bombGt40Within3d"] += 1
            rows.append({"date": td, "bombRates": brs,
                         "ztCounts": [w["ztCount"] for w in window],
                         "maxBoards": [w["maxBoard"] for w in window]})
        n = len(rows)
        br = pre["bombRate"]
        return {"transitions": n, "datedRows": n - sum(1 for r in rows if r.get("insufficient")),
                "preBombRateMean": round(sum(br) / len(br), 2) if br else None,
                "preBombGt40Rate": round(pre["bombGt40Within3d"] / n, 2) if n else None,
                "preZtMean": round(sum(pre["ztCount"]) / len(pre["ztCount"]), 1) if pre["ztCount"] else None,
                "preMaxBoardMean": round(sum(pre["maxBoard"]) / len(pre["maxBoard"]), 2) if pre["maxBoard"] else None,
                "rows": rows}

    report = {
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "purpose": "SP3-T4 转折点 corroborate 披露（只读；15:00/15:30 尾盘帧 limitSummary）",
                 "disclosureOnly": True},
        "baseline": baseline,
        "transitions": {k: pre_readings(k) for k in ("弱势40-60", "冷10-40")},
        "insufficientDates": insufficient,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"baseline": baseline,
                      "toWeak": {k: v for k, v in report["transitions"]["弱势40-60"].items() if k != "rows"},
                      "toCold": {k: v for k, v in report["transitions"]["冷10-40"].items() if k != "rows"}},
                     ensure_ascii=False, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
