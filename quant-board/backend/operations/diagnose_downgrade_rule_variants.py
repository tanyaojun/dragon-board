# -*- coding: utf-8 -*-
"""SP2 清仓规则历史验证（用户 2026-10-01 裁决：极热→弱 减半 vs 清仓，数据说话选规则）。

反事实口径：gen7 基线 54 笔 roundTrip × 持仓期内「前日定相带下移」首次触发日，以该日
EOD 帧价（缺则当日最后有价帧）反事实卖出，对比三臂：
  baseline（不动=实际历史）/ HALVE（下移一档减半）/ CLEAR（下移即清仓）
成本模型与引擎一致：per-share r(P) = (P×(1-fee-stamp) − entry×(1+fee)) / (entry×(1+fee))；
滑点已内嵌于成交价的近似未单独建模（诚实边界，见产物 meta）。
只读（Mongo + 本地 gz）；产物 data/reports/phase-monitor/downgrade-rule-variants.json。

用法：./.venv/Scripts/python.exe -m backend.operations.diagnose_downgrade_rule_variants
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
OUT = Path("data/reports/phase-monitor/downgrade-rule-variants.json")

BANDS = [("冷10-40", 40.0), ("弱势40-60", 60.0), ("强60-80", 80.0), ("极热≥80", 999.0)]
RANK = {name: i for i, (name, _) in enumerate(BANDS)}


def band_of(score: float) -> str:
    for name, upper in BANDS:
        if score < upper:
            return name
    return BANDS[-1][0]


def r_of(price: float, entry: float, fee: float, stamp: float) -> float:
    """每股净收益率（引擎口径：买入费入成本，卖出费+印花税扣 proceeds）。"""
    basis = entry * (1 + fee)
    return (price * (1 - fee - stamp) - basis) / basis


def stream_frames_prices(path: Path, needed: dict[str, set[str]]) -> dict[tuple[str, str], float]:
    """流式扫描顶层 JSON 数组，只保留 needed 日期×代码 的当日最后有价。"""
    dec = json.JSONDecoder()
    out: dict[tuple[str, str], float] = {}
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
        codes = needed.get(d)
        if not codes:
            continue
        for row in frame.get("stocks") or []:
            code = str(row.get("code") or "")
            if code not in codes:
                continue
            price = row.get("lastPrice") or row.get("price") or row.get("close") or row.get("closePrice")
            try:
                p = float(price)
            except (TypeError, ValueError):
                continue
            if p > 0:
                key = (d, code)
                # 同日多帧取「最后出现的有价」（frames 按时间序，EOD 在后）
                cur = out.get(key)
                if cur is None or p != cur:
                    out[key] = p
        # 保留同日更早帧会被后来帧覆盖：lastPrice 语义即当日最新
    return out


def main() -> int:
    fee = float(DEFAULT_TRADE_CONFIG["feeRate"])
    stamp = float(DEFAULT_TRADE_CONFIG["stampTaxRate"])
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    trades = summary.get("roundTripTrades") or []
    eod = load_eod_scores("2026-09-30")
    dates = sorted(d for d, s in eod.items() if isinstance(s, (int, float)))
    prev_score = {dates[i]: eod[dates[i - 1]] for i in range(1, len(dates))}

    # ① 逐笔找首次带下移（前日定相 as-of；缺分日不回跳，与 SP1 _phase_context 严格前日一致）
    rows: list[dict] = []
    for t in trades:
        ed = str(t.get("entryTradingDate") or "")
        xd = str(t.get("exitTradingDate") or "")
        pe = prev_score.get(ed)
        if not isinstance(pe, (int, float)):
            rows.append({"code": t.get("code"), "entryTradingDate": ed, "skipped": "entry_prev_missing"})
            continue
        entry_band = band_of(float(pe))
        entry_rank = RANK[entry_band]
        hit = None
        for d in dates:
            if d <= ed or d > xd:
                continue
            b = band_of(float(prev_score[d]))
            if RANK[b] < entry_rank:
                hit = (d, b)
                break
        rows.append({
            "code": t.get("code"), "name": t.get("name"), "entryTradingDate": ed, "exitTradingDate": xd,
            "entryBand": entry_band, "downgradeTo": hit[1] if hit else None, "downgradeDate": hit[0] if hit else None,
            "netReturn": t.get("netReturn"), "entryPrice": t.get("entryPrice"), "exitPrice": t.get("exitPrice"),
        })

    # ② 需要反事实价格的 (date, code) 集 = 全部带下移笔（含 →冷，对照完整性）
    needed: dict[str, set[str]] = {}
    for r in rows:
        if r.get("downgradeDate"):
            needed.setdefault(r["downgradeDate"], set()).add(str(r["code"]))
    prices = stream_frames_prices(FRAMES, needed) if needed else {}

    # ③ 三臂反事实：baseline=实际；HALVE=减半@触发价；CLEAR=清仓@触发价
    for r in rows:
        if not r.get("downgradeDate"):
            continue
        p = prices.get((r["downgradeDate"], str(r["code"])))
        r["transitionPrice"] = p
        if p is None:
            r["variantNote"] = "transition_price_missing"
            continue
        entry = float(r["entryPrice"])
        r_act = float(r["netReturn"])
        r_trig = r_of(p, entry, fee, stamp)
        r["rAtTransition"] = round(r_trig, 4)
        r["rHalve"] = round(0.5 * r_trig + 0.5 * r_act, 4)
        r["rClear"] = round(r_trig, 4)

    def agg(pairs: list[dict], key: str) -> dict:
        vals = [float(x[key]) for x in pairs if isinstance(x.get(key), (int, float))]
        return {"trades": len(pairs), "pricedTrades": len(vals), "priceMissing": len(pairs) - len(vals),
                "sum": round(sum(vals), 4), "avg": round(sum(vals) / len(vals), 4) if vals else None,
                "winRate": round(sum(1 for v in vals if v > 0) / len(vals), 4) if vals else None}

    def group(pred) -> list[dict]:
        return [x for x in rows if x.get("downgradeDate") and pred(x)]

    groups = {
        "all": group(lambda x: True),
        "强60-80→弱势40-60": group(lambda x: x["entryBand"] == "强60-80" and x["downgradeTo"] == "弱势40-60"),
        "极热≥80→弱势40-60": group(lambda x: x["entryBand"] == "极热≥80" and x["downgradeTo"] == "弱势40-60"),
        "任意→冷10-40": group(lambda x: x["downgradeTo"] == "冷10-40"),
    }
    report = {
        "meta": {
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "purpose": "SP2 清仓规则历史验证：极热→弱 减半 vs 清仓（用户 2026-10-01 裁决：数据说话）",
            "costModel": {"feeRate": fee, "stampTaxRate": stamp, "slippageNote": "滑点内嵌于成交价近似，未单独建模",
                          "totalNote": "baseline 含无价笔，变体臂剔除 priceMissing（组内笔数可差 1-2，评审 P2-8）"},
            "tradesTotal": len(trades), "asOf": "前日定相严格前日键（SP1 口径）",
        },
        "groups": {
            g: {
                "baseline": agg(rs, "netReturn"),
                "halve": agg(rs, "rHalve"),
                "clear": agg(rs, "rClear"),
            }
            for g, rs in groups.items()
        },
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"affected={len(groups['all'])} pairs:", {g: len(rs) for g, rs in groups.items()})
    for g, a in report["groups"].items():
        print(f"\n[{g}]")
        for arm in ("baseline", "halve", "clear"):
            print(f"  {arm:9s} {a[arm]}")
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
