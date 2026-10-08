# -*- coding: utf-8 -*-
"""连续情绪评分核心测试（路线 B，emotion-score-design.md v3）。

设计原则：分数先行、分段边界=历史分布实测分位校准（T1.5 jev 口径重放 2026-09-30）、
每维可分解、缺维降级。高潮压制条款已删除（审计 B3）。
"""
from backend.analysis.hotlist.emotion_score import (
    compute_emotion_score,
    map_stage,
)


def _evidence(**overrides):
    """构造覆盖全部 8 维的 evidence（与 collect_slot_evidence 输出同构）。"""
    base = {
        "breadth": {"total": 246, "limitUp": 24, "up5": 19, "up0": 78, "down0": 88, "down5": 16,
                     "pctMissing": 0, "trin": 0.94},
        "rowFlags": {"strongMoney": 2, "risk": 198, "judgeable": 244},
        "lifecycle": {"ignition": 11, "expansion": 5, "crowded": 9, "reversal": 23,
                       "cooling": 177, "unknown": 0},
        "limit": {"ztCount": 42, "maxBoard": 7, "zhabanRate": 19.0, "boards": {}},
        "yesterdayLimit": {"count": 38, "avgChange": 1.96, "positiveRate": 0.55,
                            "weakeningRate": 0.42, "failedOrWeakRate": 0.82},
        "totalAmount": {"amount": 8.173e11, "vsSamePct": 25.0, "yesterdaySame": 6.5e11},
    }
    base.update(overrides)
    return base


def test_score_full_dims_and_decomposable():
    result = compute_emotion_score(_evidence())
    score = result["score"]
    assert 0 <= score <= 100
    # 可分解：等权合成可从 dims 还原——第八维 amountVsSame 冻结（A-①，2026-10-08），
    # 即使原料齐全（vsSamePct=25.0 在场）也 skipped，有效维 = 7
    assert result["skippedDims"] == ["amountVsSame"]
    subs = [v["sub"] for v in result["dims"].values()]
    assert len(subs) == 7
    assert abs(score - sum(subs) / len(subs)) < 0.1
    assert result["stageCandidate"]


def test_amount_vs_same_dim_frozen_by_gate():
    """第八维冻结门（audit P1-1）：原料在场也不入分，防尾部稀释与代际混用。"""
    result = compute_emotion_score(_evidence())  # base 夹具 vsSamePct=25.0 在场
    assert "amountVsSame" not in result["dims"]
    assert result["skippedDims"] == ["amountVsSame"]
    frozen_score = result["score"]
    # 反证：同一证据若去掉量能原料，分数不变（冻结维零贡献）
    ev = _evidence()
    ev["totalAmount"] = {"amount": None, "vsSamePct": None, "yesterdaySame": None}
    assert compute_emotion_score(ev)["score"] == frozen_score


def test_score_missing_dims_degrade_and_renormalize():
    ev = _evidence()
    ev["totalAmount"] = {"amount": None, "vsSamePct": None, "yesterdaySame": None}  # 量能同期缺失
    ev["breadth"]["trin"] = None  # TRIN 缺失
    partial = compute_emotion_score(ev)
    assert set(partial["skippedDims"]) == {"trin", "amountVsSame"}
    # 归一化：缺失维跳过，score 仍由其余 6 维合成
    subs = [v["sub"] for v in partial["dims"].values()]
    assert len(subs) == 6
    assert abs(partial["score"] - sum(subs) / len(subs)) < 0.1
    # 缺维不会导致 score 伪造（仍为有效分数）
    assert 0 <= partial["score"] <= 100


def test_score_all_dims_missing_returns_none():
    ev = {"breadth": {"total": 0}, "rowFlags": {}, "lifecycle": {}, "limit": {},
          "yesterdayLimit": None, "totalAmount": {}}
    result = compute_emotion_score(ev)
    assert result["score"] is None
    assert result["stageCandidate"] is None
    assert set(result["skippedDims"]) == set(
        ["upRatio", "attackShare", "riskShare", "trin", "yhPositive",
         "limitStruct", "amountVsSame", "riskRowsPct"])


