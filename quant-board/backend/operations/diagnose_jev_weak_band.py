# -*- coding: utf-8 -*-
"""SP5 追加：jev 量身弱势带扫描（用户 2026-10-01 指令"为 jev 量身打造一条弱势带区间阈值"）。

背景：jev_block_v0 证明"规则分 40/60 手术刀"不可搬给 jev 两分类；本扫描在 jev 自己的刻度上找
"恰好切中亏损簇"的区间。协议（跑前冻结，防钓参数）：
  变量：slot_temperature / slot_crowding（同槽 as-of）、day_temperature / day_crowding（前日 eod）
        —— 分带阈值一律用已冻结的全窗四分位（读 T-jev2/SP5 标定产物，不重拟合）；
        sequence_stage 五档原始档位（两分类 start/ferment/climax→offense 可能把毒档藏在中间）。
  第一层（交易层 54 笔 t6 正式基线）：逐带 n/sum/每笔均值/胜率；毒带判据 = n≥8 且 mean≤−1%/笔。
  第二层（帧级佐证）：仅对第一层毒带 + 参照带（slotTemp≤Q1 = jev_band_v1）做带内 vs 带外
        H1/fwdWorst 分离（全窗 + 逐月 + 上下半窗 04-06 vs 07-09）。
  裁决：两层同向才立候选；in-sample 最多排队，走廊裁决；全带全报。
产物 data/reports/phase-monitor/jev-weak-band.json。只读，不碰引擎。
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pymongo import MongoClient

from backend.operations.diagnose_jev_temp_crowding import frame_prices, mannwhitney_u

FRAMES = Path("data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
BASELINE_TRADES = Path("data/reports/b-202610/t6-runs-formal/1-summary.json")
TEMP_CROWDING = Path("data/reports/phase-monitor/jev-temp-crowding.json")
DAY_CAL = Path("data/reports/phase-monitor/jev-day-axis-calibration.json")
OUT = Path("data/reports/phase-monitor/jev-weak-band.json")

Q1_TOXIC_MEAN = -0.01
Q1_TOXIC_N = 8


def load_frames(path: Path) -> list[dict]:
    text = gzip.open(path, "rt", encoding="utf-8").read()
    dec = json.JSONDecoder()
    idx = text.index("[") + 1
    out = []
    while True:
        while idx < len(text) and text[idx] in " \t\r\n,":
            idx += 1
        if idx >= len(text) or text[idx] == "]":
            break
        frame, idx = dec.raw_decode(text, idx)
        out.append(frame)
    return out


def pool_ret(prev: dict[str, float], cur: dict[str, float], min_shared: int = 5) -> float | None:
    shared = [c for c in prev if c in cur]
    if len(shared) < min_shared:
        return None
    return sum(cur[c] / prev[c] - 1 for c in shared) / len(shared)


def band_of(v: float | None, q: tuple[float, float, float]) -> str | None:
    if not isinstance(v, (int, float)):
        return None
    if v <= q[0]:
        return "Q1"
    if v <= q[1]:
        return "Q2"
    if v <= q[2]:
        return "Q3"
    return "Q4"


def group_stats(items: list[float]) -> dict:
    if not items:
        return {"n": 0}
    wins = [v for v in items if v > 0]
    return {"n": len(items), "sum": round(sum(items), 4), "mean": round(sum(items) / len(items), 5),
            "winRate": round(len(wins) / len(items), 3)}


def mw(a: list[float], b: list[float]) -> float | None:
    return mannwhitney_u(a, b) if len(a) >= 3 and len(b) >= 3 else None


def sep(a: list[float], b: list[float]) -> dict:
    if not a or not b:
        return {"nA": len(a), "nB": len(b)}
    return {"nA": len(a), "nB": len(b), "meanIn": round(sum(a) / len(a), 6),
            "meanOut": round(sum(b) / len(b), 6), "p": mw(a, b)}


def half(d: str) -> str:
    return "H1_0406" if d[:7] <= "2026-06" else "H2_0709"


def main() -> int:
    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]

    slot_sc: dict[tuple[str, str], dict] = {}
    for doc in db["hotlist_jev_sentiment_v2"].find({"kind": "slot", "status": "ok"},
                                                {"tradingDate": 1, "slotTime": 1, "scores": 1, "answers.sequence_stage": 1}):
        sc = doc.get("scores") or {}
        stage = ((doc.get("answers") or {}).get("sequence_stage") or {}).get("choice")
        slot_sc[(str(doc.get("tradingDate")), str(doc.get("slotTime")))] = {
            "temperature": float(sc["temperature"]) if isinstance(sc.get("temperature"), (int, float)) else None,
            "crowding": float(sc["crowding"]) if isinstance(sc.get("crowding"), (int, float)) else None,
            "stage": stage if isinstance(stage, str) else None,
        }
    day_sc: dict[str, dict] = {}
    for doc in db["hotlist_jev_sentiment_v2"].find({"kind": "eod", "status": "ok"}, {"tradingDate": 1, "scores": 1}):
        sc = doc.get("scores") or {}
        day_sc[str(doc.get("tradingDate"))] = {
            "day_temperature": float(sc["day_temperature"]) if isinstance(sc.get("day_temperature"), (int, float)) else None,
            "day_crowding": float(sc["day_crowding"]) if isinstance(sc.get("day_crowding"), (int, float)) else None,
        }

    tc = json.loads(TEMP_CROWDING.read_text(encoding="utf-8"))["frameSeparation"]
    dc = json.loads(DAY_CAL.read_text(encoding="utf-8"))["axes"]
    thresholds = {
        "slot_temperature": tuple(tc["slot_temperature"]["thresholds"][k] for k in ("p25", "p50", "p75")),
        "slot_crowding": tuple(tc["slot_crowding"]["thresholds"][k] for k in ("p25", "p50", "p75")),
        "day_temperature": tuple(dc["day_temperature"]["frozenQuartiles"][k] for k in ("p25", "p50", "p75")),
        "day_crowding": tuple(dc["day_crowding"]["frozenQuartiles"][k] for k in ("p25", "p50", "p75")),
    }

    frames = load_frames(FRAMES)
    frames.sort(key=lambda f: (str(f.get("tradingDate")), str(f.get("slotTime"))))
    snap2key = {str(f.get("snapshotId")): (str(f.get("tradingDate")), str(f.get("slotTime"))) for f in frames}
    day_frames: dict[str, list[dict]] = {}
    for f in frames:
        day_frames.setdefault(str(f.get("tradingDate")), []).append(f)
    dates = sorted(day_frames)
    prev_day = {dates[i]: dates[i - 1] for i in range(1, len(dates))}

    def predictors(d: str, slot: str) -> dict:
        ss = slot_sc.get((d, slot)) or {}
        ds = day_sc.get(prev_day.get(d) or "") or {}
        return {"slot_temperature": ss.get("temperature"), "slot_crowding": ss.get("crowding"),
                "stage": ss.get("stage"),
                "day_temperature": ds.get("day_temperature"), "day_crowding": ds.get("day_crowding")}

    # ---------- 第一层：交易层 54 笔逐带 ----------
    trades = json.loads(BASELINE_TRADES.read_text(encoding="utf-8"))["roundTripTrades"]
    trows = []
    for t in trades:
        key = snap2key.get(str(t.get("entrySnapshotId")))
        if not key:
            continue
        row = {"date": key[0], "month": key[0][:7], "net": float(t.get("netReturn") or 0.0)}
        row.update(predictors(key[0], key[1]))
        for var in thresholds:
            row[var + "_band"] = band_of(row.get(var), thresholds[var])
        trows.append(row)

    layer1: dict = {}
    toxic_bands: list[tuple[str, str]] = []
    for var in list(thresholds) + ["stage"]:
        key = var + "_band" if var != "stage" else "stage"
        bands: dict[str, dict] = {}
        for b in ("Q1", "Q2", "Q3", "Q4", None) if var != "stage" else \
                 ("start", "ferment", "climax", "ice", "retreat", None):
            items = [r["net"] for r in trows if r.get(key) == b]
            st = group_stats(items)
            st["h1_0406_sum"] = round(sum(r["net"] for r in trows if r.get(key) == b and half(r["date"]) == "H1_0406"), 4) if items else None
            st["h2_0709_sum"] = round(sum(r["net"] for r in trows if r.get(key) == b and half(r["date"]) == "H2_0709"), 4) if items else None
            bands[str(b)] = st
            if b is not None and st.get("n", 0) >= Q1_TOXIC_N and st.get("mean", 0) <= Q1_TOXIC_MEAN:
                toxic_bands.append((var, str(b)))
        layer1[var] = {"thresholds": list(thresholds[var]) if var in thresholds else None, "bands": bands}

    # ---------- 第二层：帧级佐证（毒带 + 参照带 slotTemp≤Q1） ----------
    refs = toxic_bands + [("slot_temperature", "Q1")]
    seen: set[tuple[str, str]] = set()
    frame_rows = []
    for d in dates:
        fs = day_frames[d]
        prices = [frame_prices(f) for f in fs]
        for i, f in enumerate(fs):
            row = {"date": d, "month": d[:7], "slot": str(f.get("slotTime"))}
            h1 = pool_ret(prices[i - 1], prices[i]) if i >= 1 else None
            fw = None
            if i < len(fs) - 1:
                rets = [pool_ret(prices[i], prices[j]) for j in range(i + 1, len(fs))]
                rets = [r for r in rets if r is not None]
                fw = min(rets) if rets else None
            row["h1"], row["fwdWorst"] = h1, fw
            row.update(predictors(d, row["slot"]))
            for var in thresholds:
                row[var + "_band"] = band_of(row.get(var), thresholds[var])
            if row["h1"] is not None or row["fwdWorst"] is not None:
                frame_rows.append(row)

    layer2: dict = {}
    for var, b in refs:
        if (var, b) in seen:
            continue
        seen.add((var, b))
        key = var + "_band" if var != "stage" else "stage"
        out: dict = {}
        for ro in ("h1", "fwdWorst"):
            inside = [r[ro] for r in frame_rows if r.get(key) == b and isinstance(r.get(ro), (int, float))]
            outside = [r[ro] for r in frame_rows if r.get(key) != b and isinstance(r.get(ro), (int, float))]
            s = sep(inside, outside)
            pm = {}
            for m in sorted({r["month"] for r in frame_rows}):
                ins = [r[ro] for r in frame_rows if r["month"] == m and r.get(key) == b and isinstance(r.get(ro), (int, float))]
                outs = [r[ro] for r in frame_rows if r["month"] == m and r.get(key) != b and isinstance(r.get(ro), (int, float))]
                pm[m] = sep(ins, outs)
            halves = {}
            for h in ("H1_0406", "H2_0709"):
                ins = [r[ro] for r in frame_rows if half(r["date"]) == h and r.get(key) == b and isinstance(r.get(ro), (int, float))]
                outs = [r[ro] for r in frame_rows if half(r["date"]) == h and r.get(key) != b and isinstance(r.get(ro), (int, float))]
                halves[h] = sep(ins, outs)
            out[ro] = {"full": s, "perMonth": pm, "halves": halves}
        layer2[f"{var}:{b}"] = out

    report = {
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "purpose": "jev 量身弱势带扫描（协议预登记：冻结四分位切带，两层裁决，全带全报）",
                 "protocol": {"toxicCriterion": f"trade n>={Q1_TOXIC_N} and mean<={Q1_TOXIC_MEAN}",
                              "layer2Scope": "第一层毒带 + 参照带 slot_temperature:Q1（jev_band_v1）"},
                 "tradesJoined": len(trows), "framesJoined": len(frame_rows),
                 "honesty": "54 笔切带多重比较风险高；候选需帧级佐证+走廊样本外；in-sample 不翻默认"},
        "thresholds": {k: list(v) for k, v in thresholds.items()},
        "layer1_trade": layer1,
        "toxicBands": [f"{v}:{b}" for v, b in toxic_bands],
        "layer2_frame": layer2,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"trades": len(trows), "frames": len(frame_rows), "toxicBands": report["toxicBands"],
                      "layer1": {v: layer1[v]["bands"] for v in layer1}}, ensure_ascii=False, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
