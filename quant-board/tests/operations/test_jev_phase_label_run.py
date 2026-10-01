# -*- coding: utf-8 -*-
"""SP4-T1 labels v3 测试：五档映射、冻结版本纪律、fallback 提取、覆盖统计（纯函数，无 Mongo）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_phase_label_run import (
    build_slot_labels,
    extract_fallback_labels,
    next_version,
    tier_of_stage,
)


def _doc(day: str, slot: str, stage: str | None, *, kind: str = "slot", status: str = "ok") -> dict:
    doc = {"kind": kind, "status": status, "tradingDate": day, "slotTime": slot, "answers": {}}
    if stage is not None:
        doc["answers"]["sequence_stage"] = {"choice": stage}
    return doc


def test_tier_of_stage_mapping_matches_t_jev_preregistration():
    assert tier_of_stage("start") == "offense"
    assert tier_of_stage("ferment") == "offense"
    assert tier_of_stage("climax") == "offense"
    assert tier_of_stage("ice") == "defense"
    assert tier_of_stage("retreat") == "defense"
    assert tier_of_stage(None) is None
    assert tier_of_stage("weird") is None
    assert tier_of_stage("") is None


def test_build_slot_labels_happy_path_and_fail_visible_counts():
    docs = [
        _doc("2026-09-01", "09:30", "ferment"),
        _doc("2026-09-01", "10:00", "retreat"),
        _doc("2026-09-02", "09:30", "unknown_tier"),   # 未知档 → 计数排除
        _doc("2026-09-02", "10:00", None),              # 缺档 → 计数排除
        _doc("2026-09-02", "10:30", "ice", status="degraded"),  # 非 ok → 计数排除
        _doc("2026-09-02", "11:00", "start", kind="eod"),       # 非 slot → 跳过
    ]
    labels, stats = build_slot_labels(docs)
    assert labels == {"2026-09-01|09:30": "offense", "2026-09-01|10:00": "defense"}
    assert stats["jevSlotDocs"] == 6
    assert stats["skippedNotSlot"] == 1  # 评审 P2-4：非 slot 文档显式计数不再静默跳过
    assert stats["okDocs"] == 4
    assert stats["used"] == 2
    assert stats["skippedUnknownStage"] == 1
    assert stats["skippedMissingStage"] == 1
    assert stats["skippedNotOk"] == 1
    assert stats["days"] == 1


def test_build_slot_labels_empty_and_missing_keys():
    labels, stats = build_slot_labels([])
    assert labels == {}
    assert stats["used"] == 0
    # 缺日期/槽的 ok 文档不崩溃、计数排除
    labels2, stats2 = build_slot_labels([{"kind": "slot", "status": "ok", "answers": {"sequence_stage": {"choice": "ice"}}}])
    assert labels2 == {}
    assert stats2["skippedMissingStage"] == 1


def test_extract_fallback_labels_filters_to_tiers():
    v2 = {"candidates": {"sentiment_2b": {"dailyByPrevDay": {
        "2026-09-01": "offense", "2026-09-02": "defense", "2026-09-03": "unknown",
    }}}}
    assert extract_fallback_labels(v2) == {"2026-09-01": "offense", "2026-09-02": "defense"}
    assert extract_fallback_labels({}) == {}
    assert extract_fallback_labels({"candidates": {"sentiment_2b": {}}}) == {}


def test_next_version_freeze_increments(tmp_path):
    assert next_version(None) == 1
    assert next_version("{}") == 1
    assert next_version(json.dumps({"meta": {"version": 3}})) == 4
    assert next_version("not-json") == 1  # 损坏产物 → 从 1 重开（不静默吞）
