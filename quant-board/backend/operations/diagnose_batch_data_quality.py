# -*- coding: utf-8 -*-
"""批次数据质量只读盘点（B-202610 阶段 0 前置项，2026-09-16）。

盘点 rerun-plan §4 阶段 0.1 五项中的三项（只读、打标记、不阻断，fail-visible）：
1. 每日帧数覆盖：half_hour 按 tradingDate 计数，<8 帧标 LOW（不硬判交易日历，
   周末/假日由帧分布自然呈现）；
2. 标准窗披露：decision/oos1/oos2/oos2u 帧数 + warm-up 前 29 帧截止日
   （get_technical_min_samples≥30 → 前 29 帧无信号，引擎设计行为，不计判定样本）；
3. 槽位情绪覆盖：hotlist_sentiment 按 tradingDate 计数，与快照帧日交叉
   → 快照有帧而情绪缺文档的日子标 SENTIMENT_MISSING（如 9/1-9/2 EOD stale 回退）。

其余两项不在此重算（避免口径漂移，复用专脚本，输出指引）：
- ATR unknown 率 → diagnose_atr_discrimination（--window，P6-a 口径）
- amount 可算率 → evaluate_vp_amount_ratio 的 P4-0 前置诊断（随 baseline 留痕）

oos2u 消费禁令（2026-09-16 起）：本脚本只读统计、不产出参数结论，不受限；
oos2u 已积累帧数仅作披露，判定读数以 B-202610 批次执行为准。

用法：
  python -m backend.operations.diagnose_batch_data_quality [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.optimize_resonance_parameters import load_frames
from backend.optimization.data_windows import (
    DECISION_START,
    OOS2_END,
    WINDOWS,
)

FULL_DAY_FRAMES = 16  # half_hour 每交易日满帧参考值（4h × 2 帧/h × 2 市场段）
LOW_DAY_FRAMES = FULL_DAY_FRAMES // 2  # 低于 8 帧标 LOW（打标记，不阻断）
WARMUP_FRAMES = 29  # get_technical_min_samples≥30 → 前 29 帧无信号（引擎设计行为）
DATASET_ID = "dragonboard_live"
SNAPSHOT_TYPE = "half_hour"

REPORT_DIR = Path(r"D:\dragon-board\quant-board\data\reports")


def sentiment_days(start: str, end: str) -> dict[str, int]:
    """hotlist_sentiment 按 tradingDate 计数（同 repo 查询字段：datasetId/snapshotType/tradingDate）。"""
    coll = get_runtime_mongodb_database()["hotlist_sentiment"]
    cur = coll.find(
        {
            "datasetId": DATASET_ID,
            "snapshotType": SNAPSHOT_TYPE,
            "tradingDate": {"$gte": start, "$lte": end},
        },
        {"tradingDate": 1, "_id": 0},
    )
    return dict(Counter(str(doc.get("tradingDate") or "") for doc in cur))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="批次数据质量只读盘点（B-202610 阶段 0）")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    t0 = time.time()
    frames = load_frames(DECISION_START, OOS2_END)
    print(f"[dq] frames={len(frames)} range={DECISION_START}~{OOS2_END} ({time.time() - t0:.0f}s)", file=sys.stderr)

    by_day = Counter(str(f.get("tradingDate") or "") for f in frames)
    daily = [
        {"date": d, "frames": n, "flag": "LOW" if n < LOW_DAY_FRAMES else "ok"}
        for d, n in sorted(by_day.items())
    ]

    windows_report: dict[str, Any] = {}
    for key in ("decision", "oos1", "oos2", "oos2u"):
        s, e = WINDOWS[key]
        wf = [f for f in frames if s <= str(f.get("tradingDate") or "") <= e]
        if wf:
            warmup_cut = str(wf[min(WARMUP_FRAMES, len(wf)) - 1].get("tradingDate") or "")
            note = (
                f"前 {WARMUP_FRAMES} 帧（至 {warmup_cut}）无信号（引擎设计行为，不计判定样本）"
                if len(wf) >= WARMUP_FRAMES
                else f"全窗 {len(wf)} 帧 < warm-up {WARMUP_FRAMES} 帧 → 全窗无信号"
            )
        else:
            note = "无帧（数据未落库或非交易日）"
        windows_report[key] = {
            "start": s,
            "end": e,
            "frames": len(wf),
            "signalEffectiveFrames": max(0, len(wf) - WARMUP_FRAMES),
            "tradingDaysWithFrames": len({str(f.get("tradingDate") or "") for f in wf}),
            "warmupNote": note,
        }

    sent = sentiment_days(DECISION_START, OOS2_END)
    frame_days = set(by_day)
    missing = sorted(d for d in frame_days - set(sent) if d)
    orphan = sorted(d for d in set(sent) - frame_days if d)

    report: dict[str, Any] = {
        "diagnostic": "批次数据质量只读盘点（B-202610 阶段 0 前置项）",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "readOnly": True,
        "oos2uConsumptionBan": "2026-09-16 起 09-13 后新帧除批次执行外不得跑结论性扫描；本脚本只读统计不受限",
        "framesRange": {"start": DECISION_START, "end": OOS2_END, "total": len(frames)},
        "dailyCoverage": daily,
        "lowDays": [d["date"] for d in daily if d["flag"] == "LOW"],
        "windows": windows_report,
        "sentimentCoverage": {
            "collection": "hotlist_sentiment",
            "daysWithDocs": len(sent),
            "sentimentMissingOnFrameDays": missing,
            "orphanDaysWithoutFrames": orphan,
            "note": "SENTIMENT_MISSING 日 = 快照有帧但情绪无文档（如 9/1-9/2 EOD stale 回退）；打标记不剔除",
        },
        "reusedScripts": {
            "atrUnknownRate": "python -m backend.operations.diagnose_atr_discrimination --window <win>（P6-a 口径）",
            "amountComputableRate": "evaluate_vp_amount_ratio P4-0 前置诊断（随 baseline 留痕）",
        },
    }

    out_path = Path(args.out) if args.out else REPORT_DIR / "batch-data-quality.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "totalFrames": len(frames),
                "lowDays": report["lowDays"],
                "windows": {k: {"frames": v["frames"], "tradingDays": v["tradingDaysWithFrames"]} for k, v in windows_report.items()},
                "sentimentMissingOnFrameDays": missing,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"[dq] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
