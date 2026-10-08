# -*- coding: utf-8 -*-
"""链切换测试（路线 B T2，emotion-score-design v3 §5.1）：

档位主定义切换为评分驱动——stage/rawStage 来自 score 映射（含 slope），确认复用
confirm_stage 滞回（S1 零改动）；legacyCascadeStage 保留级联截面作对照；score=None
采用方案 B（rawStage/stage=null + 确认跳过 + 结构化诊断，审计 B4）；stageCandidate
与 rawStage 同值（S10）。"""
from __future__ import annotations

from backend.operations.hotlist_sentiment import build_hotlist_sentiment_document

_STAGES = {"冰点", "启动", "发酵", "高潮", "退潮"}


def _frame(slot: str, *, with_limit: bool = True) -> dict:
    frame: dict = {
        "snapshotId": f"snap-{slot}", "slotTime": slot, "timestamp": 1757000000,
        "indices": {"totalAmount": {"amount": 1.2e12}},  # 当日累计两市成交额（量能同期基线）
    }
    if with_limit:
        frame["limitSummary"] = {
            "continuousBoards": {"yiban": 40, "erban": 18, "sanban": 7, "sibanPlus": 3, "maxBoard": 6},
            "zhaban": {"count": 12, "rate": 15.0, "ztCount": 68},
        }
    return frame


def _bull_stocks() -> list[dict]:
    """强多小池：20 涨（10 涨停）+ 2 跌，upRatio/trin/yhPositive 全高位。"""
    rows: list[dict] = []
    for i in range(10):
        rows.append({"code": f"ZT{i:03d}", "name": f"涨停{i}", "rank": i + 1,
                     "change": 10.0, "pctChange": 10.0, "price": 9.66, "limitUpPrice": 9.66,
                     "turnover": 1.2e8})
    for i in range(10):
        rows.append({"code": f"UP{i:03d}", "name": f"涨{i}", "rank": 20 + i,
                     "change": float(3 + i % 5), "pctChange": float(3 + i % 5),
                     "turnover": 8e7})
    for i in range(2):
        rows.append({"code": f"DN{i:03d}", "name": f"跌{i}", "rank": 90 + i,
                     "change": -2.0 - i, "pctChange": -2.0 - i, "turnover": 1e7})
    return rows


def _bull_analysis() -> dict:
    """12 行点火/扩散（displayStatus.stage + cycle.stage 同步注入）。"""
    analysis: dict = {}
    for i in range(8):
        analysis[f"ZT{i:03d}"] = {"displayStatus": {"stage": "ignition"}, "cycle": {"stage": "ignition"}}
    for i in range(4):
        analysis[f"UP{i:03d}"] = {"displayStatus": {"stage": "expansion"}, "cycle": {"stage": "expansion"}}
    return analysis


def _yesterday_rows() -> list[dict]:
    return [
        {"code": "Y001", "change": 10.0, "pctChange": 10.0, "price": 8.78, "limitUpPrice": 8.78},
        {"code": "Y002", "change": 10.0, "pctChange": 10.0, "price": 5.5, "limitUpPrice": 5.5},
    ]


def _bear_stocks() -> list[dict]:
    """强空小池：18 跌（reversal join）+ 1 弱涨；upRatio/attack/trin/risk 全指向弱势。"""
    rows: list[dict] = []
    for i in range(18):
        rows.append({"code": f"DN{i:03d}", "name": f"跌{i}", "rank": i + 1,
                     "change": -4.0 - i % 4, "pctChange": -4.0 - i % 4, "turnover": 5e7})
    rows.append({"code": "UP001", "name": "独涨", "rank": 99, "change": 1.0, "pctChange": 1.0,
                 "turnover": 2e6})
    return rows


def _bear_analysis() -> dict:
    return {f"DN{i:03d}": {"displayStatus": {"stage": "reversal"}, "cycle": {"stage": "reversal"}}
            for i in range(18)}


def _weak_yesterday_rows() -> list[dict]:
    """昨日涨停今日弱承接（positiveRate 低）。"""
    return [
        {"code": "Y001", "change": -3.0, "pctChange": -3.0, "price": 8.0, "limitUpPrice": 8.78},
        {"code": "Y002", "change": 1.0, "pctChange": 1.0, "price": 5.6, "limitUpPrice": 5.5},
        {"code": "Y003", "change": -5.0, "pctChange": -5.0, "price": 4.0, "limitUpPrice": 4.4},
        {"code": "Y004", "change": 0.5, "pctChange": 0.5, "price": 6.0, "limitUpPrice": 6.0},
    ]


