# -*- coding: utf-8 -*-
"""SP5 T1/T2 诊断纯函数测试：前向读数、高标子池、分带、交易层 MAE 回联（无 Mongo，无网络）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.diagnose_jev_day_axis import (
    day_forward_metrics,
    gate_verdict,
    pool_ret,
    quartile_band,
    top_codes,
    trade_observed_mae,
)


def test_pool_ret_min_shared_guard():
    a = {"A": 10.0, "B": 20.0}
    b = {"A": 11.0, "B": 22.0}
    assert abs(pool_ret(a, b, 2) - 0.1) < 1e-9
    assert pool_ret(a, {"A": 11.0}, 2) is None  # 共享不足
    assert pool_ret({}, b, 1) is None


def test_top_codes_rank_top_decile_with_floor():
    stocks = [{"code": f"c{i}", "rank": i} for i in range(1, 11)]  # rank 1..10
    assert set(top_codes(stocks)) == {"c1", "c2", "c3"}  # 10% = 1 只，下限 3
    small = [{"code": "x1", "rank": 1}, {"code": "x2", "rank": 2}]
    assert set(top_codes(small)) == {"x1", "x2"}  # 下限 3 但池只有 2
    assert top_codes([{"code": "n", "rank": None}]) == []  # 无有效 rank


def test_quartile_band_boundaries():
    assert quartile_band(1.0, 2.0, 3.0, 4.0) == "Q1"
    assert quartile_band(2.0, 2.0, 3.0, 4.0) == "Q1"  # 边界归下带（<=）
    assert quartile_band(2.1, 2.0, 3.0, 4.0) == "Q2"
    assert quartile_band(3.0, 2.0, 3.0, 4.0) == "Q2"
    assert quartile_band(4.1, 2.0, 3.0, 4.0) == "Q4"


def test_day_forward_metrics_known_values():
    # 三帧两股：f0{A10,B20} f1{A9,B22} f2{A8,B18}（下限参数化后小池可测）
    prices = [{"A": 10.0, "B": 20.0}, {"A": 9.0, "B": 22.0}, {"A": 8.0, "B": 18.0}]
    tops = [["A", "B"], ["A", "B"], ["A", "B"]]
    m = day_forward_metrics(prices, tops, min_pool=2, min_top=2)
    # h1: f1 vs f0 = mean(-0.1, +0.1) = 0；f2 vs f1 = mean(-1/9, -4/22)
    assert m[0]["h1"] is None  # 首帧无 h1
    assert abs(m[1]["h1"] - 0.0) < 1e-9
    assert abs(m[2]["h1"] - ((8 / 9 - 1) + (18 / 22 - 1)) / 2) < 1e-9
    # f0: fwdEnd = f2 池收益 = mean(-0.2, -0.1) = -0.15；fwdWorst = min(0, -0.15)
    assert abs(m[0]["fwdEnd"] - (-0.15)) < 1e-9
    assert abs(m[0]["fwdWorst"] - (-0.15)) < 1e-9
    # f1: fwdEnd = fwdWorst = f2 池收益
    assert abs(m[1]["fwdEnd"] - m[1]["fwdWorst"]) < 1e-12
    # 尾帧无前向窗口
    assert m[2]["fwdEnd"] is None and m[2]["fwdWorst"] is None
    # 高标子池同池时与全池一致
    assert abs(m[0]["fwdWorstTop"] - m[0]["fwdWorst"]) < 1e-12


def test_day_forward_metrics_top_diverges_from_pool():
    # 高标子池只看 A：A 一路下行 → fwdWorstTop 比 fwdWorst（含 B 上行）更深
    prices = [{"A": 10.0, "B": 10.0, "C": 10.0}, {"A": 8.0, "B": 11.0, "C": 10.0}, {"A": 7.0, "B": 12.0, "C": 10.0}]
    tops = [["A"], ["A"], ["A"]]
    m = day_forward_metrics(prices, tops, min_pool=3, min_top=1)
    assert m[0]["fwdWorstTop"] < m[0]["fwdWorst"]


def test_trade_observed_mae_with_censoring():
    frames = [
        {"tradingDate": "2026-09-01", "_prices": {"A": 10.0}},
        {"tradingDate": "2026-09-01", "_prices": {"B": 5.0}},   # A 掉池 → 截断帧
        {"tradingDate": "2026-09-02", "_prices": {"A": 8.0}},   # 最差可观测 0.8
        {"tradingDate": "2026-09-03", "_prices": {"A": 9.0}},   # 超出 exit_date 不计
    ]
    r = trade_observed_mae(frames, 0, "A", 10.0, "2026-09-02")
    assert abs(r["mae"] - (-0.2)) < 1e-9
    assert r["observedFrames"] == 2
    assert r["censoredFrames"] == 1
    # 全程掉池 → mae None 不伪装
    r2 = trade_observed_mae(frames, 0, "Z", 10.0, "2026-09-02")
    assert r2["mae"] is None and r2["observedFrames"] == 0


def test_gate_verdict_direction_semantics():
    """meanDiff = mean(lo) − mean(hi)；direction = 假设中 (hi−lo) 的符号。"""
    # 温度型（direction=+1，hi 应更优）：meanDiff<0 = Q4 更优 = 支持方向
    full = {"meanDiff": -0.001, "p": 0.01}
    pm = {"2026-04": {"meanDiff": -0.002, "p": 0.01}, "2026-05": {"meanDiff": -0.003, "p": 0.02}}
    assert gate_verdict(pm, full, direction=+1)["verdictHint"] == "PASS"
    # 同数据但方向假设 hi 应更低（拥挤型 direction=-1）→ meanDiff<0 = Q1 更优 = 反向
    assert gate_verdict(pm, full, direction=-1)["verdictHint"] == "REVERSE"
    # 全窗显著反向（温度型：Q1 显著更优）→ REVERSE
    full_rev = {"meanDiff": 0.001, "p": 0.002}
    assert gate_verdict({}, full_rev, direction=+1)["verdictHint"] == "REVERSE"
    # 全窗不显著、月度无显著 → FAIL
    assert gate_verdict({}, {"meanDiff": 0.001, "p": 0.4}, direction=+1)["verdictHint"] == "FAIL"
