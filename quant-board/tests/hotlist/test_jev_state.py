# -*- coding: utf-8 -*-
"""jev 构建器测试（阶段3 驱动打标保留件；阶段1/2 测试随证伪清理移除，见 git 历史）。

2026-10-08 观察轨道 v3（hotlist-jev-emotion-observe-design.md）：
证据聚合器 + 双问题常量 + 槽位/日级叙事构建器测试。零规则输出、零预测问。"""
import json

from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS,
    JEV_SLOT_QUESTIONS,
    build_day_jev_state,
    build_history_anchor,
    build_slot_jev_state,
    collect_slot_evidence,
    extract_history_anchor_range,
)


# ── 观察轨道 v3：questions 常量 ──


def test_questions_constants_frozen_no_prediction():
    # 2026-10-02 V1 退役：题目常量唯一来源=V2（单一事实源）
    assert set(JEV_SLOT_QUESTIONS) == {"frame_stage", "sequence_stage", "temperature", "crowding"}
    assert set(JEV_DAY_QUESTIONS) == {"day_stage", "day_pattern", "day_temperature", "day_crowding"}
    for questions in (JEV_SLOT_QUESTIONS, JEV_DAY_QUESTIONS):
        assert len(questions) == 4
        assert all(q["type"] in ("choice", "score") for q in questions.values())
        assert "noul" not in json.dumps(questions, ensure_ascii=False)
        for question in questions.values():
            if question["type"] == "choice":
                assert isinstance(question["criteria"], dict) and len(question["criteria"]) >= 5
            else:
                assert isinstance(question["criteria"], list) and len(question["criteria"]) == 10


# ── 观察轨道 v3：证据聚合器 ──


def _v3_frame():
    return {
        "indices": {"sh": {"change": -12.2}, "zz500": {"change": -23.4},
                     "totalAmount": {"amount": 1.41e12}},
        "limitSummary": {
            "continuousBoards": {"yiban": 40, "erban": 18, "sanban": 7, "sibanPlus": 3, "maxBoard": 6},
            "zhaban": {"count": 12, "rate": 15.0, "fengbanRate": 85.0, "ztCount": 68},
        },
    }


def _v3_rows():
    # sentiment 链行字段口径：change = pctChange（涨跌幅）；turnover = 成交额
    return [
        {"code": "000001", "name": "甲", "rank": 1, "heat": 99, "pctChange": 9.98, "change": 9.98,
         "price": 9.66, "limitUpPrice": 9.66, "mainTheme": "算力", "reason": "算力租赁",
         "turnover": 1.2e8, "zlje": 5.0e6, "zljzb": 9.0},
        {"code": "000002", "name": "乙", "rank": 2, "heat": 90, "pctChange": 6.0, "change": 6.0,
         "price": 5.0, "limitUpPrice": None, "mainTheme": "固态电池", "turnover": 3.0e7},
        {"code": "000003", "name": "丙", "rank": 3, "heat": 80, "pctChange": 3.0, "change": 3.0,
         "mainTheme": "AI应用", "turnover": 2.0e7},
        {"code": "000004", "name": "丁", "rank": 4, "heat": 70, "pctChange": -1.0, "change": -1.0,
         "turnover": 5.0e7},
        {"code": "000005", "name": "戊", "rank": 5, "heat": 60, "pctChange": -6.0, "change": -6.0,
         "turnover": 8.0e7},
        {"code": "000006", "name": "己", "rank": 6, "heat": 50, "pctChange": None, "change": None,
         "zlje": None},
        {"code": "000007", "name": "庚", "rank": 7, "heat": 40, "pctChange": 1.0, "change": 1.0,
         "turnover": 1.0e7, "zlje": 5.0e6},
        {"code": "000008", "name": "辛", "rank": 8, "heat": 30, "pctChange": 2.0, "change": 2.0,
         "turnover": 1.5e7, "zlje": -3.0e6},
    ]


