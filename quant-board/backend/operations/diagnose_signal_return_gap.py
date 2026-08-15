"""阶段 5：信号→收益映射缺口诊断（只读，不写库）。

从真实 MongoDB 加载 half_hour 历史快照 → RankTrendPythonEngine.replay →
诊断四类"信号→收益映射缺口"：
1. horizon_price_return_stats：S/A 档触发后 1/3/8 帧价格收益分布 vs 同分位桶未入场样本
   （回答"S/A 档有 excess 为什么交易不赚钱"——收益本身回落 = 入场时机问题，
   收益为正但交易为负 = 退出机制吞利润）；
2. sa_bucket_distribution：S/A 档触发时当前排名分位桶分布（验证"追强集中高分位、均值回归"）；
3. sa_vs_amain_overlap：S/A 档信号 ∩ A_MAIN 入场集合的 Jaccard 重叠（信号→交易损耗环节）；
4. assess_gap：缺口归属判定（entry / exit / none / unknown），结合默认配置 TradeSimulator
   的 roundTripTrades 净收益分布对照。

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_signal_return_gap
      [--dataset dragonboard_live] [--start 2026-04-15] [--end 2026-08-14]
      [--horizon 1 3 8] [--out data/reports/signal-to-return-gap.json]

fail-visible：诊断只读、不阻断、不写库；样本不足/缺维时如实输出 None/unknown/skipped* 计数，
不使用 0 伪装缺失，不静默吞掉任何可计算的统计。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.signal_return_gap import (
    assess_gap,
    horizon_price_return_stats,
    sa_bucket_distribution,
    sa_vs_amain_overlap,
    signal_entry_tier,
)
from backend.core.backtest.execution import TradeSimulator
from backend.core.settings import get_settings
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

DEFAULT_HORIZONS = (1, 3, 8)
ENTRY_TIERS = ("S", "A")


def _load_frames(dataset_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    settings = get_settings()
    print(
        f"[gap] mongodb backend={settings.storage_backend} db={settings.mongodb_database} "
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


def _sa_trade_net_returns(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
) -> tuple[list[float], dict[str, Any]]:
    """用默认交易配置跑一次 TradeSimulator，取 S/A 档信号入场的 roundTripTrades 净收益分布。

    返回 (net_returns, simulation_summary)；S/A 档识别按 entry 信号（entrySignalSnapshotId+code）
    反查 synergy tier，只统计 S/A 档入场的交易（与 horizon 收益口径同源）。
    """
    simulator = TradeSimulator()
    simulation = simulator.run(frames, signals, {})
    trades = simulation.get("roundTripTrades") or []
    signal_by_key = {
        f"{signal.get('snapshotId')}:{signal.get('code')}": signal for signal in signals
    }
    sa_net_returns: list[float] = []
    sa_trade_count = 0
    for trade in trades:
        key = f"{trade.get('entrySignalSnapshotId') or trade.get('entrySnapshotId')}:{trade.get('code')}"
        entry_signal = signal_by_key.get(key)
        if entry_signal is None or signal_entry_tier(entry_signal) not in ENTRY_TIERS:
            continue
        sa_trade_count += 1
        net_return = trade.get("netReturn")
        if net_return is None:
            continue
        sa_net_returns.append(float(net_return))
    summary = {
        "totalRoundTrips": len(trades),
        "saEntryTrades": sa_trade_count,
        "withNetReturn": len(sa_net_returns),
        "simulation": {
            "winRate": simulation.get("winRate"),
            "tradeCount": simulation.get("tradeCount"),
            "totalReturn": simulation.get("totalReturn"),
            "maxDrawdown": simulation.get("maxDrawdown"),
            "profitFactor": simulation.get("profitFactor"),
        },
    }
    return sa_net_returns, summary


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _win_rate(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(1 for value in values if value > 0) / len(values), 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段 5：信号→收益映射缺口诊断（只读）")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--horizon", type=int, nargs="+", default=list(DEFAULT_HORIZONS))
    parser.add_argument("--out", default="data/reports/signal-to-return-gap.json")
    args = parser.parse_args()

    frames = _load_frames(args.dataset, args.start, args.end)
    if not frames:
        print("[gap] no frames loaded — aborting (all sources empty)", file=sys.stderr)
        return 1
    print(f"[gap] loaded {len(frames)} frames", file=sys.stderr)

    signals = _run_replay(frames)
    if not signals:
        print("[gap] replay produced no signals — aborting", file=sys.stderr)
        return 1
    print(f"[gap] replay produced {len(signals)} signals", file=sys.stderr)

    sa_net_returns, simulation_summary = _sa_trade_net_returns(signals, frames)
    print(f"[gap] S/A 档入场交易 {simulation_summary['saEntryTrades']} 笔", file=sys.stderr)

    result: dict[str, Any] = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "window": {"dataset": args.dataset, "start": args.start, "end": args.end},
        "frameCount": len(frames),
        "signalCount": len(signals),
        "entryTiers": list(ENTRY_TIERS),
        "saBucketDistribution": sa_bucket_distribution(signals, frames),
        "saVsAmainOverlap": sa_vs_amain_overlap(signals),
        "tradeSimulation": simulation_summary,
        "horizons": {},
        "gapVerdict": {},
    }
    trade_median = _median(sa_net_returns)
    trade_win = _win_rate(sa_net_returns)
    for horizon in args.horizon:
        stats = horizon_price_return_stats(signals, frames, horizon=horizon, entry_tiers=ENTRY_TIERS)
        result["horizons"][str(horizon)] = stats
        entry = stats["entry"]
        gap = assess_gap(
            entry_median=entry.get("median"),
            entry_win_rate=entry.get("winRate"),
            trade_median=trade_median,
            trade_win_rate=trade_win,
        )
        result["gapVerdict"][str(horizon)] = gap
        print(
            f"--- horizon={horizon} ---\n"
            f"  entry: count={entry.get('count')} mean={entry.get('mean')} median={entry.get('median')} "
            f"winRate={entry.get('winRate')} lossRate={entry.get('lossRate')}\n"
            f"  control: count={stats['control'].get('count')} mean={stats['control'].get('mean')} "
            f"winRate={stats['control'].get('winRate')}\n"
            f"  skipped: frameBoundary={stats['skippedFrameBoundary']} missingRow={stats['skippedMissingRow']} "
            f"missingPrice={stats['skippedMissingPrice']}\n"
            f"  gap: {gap.get('location')} — {gap.get('reason')}",
            file=sys.stderr,
        )
    print(
        f"  trade: S/A 档入场 {len(sa_net_returns)} 笔净收益 median={trade_median} winRate={trade_win}",
        file=sys.stderr,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[gap] report written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
