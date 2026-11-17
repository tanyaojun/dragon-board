# -*- coding: utf-8 -*-
"""竞价试盘行渲染器（auction_trial_line，增量2 骨架 2026-11-14c）测试。

依据：auction-trial-source-survey-20261114.md §4 天普 605255 真实样本。
纪律：缺位字段不出现（红线 8）；jj_* 时点快照必须显式标注（勘察 §4 语义警示）；
金额语义待定案只出 App 原名数值；合同定案前 build_one trial=None → 整行缺席。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import auction_leader_ammo as AL

# 天普 605255 11-13 试盘行（勘察 §4 原始样本；金额以 WzsLinker 呈现形态传串）
TP_ROW = {"start_time": "09:15:01", "end_time": "09:18:13",
          "first_amount": "756万", "first_add": "40万", "max_amount": "961万",
          "last_amount": "898万", "jj_percent": 4.78, "jj_amount": "1398万",
          "jj_turnover": 0.15}


def test_full_row_tp_sample():
    ln = AL.auction_trial_line(TP_ROW)
    assert ln == ("竞价试盘（09:15:01–09:18:13）：首开 756万，首加 40万，最大 961万，"
                  "最终 898万；试盘涨幅 +4.78%（09:18:13 时点），竞价成交 1398万，"
                  "换手 0.15%")


def test_jj_group_needs_both_timepoints():
    """start/end 任一缺 → jj_percent/jj_amount/jj_turnover 整组不出（时点不可锚）。"""
    row = {**TP_ROW, "end_time": None}
    ln = AL.auction_trial_line(row)
    assert ln == "竞价试盘（09:15:01 起）：首开 756万，首加 40万，最大 961万，最终 898万"
    assert "试盘涨幅" not in ln and "竞价成交" not in ln


def test_full_window_annotated_as_match():
    row = {**TP_ROW, "end_time": "09:25:00"}
    ln = AL.auction_trial_line(row)
    assert "试盘涨幅 +4.78%（竞价全程匹配）" in ln


def test_numeric_amounts_formatted():
    row = {"start_time": "09:15:02", "end_time": "09:20:11",
           "first_amount": 756_000.0, "max_amount": 961_000.0,
           "jj_percent": -1.5, "jj_amount": 1_398_000.0}
    ln = AL.auction_trial_line(row)
    assert "首开 75.6万" in ln and "最大 96.1万" in ln
    assert "试盘涨幅 -1.50%（09:20:11 时点）" in ln
    assert "最终" not in ln and "换手" not in ln


def test_zero_and_missing_fields_absent_line_absent_when_empty():
    assert AL.auction_trial_line({}) is None                      # 全缺 → 整行缺席
    assert AL.auction_trial_line(None) is None
    assert AL.auction_trial_line({"max_amount": 0}) is None       # 零值不投喂
    row = {"start_time": "09:15:01", "end_time": "09:18:13",
           "jj_percent": 0, "jj_amount": 0, "jj_turnover": 0}
    assert AL.auction_trial_line(row) is None                     # 时点可锚但无量值 → 缺席
    assert AL.auction_trial_line({**TP_ROW, "jj_percent": None,
                                  "jj_amount": None}) is not None  # 部分缺位不占位


def test_pre_percent_not_in_narrative():
    """昨涨幅交叉走 corpusState.trialState.prevPercentCross 结构化留痕，不进叙事。"""
    ln = AL.auction_trial_line({**TP_ROW, "pre_percent": 10.0})
    assert "昨涨幅" not in ln and "pre_percent" not in ln


def test_leader_narrative_order_trial_before_bid_match():
    """时间序：09:15 推送 → 竞价试盘 → 09:25 匹配 → 结构行（试盘行紧邻竞价组）。"""
    text = AL.build_auction_leader_narrative(
        date="2026-11-16", prev_date="2026-11-13",
        leader_name="中重科技", leader_code="603135", board="机器人",
        push_line="竞价看龙头推送（09:15 试盘价）：09:15 中重科技 +3.00%",
        bid_line="竞价（09:25 匹配价）：中重科技 竞价涨幅 +4.78%",
        structure="昨日（2026-11-13）结构：连板 3 板，昨日封板（首封 09:47）",
        trial_line=AL.auction_trial_line(TP_ROW), evidence_block="题材证据块：测试")
    i_push = text.index("竞价看龙头推送")
    i_trial = text.index("竞价试盘")
    i_bid = text.index("竞价（09:25 匹配价）")
    assert i_push < i_trial < i_bid


def test_no_trial_line_when_absent():
    text = AL.build_auction_leader_narrative(
        date="2026-11-16", prev_date="2026-11-13",
        leader_name="中重科技", leader_code="603135", board="机器人",
        push_line=None, bid_line=None, structure=None,
        trial_line=AL.auction_trial_line(None), evidence_block="题材证据块：测试")
    assert "竞价试盘" not in text


def test_vA3_archetype_supply_alignment():
    """五夹具（vA3 预登记 §6.1）：形态题判据引用的字段在五类真实形态的试盘行中齐备
    （供给对齐验收；行值取自 11-13 真实缓存/勘察样本，金额数值元口径）。"""
    # 硬一字（兴欣新材 11-13）：end=09:25:00 全匹配 + 试盘顶死
    ln = AL.auction_trial_line({"start_time": "09:15:00", "end_time": "09:25:00",
                                "first_amount": 467_750_000.0, "first_add": 105_930_000.0,
                                "max_amount": 576_470_000.0, "last_amount": 552_570_000.0,
                                "jj_percent": 9.99, "jj_amount": 9_792_704.0,
                                "jj_turnover": 0.72})
    assert "竞价试盘（09:15:00–09:25:00）" in ln and "+9.99%" in ln
    assert "竞价全程匹配" in ln and "首开 4.68亿" in ln and "最终 5.53亿" in ln
    # 全匹配+资金撤减（合成于 11-13 真实分布）：撤减合读证据（最终<首开）在场
    ln = AL.auction_trial_line({"start_time": "09:15:00", "end_time": "09:25:00",
                                "first_amount": 200_000_000.0, "last_amount": 120_000_000.0,
                                "jj_percent": 8.0})
    assert "首开 2.00亿" in ln and "最终 1.20亿" in ln   # 撤减（最终<首开）合读证据在场
    # 天普形态 cancel_neutral（605255 11-13）：可撤窗撤单 + 0-50% 限价 + 维持
    ln = AL.auction_trial_line({"start_time": "09:15:01", "end_time": "09:18:13",
                                "first_amount": 7_560_000.0, "first_add": 400_000.0,
                                "max_amount": 9_610_000.0, "last_amount": 8_980_000.0,
                                "jj_percent": 4.78, "jj_amount": 13_979_616.0})
    assert "09:18:13 时点" in ln and "+4.78%" in ln and "首加 40.0万" in ln
    # 中重形态 cancel_weak（603135 11-13）：极早撤 + 试盘负涨幅
    ln = AL.auction_trial_line({"start_time": "09:15:02", "end_time": "09:15:20",
                                "first_amount": 20_330_000.0, "last_amount": 21_160_000.0,
                                "jj_percent": -2.36})
    assert "09:15:20 时点" in ln and "-2.36%" in ln
    # 大胜达形态 cancel_strong（603687 11-13）：可撤窗末段撤单 + 高强度 + 撤减
    ln = AL.auction_trial_line({"start_time": "09:15:00", "end_time": "09:19:51",
                                "first_amount": 121_000_000.0, "last_amount": 23_280_000.0,
                                "jj_percent": 6.73})
    assert "09:19:51 时点" in ln and "+6.73%" in ln and "最终 2328.0万" in ln


def test_vA3_hard_oneword_bid_zero_is_true_zero_not_weak():
    """一字板分支供给：bid 行真零成交（一字板无对手盘）**显式渲染 0 值**（真零是数据
    事实、与缺位不同）——封板题一字板分支可引用「匹配价≈限价 + 成交/换手真零」。"""
    bid = [{"label": "兴欣新材", "item": {"bidding_pct": 9.99, "bidding_net": 0,
                                          "bidding_turnover": 0, "bidding_amount": 0,
                                          "zt_buy_amount": 93_013_190.0}}]
    ln = AL.auction_bid_line(bid)
    assert ln is not None and "竞价涨幅 +9.99%" in ln
    assert "竞价成交额 0.0万" in ln and "竞价净额 0.0万" in ln and "竞价换手 0%" in ln
    assert "涨停委买额" in ln          # 委买 9300万 在场（天普 11-13 同款）


def test_vA3_c_audit_trial_supply_alignment():
    """C 轨道审计回归（2026-11-14 base-rate-60d 评估后）：
    ① 试盘行 9 个渲染字段全部被 settlement 题供给清单引用（无死引用/漏供给）；
    ② 结局字段（percent 收盘涨幅）不渲染——试盘行是 09:25 前可观测事实，
    look-ahead 泄漏 = 叙事假证据（天普 11-12 池漏档同级教训）。"""
    trial = {"start_time": "09:15:01", "end_time": "09:18:13", "jj_percent": 4.78,
             "jj_amount": 13_979_616.0, "jj_turnover": 0.15,
             "first_amount": 7_560_000.0, "first_add": 400_000.0,
             "max_amount": 9_610_000.0, "last_amount": 8_980_000.0,
             "percent": 9.99, "circulated_value": 9_428_505_600.0,
             "pre_percent": 10.0, "price": "73.82", "bk_name": "半导体(3)"}
    ln = AL.auction_trial_line(trial)
    assert ln is not None
    # ① 全字段渲染 + 判据供给清单引用（试盘行与题面供给对齐，缺一即漂移）
    pairs = (("start_time", "09:15:01", "开始"), ("end_time", "09:18:13", "结束"),
             ("jj_percent", "试盘涨幅", "试盘涨幅"), ("jj_amount", "竞价成交", "竞价成交"),
             ("jj_turnover", "换手", "换手"), ("first_amount", "首开", "首开额"),
             ("first_add", "首加", "首加额"), ("max_amount", "最大", "最大额"),
             ("last_amount", "最终", "最终额"))
    supply = AL.QUESTIONS_AUCTION_LEADER["trial_settlement_pattern"]["instructions"]
    for field, shown, cited in pairs:
        assert shown in ln, f"{field} 渲染缺席"
        assert cited in supply, f"{field} 未被判据供给清单声明（死引用或漏供给）"
    # ② 结局字段不进叙事
    assert "9.99" not in ln and "收盘" not in ln and "流通市值" not in ln \
        and "73.82" not in ln and "半导体" not in ln


def test_trial_line_noncanonical_end_no_semantic_note():
    """review finding-2：end 非规范串（未补零带冒号/垃圾）不参与 ≥09:25 字典序比较
    ——时点不可锚 = 快照三列整组不出（量价累计段保留），头部不渲染假时间。"""
    for end in ("9:20:00", "abc"):
        trial = {"start_time": "09:15:01", "end_time": end, "jj_percent": 4.78,
                 "jj_amount": 13979616.0, "last_amount": 8980000.0}
        ln = AL.auction_trial_line(trial)
        assert ln is not None
        assert "竞价全程匹配" not in ln and end not in ln
        assert "试盘涨幅" not in ln          # 时点不可锚 → 快照组不出
        assert "最终 898.0万" in ln          # 量价累计段是真实事实，保留
