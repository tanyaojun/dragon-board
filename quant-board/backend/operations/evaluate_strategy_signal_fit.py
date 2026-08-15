"""阶段 6 综合评估：生命周期分层策略 vs RankTrend 分析方法匹配度（只读研究）。

回答用户问题"策略到底匹不匹配 RankTrend 分析方法"——A_MAIN 入场只是其中一环，
需要逐环节评估信号（synergy S/A 档）到实际入场的损耗分布：

漏斗拆解（strategy_signal_fit.py 纯函数 + 本脚本组装）：
1. tier_distribution_by_candidate：synergy S/A 档按 candidateTier 分层 h8 收益 + delta
   → 生命周期分层是否把正期望信号归入 A_MAIN/B_IGNITION（入场档）还是错误归入 D_EXIT_RISK/N_NEUTRAL；
2. amain_funnel_by_regime：A_MAIN 候选按 regime 分层 h8 收益
   → regime 过滤（weak/retreat 不入场）是否排除掉正期望；
3. entered_vs_unentered：A_MAIN 内实际入场 vs 未入场 h8 收益
   → 执行/资金/持仓数损耗是否吃掉信号优势；
4. 叠加 synergy 档位（S vs A）视角：A_MAIN 内 S 档与 A 档的 h8 差异
   → 分层是否尊重档位强度。

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.evaluate_strategy_signal_fit
      [--dataset dragonboard_live] [--start 2026-04-15] [--end 2026-08-14]
      [--out data/reports/strategy-signal-fit.json]

fail-visible：只读、不阻断；样本不足/缺维时如实输出 None/count=0，不使用 0 伪装缺失。
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
from backend.analysis.ranktrend.strategy_signal_fit import (
    amain_funnel_by_regime,
    entered_vs_unentered,
    tier_distribution_by_candidate,
)
from backend.core.backtest.execution import TradeSimulator
from backend.core.settings import get_settings
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

DEFAULT_HORIZON = 8


def _load_frames(dataset_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    settings = get_settings()
    print(
        f"[fit] mongodb backend={settings.storage_backend} db={settings.mongodb_database} "
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


def _entered_keys(signals: list[dict[str, Any]], frames: list[dict[str, Any]]) -> set[str]:
    """TradeSimulator 默认配置 roundTripTrades 反查实际入场信号 key（entrySignalSnapshotId:code）。"""
    simulator = TradeSimulator()
    simulation = simulator.run(frames, signals, {})
    keys: set[str] = set()
    for trade in simulation.get("roundTripTrades") or []:
        keys.add(
            f"{trade.get('entrySignalSnapshotId') or trade.get('entrySnapshotId')}:{trade.get('code')}"
        )
    return keys


def _sa_tier_breakdown(signals: list[dict[str, Any]], frames: list[dict[str, Any]]) -> dict[str, Any]:
    """A_MAIN 候选内 S 档 vs A 档的 h8 收益差异（分层是否尊重档位强度）。"""
    amain = [
        signal for signal in signals
        if signal_entry_tier(signal) in ("S", "A") and str(signal.get("candidateTier") or "") == "A_MAIN"
    ]
    by_tier: dict[str, list[float]] = {"S": [], "A": []}
    for signal in amain:
        by_tier.setdefault(signal_entry_tier(signal), []).append(signal)
    from backend.analysis.ranktrend.strategy_signal_fit import _h8_samples

    result: dict[str, Any] = {}
    for tier, tier_signals in by_tier.items():
        samples = _h8_samples(tier_signals, frames, DEFAULT_HORIZON)
        values = [sample[0] for sample in samples]
        from backend.analysis.ranktrend.signal_return_gap import _summarize

        result[tier] = {
            "signalCount": len(tier_signals),
            **_summarize(values),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段 6 综合评估：生命周期分层策略 vs RankTrend 匹配度（只读）")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--out", default="data/reports/strategy-signal-fit.json")
    args = parser.parse_args()

    frames = _load_frames(args.dataset, args.start, args.end)
    if not frames:
        print("[fit] no frames loaded — aborting (all sources empty)", file=sys.stderr)
        return 1
    print(f"[fit] loaded {len(frames)} frames", file=sys.stderr)

    signals = _run_replay(frames)
    if not signals:
        print("[fit] replay produced no signals — aborting", file=sys.stderr)
        return 1
    print(f"[fit] replay produced {len(signals)} signals", file=sys.stderr)

    horizon = DEFAULT_HORIZON
    by_candidate = tier_distribution_by_candidate(signals, frames, horizon=horizon)
    by_regime = amain_funnel_by_regime(signals, frames, horizon=horizon)
    entered_keys = _entered_keys(signals, frames)
    entered = entered_vs_unentered(signals, frames, entered_keys=entered_keys, horizon=horizon)
    sa_breakdown = _sa_tier_breakdown(signals, frames)

    result: dict[str, Any] = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "window": {"dataset": args.dataset, "start": args.start, "end": args.end},
        "frameCount": len(frames),
        "signalCount": len(signals),
        "horizon": horizon,
        "byCandidateTier": by_candidate,
        "amainByRegime": by_regime,
        "amainEnteredVsUnentered": entered,
        "amainSaTierBreakdown": sa_breakdown,
        "enteredTradeCount": len(entered_keys),
    }

    # 控制台摘要
    baseline = by_candidate.get("baseline") or {}
    print(
        f"[fit] S/A 档 h8 baseline: n={baseline.get('count')} mean={baseline.get('mean')} "
        f"winRate={baseline.get('winRate')}",
        file=sys.stderr,
    )
    for tier, stats in sorted((by_candidate.get("byCandidateTier") or {}).items()):
        print(
            f"[fit] 分层 {tier}: n={stats.get('count')} mean={stats.get('mean')} "
            f"winRate={stats.get('winRate')} winRateDelta={stats.get('winRateDelta')}",
            file=sys.stderr,
        )
    for regime, stats in sorted((by_regime.get("byRegime") or {}).items()):
        print(
            f"[fit] A_MAIN regime {regime}: n={stats.get('count')} mean={stats.get('mean')} "
            f"winRate={stats.get('winRate')} winRateDelta={stats.get('winRateDelta')}",
            file=sys.stderr,
        )
    print(
        f"[fit] A_MAIN entered: n={entered.get('entered', {}).get('count')} "
        f"winRate={entered.get('entered', {}).get('winRate')} "
        f"| unentered: n={entered.get('unentered', {}).get('count')} "
        f"winRate={entered.get('unentered', {}).get('winRate')} "
        f"| enteredWinRateDelta={entered.get('enteredWinRateDelta')}",
        file=sys.stderr,
    )
    for tier, stats in sorted(sa_breakdown.items()):
        print(
            f"[fit] A_MAIN 内 synergy {tier}: n={stats.get('count')} mean={stats.get('mean')} "
            f"winRate={stats.get('winRate')}",
            file=sys.stderr,
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[fit] report written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
