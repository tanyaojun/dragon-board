# -*- coding: utf-8 -*-
"""题材周期状态机测试（v5 预登记 §五，P2 立项九裁决，2026-11-02）。

裁决锚：Q1=B 首日按节点定态；Q2=A gain10 创 20 日新高；Q3=A 终态吸收；
Q4=A 窗满复用 P1 池窗（池空即满）；迁移优先级 事件>终结>转弱>主升。
"""
from __future__ import annotations

from backend.analysis.hotlist.theme_cycle import (initial_state, replay,
                                                  step_day)


# ---------- 初始态（Q1=B） ----------

def test_initial_state_mapping():
    assert initial_state("mainline") == "mainrise"
    assert initial_state("brewing") == "mainrise"
    assert initial_state("fermenting") == "mainrise"
    assert initial_state("wzs") == "wzs"
    assert initial_state("weakening") == "weakening"
    assert initial_state("collapse") == "weakening"
    assert initial_state("normal") == "weakening"
    assert initial_state("unknown") == "weakening"
    # ice 首日不得直定终态（Q3:A 吸收性=死锁），归转弱
    assert initial_state("ice") == "weakening"


# ---------- 单步迁移 ----------

def test_event_beats_everything():
    """弱转强事件优先：转弱态事件命中→wzs；主升态事件命中→wzs。"""
    st, tr = step_day("weakening", node="weakening",
                      event_types=["leaderRebound"], leader_broken=False,
                      leader_advanced=False, gain10_new_high=False,
                      window_open=True, window_full=False)
    assert st == "wzs" and tr["trigger"] == "wzs_event"

    st, tr = step_day("mainrise", node="brewing", event_types=["benchmarkAdvance"],
                      leader_broken=False, leader_advanced=True,
                      gain10_new_high=False, window_open=False, window_full=False)
    assert st == "wzs" and tr["evidence"]["events"] == ["benchmarkAdvance"]


def test_terminal_requires_window_full_and_ice():
    """终结=窗满+ice，仅转弱态；窗未满或节点非 ice 都不终结。"""
    st, _ = step_day("weakening", node="ice", event_types=[],
                     leader_broken=False, leader_advanced=False,
                     gain10_new_high=False, window_open=True, window_full=False)
    assert st == "weakening"      # 窗未满
    st, tr = step_day("weakening", node="ice", event_types=[],
                      leader_broken=False, leader_advanced=False,
                      gain10_new_high=False, window_open=True, window_full=True)
    assert st == "terminal" and tr["trigger"] == "window_full_ice"
    # collapse 不触发终结（裁决 7），停留转弱
    st, _ = step_day("weakening", node="collapse", event_types=[],
                     leader_broken=False, leader_advanced=False,
                     gain10_new_high=False, window_open=True, window_full=True)
    assert st == "weakening"
    # 主升态窗满+ice 不终结（无观察窗语境）
    st, _ = step_day("mainrise", node="ice", event_types=[],
                     leader_broken=False, leader_advanced=False,
                     gain10_new_high=False, window_open=True, window_full=True)
    assert st == "mainrise"


def test_terminal_absorbing():
    """Q3=A：终结=终态，任何输入不可迁出。"""
    st, tr = step_day("terminal", node="mainline", event_types=["leaderRebound"],
                      leader_broken=False, leader_advanced=True,
                      gain10_new_high=True, window_open=False, window_full=False)
    assert st == "terminal" and tr is None


def test_weaken_triggers_from_mainrise_and_wzs():
    st, tr = step_day("mainrise", node="normal", event_types=[],
                      leader_broken=True, leader_advanced=False,
                      gain10_new_high=False, window_open=False, window_full=False)
    assert st == "weakening" and tr["trigger"] == "leader_broken"
    st, tr = step_day("mainrise", node="collapse", event_types=[],
                      leader_broken=False, leader_advanced=False,
                      gain10_new_high=False, window_open=False, window_full=False)
    assert st == "weakening" and "node_weakening" in tr["trigger"]
    # wzs 态龙一再断板 → 回转弱（窗重开由 replay 层管）
    st, _ = step_day("wzs", node="normal", event_types=[],
                     leader_broken=True, leader_advanced=False,
                     gain10_new_high=False, window_open=False, window_full=False)
    assert st == "weakening"


