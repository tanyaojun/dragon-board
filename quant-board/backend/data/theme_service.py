from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from backend.data.theme_repository import ThemeRepository


class ThemeMigrationError(ValueError):
    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__(detail)
        self.detail = detail


def _error(code: str, field: str, message: str) -> ThemeMigrationError:
    return ThemeMigrationError({"code": code, "field": field, "message": message})


class ThemeMigrationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = ThemeRepository(session)

    def import_mapping(self, payload: dict[str, Any]) -> dict[str, Any]:
        themes = payload.get("themes")
        if not isinstance(themes, list) or not themes:
            raise _error("missing_themes", "themes", "themes must be a non-empty list")

        inserted_themes = 0
        updated_themes = 0
        inserted_mappings = 0
        normalized = []
        for index, raw_theme in enumerate(themes):
            if not isinstance(raw_theme, dict):
                raise _error("invalid_theme", f"themes[{index}]", "theme must be an object")
            theme_id = str(raw_theme.get("id") or "").strip()
            if not theme_id:
                raise _error("missing_theme_id", f"themes[{index}].id", "theme id is required")
            name = str(raw_theme.get("name") or "").strip()
            if not name:
                raise _error("missing_theme_name", f"themes[{index}].name", "theme name is required")

            stocks = raw_theme.get("stocks")
            if stocks is None:
                stocks = []
            if not isinstance(stocks, list):
                raise _error("invalid_stocks", f"themes[{index}].stocks", "stocks must be a list")

            mappings: dict[str, dict[str, Any]] = {}
            for stock_index, raw_code in enumerate(stocks):
                code = self._normalize_stock_code(raw_code)
                if not code:
                    raise _error(
                        "invalid_stock_code",
                        f"themes[{index}].stocks[{stock_index}]",
                        "stock code must contain 1 to 6 digits",
                    )
                mappings.setdefault(code, {"stockCode": code, "tags": [], "reason": ""})

            stock_tags = raw_theme.get("stockTags") if isinstance(raw_theme.get("stockTags"), dict) else {}
            for raw_code, raw_tags in stock_tags.items():
                code = self._normalize_stock_code(raw_code)
                if not code:
                    continue
                tags = self._normalize_tags(raw_tags)
                if code in mappings:
                    mappings[code]["tags"] = tags

            stock_reasons = raw_theme.get("stockReasons") if isinstance(raw_theme.get("stockReasons"), dict) else {}
            for raw_code, raw_reason in stock_reasons.items():
                code = self._normalize_stock_code(raw_code)
                if not code:
                    continue
                reason = str(raw_reason or "").strip()
                if code in mappings:
                    mappings[code]["reason"] = reason

            normalized.append(
                {
                    "id": theme_id,
                    "name": name,
                    "zsCode": str(raw_theme.get("zsCode") or "").strip(),
                    "mappings": list(mappings.values()),
                }
            )

        for theme in normalized:
            created = self.repo.upsert_theme(theme["id"], theme["name"], theme["zsCode"])
            if created:
                inserted_themes += 1
            else:
                updated_themes += 1
            inserted_mappings += self.repo.replace_theme_mappings(theme["id"], theme["mappings"])

        version = str(payload.get("version") or "").strip() or "unknown"
        last_update = str(payload.get("lastUpdate") or payload.get("last_update") or "").strip()
        self.repo.set_metadata(version, last_update)
        self.session.commit()

        if updated_themes and inserted_themes == 0:
            inserted_mappings = 0

        return {
            "ok": True,
            "inserted": {"themes": inserted_themes, "mappings": inserted_mappings},
            "updated": {"themes": updated_themes},
            "counts": self.repo.counts(),
            "source": "sqlite",
        }

    @staticmethod
    def _normalize_stock_code(value: Any) -> str:
        raw = str(value or "").strip()
        digits = re.sub(r"\D", "", raw)
        if not digits or len(digits) > 6:
            return ""
        return digits.zfill(6)

    @staticmethod
    def _normalize_tags(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        tags = []
        for item in value:
            if not isinstance(item, dict):
                continue
            name = str(item.get("Name") or item.get("name") or "").strip()
            if not name:
                continue
            tag = {"Name": name}
            reason = str(item.get("Reason") or item.get("reason") or "").strip()
            if reason:
                tag["Reason"] = reason
            tags.append(tag)
        return tags

