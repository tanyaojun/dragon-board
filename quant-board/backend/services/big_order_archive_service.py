from __future__ import annotations

import gzip
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


class BigOrderArchiveError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BigOrderArchiveService:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[1] / "data" / "big-order"

    def load(self, source: str, stock_code: str, session_date: date) -> dict[str, Any]:
        if source not in {"longhu", "ths"} or not re.fullmatch(r"\d{6}", stock_code):
            raise BigOrderArchiveError("invalid_request", "invalid archive selector")

        date_text = session_date.isoformat()
        suffix = ".money0.json.gz" if source == "longhu" else ".json.gz"
        path = self.root / source / date_text / f"{stock_code}{suffix}"
        if not path.is_file():
            raise BigOrderArchiveError("archive_not_found", "big-order archive not found")

        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                payload = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BigOrderArchiveError("archive_invalid", "invalid big-order archive") from exc

        if not isinstance(payload, dict):
            raise BigOrderArchiveError("archive_invalid", "invalid big-order archive payload")
        if payload.get("sessionDate") != date_text or payload.get("stockCode") != stock_code:
            raise BigOrderArchiveError("archive_invalid", "archive metadata does not match request")
        if payload.get("source") not in {None, source}:
            raise BigOrderArchiveError("archive_invalid", "archive source does not match request")

        data = payload.get("data")
        if source == "longhu":
            valid = isinstance(data, dict) and isinstance(data.get("List"), list)
        else:
            valid = (
                isinstance(data, dict)
                and isinstance(data.get("title"), dict)
                and isinstance(data.get("list"), list)
                and isinstance(data.get("pricechange"), list)
            )
        if not valid:
            raise BigOrderArchiveError("archive_invalid", "archive data shape is invalid")
        return payload