def _v3_analysis():
    # 甲=强资确认（cooling + zlje>0 + zljzb≥8 + 量能 tierA）；丁=风险（reversal）
    return {
        "000001": {"displayStatus": {"stage": "cooling"},
                    "cycle": {"stage": "cooling"},
                    "observation": {"volumePrice": {"signalTier": "A"}}},
        "000002": {"displayStatus": {"stage": "expansion"},
                    "cycle": {"stage": "expansion"}},
        "000004": {"displayStatus": {"stage": "reversal"},
                    "cycle": {"stage": "reversal"}},
    }


def _v3_yesterday_rows():
    # sentiment 链行字段口径：change = 涨跌幅（check_limit_status 阈值判据）
    return [
        {"code": "000001", "name": "甲", "pctChange": 10.0, "change": 10.0,
         "price": 8.78, "limitUpPrice": 8.78},
        {"code": "999999", "name": "昨日只有它", "pctChange": 10.0, "change": 10.0,
         "price": 3.3, "limitUpPrice": 3.3},
    ]


def test_collect_slot_evidence_shape():
    ev = collect_slot_evidence(
        frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=_v3_yesterday_rows(),
        analysis_by_code=_v3_analysis(), slot_time="10:30",
        yesterday_same_slot_total_amount=1.0e12)
    assert ev["slotTime"] == "10:30"
    assert ev["indices"] == {"sh": -12.2, "zz500": -23.4}
    assert ev["limit"]["ztCount"] == 68 and ev["limit"]["maxBoard"] == 6
    assert ev["limit"]["zhabanRate"] == 15.0 and ev["limit"]["zhabanCount"] == 12
    breadth = ev["breadth"]
    assert breadth["total"] == 8 and breadth["limitUp"] == 1 and breadth["up5"] == 1
    assert breadth["up0"] == 3 and breadth["down0"] == 1 and breadth["down5"] == 1
    assert breadth["pctMissing"] == 1
    fund = ev["fund"]
    assert fund["zljeSum"] == 7.0e6 and fund["zljePos"] == 2 and fund["zljeNeg"] == 1
    assert fund["zljeMissing"] == 5
    # TRIN：(5/2)/(1.95亿/1.3亿) = 2.5/1.5 ≈ 1.667（涨势缩量背离）
    assert abs(ev["breadth"]["trin"] - 1.667) < 0.001
    assert ev["breadth"]["upTurnover"] == 1.95e8 and ev["breadth"]["downTurnover"] == 1.3e8
    assert ev["turnover"]["newCount"] == 7 and ev["turnover"]["droppedCount"] == 1
    assert ev["yesterdayLimit"] is not None and ev["yesterdayLimit"]["count"] >= 1
    lifecycle = ev["lifecycle"]
    assert lifecycle["ignition"] == 0 and lifecycle["expansion"] == 1 and lifecycle["cooling"] == 1
    assert lifecycle["reversal"] == 1 and lifecycle["unknown"] == 0 and ev["lifecycleMissing"] == 5
    # 强资确认（甲 cooling+tierA+zlje/zljzb 达标）与风险预警（丁 reversal）各 1，可判定 3 行
    assert ev["rowFlags"] == {"strongMoney": 1, "risk": 1, "judgeable": 3}
    leader = ev["leaders"][0]
    assert leader["name"] == "甲" and leader["zt"] is True and leader["stage"] == "cooling"
    assert ev["reasons"][0] == ["算力租赁", 1]
    assert ev["quality"]["degradedSources"] == []


def test_collect_slot_evidence_degrades_not_fabricates():
    ev = collect_slot_evidence(
        frame=None, rows=[{"code": "X", "pctChange": None}], yesterday_rows=[],
        analysis_by_code={}, slot_time="10:00")
    degraded = " ".join(ev["quality"]["degradedSources"])
    assert "指数缺失" in degraded and "涨停证据缺失" in degraded and "昨日行缺失" in degraded
    assert ev["fund"]["zljeSum"] is None and ev["fund"]["zljeMissing"] == 1
    assert ev["turnover"]["newCount"] is None and ev["turnover"]["droppedCount"] is None
    assert ev["breadth"]["trin"] is None  # 单行且无方向对比，不可算
    assert ev["yesterdayLimit"] is None
    assert ev["lifecycleMissing"] == 1


