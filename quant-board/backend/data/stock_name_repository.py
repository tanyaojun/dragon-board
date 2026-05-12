from __future__ import annotations

from typing import Any


STOCK_NAMES_VERSION = "stock_names.v1"


class StockNameRepository:
    def __init__(self, database: Any) -> None:
        self.db = database

    def list_names(
        self,
        *,
        market: str | None = None,
        type: str | None = None,
        active: bool | None = True,
    ) -> list[dict[str, Any]]:
        query = self._build_query(market=market, type=type, active=active)
        rows = self.db["stock_names"].find(query).sort([("code", 1)])
        return [self._to_stock(row) for row in rows]

    def get_by_code(self, code: str, *, active: bool | None = True) -> dict[str, Any] | None:
        normalized_code = self._normalize_code(code)
        if not normalized_code:
            return None
        query: dict[str, Any] = {"code": normalized_code}
        if active is not None:
            query["active"] = active
        row = self.db["stock_names"].find_one(query)
        return self._to_stock(row) if row else None

    def search(
        self,
        keyword: str,
        *,
        market: str | None = None,
        type: str | None = None,
        active: bool | None = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        term = str(keyword or "").strip().lower()
        if not term:
            return []

        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for stock in self.list_names(market=market, type=type, active=active):
            rank = self._match_rank(stock, term)
            if rank is not None:
                ranked.append((rank, str(stock.get("code") or ""), stock))

        ranked.sort(key=lambda item: (item[0], item[1]))
        max_count = max(1, min(int(limit or 50), 500))
        return [item[2] for item in ranked[:max_count]]

    @staticmethod
    def _build_query(
        *,
        market: str | None,
        type: str | None,
        active: bool | None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {}
        if active is not None:
            query["active"] = active
        if market:
            query["market"] = str(market).strip().upper()
        if type:
            query["type"] = str(type).strip().lower()
        return query

    @staticmethod
    def _to_stock(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": StockNameRepository._normalize_code(row.get("code")),
            "name": str(row.get("name") or ""),
            "market": str(row.get("market") or "").upper(),
            "type": str(row.get("type") or "stock").lower(),
            "active": bool(row.get("active", True)),
            "pinyinInitials": str(row.get("pinyinInitials") or ""),
            "pinyinFull": str(row.get("pinyinFull") or ""),
        }

    @staticmethod
    def _match_rank(stock: dict[str, Any], term: str) -> int | None:
        code = str(stock.get("code") or "").lower()
        name = str(stock.get("name") or "").lower()
        name_normalized = "".join(name.split())
        pinyin_initials = str(stock.get("pinyinInitials") or "").lower()
        pinyin_full = str(stock.get("pinyinFull") or "").lower()

        if code == term:
            return 0
        if code.startswith(term):
            return 1
        if name.startswith(term) or name_normalized.startswith(term):
            return 2
        if term in name or term in name_normalized:
            return 3
        if pinyin_initials.startswith(term):
            return 4
        if pinyin_full.startswith(term):
            return 5
        return None

    @staticmethod
    def _normalize_code(value: Any) -> str:
        code = str(value or "").strip()
        return code.zfill(6) if code.isdigit() else code
