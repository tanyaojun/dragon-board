# -*- coding: utf-8 -*-
"""jev 构建器测试（阶段3 驱动打标保留件；阶段1/2 测试随证伪清理移除，见 git 历史）。

2026-10-08 观察轨道 v3（hotlist-jev-emotion-observe-design.md）：
证据聚合器 + 双问题常量 + 槽位/日级叙事构建器测试。零规则输出、零预测问。"""
import json

from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS,
    JEV_SLOT_QUESTIONS,
    build_day_jev_state,
    build_driver_label_narrative,
    build_slot_jev_state,
    collect_slot_evidence,
)


# ── 观察轨道 v3：questions 常量 ──


def test_questions_constants_frozen_no_prediction():
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


def test_driver_label_narrative():
    mappings = [{"themeName": "AI影视", "tags": ["视频数据"], "reason": "图片数据资源类国内第一"},
                {"themeName": "上海国资", "tags": ["地方国资"], "reason": "上海国资背景"}]
    s = build_driver_label_narrative("首部AI电影上映+《三星堆：未来往事》",
                                     {"name": "新华传媒", "rank": 2, "mainTheme": "AI应用"},
                                     mappings)
    assert "新华传媒" in s and "首部AI电影上映" in s
    assert "AI影视" in s and "图片数据资源类国内第一" in s and "上海国资" in s
    assert "AI应用" in s


def test_driver_label_narrative_object_tags():
    mappings = [{"themeName": "AI影视", "tags": [{"Name": "视频数据"}], "reason": "图片数据资源类国内第一"}]
    s = build_driver_label_narrative("首部AI电影上映", {"name": "新华传媒", "rank": 2}, mappings)
    assert "标签:视频数据" in s


def test_driver_label_narrative_no_mapping():
    s = build_driver_label_narrative("算力租赁概念", {"name": "X股"}, [])
    assert "无题材映射记录" in s and "算力租赁概念" in s
