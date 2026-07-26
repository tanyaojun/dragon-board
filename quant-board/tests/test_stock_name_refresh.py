from __future__ import annotations

from typing import Any

from backend.data.stock_name_refresh import fetch_mootdx_stock_directory, refresh_stock_names


class FakeCollection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = [dict(row) for row in rows]
        self.bulk_writes: list[list[Any]] = []

    def bulk_write(self, operations: list[Any], ordered: bool = False) -> None:
        assert ordered is False
        self.bulk_writes.append(operations)
        for operation in operations:
            code = operation._filter['code']
            row = next((item for item in self.rows if item['code'] == code), None)
            if row is None:
                row = dict(operation._doc.get('$setOnInsert') or {})
                self.rows.append(row)
            row.update(operation._doc.get('$set') or {})

    def find(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        codes = set(query.get('code', {}).get('$in', []))
        return [dict(row) for row in self.rows if row['code'] in codes]


class FakeDatabase(dict[str, FakeCollection]):
    def __getitem__(self, name: str) -> FakeCollection:
        return dict.__getitem__(self, name)


def test_refresh_stock_names_upserts_new_shenzhen_and_shanghai_a_shares() -> None:
    collection = FakeCollection(
        [
            _stock('000001', '平安银行', market='SZ'),
            _stock('600001', '旧名称', market='SH'),
            _stock('920001', '纬达光电', market='BJ'),
        ]
    )
    database = FakeDatabase(stock_names=collection)

    result = refresh_stock_names(
        database,
        fetch_directory=lambda: [
            {'market': 'SZ', 'code': '000001', 'name': '平安银行'},
            {'market': 'SZ', 'code': '301707', 'name': '展芯股份'},
            {'market': 'SH', 'code': '600001', 'name': '新名称'},
            {'market': 'SH', 'code': '110001', 'name': '债券'},
        ],
    )

    assert result == {
        'ok': True,
        'source': 'mootdx_7709',
        'fetched': 4,
        'eligible': 3,
        'inserted': 1,
        'renamed': 1,
        'unchanged': 1,
        'skippedTemporaryNames': 0,
        'error': None,
    }
    assert _find(collection, '301707') == {
        'code': '301707',
        'name': '展芯股份',
        'market': 'SZ',
        'type': 'stock',
        'active': True,
        'nameNormalized': '展芯股份',
        'pinyinInitials': '',
        'pinyinFull': '',
        'searchText': '301707 展芯股份 SZ stock',
        'source': 'mootdx_7709',
    }
    assert _find(collection, '600001')['name'] == '新名称'
    assert _find(collection, '920001')['name'] == '纬达光电'


def test_refresh_stock_names_does_not_replace_canonical_name_with_corporate_action_alias() -> None:
    collection = FakeCollection([_stock('600004', '白云机场', market='SH')])

    result = refresh_stock_names(
        FakeDatabase(stock_names=collection),
        fetch_directory=lambda: [{'market': 'SH', 'code': '600004', 'name': 'XD白云机'}],
    )

    assert result['skippedTemporaryNames'] == 1
    assert result['renamed'] == 0
    assert _find(collection, '600004')['name'] == '白云机场'


def test_refresh_stock_names_does_not_insert_corporate_action_alias() -> None:
    collection = FakeCollection([])

    result = refresh_stock_names(
        FakeDatabase(stock_names=collection),
        fetch_directory=lambda: [{'market': 'SH', 'code': '600004', 'name': 'XD白云机'}],
    )

    assert result['inserted'] == 0
    assert result['skippedTemporaryNames'] == 1
    assert collection.rows == []


def test_refresh_stock_names_keeps_existing_rows_unchanged_when_directory_fetch_fails() -> None:
    collection = FakeCollection([_stock('000001', '平安银行', market='SZ')])

    result = refresh_stock_names(
        FakeDatabase(stock_names=collection),
        fetch_directory=lambda: (_ for _ in ()).throw(ConnectionError('TDX unavailable')),
    )

    assert result == {
        'ok': False,
        'source': 'mootdx_7709',
        'fetched': 0,
        'eligible': 0,
        'inserted': 0,
        'renamed': 0,
        'unchanged': 0,
        'skippedTemporaryNames': 0,
        'error': 'TDX unavailable',
    }
    assert collection.rows == [_stock('000001', '平安银行', market='SZ')]
    assert collection.bulk_writes == []


def test_fetch_mootdx_stock_directory_uses_a_fixed_7709_host(monkeypatch) -> None:
    import mootdx.quotes
    from mootdx.consts import HQ_HOSTS

    calls: list[dict[str, Any]] = []

    class FakeFrame:
        def to_dict(self, orient: str) -> list[dict[str, str]]:
            assert orient == 'records'
            return [{'code': '000001', 'name': '平安银行'}]

    class FakeClient:
        def stocks(self, market: int) -> FakeFrame:
            assert market in (0, 1)
            return FakeFrame()

        def close(self) -> None:
            return None

    class FakeQuotes:
        @staticmethod
        def factory(**kwargs: Any) -> FakeClient:
            calls.append(kwargs)
            return FakeClient()

    monkeypatch.setattr(mootdx.quotes, 'Quotes', FakeQuotes)

    rows = fetch_mootdx_stock_directory()

    assert len(rows) == 2
    assert {row['market'] for row in rows} == {'SZ', 'SH'}
    assert calls == [
        {
            'market': 'std',
            'server': (HQ_HOSTS[0][1], HQ_HOSTS[0][2]),
            'bestip': False,
            'heartbeat': False,
            'auto_retry': False,
            'timeout': 10,
        }
    ]


def _stock(code: str, name: str, *, market: str) -> dict[str, Any]:
    return {
        'code': code,
        'name': name,
        'market': market,
        'type': 'stock',
        'active': True,
        'nameNormalized': name,
        'pinyinInitials': '',
        'pinyinFull': '',
        'searchText': f'{code} {name} {market} stock',
    }


def _find(collection: FakeCollection, code: str) -> dict[str, Any]:
    return next(row for row in collection.rows if row['code'] == code)