def _build(slot: str, *, stocks: list[dict] | None = None, stage_history: dict | None = None,
           yesterday_rows: list[dict] | None = None, analysis_by_code: dict | None = None,
           yesterday_amounts: dict | None = None, with_limit: bool = True) -> dict:
    return build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-09-30",
        frame=_frame(slot, with_limit=with_limit), stocks=_bull_stocks() if stocks is None else stocks,
        slot_time=slot, current_slot=slot, stage_history=stage_history,
        yesterday_rows=yesterday_rows, analysis_by_code=analysis_by_code,
        yesterday_amounts=yesterday_amounts,
    )


def test_document_stage_is_score_driven_with_embedded_emotion_score():
    doc = _build("10:30", stocks=_bull_stocks(), yesterday_rows=_yesterday_rows(),
                 analysis_by_code=_bull_analysis(), yesterday_amounts={"10:30": 1.0e12})
    emotion = doc["emotionScore"]
    assert emotion["score"] is not None and 0 <= emotion["score"] <= 100
    # 可分解：等权合成可从 dims 还原
    subs = [v["sub"] for v in emotion["dims"].values()]
    assert abs(emotion["score"] - sum(subs) / len(subs)) < 0.15
    assert "amountVsSame" not in emotion["skippedDims"]  # 第八维永久退役（2026-10-08 研究轮出口 b）：不入分不入 skipped；原料照采走 record 步
    # 档位主定义 = 评分映射（强多证据 ≥ 发酵）
    assert emotion["score"] >= 60
    assert doc["rawStage"] == emotion["stageCandidate"]  # S10 同值
    assert doc["rawStage"] in _STAGES and doc["rawStage"] != "冰点"
    # 当日首槽：确认直通（confirm_stage 第一条截面直接确认）
    assert doc["stage"] == doc["rawStage"]
    # 对照面：legacyCascadeStage 仍是级联截面五档（与评分档位可不同）
    assert doc["legacyCascadeStage"] in _STAGES
    assert doc["stageConfirmState"]["historyStatus"] == "empty"


def test_document_confirmation_absorbs_single_slot_crossing():
    """确认复用零改动（S1）：候选档位 1 槽不切换，单槽越界被吸收（pending 可见）。"""
    history = {
        "rawStagePoints": [("09:30", "启动"), ("10:00", "启动")],
        "scorePoints": [("09:30", 45.0), ("10:00", 46.0)],
        "historyStatus": "complete",
        "diagnostics": [],
    }
    doc = _build("10:30", stocks=_bull_stocks(), yesterday_rows=_yesterday_rows(),
                 analysis_by_code=_bull_analysis(), stage_history=history)
    assert doc["rawStage"] != "启动"  # 本帧评分已走高
    assert doc["stage"] == "启动"  # 2 槽阈值下候选未确认
    state = doc["stageConfirmState"]
    assert state["pending"] is True and state["pendingStage"] == doc["rawStage"]
    assert state["pendingSince"] == "10:30"


def test_document_slope_wiring_retreat_vs_ice():
    """B2 斜率接线：低分 + 负斜率 → 退潮；prev 缺失（首槽）→ 冰点；prev 缺失且有当日
    历史文档 → 诊断 emotion_slope_unavailable。"""
    bear = _bear_stocks()
    ice = _build("10:30", stocks=bear, with_limit=False, yesterday_rows=_weak_yesterday_rows(),
                 analysis_by_code=_bear_analysis())
    assert ice["emotionScore"]["score"] is not None and ice["emotionScore"]["score"] < 40
    assert ice["emotionScore"]["slope"] is None  # 当日首槽无 prev
    assert ice["rawStage"] == "冰点" and ice["stage"] == "冰点"
    assert not any(d.startswith("emotion_slope_unavailable") for d in ice["diagnostics"])

    declining = _build("10:30", stocks=bear, with_limit=False, yesterday_rows=_weak_yesterday_rows(),
                       analysis_by_code=_bear_analysis(), stage_history={
        "rawStagePoints": [("09:30", "启动")],
        "scorePoints": [("09:30", 55.0)],
        "historyStatus": "complete", "diagnostics": [],
    })
    assert declining["emotionScore"]["slope"] is not None and declining["emotionScore"]["slope"] < 0
    assert declining["rawStage"] == "退潮"

    missing_prev = _build("10:30", stocks=bear, with_limit=False, yesterday_rows=_weak_yesterday_rows(),
                          analysis_by_code=_bear_analysis(), stage_history={
        "rawStagePoints": [("09:30", "启动")],  # 有历史文档但无 emotionScore（旧文档混合态）
        "scorePoints": [],
        "historyStatus": "complete", "diagnostics": [],
    })
    assert missing_prev["rawStage"] == "冰点"
    assert any(d == "emotion_slope_unavailable:prev_score_missing" for d in missing_prev["diagnostics"])


