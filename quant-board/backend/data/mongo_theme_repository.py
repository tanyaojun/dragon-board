from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class MongoThemeRepository:
    def __init__(self, database: Any) -> None:
        self.db = database

    def upsert_theme(self, theme_id: str, name: str, zs_code: str = "") -> bool:
        existing = self.db["themes"].find_one({"id": theme_id})
        now = datetime.now(UTC)
        doc = {
            "id": theme_id,
            "name": name,
            "zsCode": zs_code,
            "updatedAt": now,
        }
        if existing and existing.get("createdAt"):
            doc["createdAt"] = existing["createdAt"]
        else:
            doc["createdAt"] = now
        self.db["themes"].replace_one({"id": theme_id}, doc, upsert=True)
        return existing is None

    def replace_theme_mappings(self, theme_id: str, mappings: list[dict[str, Any]]) -> int:
        self.db["theme_stock_mappings"].delete_many({"themeId": theme_id})
        docs = [
            {
                "themeId": theme_id,
                "stockCode": str(item.get("stockCode") or ""),
                "stockTags": item.get("tags") if isinstance(item.get("tags"), list) else [],
                "stockReason": str(item.get("reason") or ""),
                "updatedAt": datetime.now(UTC),
            }
            for item in mappings
        ]
        if docs:
            self.db["theme_stock_mappings"].insert_many(docs, ordered=False)
        return len(docs)

    def set_metadata(self, version: str, last_update: str) -> None:
        for key, value in {"version": version, "lastUpdate": last_update}.items():
            self.db["theme_metadata"].replace_one(
                {"key": key},
                {"key": key, "value": value, "updatedAt": datetime.now(UTC)},
                upsert=True,
            )

    def get_metadata(self, key: str, default: str = "") -> str:
        row = self.db["theme_metadata"].find_one({"key": key})
        return str(row.get("value") or default) if row else default

    def get_mapping(self) -> dict[str, Any]:
        themes = list(self.db["themes"].find({}).sort([("id", 1)]))
        rows = list(self.db["theme_stock_mappings"].find({}).sort([("themeId", 1), ("stockCode", 1)]))
        by_theme: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_theme.setdefault(str(row.get("themeId") or ""), []).append(row)

        return {
            "version": self.get_metadata("version", "unknown"),
            "lastUpdate": self.get_metadata("lastUpdate", ""),
            "totalThemes": len(themes),
            "themes": [
                {
                    "id": str(theme.get("id") or ""),
                    "name": str(theme.get("name") or ""),
                    "zsCode": str(theme.get("zsCode") or ""),
                    "stocks": [str(row.get("stockCode") or "") for row in by_theme.get(str(theme.get("id") or ""), [])],
                    "stockTags": {
                        str(row.get("stockCode") or ""): row.get("stockTags")
                        for row in by_theme.get(str(theme.get("id") or ""), [])
                        if isinstance(row.get("stockTags"), list) and row.get("stockTags")
                    },
                    "stockReasons": {
                        str(row.get("stockCode") or ""): str(row.get("stockReason") or "")
                        for row in by_theme.get(str(theme.get("id") or ""), [])
                        if row.get("stockReason")
                    },
                }
                for theme in themes
            ],
        }

    def get_market_universe(self) -> dict[str, Any]:
        themes = list(self.db["themes"].find({}).sort([("id", 1)]))
        rows = list(
            self.db["theme_stock_mappings"].find({}).sort(
                [("themeId", 1), ("stockCode", 1)]
            )
        )
        theme_stocks: dict[str, list[str]] = {}
        stock_themes: dict[str, list[str]] = {}
        for row in rows:
            theme_id = str(row.get("themeId") or "")
            stock_code = str(row.get("stockCode") or "")
            if not theme_id or not stock_code:
                continue
            theme_stocks.setdefault(theme_id, []).append(stock_code)
            stock_themes.setdefault(stock_code, []).append(theme_id)

        return {
            "version": self.get_metadata("version", "unknown"),
            "lastUpdate": self.get_metadata("lastUpdate", ""),
            "themes": [
                {
                    "id": str(theme.get("id") or ""),
                    "name": str(theme.get("name") or ""),
                    "zsCode": str(theme.get("zsCode") or ""),
                }
                for theme in themes
            ],
            "themeStocks": theme_stocks,
            "stockThemes": stock_themes,
            "stockCodes": sorted(stock_themes),
        }

    def get_theme_stocks(self, theme_id: str) -> dict[str, Any]:
        theme = self.db["themes"].find_one({"id": theme_id})
        if not theme:
            return {"themeId": theme_id, "stocks": [], "source": "mongodb"}
        rows = list(self.db["theme_stock_mappings"].find({"themeId": theme_id}).sort([("stockCode", 1)]))
        return {
            "themeId": str(theme.get("id") or ""),
            "themeName": str(theme.get("name") or ""),
            "stocks": [str(row.get("stockCode") or "") for row in rows],
            "source": "mongodb",
        }

    def get_stock_themes(self, code: str) -> dict[str, Any]:
        rows = list(self.db["theme_stock_mappings"].find({"stockCode": code}).sort([("themeId", 1)]))
        themes = []
        tags: list[dict[str, Any]] = []
        reason_parts: list[str] = []
        tag_names: set[str] = set()
        for row in rows:
            theme = self.db["themes"].find_one({"id": row.get("themeId")})
            if theme:
                themes.append(
                    {
                        "id": str(theme.get("id") or ""),
                        "name": str(theme.get("name") or ""),
                        "zsCode": str(theme.get("zsCode") or ""),
                    }
                )
            row_tags = row.get("stockTags")
            if isinstance(row_tags, list):
                for tag in row_tags:
                    if not isinstance(tag, dict):
                        continue
                    name = str(tag.get("Name") or "").strip()
                    if not name or name in tag_names:
                        continue
                    tags.append(tag)
                    tag_names.add(name)
            if row.get("stockReason"):
                for part in str(row.get("stockReason") or "").split("；"):
                    normalized = part.strip()
                    if normalized and normalized not in reason_parts:
                        reason_parts.append(normalized)
        return {"code": code, "themes": themes, "tags": tags, "reason": "；".join(reason_parts), "source": "mongodb"}

    def counts(self) -> dict[str, Any]:
        mapping_rows = list(self.db["theme_stock_mappings"].find({}))
        return {
            "themeCount": int(self.db["themes"].count_documents({})),
            "mappingCount": len(mapping_rows),
            "stockCount": len({str(row.get("stockCode") or "") for row in mapping_rows if row.get("stockCode")}),
            "version": self.get_metadata("version", "unknown"),
            "lastUpdate": self.get_metadata("lastUpdate", ""),
            "source": "mongodb",
        }
