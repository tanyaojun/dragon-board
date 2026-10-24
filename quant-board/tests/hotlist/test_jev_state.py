# -*- coding: utf-8 -*-
"""jev 构建器测试（阶段3 驱动打标保留件；阶段1/2 测试随证伪清理移除，见 git 历史）。

2026-10-08 观察轨道 v3（hotlist-jev-emotion-observe-design.md）：
证据聚合器 + 双问题常量 + 槽位/日级叙事构建器测试。零规则输出、零预测问。"""
import json

from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS,
    JEV_SLOT_QUESTIONS,
    NARRATIVE_TRUNCATION_MARK,
    build_day_jev_state,
    build_history_anchor,
    build_slot_jev_state,
    collect_slot_evidence,
    extract_history_anchor_range,
    format_evidence_line,
    narrative_is_truncated,
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


def _ladder_pools(one=30, two=10, three=2, four=1, high=0):
    """THS 连板层五池（hotspot_focus，真连板口径）帧内形态（10-10 起 EOD 帧入采）。"""
    def _pool(n, items=None):
        return {"ok": True, "items": items if items is not None else [{}] * n}
    return {"one": _pool(one), "two": _pool(two), "three": _pool(three),
            "four": _pool(four), "high": _pool(high)}


def _v3_frame():
    # 2026-10-22 口径修复后现代帧形态：changePct 伴生（10-16 起）+ indexExtra 三指数
    # （10-20 起）+ thsPools 连板层五池（EOD 帧）——真连板口径单一事实源。
    return {
        "indices": {
            "sh": {"change": -12.2, "changePct": -0.38},
            "zz500": {"change": -23.4, "changePct": -1.05},
            "indexExtra": {
                "szcz": {"change": -40.1, "changePct": -0.40},
                "cybz": {"change": -31.2, "changePct": -1.37},
                "kc50": {"change": 3.5, "changePct": 0.27},
            },
            "totalAmount": {"amount": 1.41e12},
        },
        "limitSummary": {
            "continuousBoards": {"yiban": 40, "erban": 18, "sanban": 7, "sibanPlus": 3, "maxBoard": 6},
            "zhaban": {"count": 12, "rate": 15.0, "fengbanRate": 85.0, "ztCount": 68},
            "thsPools": {"pools": _ladder_pools()},
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
    assert ev["indices"]["sh"] == -12.2 and ev["indices"]["zz500"] == -23.4
    # 2026-10-22 口径修复：changePct 伴生（渲染口径）+ indexExtra 三指数透传（帧镜像位）
    assert ev["indexPct"] == {"sh": -0.38, "zz500": -1.05}
    assert ev["indices"]["indexExtra"]["cybz"]["changePct"] == -1.37
    assert ev["indices"]["indexExtra"]["kc50"]["change"] == 3.5
    # 真连板口径（帧连板层派生，优先于外部供给）：maxBoard 区间值原样保留（emotion 链消费）
    assert ev["limit"]["ztCount"] == 68 and ev["limit"]["maxBoard"] == 6
    assert ev["limit"]["maxTrueBoard"] == 4
    assert ev["limit"]["trueBoardSource"] == "frame_ths_ladder"
    assert ev["limit"]["trueBoards"] == {"yiban": 30, "erban": 10, "sanban": 2,
                                          "sibanPlus": 1, "high": 0}
    assert ev["reasonsTotal"] == 1
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


def test_collect_slot_evidence_legacy_board_schema_normalized():
    """2026-07-03 前旧 schema（board1..board4plus）→ 归一化，不得再报「涨停 0」。
    07-01 09:30 实证：board1=7/board2=3，当前代码旧版只读 yiban… 回退求和得 0。"""
    frame = {"indices": {}, "limitSummary": {
        "continuousBoards": {"board1": 7, "board2": 3, "board3": 0, "board4plus": 0},
        "zhaban": {"count": 4, "rate": 18.18, "fengbanRate": 81.82}}}
    ev = collect_slot_evidence(frame=frame, rows=[], yesterday_rows=[], analysis_by_code={}, slot_time="09:30")
    assert ev["limit"]["ztCount"] == 10
    assert ev["limit"]["boards"] == {"yiban": 7, "erban": 3, "sanban": 0, "sibanPlus": 0}
    assert "涨停证据缺失" not in " ".join(ev["quality"]["degradedSources"])


def test_collect_slot_evidence_empty_board_buckets_not_pseudo_zero():
    """现代帧桶键全 None 且无 ztCount → 不可求和；必须 None + 缺失披露，不得伪 0。"""
    frame = {"indices": {}, "limitSummary": {
        "continuousBoards": {"yiban": None, "erban": None, "sanban": None, "sibanPlus": None},
        "zhaban": {"count": 4, "rate": 18.18, "fengbanRate": 81.82}}}
    ev = collect_slot_evidence(frame=frame, rows=[], yesterday_rows=[], analysis_by_code={}, slot_time="09:30")
    assert ev["limit"]["ztCount"] is None
    assert "涨停证据缺失" in " ".join(ev["quality"]["degradedSources"])


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
    # 2026-10-22 口径修复：7 指数 changePct 渲染（changePct 缺失降级点位）
    assert "沪指 -0.38%" in s and "中证500 -1.05%" in s
    assert "深成指 -0.40%" in s and "创业板指 -1.37%" in s and "科创50 +0.27%" in s
    assert "涨停 68" in s and "最高 4 连板（真连板）" in s and "炸板率 15%" in s
    assert "（一板30/二板10/三板2/四板以上1，真连板口径）" in s
    assert "另有断板股区间高度最高 6 板" in s  # 区间高度降级为标注，杜绝两个「最高板」
    assert "热榜TRIN：1.67" in s and "量价背离" in s
    # B1 第二刀：压缩行 slim 化后，TRIN/主力/生命周期/强资只活在当前帧全量段，
    # 已走帧压缩行不再携带（"TRIN 1.67"/"强资1·风险1" 旧断言随刀退役）
    assert "量能同期+41%" in s  # 压缩行携带同期量能（判据引用，保留）
    assert "指数与量能：" in s and "两市总成交额 +14100.00亿（较昨日同期放量 41%）" in s  # 指数×量能同行
    assert "资金确认 1 只" in s and "占可判定 33%" in s  # 行级标记带占比（跨日可比，当前帧段）
    assert "风险预警 1 只" in s
    assert "新进 7" in s and "淘汰 1" in s
    assert "净额合计" in s and "+0.07亿" in s
    assert "昨涨停承接" in s
    # 2026-10-22 次级修复 C：已走帧压缩行生命周期含「反转」（sequence_stage 退潮判据弹药）
    assert "点火 0" in s and "扩散 1" in s and "反转 1" in s and "冷却 1" in s
    assert "甲" in s and "算力" in s and "涨停" in s and "点火" in s
    assert "10:00｜" in s  # 压缩行进入已走帧段
    assert "无缺失" in s
    assert len(s) <= 4000


def test_build_slot_jev_state_truncation_disclosed():
    # A3（2026-10-24）：超限静默硬切会让末段【数据质量】无声丢失（fail-visible 违规）。
    # 截断必须显式注记，对模型与人同时对可见；未超限时输出逐字节不变（full_shape 用例守护）。
    prior = collect_slot_evidence(
        frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=_v3_yesterday_rows(),
        analysis_by_code=_v3_analysis(), slot_time="10:00",
        yesterday_same_slot_total_amount=1.0e12)
    s = build_slot_jev_state(
        trading_date="2026-10-08", slot_time="15:00",
        current=_v3_current_evidence(), priors=[prior] * 30)
    assert NARRATIVE_TRUNCATION_MARK in s
    assert narrative_is_truncated(s)
    # 质量段被截掉时，截断注记必须补位说明（只查注记之前的正文）
    assert "【数据质量】" not in s.split(NARRATIVE_TRUNCATION_MARK)[0]


def test_format_evidence_line_slim_omits_context_groups_only():
    # B1 第二刀：slim=True 删四组判据外语境证据（TRIN/主力净额/生命周期/强资风险），
    # 判据与参照系引用字段（指数/涨停/连板/炸板率/封板率/涨跌分布/量能同期/新进淘汰/
    # 昨涨停承接）保留；slim=False（默认）逐字节不变（日级逐帧行同享该保证）。
    ev = collect_slot_evidence(
        frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=_v3_yesterday_rows(),
        analysis_by_code=_v3_analysis(), slot_time="10:00",
        yesterday_same_slot_total_amount=1.0e12)
    full = format_evidence_line(ev)
    slim = format_evidence_line(ev, slim=True)
    assert "TRIN" in full and "TRIN" not in slim
    assert "主力净额" in full and "主力净额" not in slim
    assert "点火" in full and "点火" not in slim
    assert "强资" in full and "强资" not in slim
    for kept in ("涨停 ", "炸板率", "封板率", "涨跌 涨停", "量能同期", "新进 ", "昨涨停承接"):
        assert kept in slim, f"slim 行不得删判据引用字段：{kept}"


def test_build_slot_jev_state_slim_scoped_to_priors():
    # slim 只作用于槽级已走帧段：当前帧全量段与日级逐帧行不受影响
    prior = collect_slot_evidence(
        frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=_v3_yesterday_rows(),
        analysis_by_code=_v3_analysis(), slot_time="10:00",
        yesterday_same_slot_total_amount=1.0e12)
    s = build_slot_jev_state(
        trading_date="2026-10-08", slot_time="10:30",
        current=_v3_current_evidence(), priors=[prior])
    walked = s.split("【当日已走帧证据】")[1].split("【数据质量】")[0]
    assert "TRIN" not in walked and "主力净额" not in walked and "强资" not in walked
    assert "热榜TRIN" in s and "资金确认 1 只" in s  # 当前帧全量段保留
    day = build_day_jev_state(
        trading_date="2026-10-08",
        evidences=[prior, _v3_current_evidence()])
    assert "TRIN" in day  # 日级逐帧行 slim=False 逐字节不变


def test_build_slot_jev_state_no_truncation_untouched():
    prior = collect_slot_evidence(
        frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=_v3_yesterday_rows(),
        analysis_by_code=_v3_analysis(), slot_time="10:00",
        yesterday_same_slot_total_amount=1.0e12)
    s = build_slot_jev_state(
        trading_date="2026-10-08", slot_time="10:30",
        current=_v3_current_evidence(), priors=[prior])
    assert NARRATIVE_TRUNCATION_MARK not in s
    assert not narrative_is_truncated(s)


def test_build_day_jev_state_truncation_disclosed():
    evidences = [
        collect_slot_evidence(frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=_v3_yesterday_rows(),
                              analysis_by_code=_v3_analysis(), slot_time="09:30"),
        _v3_current_evidence(),
    ]
    s = build_day_jev_state(trading_date="2026-10-08", evidences=evidences * 30)
    assert NARRATIVE_TRUNCATION_MARK in s and narrative_is_truncated(s)
    s_ok = build_day_jev_state(trading_date="2026-10-08", evidences=evidences)
    assert not narrative_is_truncated(s_ok)


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
    # 2026-10-22 真连板口径：日级峰值取 maxTrueBoard（4），区间 6 降级为标注
    assert "【当日累计】" in s and "新进 7" in s and "真连板峰值 4 板" in s
    assert "【数据质量】" in s and len(s) <= 6000


def test_build_day_jev_state_empty_defensive():
    s = build_day_jev_state(trading_date="2026-10-08", evidences=[])
    assert "无帧证据" in s


# ── 2026-10-22 日级 EOD 语料修复：收盘帧全量块 + 帧覆盖 + 结构化质量 + 真连板覆盖标签 ──


def _day_evidence(slot, *, close=False, no_indices=False, no_amount=False,
                  no_heat=False, no_pools=False):
    import copy

    frame = copy.deepcopy(_v3_frame())
    if no_indices:
        frame["indices"] = {}
    if no_amount and isinstance(frame.get("indices"), dict):
        frame["indices"] = {k: v for k, v in frame["indices"].items() if k != "totalAmount"}
    if no_pools:
        frame["limitSummary"] = {k: v for k, v in frame["limitSummary"].items() if k != "thsPools"}
    if close:
        frame["limitSummary"]["sealQuality"] = {
            "byzCount": 27, "hardCount": 7, "rottenCount": 16,
            "rottenShare": 0.32, "avgSucRate": 0.812}
        frame["limitSummary"]["drawdown"] = {
            "count": 3, "avgDrawdownPct": 12.99, "deepestDrawdownPct": 14.93}
    rows = [dict(r) for r in _v3_rows()]
    if no_heat:
        rows = [dict(r, heat=0) for r in rows]
    return collect_slot_evidence(
        frame=frame, rows=rows, yesterday_rows=_v3_yesterday_rows(),
        analysis_by_code=_v3_analysis(), slot_time=slot,
        yesterday_same_slot_total_amount=1.0e12)


def test_build_day_jev_state_no_close_block_but_cumulative_close_facts():
    """v2.6 裁决：不补收盘帧全量块，只保留压缩行+当日累计（收盘实况）。"""
    close = _day_evidence("15:00", close=True)
    prior = _day_evidence("09:30")
    s = build_day_jev_state(
        trading_date="2026-10-21", evidences=[prior, close],
        expected_slots=["09:30", "15:00"], present_slots=["09:30", "15:00"])
    assert "【收盘帧证据】" not in s
    assert "封板质量：" not in s and "触板回撤池：" not in s
    assert "焦点个股：" not in s and "涨停原因" not in s
    # 压缩行与累计仍给收盘实况（判据可用的炸板率/封板率/涨停/真连板）
    assert "封板率 85%" in s
    assert "【当日累计】" in s and "收盘涨停 68" in s and "收盘封板率 85%" in s
    assert "帧 2/2" in s
    assert "全日真连板峰值 4 板（2/2 帧有真连板）" in s
    assert "【数据质量】无缺失" in s


def test_build_day_jev_state_missing_close_disclosed():
    mid = _day_evidence("14:00")
    prior = _day_evidence("09:30")
    s = build_day_jev_state(
        trading_date="2026-10-21", evidences=[prior, mid],
        expected_slots=["09:30", "14:00"], present_slots=["09:30", "14:00"])
    assert "【收盘帧证据】" not in s
    assert "收盘帧 缺" in s
    assert "无 15:00 收盘帧（末帧 14:00；日级判读非全天口径）" in s
    assert "帧 2/2" in s


def test_build_day_jev_state_true_board_coverage_labels():
    # 早盘无连板层、收盘帧有 → 只能称「收盘真连板」，不得称「全日峰值」
    prior = _day_evidence("09:30", no_pools=True)
    close = _day_evidence("15:00", close=True)
    s = build_day_jev_state(
        trading_date="2026-10-21", evidences=[prior, close],
        expected_slots=["09:30", "15:00"], present_slots=["09:30", "15:00"])
    assert "收盘真连板 4 板（仅收盘帧有真连板）" in s
    assert "全日真连板峰值" not in s


def test_build_day_jev_state_quality_counts_not_string_dedup():
    prior = _day_evidence("09:30", no_indices=True, no_amount=True)
    close = _day_evidence("15:00", close=True)
    s = build_day_jev_state(
        trading_date="2026-10-21", evidences=[prior, close],
        expected_slots=["09:30", "15:00"], present_slots=["09:30", "15:00"])
    assert "指数缺失 1/2 帧" in s
    assert "盘中 1 帧无量能字段（收盘帧已采集）" in s
    assert "两市总成交额缺失（历史帧无该字段）" not in s


def test_build_day_jev_state_no_slot_only_heat_noise():
    """v2.6 日级不渲染焦点个股 → 槽级「热度未采集」不得泄漏进日级质量段。"""
    prior = _day_evidence("09:30", no_heat=True)
    close = _day_evidence("15:00", close=True)
    s = build_day_jev_state(
        trading_date="2026-10-21", evidences=[prior, close],
        expected_slots=["09:30", "15:00"], present_slots=["09:30", "15:00"])
    assert "热度字段未采集" not in s
    prior2 = _day_evidence("09:30", no_heat=True)
    close2 = _day_evidence("15:00", close=True, no_heat=True)
    s2 = build_day_jev_state(
        trading_date="2026-10-21", evidences=[prior2, close2],
        expected_slots=["09:30", "15:00"], present_slots=["09:30", "15:00"])
    assert "热度字段未采集" not in s2


def test_build_history_anchor_effective_sample_and_provenance():
    stats = [
        {"date": f"2026-08-{d:02d}", "ztCount": 50, "maxTrueBoard": 4,
         "maxTrueBoardSource": "frame_15", "amountYi": (None if d == 20 else 16000.0),
         "zhabanRate": 20.0}
        for d in range(1, 21)
    ]
    out = build_history_anchor(stats)
    assert "两市成交额：p20=" in out and "有效样本 19/20" in out
    assert "最高连板来源：" in out and "帧" in out


# ── 近20日参照锚 + 封板质量/回撤池/09:30 注记（原 v2 判定测试，2026-10-02 归一）──


STATS = [
    {"date": f"2026-08-{d:02d}", "ztCount": 30 + i * 2, "maxTrueBoard": 4 + (i % 3),
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
    # v2.6（2026-10-22 用户裁决）：日级判据删去日级语料未供给的封板率/焦点高位股/题材分散；
    # 槽级判据保留（槽位当前帧段有这些证据）。
    day_crowd = JEV_DAY_QUESTIONS["day_crowding"]["criteria"]
    assert "封板率" not in day_crowd["late_seal_weakness"]
    assert "焦点高位股" not in day_crowd["top_acceleration"]
    assert "题材分散" not in day_crowd["no_crowding"]
    assert "封板率" not in day_crowd["insufficient_evidence"]
    assert "封板率" in JEV_SLOT_QUESTIONS["crowding"]["criteria"]["late_seal_weakness"]
    assert "焦点高位股" in JEV_SLOT_QUESTIONS["crowding"]["criteria"]["top_acceleration"]
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


# ── 2026-10-22 语料口径修复（jev-slot-corpus-caliber-fix-preregistration.md）──
# A 指数 7 只 changePct；B 真连板口径；C 反转计数；D 热度降噪；E 原因口径；F 降级披露。

from backend.analysis.hotlist.jev_state import (  # noqa: E402
    collect_slot_evidence as _collect,
    derive_true_ladder_from_pools,
    format_evidence_line,
)


def test_derive_true_ladder_from_pools_caliber():
    # 池身份=高度（one=1…four=4），high 池条目 continue_day_cnt=精确高度（10-16 新华传媒 11 板实证形态）
    pools = {"one": {"ok": True, "items": [{}] * 5}, "two": {"ok": True, "items": [{}] * 2},
             "three": {"ok": True, "items": []}, "four": {"ok": True, "items": []},
             "high": {"ok": True, "items": [{"continue_day_cnt": 11}, {"continue_day_cnt": 7}]}}
    lad = derive_true_ladder_from_pools(pools)
    assert lad["maxBoard"] == 11 and lad["boards"]["high"] == 2
    # 任一池缺失/不 ok → 整体不可算 None（relay 审查 #8 同规：半池不可用不冒充全量）
    assert derive_true_ladder_from_pools(dict(pools, four={"ok": False, "items": []})) is None
    assert derive_true_ladder_from_pools({"one": pools["one"]}) is None
    assert derive_true_ladder_from_pools(None) is None
    # 五池全零 → None（无法区分「池未就绪」与「真无涨停」，review P2-3 裁决：
    # 09:30 开盘池未就绪与冰点日同样是全零，任一种按 0 连板呈现都会伪装权威口径）
    empty = {k: {"ok": True, "items": []} for k in ("one", "two", "three", "four", "high")}
    assert derive_true_ladder_from_pools(empty) is None
    # high 池有条目但高度字段缺失 → 池身份下限 5（宁缺毋猜的下界披露）
    no_cnt = {**empty, "high": {"ok": True, "items": [{"stock_code": "X"}]}}
    assert derive_true_ladder_from_pools(no_cnt)["maxBoard"] == 5


def test_collect_slot_evidence_true_ladder_param_fallback():
    # 盘中帧（无连板层五池）→ 外部真连板供给（计算层 ths_live / stored_doc）生效
    frame = _v3_frame()
    frame["limitSummary"] = {k: v for k, v in frame["limitSummary"].items() if k != "thsPools"}
    lad = {"maxBoard": 3, "source": "ths_live",
           "boards": {"one": 20, "two": 5, "three": 1, "four": 2, "high": 0}}
    ev = _collect(frame=frame, rows=_v3_rows(), yesterday_rows=[], analysis_by_code={},
                  slot_time="14:00", true_ladder=lad)
    assert ev["limit"]["maxTrueBoard"] == 3 and ev["limit"]["trueBoardSource"] == "ths_live"
    assert ev["limit"]["trueBoards"]["sibanPlus"] == 2
    assert not any("真连板" in s for s in ev["quality"]["degradedSources"])


def test_collect_slot_evidence_frame_ladder_wins_over_param():
    # EOD 帧（连板层在帧内）→ 帧池 as-of 派生优先，外部供给（可能 now-state）不污染
    stale = {"maxBoard": 9, "source": "ths_live",
             "boards": {"one": 1, "two": 1, "three": 1, "four": 1, "high": 1}}
    ev = _collect(frame=_v3_frame(), rows=_v3_rows(), yesterday_rows=[], analysis_by_code={},
                  slot_time="15:00", true_ladder=stale)
    assert ev["limit"]["trueBoardSource"] == "frame_ths_ladder"
    assert ev["limit"]["maxTrueBoard"] == 4


def test_collect_slot_evidence_index_extra_missing_disclosed():
    # 历史帧（10-20 前无 indexExtra）→ 三指数缺席进 degradedSources（fail-visible 不补 0）
    frame = _v3_frame()
    frame["indices"] = {k: v for k, v in frame["indices"].items() if k != "indexExtra"}
    ev = _collect(frame=frame, rows=_v3_rows(), yesterday_rows=[], analysis_by_code={},
                  slot_time="10:30")
    assert "三指数缺席：深成指、创业板指、科创50" in " ".join(ev["quality"]["degradedSources"])


def test_collect_slot_evidence_true_ladder_missing_disclosed():
    # 盘中帧且无外部供给 → 真连板缺席进 degradedSources；区间 maxBoard 原样保留（emotion 链零漂移）
    frame = _v3_frame()
    frame["limitSummary"] = {k: v for k, v in frame["limitSummary"].items() if k != "thsPools"}
    ev = _collect(frame=frame, rows=_v3_rows(), yesterday_rows=[], analysis_by_code={},
                  slot_time="14:00")
    assert "真连板未采集" in " ".join(ev["quality"]["degradedSources"])
    assert ev["limit"]["maxBoard"] == 6 and "maxTrueBoard" not in ev["limit"]


def test_slot_narrative_legacy_frame_renders_points_and_4_indices():
    # 10-16 前历史帧：无 changePct、无 indexExtra → 点位口径降级 + 4 指数，不补 0 不冒充
    frame = {"indices": {"sh": {"change": -12.2}, "zz500": {"change": -23.4}},
             "limitSummary": _v3_frame()["limitSummary"]}
    ev = _collect(frame=frame, rows=_v3_rows(), yesterday_rows=[], analysis_by_code={},
                  slot_time="10:30")
    s = build_slot_jev_state(trading_date="2026-09-10", slot_time="10:30", current=ev, priors=[])
    assert "沪指 -12.20点" in s and "中证500 -23.40点" in s
    idx_line = [line for line in s.split("\n") if line.startswith("指数与量能：")][0]
    assert "深成指" not in idx_line and "创业板指" not in idx_line and "科创50" not in idx_line
    assert "三指数缺席" in s


def test_slot_narrative_true_ladder_missing_renders_range_caliber():
    # 真连板不可得 → 「最高 N 板（区间跨度口径）」+ 降级披露（不再以区间冒充连板）
    frame = _v3_frame()
    frame["limitSummary"] = {k: v for k, v in frame["limitSummary"].items() if k != "thsPools"}
    ev = _collect(frame=frame, rows=_v3_rows(), yesterday_rows=[], analysis_by_code={},
                  slot_time="14:00")
    s = build_slot_jev_state(trading_date="2026-10-21", slot_time="14:00", current=ev, priors=[ev])
    assert "最高 6 板（区间跨度口径）" in s
    assert "真连板该帧未采集" in s
    # 压缩行同步降级标注
    assert "最高区间 6 板" in s


def test_slot_narrative_heat_all_zero_rank_order_no_noise():
    # D：上游热度无供给（10-21 实证 232/232 行 heat=0）→ rank 序 + 无「热度 0」噪音 + 披露
    rows = []
    for i in range(1, 9):
        rows.append({"code": f"00000{i}", "name": f"股{i}", "rank": i, "heat": 0,
                     "pctChange": 1.0, "change": 1.0, "turnover": 1.0e7})
    ev = _collect(frame=_v3_frame(), rows=rows, yesterday_rows=[], analysis_by_code={},
                  slot_time="14:00")
    assert ev["leaders"][0]["name"] == "股1"  # heat 全零 → rank 序
    s = build_slot_jev_state(trading_date="2026-10-21", slot_time="14:00", current=ev, priors=[])
    assert "热度 0" not in s
    assert "热度字段未采集" in s


def test_slot_narrative_reasons_total_disclosed():
    # E：涨停原因行披露「有原因个股 N 只，列前 5」（36 只中任意截 5 的口径可见）
    rows = []
    for i in range(1, 8):
        rows.append({"code": f"00000{i}", "name": f"股{i}", "rank": i, "heat": 90 - i,
                     "pctChange": 9.9, "change": 9.9, "reason": f"题材{i}", "turnover": 1.0e7})
    ev = _collect(frame=_v3_frame(), rows=rows, yesterday_rows=[], analysis_by_code={},
                  slot_time="14:00")
    assert ev["reasonsTotal"] == 7 and len(ev["reasons"]) == 5
    s = build_slot_jev_state(trading_date="2026-10-21", slot_time="14:00", current=ev, priors=[])
    assert "涨停原因（有原因个股 7 只，原因列前 5 类）" in s


def test_format_evidence_line_seven_indices_and_reversal():
    ev = _v3_current_evidence()
    line = format_evidence_line(ev)
    # 压缩行：7 指数 pct + 反转生命周期 + 真连板
    assert "沪指 -0.38%" in line and "创业板指 -1.37%" in line and "科创50 +0.27%" in line
    assert "反转 1" in line
    assert "最高 4 连板" in line and "最高区间" not in line


def test_collect_slot_evidence_partial_index_extra_disclosed():
    """indexExtra 部分缺席（如只有深成指）→ 逐键披露，创业板指/科创50 不得静默消失（review P2-2）。"""
    frame = _v3_frame()
    frame["indices"]["indexExtra"] = {"szcz": {"change": -40.1, "changePct": -0.40}}
    ev = _collect(frame=frame, rows=_v3_rows(), yesterday_rows=[], analysis_by_code={},
                  slot_time="10:30")
    degraded = " ".join(ev["quality"]["degradedSources"])
    assert "三指数缺席：创业板指、科创50" in degraded
    s = build_slot_jev_state(trading_date="2026-10-21", slot_time="10:30", current=ev, priors=[])
    idx_line = [line for line in s.split("\n") if line.startswith("指数与量能：")][0]
    assert "深成指 -0.40%" in idx_line
    assert "创业板指" not in idx_line and "科创50" not in idx_line


def test_collect_slot_evidence_change_pct_only_not_core_missing():
    """10-16 回填形态：主指数只有 changePct 没有 change——渲染走 pct，质量层不得报「指数缺失」。"""
    frame = {"indices": {"sh": {"changePct": -0.5}, "hs300": {"changePct": -0.2},
                         "zz500": {"changePct": 0.1}, "zz1000": {"changePct": 0.3}},
             "limitSummary": _v3_frame()["limitSummary"]}
    ev = _collect(frame=frame, rows=_v3_rows(), yesterday_rows=[], analysis_by_code={},
                  slot_time="10:30")
    degraded = " ".join(ev["quality"]["degradedSources"])
    assert "指数缺失" not in degraded
    assert "三指数缺席：深成指、创业板指、科创50" in degraded
    s = build_slot_jev_state(trading_date="2026-10-16", slot_time="10:30", current=ev, priors=[])
    assert "沪指 -0.50%" in s and "三指数缺席" in s


def test_slot_narrative_day_peak_zero_truthiness():
    """maxTrueBoard 显式 None 判定（review P3-3）：无连板证据时不把 0 当「缺」的替身。"""
    frame = _v3_frame()
    frame["limitSummary"] = {k: v for k, v in frame["limitSummary"].items() if k != "thsPools"}
    ev = _collect(frame=frame, rows=_v3_rows(), yesterday_rows=[], analysis_by_code={},
                  slot_time="15:00")
    s = build_day_jev_state(trading_date="2026-10-21", evidences=[ev])
    assert "最高区间板峰值 6 板（真连板未采集）" in s


def test_collect_slot_evidence_heat_sort_beats_rank_order():
    """热度序区分性（review P3-7）：heat 倒序夹具——rank 靠后但热度最高者排第一，
    rank 序实现不得巧合通过。"""
    rows = [
        {"code": "000001", "name": "rank1低热", "rank": 1, "heat": 10,
         "pctChange": 1.0, "change": 1.0, "turnover": 1.0e7},
        {"code": "000005", "name": "rank5高热", "rank": 5, "heat": 500,
         "pctChange": 2.0, "change": 2.0, "turnover": 1.0e7},
    ]
    ev = _collect(frame=_v3_frame(), rows=rows, yesterday_rows=[], analysis_by_code={},
                  slot_time="10:30")
    assert ev["leaders"][0]["name"] == "rank5高热"


def test_collect_slot_evidence_index_extra_point_fallback():
    """indexExtra 有 change 无 changePct → 点位口径降级渲染，changePct 缺席不补 0。"""
    frame = _v3_frame()
    frame["indices"]["indexExtra"] = {"kc50": {"change": 3.5}}
    ev = _collect(frame=frame, rows=_v3_rows(), yesterday_rows=[], analysis_by_code={},
                  slot_time="10:30")
    assert ev["indices"]["indexExtra"]["kc50"]["changePct"] is None
    s = build_slot_jev_state(trading_date="2026-10-21", slot_time="10:30", current=ev, priors=[])
    idx_line = [line for line in s.split("\n") if line.startswith("指数与量能：")][0]
    assert "科创50 +3.50点" in idx_line
