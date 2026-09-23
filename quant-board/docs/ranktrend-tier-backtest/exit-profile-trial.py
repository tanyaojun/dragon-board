# -*- coding: utf-8 -*-
"""profile 一次小窗口回测，定位信号计算 vs 撮合 vs 加载的耗时占比。"""
from __future__ import annotations

import cProfile
import io
import json
import pstats
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

QB_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(QB_ROOT))

from backend.cli import runtime_session  # noqa: E402
from backend.services.backtest_service import BacktestService  # noqa: E402


def main() -> None:
    payload_path = Path(sys.argv[1])
    local_frames_path = Path(sys.argv[2])
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    t0 = time.time()
    import gzip as _gzip
    from backend.data.repositories import mongo_repository

    with _gzip.open(local_frames_path, "rt", encoding="utf-8") as fh:
        local_frames = json.load(fh)
    t_load = time.time() - t0

    def _load_frames_local(self, dataset_id, snapshot_type="half_hour", start_date=None, end_date=None, include_payload=True, fields=None):
        def ok(f):
            d = str(f.get("tradingDate") or "")
            return (not start_date or d >= start_date) and (not end_date or d <= end_date)
        return [f for f in local_frames if ok(f)]

    mongo_repository.MongoRepository.load_frames = _load_frames_local

    profiler = cProfile.Profile()
    t1 = time.time()
    with runtime_session() as session:
        profiler.enable()
        result = BacktestService(session).run_ranktrend(payload)
        profiler.disable()
    t_total = time.time() - t1

    print(f"\n==== timing: load={t_load:.1f}s backtest_total={t_total:.1f}s runId={result.get('runId')}")
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative").print_stats(36)
    text = stream.getvalue()
    seen = False
    for line in text.splitlines():
        if "ncalls" in line:
            seen = True
        if seen and line.strip():
            print(line[:240])
    stream2 = io.StringIO()
    stats2 = pstats.Stats(profiler, stream=stream2)
    stats2.sort_stats("tottime").print_stats(20)
    text2 = stream2.getvalue()
    seen2 = False
    for line in text2.splitlines():
        if "ncalls" in line:
            seen2 = True
        if seen2 and line.strip():
            print("TT " + line[:240])


if __name__ == "__main__":
    main()
