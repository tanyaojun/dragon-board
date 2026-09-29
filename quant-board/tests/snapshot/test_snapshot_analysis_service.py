# -*- coding: utf-8 -*-
"""snapshot_analysis_service 单测（2026-08-23 前后端分离 G4 子工程 2）。"""
import pytest

from backend.data.cache import snapshot_cache
from backend.services.snapshot_analysis_service import analyze_snapshot_and_persist


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


class _FakeDB:
    def __init__(self):
        self._colls: dict[str, _FakeCollection] = {"snapshot_analysis": _FakeCollection()}

    def __getitem__(self, name):
        return self._colls.setdefault(name, _FakeCollection())


class FakeRepo:
    def __init__(self, frames):
        self.frames = frames

    def load_frame_bundles(self, *args, **kwargs):
        frames = list(self.frames)
        if kwargs.get("sort") == "desc":
            frames.sort(key=lambda f: int(f.get("timestamp") or 0), reverse=True)
            limit = kwargs.get("limit")
            if limit and limit > 0:
                frames = frames[:limit]
        return frames


def _stock(code, rank, turnover):
    return {
        "code": code, "name": f"股{code}", "rank": rank, "avgRankNum": float(rank),
        "change": 3.0, "volumeRatio": 1.5, "zlje": 1e8, "zljzb": 12.0,
        "turnover": turnover, "turnoverRate": 5.0,
    }


def _frame(ts, date, slot, stocks):
    return {
        "tradingDate": date, "slotTime": slot, "type": "half_hour", "timestamp": ts,
        "rows": [{"code": s["code"], "name": s["name"], "rank": s["rank"], "avgRankNum": s["avgRankNum"],
                  "turnover": s["turnover"], "volumeRatio": s["volumeRatio"], "turnoverRate": s["turnoverRate"]} for s in stocks],
        "hotlist": [], "stocks": stocks,
        "sentiment": {"phaseName": "启动"}, "marketStats": {},
    }


@pytest.fixture(autouse=True)
def _disable_redis(monkeypatch):
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(redis_client=None, ttl_seconds=60, empty_ttl_seconds=10),
    )


def test_analyze_snapshot_persists_observation(monkeypatch):
    stocks = [_stock("600000", 1, 100.0), _stock("600001", 2, 200.0), _stock("600002", 3, 300.0)]
    frames = [
        _frame(1, "2026-08-13", "14:00", stocks),
        _frame(2, "2026-08-14", "14:00", stocks),
    ]
    db = _FakeDB()
    server_frames = list(frames)

    class _RepoWrapper:
        def load_frame_bundles(self, *args, **kwargs):
            f = list(server_frames)
            if kwargs.get("sort") == "desc":
                f.sort(key=lambda x: int(x.get("timestamp") or 0), reverse=True)
            return f

        def upsert_snapshot_analysis(self, dataset_id, snapshot_id, code, analysis):
            db["snapshot_analysis"].replace_one(
                {"datasetId": dataset_id, "snapshotId": snapshot_id, "code": code}, analysis, upsert=True
            )

    snapshot_frame = {"tradingDate": "2026-08-14", "slotTime": "current", "stocks": stocks}
    count = analyze_snapshot_and_persist(_RepoWrapper(), "ds", "s1", "half_hour", snapshot_frame)
    assert count >= 1
    docs = db["snapshot_analysis"]._docs
    assert all("observation" in d for d in docs)
    assert all("displayStatus" in d for d in docs)
    # cycle 必须一并落库：hotlist join 侧用 analysis["cycle"]["stage"] 判"阶段是否缺失"，
    # 缺它会把"字段未持久化"误判成"阶段真缺失"（2026-09-10 stageMissing 假阳性）。
    assert all("cycle" in d for d in docs)
