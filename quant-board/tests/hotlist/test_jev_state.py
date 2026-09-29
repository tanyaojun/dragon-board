# -*- coding: utf-8 -*-
"""jev 构建器测试（阶段3 驱动打标保留件；阶段1/2 测试随证伪清理移除，见 git 历史）。

2026-10-08 观察轨道 v3（hotlist-jev-emotion-observe-design.md）：
证据聚合器 + 双问题常量 + 槽位/日级叙事构建器测试。零规则输出、零预测问。"""
import json

from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS,
    JEV_SLOT_QUESTIONS,
    build_driver_label_narrative,
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
        "indices": {"sh": {"change": -12.2}, "zz500": {"change": -23.4}},
        "limitSummary": {
            "continuousBoards": {"yiban": 40, "erban": 18, "sanban": 7, "sibanPlus": 3, "maxBoard": 6},
            "zhaban": {"count": 12, "rate": 15.0, "fengbanRate": 85.0, "ztCount": 68},
        },
    }


def _v3_rows():
    return [
        {"code": "000001", "name": "甲", "rank": 1, "heat": 99, "pctChange": 9.98,
         "price": 9.66, "limitUpPrice": 9.66, "mainTheme": "算力", "reason": "算力租赁"},
        {"code": "000002", "name": "乙", "rank": 2, "heat": 90, "pctChange": 6.0,
         "price": 5.0, "limitUpPrice": None, "mainTheme": "固态电池"},
        {"code": "000003", "name": "丙", "rank": 3, "heat": 80, "pctChange": 3.0, "mainTheme": "AI应用"},
        {"code": "000004", "name": "丁", "rank": 4, "heat": 70, "pctChange": -1.0},
        {"code": "000005", "name": "戊", "rank": 5, "heat": 60, "pctChange": -6.0},
        {"code": "000006", "name": "己", "rank": 6, "heat": 50, "pctChange": None, "zlje": None},
        {"code": "000007", "name": "庚", "rank": 7, "heat": 40, "pctChange": 1.0, "zlje": 5.0e6},
        {"code": "000008", "name": "辛", "rank": 8, "heat": 30, "pctChange": 2.0, "zlje": -3.0e6},
    ]


def _v3_analysis():
    return {
        "000001": {"displayStatus": {"stage": "ignition"}},
        "000002": {"displayStatus": {"stage": "expansion"}},
        "000004": {"displayStatus": {"stage": "cooling"}},
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
        analysis_by_code=_v3_analysis(), slot_time="10:30")
    assert ev["slotTime"] == "10:30"
    assert ev["indices"] == {"sh": -12.2, "zz500": -23.4}
    assert ev["limit"]["ztCount"] == 68 and ev["limit"]["maxBoard"] == 6
    assert ev["limit"]["zhabanRate"] == 15.0 and ev["limit"]["zhabanCount"] == 12
    breadth = ev["breadth"]
    assert breadth["total"] == 8 and breadth["limitUp"] == 1 and breadth["up5"] == 1
    assert breadth["up0"] == 3 and breadth["down0"] == 1 and breadth["down5"] == 1
    assert breadth["pctMissing"] == 1
    fund = ev["fund"]
    assert fund["zljeSum"] == 2.0e6 and fund["zljePos"] == 1 and fund["zljeNeg"] == 1
    assert fund["zljeMissing"] == 6
    assert ev["turnover"]["newCount"] == 7 and ev["turnover"]["droppedCount"] == 1
    assert ev["yesterdayLimit"] is not None and ev["yesterdayLimit"]["count"] >= 1
    lifecycle = ev["lifecycle"]
    assert lifecycle["ignition"] == 1 and lifecycle["expansion"] == 1 and lifecycle["cooling"] == 1
    assert lifecycle["unknown"] == 0 and ev["lifecycleMissing"] == 5
    leader = ev["leaders"][0]
    assert leader["name"] == "甲" and leader["zt"] is True and leader["stage"] == "ignition"
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
    assert ev["yesterdayLimit"] is None
    assert ev["lifecycleMissing"] == 1


def test_collect_slot_evidence_zt_count_from_boards_when_zhaban_missing():
    frame = {"indices": {}, "limitSummary": {"continuousBoards": {"yiban": 40, "erban": 18, "sanban": 7, "sibanPlus": 3, "maxBoard": 6}}}
    ev = collect_slot_evidence(frame=frame, rows=[], yesterday_rows=[], analysis_by_code={}, slot_time="09:30")
    assert ev["limit"]["ztCount"] == 68
    assert "指数缺失" in " ".join(ev["quality"]["degradedSources"])


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
