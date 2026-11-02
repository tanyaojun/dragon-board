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


# ---------- 操作层：终态吸收的续跑语义（Q3:A + 2026-11-02 展示清理裁决） ----------

class _FakeCol:
    def __init__(self):
        self.docs = {}

    def find(self, query, projection=None):
        td = query.get("tradingDate")
        rows = [d for d in self.docs.values()
                if td is None or d.get("tradingDate") == td]
        return list(rows)

    def replace_one(self, q, doc, upsert=False):
        self.docs[doc["_id"]] = doc


class _FakeDb:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, _FakeCol())


def test_ops_resume_from_terminal_no_window_and_terminated_on(monkeypatch):
    """终态续跑：不恢复窗（窗满判定失效）+ terminatedOn 沿用——终结后
    板块新行情不回溯改判（重启判据已并入 P3 立项）。"""
    import backend.operations.theme_cycle as ops

    db = _FakeDb()
    col = db[ops.COLLECTION]
    col.docs["2026-11-01:大消费:main"] = {
        "_id": "2026-11-01:大消费:main", "tradingDate": "2026-11-01",
        "board": "大消费", "segment": "main", "state": "terminal",
        "windowOpenedOn": None, "terminatedOn": "2026-06-16"}

    monkeypatch.setattr(ops, "trading_dates_before",
                        lambda db_, date, n, ds: ["2026-11-01"])
    # 当日节点回暖+龙一晋级：若非吸收态会迁主升，吸收态必须停留 terminal
    monkeypatch.setattr(ops, "collect_day_inputs", lambda *a, **k: {
        "date": "2026-11-02", "nodes": {"大消费": "brewing"},
        "events": [], "pool_boards": set(), "reconcile_gaps": [],
        "leaders": [{"board": "大消费", "segment": "main", "code": "001219",
                     "leaderSealedToday": True, "streak": 6,
                     "gain10NewHigh": True}]})
    summary = ops.build_and_save_theme_cycle(db, ["2026-11-02"])
    doc = col.docs["2026-11-02:大消费:main"]
    assert summary["rows"] == 1
    assert doc["state"] == "terminal"            # Q3:A 吸收
    assert doc["terminatedOn"] == "2026-06-16"   # 终结日落痕沿用
    assert doc["windowOpenedOn"] is None         # 终态不恢复窗


def test_ops_terminal_transition_records_day_and_clears_window(monkeypatch):
    """终结发生日：落 terminatedOn=当日，windowOpenedOn 清空。"""
    import backend.operations.theme_cycle as ops

    db = _FakeDb()
    col = db[ops.COLLECTION]
    col.docs["2026-11-01:某板块:main"] = {
        "_id": "2026-11-01:某板块:main", "tradingDate": "2026-11-01",
        "board": "某板块", "segment": "main", "state": "weakening",
        "windowOpenedOn": "2026-10-28", "terminatedOn": None}

    def _dates(db_, date, n, ds):
        return ["2026-10-30", "2026-11-01"][-n:]

    monkeypatch.setattr(ops, "trading_dates_before", _dates)
    monkeypatch.setattr(ops, "collect_day_inputs", lambda *a, **k: {
        "date": "2026-11-02", "nodes": {"某板块": "ice"},
        "events": [], "pool_boards": set(), "reconcile_gaps": [],
        "leaders": []})
    ops.build_and_save_theme_cycle(db, ["2026-11-02"])
    doc = col.docs["2026-11-02:某板块:main"]
    assert doc["state"] == "terminal"
    assert doc["transition"]["trigger"] == "window_full_ice"
    assert doc["terminatedOn"] == "2026-11-02"
    assert doc["windowOpenedOn"] is None
