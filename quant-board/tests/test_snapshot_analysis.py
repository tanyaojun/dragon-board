# -*- coding: utf-8 -*-
"""snapshot_analysis 存储层单测（2026-08-23 前后端分离 G4 子工程 1）。"""
from backend.data.repositories.mongo_repository import MongoRepository


class _FakeCollection:
    def __init__(self):
        self._docs: list[dict] = []

    def replace_one(self, query, doc, upsert=False):
        for i, d in enumerate(self._docs):
            if all(d.get(k) == v for k, v in query.items()):
                self._docs[i] = doc
                return self
        self._docs.append(doc)
        return self

    def find(self, query, projection=None):
        out = []
        for d in self._docs:
            if all(self._match(d.get(k), v) for k, v in query.items()):
                if projection:
                    out.append({k: d[k] for k in projection if k != "_id"})
                else:
                    out.append({**d})
        return iter(out)

    @staticmethod
    def _match(actual, expected):
        if isinstance(expected, dict) and "$in" in expected:
            return actual in expected["$in"]
        return actual == expected


class _FakeDB:
    def __init__(self):
        self._colls: dict[str, _FakeCollection] = {}

    def __getitem__(self, name):
        self._colls.setdefault(name, _FakeCollection())
        return self._colls[name]


def _repo():
    return MongoRepository(_FakeDB())


def test_upsert_and_load_snapshot_analysis():
    repo = _repo()
    repo.upsert_snapshot_analysis("ds", "s1", "600000", {"observation": {"a": 1}, "displayStatus": {"label": "主升确认"}})
    repo.upsert_snapshot_analysis("ds", "s1", "600001", {"observation": {"b": 2}})
    repo.upsert_snapshot_analysis("ds", "s1", "600000", {"observation": {"a": 2}})  # 幂等覆盖
    got = repo.load_snapshot_analysis("ds", "s1")
    assert got["600000"]["observation"] == {"a": 2}
    assert "600001" in got
    assert got["600001"]["observation"] == {"b": 2}


def test_load_by_codes_and_empty():
    repo = _repo()
    assert repo.load_snapshot_analysis("ds", "s2") == {}
    repo.upsert_snapshot_analysis("ds", "s2", "000001", {"observation": {"x": 9}})
    repo.upsert_snapshot_analysis("ds", "s2", "000002", {"observation": {"y": 8}})
    only = repo.load_snapshot_analysis("ds", "s2", ["000002"])
    assert set(only.keys()) == {"000002"}