def _v3_frame_without_total_amount():
    """历史帧形态：indices 无 totalAmount（该字段 09-30 才接线）。"""
    frame = _v3_frame()
    frame["indices"] = {k: v for k, v in frame["indices"].items() if k != "totalAmount"}
    return frame


def test_collect_slot_evidence_total_amount_fallback_for_1500():
    """15:00 槽=全日累计：历史帧缺 totalAmount 时回退 market_daily_amount 参考（重算冲掉根治），
    amount 生效 + source 标记来源 + degraded 记录回退事实（fail-visible）。"""
    ev = collect_slot_evidence(
        frame=_v3_frame_without_total_amount(), rows=_v3_rows(), yesterday_rows=[],
        analysis_by_code={}, slot_time="15:00", daily_total_amount_fallback=1.9e12)
    ta = ev["totalAmount"]
    assert ta["amount"] == 1.9e12
    assert ta["source"] == "market_daily_amount_reference"
    assert ta["vsSamePct"] is None and ta["yesterdaySame"] is None
    assert any("回退" in s for s in ev["quality"]["degradedSources"])


def test_collect_slot_evidence_total_amount_fallback_not_for_intraday_slots():
    """非 15:00 槽的盘中累计无法用日额近似 → 回退不生效，保持 None（不伪造）。"""
    ev = collect_slot_evidence(
        frame=_v3_frame_without_total_amount(), rows=_v3_rows(), yesterday_rows=[],
        analysis_by_code={}, slot_time="10:30", daily_total_amount_fallback=1.9e12)
    assert ev["totalAmount"]["amount"] is None
    assert ev["totalAmount"]["source"] is None
    assert any("两市总成交额缺失" in s for s in ev["quality"]["degradedSources"])


def test_collect_slot_evidence_live_total_amount_wins_over_fallback():
    """帧自带 totalAmount（09-30+ 活帧）→ 活数据优先，source=None，无回退记录。"""
    ev = collect_slot_evidence(
        frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=[],
        analysis_by_code={}, slot_time="15:00", daily_total_amount_fallback=9.9e12)
    assert ev["totalAmount"]["amount"] == 1.41e12
    assert ev["totalAmount"]["source"] is None
    assert not any("回退" in s for s in ev["quality"]["degradedSources"])


def test_collect_slot_evidence_change_fallback_for_legacy_rows():
    """2026-07-03 前导入的历史行无 pctChange 只有 change（校准重放 T1.5 实证）：
    字段回退后涨跌分布/TRIN 可算，回退行数 fail-visible 进 degradedSources。"""
    rows = [
        {"code": "A", "change": 9.98, "price": 9.66, "limitUpPrice": 9.66, "turnover": 1.2e8},
        {"code": "B", "change": -2.0, "turnover": 3.0e7},
        {"code": "C", "change": None},  # 两字段都缺 → pctMissing，不伪造
    ]
    ev = collect_slot_evidence(frame=_v3_frame(), rows=rows, yesterday_rows=[],
                               analysis_by_code={}, slot_time="10:00")
    breadth = ev["breadth"]
    assert breadth["limitUp"] == 1 and breadth["up0"] == 0 and breadth["down0"] == 1
    assert breadth["pctMissing"] == 1
    assert "pctChange 缺失 2 行（回退 change）" in " ".join(ev["quality"]["degradedSources"])


def test_collect_slot_evidence_trin_one_sided_is_none():
    rows = [{"code": "A", "pctChange": 5.0, "change": 5.0, "turnover": 1.0e7}]
    ev = collect_slot_evidence(frame=_v3_frame(), rows=rows, yesterday_rows=[],
                               analysis_by_code={}, slot_time="10:00")
    assert ev["breadth"]["trin"] is None  # 跌向无数据（单边），不发明数值


def test_collect_slot_evidence_zt_count_from_boards_when_zhaban_missing():
    frame = {"indices": {}, "limitSummary": {"continuousBoards": {"yiban": 40, "erban": 18, "sanban": 7, "sibanPlus": 3, "maxBoard": 6}}}
    ev = collect_slot_evidence(frame=frame, rows=[], yesterday_rows=[], analysis_by_code={}, slot_time="09:30")
    assert ev["limit"]["ztCount"] == 68
    assert "指数缺失" in " ".join(ev["quality"]["degradedSources"])


