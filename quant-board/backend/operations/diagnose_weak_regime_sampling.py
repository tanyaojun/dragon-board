# -*- coding: utf-8 -*-
"""weak 状态 synergy 档位样本量重估（backend/operations，2026-08-17）。

背景：阶段 7.5 regime 分桶发现 weak 是唯一样本外 synergy 区分度成立的 regime，
但 half_hour validation 段（2026-07-09~08-14）S 档仅 12 样本（<30），统计置信度不足。
本脚本用**更长样本外窗口（quarter_hour，2026-03-27~07-31，1399 帧）**重估 weak 桶
S 档样本量与 synergy 区分度显著性（quarter_hour 为显式研究口径，非默认 half_hour）。

方法：quarter_hour frames → chronological split（ratio 0.3）→ 每配置全量 replay →
weak / weak+normal / all 三桶 × all/train/validation 三段统计 synergy h1（S/A/B 样本、
saEx、passHard checks）。

输出：data/reports/weak-regime-sampling.json
fail-visible：样本不足如实输出（count/S 样本可见），不伪造、不归零。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.optimize_resonance_parameters import _tier_summary
from backend.optimization.validation import split_frames
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

REPORT_PATH = Path(r"D:\dragon-board\quant-board\data\reports\weak-regime-sampling.json")

CONFIGS: list[tuple[str, dict[str, Any]]] = [
    ("baseline", {}),
    ("jump_min_0.6", {"tierResonanceJumpFreshnessMin": 0.6}),
    (
        "jump_min_0.6 + reversal_penalty_min_0.4",
        {"tierResonanceJumpFreshnessMin": 0.6, "tierResonanceReversalPenaltyMin": 0.4},
    ),
]
BUCKETS: dict[str, tuple[str, ...] | None] = {
    "weak": ("weak",),
    "weak+normal": ("weak", "normal"),
    "all": None,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="weak 状态 synergy 档位样本量重估（quarter_hour 长窗口）")
    parser.add_argument("--snapshot-type", default="quarter_hour", choices=("quarter_hour", "half_hour"))
    parser.add_argument("--start", default="2026-03-27")
    parser.add_argument("--end", default="2026-07-31")
    args = parser.parse_args()

    repo = MongoRepository(get_runtime_mongodb_database())
    frames = repo.load_frame_bundles(
        "dragonboard_live",
        snapshot_type=args.snapshot_type,
        start_date=args.start,
        end_date=args.end,
        projection="ranktrend",
        fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )
    print(f"[weak-sampling] type={args.snapshot_type} frames={len(frames)} window={args.start}~{args.end}", file=sys.stderr)
    if not frames:
        print("[weak-sampling] no frames loaded — aborting", file=sys.stderr)
        return 1

    split = split_frames(frames, {"validation_mode": "chronological", "validation_ratio": 0.3})
    train_frames = split["train_frames"]
    validation_frames = split["validation_frames"]
    meta = split["metadata"]
    print(
        f"[weak-sampling] train={len(train_frames)} ({meta['train']['startDate']}~{meta['train']['endDate']}) / "
        f"validation={len(validation_frames)} ({meta['validation']['startDate']}~{meta['validation']['endDate']})",
        file=sys.stderr,
    )

    report: dict[str, Any] = {
        "window": {"snapshotType": args.snapshot_type, "start": args.start, "end": args.end, "frameCount": len(frames)},
        "split": meta,
        "configs": {},
    }
    for label, params in CONFIGS:
        trial = RankTrendConfig(**{**dict(RankTrendConfig().__dict__), **params})
        print(f"[weak-sampling] {label} replay ...", file=sys.stderr)
        t0 = time.time()
        signals = RankTrendPythonEngine(config=trial).replay(frames, window_size=50)
        replay_sec = round(time.time() - t0, 1)
        entry: dict[str, Any] = {"params": params, "replaySec": replay_sec, "buckets": {}}
        for bname, bset in BUCKETS.items():
            flt = (lambda s, bset=bset: bset is None or str(s.get("regime") or "normal") in bset)
            bucket: dict[str, Any] = {"signalCount": sum(1 for s in signals if flt(s)), "segments": {}}
            for seg_name, seg_frames in (("all", frames), ("train", train_frames), ("validation", validation_frames)):
                t1 = time.time()
                syn = tier_forward_returns(signals, seg_frames, horizon=1, dimension="synergy", signal_filter=flt)
                tiers = syn.get("tiers") or {}
                mono = syn.get("monotonicity") or {}
                bucket["segments"][seg_name] = {
                    "synergySummary": _tier_summary(syn),
                    "sCount": (tiers.get("S") or {}).get("count"),
                    "aCount": (tiers.get("A") or {}).get("count"),
                    "bCount": (tiers.get("B") or {}).get("count"),
                    "sExcessAcc": (tiers.get("S") or {}).get("excessDirectionAccuracy"),
                    "aExcessAcc": (tiers.get("A") or {}).get("excessDirectionAccuracy"),
                    "checks": mono.get("checks"),
                    "elapsedSec": round(time.time() - t1, 1),
                }
                seg = bucket["segments"][seg_name]
                print(
                    f"[weak-sampling] {label} | {bname} | {seg_name}: S={seg['sCount']} A={seg['aCount']} "
                    f"B={seg['bCount']} saEx={seg['synergySummary']['saEx']} pass={seg['synergySummary']['passHard']}",
                    file=sys.stderr,
                )
            entry["buckets"][bname] = bucket
        report["configs"][label] = entry
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[weak-sampling] report written to {REPORT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
