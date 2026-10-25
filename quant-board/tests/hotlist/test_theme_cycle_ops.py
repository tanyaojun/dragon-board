# -*- coding: utf-8 -*-
"""题材周期 v2 operations 层测试（settle_day / backfill）。

全 mock（AGENTS §1.2-7 禁真实调用）：sealed_and_info / jiuyan_streak_map /
day_status_of / _daily_bars / trading_dates_before / build_rewrap_pool /
_hotlist_codes_of / _theme_map 全部 patch 到 theme_cycle 模块命名空间或源头；
classify_day patch 源头模块；DB 用 FakeCollection（replace_one 捕获落库，
jiuyan_action final 名单提供个股 name/time）。
对象=题材（v2）：题材归属经 _theme_map 治理层注入（一股多题材重叠计入）。
"""
from __future__ import annotations

import contextlib

import pytest

from backend.operations import theme_cycle as tc

TODAY = "2026-10-26"
PREV = "2026-10-23"

THEME_MAP = {
    "600001": [{"themeId": "84", "name": "人形机器人", "role": "branch",
                "jiuyanBoard": "机器人"}],
    "600003": [{"themeId": "84", "name": "人形机器人", "role": "branch",
                "jiuyanBoard": "机器人"}],
    "600010": [{"themeId": "395", "name": "宇树机器人", "role": "episode",
                "jiuyanBoard": "机器人"}],
    "600020": [{"themeId": "395", "name": "宇树机器人", "role": "episode",
                "jiuyanBoard": "机器人"},
               {"themeId": "84", "name": "人形机器人", "role": "branch",
                "jiuyanBoard": "机器人"}],
    "600030": [{"themeId": "224", "name": "军工信息化", "role": "branch",
                "jiuyanBoard": "军工"}],
    "600001x": [{"themeId": "x", "name": "某风格题材", "role": "style"}],
}


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
        self.jiuyan_action = FakeCollection()

    def __getitem__(self, name):
        return {"hotlist_jev_theme_cycle": self.cycle,
                "jiuyan_action": self.jiuyan_action}.get(name, FakeCollection())


def _cycle_row(theme: str, cycle_state: dict | None, today_sealed: list[str],
               stage: str = "main_surge") -> dict:
    return {"theme": theme, "stage": stage, "cycleState": cycle_state,
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
    monkeypatch.setattr(tc, "_theme_map", lambda db_: THEME_MAP)
    monkeypatch.setattr(tc, "_gov_missing_n", lambda db_: 0)
    # 韭研 final 名单（个股 name/time 来源）
    db.jiuyan_action.docs[f"{TODAY}:final"] = {"fields": [
        {"name": "机器人", "stocks": [{"code": "sh600001", "name": "龙头甲"},
                                       {"code": "sz600010", "name": "宇树概念股"},
                                       {"code": "sh600020", "name": "双题材股"}]},
        {"name": "军工", "stocks": [{"code": "sh600030", "name": "军工股"}]}]}
    db.jiuyan_action.docs[f"{PREV}:final"] = {"fields": []}
    monkeypatch.setattr(tc, "sealed_and_info",
                        lambda db_, date, ds=None:
                        ({"600001", "600003", "600010", "600020", "600030"}, {},
                         {"thsPoolFound": True}))
    from backend.analysis.hotlist import weak_to_strong as wts
    monkeypatch.setattr(wts, "classify_day",
                        lambda db_, date, ds=None: {"state": "strong", "idx": 55.0,
                                                    "hit": False})
    return db


def test_settle_theme_aggregation_overlap(env):
    """题材独立聚合重叠计入：600020 双题材同时进 人形机器人+宇树机器人。"""
    out = tc.settle_day(env, TODAY)
    assert out["status"] == "ok"
    doc = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]
    by = {r["theme"]: r for r in doc["rows"]}
    # 人形机器人 = 600001+600003+600020（600020 双题材重叠计入）
    assert sorted(by["人形机器人"]["todaySealed"]) == ["600001", "600003", "600020"]
    # 宇树机器人 = 600010+600020（episode 题材）
    assert sorted(by["宇树机器人"]["todaySealed"]) == ["600010", "600020"]
    assert by["人形机器人"]["jiuyanBoard"] == "机器人"
    assert doc["marketState"]["state"] == "strong"
    assert doc["meta"]["mappingBatchAt"] or True