def test_score_strong_bullish_evidence_scores_high():
    ev = _evidence(
        breadth={"total": 246, "limitUp": 40, "up5": 50, "up0": 100, "down0": 40, "down5": 10,
                  "pctMissing": 0, "trin": 0.60},
        rowFlags={"strongMoney": 30, "risk": 80, "judgeable": 244},
        lifecycle={"ignition": 40, "expansion": 35, "crowded": 20, "reversal": 10,
                    "cooling": 130, "unknown": 0},
        limit={"ztCount": 90, "maxBoard": 8, "zhabanRate": 8.0, "boards": {}},
        yesterdayLimit={"count": 38, "avgChange": 5.0, "positiveRate": 0.85,
                         "weakeningRate": 0.2, "failedOrWeakRate": 0.3},
        totalAmount={"amount": 1.8e12, "vsSamePct": 30.0, "yesterdaySame": 1.4e12},
    )
    result = compute_emotion_score(ev)
    assert result["score"] >= 70, f"强多头证据应得高分，实际 {result['score']}"
    assert result["stageCandidate"] in ("高潮", "发酵")


def test_score_strong_bearish_evidence_scores_low():
    ev = _evidence(
        breadth={"total": 246, "limitUp": 2, "up5": 5, "up0": 40, "down0": 120, "down5": 75,
                  "pctMissing": 0, "trin": 2.2},
        rowFlags={"strongMoney": 0, "risk": 230, "judgeable": 244},
        lifecycle={"ignition": 2, "expansion": 1, "crowded": 1, "reversal": 40,
                    "cooling": 200, "unknown": 0},
        limit={"ztCount": 8, "maxBoard": 2, "zhabanRate": 45.0, "boards": {}},
        yesterdayLimit={"count": 38, "avgChange": -3.0, "positiveRate": 0.2,
                         "weakeningRate": 0.9, "failedOrWeakRate": 0.95},
        totalAmount={"amount": 9.0e11, "vsSamePct": -35.0, "yesterdaySame": 1.4e12},
    )
    result = compute_emotion_score(ev)
    assert result["score"] <= 35, f"强空头证据应得低分，实际 {result['score']}"


def test_stage_candidate_uses_slope_for_low_scores():
    """slope 接线（审计 B2）：低分按斜率分退潮/冰点，stageCandidate 与映射同源。"""
    ev = _evidence(
        breadth={"total": 246, "limitUp": 2, "up5": 5, "up0": 40, "down0": 120, "down5": 75,
                  "pctMissing": 0, "trin": 2.2},
        rowFlags={"strongMoney": 0, "risk": 230, "judgeable": 244},
        lifecycle={"ignition": 2, "expansion": 1, "crowded": 1, "reversal": 40,
                    "cooling": 200, "unknown": 0},
        limit={"ztCount": 8, "maxBoard": 2, "zhabanRate": 45.0, "boards": {}},
        yesterdayLimit={"count": 38, "avgChange": -3.0, "positiveRate": 0.2,
                         "weakeningRate": 0.9, "failedOrWeakRate": 0.95},
        totalAmount={"amount": 9.0e11, "vsSamePct": -35.0, "yesterdaySame": 1.4e12},
    )
    assert compute_emotion_score(ev)["stageCandidate"] == "冰点"      # slope 缺省
    assert compute_emotion_score(ev, slope=-8.0)["stageCandidate"] == "退潮"
    assert compute_emotion_score(ev, slope=3.0)["stageCandidate"] == "冰点"


def test_map_stage_by_score():
    assert map_stage(85) == "高潮"   # 压制条款已删除（审计 B3：riskRowsPct 系统性高位）
    assert map_stage(65) == "发酵"
    assert map_stage(50) == "启动"   # slope=None：缺失不发明退潮（预登记 §2）
    # 中段 [40,60) 接 slope 方向（2026-10-08 预登记：高位回落日不再误判启动）
    assert map_stage(50, slope=-12.7) == "退潮"   # 2026-10-08 实证日（44.8/−12.7）
    assert map_stage(50, slope=-0.1) == "退潮"
    assert map_stage(50, slope=0) == "启动"
    assert map_stage(50, slope=3) == "启动"
    # 低分按斜率分退潮/冰点
    assert map_stage(25, slope=-8) == "退潮"
    assert map_stage(25, slope=3) == "冰点"
    assert map_stage(25) == "冰点"


def test_map_stage_boundaries():
    assert map_stage(75) == "高潮"
    assert map_stage(74.9) == "发酵"
    assert map_stage(60) == "发酵"
    assert map_stage(59.9) == "启动"
    assert map_stage(59.9, slope=-0.1) == "退潮"   # 中段下边界：slope<0 即退潮
    assert map_stage(40, slope=-0.1) == "退潮"
    assert map_stage(40) == "启动"
