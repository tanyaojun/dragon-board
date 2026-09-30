# -*- coding: utf-8 -*-
"""M1 检验三关测试：翻转率 / 对称互相关滞后 / 帧级+日级区分度（scipy mannwhitneyu）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_quality_report import (
    flip_rate,
    lag_check,
    monthly_discrimination,
)


def test_flip_rate():
    labels = ["offense", "offense", "defense", "defense", "offense", "unknown", "offense"]
    # 6 对相邻转移中，含 unknown 的 2 对不计分母 → 4 对有效，其中 2 对翻转 → 0.5
    rate = flip_rate(labels)
    assert abs(rate - 0.5) < 1e-9


def test_monthly_discrimination_pass_and_direction():
    """两侧各 ≥2 才产行；方向反指的月份 pass 必须 False（I2）；样本不足月进 skipped。"""
    daily = {
        "2026-05-04": "offense", "2026-05-05": "offense", "2026-05-06": "defense", "2026-05-07": "defense",
        "2026-06-01": "offense", "2026-06-02": "offense", "2026-06-03": "defense", "2026-06-04": "defense",
        "2026-07-01": "defense", "2026-07-02": "defense", "2026-07-03": "offense", "2026-07-04": "offense",
        "2026-08-01": "offense",  # 8 月单侧 → skipped
    }
    rets = {
        "2026-05-04": 0.05, "2026-05-05": 0.06, "2026-05-06": -0.05, "2026-05-07": -0.04,
        "2026-06-01": 0.04, "2026-06-02": 0.05, "2026-06-03": -0.06, "2026-06-04": -0.04,
        "2026-07-01": 0.07, "2026-07-02": 0.08, "2026-07-03": -0.05, "2026-07-04": -0.06,  # 7 月方向反指
        "2026-08-01": 0.01,
    }
    out = monthly_discrimination(daily, rets)
    rows = out["months"]
    assert len(rows) == 3                      # 8 月 skipped
    assert out["skippedMonths"] == ["2026-08"]
    assert out["directionConsistentMonths"] == 2  # 5/6 月 offense>defense，7 月反指不计
    may = next(r for r in rows if r["month"] == "2026-05")
    assert may["offenseMean"] > may["defenseMean"] and may["pass"] is True
    july = next(r for r in rows if r["month"] == "2026-07")
    assert july["offenseMean"] < july["defenseMean"] and july["pass"] is False  # 反指拦截


def test_lag_check_semantics():
    """相位领先收益 2 步 → argmax=+2 且 acceptable；相位落后 4 步 → argmax=-4 不合格。"""
    days = [f"2026-06-{d:02d}" for d in range(1, 11)]
    phase_seq = ["offense"] * 5 + ["defense"] * 5  # 块状非周期，避免偶数 lag 歧义
    daily = dict(zip(days, phase_seq))

    # 领先 2 步：ret(t) 由 phase(t-2) 决定 → c(+2)=1 唯一最大
    rets = {days[i]: (0.01 if phase_seq[i - 2] == "offense" else -0.01) for i in range(2, 10)}
    out = lag_check(daily, rets)
    assert out["argmaxLag"] == 2 and out["acceptable"] is True

    # 落后 4 步：ret(t) 由 phase(t+4) 决定 → c(-4)=1 唯一最大，滞后 4>3 不合格
    # （构造纪律：rets 必须覆盖全部天——lag_check 配对要求 phase(t) 与 ret(t+k) 双存在，
    #   覆盖不足会把 c(-4) 截到 n<3 归零，argmax 假移位；尾部天给微噪声防常数列）
    days = [f"2026-06-{d:02d}" for d in range(1, 13)]
    phase_seq = ["offense"] * 6 + ["defense"] * 6
    daily = dict(zip(days, phase_seq))
    rets2 = {}
    for i, d in enumerate(days):
        if i + 4 < len(days):
            rets2[d] = 0.01 if phase_seq[i + 4] == "offense" else -0.01
        else:
            rets2[d] = 0.001 * (1 if i % 2 == 0 else -1)
    out2 = lag_check(daily, rets2)
    assert out2["argmaxLag"] == -4 and out2["acceptable"] is False
