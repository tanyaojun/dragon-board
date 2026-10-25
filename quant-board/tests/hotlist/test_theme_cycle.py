# -*- coding: utf-8 -*-
"""题材周期 v1 判据测试（预登记 docs/hotlist-jev/theme-cycle-v1-preregistration.md §三）。

纯函数层测试（analysis/hotlist/theme_cycle.classify_board_cycle / panic_note），
零 DB 零模型调用；逐条判据场景 + fail-visible（缺料 unknown 透传、计时暂停、不伪判）。
含军工案例骨架（第3课 5/7-5/22）：龙断→标杆接力 wzs→再断→终结。
"""
from __future__ import annotations

from backend.analysis.hotlist.theme_cycle import (
    NEW_BENCHMARK_MIN_STREAK,
    STAGE_LABELS_CN,
    THEME_CYCLE_VERSION,
    classify_board_cycle,
    panic_note,
)

BOARD = "军工"


def _state(**over) -> dict:
    """周期状态字典（§三.0 形状）。"""
    st = {"cycleN": 1, "stage": "main_surge", "leaderCode": "600001",
          "leaderName": "润贝航科", "peakStreak": 4,
          "membersPeak": {"600001": 4, "600002": 3},
          "brokenElite": [], "weakDays": 0}
    st.update(over)
    return st


def _cls(**kw) -> dict:
    args = dict(prev_state=None, today_codes=[], leader=None, cycle_leader_state=None,
                streaks={}, prev_sealed=set(), hotlist_codes=set(),
                in_rewrap_pool=set(), bars_pct=None, unavailable_reason=None)
    args.update(kw)
    return classify_board_cycle(**args)


# ── 条 0 unknown：缺料透传 + 计时暂停 ─────────────────────────────────────────

def test_unknown_passthrough_and_timer_pause():
    prev = _state(stage="weakening", weakDays=2)
    out = _cls(prev_state=prev, today_codes=None, unavailable_reason="THS 池缺失")
    assert out["stage"] == "unknown"
    assert out["cycleState"]["weakDays"] == 2      # 计时不推进
    assert out["cycleState"]["stage"] == "weakening"  # 状态原样透传
    assert "THS 池缺失" in out["notes"][0]


def test_unknown_no_cycle():
    out = _cls(today_codes=None)
    assert out["stage"] == "unknown" and out["cycleState"] is None


# ── 军工案例骨架（第3课 5/7-5/22）：主升→断板转弱→标杆接力 wzs→再断→终结 ────

def test_main_surge_continue():
    """龙一续板（sealed 且 ≥2 板）→ main_surge continue。"""
    out = _cls(prev_state=_state(), today_codes=["600001", "600003"],
               leader={"code": "600001", "name": "润贝航科", "streak": 5},
               cycle_leader_state="sealed", streaks={"600001": 5, "600003": 1},
               prev_sealed={"600001", "600002"})
    assert out["stage"] == "main_surge"
    assert out["events"][0]["type"] == "continue"
    assert out["cycleState"]["membersPeak"]["600001"] == 5


def test_leader_break_weakening():
    """龙一断板 → weakening，weakDays=1，龙一入 brokenElite（曾≥2板）。"""
    out = _cls(prev_state=_state(), today_codes=[], cycle_leader_state="broken",
               prev_sealed={"600001"})
    assert out["stage"] == "weakening"
    assert out["cycleState"]["weakDays"] == 1
    assert out["cycleState"]["brokenElite"] == ["600001"]
    assert out["events"][0]["type"] == "leader_break"


def test_wzs_by_new_benchmark():
    """军工 5/12：转弱中 3 连板标杆接力 → wzs（新连板标杆路径）。"""
    prev = _state(stage="weakening", weakDays=1, brokenElite=["600001"],
                  leaderCode="600001")
    out = _cls(prev_state=prev, today_codes=["600003"],
               cycle_leader_state="broken", streaks={"600003": 3},
               prev_sealed=set(), hotlist_codes={"600003"})
    assert out["stage"] == "wzs"
    assert out["cycleState"]["weakDays"] == 0
    assert out["events"][0]["type"] == "wzs"
    assert "新连板标杆" in out["events"][0]["note"]
    assert out["cycleState"]["leaderCode"] == "600003"   # 新龙接位


