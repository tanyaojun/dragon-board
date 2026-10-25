# -*- coding: utf-8 -*-
"""题材周期 operations 层测试（settle_day / backfill）。

全 mock（AGENTS §1.2-7 禁真实调用）：day_leader_rows / jiuyan_streak_map /
sealed_and_info / day_status_of / _daily_bars / trading_dates_before /
build_rewrap_pool / _hotlist_codes_of 全部 patch 到 theme_cycle 模块命名空间或源头；
classify_day patch 源头模块；DB 用 FakeCollection（replace_one 捕获落库）。
"""
from __future__ import annotations

import contextlib

import pytest

from backend.operations import theme_cycle as tc

TODAY = "2026-10-26"
PREV = "2026-10-23"


class FakeCollection:
    def __init__(self, docs=None):
        self.docs: dict[str, dict] = docs or {}

    def find_one(self, q, *a, **k):
        return self.docs.get(q.get("_id"))

    def replace_one(self, q, doc, upsert=False):
        self.docs[q["_id"]] = doc

    def find(self, q, *a, **k):
        return []


class FakeDB:
    def __init__(self):
        self.cycle = FakeCollection()
        self.sector_nodes = FakeCollection()
        self.jiuyan_action = FakeCollection()

    def __getitem__(self, name):
        return {"hotlist_jev_theme_cycle": self.cycle,
                "hotlist_jev_sector_nodes": self.sector_nodes,
                "jiuyan_action": self.jiuyan_action}.get(name, FakeCollection())


def _row(board: str, codes: list[str], leader_code: str | None = None,
         leader_name: str | None = None, streak: int | None = None) -> dict:
    return {"board": board, "boardCodes": codes,
            "code": leader_code or (codes[0] if codes else None),
            "name": leader_name, "streak": streak if streak is not None else 1}


def _cycle_row(board: str, cycle_state: dict | None, today_sealed: list[str],
               stage: str = "main_surge") -> dict:
    return {"board": board, "stage": stage, "cycleState": cycle_state,
            "todaySealed": today_sealed}


@pytest.fixture
def env(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(tc, "trading_dates_before",
                        lambda db_, date, n, dataset_id=None:
                        [PREV] if date == TODAY else [])
    monkeypatch.setattr(tc, "bars_need_upto", lambda date: contextlib.nullcontext())
    monkeypatch.setattr(tc, "_daily_bars", lambda code: [])
    monkeypatch.setattr(tc, "_adj_prev_series", lambda date, code, bars: {})
    monkeypatch.setattr(tc, "jiuyan_streak_map",
                        lambda db_, date, ds=None, **k: {})
    monkeypatch.setattr(tc, "build_rewrap_pool",
                        lambda db_, date, slot, ds=None: {"rewrapCodes": [], "rewrapN": 0})
    monkeypatch.setattr(tc, "_hotlist_codes_of", lambda db_, date, ds=None: set())
    from backend.operations import theme_leader_baseline as tlb
    monkeypatch.setattr(tlb, "sealed_and_info",
                        lambda db_, date, ds=None: (set(), {}, {"thsPoolFound": True}))
    from backend.analysis.hotlist import weak_to_strong as wts
    monkeypatch.setattr(wts, "classify_day",
                        lambda db_, date, ds=None: {"state": "strong", "idx": 55.0,
                                                    "hit": False})
    return db


def test_settle_weakening_chain(env, monkeypatch):
    """昨日 weakening day1 → 今日龙一 broken → weakening day2 落库 + 对照列。"""
    monkeypatch.setattr(tc, "day_leader_rows",
                        lambda db_, d, ds=None, p=None: (
                            [_row("机器人", ["600003"], "600003", "新龙头", 1)],
                            {"jiuyanFinalFound": True}) if d == TODAY else (None, {}))
    monkeypatch.setattr(tc, "day_status_of", lambda *a, **k: "broken")
    prev_state = {"cycleN": 1, "stage": "weakening", "leaderCode": "600001",
                  "leaderName": "老龙头", "peakStreak": 4,
                  "membersPeak": {"600001": 4}, "brokenElite": ["600001"], "weakDays": 1}
    env.cycle.docs[f"{PREV}:THEME_CYCLE"] = {"rows": [
        _cycle_row("机器人", prev_state, ["600001"], "weakening")]}
    env.sector_nodes.docs[f"{TODAY}:SECTOR_NODES"] = {"rows": [
        {"board": "机器人", "node": "collapse"}]}
    out = tc.settle_day(env, TODAY)
    assert out["status"] == "ok"
    doc = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]
    row = doc["rows"][0]
    assert row["stage"] == "weakening" and row["cycleState"]["weakDays"] == 2
    assert row["cycleState"]["brokenElite"] == ["600001"]
    assert row["sectorNode"] == "collapse"
    assert doc["marketState"]["state"] == "strong"
    assert doc["meta"]["prevFound"] is True