# ── 观察轨道 v3：槽位/日级叙事构建器 ──


def _v3_current_evidence():
    return collect_slot_evidence(
        frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=_v3_yesterday_rows(),
        analysis_by_code=_v3_analysis(), slot_time="10:30",
        yesterday_same_slot_total_amount=1.0e12)


def test_build_slot_jev_state_full_shape():
    prior = collect_slot_evidence(
        frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=_v3_yesterday_rows(),
        analysis_by_code=_v3_analysis(), slot_time="10:00",
        yesterday_same_slot_total_amount=1.0e12)
    s = build_slot_jev_state(
        trading_date="2026-10-08", slot_time="10:30",
        current=_v3_current_evidence(), priors=[prior])
    assert "2026-10-08 10:30" in s and "【当前帧证据】" in s and "【当日已走帧证据】" in s and "【数据质量】" in s
    assert "沪指 -12.20点" in s and "中证500 -23.40点" in s
    assert "涨停 68" in s and "最高 6 连板" in s and "炸板率 15%" in s
    assert "热榜TRIN：1.67" in s and "量价背离" in s
    assert "TRIN 1.67" in s  # 压缩行也携带
    assert "量能同期+41%" in s  # 压缩行携带同期量能
    assert "指数与量能：" in s and "两市总成交额 +14100.00亿（较昨日同期放量 41%）" in s  # 指数×量能同行
    assert "资金确认 1 只" in s and "占可判定 33%" in s  # 行级标记带占比（跨日可比）
    assert "风险预警 1 只" in s
    assert "强资1·风险1" in s  # 压缩行携带
    assert "新进 7" in s and "淘汰 1" in s
    assert "主力净额" in s and "+0.07亿" in s
    assert "昨涨停承接" in s
    assert "点火 0" in s and "扩散 1" in s and "冷却 1" in s
    assert "甲" in s and "算力" in s and "涨停" in s and "点火" in s
    assert "10:00｜" in s  # 压缩行进入已走帧段
    assert "无缺失" in s
    assert len(s) <= 4000


def test_build_slot_jev_state_missing_sources_and_slots():
    deg = collect_slot_evidence(frame=None, rows=[], yesterday_rows=[], analysis_by_code={}, slot_time="10:30")
    s = build_slot_jev_state(
        trading_date="2026-10-08", slot_time="10:30", current=deg, priors=[],
        missing_slots=["09:30", "10:00"])
    assert "缺失" in s and "09:30" in s and "10:00" in s
    assert "无缺失" not in s.split("【数据质量】")[-1]


def test_build_slot_jev_state_no_rule_output():
    s = build_slot_jev_state(
        trading_date="2026-10-08", slot_time="10:30",
        current=_v3_current_evidence(), priors=[])
    assert "确认阶段" not in s and "规则摘要" not in s and "rawStage" not in s


def test_build_day_jev_state_full_shape():
    evidences = [
        collect_slot_evidence(frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=_v3_yesterday_rows(),
                              analysis_by_code=_v3_analysis(), slot_time="09:30"),
        _v3_current_evidence(),
    ]
    s = build_day_jev_state(trading_date="2026-10-08", evidences=evidences)
    assert "2026-10-08" in s and "【逐帧证据】" in s
    assert "09:30｜" in s and "10:30｜" in s
    assert "【当日累计】" in s and "新进 7" in s and "最高连板峰值 6 板" in s
    assert "【数据质量】" in s and len(s) <= 6000


def test_build_day_jev_state_empty_defensive():
    s = build_day_jev_state(trading_date="2026-10-08", evidences=[])
    assert "无帧证据" in s


# ── 近20日参照锚 + 封板质量/回撤池/09:30 注记（原 v2 判定测试，2026-10-02 归一）──


STATS = [
    {"date": f"2026-08-{d:02d}", "ztCount": 30 + i * 2, "maxBoard": 4 + (i % 3),
     "amountYi": 15000.0 + i * 100, "zhabanRate": 10.0 + i}
    for i, d in enumerate(range(11, 31))
]