def test_document_score_none_semantics_plan_b():
    """B4 方案 B：stocks 空 → score=None → rawStage/stage=null、确认跳过、结构化诊断、
    不出现字符串 "None"；级联伪值只存 legacyCascadeStage 对照面。"""
    doc = _build("10:30", stocks=[], with_limit=False)
    assert doc["emotionScore"]["score"] is None
    assert doc["rawStage"] is None and doc["stage"] is None
    assert doc["legacyCascadeStage"] in _STAGES  # 级联缺证输出降级伪值（冰点），仅对照
    assert any(d.startswith("emotion_score_unavailable") for d in doc["diagnostics"])
    assert set(doc["emotionScore"]["skippedDims"]) == {
        "upRatio", "attackShare", "riskShare", "trin", "yhPositive",
        "limitStruct", "riskRowsPct"}
    # 有确认历史时 score=None 槽不破坏已确认档位（重放跳过）
    doc2 = _build("10:30", stocks=[], with_limit=False, stage_history={
        "rawStagePoints": [("09:30", "启动"), ("10:00", "启动")],
        "scorePoints": [("09:30", 45.0), ("10:00", 46.0)],
        "historyStatus": "complete", "diagnostics": [],
    })
    assert doc2["stage"] == "启动" and doc2["rawStage"] is None

    # review 阻塞项回归：unavailable × score=None 组合——本帧 None 点同样不得进确认序列
    #（str(None)="None" 会穿透 confirm_stage 空串过滤，伪造字符串档位）
    doc3 = _build("10:30", stocks=[], with_limit=False, stage_history={
        "rawStagePoints": [], "scorePoints": [],
        "historyStatus": "unavailable", "diagnostics": ["stage_confirm_history_unavailable:RuntimeError:boom"],
    })
    assert doc3["rawStage"] is None
    assert doc3["stage"] is None  # 绝不为字符串 "None"
    assert doc3["stageConfirmState"]["historyStatus"] == "unavailable"


def test_document_eod_uses_anchored_slot_for_evidence():
    """EOD 文档（slot_time=None）：评分证据槽位 = 锚定帧槽位。"""
    doc = build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-09-30",
        frame=_frame("15:00"), stocks=_bull_stocks(),
        yesterday_rows=_yesterday_rows(), analysis_by_code=_bull_analysis(),
        yesterday_amounts={"15:00": 1.0e12},
    )
    assert doc["slotTime"] == "EOD"
    assert doc["emotionScore"]["score"] is not None
    # 第八维永久退役（2026-10-08 研究轮出口 b）：EOD 锚定槽 wiring 不变；
    # 退役维不入 dims/skippedDims，原料照采走 record 步
    assert "amountVsSame" not in doc["emotionScore"]["skippedDims"]
    assert "amountVsSame" not in doc["emotionScore"]["dims"]


# ── 方向一+①（2026-10-05 用户裁决）：activeDims 维度基数戳 + pathDiag 路径诊断 + limitStruct 诊断行 ──

def test_document_emotion_score_active_dims_baseline():
    """activeDims = 7 − len(skippedDims)：跨日可比性的维度基数戳。
    fixture 边界：_yesterday_rows 无涨停证据行 → yhPositive 恒 skip；第八维已永久退役
    （2026-10-08 研究轮出口 b）→ 总维数 7、基线 6 维。"""
    full = _build("10:30", stocks=_bull_stocks(), yesterday_rows=_yesterday_rows(),
                  analysis_by_code=_bull_analysis(), yesterday_amounts={"10:30": 1.0e12})
    assert full["emotionScore"]["skippedDims"] == ["yhPositive"]
    assert full["emotionScore"]["activeDims"] == 6

    partial = _build("10:30", stocks=_bull_stocks(), yesterday_rows=_yesterday_rows(),
                     analysis_by_code=_bull_analysis())  # 无 yesterday_amounts：退役后与 full 同基线
    assert set(partial["emotionScore"]["skippedDims"]) == {"yhPositive"}
    assert partial["emotionScore"]["activeDims"] == 6

    empty = _build("10:30", stocks=[], with_limit=False)
    assert empty["emotionScore"]["score"] is None
    assert empty["emotionScore"]["activeDims"] == 0  # 全 skip（7−7）


