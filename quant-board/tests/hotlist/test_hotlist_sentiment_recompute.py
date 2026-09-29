# -*- coding: utf-8 -*-
"""hotlist_sentiment 强制重算（displayStatus 补跑后的口径刷新）单测。

覆盖：重算前备份旧文档、before/after 摘要、dry-run 不覆盖。
"""
from backend.services.theme.hotlist_sentiment_compute import (
    HotListSentimentComputeService,
    _status_source_summary,
)


class _FakeCollection:
    def __init__(self, docs=None):
        self._docs = list(docs or [])
        self.inserted = []
        self.replaced = []

    def find_one(self, query=None, projection=None):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in (query or {}).items()):
                return doc
        return None

    def insert_one(self, doc):
        self.inserted.append(doc)
        self._docs.append(doc)

    def replace_one(self, query, doc, upsert=False):
        self.replaced.append(doc)
        for i, existing in enumerate(self._docs):
            if all(existing.get(k) == v for k, v in (query or {}).items()):
                self._docs[i] = doc
                return
        self._docs.append(doc)


class _FakeDB:
    def __init__(self):
        self._colls = {}

    def __getitem__(self, name):
        return self._colls.setdefault(name, _FakeCollection())


_BEFORE = {
    "_id": "ds:half_hour:2026-09-10",
    "datasetId": "ds",
    "snapshotType": "half_hour",
    "tradingDate": "2026-09-10",
    "slotTime": "EOD",
    "computedAt": 1789025414,
    "stage": "cooling",
    # 2026-09-10 8 类退役：分布只存在于 metrics.layers.<layer>.stageCounts（5 态 + unknown）
    "metrics": {
        "layers": {"all": {"stageCounts": {"unknown": 235}}},
        "statusSourceCounts": {"displayStatus": 0, "fallback": 235},
    },
}

_AFTER = {
    "_id": "ds:half_hour:2026-09-10",
    "datasetId": "ds",
    "snapshotType": "half_hour",
    "tradingDate": "2026-09-10",
    "slotTime": "EOD",
    "computedAt": 1789026999,
    "stage": "cooling",
    "metrics": {
        "layers": {"all": {"stageCounts": {"ignition": 40, "unknown": 195}}},
        "statusSourceCounts": {"displayStatus": 200, "fallback": 35},
    },
}


def test_status_source_summary_tolerates_missing_shapes():
    assert _status_source_summary(None) is None
    assert _status_source_summary({})["statusSourceCounts"] is None
    summary = _status_source_summary(_BEFORE)
    assert summary["statusSourceCounts"]["fallback"] == 235
    assert summary["stageCounts"] == {"unknown": 235}
    assert "statusCounts" not in summary  # 8 类字段不复活


def test_recompute_dry_run_backs_up_and_does_not_overwrite(monkeypatch):
    db = _FakeDB()
    db["hotlist_sentiment"]._docs.append(dict(_BEFORE))
    service = HotListSentimentComputeService(db)
    monkeypatch.setattr(
        HotListSentimentComputeService,
        "_compute_and_persist",
        lambda self, dataset_id, snapshot_type, trading_date, persist=True: dict(_AFTER),
    )

    result = service.recompute("ds", "half_hour", "2026-09-10", persist=False)

    assert result["applied"] is False
    assert result["before"]["statusSourceCounts"] == {"displayStatus": 0, "fallback": 235}
    assert result["after"]["statusSourceCounts"] == {"displayStatus": 200, "fallback": 35}
    assert result["after"]["stageCounts"] == {"ignition": 40, "unknown": 195}
    # 备份写入新集合，不动原文档
    backups = db["hotlist_sentiment_recompute_backup"].inserted
    assert len(backups) == 1
    assert backups[0]["sourceId"] == "ds:half_hour:2026-09-10"
    assert backups[0]["metrics"]["statusSourceCounts"]["fallback"] == 235
    assert db["hotlist_sentiment"].replaced == []  # dry-run 不覆盖
    assert db["hotlist_sentiment"]._docs[0]["computedAt"] == 1789025414


def test_recompute_apply_persists(monkeypatch):
    db = _FakeDB()
    db["hotlist_sentiment"]._docs.append(dict(_BEFORE))
    service = HotListSentimentComputeService(db)
    monkeypatch.setattr(
        HotListSentimentComputeService,
        "_compute_and_persist",
        lambda self, dataset_id, snapshot_type, trading_date, persist=True: dict(_AFTER),
    )

    result = service.recompute("ds", "half_hour", "2026-09-10", persist=True)

    assert result["applied"] is True
    assert result["after"]["stageCounts"] == {"ignition": 40, "unknown": 195}


def test_recompute_without_existing_document_skips_backup(monkeypatch):
    db = _FakeDB()
    service = HotListSentimentComputeService(db)
    monkeypatch.setattr(
        HotListSentimentComputeService,
        "_compute_and_persist",
        lambda self, dataset_id, snapshot_type, trading_date, persist=True: dict(_AFTER),
    )

    result = service.recompute("ds", "half_hour", "2026-09-10", persist=False)

    assert result["before"] is None
    assert db["hotlist_sentiment_recompute_backup"].inserted == []
