# -*- coding: utf-8 -*-
"""data_windows 标准窗口划分测试（2026-08-19 防过拟合 A/B）。"""
import pytest

from backend.optimization.data_windows import (
    FINAL_START,
    TRAIN_END,
    TRAIN_START,
    WINDOWS,
    assert_not_frozen,
    in_window,
    rolling_windows,
    split_window,
)


def _frames(n: int = 30, start: str = "2026-04-15") -> list[dict]:
    from datetime import date, timedelta

    out = []
    d = date.fromisoformat(start)
    for i in range(n):
        out.append({"snapshotId": f"s{i}", "tradingDate": d.isoformat()})
        d += timedelta(days=1)
    return out


def test_window_boundaries_consistent() -> None:
    # train 与 val 无缝衔接、val 与 test、test 与 final
    assert TRAIN_END < WINDOWS["val"][0]
    assert WINDOWS["val"][1] < WINDOWS["test"][0]
    assert WINDOWS["test"][1] < FINAL_START


def test_split_window_respects_inclusive_bounds() -> None:
    frames = _frames()
    train = split_window(frames, "train")
    assert all(in_window(f, *WINDOWS["train"]) for f in train)
    # 边界含当日
    assert split_window(_frames(1, TRAIN_END), "train")  # 5-31 含


def test_rolling_windows_produces_three_sets() -> None:
    # 覆盖 4-15 ~ 7-31（108 天）确保三窗口均有帧
    frames = _frames(n=108)
    for w in rolling_windows(frames):
        assert set(w) == {"train", "val", "test"}
        assert w["train"] and w["val"] and w["test"]


def test_assert_not_frozen_blocks_decision() -> None:
    frames = _frames(start="2026-08-01")
    with pytest.raises(ValueError):
        assert_not_frozen(frames, purpose="scan")
    # report 用途放行
    assert_not_frozen(frames, purpose="report")
    # 非冻结窗口放行
    assert_not_frozen(_frames(start="2026-05-01"), purpose="scan")


def test_ranktrend_windows_registered() -> None:
    # B-202610 口径（2026-09-16 用户裁决）：RankTrend 四窗注册进 WINDOWS 单一事实源
    assert WINDOWS["decision"] == ("2026-04-15", "2026-07-31")
    assert WINDOWS["oos1"] == ("2026-08-15", "2026-08-31")
    assert WINDOWS["oos2"] == ("2026-09-01", "2026-09-30")
    assert WINDOWS["oos2u"] == ("2026-09-13", "2026-09-30")


def test_ranktrend_windows_sequencing() -> None:
    # decision = train+val+test 全域（in-sample 锚定窗）；FINAL 冻结窗与 oos1 无缝；
    # oos2u ⊂ oos2（未消费裁决子窗，M3 纪律）
    assert WINDOWS["decision"] == (TRAIN_START, WINDOWS["test"][1])
    assert WINDOWS["final"][1] < WINDOWS["oos1"][0]
    assert WINDOWS["oos2"][0] <= WINDOWS["oos2u"][0] < WINDOWS["oos2u"][1] <= WINDOWS["oos2"][1]


def test_split_window_oos2u_excludes_consumed_frames() -> None:
    # oos2u 子窗排除 09-13 前已被阶段 0-26 harness 消费的帧（M3 窗口消费折扣）
    frames = (
        _frames(1, "2026-09-12")
        + _frames(1, "2026-09-13")
        + _frames(1, "2026-09-30")
        + _frames(1, "2026-10-01")
    )
    picked = split_window(frames, "oos2u")
    assert [f["tradingDate"] for f in picked] == ["2026-09-13", "2026-09-30"]
    # oos2 全月含 09-12 已消费帧，不含 10 月帧
    picked_oos2 = split_window(frames, "oos2")
    assert [f["tradingDate"] for f in picked_oos2] == ["2026-09-12", "2026-09-13", "2026-09-30"]