def test_mainrise_triggers_from_weakening_and_wzs():
    for trig_kwargs, want in (
            ({"node": "brewing"}, "node_uptrend"),
            ({"node": None, "leader_advanced": True}, "leader_advance"),
            ({"node": None, "gain10_new_high": True}, "gain10_new_high")):
        kw = dict(node=None, event_types=[], leader_broken=False,
                  leader_advanced=False, gain10_new_high=False,
                  window_open=True, window_full=False)
        kw.update(trig_kwargs)
        st, tr = step_day("weakening", **kw)
        assert st == "mainrise" and want in tr["trigger"]
    # wzs 证据续强 → 主升
    st, _ = step_day("wzs", node="mainline", event_types=[],
                     leader_broken=False, leader_advanced=False,
                     gain10_new_high=False, window_open=False, window_full=False)
    assert st == "mainrise"


def test_no_evidence_no_migration():
    """无证据不得迁移：主升无触发停留主升。"""
    st, tr = step_day("mainrise", node="normal", event_types=[],
                      leader_broken=False, leader_advanced=False,
                      gain10_new_high=False, window_open=False, window_full=False)
    assert st == "mainrise" and tr is None


# ---------- 重放（窗口跟踪 + 首见定态） ----------

def _day(date, nodes=None, events=None, leaders=None, pool=None):
    return {"date": date, "nodes": nodes or {}, "events": events or [],
            "leaders": leaders or [], "pool_boards": pool or set()}


def test_replay_window_full_ice_terminal():
    """重放场景：主升→龙一断板转弱开窗→池在位三日→池空+ice→终结。"""
    ld = {"board": "机器人", "segment": "main", "code": "600111",
          "name": "沪工", "leaderSealedToday": True, "streak": 3}
    broken = dict(ld, leaderSealedToday=False)
    days = [
        _day("2026-10-27", nodes={"机器人": "mainline"}, leaders=[ld]),
        _day("2026-10-28", nodes={"机器人": "normal"},
             leaders=[broken], pool={("机器人", "main")}),        # 断板开窗 k0
        _day("2026-10-29", nodes={"机器人": "weakening"},
             pool={("机器人", "main")}),                          # k1 在池
        _day("2026-10-30", nodes={"机器人": "weakening"},
             pool={("机器人", "main")}),                          # k2 末窗
        _day("2026-10-31", nodes={"机器人": "ice"}),              # 池空=窗满+ice
    ]
    out = replay(days)
    rows = {r["date"]: {(x["board"], x["segment"]): x for x in r["rows"]}
            for r in out}
    assert rows["2026-10-27"][("机器人", "main")]["state"] == "mainrise"
    assert rows["2026-10-28"][("机器人", "main")]["state"] == "weakening"
    assert rows["2026-10-28"][("机器人", "main")]["transition"]["trigger"] \
        == "leader_broken"
    assert rows["2026-10-30"][("机器人", "main")]["state"] == "weakening"
    last = rows["2026-10-31"][("机器人", "main")]
    assert last["state"] == "terminal" and last["migrated"]
    assert last["transition"]["trigger"] == "window_full_ice"


def test_replay_rebound_within_window():
    """窗内反包：转弱→事件命中→wzs；再断板回转弱。"""
    ld = {"board": "机器人", "segment": "main", "code": "600111",
          "name": "沪工", "leaderSealedToday": True, "streak": 3}
    days = [
        _day("d1", nodes={"机器人": "mainline"}, leaders=[ld]),
        _day("d2", nodes={"机器人": "normal"},
             leaders=[dict(ld, leaderSealedToday=False, streak=None)],
             pool={("机器人", "main")}),
        _day("d3", nodes={"机器人": "weakening"},
             events=[{"board": "机器人", "segment": "main",
                      "type": "leaderRebound"}],
             leaders=[dict(ld, streak=4)],
             pool={("机器人", "main")}),
        _day("d4", nodes={"机器人": "weakening"},
             leaders=[dict(ld, leaderSealedToday=False, streak=None)],
             pool={("机器人", "main")}),
    ]
    out = replay(days)
    seq = [r["rows"][0]["state"] for r in out]
    assert seq == ["mainrise", "weakening", "wzs", "weakening"]


def test_replay_first_seen_node_state_and_absent_boards():
    """首见板块按节点定态（Q1=B）；当日缺席板块不留痕但状态记忆保留。"""
    days = [
        _day("d1", nodes={"机器人": "brewing"}),
        _day("d2"),                                    # 板块整体缺席
        _day("d3", nodes={"机器人": "collapse"}),
    ]
    out = replay(days)
    assert out[0]["rows"][0]["state"] == "mainrise"
    assert out[1]["rows"] == []
    assert out[2]["rows"][0]["prev"] == "mainrise"       # 从记忆态迁移
    assert out[2]["rows"][0]["state"] == "weakening"
