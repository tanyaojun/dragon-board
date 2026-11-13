# -*- coding: utf-8 -*-
"""jev 全线版本戳纪律回归锁（2026-10-13 复盘修复：phase_band/daily_line 起戳）。

背景：全线盘点发现 phase_band 题与 daily_line 无题集代际戳（I15 口径：判据换代必须动戳，
跨代不可比）。本文件锁定「每条调 jev 的线都有独立版本戳常量」，新增线须在此登记。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_all_jev_lines_have_dedicated_version_stamps():
    from backend.analysis.hotlist import jev_state
    from backend.analysis.hotlist import jev_driver_ammo as drv
    from backend.analysis.hotlist import jev_relay_ammo as relay
    from backend.operations import jev_daily_line as daily

    # 每日链 5 线 + 链外登记（vote/vote 线已于 2026-10-29 随热榜行情页删除移除）
    assert jev_state.QUESTION_SET_VERSION == "v2.6"                    # 热榜情绪（日级判据删减）
    assert drv.QUESTION_SET_VERSION_DRIVER == "v4.0"                   # 个股打标+合并相位（v3.2 freshness 分界/v3.3 depth 联动判层/v4.0 驱动+买盘兑底选项，均 2026-10-22）
    assert drv.QUESTION_SET_VERSION_PHASE_BAND == "v1"                 # 相位带（复盘修复起戳）
    assert relay.QUESTION_SET_VERSION_RELAY == "v9"                    # 连板指数（v9 删 theme_pulse/leader_strength + 相位状态机化；relay_index 降观察）
    assert relay.QUESTION_SET_VERSION_ZHABAN == "v1"                   # 炸板归因（已挂链）
    assert daily.QUESTION_SET_VERSION_DAILY_LINE == "v1"               # 日线一句话（复盘修复起戳）


def test_daily_line_meta_carries_stamp():
    """daily_line 报告 meta 必须含 questionSetVersion（落 phase_monitor 可追溯）。"""
    from backend.operations import jev_daily_line as daily
    import inspect
    src = inspect.getsource(daily)
    assert '"questionSetVersion": QUESTION_SET_VERSION_DAILY_LINE' in src


def test_phase_band_doc_uses_dedicated_stamp():
    """phase_band 落档用独立戳（不再借 driver 戳——跨代不可比违规防范）。"""
    from backend.operations import jev_label_jiuyan as jl
    import inspect
    src = inspect.getsource(jl.run_phase_band_day)
    assert "QUESTION_SET_VERSION_PHASE_BAND" in src
    assert "QUESTION_SET_VERSION_DRIVER" not in src


def test_driver_v3_2_freshness_boundary_wording():
    """v3.2 判据增补锁定（2026-10-22 用户裁决）：catalyst_freshness none/unclear 分界——
    解析通篇常设业务介绍、无事件行判 none；仅存在事件但日期不可考才判 unclear
    （2026-10-22 林州重机/南方路机 unclear 误判实证，见 jev-crowding 相关复盘链）。"""
    from backend.analysis.hotlist import jev_driver_ammo as drv
    q = drv.QUESTIONS_STOCK["catalyst_freshness"]
    assert "无任何事件行时判无明确催化（none）" in q["instructions"]
    assert "仅当解析存在事件/催化描述但日期不可考时才判信息不足（unclear）" in q["instructions"]
    assert "无任何事件行时也判本层" in q["criteria"]["none"]
    assert "解析完全无事件行时不判本层（判 none）" in q["criteria"]["unclear"]
    assert drv.QUESTION_SET_VERSION_DRIVER == "v4.0"   # v3.3 depth 联动判层 + v4.0 驱动/买盘兑底选项（同日叠加增档）


def test_driver_v3_3_depth_escape_lane_wording():
    """v3.3 判据增补锁定（2026-10-22 用户裁决）：catalyst_depth 联动行情判层——
    解析无催化事件行时按联动板块对应业务落点判层，insufficient_evidence 不得用作
    「无明确催化」逃生口（当日 3 只 depth=insufficient 全部 label=capital_flow、
    解析业务信息充分实证，沈鼓集团 601091 insufficient 0.58 为代表）。"""
    from backend.analysis.hotlist import jev_driver_ammo as drv
    q = drv.QUESTIONS_STOCK["catalyst_depth"]
    assert "以与今日联动板块/题材直接相关的解析所述业务判层" in q["instructions"]
    assert "不得用作「无明确催化」的逃生口" in q["instructions"]
    assert "不因「无催化」判本层，按联动板块对应业务的落点判层" in q["criteria"]["insufficient_evidence"]
    assert drv.QUESTION_SET_VERSION_DRIVER == "v4.0"


def test_driver_v4_0_escape_lanes_for_driver_and_buyside():
    """v4.0 兑底选项锁定（2026-10-22 用户裁决）：driver_type/buy_side_logic 新增 insufficient——
    避免 jev 无兑底时乱塞答案拉低置信度，且信息不足可按日复盘成因持续优化题集。"""
    from backend.analysis.hotlist import jev_driver_ammo as drv
    qs = drv.QUESTIONS_STOCK
    d_ins = qs["driver_type"]["criteria"]["insufficient_evidence"]
    b_ins = qs["buy_side_logic"]["criteria"]["insufficient"]
    assert "无板块联动或资金面证据可依" in d_ins
    assert "仍判资金接力，不判本层" in d_ins          # capital_flow 与兑底选项分界
    assert "判据锚均缺失" in b_ins and "不判本层" in b_ins
    assert drv.QUESTION_SET_VERSION_DRIVER == "v4.0"


def test_relay_v7_1_criteria_wording():
    """v7.1 边界修正锁定（预注册 §10.1，2026-10-21 全量门 6 例 strong 误判实证）。"""
    from backend.analysis.hotlist import jev_relay_ammo as relay
    q = relay.QUESTIONS_RELAY
    strong = q["money_effect"]["criteria"]["strong"]
    assert "P80 以上" in strong and "P20 以下" not in strong   # 恒假分支修复
    assert "两分支均不满足时不得判 strong" in strong
    assert "fracture > inverted > balanced" in q["ladder_health"]["instructions"]
    assert "比率恰=0.5 时 fracture 优先于 balanced" in q["ladder_health"]["instructions"]
    # v9：删 theme_pulse/leader_strength（与题材龙头/周期锚重复）；保留 ladder_health；8 题
    assert list(q) == ["relay_index", "relay_phase", "relay_momentum", "ladder_health",
                       "money_effect", "turn_quality", "cycle_intensity", "risk_ahead"]


def test_relay_v8_market_cycle_fusion_questions():
    """v8 市场周期融合 3 题（2026-11-12 用户裁决 Q-A/B/C）：补维度等同加语料，
    主锚=【市场情绪周期】段；choice 题带 insufficient_evidence；状态机仍唯一权威（不改判）。"""
    from backend.analysis.hotlist import jev_relay_ammo as relay
    q = relay.QUESTIONS_RELAY
    for qid in ("turn_quality", "cycle_intensity", "risk_ahead"):
        assert q[qid]["type"] == "choice", qid
        assert "insufficient_evidence" in q[qid]["criteria"], qid
        assert "【市场情绪周期】" in q[qid]["instructions"], qid
    assert set(q["turn_quality"]["criteria"]) == {
        "confirmed", "pending", "false", "not_in_window", "insufficient_evidence"}
    assert set(q["risk_ahead"]["criteria"]) == {
        "high_collapse", "space_compress", "none", "insufficient_evidence"}
    assert set(q["cycle_intensity"]["criteria"]) == {
        "strong", "moderate", "weak", "insufficient_evidence"}


def test_relay_v9_phase_state_machine_criteria():
    """v9 相位状态机化（预登记 relay-v9 §四/五，2026-11-12 用户裁决方案 D/软参照）：
    量化分位判据 + 消歧序 collapse>divergence>relay_heat + 昨日相位软参照 + 周期态背景。"""
    from backend.analysis.hotlist import jev_relay_ammo as relay
    q = relay.QUESTIONS_RELAY["relay_phase"]
    ins = q["instructions"]
    # 消歧序（保守优先）+ 软参照 + 周期态背景 + 分位锚定
    assert "collapse > divergence > relay_heat" in ins
    assert "软参照" in ins and "可背离" in ins
    assert "【市场情绪周期】" in ins and "允许背离" in ins
    assert "P20/P50/P80" in ins
    c = q["criteria"]
    # 量化阈值（去模糊词）：各态锚定分位/百分比
    assert "≥75%" in c["launch"] and "≤P50" in c["launch"]
    assert "≥P50" in c["relay_heat"] and "<10%" in c["relay_heat"]
    assert "−5pct" in c["divergence"] and "<0.5" in c["divergence"]
    assert "≥30%" in c["collapse"] and "≤P20" in c["collapse"]
    assert "≤P20" in c["bottoming"] and "≥80%" in c["bottoming"]
    # 删题不删叙事：theme_evolution/leader_profile 仍在 ops（此处仅锁题集已删）
    assert "theme_pulse" not in relay.QUESTIONS_RELAY
    assert "leader_strength" not in relay.QUESTIONS_RELAY


def test_auction_leader_vA1_dedicated_stamps():
    """竞价龙头晨间链独立版本戳（vA1，2026-11-13 预登记 auction-leader-vA1）：
    独立题集代际 + 独立 AMMO 戳；落档用独立戳（跨代不可比违规防范）。"""
    import inspect
    from backend.analysis.hotlist import auction_leader_ammo as al
    from backend.operations import auction_leader_label as ops
    assert al.QUESTION_SET_VERSION_AUCTION_LEADER == "vA1"
    assert al.AMMO_VERSION_AUCTION_LEADER == "2026-11-13e"   # 竞价榜外腾讯补源
    assert al.QUESTION_SET_HASH_AUCTION_LEADER == al._questions_hash(al.QUESTIONS_AUCTION_LEADER)
    # A2 删题锁定：空间/人气题不在晨间题集
    assert "leader_headroom" not in al.QUESTIONS_AUCTION_LEADER
    assert "leader_rebound_popularity" not in al.QUESTIONS_AUCTION_LEADER
    # 板块两题与催化硬度题原文复用 v17（单一事实源）
    from backend.analysis.hotlist import theme_leader_ammo as tl
    assert al.QUESTIONS_AUCTION_LEADER["theme_speculation_depth"] is tl.QUESTIONS_THEME_LEADER["theme_speculation_depth"]
    assert al.QUESTIONS_AUCTION_LEADER["leader_catalyst_hardness"] is tl.QUESTIONS_THEME_LEADER["leader_catalyst_hardness"]
    src = inspect.getsource(ops._label_one)
    assert "QUESTION_SET_VERSION_AUCTION_LEADER" in src
    assert "QUESTION_SET_VERSION_THEME_LEADER" not in src
    assert al.QUESTIONS_AUCTION_LEADER["theme_continuation"] is tl.QUESTIONS_THEME_LEADER["theme_continuation"]
