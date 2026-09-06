"""成本敏感性扫描（WP3.1，只读）——验证近盈亏平衡结论（如 four_dim pf 1.0377）对成本的弹性。

用法：cd quant-board && .venv/Scripts/python.exe -m backend.operations.diagnose_cost_sensitivity \
    --dataset <dataset_id> [--start 2026-08-01] [--end 2026-08-31] [--out <path>]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_GRID = {"slippageRate": [0.0005, 0.001, 0.002], "feeRate": [0.0003, 0.0006]}


def run_cost_grid(
    frames: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    base_config: dict[str, Any],
    grid: dict[str, list[float]] | None = None,
) -> list[dict[str, Any]]:
    from backend.core.backtest.execution import TradeSimulator

    grid = grid or DEFAULT_GRID
    rows: list[dict[str, Any]] = []
    for slippage in grid.get("slippageRate", []):
        for fee in grid.get("feeRate", []):
            config = copy.deepcopy(base_config)
            config["slippageRate"] = float(slippage)
            config["feeRate"] = float(fee)
            try:
                report = TradeSimulator().run(frames, signals, config) or {}
                rows.append({
                    "slippageRate": float(slippage),
                    "feeRate": float(fee),
                    "profitFactor": report.get("profitFactor"),
                    "winRate": report.get("winRate"),
                    "totalReturn": report.get("totalReturn"),
                    "tradeCount": report.get("tradeCount"),
                })
            except Exception as exc:  # 单格失败不中断网格（fail-visible 记行）
                rows.append({"slippageRate": float(slippage), "feeRate": float(fee), "error": str(exc)})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="成本敏感性扫描（只读）")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--snapshot-type", default="half_hour")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from backend.core.backtest.config import DEFAULT_TRADE_CONFIG
    from backend.data.repositories.mongo_repository import MongoRepository
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

    repository = MongoRepository(get_runtime_mongodb_database())
    frames = repository.load_frame_bundles(
        args.dataset,
        snapshot_type=args.snapshot_type,
        start_date=args.start,
        end_date=args.end,
        projection="ranktrend",
        fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )
    if not frames:
        print(json.dumps({"error": "no_frames_loaded", "dataset": args.dataset}), file=sys.stderr)
        return 1
    signals = _replay_signals(frames)
    rows = run_cost_grid(frames, signals, dict(DEFAULT_TRADE_CONFIG))
    out_path = Path(args.out) if args.out else Path("data/reports") / (
        f"cost_sensitivity_{args.dataset}_{args.start or 'all'}_{args.end or 'all'}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False)[:2000])
    print(f"report -> {out_path}", file=sys.stderr)
    return 0


def _replay_signals(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    return RankTrendPythonEngine().replay(frames, meta={})


if __name__ == "__main__":
    raise SystemExit(main())
