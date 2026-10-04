# -*- coding: utf-8 -*-
"""F3 相位矩阵测试（融合总纲合流点三）：覆盖门拒跑 + 网格聚合纯函数。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_stock_matrix import compute_matrix


def test_compute_matrix_refuses_insufficient_coverage():
    """覆盖门：标签日数 < min_days 拒跑（fail-visible 不产退化矩阵——当前 9/30 单日 64 只即此态）。"""
    cells = [{"band": "弱势40-60", "phase": "climax", "retPct": 1.0}]
    out = compute_matrix(cells, labeled_days=1, min_days=20)
    assert out["ok"] is False
    assert "拒绝产出退化矩阵" in out["reason"]
    assert out["labeledDays"] == 1


def test_compute_matrix_grid_aggregation():
    """四带×五档聚合：n/withRet/meanPct/winRate 逐格正确（键=引擎 BAND_TAGS 原始标签），缺结果笔只计 n 不进均值。"""
    cells = [
        {"band": "冷10-40", "phase": "start", "retPct": 2.0},
        {"band": "冷10-40", "phase": "start", "retPct": -1.0},
        {"band": "冷10-40", "phase": "start", "retPct": None},
        {"band": "弱势40-60", "phase": "divergence", "retPct": -3.0},
        {"band": "极热≥80", "phase": "climax", "retPct": 0.5},
    ]
    out = compute_matrix(cells, labeled_days=25, min_days=20)
    assert out["ok"] is True and out["cells"] == 5
    g = out["grid"]
    assert g["冷10-40"]["start"]["n"] == 3 and g["冷10-40"]["start"]["withRet"] == 2
    assert g["冷10-40"]["start"]["meanPct"] == 0.5 and g["冷10-40"]["start"]["winRate"] == 0.5
    assert g["弱势40-60"]["divergence"]["meanPct"] == -3.0 and g["弱势40-60"]["divergence"]["winRate"] == 0.0
    assert g["极热≥80"]["climax"]["meanPct"] == 0.5
    assert g["强60-80"]["start"]["n"] == 0 and g["强60-80"]["start"]["meanPct"] is None
