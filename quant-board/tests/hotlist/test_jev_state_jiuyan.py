# -*- coding: utf-8 -*-
"""day_population fake-db 测试。

2026-10-05 批次D M1：v2 叙事构建器 build_jiuyan_label_narrative 及其测试随死代码
清理删除（生产调用方=jev_label_jiuyan.build_pilot_narrative，git 历史留档）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_label_jiuyan import day_population


class _FakeCol:
    def __init__(self, doc):
        self._doc = doc

    def find_one(self, *_a, **_k):
        return self._doc


class _FakeDb(dict):
    def __init__(self, doc):
        super().__init__()
        self["jiuyan_action"] = _FakeCol(doc)


def test_day_population_uses_final_only():
    doc = {"_id": "2026-09-30:final", "fields": [
        {"name": "公告", "stocks": [{"code": "sh600825", "name": "新华传媒"}]},
        {"name": "医药医疗", "stocks": [{"code": "sz000504", "name": "南华生物"}]},
    ]}
    pop = day_population(_FakeDb(doc), "2026-09-30")
    assert [(p["stock"]["code"], p["board"]) for p in pop] == [
        ("sh600825", "公告"), ("sz000504", "医药医疗")]


def test_day_population_missing_date_returns_empty():
    assert day_population(_FakeDb(None), "2026-09-30") == []
