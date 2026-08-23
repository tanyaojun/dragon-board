# -*- coding: utf-8 -*-
"""G4（2026-08-23 前后端分离）：analyze 结果持久化 service。

用户选择 A：采集后对快照帧全量跑 analyze，把每只股票 observation/displayStatus/meta/resonance
持久化到 snapshot_analysis collection（幂等 dataset+snapshot+code），前端读库获稳定回放值
（不随"每次实时算"漂移）。此处用**快照自身帧**作为 current_frame（无前端实时行情），
入库口径 = 采集时快照。

注意：这是**稳定口径入库**，与前端 current_frame 实时 analyze 是两套（用户已确认接受
牺牲实时 current_frame）。ingest 后触发 + 读口 API + 前端读库为后续子工程。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.ranktrend.engine import RankTrendPythonEngine
from backend.api.ranktrend_routes import _analyze_frames, _load_frames_for_analysis


def analyze_snapshot_and_persist(
    repo: Any,
    dataset_id: str,
    snapshot_id: str,
    snapshot_type: str,
    snapshot_frame: dict[str, Any],
) -> int:
    """对单个快照帧全量 analyze 并持久化 observation/displayStatus/meta/resonance。

    返回持久化的股票数（fail-visible：无帧/无 observation 返回 0，不伪造）。
    """
    frames, series_by_code = _load_frames_for_analysis(
        repo,
        dataset_id,
        snapshot_type,
        [],
        current_frame=snapshot_frame,
        codes=None,
    )
    if not frames:
        return 0
    engine = RankTrendPythonEngine()
    output = _analyze_frames(engine, frames, series_by_code, [])
    if not output:
        return 0
    last = output[-1]
    count = 0
    for stock in last.get("stocks", []):
        analysis = stock.get("analysis") or {}
        observation = analysis.get("observation") or {}
        if not observation:
            continue
        repo.upsert_snapshot_analysis(
            dataset_id,
            snapshot_id,
            str(stock.get("code") or ""),
            {
                "observation": observation,
                "displayStatus": analysis.get("displayStatus"),
                "meta": analysis.get("meta"),
                "resonance": analysis.get("resonance"),
            },
        )
        count += 1
    return count
