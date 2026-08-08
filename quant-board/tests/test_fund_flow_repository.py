from __future__ import annotations

from pymongo import UpdateOne

from backend.data.repositories.fund_flow_repository import (
    FundFlowRepository,
    project_cache_rows,
)


class FakeBulkResult:
    def __init__(self, upserted: int = 0, modified: int = 0) -> None:
        self.upserted_count = upserted
        self.modified_count = modified


class FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def sort(self, key, direction=1):
        reverse = direction < 0
        self._rows = sorted(self._rows, key=lambda row: row.get(key), reverse=reverse)
        return self

    def __iter__(self):
        return iter(self._rows)


class FakeCollection:
    def __init__(self) -> None:
        self.docs: list[dict] = []
        self.indexes: list[tuple[list, dict]] = []
        self.bulk_writes: list[list] = []

    def create_index(self, keys, unique: bool = False, name: str | None = None) -> None:
        self.indexes.append((keys, {"unique": unique, "name": name}))

    def bulk_write(self, operations: list, ordered: bool = False):
        self.bulk_writes.append(operations)
        upserted = 0
        modified = 0
        for op in operations:
            if not isinstance(op, UpdateOne):
                continue
            flt = op._filter
            matched = next(
                (d for d in self.docs if d.get("sessionDate") == flt.get("sessionDate") and d.get("code") == flt.get("code")),
                None,
            )
            replacement = dict(op._doc["$set"])
            if matched is None:
                self.docs.append(replacement)
                upserted += 1
            else:
                matched.update(replacement)
                modified += 1
        return FakeBulkResult(upserted=upserted, modified=modified)

    def find(self, query: dict):
        rows = [dict(d) for d in self.docs if all(d.get(k) == v for k, v in query.items())]
        return FakeCursor(rows)

    def find_one(self, query: dict | None = None, sort=None, projection=None):
        rows = [dict(d) for d in self.docs if not query or all(d.get(k) == v for k, v in query.items())]
        if sort:
            for key, direction in reversed(sort):
                rows.sort(key=lambda row: row.get(key), reverse=direction < 0)
        if not rows:
            return None
        row = rows[0]
        if projection:
            row = {k: row.get(k) for k, v in projection.items() if v}
        return row


class FakeMongoDatabase(dict):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def _doc(code: str, session_date: str, zlje: float = 1.0) -> dict:
    return {
        "code": code,
        "sessionDate": session_date,
        "tradingDate": session_date,
        "source": "ths_main_monitor",
        "sourceTs": 1,
        "total": {"zlje": zlje, "buyAmount": 2.0, "sellAmount": 1.0},
        "buckets": [],
    }


def test_upsert_many_inserts_and_overwrites_by_session_code() -> None:
    db = FakeMongoDatabase()
    repo = FundFlowRepository(db)

    n = repo.upsert_many([_doc("000001", "2026-08-07", 10.0), _doc("000002", "2026-08-07", 5.0)])
    assert n == 2
    # 同 {sessionDate, code} 覆盖（$set 更新）
    n2 = repo.upsert_many([_doc("000001", "2026-08-07", 99.0)])
    assert n2 == 1
    rows = list(db["fund_flow_l2"].docs)
    assert len(rows) == 2
    assert next(r for r in rows if r["code"] == "000001")["total"]["zlje"] == 99.0


def test_upsert_many_empty_returns_zero() -> None:
    repo = FundFlowRepository(FakeMongoDatabase())
    assert repo.upsert_many([]) == 0


def test_load_latest_session_returns_most_recent_sorted() -> None:
    db = FakeMongoDatabase()
    repo = FundFlowRepository(db)
    repo.upsert_many(
        [
            _doc("000002", "2026-08-06", 1.0),
            _doc("000001", "2026-08-07", 2.0),
            _doc("000003", "2026-08-07", 3.0),
        ]
    )

    session_date, rows = repo.load_latest_session()

    assert session_date == "2026-08-07"
    assert [r["code"] for r in rows] == ["000001", "000003"]


def test_load_latest_session_empty_db() -> None:
    repo = FundFlowRepository(FakeMongoDatabase())
    assert repo.load_latest_session() == ("", [])


def test_ensure_indexes_unique() -> None:
    db = FakeMongoDatabase()
    repo = FundFlowRepository(db)
    repo.ensure_indexes()
    assert db["fund_flow_l2"].indexes == [
        ([("sessionDate", 1), ("code", 1)], {"unique": True, "name": "fund_flow_l2_unique"})
    ]


def test_project_cache_rows_projects_total_zlje_summary() -> None:
    docs = [
        {
            "code": "000001",
            "sessionDate": "2026-08-07",
            "tradingDate": "2026-08-07",
            "source": "ths_main_monitor",
            "sourceTs": 123,
            "total": {"zlje": -31_000_000.0, "buyAmount": 268_000_000.0, "sellAmount": 299_000_000.0},
            "buckets": [],
        },
        {"code": "000002", "sessionDate": "2026-08-07"},  # 缺 total.zlje → 跳过
        {"sessionDate": "2026-08-07", "total": {"zlje": 1.0}},  # 缺 code → 跳过
    ]
    rows = project_cache_rows(docs)

    assert len(rows) == 1
    assert rows[0] == {
        "code": "000001",
        "zlje": -31_000_000.0,
        "sessionDate": "2026-08-07",
        "tradingDate": "2026-08-07",
        "source": "ths_main_monitor",
        "moneyFlowSource": "ths_main_monitor",
        "sourceTs": 123,
    }


def test_project_cache_rows_empty() -> None:
    assert project_cache_rows([]) == []