def test_document_emotion_score_path_diag_directional_semantics():
    """pathDiag 路径诊断（方向一，纯诊断不进档位链）：日内极值+自高点回撤+自低点反弹，
    序列=严格早于当前槽的 scorePoints + 当前槽。回落中（drawdown<0）与修复后（bounce>0）可判。"""
    rising = _build("10:30", stocks=_bull_stocks(), yesterday_rows=_yesterday_rows(),
                    analysis_by_code=_bull_analysis(), stage_history={
        "rawStagePoints": [("09:30", "启动"), ("10:00", "启动")],
        "scorePoints": [("09:30", 45.0), ("10:00", 46.0)],
        "historyStatus": "complete", "diagnostics": [],
    })
    diag = rising["emotionScore"]["pathDiag"]
    current = rising["emotionScore"]["score"]
    assert diag["dayHigh"]["score"] == current  # 当前即日内高点（爬升中）
    assert diag["dayLow"]["score"] == 45.0 and diag["dayLow"]["slotTime"] == "09:30"
    assert diag["drawdownFromHigh"] == 0
    assert diag["bounceFromLow"] == round(current - 45.0, 1)
    assert diag["points"] == 3

    falling = _build("10:30", stocks=_bear_stocks(), with_limit=False,
                     yesterday_rows=_weak_yesterday_rows(), analysis_by_code=_bear_analysis(),
                     stage_history={
        "rawStagePoints": [("09:30", "启动")],
        "scorePoints": [("09:30", 55.0)],
        "historyStatus": "complete", "diagnostics": [],
    })
    fdiag = falling["emotionScore"]["pathDiag"]
    assert fdiag["dayHigh"]["score"] == 55.0 and fdiag["dayHigh"]["slotTime"] == "09:30"
    assert fdiag["drawdownFromHigh"] < 0  # 回落中：当前低于日内高点
    assert fdiag["dayLow"]["score"] == falling["emotionScore"]["score"]  # 当前即低点

    # score=None（方案 B）→ pathDiag=None 不伪造
    none_doc = _build("10:30", stocks=[], with_limit=False)
    assert none_doc["emotionScore"]["pathDiag"] is None


def test_document_limitstruct_skip_diagnostic_line():
    """limitStruct skip 且 score 有效 → 结构化诊断行（fail-visible，与炸板缺失行同风格）。"""
    doc = _build("10:30", stocks=_bull_stocks(), yesterday_rows=_yesterday_rows(),
                 analysis_by_code=_bull_analysis())  # 无 with_limit=False 之外的手段——用 with_limit=False
    # 上例 limit 在场；构造缺失：with_limit=False
    missing = _build("10:30", stocks=_bull_stocks(), with_limit=False,
                     yesterday_rows=_yesterday_rows(), analysis_by_code=_bull_analysis())
    assert "limitStruct" in missing["emotionScore"]["skippedDims"]
    assert any(d.startswith("emotion_limitstruct_unavailable") for d in missing["diagnostics"])
    # limit 在场 → 无该诊断行
    assert not any(d.startswith("emotion_limitstruct_unavailable") for d in doc["diagnostics"])


def test_document_eod_path_direction_vs_slot(monkeypatch):
    """B+C 预登记（2026-10-08）wiring：EOD 档方向判别消费 pathDiag.dd，盘中槽不消费。

    场景=尾盘反抽日：日内 75→50，EOD 50/末步 slope 0（构造 history 末点=50）——
    EOD dd=−25 命中退潮（旧规则 slope=0 判启动=误判）；同数据 10:30 槽位保持末步差分语义。
    """
    import backend.analysis.hotlist.emotion_score as es_mod
    monkeypatch.setattr(es_mod, "compute_emotion_score",
                        lambda ev, slope=None: {"score": 50.0, "dims": {}, "skippedDims": [],
                                                "stageCandidate": None})
    history = {"rawStagePoints": [("09:30", "发酵"), ("10:00", "发酵")],
               "scorePoints": [("09:30", 75.0), ("10:00", 50.0)],
               "historyStatus": "complete", "diagnostics": []}
    eod = build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-10-08",
        frame=_frame("15:00"), stocks=_bull_stocks(), stage_history=history)
    assert eod["slotTime"] == "EOD"
    assert eod["emotionScore"]["pathDiag"]["drawdownFromHigh"] == -25.0
    assert eod["rawStage"] == "退潮"  # dd≤−8 接管（B 目标场景）
    slot = build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-10-08",
        frame=_frame("10:30"), stocks=_bull_stocks(), slot_time="10:30",
        current_slot="10:30", stage_history=history)
    assert slot["rawStage"] == "启动"  # 盘中槽 path=None：末步差分语义零变化
    # wiring 自洽：档位 ≡ 自身 emotionScore 字段重放（EOD 带 dd，槽位不带）
    es = eod["emotionScore"]
    assert eod["rawStage"] == es_mod.map_stage(es["score"], es["slope"],
                                               {"dd": es["pathDiag"]["drawdownFromHigh"]})
    ss = slot["emotionScore"]
    assert slot["rawStage"] == es_mod.map_stage(ss["score"], ss["slope"], None)
