from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from backend.settings import get_settings
from backend.data.repository_factory import get_runtime_mongodb_database
from backend.data.mongo_theme_repository import MongoThemeRepository
from backend.data.theme_repository import ThemeRepository


class ThemeMigrationError(ValueError):
    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__(detail)
        self.detail = detail


def _error(code: str, field: str, message: str) -> ThemeMigrationError:
    return ThemeMigrationError({"code": code, "field": field, "message": message})


class ThemeMigrationService:
    def __init__(self, session: Session | None) -> None:
        self.session = session
        self.repo = (
            MongoThemeRepository(get_runtime_mongodb_database())
            if get_settings().storage_backend == "mongodb"
            else ThemeRepository(session)
        )

    def import_mapping(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_payload(payload)

        inserted_themes = 0
        updated_themes = 0
        inserted_mappings = 0
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
        if self.session is not None:
            self.session.commit()

        if updated_themes and inserted_themes == 0:
            inserted_mappings = 0

        return {
            "ok": True,
            "inserted": {"themes": inserted_themes, "mappings": inserted_mappings},
            "updated": {"themes": updated_themes},
            "counts": self.repo.counts(),
            "source": "mongodb" if get_settings().storage_backend == "mongodb" else "sqlite",
        }

    def verify_mapping(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_payload(payload)
        expected_themes = {theme["id"]: theme["name"] for theme in normalized}
        expected_mappings = {
            (theme["id"], mapping["stockCode"])
            for theme in normalized
            for mapping in theme["mappings"]
        }
        expected_stocks = {stock_code for _, stock_code in expected_mappings}

        actual_mapping = self.repo.get_mapping()
        actual_themes = {theme["id"]: theme["name"] for theme in actual_mapping.get("themes", [])}
        actual_mappings = {
            (theme["id"], stock_code)
            for theme in actual_mapping.get("themes", [])
            for stock_code in theme.get("stocks", [])
        }
        actual_stocks = {stock_code for _, stock_code in actual_mappings}

        expected_counts = {
            "themeCount": len(expected_themes),
            "mappingCount": len(expected_mappings),
            "stockCount": len(expected_stocks),
        }
        actual_counts = {
            "themeCount": len(actual_themes),
            "mappingCount": len(actual_mappings),
            "stockCount": len(actual_stocks),
        }
        mismatches = {
            key: {"expected": expected_counts[key], "actual": actual_counts[key]}
            for key in expected_counts
            if expected_counts[key] != actual_counts[key]
        }
        missing_themes = [
            {"id": theme_id, "name": expected_themes[theme_id]}
            for theme_id in sorted(set(expected_themes) - set(actual_themes))
        ]
        extra_themes = [
            {"id": theme_id, "name": actual_themes[theme_id]}
            for theme_id in sorted(set(actual_themes) - set(expected_themes))
        ]
        missing_mappings = [
            {"themeId": theme_id, "stockCode": stock_code}
            for theme_id, stock_code in sorted(expected_mappings - actual_mappings)
        ]
        extra_mappings = [
            {"themeId": theme_id, "stockCode": stock_code}
            for theme_id, stock_code in sorted(actual_mappings - expected_mappings)
        ]

        ok = not (mismatches or missing_themes or extra_themes or missing_mappings or extra_mappings)
        return {
            "ok": ok,
            "expected": expected_counts,
            "actual": actual_counts,
            "mismatches": mismatches,
            "missingThemes": missing_themes,
            "extraThemes": extra_themes,
            "missingMappings": missing_mappings,
            "extraMappings": extra_mappings,
            "source": "mongodb" if get_settings().storage_backend == "mongodb" else "sqlite",
        }

    def _normalize_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        themes = payload.get("themes")
        if not isinstance(themes, list) or not themes:
            raise _error("missing_themes", "themes", "themes must be a non-empty list")

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
        return normalized

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