def test_settle_wzs_with_hotlist(env, monkeypatch):
    """昨日转弱 + 今日精英反包（热榜在榜）→ wzs 落库。"""
    monkeypatch.setattr(tc, "day_leader_rows",
                        lambda db_, d, ds=None, p=None:
                        ([_row("机器人", ["600001"], "600001", "老龙反包", 1)],
                         {"jiuyanFinalFound": True}))
    # 龙一今日在池 → sealed（池权威）；热榜在榜含 600001 → 精英反包
    from backend.operations import theme_leader_baseline as tlb
    monkeypatch.setattr(tlb, "sealed_and_info",
                        lambda db_, date, ds=None: ({"600001"}, {}, {"thsPoolFound": True}))
    monkeypatch.setattr(tc, "_hotlist_codes_of",
                        lambda db_, date, ds=None: {"600001"})
    monkeypatch.setattr(tc, "jiuyan_streak_map",
                        lambda db_, date, ds=None, **k: {"600001": 1})
    prev_state = {"cycleN": 1, "stage": "weakening", "leaderCode": "600001",
                  "leaderName": "老龙头", "peakStreak": 4,
                  "membersPeak": {"600001": 4}, "brokenElite": [], "weakDays": 1}
    env.cycle.docs[f"{PREV}:THEME_CYCLE"] = {"rows": [
        _cycle_row("机器人", prev_state, [], "weakening")]}   # 昨日未封=断板中
    tc.settle_day(env, TODAY)
    row = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]["rows"][0]
    assert row["stage"] == "wzs"
    assert row["rewrapElite"] and row["rewrapElite"][0]["code"] == "600001"
    assert row["cycleState"]["leaderCode"] == "600001"


def test_settle_unknown_ths_missing(env, monkeypatch):
    """今日 THS 池缺失 → 整日 unknown 透传 + 计时暂停 + degraded。"""
    monkeypatch.setattr(tc, "day_leader_rows",
                        lambda db_, d, ds=None, p=None: (None, {"thsPoolFound": False}))
    prev_state = {"cycleN": 1, "stage": "weakening", "leaderCode": "600001",
                  "leaderName": "老龙头", "peakStreak": 4,
                  "membersPeak": {"600001": 4}, "brokenElite": ["600001"],
                  "weakDays": 2}
    env.cycle.docs[f"{PREV}:THEME_CYCLE"] = {"rows": [
        _cycle_row("机器人", prev_state, ["600001"], "weakening")]}
    out = tc.settle_day(env, TODAY)
    assert out["status"] == "degraded"
    doc = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]
    assert doc["rows"][0]["stage"] == "unknown"
    assert doc["rows"][0]["cycleState"]["weakDays"] == 2    # 计时暂停
    assert doc["meta"]["thsFound"] is False


def test_settle_final_missing_masks_ice(env, monkeypatch):
    """final 缺失（空列表 jiuyanFinalFound=False）不伪装平淡：同 unknown 整日降级。"""
    monkeypatch.setattr(tc, "day_leader_rows",
                        lambda db_, d, ds=None, p=None:
                        ([], {"jiuyanFinalFound": False, "thsPoolFound": True}))
    out = tc.settle_day(env, TODAY)
    assert out["status"] == "degraded"
    doc = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]
    assert all(r["stage"] == "unknown" for r in doc["rows"]) or doc["degraded"]


def test_settle_prev_doc_missing(env, monkeypatch):
    """昨日周期文档缺失 → 无周期起步 + 注记（周期链断 fail-visible）。"""
    monkeypatch.setattr(tc, "day_leader_rows",
                        lambda db_, d, ds=None, p=None:
                        ([_row("新板块", ["600010"], "600010", "新股", 1)],
                         {"jiuyanFinalFound": True}))
    monkeypatch.setattr(tc, "jiuyan_streak_map",
                        lambda db_, date, ds=None, **k: {"600010": 1})
    out = tc.settle_day(env, TODAY)
    doc = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]
    row = doc["rows"][0]
    assert row["stage"] == "emerging" and row["cycleN"] == 1
    assert any("昨日周期文档缺失" in n for n in row["notes"])


