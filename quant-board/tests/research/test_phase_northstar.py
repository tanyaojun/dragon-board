# -*- coding: utf-8 -*-
"""M2 北极星读数 harness 测试：相位×交易切片 / 相位×权益段切片 / 机械线判定。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_northstar import (
    equity_phase_slices,
    evaluate_northstar,
    worst_drawdown,
)


def _mk_equity(points: list[tuple[str, str, float]]) -> list[dict]:
    return [{"tradingDate": d, "slotTime": s, "equity": e, "marketValue": mv}
            for (d, s, e), mv in zip(points, [0.0] * len(points))]


def test_worst_drawdown_window():
    eq = [100.0, 110.0, 99.0, 105.0, 120.0]
    assert worst_drawdown(eq) == min(0.0, (99 - 110) / 110)  # -0.1


def test_equity_phase_slices():
    daily = {"2026-05-06": "offense", "2026-05-07": "offense", "2026-05-08": "defense"}
    eq = _mk_equity([
        ("2026-05-06", "15:00", 100.0), ("2026-05-07", "15:00", 110.0),
        ("2026-05-08", "15:00", 99.0), ("2026-05-09", "15:00", 108.0),
    ])
    out = equity_phase_slices(eq, daily)
    # offense 段 = 05-06/07 两点；defense 段 = 05-08 一点（05-09 无标签不入段）
    assert out["offense"]["equityPoints"] == 2
    assert out["defense"]["equityPoints"] == 1
    assert out["unknownPoints"] == 1
    # 段内收益：offense 100→110 = +10%（两点才有 segReturn；单点 None）
    assert out["offense"]["segReturn"] == 0.10
    assert out["defense"]["segReturn"] is None


def test_equity_phase_slices_maxdd():
    daily = {"2026-05-06": "defense", "2026-05-07": "defense"}
    eq = _mk_equity([("2026-05-06", "15:00", 110.0), ("2026-05-07", "15:00", 99.0)])
    out = equity_phase_slices(eq, daily)
    assert out["defense"]["maxDD"] == (99 - 110) / 110


def test_evaluate_northstar_mechanical_lines():
    """好相位线：wrxpf≥0.78 ∧ 笔数≥60 ∧ 段内 maxDD≤10%；差相位防守线：段内回撤/净损优于满仓对照。"""
    by_phase = {
        "offense": {"trades": 61, "wrxpf": 0.80, "sumNetReturn": 0.30, "winRate": 0.5, "profitFactor": 1.6},
        "defense": {"trades": 10, "wrxpf": 0.30, "sumNetReturn": -0.20},
    }
    slices = {
        "offense": {"maxDD": -0.05, "equityPoints": 100, "segReturn": 0.10},
        "defense": {"maxDD": -0.08, "equityPoints": 60, "segReturn": -0.04},
    }
    full = {"maxDD": -0.12, "segReturn": -0.02}  # 满仓穿越对照
    out = evaluate_northstar(by_phase, slices, full)
    assert out["offense"]["line"] == {"wrxpf": True, "trades": True, "maxDD": True}
    assert out["offense"]["pass"] is True
    # 防守线：回撤浅于满仓（-0.08 > -0.12）或净损小（-0.04 > -0.02 不成立）→ pass=True（回撤项成立）
    assert out["defense"]["pass"] is True
    assert out["defense"]["defenseLine"] == {"ddBetter": True, "lossBetter": False}
