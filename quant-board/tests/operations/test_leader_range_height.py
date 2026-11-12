# -*- coding: utf-8 -*-
"""龙一区间高度 N天M板 随空间龙一行落库（2026-11-12 用户修复）。

节点龙头列未封板（断板反包候选）旧显「断板反包」琥珀徽章占高度位，用户判不正确：
应显区间高度 N天M板。单源=韭研 num（_jiuyan_days_boards 解析）：封板龙一=当日 num，
断板龙一=最近封板日（poolDay）num；连板语义仍一律 streak（不复活 M 冒充连板）。
零 DB 零 jev（硬红线 §1.2-7）：sealed_and_info / jiuyan_streak_map 全 monkeypatch。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as J
import backend.operations.theme_leader_baseline as B

D0, PD = "2026-11-11", "2026-11-06"


class _Col:
    def __init__(self):
        self.docs = {}

    def replace_one(self, q, doc, upsert=False):
        self.docs[q["_id"]] = doc

    def find_one(self, q=None, projection=None):
        for d in self.docs.values():
            if all(d.get(k) == v for k, v in (q or {}).items()):
                return dict(d)
        return None


class FakeDb:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, _Col())


def _fixture(monkeypatch, *, pool_num="5天5板", today_num="4天4板"):
    def fake_sealed(db_, date, dataset_id=None):
        if date == D0:
            return {"603366"}, {"603366": {}}, {"thsPoolFound": True}
        return {"601599"}, {"601599": {}}, {"thsPoolFound": True}

    monkeypatch.setattr(B, "sealed_and_info", fake_sealed)
    monkeypatch.setattr(J, "jiuyan_streak_map",
                        lambda db_, date, dataset_id=None:
                        {"603366": 4} if date == D0 else {"601599": 5})
    db = FakeDb()
    db["jiuyan_action"].replace_one(
        {"_id": f"{D0}:final"},
        {"_id": f"{D0}:final", "fields": [
            {"name": "光伏", "stocks": [
                {"code": "sh603366", "name": "日出东方", "time": "09:25",
                 "num": today_num}]}]})
    db["jiuyan_action"].replace_one(
        {"_id": f"{PD}:final"},
        {"_id": f"{PD}:final", "fields": [
            {"name": "光伏", "stocks": [
                {"code": "sh601599", "name": "浙文影业", "time": "10:07",
                 "num": pool_num}]}]})
    return db


def _rows(db, gains):
    return B.day_leader_rows(db, D0, space_mode=True, pool_dates=[PD],
                             gain_fetcher=lambda codes, end: gains,
                             day_change_fetcher=lambda codes, date:
                                 {c: -2.0 for c in codes})


def test_unsealed_leader_carries_pool_day_range_height(monkeypatch):
    """断板龙一（今日未封）days/boards=最近封板日 num；streak/time 如实 None。"""
    db = _fixture(monkeypatch)
    rows, _m = _rows(db, {"603366": 55.0, "601599": 70.0})
    row = rows[0]
    assert row["code"] == "601599" and row["leaderSealedToday"] is False
    assert row["streak"] is None and row["poolDay"] == PD
    assert row["days"] == 5 and row["boards"] == 5, "区间高度截至最近封板日 num"


def test_sealed_leader_carries_today_range_height(monkeypatch):
    """封板龙一 days/boards=当日 num；真连板仍 streak（4天4板→streak 4）。"""
    db = _fixture(monkeypatch)
    rows, _m = _rows(db, {"603366": 90.0, "601599": 70.0})
    row = rows[0]
    assert row["code"] == "603366" and row["leaderSealedToday"] is True
    assert row["streak"] == 4 and row["days"] == 4 and row["boards"] == 4


def test_num_missing_range_height_none_not_fabricated(monkeypatch):
    """num 不可解析 → days/boards=None（宁缺毋猜）；histStreak 仍供空间板判定。"""
    db = _fixture(monkeypatch, pool_num=None)
    rows, _m = _rows(db, {"603366": 55.0, "601599": 70.0})
    row = rows[0]
    assert row["code"] == "601599", "高度≥2 由 histStreak 保证，不因 num 缺被剔"
    assert row["days"] is None and row["boards"] is None


def test_default_streak_mode_range_height_absent(monkeypatch):
    """历史窗口/基线口径（非 space_mode）行形状不漂移：days/boards=None。"""
    db = _fixture(monkeypatch)
    rows, _m = B.day_leader_rows(db, D0)
    assert rows[0]["code"] == "603366"
    assert rows[0]["days"] is None and rows[0]["boards"] is None
