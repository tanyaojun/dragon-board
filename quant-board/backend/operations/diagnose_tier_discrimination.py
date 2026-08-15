"""阶段 3：四维信号区分度诊断（只读，不写库）。

从真实 MongoDB 加载 half_hour 历史快照 → RankTrendPythonEngine.replay →
对共振/趋势/量价/周期/synergy 各维做 tier 分层统计（tier_forward_returns）
+ 区分度指标（tier_discrimination），输出 JSON 报告到 data/reports/。

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_tier_discrimination
      [--dataset dragonboard_live] [--start 2026-04-15] [--end 2026-08-14]
      [--horizon 1 3 8] [--out data/reports/tier-discrimination.json]

fail-visible：诊断只读、不阻断、不写库；样本不足/缺维时如实输出 None/unknown，
不使用 0 伪装缺失，不静默吞掉任何可计算的档位统计。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.tier_monotonicity import (
    DIMENSION_PATHS,
    tier_discrimination,
    tier_forward_returns,
)
from backend.core.settings import get_settings
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

DIMENSIONS = tuple(DIMENSION_PATHS.keys())  # resonance/rankTrend/volumePrice/lifecycle/synergy
DEFAULT_HORIZONS = (1, 3, 8)


def _load_frames(dataset_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
    settings = get_settings()
    print(
        f"[diagnose] mongodb backend={settings.storage_backend} db={settings.mongodb_database} "
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
    signals = engine.replay(frames, window_size=50)
    return signals


def _dimension_report(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    horizon: int,
) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        stats = tier_forward_returns(signals, frames, horizon=horizon, dimension=dimension)
        report[dimension] = {
            "stats": stats,
            "discrimination": tier_discrimination(stats),
        }
    return report


def _summarize(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for dimension, entry in report.items():
        stats = entry["stats"]
        disc = entry["discrimination"]
        tiers = stats["tiers"]
        tier_line = " ".join(
            f"{t}:n={tiers.get(t, {}).get('count', 0)},r={tiers.get(t, {}).get('meanFutureReturn')},"
            f"acc={tiers.get(t, {}).get('directionAccuracy')},ex={tiers.get(t, {}).get('excessDirectionAccuracy')}"
            for t in ("S", "A", "B", "C", "D", "E", "unknown")
        )
        mono = stats["monotonicity"]
        lines.append(
            f"[{dimension}] unknownRate={stats['unknownRate']} spearman={mono['spearmanRankCorr']} "
            f"reversals={len(mono['reversals'])} passHard={mono['passHardConstraint']} "
            f"discrim: sMinusC={disc['sMinusC']} saAcc={disc['saDirectionAccuracy']} "
            f"saEx={disc['saExcessAccuracy']} deVsC={disc['deVsC']} positiveMonotonic={disc['positiveMonotonic']}\n  {tier_line}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段 3：四维信号区分度诊断（只读）")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--horizon", type=int, nargs="+", default=list(DEFAULT_HORIZONS))
    parser.add_argument("--out", default="data/reports/tier-discrimination.json")
    args = parser.parse_args()

    frames = _load_frames(args.dataset, args.start, args.end)
    if not frames:
        print("[diagnose] no frames loaded — aborting (all sources empty)", file=sys.stderr)
        return 1
    print(f"[diagnose] loaded {len(frames)} frames", file=sys.stderr)

    signals = _run_replay(frames)
    if not signals:
        print("[diagnose] replay produced no signals — aborting", file=sys.stderr)
        return 1
    print(f"[diagnose] replay produced {len(signals)} signals", file=sys.stderr)

    result: dict[str, Any] = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "window": {"dataset": args.dataset, "start": args.start, "end": args.end},
        "frameCount": len(frames),
        "signalCount": len(signals),
        "horizons": {},
    }
    for horizon in args.horizon:
        report = _dimension_report(signals, frames, horizon)
        result["horizons"][str(horizon)] = report
        print(f"--- horizon={horizon} ---\n{_summarize(report)}", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[diagnose] report written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
