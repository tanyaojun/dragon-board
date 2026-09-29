# -*- coding: utf-8 -*-
"""O7 crossSection A 档复核统计 harness 测试（合成 mini replay，不触 MongoDB）。

2026-09-25 B-202610 演练新增（rerun-plan §4 阶段 3 O7，触发线 §11.5：A 档样本 >500
+ 新窗口 synergy 稳定 >0.05）。统计口径：
- cs 维档位分布与 A 档样本数（raw 命中 + h1 有效前瞻）；
- cs 维 h1 档位统计（A 档 excessDirectionAccuracy / saEx）；
- cs=A 档内 synergy saEx（tier_forward_returns dimension="synergy" + signal_filter）；
- 锚校验：baseline synergy saEx 对照锚注册表 currentGeneration（gen-2026-10-b202610）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.operations.diagnose_cs_a_tier_stats import (
    WINDOWS,
    analyze_window,
    anchor_check,
    cs_tier_counts,
)


def test_windows_single_source_four_keys():
    from backend.optimization.data_windows import WINDOWS as STANDARD

    assert set(WINDOWS) == {"decision", "oos1", "oos2", "oos2u"}
    for name, (start, end) in WINDOWS.items():
        assert (start, end) == STANDARD[name], name
    assert WINDOWS["oos2"][1] == "2026-09-30"  # 全月口径


def test_anchor_check_registry_generation():
    """锚校验对照注册表 currentGeneration：decision 0.1323 匹配、漂移不匹配、未建锚窗跳过。"""
    from backend.operations.harness_common import baseline_anchor

    _gen, anchors = baseline_anchor()
    assert anchors["decision"] == 0.1323
    assert anchor_check("decision", 0.1323, anchors)["match"] is True
    assert anchor_check("decision", 0.13, anchors)["match"] is False
    unchecked = anchor_check("oos2u", None, anchors)
    assert unchecked["checked"] is True and unchecked["match"] is False  # None 不伪装匹配


def test_cs_tier_counts_raw_and_fail_visible():
    signals = [
        {"rankTrend": {"observation": {"crossSection": {"signalTier": "A"}}}},
        {"rankTrend": {"observation": {"crossSection": {"signalTier": "A"}}}},
        {"rankTrend": {"observation": {"crossSection": {"signalTier": "C"}}}},
        {"rankTrend": {"observation": {}}},  # 缺档位 → unknown（fail-visible 如实计数）
    ]
    counts = cs_tier_counts(signals)
    assert counts == {"A": 2, "C": 1, "unknown": 1}


def test_analyze_window_reports_cs_stats_and_dual_strong():
    """合成帧上验证结构：cs 维统计 + A 档内 synergy 统计 + 双强计数，缺失键 fail-visible。"""
    from backend.operations.harness_common import known_answer_issues

    assert known_answer_issues() == []  # 合成 mini replay 前提健康
    from backend.operations.harness_common import _known_answer_frames

    frames = _known_answer_frames()
    # 合成 mini replay 的 saEx 非真锚值：跳过锚校验，只验证统计结构
    result = analyze_window("decision", frames, anchors={"decision": 0.1323}, skip_anchor_on_missing=True)
    assert result["frameCount"] == len(frames)
    assert "error" not in result or result.get("error") != "no frames loaded"
    cs_stats = result["csDimensionH1"]
    assert set(("saEx", "unknownRate", "distribution")) <= set(cs_stats)
    tier_a = result["csATier"]
    assert set(("rawHits", "h1Count", "synergySaExInA", "meanFutureReturnInA")) <= set(tier_a)
    assert tier_a["rawHits"] == cs_tier_counts(_replay_signals(frames)).get("A", 0)
    assert "dualStrong" in result  # 与 T2 口径衔接（synA ∩ rtA ∩ csA）


def _replay_signals(frames: list[dict]) -> list[dict]:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine

    return RankTrendPythonEngine(config=RankTrendConfig()).replay(frames, meta={})


def test_main_writes_report(tmp_path, monkeypatch):
    from backend.operations import diagnose_cs_a_tier_stats as mod
    from backend.operations.harness_common import _known_answer_frames

    monkeypatch.setattr(mod, "load_frames", lambda s, e, purpose="scan": _known_answer_frames())
    out = str(tmp_path / "cs-stats.json")
    monkeypatch.setattr(sys, "argv", ["prog", "--window", "decision", "--out", out, "--skip-anchor-on-missing"])
    assert mod.main() == 0
    report = json.loads(Path(out).read_text(encoding="utf-8"))
    assert report["results"]["decision"]["frameCount"] == 8
