# -*- coding: utf-8 -*-
"""扫描 frames 一次性本地导出（harness 侧，不碰 golden 链）。

把指定窗口的快照帧（backtest 链的 repo.load_frames 全量投影）导出为 gzip JSON，
供 exit-scan-trial-runner.py 以 --local-frames 读本地——扫描全程零 MongoDB 大读。
用法：
    python exit-frames-export.py <dataset_id> <snapshot_type> <start> <end> <out.json.gz>
导出内容与 repo.load_frames 返回逐字段一致（含 stocks 行），runner 端按
tradingDate 再过滤，行为与 Mongo 版一致。
"""
from __future__ import annotations

import gzip
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

QB_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(QB_ROOT))

from backend.cli import runtime_session  # noqa: E402
from backend.data.repositories.repository_factory import create_repository  # noqa: E402


def main() -> None:
    if len(sys.argv) < 6:
        raise SystemExit("usage: exit-frames-export.py <dataset> <snap_type> <start> <end> <out.json.gz>")
    dataset, snap_type, start, end, out_path = sys.argv[1:6]
    started = time.time()
    with runtime_session() as session:
        repo = create_repository(session)
        frames = repo.load_frames(dataset, snapshot_type=snap_type, start_date=start, end_date=end, include_payload=True)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(frames, fh, ensure_ascii=False, default=str)
    size_mb = out.stat().st_size / 1_000_000
    print(f"exported {len(frames)} frames -> {out} ({size_mb:.1f} MB) in {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
