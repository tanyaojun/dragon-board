# -*- coding: utf-8 -*-
"""双强共振降级复核 harness 测试（§11.5/§2.2，全 mock/小数据，不触 MongoDB）。

2026-09-25 B-202610 演练前置修复（TDD）：WINDOWS 曾 import 自
diagnose_regime_saex_decomposition 的手写截断副本（oos2=(09-01,09-09)），与
data_windows.WINDOWS 单一源（oos2 全月 09-30）同名不同义——直接跑会产出截断读数
冒充全月 oos2（审计 D1 同族缺陷）。修复后本 harness 窗口自单一源派生并新增 oos2u
（§2.1 判定读数窗）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.diagnose_dual_strength_syna import (
    WINDOWS,
    _syn_a_group,
)


def _signal(synergy: str, rank_trend: str, cross_section: str) -> dict:
    obs = {name: {"signalTier": tier} for name, tier in (
        ("synergy", synergy), ("rankTrend", rank_trend), ("crossSection", cross_section),
    )}
    return {"rankTrend": {"observation": obs}}


def test_windows_derived_from_single_source():
    """窗口单一源派生：键集合与 bounds 必须与 data_windows.WINDOWS 一致（D1 同族缺陷防线）。

    修复前：import diagnose_regime_saex_decomposition.WINDOWS 手写副本，oos2 截断至
    09-09（比 09-12 更老的口径）且无 oos2u——全月读数会被截断口径冒充。
    """
    from backend.optimization.data_windows import WINDOWS as STANDARD

    assert set(WINDOWS) == {"decision", "oos1", "oos2", "oos2u"}
    for name, bounds in WINDOWS.items():
        start, end = STANDARD[name]
        assert bounds["start"] == start, f"{name}.start 漂移：{bounds['start']} != {start}"
        assert bounds["end"] == end, f"{name}.end 漂移：{bounds['end']} != {end}"
    assert WINDOWS["oos2"]["end"] == "2026-09-30"  # 全月口径（非 09-09/09-12 截断）
    assert WINDOWS["oos2u"]["start"] == "2026-09-13"  # 未消费裁决子窗（§2.1）


def test_syn_a_group_predicate_matches_s22_definition():
    """§2.2 口径：双强 = synA 交集内 rt=A × cs=A 交叉（先圈 synA 再交叉，非共现全集）。"""
    dual = _signal("A", "A", "A")
    assert _syn_a_group("A", "A")(dual) is True
    assert _syn_a_group("A")(dual) is True
    assert _syn_a_group()(dual) is True
    # rt 非 A / cs 非 A / syn 非 A 均不入双强组
    assert _syn_a_group("A", "A")(_signal("A", "B", "A")) is False
    assert _syn_a_group("A", "A")(_signal("A", "A", "C")) is False
    assert _syn_a_group("A", "A")(_signal("B", "A", "A")) is False
    # unknown 档不满足精确档位匹配
    assert _syn_a_group("A", "A")(_signal("A", "unknown", "A")) is False


def test_main_accepts_oos2u_window_choice():
    """--window 必须接受 oos2u（§2.1 判定读数窗）；argparse choices 与 WINDOWS 键集合同步。"""
    import argparse

    from backend.operations import diagnose_dual_strength_syna as mod

    parser = argparse.ArgumentParser()
    parser.add_argument("--window", default="all", choices=["all", *WINDOWS])
    args = parser.parse_args(["--window", "oos2u"])
    assert args.window == "oos2u"
    assert "oos2u" in mod.__dict__.get("WINDOWS", WINDOWS)