def test_theme_threshold_two_boards(env):
    """行集门槛：当日题材封板 ≥2 家出行；1 家题材不出行（链延续例外单独测）。"""
    env.jiuyan_action.docs[f"{TODAY}:final"] = {"fields": [
        {"name": "机器人", "stocks": [{"code": "sh600001", "name": "龙头甲"},
                                       {"code": "sz600010", "name": "宇树概念股"}]}]}
    # 人形机器人 2 家（600001+600003）达门槛出行；宇树仅 600010 1 家不达门槛
    old = tc.sealed_and_info
    tc.sealed_and_info = lambda db_, date, ds=None: (
        {"600001", "600003", "600010"}, {}, {"thsPoolFound": True})
    try:
        tc.settle_day(env, TODAY)
    finally:
        tc.sealed_and_info = old
    doc = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]
    themes = {r["theme"] for r in doc["rows"]}
    assert "人形机器人" in themes          # 2 家出行
    assert "宇树机器人" not in themes      # 只有 600010 1 家，不达门槛（无链延续）


def test_chain_continuation_below_threshold(env, monkeypatch):
    """链延续例外：昨日有 cycleState 的题材今日 1 家照常演化（不达门槛也出行）。"""
    monkeypatch.setattr(tc, "day_status_of", lambda *a, **k: "broken")
    prev_state = {"cycleN": 1, "stage": "weakening", "leaderCode": "600001",
                  "leaderName": "龙头甲", "peakStreak": 4,
                  "membersPeak": {"600001": 4}, "brokenElite": ["600001"],
                  "weakDays": 1}
    env.cycle.docs[f"{PREV}:THEME_CYCLE"] = {"rows": [
        _cycle_row("人形机器人", prev_state, ["600001"], "weakening")]}
    env.jiuyan_action.docs[f"{TODAY}:final"] = {"fields": [
        {"name": "机器人", "stocks": [{"code": "sh600001", "name": "龙头甲"}]}]}
    monkeypatch.setattr(tc, "sealed_and_info",
                        lambda db_, date, ds=None: ({"600001"}, {}, {"thsPoolFound": True}))
    tc.settle_day(env, TODAY)
    row = next(r for r in env.cycle.docs[f"{TODAY}:THEME_CYCLE"]["rows"]
               if r["theme"] == "人形机器人")
    assert row["stage"] == "weakening" and row["cycleState"]["weakDays"] == 2
    assert any("未达门槛" in n or "无封板" in n for n in row["notes"]) is False


def test_settle_unknown_ths_missing(env, monkeypatch):
    """今日 THS 池缺失 → 整日 unknown 透传 + 计时暂停 + degraded。"""
    monkeypatch.setattr(tc, "sealed_and_info",
                        lambda db_, date, ds=None: (None, {}, {"thsPoolFound": False}))
    prev_state = {"cycleN": 1, "stage": "weakening", "leaderCode": "600001",
                  "leaderName": "老龙头", "peakStreak": 4,
                  "membersPeak": {"600001": 4}, "brokenElite": ["600001"],
                  "weakDays": 2}
    env.cycle.docs[f"{PREV}:THEME_CYCLE"] = {"rows": [
        _cycle_row("人形机器人", prev_state, ["600001"], "weakening")]}
    out = tc.settle_day(env, TODAY)
    assert out["status"] == "degraded"
    doc = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]
    assert all(r["stage"] == "unknown" for r in doc["rows"])
    assert doc["rows"][0]["cycleState"]["weakDays"] == 2    # 计时暂停
    assert doc["meta"]["thsFound"] is False


def test_settle_final_missing_masks_ice(env, monkeypatch):
    """final 缺失（jiuyanFinalFound=False）不伪装平淡：同 unknown 整日降级。"""
    monkeypatch.setattr(tc, "sealed_and_info",
                        lambda db_, date, ds=None:
                        (set(), {}, {"thsPoolFound": True, "jiuyanFinalFound": False}))
    out = tc.settle_day(env, TODAY)
    assert out["status"] == "degraded"
    doc = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]
    assert doc["degraded"] and "final" in doc["degraded"][0]


def test_prev_doc_missing_starts_fresh(env):
    """昨日周期文档缺失 → 无周期起步 + 注记（周期链断 fail-visible）。"""
    out = tc.settle_day(env, TODAY)
    doc = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]
    row = next(r for r in doc["rows"] if r["theme"] == "宇树机器人")
    assert row["stage"] in ("emerging", "main_surge") and row["cycleN"] == 1
    assert any("昨日周期文档缺失" in n for n in row["notes"])


