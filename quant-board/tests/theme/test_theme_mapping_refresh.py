from datetime import UTC, datetime

import pytest

from backend.services.theme import mapping_refresh


class _FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find(self, query=None, projection=None):
        return self

    def sort(self, key):
        self.docs = sorted(self.docs, key=lambda doc: str(doc.get("id", "")))
        return self

    def __iter__(self):
        return iter(self.docs)

    def find_one(self, query=None, *args, **kwargs):
        if not query:
            return self.docs[0] if self.docs else None
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None

    def count_documents(self, query=None):
        return len(self.docs)

    def replace_one(self, query, doc, upsert=False):
        for index, current in enumerate(self.docs):
            if all(current.get(key) == value for key, value in query.items()):
                self.docs[index] = doc
                return
        if upsert:
            self.docs.append(doc)

    def delete_many(self, query=None):
        before = len(self.docs)
        if query is None:
            self.docs = []
        else:
            self.docs = [
                doc for doc in self.docs
                if not all(doc.get(key) == value for key, value in query.items())
            ]
        return _Deleted(before - len(self.docs))

    def insert_many(self, docs, ordered=False):
        self.docs.extend(docs)
        return _Inserted(len(docs))


class _Deleted:
    def __init__(self, count):
        self.deleted_count = count


class _Inserted:
    def __init__(self, count):
        self.inserted_count = count


def _make_database():
    return {
        "themes": _FakeCollection([
            {"id": "9", "name": "旧题材", "zsCode": "", "createdAt": None},
        ]),
        "theme_stock_mappings": _FakeCollection(),
        "theme_metadata": _FakeCollection([
            {"key": "directoryScanCursor", "value": "9", "updatedAt": None},
            {"key": "version", "value": "v", "updatedAt": None},
            {"key": "lastUpdate", "value": "", "updatedAt": None},
        ]),
    }


def test_refresh_scans_ahead_and_adds_new_theme(monkeypatch):
    database = _make_database()

    def fake_fetch(theme_id):
        if theme_id == "9":
            return {"errcode": "0", "Name": "旧题材", "StockList": [{"StockID": "000001"}]}
        if theme_id == "10":
            return {"errcode": "0", "Name": "新题材10", "StockList": [{"StockID": "000002"}]}
        return {"errcode": "0", "Name": "", "StockList": []}

    monkeypatch.setattr(mapping_refresh, "_fetch_theme_detail", fake_fetch)

    result = mapping_refresh.refresh_theme_stock_mappings(
        database,
        directory_scan_ahead=3,
    )

    assert result["ok"] is True
    assert result["directoryScanned"] == 3
    assert result["directoryAdded"] == 1
    assert result["directoryEmptyIds"] == ["11", "12"]
    assert result["directoryScanCursor"] == 12
    assert {doc["id"] for doc in database["themes"].docs} == {"9", "10"}
    assert {doc["themeId"] for doc in database["theme_stock_mappings"].docs} == {"9", "10"}


def test_refresh_scan_disabled_preserves_cursor(monkeypatch):
    database = _make_database()

    def fake_fetch(theme_id):
        return {"errcode": "0", "Name": "旧题材", "StockList": [{"StockID": "000001"}]}

    monkeypatch.setattr(mapping_refresh, "_fetch_theme_detail", fake_fetch)

    result = mapping_refresh.refresh_theme_stock_mappings(
        database,
        directory_scan_ahead=0,
    )

    assert result["directoryScanned"] == 0
    assert result["directoryScanCursor"] == 9
    assert {doc["id"] for doc in database["themes"].docs} == {"9"}


def test_refresh_counts_nonexistent_as_empty_not_failed(monkeypatch):
    # 真实 API 对无效 ID 返回 errcode != 0 → _fetch_theme_detail 返回 None → 应计 empty 而非 failed
    database = _make_database()

    def fake_fetch(theme_id):
        if theme_id == "9":
            return {"errcode": "0", "Name": "旧题材", "StockList": [{"StockID": "000001"}]}
        return None  # errcode != 0（该 ID 无题材）

    monkeypatch.setattr(mapping_refresh, "_fetch_theme_detail", fake_fetch)
    result = mapping_refresh.refresh_theme_stock_mappings(database, directory_scan_ahead=3)
    assert result["directoryEmptyIds"] == ["10", "11", "12"]
    # 空洞 ID 不误判为失败（应修复：directoryFailedIds 为空）
    assert result["directoryFailedIds"] == []
    assert result["directoryScanCursor"] == 12


# ── 目录 diff 提示源退役（2026-11-19 全直连裁决：wzs 目录 dump 清理） ─────────
def test_directory_diff_retired_discloses_without_third_party(monkeypatch):
    """wzs 目录提示源退役：diff_only 零动作+结构化披露，不触第三方/官方 fetch。"""
    database = _make_database()
    calls = []
    monkeypatch.setattr(mapping_refresh, "_fetch_theme_detail",
                        lambda tid: calls.append(tid) or None)
    result = mapping_refresh.refresh_theme_stock_mappings(database, diff_only=True)
    assert result["ok"] is True
    assert result["directoryDiffAttempted"] is True
    assert str(result["directoryDiffError"]).startswith("wzs_directory_hint_retired")
    assert result["directoryDiffAdded"] == 0 and result["directoryDiffRenamed"] == 0
    assert calls == []                      # 退役后 diff 不拉官方详情
    assert {d["id"] for d in database["themes"].docs} == {"9"}


def test_directory_diff_retired_symbol_removed():
    """guard：wzs 目录 fetch/URL 不得复活（全直连红线）。"""
    assert not hasattr(mapping_refresh, "_fetch_wzs_theme_directory")
    assert not hasattr(mapping_refresh, "WZS_THEME_DIRECTORY_URL")


def test_full_refresh_still_discloses_retired_diff(monkeypatch):
    """主刷新路径同样披露退役状态（fail-visible），盲扫兜底不受影响。"""
    database = _make_database()
    monkeypatch.setattr(mapping_refresh, "_fetch_theme_detail",
                        lambda tid: {"errcode": "0", "Name": "旧题材",
                                     "StockList": [{"StockID": "000001"}]})
    result = mapping_refresh.refresh_theme_stock_mappings(database, directory_scan_ahead=0)
    assert result["ok"] is True
    assert str(result["directoryDiffError"]).startswith("wzs_directory_hint_retired")