def test_wzs_by_elite_rewrap_then_rebreak_then_terminator():
    """精英反包触发 wzs → 新龙再断 → 3 个可判交易日无新龙 → 终结者。"""
    prev = _state(stage="weakening", weakDays=1, brokenElite=["600001"])
    out = _cls(prev_state=prev, today_codes=["600001"], cycle_leader_state="broken",
               streaks={"600001": 1}, prev_sealed=set(),          # 昨日未封=断板中
               hotlist_codes={"600001"})
    assert out["stage"] == "wzs"
    assert out["events"][0]["type"] == "wzs"
    assert "人气股反包" in out["events"][0]["note"]
    # 新龙（600001 复位）次日再断
    prev2 = out["cycleState"]
    out2 = _cls(prev_state=prev2, today_codes=[], cycle_leader_state="broken",
                prev_sealed={"600001"})
    assert out2["stage"] == "weakening" and out2["cycleState"]["weakDays"] == 1
    # 第 2 日无封板（计时 2）、第 3 日无封板（计时 3 → 判死）
    out3 = _cls(prev_state=out2["cycleState"], today_codes=[], cycle_leader_state="broken",
                prev_sealed=set())
    assert out3["stage"] == "weakening" and out3["cycleState"]["weakDays"] == 2
    out4 = _cls(prev_state=out3["cycleState"], today_codes=[], cycle_leader_state="broken",
                prev_sealed=set())
    assert out4["stage"] == "terminator"
    assert out4["events"][0]["type"] == "end"
    assert out4["cycleState"]["stage"] == "terminator"


def test_plain_rewrap_no_wzs():
    """周期内仅首板的股反包（普通反包）不触发 wzs，只记事件。"""
    prev = _state(stage="weakening", weakDays=1, membersPeak={"600001": 4, "600005": 1},
                  brokenElite=["600001"])
    out = _cls(prev_state=prev, today_codes=["600005"], cycle_leader_state="broken",
               streaks={"600005": 1}, prev_sealed=set(), hotlist_codes={"600005"})
    assert out["stage"] == "weakening"          # 不改档
    assert out["rewrapPlain"] and out["rewrapPlain"][0]["code"] == "600005"
    assert out["rewrapElite"] == []


def test_first_board_rebound_in_weak_is_plain_attempt():
    """转弱中首板回升=补涨语义：记 plain_attempt 维持 weakening（不入 emerging）。"""
    prev = _state(stage="weakening", weakDays=1, brokenElite=["600001"])
    out = _cls(prev_state=prev, today_codes=["600007"], cycle_leader_state="broken",
               streaks={"600007": 1}, prev_sealed=set(), hotlist_codes={"600007"})
    assert out["stage"] == "weakening"
    assert any(e["type"] == "plain_attempt" for e in out["events"])


# ── 精英判定（热榜 ∧ 高度双条件） ────────────────────────────────────────────

def test_elite_requires_hotlist():
    """曾≥2板但今日未在热榜 → 普通反包（精英须双条件）。"""
    prev = _state(stage="weakening", weakDays=1, brokenElite=["600001"])
    out = _cls(prev_state=prev, today_codes=["600001"], cycle_leader_state="broken",
               streaks={"600001": 1}, prev_sealed=set(), hotlist_codes=set())
    assert out["stage"] != "wzs"
    assert out["rewrapPlain"][0]["code"] == "600001"


def test_elite_degraded_when_hotlist_missing():
    """热榜不可考（None）→ 精英降级高度代理 + 注记（fail-visible）。"""
    prev = _state(stage="weakening", weakDays=1, brokenElite=["600001"])
    out = _cls(prev_state=prev, today_codes=["600001"], cycle_leader_state="broken",
               streaks={"600001": 1}, prev_sealed=set(), hotlist_codes=None)
    assert out["stage"] == "wzs"
    assert out["rewrapElite"][0]["eliteDegraded"] is True
    assert any("热榜不可考" in n for n in out["notes"])


def test_rewrap_needs_break_day():
    """昨日仍封 → 连续非反包；rewrap 须昨日未封今日封。"""
    prev = _state(stage="weakening", weakDays=1)
    out = _cls(prev_state=prev, today_codes=["600001"], cycle_leader_state="sealed",
               streaks={"600001": 1}, prev_sealed={"600001"}, hotlist_codes={"600001"})
    assert out["rewrapElite"] == [] and out["rewrapPlain"] == []


# ── 周期开启 / 终结后新周期 ──────────────────────────────────────────────────

def test_burst_emerging_from_no_cycle():
    """无周期首板 → emerging 开周期。"""
    out = _cls(today_codes=["600010"], leader={"code": "600010", "name": "新题材股",
                                                "streak": 1},
               streaks={"600010": 1})
    assert out["stage"] == "emerging" and out["cycleN"] == 1
    assert out["events"][0]["type"] == "burst"


def test_burst_main_surge_two_streak_no_cycle():
    """无周期今日龙一 2 板（跳过可见 emerging）→ main_surge burst。"""
    out = _cls(today_codes=["600010"], leader={"code": "600010", "name": "新龙头",
                                                "streak": 2},
               streaks={"600010": 2})
    assert out["stage"] == "main_surge" and out["cycleN"] == 1


