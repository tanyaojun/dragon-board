"""阶段多帧确认回放统计纯函数测试（operations/replay_stage_confirm.py）。

覆盖 spec §8.2 回放输入合同：rawStage 优先、旧文档 stage 回退计数、双 EOD 排除、
确认延迟上界、阈值 1 逐槽等价。
"""
from __future__ import annotations

from operations.replay_stage_confirm import collect_day_points, replay_with_metrics


def test_collect_prefers_rawstage_even_when_stage_already_smoothed() -> None:
    docs = [
        {"_id": "dragonboard_live:half_hour:2026-09-24:09:30", "slotTime": "09:30",
         "rawStage": "退潮", "stage": "高潮"},  # stage 已平滑，不得当原始真值
        {"_id": "dragonboard_live:half_hour:2026-09-24:10:00", "slotTime": "10:00",
         "rawStage": "退潮", "stage": "高潮"},
    ]
    points, counters = collect_day_points(docs)
    assert points == [("09:30", "退潮"), ("10:00", "退潮")]
    assert counters["legacy_fallback"] == 0


def test_collect_legacy_doc_falls_back_to_stage_with_counter() -> None:
    docs = [
        {"_id": "dragonboard_live:half_hour:2026-06-01:09:30", "slotTime": "09:30", "stage": "退潮"},
    ]
    points, counters = collect_day_points(docs)
    assert points == [("09:30", "退潮")]
    assert counters["legacy_fallback"] == 1


def test_collect_excludes_both_eod_shapes() -> None:
    docs = [
        {"_id": "dragonboard_live:half_hour:2026-09-24", "slotTime": "14:30",
         "stage": "启动"},  # 日级 _id 旧 EOD（slotTime 仍是 HH:MM）
        {"_id": "dragonboard_live:half_hour:2026-09-24:14:30", "slotTime": "EOD",
         "stage": "启动"},  # slotTime 哨兵
        {"_id": "dragonboard_live:half_hour:2026-09-24:10:00", "slotTime": "10:00",
         "rawStage": "退潮"},
    ]
    points, _ = collect_day_points(docs)
    assert points == [("10:00", "退潮")]


def test_collect_counts_invalid_slot_shapes() -> None:
    docs = [
        {"_id": "dragonboard_live:half_hour:2026-09-24:09", "slotTime": "09", "stage": "退潮"},
        {"_id": "dragonboard_live:half_hour:2026-09-24:10:00", "slotTime": "10:00",
         "rawStage": "退潮"},
    ]
    points, counters = collect_day_points(docs)
    assert points == [("10:00", "退潮")]
    assert counters["invalid_slot"] == 1


def test_threshold_two_confirms_with_one_slot_delay() -> None:
    """A,A,B,B：候选起点第 3 槽、确认在第 4 槽——最大延迟 1 个可观察槽。"""
    points = [("09:30", "退潮"), ("10:00", "退潮"), ("10:30", "高潮"), ("11:00", "高潮")]
    metrics = replay_with_metrics(points, 2)
    assert metrics["confirmed_switches"] == 1
    assert metrics["confirmed_seq"] == ["退潮", "退潮", "退潮", "高潮"]
    assert metrics["delays"] == [1]
    assert metrics["confirmed_transitions"] == [("10:30", "退潮", "高潮")]


def test_single_slot_candidate_is_absorbed() -> None:
    points = [("09:30", "退潮"), ("10:00", "退潮"), ("10:30", "高潮"), ("11:00", "退潮")]
    metrics = replay_with_metrics(points, 2)
    assert metrics["confirmed_switches"] == 0
    assert metrics["absorbed_singletons"] == 1


def test_threshold_one_is_slot_by_slot_equivalent() -> None:
    points = [("09:30", "退潮"), ("10:00", "高潮"), ("10:30", "退潮"), ("11:00", "发酵")]
    metrics = replay_with_metrics(points, 1)
    assert metrics["confirmed_seq"] == [stage for _, stage in points]
    assert metrics["confirmed_switches"] == 3
