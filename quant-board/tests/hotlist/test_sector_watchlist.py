# -*- coding: utf-8 -*-
"""sector_pulse.get_watchlist：V4-G 盯盘票清单（2026-11-01，Q1a/Q2a/Q4a 口径）。

单元注入式（生产链 monkeypatch + quotes_fetcher 注入；真实库集成由
test_sector_name_check 同款 restore 库覆盖 pulse 链本体的存量用例保护）。
零网络零模型调用。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from backend.operations import sector_pulse as sp

TODAY = "2026-10-26"
NOW = datetime(2026, 10, 26, 10, 33, 0)


def _pulse_payload():
    """构造 pulse payload：两个候选板块（机器人/AI算力）+ 一个非候选。"""
    def row(board, hint, strong, streaks):
        e = {"board": board, "yesterdayNode": "weakening", "pulse":
             {"pctMean": 2.0, "redRatio": 0.6, "memberN": 4, "quotedN": 4,
              "redN": 3, "amountSum": 1e8},
             "hint": hint, "strongN": len(strong),
             "strongQuotedN": len(strong), "strongRedN": 1,
             "strongRedRatio": 0.5 if strong else None,
             "strongCodes": list(strong), "strongStreaks": streaks,
             "amountPct": 0.9, "amountPctN": 30,
             "volRatioMedian": 1.2, "volFrame": "10:30"}
        return e

    return {"ok": True, "source": "live", "evidenceStage": "intraday",
            "candidates": [row("机器人", True, ["600001", "600002"],
                               {"600001": 3, "600002": 2}),
                           row("AI算力", False, ["300001"], {"300001": 2})],
            "all": [row("机器人", None, ["600001", "600002"], {}),
                    row("AI算力", None, ["300001"], {}),
                    row("大消费", None, [], {})]}


class _FakeDb:
    pass


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(sp, "get_pulse_cached",
                        lambda db, d, ds, now=None: _pulse_payload())
    monkeypatch.setattr(sp, "trading_dates_before",
                        lambda db, d, n, dataset_id=None:
                        ["2026-10-21", "2026-10-22", "2026-10-23"] if n == 3
                        else ["2026-10-23"])
    # 昨日 space_mode 龙一：机器人→600001(3板,growth,断板反包)；AI算力→300001；
    # 大消费行（非候选板块→不入清单）
    monkeypatch.setattr(sp, "day_leader_rows", lambda db, d, ds, prev_date=None,
                         space_mode=False, pool_dates=None: (
        [{"board": "机器人", "code": "sz600001", "name": "金科股份",
          "streak": 3, "segment": "growth", "gain10": 88.5,
          "leaderSealedToday": False, "boardCodes": ["sz600001"]},
         {"board": "AI算力", "code": "sz300001", "name": "凡拓数创",
          "streak": 2, "segment": "growth", "gain10": 40.0,
          "leaderSealedToday": True, "boardCodes": ["sz300001"]},
         {"board": "大消费", "code": "600999", "name": "无关板块龙一",
          "streak": 5, "segment": "main", "gain10": 30.0,
          "leaderSealedToday": True, "boardCodes": []}], {}))
    monkeypatch.setattr(sp, "_jiuyan_name_map",
                        lambda db, dates: {"600001": "金科股份",
                                           "600002": "天房发展",
                                           "300001": "凡拓数创"})


def test_groups_roles_and_dedup(env):
    """组=candidates；票=龙一+strong；龙一同时连板≥2 → 只留 leader 角色。"""
    prices = {"sz600001": (11.0, 10.0), "600002": (9.8, 10.0),
              "sz300001": (20.0, 21.0)}
    out = sp.get_watchlist(_FakeDb(), TODAY, now=NOW,
                           quotes_fetcher=lambda codes: dict(prices))
    assert out["ok"] is True and out["prevDate"] == "2026-10-23"
    g = {x["board"]: x for x in out["groups"]}
    assert set(g) == {"机器人", "AI算力"}   # 非候选「大消费」不进清单
    tk = g["机器人"]["tickets"]
    assert [t["role"] for t in tk] == ["leader", "strong"]
    assert tk[0]["code"] == "600001" and tk[0]["streak"] == 3
    assert tk[0]["leaderSealedToday"] is False   # 断板反包候选如实透出
    assert tk[1]["code"] == "600002" and tk[1]["streak"] == 2
    assert g["AI算力"]["tickets"][0]["role"] == "leader"   # 300001 龙一兼 strong → 仅 leader


def test_quotes_pct_and_red(env):
    prices = {"sz600001": (11.0, 10.0), "600002": (9.8, 10.0),
              "sz300001": (20.0, 21.0)}
    out = sp.get_watchlist(_FakeDb(), TODAY, now=NOW,
                           quotes_fetcher=lambda codes: dict(prices))
    tk = {t["code"]: t for x in out["groups"] for t in x["tickets"]}
    assert tk["600001"]["pct"] == 10.0 and tk["600001"]["red"] is True
    assert tk["600002"]["pct"] == -2.0 and tk["600002"]["red"] is False
    assert tk["300001"]["pct"] == -4.76


def test_quotes_unavailable_fail_visible(env):
    """报价不可考 → 票 pct/red 全 None + reason 透出，不伪 0。"""
    out = sp.get_watchlist(_FakeDb(), TODAY, now=NOW,
                           quotes_fetcher=lambda codes: None)
    assert out["ok"] is True and "报价不可考" in out["reason"]
    for x in out["groups"]:
        for t in x["tickets"]:
            assert t["pct"] is None and t["red"] is None


def test_leader_baseline_missing_fail_visible(monkeypatch, env):
    """昨日 THS 池缺失 → leaderReason 透出，strong 票照常（fail-visible 不静默）。"""
    monkeypatch.setattr(sp, "day_leader_rows", lambda *a, **k: (None, {}))
    prices = {"600001": (11.0, 10.0), "600002": (9.8, 10.0)}
    out = sp.get_watchlist(_FakeDb(), TODAY, now=NOW,
                           quotes_fetcher=lambda codes: dict(prices))
    assert out["ok"] is True and "THS 池缺失" in out["leaderReason"]
    g = {x["board"]: x for x in out["groups"]}
    assert [t["role"] for t in g["机器人"]["tickets"]] == ["strong", "strong"]


def test_no_candidates(env, monkeypatch):
    monkeypatch.setattr(sp, "get_pulse_cached",
                        lambda db, d, ds, now=None: {"ok": True,
                                                     "candidates": [], "all": []})
    out = sp.get_watchlist(_FakeDb(), TODAY, now=NOW,
                           quotes_fetcher=lambda codes: None)
    assert out["ok"] is True and out["groups"] == []
    assert "无弱转强候选" in out["reason"]


def test_pulse_unavailable(monkeypatch, env):
    monkeypatch.setattr(sp, "get_pulse_cached",
                        lambda db, d, ds, now=None: {"ok": False,
                                                     "reason": "mongodb_down"})
    out = sp.get_watchlist(_FakeDb(), TODAY, now=NOW,
                           quotes_fetcher=lambda codes: None)
    assert out["ok"] is False and "pulse_unavailable" in out["reason"]


def test_group_carries_board_level_readings(env):
    """组行透出缺口 2/3/5 读数（家数对比/核心票翻红/量级分位/量比），前端不重算。"""
    out = sp.get_watchlist(_FakeDb(), TODAY, now=NOW,
                           quotes_fetcher=lambda codes: {})
    g = {x["board"]: x for x in out["groups"]}["机器人"]
    assert g["strongN"] == 2 and g["strongRedRatio"] == 0.5
    assert g["amountPct"] == 0.9 and g["volRatioMedian"] == 1.2
    assert g["hint"] is True and g["yesterdayNode"] == "weakening"
