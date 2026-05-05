from __future__ import annotations

from typing import Any

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from backend.data.theme_models import ThemeMetadataModel, ThemeModel, ThemeStockMappingModel
from backend.utils import json_dumps


def _loads_json(value: str, fallback: Any) -> Any:
    import json

    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return fallback


class ThemeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_theme(self, theme_id: str, name: str, zs_code: str = "") -> bool:
        existing = self.session.get(ThemeModel, theme_id)
        if existing:
            existing.name = name
            existing.zs_code = zs_code
            return False
        self.session.add(ThemeModel(id=theme_id, name=name, zs_code=zs_code))
        return True

    def replace_theme_mappings(self, theme_id: str, mappings: list[dict[str, Any]]) -> int:
        self.session.execute(delete(ThemeStockMappingModel).where(ThemeStockMappingModel.theme_id == theme_id))
        for item in mappings:
            self.session.add(
                ThemeStockMappingModel(
                    theme_id=theme_id,
                    stock_code=item["stockCode"],
                    stock_tags_json=json_dumps(item.get("tags") or []),
                    stock_reason=str(item.get("reason") or ""),
                )
            )
        return len(mappings)

    def set_metadata(self, version: str, last_update: str) -> None:
        for key, value in {"version": version, "lastUpdate": last_update}.items():
            row = self.session.get(ThemeMetadataModel, key)
            if row:
                row.value = value
            else:
                self.session.add(ThemeMetadataModel(key=key, value=value))

    def get_metadata(self, key: str, default: str = "") -> str:
        row = self.session.get(ThemeMetadataModel, key)
        return row.value if row else default

    def get_mapping(self) -> dict[str, Any]:
        themes = list(self.session.scalars(select(ThemeModel).order_by(ThemeModel.id.asc())))
        rows = list(
            self.session.scalars(
                select(ThemeStockMappingModel).order_by(
                    ThemeStockMappingModel.theme_id.asc(),
                    ThemeStockMappingModel.stock_code.asc(),
                )
            )
        )
        by_theme: dict[str, list[ThemeStockMappingModel]] = {}
        for row in rows:
            by_theme.setdefault(row.theme_id, []).append(row)

        return {
            "version": self.get_metadata("version", "unknown"),
            "lastUpdate": self.get_metadata("lastUpdate", ""),
            "totalThemes": len(themes),
            "themes": [
                {
                    "id": theme.id,
                    "name": theme.name,
                    "zsCode": theme.zs_code,
                    "stocks": [row.stock_code for row in by_theme.get(theme.id, [])],
                    "stockTags": {
                        row.stock_code: _loads_json(row.stock_tags_json, [])
                        for row in by_theme.get(theme.id, [])
                        if _loads_json(row.stock_tags_json, [])
                    },
                    "stockReasons": {
                        row.stock_code: row.stock_reason
                        for row in by_theme.get(theme.id, [])
                        if row.stock_reason
                    },
                }
                for theme in themes
            ],
        }

    def get_theme_stocks(self, theme_id: str) -> dict[str, Any]:
        theme = self.session.get(ThemeModel, theme_id)
        if not theme:
            return {"themeId": theme_id, "stocks": [], "source": "sqlite"}
        rows = list(
            self.session.scalars(
                select(ThemeStockMappingModel)
                .where(ThemeStockMappingModel.theme_id == theme_id)
                .order_by(ThemeStockMappingModel.stock_code.asc())
            )
        )
        return {
            "themeId": theme.id,
            "themeName": theme.name,
            "stocks": [row.stock_code for row in rows],
            "source": "sqlite",
        }

    def get_stock_themes(self, code: str) -> dict[str, Any]:
        rows = list(
            self.session.scalars(
                select(ThemeStockMappingModel)
                .where(ThemeStockMappingModel.stock_code == code)
                .order_by(ThemeStockMappingModel.theme_id.asc())
            )
        )
        themes = []
        tags: list[dict[str, Any]] = []
        reason_parts: list[str] = []
        tag_names: set[str] = set()
        for row in rows:
            theme = self.session.get(ThemeModel, row.theme_id)
            if theme:
                themes.append({"id": theme.id, "name": theme.name, "zsCode": theme.zs_code})
            row_tags = _loads_json(row.stock_tags_json, [])
            if isinstance(row_tags, list):
                for tag in row_tags:
                    if not isinstance(tag, dict):
                        continue
                    name = str(tag.get("Name") or "").strip()
                    if not name or name in tag_names:
                        continue
                    tags.append(tag)
                    tag_names.add(name)
            if row.stock_reason:
                for part in row.stock_reason.split("；"):
                    normalized = part.strip()
                    if normalized and normalized not in reason_parts:
                        reason_parts.append(normalized)
        reason = "；".join(reason_parts)
        return {"code": code, "themes": themes, "tags": tags, "reason": reason, "source": "sqlite"}

    def counts(self) -> dict[str, Any]:
        theme_count = int(self.session.scalar(select(func.count()).select_from(ThemeModel)) or 0)
        mapping_count = int(self.session.scalar(select(func.count()).select_from(ThemeStockMappingModel)) or 0)
        stock_count = int(
            self.session.scalar(select(func.count(distinct(ThemeStockMappingModel.stock_code)))) or 0
        )
        return {
            "themeCount": theme_count,
            "mappingCount": mapping_count,
            "stockCount": stock_count,
            "version": self.get_metadata("version", "unknown"),
            "lastUpdate": self.get_metadata("lastUpdate", ""),
            "source": "sqlite",
        }
