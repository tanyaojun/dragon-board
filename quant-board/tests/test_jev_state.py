# -*- coding: utf-8 -*-
"""jev_state 构建器测试：shape、fail-visible、不伪造。

阶段1 回放验证（quant-board/docs/hotlist-jev/hotlist-jev-phase1-plan.md Task 1）。
"""
import json

from backend.analysis.hotlist.jev_state import build_replay_state


def _frame(limit=None, indices=None, market_stats=None):
    return {"tradingDate": "2026-09-01", "slotTime": "10:30", "datasetId": "dragonboard_live",
            "type": "half_hour", "timestamp": "2026-09-01T10:31:00",
            "limitSummary": limit if limit is not None else {"thsPools": {}, "zhaban": {}},
            "marketStats": market_stats if market_stats is not None else
            {"ztCount": 1, "dtCount": 0, "zhaban": {"rate": 10.0}, "upCount": 60, "downCount": 40},
            "indices": indices if indices is not None else {"sh": {"change": -12.2}}}


def _sentiment(counts):
    return {"stage": "退潮", "confidence": 70,
            "metrics": {"layers": {"top50": {"stageCounts": counts}}}}


FULL_COUNTS = {"ignition": 1, "expansion": 0, "crowded": 0, "reversal": 0, "cooling": 0, "unknown": 0}


def test_state_shape_and_budget():
    st = build_replay_state(
        frame=_frame(indices={"sh": {"change": -12.2}, "zz500": {"change": -23.4}}),
        rows=[{"code": "000592", "name": "平潭发展", "rank": 1, "heat": 95, "pctChange": 9.98,
               "speed": 3.2, "limitUpPrice": 9.66, "price": 9.66, "mainTheme": "算力",
               "snapshotId": "s1", "platforms": ["ths", "xq"]}],
        analysis_by_code={"000592": "ignition"},
        sentiment_doc=_sentiment(FULL_COUNTS),
        prev_counts={k: 0 for k in FULL_COUNTS},
        prev_codes=set())
    assert st["market"]["zt"] == 1
    assert st["lifecycle"]["counts"]["ignition"] == 1
    assert st["lifecycle"]["migration"]["ignition"] == 1
    assert st["stocks"][0]["s"] == "ignition" and st["stocks"][0]["zt"] is True
    assert st["hotlist"]["newEntries"] == 1
    assert len(json.dumps(st, ensure_ascii=False)) < 20000  # ≈5K token 预算


def test_missing_fields_degrade_not_fabricate():
    st = build_replay_state(frame=_frame(limit=None), rows=[], analysis_by_code={},
                            sentiment_doc=None, prev_counts=None, prev_codes=set())
    assert st["quality"]["degraded"], "缺情绪桶/缺行必须记录 degraded"
    assert st["stocks"] == []            # 真实缺失保持空，不伪造
    assert st["lifecycle"] is None       # 缺源保持 None，不伪造全零


def test_no_row_stage_marked_unknown():
    st = build_replay_state(frame=_frame(), rows=[{"code": "X", "name": "X", "rank": 1, "heat": 1,
                                                   "pctChange": 1.0, "snapshotId": "s1"}],
                            analysis_by_code={}, sentiment_doc=_sentiment(FULL_COUNTS),
                            prev_counts=None, prev_codes=set())
    assert st["stocks"][0]["s"] is None
    assert any(d["code"] == "stock_stage_missing" for d in st["quality"]["degraded"])


def test_top_stocks_sorted_by_heat():
    rows = [{"code": f"c{i}", "name": f"s{i}", "rank": i + 1, "heat": h, "pctChange": 0.0,
             "snapshotId": "s1"} for i, h in enumerate([5, 99, 42])]
    st = build_replay_state(frame=_frame(), rows=rows, analysis_by_code={},
                            sentiment_doc=_sentiment(FULL_COUNTS), prev_counts=None, prev_codes=set())
    assert [s["n"] for s in st["stocks"]] == ["s1", "s2", "s0"]  # heat 降序
    assert len(st["stocks"]) == 3


def test_limit_evidence_fallback_and_narrative():
    """8 月老帧无 marketStats → limitEvidence 兜底；narrative 由存在字段生成。"""
    frame = _frame(market_stats={})  # 老帧：marketStats 空
    sent = {**_sentiment(FULL_COUNTS),
            "metrics": {"layers": {"top50": {"stageCounts": FULL_COUNTS}},
                        "limitEvidence": {"market": {"ztCount": 39, "zhabanCount": 13,
                                                     "board1": 26, "board2": 10, "board3": 1,
                                                     "board4Plus": 2, "maxContinuousDays": 4}}}}
    st = build_replay_state(frame=frame, rows=[], analysis_by_code={}, sentiment_doc=sent,
                            prev_counts=None, prev_codes=set())
    assert st["market"]["zt"] == 39
    assert st["market"]["zhabanRate"] == round(13 / 52 * 100, 1)   # 25.0
    assert st["market"]["promotionRate"] == round(13 / 26, 3)
    assert st["market"]["maxBoard"] == 4
    assert "涨停39家" in st["narrative"] and "炸板率25.0%" in st["narrative"]


def test_stock_config_narrative():
    from backend.analysis.hotlist.jev_state import build_stock_config_narrative
    analysis = {"resonance": {"score": 45.2, "label": "较弱", "direction": "sell",
                              "relativeMomentum": -0.78, "acceleration": -0.99},
                "technical": {"movingAverage": {"trend": "down"},
                              "macd": {"cross": "death", "confirmed": True}},
                "cycle": {"stage": "cooling", "transition": "cooling", "confidence": 90,
                          "metrics": {"rankVelocity": -12.1}},
                "themeMomentum": {"themeName": "高股息", "score": 53.8, "direction": "neutral",
                                  "phaseLabel": "中性"},
                "decision": {"final": {"signal": "sell", "confidence": 45.2}},
                "observation": {"rankTrend": {"signalTier": "D", "tierReasons": ["趋势转弱/反向"]}}}
    row = {"code": "000592", "name": "平潭发展", "rank": 3}
    s = build_stock_config_narrative(analysis, row)
    assert "平潭发展" in s and "热榜第3" in s
    assert "共振" in s and "45.2" in s and "MACD" in s and "死叉" in s
    assert "cooling" in s and "高股息" in s and "D" in s


def test_stock_config_narrative_partial_missing():
    from backend.analysis.hotlist.jev_state import build_stock_config_narrative
    s = build_stock_config_narrative({"resonance": {"score": 70.0, "label": "强", "direction": "buy"}}, {"name": "X"})
    assert "共振" in s and "70" in s and "MACD" not in s  # 缺技术维则跳过该行，不伪造
