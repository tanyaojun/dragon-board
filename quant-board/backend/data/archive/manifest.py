from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ARCHIVE_SCHEMA_VERSION = "archive.v1"


def snapshot_archive_id(dataset_id: str, snapshot_type: str, trading_date: str) -> str:
    return f"snapshots_{_safe_key(dataset_id)}_{_safe_key(snapshot_type)}_{_safe_key(trading_date)}"


def research_archive_id(run_id: str) -> str:
    return f"research_{_safe_key(run_id)}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "schemaVersion": ARCHIVE_SCHEMA_VERSION,
        **payload,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def read_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_key(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(value))
