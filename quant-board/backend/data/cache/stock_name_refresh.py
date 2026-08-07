from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pymongo import UpdateOne


STOCK_NAME_SOURCE = 'mootdx_7709'
_TEMPORARY_NAME_PREFIXES = ('XD', 'XR', 'DR')
_A_SHARE_PREFIXES = {
    'SZ': ('000', '001', '002', '003', '300', '301'),
    'SH': ('600', '601', '603', '605', '688', '689'),
}


def refresh_stock_names(
    database: Any,
    *,
    fetch_directory: Callable[[], Iterable[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    try:
        directory = list((fetch_directory or fetch_mootdx_stock_directory)())
    except Exception as error:
        return _result(ok=False, error=str(error))

    stocks = _eligible_stocks(directory)
    collection = database['stock_names']
    existing = {
        str(row.get('code') or ''): row
        for row in collection.find({'code': {'$in': [stock['code'] for stock in stocks]}})
    }
    operations: list[UpdateOne] = []
    inserted = renamed = unchanged = skipped_temporary_names = 0

    for stock in stocks:
        if _is_temporary_name(stock['name']):
            skipped_temporary_names += 1
            continue

        current = existing.get(stock['code'])
        if current is None:
            operations.append(
                UpdateOne(
                    {'code': stock['code']},
                    {
                        '$setOnInsert': _new_stock_document(stock),
                    },
                    upsert=True,
                )
            )
            inserted += 1
            continue

        if _names_match(current.get('name'), stock['name']):
            unchanged += 1
            continue

        operations.append(
            UpdateOne(
                {'code': stock['code']},
                {
                    '$set': {
                        'name': stock['name'],
                        'nameNormalized': _normalized_name(stock['name']),
                        'searchText': _search_text(stock),
                        'source': STOCK_NAME_SOURCE,
                    }
                },
            )
        )
        renamed += 1

    if operations:
        collection.bulk_write(operations, ordered=False)

    return _result(
        ok=True,
        fetched=len(directory),
        eligible=len(stocks),
        inserted=inserted,
        renamed=renamed,
        unchanged=unchanged,
        skipped_temporary_names=skipped_temporary_names,
    )


def fetch_mootdx_stock_directory() -> list[dict[str, str]]:
    from mootdx.consts import HQ_HOSTS
    from mootdx.quotes import Quotes

    _, host, port = HQ_HOSTS[0]
    client = Quotes.factory(
        market='std',
        server=(host, port),
        bestip=False,
        heartbeat=False,
        auto_retry=False,
        timeout=10,
    )
    try:
        rows: list[dict[str, str]] = []
        for market, mootdx_market in (('SZ', 0), ('SH', 1)):
            frame = client.stocks(mootdx_market)
            records = frame.to_dict('records') if frame is not None else []
            rows.extend(
                {
                    'market': market,
                    'code': str(row.get('code') or ''),
                    'name': str(row.get('name') or ''),
                }
                for row in records
            )
        return rows
    finally:
        client.close()


def _eligible_stocks(rows: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    stocks: dict[str, dict[str, str]] = {}
    for row in rows:
        market = str(row.get('market') or '').upper()
        code = str(row.get('code') or '').strip()
        name = str(row.get('name') or '').replace('\x00', '').strip()
        if not name or not code.startswith(_A_SHARE_PREFIXES.get(market, ())):
            continue
        stocks[code] = {'market': market, 'code': code, 'name': name}
    return list(stocks.values())


def _new_stock_document(stock: dict[str, str]) -> dict[str, Any]:
    return {
        'code': stock['code'],
        'name': stock['name'],
        'market': stock['market'],
        'type': 'stock',
        'active': True,
        'nameNormalized': _normalized_name(stock['name']),
        'pinyinInitials': '',
        'pinyinFull': '',
        'searchText': _search_text(stock),
        'source': STOCK_NAME_SOURCE,
    }


def _search_text(stock: dict[str, str]) -> str:
    return ' '.join((stock['code'], _normalized_name(stock['name']), stock['market'], 'stock'))


def _normalized_name(name: Any) -> str:
    return ''.join(str(name or '').split())


def _names_match(left: Any, right: str) -> bool:
    return _normalized_name(left) == _normalized_name(right)


def _is_temporary_name(name: str) -> bool:
    return name.upper().startswith(_TEMPORARY_NAME_PREFIXES)


def _result(
    *,
    ok: bool,
    fetched: int = 0,
    eligible: int = 0,
    inserted: int = 0,
    renamed: int = 0,
    unchanged: int = 0,
    skipped_temporary_names: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        'ok': ok,
        'source': STOCK_NAME_SOURCE,
        'fetched': fetched,
        'eligible': eligible,
        'inserted': inserted,
        'renamed': renamed,
        'unchanged': unchanged,
        'skippedTemporaryNames': skipped_temporary_names,
        'error': error,
    }
