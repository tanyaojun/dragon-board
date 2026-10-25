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


# ── 目录 diff（2026-10-25 修复：低段补号漏题） ──────────────────────────────
@pytest.fixture(autouse=True)
def _no_wzs_http(monkeypatch):
    """测试禁真实 HTTP：默认目录 diff 走「空目录」零动作（个别用例自行覆盖）。"""
    monkeypatch.setattr(mapping_refresh, "_fetch_wzs_theme_directory", lambda: [])


def test_directory_diff_adds_new_and_renames(monkeypatch):
    """目录 diff：新 ID 入库 + 改名 upsert；成分走官方端点（mock _fetch_theme_detail）。"""
    database = _make_database()

    monkeypatch.setattr(mapping_refresh, "_fetch_wzs_theme_directory", lambda: [
        {"ID": "9", "Name": "旧题材"},                       # 无变化 → 跳过
        {"ID": "397", "Name": "AI安全"},                     # 新 ID → 入库
        {"ID": "402", "Name": "俄乌重建"},                   # 新 ID → 入库
    ])

    def fake_fetch(theme_id):
        if theme_id == "9":
            return {"errcode": "0", "Name": "旧题材", "StockList": [{"StockID": "000001"}]}
        if theme_id == "397":
            return {"errcode": "0", "Name": "AI安全", "ZSCode": "AISEC",
                    "StockList": [{"StockID": "000839"}]}
        if theme_id == "402":
            return {"errcode": "0", "Name": "俄乌重建", "ZSCode": "RUREB",
                    "StockList": [{"StockID": "000338"}]}
        return None

    monkeypatch.setattr(mapping_refresh, "_fetch_theme_detail", fake_fetch)
    result = mapping_refresh.refresh_theme_stock_mappings(database, diff_only=True)
    assert result["directoryDiffAdded"] == 2 and result["directoryDiffRenamed"] == 0
    themes = {d["id"]: d for d in database["themes"].docs}
    assert themes["402"]["name"] == "俄乌重建" and themes["397"]["name"] == "AI安全"
    codes = {m["stockCode"] for m in database["theme_stock_mappings"].docs
             if m.get("themeId") == "402"}
    assert codes == {"000338"}
    assert result["themesFetched"] == 0          # diff_only 跳存量


def test_directory_diff_renames_existing(monkeypatch):
    database = _make_database()

    def fake_fetch(theme_id):
        return {"errcode": "0", "Name": "海南封关概念", "ZSCode": "HNSZ",
                "StockList": [{"StockID": "000613"}]}

    monkeypatch.setattr(mapping_refresh, "_fetch_theme_detail", fake_fetch)
    monkeypatch.setattr(mapping_refresh, "_fetch_wzs_theme_directory", lambda: [
        {"ID": "9", "Name": "海南封关概念"}])       # 库内 9=旧题材 → 改名
    result = mapping_refresh.refresh_theme_stock_mappings(database, diff_only=True)
    assert result["directoryDiffRenamed"] == 1 and result["directoryDiffAdded"] == 0
    assert database["themes"].docs[0]["name"] == "海南封关概念"


def test_directory_diff_failure_degrades_visibly(monkeypatch):
    """第三方目录拉取失败 → 结构化披露不炸主流程（fail-visible）。"""
    database = _make_database()

    def boom():
        raise RuntimeError("wzslinker 目录拉取失败: timeout")

    monkeypatch.setattr(mapping_refresh, "_fetch_wzs_theme_directory", boom)
    monkeypatch.setattr(mapping_refresh, "_fetch_theme_detail",
                        lambda tid: {"errcode": "0", "Name": "旧题材",
                                     "StockList": [{"StockID": "000001"}]})
    result = mapping_refresh.refresh_theme_stock_mappings(database, diff_only=True)
    assert result["directoryDiffError"].startswith("wzslinker 目录拉取失败")
    assert result["directoryDiffAdded"] == 0 and result["ok"] is True