def test_hotlist_missing_degrades_elite(env, monkeypatch):
    """热榜不可考 → 精英降级高度代理 + 注记（wzs 照常触发）。"""
    monkeypatch.setattr(tc, "day_leader_rows",
                        lambda db_, d, ds=None, p=None:
                        ([_row("机器人", ["600001"], "600001", "老龙", 1)],
                         {"jiuyanFinalFound": True}))
    monkeypatch.setattr(tc, "day_status_of", lambda *a, **k: "broken")
    monkeypatch.setattr(tc, "jiuyan_streak_map",
                        lambda db_, date, ds=None, **k: {"600001": 1})
    monkeypatch.setattr(tc, "_hotlist_codes_of", lambda db_, date, ds=None: None)
    prev_state = {"cycleN": 1, "stage": "weakening", "leaderCode": "600001",
                  "leaderName": "老龙", "peakStreak": 4,
                  "membersPeak": {"600001": 4}, "brokenElite": [], "weakDays": 1}
    env.cycle.docs[f"{PREV}:THEME_CYCLE"] = {"rows": [
        _cycle_row("机器人", prev_state, [], "weakening")]}
    tc.settle_day(env, TODAY)
    row = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]["rows"][0]
    assert row["stage"] == "wzs"
    assert row["rewrapElite"][0]["eliteDegraded"] is True
    assert any("热榜不可考" in n for n in row["notes"])


def test_panic_note_attached(env, monkeypatch):
    """weakening 行 brokenElite 崩塌 → 恐慌蔓延注记挂行。"""
    monkeypatch.setattr(tc, "day_leader_rows",
                        lambda db_, d, ds=None, p=None:
                        ([], {"jiuyanFinalFound": True}))
    monkeypatch.setattr(tc, "day_status_of", lambda *a, **k: "broken")

    def _bars(code):
        if code in ("600001", "600002"):
            return [{"date": TODAY, "close": 9.0 if code == "600001" else 9.4,
                     "prevClose": 10.0}]
        return []

    monkeypatch.setattr(tc, "_daily_bars", _bars)
    prev_state = {"cycleN": 1, "stage": "weakening", "leaderCode": "600001",
                  "leaderName": "老龙", "peakStreak": 4,
                  "membersPeak": {"600001": 4, "600002": 3},
                  "brokenElite": ["600001", "600002"], "weakDays": 1}
    env.cycle.docs[f"{PREV}:THEME_CYCLE"] = {"rows": [
        _cycle_row("机器人", prev_state, ["600001", "600002"], "weakening")]}
    tc.settle_day(env, TODAY)
    row = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]["rows"][0]
    assert row["stage"] == "weakening"
    assert any("恐慌蔓延" in n for n in row["notes"])


def test_backfill_two_days_chain(env, monkeypatch):
    """两日回填成链：首日 burst（无昨日文档）→ 次日龙一断板转弱。"""
    env.jiuyan_action.docs = {}
    dates = iter([])

    def _find(q, *a, **k):
        class _Cur:
            def __iter__(self):
                return iter([{"tradingDate": PREV}, {"tradingDate": TODAY}])
        return _Cur()

    env.jiuyan_action.find = _find
    rows_by_day = {PREV: [_row("机器人", ["600001"], "600001", "新龙", 2)],
                   TODAY: [_row("机器人", ["600001"], "600001", "新龙", 2)]}
    monkeypatch.setattr(tc, "day_leader_rows",
                        lambda db_, d, ds=None, p=None:
                        (rows_by_day[d], {"jiuyanFinalFound": True}))
    monkeypatch.setattr(tc, "jiuyan_streak_map",
                        lambda db_, date, ds=None, **k: {"600001": 2})
    # 不 patch day_status_of：走真实池权威路径——TODAY 池不含 600001 → broken；
    # PREV 池含 600001 → sealed
    from backend.operations import theme_leader_baseline as tlb

    def _sealed(db_, date, ds=None):
        if date == TODAY:
            return ({"600003"}, {}, {"thsPoolFound": True})   # 龙一今日不在池=断板
        return ({"600001"}, {}, {"thsPoolFound": True})

    monkeypatch.setattr(tlb, "sealed_and_info", _sealed)
    monkeypatch.setattr(tc, "trading_dates_before",
                        lambda db_, date, n, dataset_id=None:
                        [PREV] if date == TODAY else [])
    out = tc.backfill(env, PREV, TODAY)
    assert out["days"] == 2 and out["ok"] == 2
    d1 = env.cycle.docs[f"{PREV}:THEME_CYCLE"]["rows"][0]
    d2 = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]["rows"][0]
    assert d1["stage"] == "main_surge" and d1["cycleN"] == 1
    assert d2["stage"] == "weakening" and d2["cycleState"]["weakDays"] == 1
    assert d2["prevStage"] == "main_surge"
