"""门控翻转率诊断（WP3.2，只读）——WP2 去噪效果的基线/对比度量。

用法：cd quant-board && .venv/Scripts/python.exe -m backend.operations.diagnose_gate_flip_rate \
    --dataset <dataset_id> [--start 2026-08-01] [--end 2026-08-31] [--out <path>]

只读不写库；样本不足或字段缺失在报告中显式计数（fail-visible），不静默。
signals 为 replay 产物：每帧×每股一条，per-code 序列按 signal["code"] 分组，
market 级 regime 按 snapshotId 去重（同帧全股票同 state）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from backend.analysis.ranktrend.research.gate_flip_stats import (
    count_gate_flips,
    extract_gate_states,
)


def _stage_bucket(slot_time: str) -> str:
    if not slot_time:
        return "mid"
    if slot_time <= "10:30":
        return "morning"
    if slot_time >= "14:00":
        return "late"
    return "mid"


def collect_flip_report(signals: list[dict[str, Any]]) -> dict[str, Any]:
    per_code_states: dict[str, list[dict[str, Any]]] = defaultdict(list)
    regime_by_snapshot: dict[str, str] = {}
    stage_sequences: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for signal in signals:  # replay 追加序 = 帧序
        states = extract_gate_states(signal)
        code = str(signal.get("code") or "")
        if code:
            per_code_states[code].append(states)
        sid = str(signal.get("snapshotId") or "")
        if sid and states["regime_state"] and sid not in regime_by_snapshot:
            regime_by_snapshot[sid] = states["regime_state"]
        stage_sequences[_stage_bucket(str(signal.get("slotTime") or ""))].append(
            (sid, states)
        )
    report = count_gate_flips(dict(per_code_states), list(regime_by_snapshot.values()))
    stage_flip_rates = {}
    for bucket, pairs in stage_sequences.items():
        # 桶内 regime 序列同样按 snapshotId 去重（同帧多股同 state，不重复计数）
        bucket_regime: dict[str, str] = {}
        for sid, states in pairs:
            if sid and states["regime_state"] and sid not in bucket_regime:
                bucket_regime[sid] = states["regime_state"]
        sub = count_gate_flips({"all": [s for _, s in pairs]}, list(bucket_regime.values()))
        stage_flip_rates[bucket] = sub["flip_rates"]
    report["stage_flip_rates"] = stage_flip_rates
    report["frame_count"] = len(regime_by_snapshot)
    report["signal_count"] = len(signals)
    report["code_count"] = len(per_code_states)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="门控翻转率诊断（只读）")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--snapshot-type", default="half_hour")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from backend.analysis.ranktrend.engine import RankTrendPythonEngine
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
    engine = RankTrendPythonEngine()
    signals = engine.replay(frames, meta={})
    report = collect_flip_report(signals)
    report["dataset"] = args.dataset
    report["snapshotType"] = args.snapshot_type
    report["start"] = args.start
    report["end"] = args.end
    out_path = Path(args.out) if args.out else Path("data/reports") / (
        f"gate_flip_rate_{args.dataset}_{args.start or 'all'}_{args.end or 'all'}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"frameCount={report['frame_count']} signalCount={report['signal_count']} codes={report['code_count']}", file=sys.stderr)
    print(json.dumps(report["flip_rates"], ensure_ascii=False))
    print(f"report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
