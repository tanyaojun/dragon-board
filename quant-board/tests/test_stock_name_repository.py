from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.data.stock_name_repository import StockNameRepository


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def sort(self, keys) -> "FakeCursor":
        sort_keys = list(keys if isinstance(keys, list) else [keys])
        for key, direction in reversed(sort_keys):
            self.rows.sort(key=lambda row: row.get(key) or "", reverse=int(direction) < 0)
        return self

    def limit(self, count: int) -> "FakeCursor":
        if count and count > 0:
            self.rows = self.rows[:count]
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeCollection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def find(self, query: dict[str, Any] | None = None) -> FakeCursor:
        return FakeCursor([dict(row) for row in self.rows if _matches(row, query or {})])

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return next(iter(self.find(query)), None)


class FakeMongoDatabase(dict):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def test_stock_name_repository_lists_active_names_with_filters_and_exact_code() -> None:
    repo = StockNameRepository(
        FakeMongoDatabase(
            {
                "stock_names": FakeCollection(
                    [
                        _stock("600001", "浦发银行", market="SH", stock_type="stock"),
                        _stock("000001", "平安银行", market="SZ", stock_type="stock"),
                        _stock("159001", "测试ETF", market="SZ", stock_type="etf"),
                        _stock("430001", "退市样本", market="BJ", stock_type="stock", active=False),
                    ]
                )
            }
        )
    )

    assert [item["code"] for item in repo.list_names()] == ["000001", "159001", "600001"]
    assert [item["code"] for item in repo.list_names(market="sh")] == ["600001"]
    assert [item["code"] for item in repo.list_names(type="etf")] == ["159001"]
    assert [item["code"] for item in repo.list_names(active=False)] == ["430001"]
    assert repo.get_by_code("600001")["name"] == "浦发银行"
    assert repo.get_by_code("430001") is None
    assert repo.get_by_code("430001", active=False)["name"] == "退市样本"


def test_stock_name_repository_search_ranks_match_types_and_sorts_by_code() -> None:
    repo = StockNameRepository(
        FakeMongoDatabase(
            {
                "stock_names": FakeCollection(
                    [
                        _stock("001005", "又见abc", pinyin_initials="", pinyin_full=""),
                        _stock("001002", "无关", pinyin_initials="abcx", pinyin_full=""),
                        _stock("abc100", "代码前缀", pinyin_initials="", pinyin_full=""),
                        _stock("001003", "无关", pinyin_initials="", pinyin_full="abcquanpin"),
                        _stock("001001", "证券abc", pinyin_initials="", pinyin_full=""),
                        _stock("001000", "abc证券", pinyin_initials="", pinyin_full=""),
                        _stock("abc", "精确代码", pinyin_initials="", pinyin_full=""),
                        _stock("000999", "abc停用", active=False),
                    ]
                )
            }
        )
    )

    results = repo.search("abc", limit=20)

    assert [item["code"] for item in results] == [
        "abc",
        "abc100",
        "001000",
        "001001",
        "001005",
        "001002",
        "001003",
    ]


def test_stock_name_api_contract(monkeypatch) -> None:
    repo = StockNameRepository(
        FakeMongoDatabase(
            {
                "stock_names": FakeCollection(
                    [
                        _stock("600001", "浦发银行", market="SH", pinyin_initials="pfyh"),
                        _stock("000001", "平安银行", market="SZ", pinyin_initials="payh"),
                    ]
                )
            }
        )
    )
    import backend.main as main

    monkeypatch.setattr(main, "get_stock_name_repository", lambda: repo)
    client = TestClient(main.app)

    names = client.get("/api/stocks/names", params={"market": "SH"})
    detail = client.get("/api/stocks/names/600001")
    search = client.get("/api/stocks/search", params={"q": "pf", "limit": 5})

    assert names.status_code == 200
    assert names.json()["source"] == "mongodb"
    assert [item["code"] for item in names.json()["stocks"]] == ["600001"]
    assert detail.status_code == 200
    assert detail.json()["stock"]["name"] == "浦发银行"
    assert search.status_code == 200
    assert [item["code"] for item in search.json()["stocks"]] == ["600001"]


def _stock(
    code: str,
    name: str,
    *,
    market: str = "SH",
    stock_type: str = "stock",
    active: bool = True,
    pinyin_initials: str = "",
    pinyin_full: str = "",
) -> dict[str, Any]:
    return {
        "code": code,
        "name": name,
        "market": market,
        "type": stock_type,
        "active": active,
        "nameNormalized": "".join(name.split()),
        "pinyinInitials": pinyin_initials,
        "pinyinFull": pinyin_full,
    }


def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        value = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$ne" in expected and value == expected["$ne"]:
                return False
            continue
        if value != expected:
            return False
    return True
