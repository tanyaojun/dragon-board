# -*- coding: utf-8 -*-
"""C10 高峰兑现月度复验（peak_revalidate）纯函数测试——全 mock，禁触真实 jev 调用（AGENTS.md §1.2-7）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.peak_revalidate import PEAK, compute_peak_summary


def test_peak_threshold_frozen():
    """主锚=用户裁决 ≥75（ranktrend-c10-peak-exit-plan.md §2.1）。"""
    assert PEAK == 75.0


def test_compute_peak_summary_gap_groups():
    """缺口三分组聚合（V3 强单调口径）+ 基线与 edge；insufficient（缺缺口/缺收益）不入组只计数。"""
    samples = [
        {"date": "2026-05-07", "eodScore": 77.0, "n": 10, "gapLt1": [1.0, 2.0], "gap1to3": [0.5], "gapGe3": [-2.0, -4.0]},
        {"date": "2026-09-16", "eodScore": 80.3, "n": 5, "gapLt1": [3.0], "gap1to3": [], "gapGe3": [-1.0]},
    ]
    out = compute_peak_summary("2026-09", samples, baseline_mean=-0.26)
    assert out["month"] == "2026-09" and out["peakDays"] == 2 and out["samples"] == 15
    assert out["gapLt1"]["n"] == 3 and round(out["gapLt1"]["mean"], 2) == 2.0 and out["gapLt1"]["win"] == 3
    assert out["gapGe3"]["n"] == 3 and round(out["gapGe3"]["mean"], 2) == -2.33 and out["gapGe3"]["win"] == 0
    # 兑现 edge = 基线 - 大高开组均值（兑现换入基线资产避免的回撤，pp）
    assert out["edgeGe3VsBaseline"] == round(-0.26 - (-2.33), 2)


def test_compute_peak_summary_empty_fail_visible():
    """无高峰日 → noData+reason（fail-visible 不伪造）。"""
    out = compute_peak_summary("2026-07", [], baseline_mean=None)
    assert out["peakDays"] == 0 and out["noData"] is True and "无高峰状态日" in out["reason"]
    assert out["gapGe3"]["n"] == 0 and out["gapGe3"]["mean"] is None
