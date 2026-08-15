"""阶段 6 立项量化：退出结构对 S/A 档入场 winRate×pf 的影响（只读研究，不写库）。

背景（阶段 5 结论）：S/A 档信号在 8 帧 horizon 有正方向信息（winRate 0.5272 vs 交易 0.3711），
但默认交易配置（minHoldingBars=0）在收益兑现前打断持仓 → 缺口在退出机制。

本研究用真实 MongoDB half_hour 快照跑同一批信号的多组退出结构：
  - baseline：默认配置（minHoldingBars=0，等价现状）
  - min8：minHoldingBars=8（强制持有至少 8 帧后再允许退出）
  - min8_wide_stop：minHoldingBars=8 + stopLoss=-0.12（防强制持有期内的"硬扛"放大亏损）
对比 S/A 档入场的 winRate / profitFactor / winRate×pf / median 净收益，
量化"延长持有"是否改善第 4 节验收组合线（winRate×pf >= 0.78 为目标，现状远低于此）。

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.research_exit_holding
      [--dataset dragonboard_live] [--start 2026-04-15] [--end 2026-08-14]
      [--out data/reports/exit-holding-research.json]

fail-visible：只读、不阻断；样本不足/缺字段时如实输出 None/skipped* 计数，
不使用 0 伪装缺失，不静默吞掉任何可计算的分组统计。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.signal_return_gap import signal_entry_tier
from backend.core.backtest.config import DEFAULT_TRADE_CONFIG
from backend.core.backtest.execution import TradeSimulator
from backend.core.settings import get_settings
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

ENTRY_TIERS = ("S", "A")


def _load_frames(dataset_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    settings = get_settings()
    print(
        f"[exit-holding] mongodb backend={settings.storage_backend} db={settings.mongodb_database} "
        f"dataset={dataset_id} window={start_date}~{end_date}",
        file=sys.stderr,
    )
    repo = MongoRepository(get_runtime_mongodb_database())
    frames = repo.load_frame_bundles(
        dataset_id,
        snapshot_type="half_hour",
        start_date=start_date,
        end_date=end_date,
        projection="ranktrend",
        fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )
    return frames


def _run_replay(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    engine = RankTrendPythonEngine(config=RankTrendConfig())
    return engine.replay(frames, window_size=50)


def _sa_stats(signals: list[dict[str, Any]], frames: list[dict[str, Any]], patch: dict[str, Any]) -> dict[str, Any]:
    """跑一组交易配置，只统计 S/A 档信号入场的 roundTripTrades（与阶段 5 同口径）。"""
    simulator = TradeSimulator()
    simulation = simulator.run(frames, signals, patch)
    trades = simulation.get("roundTripTrades") or []
    signal_by_key = {
        f"{signal.get('snapshotId')}:{signal.get('code')}": signal for signal in signals
    }
    sa_net: list[float] = []
    sa_trades: list[dict[str, Any]] = []
    for trade in trades:
        key = f"{trade.get('entrySignalSnapshotId') or trade.get('entrySnapshotId')}:{trade.get('code')}"
        entry_signal = signal_by_key.get(key)
        if entry_signal is None or signal_entry_tier(entry_signal) not in ENTRY_TIERS:
            continue
        net_return = trade.get("netReturn")
        if net_return is None:
            continue
        sa_net.append(float(net_return))
        sa_trades.append(trade)
    count = len(sa_net)
    wins = sum(1 for value in sa_net if value > 0)
    win_rate = wins / count if count else None
    profits = sum(float(trade.get("profit") or 0) for trade in sa_trades if float(trade.get("profit") or 0) > 0)
    losses = sum(abs(float(trade.get("profit") or 0)) for trade in sa_trades if float(trade.get("profit") or 0) < 0)
    profit_factor = profits / losses if losses else None
    ordered = sorted(sa_net)
    mid = len(ordered) // 2
    median = ordered[mid] if count % 2 == 1 else ((ordered[mid - 1] + ordered[mid]) / 2 if count else None)
    total_returns = simulation.get("totalReturn")
    max_dd = simulation.get("maxDrawdown")
    return {
        "patch": {k: patch[k] for k in ("minHoldingBars", "stopLoss", "takeProfit", "maxHoldingBars") if k in patch},
        "saEntryTrades": count,
        "allTrades": len(trades),
        "winRate": round(win_rate, 4) if win_rate is not None else None,
        "profitFactor": round(profit_factor, 4) if profit_factor is not None else None,
        "winRateTimesProfitFactor": round(win_rate * profit_factor, 4) if win_rate is not None and profit_factor is not None else None,
        "medianNetReturn": round(median, 6) if median is not None else None,
        "totalReturn": total_returns,
        "maxDrawdown": max_dd,
        "exitReasons": _exit_reason_distribution(sa_trades),
    }


def _exit_reason_distribution(trades: list[dict[str, Any]]) -> dict[str, int]:
    by_reason: dict[str, int] = {}
    for trade in trades:
        reason = str(trade.get("reason") or "unknown")
        by_reason[reason] = by_reason.get(reason, 0) + 1
    return dict(sorted(by_reason.items(), key=lambda item: item[1], reverse=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段 6 立项量化：退出结构对 S/A 档入场 winRate×pf 的影响（只读）")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--out", default="data/reports/exit-holding-research.json")
    args = parser.parse_args()

    frames = _load_frames(args.dataset, args.start, args.end)
    if not frames:
        print("[exit-holding] no frames loaded — aborting (all sources empty)", file=sys.stderr)
        return 1
    print(f"[exit-holding] loaded {len(frames)} frames", file=sys.stderr)

    signals = _run_replay(frames)
    if not signals:
        print("[exit-holding] replay produced no signals — aborting", file=sys.stderr)
        return 1
    print(f"[exit-holding] replay produced {len(signals)} signals", file=sys.stderr)

    base = {**DEFAULT_TRADE_CONFIG}
    variants: dict[str, dict[str, Any]] = {
        "baseline": {**base, "minHoldingBars": 0},
        "min8": {**base, "minHoldingBars": 8},
        "min8_wide_stop": {**base, "minHoldingBars": 8, "stopLoss": -0.12},
    }
    result: dict[str, Any] = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "window": {"dataset": args.dataset, "start": args.start, "end": args.end},
        "frameCount": len(frames),
        "signalCount": len(signals),
        "entryTiers": list(ENTRY_TIERS),
        "variants": {},
        "comparison": {},
    }
    for name, patch in variants.items():
        stats = _sa_stats(signals, frames, patch)
        result["variants"][name] = stats
        print(
            f"[{name}] S/A 入场 {stats['saEntryTrades']} 笔 winRate={stats['winRate']} "
            f"pf={stats['profitFactor']} winRate×pf={stats['winRateTimesProfitFactor']} "
            f"median={stats['medianNetReturn']} totalReturn={stats['totalReturn']} maxDD={stats['maxDrawdown']}",
            file=sys.stderr,
        )
        print(f"  exitReasons: {stats['exitReasons']}", file=sys.stderr)

    # 对比：min8 / min8_wide_stop 相对 baseline 的 winRate×pf 差
    baseline = result["variants"]["baseline"]
    for name in ("min8", "min8_wide_stop"):
        variant = result["variants"][name]
        result["comparison"][name] = {
            "winRateDelta": round(variant["winRate"] - baseline["winRate"], 4)
            if variant["winRate"] is not None and baseline["winRate"] is not None else None,
            "profitFactorDelta": round(variant["profitFactor"] - baseline["profitFactor"], 4)
            if variant["profitFactor"] is not None and baseline["profitFactor"] is not None else None,
            "winRatePfDelta": round(variant["winRateTimesProfitFactor"] - baseline["winRateTimesProfitFactor"], 4)
            if variant["winRateTimesProfitFactor"] is not None and baseline["winRateTimesProfitFactor"] is not None else None,
            "medianNetReturnDelta": round(variant["medianNetReturn"] - baseline["medianNetReturn"], 6)
            if variant["medianNetReturn"] is not None and baseline["medianNetReturn"] is not None else None,
            "tradeCountDelta": variant["saEntryTrades"] - baseline["saEntryTrades"],
        }
        print(
            f"[{name} vs baseline] winRateΔ={result['comparison'][name]['winRateDelta']} "
            f"winRate×pfΔ={result['comparison'][name]['winRatePfDelta']} "
            f"medianΔ={result['comparison'][name]['medianNetReturnDelta']}",
            file=sys.stderr,
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[exit-holding] report written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