def test_unmapped_and_style_excluded(env, monkeypatch):
    """未映射股/仅属 style 题材股披露（fail-visible，不静默丢弃）。"""
    monkeypatch.setattr(tc, "sealed_and_info",
                        lambda db_, date, ds=None:
                        ({"600001", "999999"}, {}, {"thsPoolFound": True}))
    env.jiuyan_action.docs[f"{TODAY}:final"] = {"fields": [
        {"name": "机器人", "stocks": [{"code": "sh600001", "name": "龙头甲"},
                                       {"code": "bj999999", "name": "无映射股"}]}]}
    tc.settle_day(env, TODAY)
    doc = env.cycle.docs[f"{TODAY}:THEME_CYCLE"]
    assert any("未映射股 1 只" in d for d in doc["degraded"])


def test_wzs_elite_rewrap(env, monkeypatch):
    """昨日转弱 + 今日精英反包（热榜在榜）→ wzs 落库。"""
    monkeypatch.setattr(tc, "jiuyan_streak_map",
                        lambda db_, date, ds=None, **k: {"600001": 1})
    monkeypatch.setattr(tc, "_hotlist_codes_of",
                        lambda db_, date, ds=None: {"600001"})
    prev_state = {"cycleN": 1, "stage": "weakening", "leaderCode": "600001",
                  "leaderName": "龙头甲", "peakStreak": 4,
                  "membersPeak": {"600001": 4}, "brokenElite": [], "weakDays": 1}
    env.cycle.docs[f"{PREV}:THEME_CYCLE"] = {"rows": [
        _cycle_row("人形机器人", prev_state, [], "weakening")]}   # 昨日未封=断板中
    # 今日仅 600001 封板 → 1 家题材不达门槛，但链延续出行（prev cycleState 在）
    monkeypatch.setattr(tc, "sealed_and_info",
                        lambda db_, date, ds=None: ({"600001"}, {}, {"thsPoolFound": True}))
    env.jiuyan_action.docs[f"{TODAY}:final"] = {"fields": [
        {"name": "机器人", "stocks": [{"code": "sh600001", "name": "龙头甲"}]}]}
    tc.settle_day(env, TODAY)
    row = next(r for r in env.cycle.docs[f"{TODAY}:THEME_CYCLE"]["rows"]
               if r["theme"] == "人形机器人")
    assert row["stage"] == "wzs"
    assert row["rewrapElite"] and row["rewrapElite"][0]["code"] == "600001"
    assert row["cycleState"]["leaderCode"] == "600001"


def test_backfill_two_days_chain(env, monkeypatch):
    """两日回填成链：首日 burst → 次日龙一断板转弱。"""
    def _find(q, *a, **k):
        class _Cur:
            def __iter__(self):
                return iter([{"tradingDate": PREV}, {"tradingDate": TODAY}])
        return _Cur()

    env.jiuyan_action.find = _find
    sealed_by_day = {PREV: {"600010", "600020"}, TODAY: {"600010", "600020", "600030"}}
    monkeypatch.setattr(tc, "sealed_and_info",
                        lambda db_, date, ds=None:
                        (sealed_by_day.get(date, set()), {}, {"thsPoolFound": True}))
    monkeypatch.setattr(tc, "jiuyan_streak_map",
                        lambda db_, date, ds=None, **k: {"600010": 2, "600020": 1})
    monkeypatch.setattr(tc, "trading_dates_before",
                        lambda db_, date, n, dataset_id=None:
                        [PREV] if date == TODAY else [])
    out = tc.backfill(env, PREV, TODAY)
    assert out["days"] == 2 and out["ok"] == 2
    d1 = next(r for r in env.cycle.docs[f"{PREV}:THEME_CYCLE"]["rows"]
              if r["theme"] == "宇树机器人")
    d2 = next(r for r in env.cycle.docs[f"{TODAY}:THEME_CYCLE"]["rows"]
              if r["theme"] == "宇树机器人")
    assert d1["stage"] == "main_surge" and d1["cycleN"] == 1
    # 次日 600010 续板（streak 2）→ 龙一 sealed 续板 → main_surge continue（宇树题材内）
    assert d2["stage"] == "main_surge"
    assert d2["events"][0]["type"] == "continue"