def test_history_anchor_percentiles():
    out = build_history_anchor(STATS)
    assert out.startswith("【近20日参照】（2026-08-11 → 2026-08-30，20 个交易日收盘统计")
    assert "涨停数：p20=" in out and "p50=" in out and "p80=" in out
    assert "（2026-08-30 68 家）" in out  # 最后非空样本带实际日期（防陈旧值误标"昨日"）
    assert "最高连板：p20=" in out and "炸板率：p20=" in out


def test_history_anchor_insufficient_sample_fail_visible():
    # 指标样本 <8 → 如实标注，不伪造刻度
    out = build_history_anchor(STATS[:5])
    assert "历史样本不足（5 日）" in out
    assert "p20" not in out.split("\n")[1] or "涨停数 历史样本不足" in out


def test_history_anchor_empty():
    out = build_history_anchor([])
    assert "历史参照缺失" in out and "不得虚构对比" in out


def test_extract_history_anchor_range():
    # 标准首行 → 括号内完整区间（含中文逗号段，前端 split('，')[0] 取日期段）
    assert extract_history_anchor_range(build_history_anchor(STATS)) == \
        "2026-08-11 → 2026-08-30，20 个交易日收盘统计，判读坐标系"
    # 历史参照缺失首行不带（ 前缀 → None（旧定长切片在此错位产出半截句）
    assert extract_history_anchor_range(build_history_anchor([])) is None


def test_slot_narrative_contains_anchor():
    state = build_slot_jev_state(trading_date="2026-09-07", slot_time="09:30",
                                 current={"quality": {"degradedSources": []}}, priors=[],
                                 history_anchor=build_history_anchor(STATS))
    assert "【近20日参照】" in state
    assert "2026-09-07 09:30 时点快照" in state
    # 空 anchor 行被过滤不留双空行
    state2 = build_slot_jev_state(trading_date="2026-09-07", slot_time="09:30",
                                  current={"quality": {"degradedSources": []}}, priors=[])
    assert "【近20日参照】" not in state2


def test_day_narrative_contains_anchor():
    out = build_day_jev_state(trading_date="2026-09-07", evidences=[],
                              history_anchor="【近20日参照】X")
    assert "无帧证据" in out  # 空证据仍是 fail-visible 短路


def test_v2_question_sets_structure():
    # crowding 已离散归层（v2.5 起六选一：拥挤解除单列，不再与 no_crowding 混装；含逃生口）
    assert JEV_SLOT_QUESTIONS["crowding"]["type"] == "choice"
    assert set(JEV_SLOT_QUESTIONS["crowding"]["criteria"]) == {
        "top_acceleration", "late_seal_weakness", "breadth_climax", "crowd_clearing",
        "no_crowding", "insufficient_evidence"}
    assert set(JEV_DAY_QUESTIONS["day_crowding"]["criteria"]) == \
        set(JEV_SLOT_QUESTIONS["crowding"]["criteria"])
    # 拥挤解除判据须锚叙事已给证据（当日早些帧/参照高位），no_crowding 判据带分流指针
    assert "参照高位" in JEV_SLOT_QUESTIONS["crowding"]["criteria"]["crowd_clearing"]
    assert "crowd_clearing" in JEV_SLOT_QUESTIONS["crowding"]["criteria"]["no_crowding"]
    # day_pattern v2.5 起八类：尾盘偷袭单列，low_recover 收窄为盘中修复
    assert set(JEV_DAY_QUESTIONS["day_pattern"]["criteria"]) == {
        "steady_strong", "steady_weak", "rally_fade", "low_recover", "late_rescue",
        "wide_swing", "narrow_range", "unclear"}
    assert "尾盘偷袭" in JEV_DAY_QUESTIONS["day_pattern"]["criteria"]["low_recover"]
    assert "最后一至两帧" in JEV_DAY_QUESTIONS["day_pattern"]["criteria"]["late_rescue"]
    # 温度仍 score 且题干锚定参照系
    assert JEV_SLOT_QUESTIONS["temperature"]["type"] == "score"
    assert "近20日参照" in JEV_SLOT_QUESTIONS["temperature"]["instructions"]
    # 五档判据绑可数证据
    assert "近20日参照低位" in JEV_SLOT_QUESTIONS["frame_stage"]["criteria"]["ice"]
    assert "炸板率" in JEV_SLOT_QUESTIONS["frame_stage"]["criteria"]["retreat"]
    # 2026-10-02 V1 退役：v1 题目常量已随链删除，V2 为唯一题目源


