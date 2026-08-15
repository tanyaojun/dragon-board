"""阶段 6：趋势反转 × Jump 跳跃度搭配统计分析（只读，不写库）。

从真实 MongoDB 加载 half_hour 历史快照 → RankTrendPythonEngine.replay →
对 trendReversal 信号按 jump 参数（事件方向 / 新鲜度 / 幅度）分桶，
统计 h1/h3/h8 价格收益，对照全量 trend_reversal 基线，
回答"低位弱转强 + 排名跳跃确认（jump buy + 新鲜 + 大幅）是否有正期望"。

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_trend_reversal_jump
      [--dataset dragonboard_live] [--start 2026-04-15] [--end 2026-08-14]
      [--out data/reports/trend-reversal-jump.json]

fail-visible：只读、不阻断、不写库；每桶独立 skipped* 计数，不伪造收益。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.trend_reversal_jump import (
    DEFAULT_HORIZONS,
    trend_reversal_jump_stats,
)
from backend.core.settings import get_settings
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段 6：趋势反转 × Jump 搭配分析（只读）")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--horizon", type=int, nargs="+", default=list(DEFAULT_HORIZONS))
    parser.add_argument("--out", default="data/reports/trend-reversal-jump.json")
    args = parser.parse_args()

    settings = get_settings()
    print(
        f"[trj] mongodb backend={settings.storage_backend} db={settings.mongodb_database} "
        f"dataset={args.dataset} window={args.start}~{args.end}",
        file=sys.stderr,
    )
    repo = MongoRepository(get_runtime_mongodb_database())
    frames = repo.load_frame_bundles(
        args.dataset,
        snapshot_type="half_hour",
        start_date=args.start,
        end_date=args.end,
        projection="ranktrend",
        fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )
    if not frames:
        print("[trj] no frames loaded — aborting (all sources empty)", file=sys.stderr)
        return 1
    print(f"[trj] loaded {len(frames)} frames", file=sys.stderr)

    engine = RankTrendPythonEngine(config=RankTrendConfig())
    signals = engine.replay(frames, window_size=50)
    if not signals:
        print("[trj] replay produced no signals — aborting", file=sys.stderr)
        return 1
    print(f"[trj] replay produced {len(signals)} signals", file=sys.stderr)

    stats = trend_reversal_jump_stats(signals, frames, horizons=tuple(args.horizon))
    result = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "window": {"dataset": args.dataset, "start": args.start, "end": args.end},
        "horizonsAnalyzed": list(args.horizon),
        **stats,
    }
    print(
        f"[trj] trendReversal={stats['trendReversalCount']} "
        f"(/{stats['signalCount']} signals)",
        file=sys.stderr,
    )
    for horizon in args.horizon:
        print(f"--- horizon={horizon} ---", file=sys.stderr)
        for bucket, s in result["horizons"][str(horizon)].items():
            print(
                f"  {bucket:<36} n={s['count']:>6} mean={s['mean']} median={s['median']} "
                f"winRate={s['winRate']} skipped={s['skipped']}",
                file=sys.stderr,
            )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[trj] report written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
