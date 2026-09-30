# -*- coding: utf-8 -*-
"""M3 盘面脉拍（phase pulse）：当月至今相位×交易快照，挂账即数据不靠记忆。

用法（quant-board 目录，独立进程，资源纪律=隔离 CLI）：
  ./.venv/Scripts/python.exe -m backend.operations.phase_pulse --month 2026-10

流程：warmup 前导帧 + 当月 frames → BacktestService.run_ranktrend（dryRun，默认栈
gate OFF 基线）→ 按当月 EOD 同日定相切片（与时间线口径一致）→ 北极星机械线 →
phase_monitor 集合 kind=pulse（前端"本月至今"卡数据源）+ 本地 JSON。
样本纪律：月内笔数少（尤其月初），读数仅方向参考，报告携带 sampleNote。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_northstar import equity_phase_slices, evaluate_northstar, worst_drawdown
from backend.operations.phase_trade_slice import round_trips_of, slice_trades

PULSE_THRESHOLD = 50.0  # 口径源=phase_label_run CANDIDATES sentiment_2b


def build_pulse_report(
    summary: dict,
    eod_scores: dict[str, float | None],
    month: str,
    *,
    full_window: dict | None = None,
) -> dict:
    """当月切片纯函数：roundTrip 交易 + equity 曲线按当月 EOD 同日定相切 northstar 读数。"""
    trades = [t for t in round_trips_of(summary)
              if str(t.get("entryTradingDate") or "").startswith(month)]
    equity = [pt for pt in (summary.get("equityCurve") or [])
              if str(pt.get("tradingDate") or "").startswith(month)]
    daily = {d: phase for d, s in eod_scores.items()
             if d.startswith(month)
             for phase in [_phase_of(s)]}
    by_phase = slice_trades(trades, daily, "phase")
    # 稳定键：空桶补零读数（前端月卡固定读 offense/defense 两键；evaluate 对空桶产 pass=False）
    for bucket in ("offense", "defense"):
        by_phase.setdefault(bucket, {
            "trades": 0, "missingNetReturn": 0, "winRate": None, "profitFactor": None,
            "wrxpf": None, "sumNetReturn": None, "maxSingleLoss": None,
        })
    slices = equity_phase_slices(equity, daily)
    full = full_window or {
        "maxDD": (lambda eq: round(worst_drawdown(eq), 4) if len(eq) >= 2 else None)(
            [float(pt.get("equity") or 0.0) for pt in equity]),
        "segReturn": (lambda eq: round(eq[-1] / eq[0] - 1, 4) if len(eq) >= 2 else None)(
            [float(pt.get("equity") or 0.0) for pt in equity]),
    }
    return {
        "month": month,
        "tradeCount": len(trades),
        "sampleNote": "月内笔数少，读数仅方向参考（M3 脉拍非验收）",
        "eodDays": sum(1 for d in eod_scores if d.startswith(month)),
        "byPhase": by_phase,
        "equitySlices": slices,
        "northstar": evaluate_northstar(by_phase, slices, full),
        "fullWindow": full,
    }


def _phase_of(score: float | None) -> str:
    if score is None:
        return "unknown"
    return "offense" if score >= PULSE_THRESHOLD else "defense"


# C6 分带（2026-10-01 用户定义：40-60 弱势区间；前一日 EOD as-of 口径）
PULSE_BANDS = [("冷10-40", 10.0, 40.0), ("弱势40-60", 40.0, 60.0), ("强60-80", 60.0, 80.0)]


def band_stats(trades: list[dict], eod_scores: dict[str, float | None], month: str) -> dict:
    """基线交易按前一日 EOD 分带（as-of 无前视）——C6 证据逐次脉拍累积。"""
    scored = sorted((d, s) for d, s in eod_scores.items() if isinstance(s, (int, float)))
    prev_score = {scored[i][0]: scored[i - 1][1] for i in range(1, len(scored))}
    out: dict = {}
    for tag, lo, hi in PULSE_BANDS:
        rets = [
            float(t["netReturn"])
            for t in trades
            if str(t.get("entryTradingDate") or "").startswith(month)
            and isinstance(t.get("netReturn"), (int, float))
            and isinstance(prev_score.get(str(t.get("entryTradingDate") or "")), (int, float))
            and lo <= prev_score[str(t.get("entryTradingDate") or "")] < hi
        ]
        out[tag] = {
            "trades": len(rets),
            "sumNetReturn": round(sum(rets), 4),
            "avgPerTrade": round(sum(rets) / len(rets), 4) if rets else None,
        }
    return out


def ab_compare(baseline: dict, controlled: dict, month: str) -> dict:
    """A/B 装配：基线 vs 弱势带回避臂（reduce_band factor=0），月内口径。"""

    def stats(summary: dict) -> dict:
        rets = [
            float(t["netReturn"])
            for t in round_trips_of(summary)
            if str(t.get("entryTradingDate") or "").startswith(month)
            and isinstance(t.get("netReturn"), (int, float))
        ]
        return {"tradeCount": len(rets), "sumNetReturn": round(sum(rets), 4)}

    b, c = stats(baseline), stats(controlled)
    return {
        "baseline": b,
        "bandAvoided": c,
        "delta": {
            "tradesRemoved": b["tradeCount"] - c["tradeCount"],
            "netReturnSaved": round(c["sumNetReturn"] - b["sumNetReturn"], 4),
        },
        "arm": "ladder ③：10-40 满 / 40-60 零 / 60+ 三成（前日定相，C7 用户确认）",
    }


def load_eod_scores(end_date: str) -> dict[str, float | None]:
    from backend.data.repositories import repository_factory

    db = repository_factory.get_runtime_mongodb_database()
    out: dict[str, float | None] = {}
    for doc in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD",
         "tradingDate": {"$lte": end_date}},
        {"tradingDate": 1, "emotionScore.score": 1},
    ):
        es = doc.get("emotionScore")
        out[str(doc.get("tradingDate") or "")] = (
            float(es["score"]) if isinstance(es, dict) and isinstance(es.get("score"), (int, float)) else None
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="M3 盘面脉拍（当月至今相位快照，隔离进程）")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--end", default="", help="截止日 YYYY-MM-DD（默认今天）")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    end = args.end or datetime.now().strftime("%Y-%m-%d")

    from backend.cli import runtime_session
    from backend.services.backtest_service import BacktestService

    eod_scores = load_eod_scores(end)
    warmup_start = (datetime.strptime(f"{args.month}-01", "%Y-%m-%d")).replace(day=1)
    warmup_start = warmup_start.fromordinal(warmup_start.toordinal() - 10)
    payload = {
        "dataset_id": "dragonboard_live",
        "snapshot_type": "half_hour",
        "start_date": warmup_start.strftime("%Y-%m-%d"),
        "end_date": end,
        "strategy_name": "ranktrend_early_big_move_v3_lifecycle_fusion",
        "random_seed": 20260430,
        "trade_config": {},
        "dryRun": True,
    }
    summary = BacktestService(runtime_session()).run_ranktrend(payload)

    report = build_pulse_report(summary, eod_scores, args.month)
    report["meta"] = {
        "month": args.month, "end": end,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "gate": "off（基线读数；A/B 对照用 trade_config.phaseExposureControl）",
    }
    # C6 证据：基线交易按前日分带累积
    report["bands"] = band_stats(round_trips_of(summary), eod_scores, args.month)
    # A/B 臂：阶梯仓位（C7 用户确认③：10-40 满/40-60 零/60+ 三成；仅 trade_config 不同 → 信号缓存复用）
    try:
        ladder_cfg = {
            "phaseExposureControl": {
                "mode": "ladder", "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]],
                "eodScores": {d: s for d, s in eod_scores.items() if s is not None},
            }
        }
        controlled = BacktestService(runtime_session()).run_ranktrend({**payload, "trade_config": ladder_cfg})
        report["ab"] = ab_compare(summary, controlled, args.month)
    except Exception as exc:  # noqa: BLE001 — 基线脉拍不因 A/B 臂失败而失效
        report["ab"] = {"degraded": True, "reason": str(exc)}
        print(f"[phase-pulse] A/B 臂失败（基线照常）: {exc}", file=sys.stderr)
    out = Path(args.out) if args.out else Path(f"data/reports/phase-monitor/pulse-{args.month}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    from backend.operations.phase_monitor_persistence import persist_pulse

    persist_pulse(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
