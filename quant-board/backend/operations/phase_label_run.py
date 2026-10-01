# -*- coding: utf-8 -*-
"""M1 全窗打标：候选相位定义 × 全窗帧 → 帧级+日级标签 JSON（含溯源元数据，M3）。

用法（quant-board 目录）：
  ./.venv/Scripts/python.exe -m backend.operations.phase_label_run \
      --frames data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz \
      --out data/reports/phase-monitor/phase-labels-v2.json

只读：Mongo hotlist_sentiment（half_hour 口径）+ 本地 frames gzip；不占 8000。
候选定义（v2，2026-10-01 章程 Q1 裁决：sentiment_2b 边界 50→60，与四带强带下沿嵌套对齐）：
  sentiment_v1 : emotionScore.score，hi=55 / lo=40（三档）
  sentiment_2b : emotionScore.score 两档，hi=60 / lo=60（offense≥60；v1 历史口径 hi=50/lo=50 见地图基线 v1 对照段）
  breadth_v1   : marketContext.marketStats.emotionValue，hi=0.005 / lo=-0.005
"""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pymongo import MongoClient

from backend.operations.phase_labeler import (
    daily_phase_from_frames,
    load_sentiment_scores,
    phase_from_emotion_value,
    phase_from_sentiment_score,
    shift_daily_to_prev,
)

CANDIDATES = {
    "sentiment_v1": ("sentiment", {"hi": 55.0, "lo": 40.0}),
    "sentiment_2b": ("sentiment", {"hi": 60.0, "lo": 60.0}),
    "breadth_v1": ("emotion_value", {"hi": 0.005, "lo": -0.005}),
}


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 相位打标（只读）")
    parser.add_argument("--frames", required=True, help="本地 frames gzip 路径")
    parser.add_argument("--out", required=True, help="输出 JSON 路径")
    args = parser.parse_args()

    with gzip.open(args.frames, "rt", encoding="utf-8") as f:
        frames = json.load(f)
    days = sorted({str(fr.get("tradingDate") or "") for fr in frames if fr.get("tradingDate")})
    print(f"[phase-label] frames={len(frames)} days={len(days)}", file=sys.stderr)

    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]
    docs = list(db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour"},
        {"tradingDate": 1, "slotTime": 1, "emotionScore.score": 1},
    ))
    frame_scores, eod_scores = load_sentiment_scores(docs)
    missing_days = [d for d in days if not any(k[0] == d for k in frame_scores)]
    print(f"[phase-label] sentiment docs={len(docs)} eod_days={len(eod_scores)} 有帧无情绪日={missing_days}", file=sys.stderr)

    report: dict = {
        "meta": {  # 溯源元数据（M3）：复测对账用
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "gitCommit": _git_commit(),
            "framesFile": Path(args.frames).name,
            "frameCount": len(frames),
            "tradingDays": len(days),
            "datasetId": "dragonboard_live",
            "snapshotType": "half_hour",
            "sentimentDocCount": len(docs),
            "daysWithoutSentiment": missing_days,
            "synthesizedFrames": sum(1 for fr in frames if fr.get("captureMode") == "synthesized"),
        },
        "candidates": {},
    }
    for key, (source, thr) in CANDIDATES.items():
        labeled = []
        for fr in frames:
            day, slot = str(fr.get("tradingDate") or ""), str(fr.get("slotTime") or "")
            if source == "sentiment":
                phase = phase_from_sentiment_score(frame_scores.get((day, slot)), **thr)
            else:
                mv = ((fr.get("marketContext") or {}).get("marketStats") or {}).get("emotionValue")
                phase = phase_from_emotion_value(mv if isinstance(mv, (int, float)) else None, **thr)
            labeled.append({"tradingDate": day, "slotTime": slot, "phase": phase})
        daily = daily_phase_from_frames(labeled)
        daily_eod = {d: phase_from_sentiment_score(s, **thr) for d, s in eod_scores.items()} \
            if source == "sentiment" else {}
        report["candidates"][key] = {
            "source": source, "thresholds": thr,
            "frameLabels": labeled,
            "dailyByMajority": daily,
            "dailyByPrevDay": shift_daily_to_prev(daily, days),
            "dailyByEod": daily_eod,
        }
        dist = Counter(x["phase"] for x in labeled)
        print(f"[phase-label] {key}: 帧分布={dict(dist)} 日数={len(daily)}", file=sys.stderr)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    print(f"[phase-label] -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