# ── 封板质量/触板回撤池接线 + 09:30 伪 0 注记（2026-10-02 裁决）──────────────────

from backend.analysis.hotlist.jev_state import collect_slot_evidence  # noqa: E402

_SQ_FRAME = {
    "snapshotId": "half_hour:2026-09-29:15:00", "type": "half_hour",
    "tradingDate": "2026-09-29", "slotTime": "15:00",
    "indices": {"sh": {"change": -1.0}},
    "limitSummary": {
        "continuousBoards": {"yiban": 30, "erban": 10, "sanban": 2, "sibanPlus": 1, "maxBoard": 4},
        "zhaban": {"count": 8, "rate": 12.0, "fengbanRate": 88.0, "ztCount": 43},
        "sealQuality": {"byzCount": 25, "hardCount": 10, "rottenCount": 8, "rottenShare": 0.186,
                        "avgSucRate": 0.62},
        "drawdown": {"count": 3, "avgDrawdownPct": 8.5, "deepestDrawdownPct": 12.6},
    },
}

_ROW = {"code": "000001", "name": "甲", "rank": 1, "heat": 90, "pctChange": 9.9,
        "change": 9.9, "price": 9.66, "limitUpPrice": 9.66, "zlje": 3.0e6}


def _slot_narrative(frame, slot_time="15:00"):
    ev = collect_slot_evidence(frame=frame, rows=[dict(_ROW)], yesterday_rows=[],
                               analysis_by_code={}, slot_time=slot_time)
    return build_slot_jev_state(trading_date="2026-09-29", slot_time=slot_time,
                                current=ev, priors=[]), ev


def test_seal_quality_and_drawdown_flow_to_narrative():
    text, ev = _slot_narrative(_SQ_FRAME)
    assert ev["limit"]["sealQuality"]["rottenShare"] == 0.186
    assert ev["limit"]["drawdown"]["count"] == 3
    assert "封板质量：一字/秒板 25 家、硬板 10 家、开板重封 8 家、重封率 19%" in text
    assert "该批个股平均历史封板成功率 62%" in text
    assert "触板回撤池：大幅回撤 3 家、平均回撤 8.5%、最深 12.6%" in text


def test_missing_blocks_absent_not_faked():
    # 帧无 sealQuality/drawdown（历史帧）→ 叙事无该行、evidence 键缺席（fail-visible）
    frame = {k: v for k, v in _SQ_FRAME.items()}
    frame = dict(frame)
    frame["limitSummary"] = {
        "continuousBoards": _SQ_FRAME["limitSummary"]["continuousBoards"],
        "zhaban": _SQ_FRAME["limitSummary"]["zhaban"]}
    text, ev = _slot_narrative(frame)
    assert "sealQuality" not in ev["limit"] and "drawdown" not in ev["limit"]
    assert "封板质量" not in text and "触板回撤池" not in text


def test_0930_pseudo_zero_annotated():
    # 09:30 帧 zt=0（开盘伪 0 形态）→ 叙事带谨慎采信注记；15:00 同值不带
    frame = {
        "snapshotId": "half_hour:2026-09-29:09:30", "type": "half_hour",
        "tradingDate": "2026-09-29", "slotTime": "09:30",
        "indices": {"sh": {"change": -1.0}},
        "limitSummary": {"continuousBoards": {"yiban": 0, "erban": 0, "sanban": 0, "sibanPlus": 0, "maxBoard": 0},
                         "zhaban": {"count": 0, "rate": 0.0, "fengbanRate": 0.0, "ztCount": 0}},
    }
    text, _ = _slot_narrative(frame, slot_time="09:30")
    assert "09:30 开盘时点：涨停池可能未就绪" in text
    text15, _ = _slot_narrative(_SQ_FRAME, slot_time="15:00")
    assert "谨慎采信" not in text15
