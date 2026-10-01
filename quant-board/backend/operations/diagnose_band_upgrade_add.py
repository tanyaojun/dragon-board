# -*- coding: utf-8 -*-
"""SP3-T0 上移加仓观察臂（SP2-REBAL-ADD-OBS；方案 α 裁决：证据先行不接引擎）。

问题：冷带入场的持仓，当市场带升入 强60-80/极热≥80 时追加仓位是否划算？
口径：
  帧级（主）：冷带入场的 54 笔持仓帧集合，按当前带分 升级态(强/极热) vs 未升级态(冷/弱)，
    各自的池等权 forward return（H1=下一帧、H8），MW + 均值差；
  交易层（辅）：升级笔从升级日价格到实际退出的段收益（引擎成本模型）。
判据（预登记）：升级态 forward 期望显著为正 且 ≥ 未升级态 → 才允许 SP4 提出上移加仓提案。
只读；产物 data/reports/phase-monitor/band-upgrade-add.json。
"""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest.config import DEFAULT_TRADE_CONFIG
from backend.operations.phase_pulse import load_eod_scores

SUMMARY = Path("data/reports/b-202610/t6-runs-formal/1-summary.json")
FRAMES = Path("data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
OUT = Path("data/reports/phase-monitor/band-upgrade-add.json")

COLD = "冷10-40"
UPGRADED_TO = ("强60-80", "极热≥80")


def band_of(score: float) -> str:
    if score < 40.0:
        return COLD
    if score < 60.0:
        return "弱势40-60"
    if score < 80.0:
        return "强60-80"
    return "极热≥80"


def stream_day_close(path: Path) -> dict[str, dict[str, float]]:
    """流式扫描 frames，产出 {date: {code: 当日最后有价}}（日频，供 H1/H8 与段收益）。"""
    dec = json.JSONDecoder()
    out: dict[str, dict[str, float]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as f:
        text = f.read()
    idx = 0
    n = len(text)
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
        d = str(frame.get("tradingDate") or "")
        day = out.setdefault(d, {})
        for row in frame.get("stocks") or []:
            code = str(row.get("code") or "")
            price = row.get("lastPrice") or row.get("price") or row.get("close") or row.get("closePrice")
            try:
                p = float(price)
            except (TypeError, ValueError):
                continue
            if p > 0:
                day[code] = p  # frames 按时间序，后写覆盖=当日收盘口径
    return out


def mannwhitney_u(a: list[float], b: list[float]) -> float | None:
    """双侧 MW p 值（正态近似，n 足够时；样本不足返回 None）。"""
    import math

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
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return round(p, 5)


def main() -> int:
    fee = float(DEFAULT_TRADE_CONFIG["feeRate"])
    stamp = float(DEFAULT_TRADE_CONFIG["stampTaxRate"])
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    trades = summary.get("roundTripTrades") or []
    eod = load_eod_scores("2026-09-30")
    dates = sorted(d for d, s in eod.items() if isinstance(s, (int, float)))
    prev_score = {dates[i]: eod[dates[i - 1]] for i in range(1, len(dates))}

    # ① 冷带入场笔分类：升级（首次升入 强/极热）vs 未升级
    cold_trades: list[dict] = []
    for t in trades:
        ed = str(t.get("entryTradingDate") or "")
        xd = str(t.get("exitTradingDate") or "")
        pe = prev_score.get(ed)
        if not isinstance(pe, (int, float)) or band_of(float(pe)) != COLD:
            continue
        upgrade_date = None
        for d in dates:
            if d <= ed or d > xd:
                continue
            b = band_of(float(prev_score[d]))
            if b in UPGRADED_TO:
                upgrade_date = d
                break
        cold_trades.append({
            "code": t.get("code"), "name": t.get("name"), "entryTradingDate": ed,
            "exitTradingDate": xd, "entryPrice": t.get("entryPrice"), "exitPrice": t.get("exitPrice"),
            "netReturn": t.get("netReturn"), "upgradeDate": upgrade_date,
        })
    upgraded = [t for t in cold_trades if t["upgradeDate"]]
    stayed = [t for t in cold_trades if not t["upgradeDate"]]

    day_close = stream_day_close(FRAMES)

    # ② 交易层：升级段收益（升级日收盘 → 实际退出价，引擎成本模型）
    seg_rows = []
    for t in upgraded:
        p_up = day_close.get(t["upgradeDate"], {}).get(str(t["code"]))
        if p_up is None:
            seg_rows.append({"code": t["code"], "upgradeDate": t["upgradeDate"], "segmentReturn": None})
            continue
        basis = float(t["entryPrice"]) * (1 + fee)
        r_up = (p_up * (1 - fee - stamp) - basis) / basis
        r_exit = float(t["netReturn"])
        seg = round(0.5 * r_up + 0.5 * r_exit, 4)  # 升级日加半仓的组合段收益（对齐不加仓对照=0.5*r_exit+0.5*r_exit）
        no_add = round(r_exit, 4)
        seg_rows.append({"code": t["code"], "upgradeDate": t["upgradeDate"],
                         "segmentReturn": seg, "noAddReturn": no_add,
                         "rAtUpgrade": round(r_up, 4)})

    # ③ 帧级：冷带持仓帧 按 当前带 分 升级态/未升级态，池等权 H1/H8
    held_by_date: dict[str, set[str]] = {}
    for t in cold_trades:
        for d in dates:
            if str(t["entryTradingDate"]) < d <= str(t["exitTradingDate"]):
                held_by_date.setdefault(d, set()).add(str(t["code"]))
    frame_states: dict[str, list[dict]] = {"upgraded": [], "stayed": []}
    date_index = {d: i for i, d in enumerate(dates)}
    for d, codes in held_by_date.items():
        ps = prev_score.get(d)
        if not isinstance(ps, (int, float)):
            continue
        b = band_of(float(ps))
        state = "upgraded" if b in UPGRADED_TO else "stayed"
        i = date_index[d]
        for h, label in ((1, "H1"), (8, "H8")):
            j = i + h
            if j >= len(dates):
                continue
            nxt, cur = day_close.get(dates[j], {}), day_close.get(d, {})
            rets = [(nxt[c] / cur[c] - 1) for c in codes if c in nxt and c in cur]
            if rets:
                frame_states[state].append({"h": label, "mean": sum(rets) / len(rets), "n": len(rets), "month": d[:7]})

    def agg_state(state: str, h: str) -> dict:
        vals = [f["mean"] for f in frame_states[state] if f["h"] == h]
        if not vals:
            return {"frames": 0}
        other = [f["mean"] for f in frame_states["stayed" if state == "upgraded" else "upgraded"] if f["h"] == h]
        return {"frames": len(vals), "mean": round(sum(vals) / len(vals), 5),
                "winRate": round(sum(1 for v in vals if v > 0) / len(vals), 4),
                "mwVsOther": mannwhitney_u(vals, other)}

    report = {
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"),
                 "purpose": "SP2-REBAL-ADD-OBS：上移加仓观察臂（方案 α；判据=升级态 forward 期望显著为正且 ≥ 未升级态）",
                 "coldTrades": len(cold_trades), "upgradedTrades": len(upgraded), "stayedTrades": len(stayed)},
        "frameLevel": {f"{s}_{h}": agg_state(s, h) for s in ("upgraded", "stayed") for h in ("H1", "H8")},
        "tradeLevelSegments": seg_rows,
        "verdict": None,
    }
    up1 = report["frameLevel"]["upgraded_H1"]
    st1 = report["frameLevel"]["stayed_H1"]
    if up1.get("frames", 0) >= 3:
        positive = up1["mean"] > 0
        sig = (up1.get("mwVsOther") is not None and up1["mwVsOther"] < 0.05) or (
            st1.get("mean") is not None and up1["mean"] - st1["mean"] >= 0.02)
        better = st1.get("mean") is not None and up1["mean"] >= st1["mean"]
        report["verdict"] = ("达标：升级态显著为正且 ≥ 未升级态" if (positive and better and sig)
                             else "不达标：升级态优势不足（方向或显著性缺失）")
    else:
        report["verdict"] = "样本不足"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"coldTrades": len(cold_trades), "upgraded": len(upgraded),
                      "frameLevel": report["frameLevel"], "verdict": report["verdict"]},
                     ensure_ascii=False, indent=1))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
