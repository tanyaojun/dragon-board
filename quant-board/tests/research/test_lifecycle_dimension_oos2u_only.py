# -*- coding: utf-8 -*-
"""lifecycle 维 harness B-202610 演练扩展测试：--only 缩围过滤。

2026-09-25 演练（rerun-plan §4 阶段 3 O6）：MidLongCommitmentMin 剂量曲线重扫——
trial 表全量 51+（13 阈值 × 3 档 + 精扫 + 提案），演练只需 MidLong 相关档 + baseline；
`filter_specs` 提供 key 前缀过滤（baseline 恒保留，contribution_summary 对照依赖）。
"""
from __future__ import annotations

from backend.operations.evaluate_lifecycle_dimension import (
    TRIAL_GROUPS,
    filter_specs,
)


def _all_specs() -> list[dict]:
    specs: list[dict] = []
    for group in ("a_display", "b_scan", "b_refine", "proposal"):
        specs.extend(TRIAL_GROUPS.get(group) or [])
    return specs


def test_filter_empty_keeps_everything():
    specs = _all_specs()
    assert filter_specs(specs, "") == specs
    assert filter_specs(specs, "  ") == specs


def test_filter_prefix_keeps_baseline_and_matched():
    specs = _all_specs()
    filtered = filter_specs(specs, "thr_lifecycleMidLongCommitmentMin")
    keys = [s["key"] for s in filtered]
    # baseline 恒保留（contribution_summary 的对照依赖）
    assert keys[0] == "baseline"
    # MidLong 6 档：b_scan ×{05,15,20} + b_refine ×{125,175,30}
    midlong = [k for k in keys if k.startswith("thr_lifecycleMidLongCommitmentMin")]
    assert len(midlong) == 6
    assert "thr_lifecycleVelocityMin__x125" not in keys  # 非匹配 trial 被排除
    assert "a_equal_weights" not in keys
    # 组合提案含 MidLong 轴，单独前缀可拉入
    filtered2 = filter_specs(specs, "thr_lifecycleMidLongCommitmentMin,c1_commit")
    assert "c1_commit_tight" in [s["key"] for s in filtered2]


def test_filter_no_match_keeps_only_baseline():
    specs = _all_specs()
    filtered = filter_specs(specs, "no_such_prefix")
    assert [s["key"] for s in filtered] == ["baseline"]