def test_relaunch_after_terminator():
    """终结者判死后 ≥3 板新标杆 → 新周期（cycleN+1）main_surge + relaunch 事件。"""
    prev = _state(stage="terminator", cycleN=1, leaderCode="600001")
    out = _cls(prev_state=prev, today_codes=["600020"],
               cycle_leader_state="broken", streaks={"600020": 3},
               prev_sealed=set(), hotlist_codes={"600020"})
    assert out["stage"] == "main_surge"
    assert out["cycleN"] == 2
    assert any(e["type"] == "relaunch" for e in out["events"])
    assert out["cycleState"]["membersPeak"] == {"600020": 3}   # 新周期成员重置


def test_old_leader_revive_from_terminator():
    """终态下老龙自己 2 连板复活 → cycleN+1 新周期（relaunch），成员重置。"""
    prev = _state(stage="terminator", cycleN=2, leaderCode="600001",
                  membersPeak={"600001": 4}, brokenElite=["600001"])
    out = _cls(prev_state=prev, today_codes=["600001"], cycle_leader_state="sealed",
               streaks={"600001": 2}, prev_sealed={"600001"})
    assert out["stage"] == "main_surge" and out["cycleN"] == 3
    assert any(e["type"] == "relaunch" for e in out["events"])
    assert out["cycleState"]["brokenElite"] == []
    assert out["cycleState"]["membersPeak"] == {"600001": 2}


def test_terminator_plain_attempt_no_stage_change():
    """终态下 1-2 板封板（非精英非标杆）记 plain_attempt 不改档。"""
    prev = _state(stage="terminator", leaderCode="600001", brokenElite=["600001"])
    out = _cls(prev_state=prev, today_codes=["600030"], cycle_leader_state="broken",
               streaks={"600030": 2}, prev_sealed=set(), hotlist_codes=set())
    assert out["stage"] == "terminator"
    assert any(e["type"] == "plain_attempt" for e in out["events"])


def test_terminator_holds_without_stocks():
    """终态无封板维持 terminator（长尾冷却归档登记局限 §六.3）。"""
    prev = _state(stage="terminator")
    out = _cls(prev_state=prev, today_codes=[], cycle_leader_state="broken")
    assert out["stage"] == "terminator"


# ── 停牌 / 数据洞（停牌不算断板） ────────────────────────────────────────────

def test_suspended_holds_stage():
    """龙一停牌不算断板：周期档维持、终结窗不推进。"""
    prev = _state()
    out = _cls(prev_state=prev, today_codes=[], cycle_leader_state="suspended")
    assert out["stage"] == "main_surge"
    assert any("停牌" in n or "不算断板" in n for n in out["notes"])


# ── 注记（妖股 / 崩塌） ─────────────────────────────────────────────────────

def test_yaogu_note():
    """妖股形态：龙一 ≥5 板续板且板块封板 ≤3 家 → 注记不改档。"""
    out = _cls(prev_state=_state(), today_codes=["600001"],
               leader={"code": "600001", "name": "成飞集成", "streak": 8},
               cycle_leader_state="sealed", streaks={"600001": 8},
               prev_sealed={"600001"})
    assert out["stage"] == "main_surge"
    assert any("妖股形态" in n for n in out["notes"])


def test_panic_note_median():
    """人气股崩塌：brokenElite 中位跌幅 ≤−5% → 恐慌蔓延注记。"""
    note = panic_note(["600001", "600002", "600003"],
                      {"600001": -9.9, "600002": -6.0, "600003": -1.0})
    assert note and "恐慌蔓延" in note


def test_panic_note_limit_count():
    """收盘 ≤−9.9% 家数 ≥2 触发（即使中位未过 −5%）。"""
    note = panic_note(["600001", "600002", "600003", "600004"],
                      {"600001": -10.0, "600002": -9.95, "600003": 0.5, "600004": 1.0})
    assert note and "恐慌蔓延" in note


def test_panic_note_calm():
    note = panic_note(["600001", "600002"], {"600001": -1.0, "600002": -2.0})
    assert note is None


def test_panic_note_insufficient_sample():
    assert panic_note(["600001"], {"600001": -9.9}) is None
    assert panic_note(["600001", "600002"], {"600001": -9.9, "600002": None}) is None


# ── 常量与 fail-visible 兜底 ────────────────────────────────────────────────

def test_constants():
    assert THEME_CYCLE_VERSION == "v1"
    assert NEW_BENCHMARK_MIN_STREAK == 3
    assert STAGE_LABELS_CN["wzs"] == "弱转强"
    assert STAGE_LABELS_CN["terminator"] == "终结者"


def test_no_cycle_no_stocks_normal():
    out = _cls(today_codes=[])
    assert out["stage"] == "normal" and out["cycleState"] is None
