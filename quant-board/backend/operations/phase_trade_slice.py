# -*- coding: utf-8 -*-
"""M1 最小实验：历史 roundTrip 交易按相位切片读数（设计 §5 M1 首步）。

样本口径（C2 裁定）：消费 summary.roundTripTrades（=tradeCount=54，与文档"54 笔"一致）；
summary.trades（65/61 行）含退出分片/强平记录，不消费。
双口径：① 入场日相位（daily 标签 join entryTradingDate；另出前日标签 dailyByPrevDay
严格 as-of 变体）② 入场时引擎 regime（trade.regime 现成字段）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def round_trips_of(summary: dict) -> list[dict]:
    """样本口径唯一入口：roundTripTrades 优先，无则回退 trades（并在读数中注明）。"""
    rt = summary.get("roundTripTrades")
    if isinstance(rt, list) and rt:
        return rt
    return summary.get("trades") or []


def wrxpf_of(trades: list[dict]) -> dict:
    """netReturn 缺失的条目不计入收益统计，missingNetReturn 显式计数（fail-visible）。"""
    rets: list[float] = []
    missing = 0
    for t in trades:
        nr = t.get("netReturn")
        if isinstance(nr, (int, float)):
            rets.append(float(nr))
        else:
            missing += 1
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r < 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    win_rate = len(wins) / len(rets) if rets else None
    pf = (gross_win / gross_loss) if gross_loss > 0 else (None if gross_win == 0 else float("inf"))
    return {
        "trades": len(rets),
        "missingNetReturn": missing,
        "winRate": round(win_rate, 4) if win_rate is not None else None,
        "profitFactor": round(pf, 4) if pf is not None and pf != float("inf") else None,
        "wrxpf": round(win_rate * pf, 4) if (win_rate is not None and pf is not None and pf != float("inf")) else None,
        "sumNetReturn": round(sum(rets), 4),
        "maxSingleLoss": round(min(rets), 4) if rets else None,
    }


def slice_trades(trades: list[dict], daily: dict[str, str] | None, phase_key: str) -> dict:
    """phase_key='phase'（用 daily 标签 join entryTradingDate）或 'regime'（trade 自带字段）。"""
    buckets: dict[str, list[dict]] = {}
    for t in trades:
        if phase_key == "phase":
            label = (daily or {}).get(str(t.get("entryTradingDate") or ""), "unknown")
        else:
            label = str(t.get("regime") or "unknown")
        buckets.setdefault(label, []).append(t)
    return {k: wrxpf_of(v) for k, v in sorted(buckets.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 交易层相位切片")
    parser.add_argument("--summary", default="data/reports/b-202610/t6-runs-formal/1-summary.json")
    parser.add_argument("--labels", default="data/reports/phase-monitor/phase-labels-v1.json")
    parser.add_argument("--out", default="data/reports/phase-monitor/phase-trade-slice-v1.json")
    args = parser.parse_args()

    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    trades = round_trips_of(summary)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    report: dict = {
        "tradeCount": len(trades),
        "sampleSource": "roundTripTrades" if summary.get("roundTripTrades") else "trades(fallback)",
        "byCandidate": {},
        "byCandidatePrevDay": {},
        "byRegime": slice_trades(trades, None, "regime"),
    }
    for key, cand in labels.get("candidates", {}).items():
        report["byCandidate"][key] = slice_trades(trades, cand.get("dailyByMajority"), "phase")
        report["byCandidatePrevDay"][key] = slice_trades(trades, cand.get("dailyByPrevDay"), "phase")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
