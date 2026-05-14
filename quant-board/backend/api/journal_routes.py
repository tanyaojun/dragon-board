from __future__ import annotations

import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.data.models import TradeJournal
from backend.data.repository_factory import create_repository


router = APIRouter(prefix="/api/journal", tags=["journal"])

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "journal_screenshots"
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _new_journal_id() -> str:
    return f"tj_{uuid.uuid4().hex[:16]}"


def _get_repo():
    return create_repository(None)


def _get_journal_repo():
    repo = _get_repo()
    if not hasattr(repo, "save_journal_entry"):
        raise HTTPException(status_code=503, detail="journal requires MongoDB storage backend")
    return repo


# --- Request Models ---

class CreateJournalEntryRequest(BaseModel):
    stock_code: str
    stock_name: str
    direction: str = "buy"  # "buy" | "sell"
    trade_type: str = "thesis"  # "thesis" | "entry" | "exit"
    price: float = 0
    volume: int = 0
    trade_time: str = ""  # ISO 8601
    linked_entry_id: str | None = None
    signals_snapshot: dict[str, Any] | None = None
    notes: str = ""
    status: str = "observe"
    market_phase: str = ""
    theme_role: str = ""
    stock_role: str = ""
    entry_reason: str = ""
    trade_hypothesis: str = ""
    entry_prerequisites: str = ""
    invalidation_rules: str = ""
    expected_holding_days: int = 3
    human_decision: str = "watch"
    skip_reason: str = ""
    review_outcome: str = "pending"
    model_result: str = "unknown"
    execution_result: str = "unknown"
    review_notes: str = ""


class UpdateJournalEntryRequest(BaseModel):
    stock_code: str | None = None
    stock_name: str | None = None
    direction: str | None = None
    trade_type: str | None = None
    price: float | None = None
    volume: int | None = None
    trade_time: str | None = None
    linked_entry_id: str | None = None
    signals_snapshot: dict[str, Any] | None = None
    notes: str | None = None
    review_tags: list[str] | None = None
    pnl: float | None = None
    pnl_pct: float | None = None
    status: str | None = None
    market_phase: str | None = None
    theme_role: str | None = None
    stock_role: str | None = None
    entry_reason: str | None = None
    trade_hypothesis: str | None = None
    entry_prerequisites: str | None = None
    invalidation_rules: str | None = None
    expected_holding_days: int | None = None
    human_decision: str | None = None
    skip_reason: str | None = None
    review_outcome: str | None = None
    model_result: str | None = None
    execution_result: str | None = None
    review_notes: str | None = None


# --- Routes ---

@router.post("/entries")
def create_entry(payload: CreateJournalEntryRequest) -> dict[str, Any]:
    repo = _get_journal_repo()
    now = datetime.now(UTC).isoformat()
    entry = TradeJournal(
        id=_new_journal_id(),
        stock_code=payload.stock_code,
        stock_name=payload.stock_name,
        direction=payload.direction,
        trade_type=payload.trade_type,
        price=payload.price,
        volume=payload.volume,
        trade_time=payload.trade_time or now,
        linked_entry_id=payload.linked_entry_id,
        signals_snapshot=payload.signals_snapshot,
        notes=payload.notes,
        status=payload.status,
        market_phase=payload.market_phase,
        theme_role=payload.theme_role,
        stock_role=payload.stock_role,
        entry_reason=payload.entry_reason,
        trade_hypothesis=payload.trade_hypothesis,
        entry_prerequisites=payload.entry_prerequisites,
        invalidation_rules=payload.invalidation_rules,
        expected_holding_days=payload.expected_holding_days,
        human_decision=payload.human_decision,
        skip_reason=payload.skip_reason,
        review_outcome=payload.review_outcome,
        model_result=payload.model_result,
        execution_result=payload.execution_result,
        review_notes=payload.review_notes,
        created_at=now,
        updated_at=now,
    )
    repo.save_journal_entry(entry)
    return entry.to_dict()


@router.get("/entries")
def list_entries(
    stock_code: str | None = Query(None),
    trade_type: str | None = Query(None),
    direction: str | None = Query(None),
    status: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    review_tags: str | None = Query(None),  # comma-separated
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    repo = _get_journal_repo()
    tags_list = [t.strip() for t in review_tags.split(",") if t.strip()] if review_tags else None
    entries = repo.list_journal_entries(
        stock_code=stock_code,
        trade_type=trade_type,
        direction=direction,
        status=status,
        date_from=date_from,
        date_to=date_to,
        review_tags=tags_list,
        limit=limit,
        offset=offset,
    )
    total = repo.count_journal_entries(
        stock_code=stock_code,
        trade_type=trade_type,
        direction=direction,
        status=status,
        date_from=date_from,
        date_to=date_to,
        review_tags=tags_list,
    )
    return {"entries": entries, "total": total, "limit": limit, "offset": offset}


@router.get("/entries/{entry_id}")
def get_entry(entry_id: str) -> dict[str, Any]:
    repo = _get_journal_repo()
    entry = repo.get_journal_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="交易记录不存在")
    return entry


@router.put("/entries/{entry_id}")
def update_entry(entry_id: str, payload: UpdateJournalEntryRequest) -> dict[str, Any]:
    repo = _get_journal_repo()
    existing = repo.get_journal_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="交易记录不存在")

    updates: dict[str, Any] = {}
    field_map = {
        "stock_code": "stockCode",
        "stock_name": "stockName",
        "direction": "direction",
        "trade_type": "tradeType",
        "price": "price",
        "volume": "volume",
        "trade_time": "tradeTime",
        "linked_entry_id": "linkedEntryId",
        "signals_snapshot": "signalsSnapshot",
        "notes": "notes",
        "review_tags": "reviewTags",
        "pnl": "pnl",
        "pnl_pct": "pnlPct",
        "status": "status",
        "market_phase": "marketPhase",
        "theme_role": "themeRole",
        "stock_role": "stockRole",
        "entry_reason": "entryReason",
        "trade_hypothesis": "tradeHypothesis",
        "entry_prerequisites": "entryPrerequisites",
        "invalidation_rules": "invalidationRules",
        "expected_holding_days": "expectedHoldingDays",
        "human_decision": "humanDecision",
        "skip_reason": "skipReason",
        "review_outcome": "reviewOutcome",
        "model_result": "modelResult",
        "execution_result": "executionResult",
        "review_notes": "reviewNotes",
    }
    for py_field, doc_field in field_map.items():
        value = getattr(payload, py_field)
        if value is not None:
            updates[doc_field] = value

    result = repo.update_journal_entry(entry_id, updates)
    if not result:
        raise HTTPException(status_code=500, detail="更新失败")
    return result


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str) -> dict[str, str]:
    repo = _get_journal_repo()
    existing = repo.get_journal_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="交易记录不存在")

    repo.delete_linked_exits(entry_id)
    repo.delete_journal_entry(entry_id)

    entry_screenshots = SCREENSHOTS_DIR / entry_id
    if entry_screenshots.exists():
        shutil.rmtree(entry_screenshots)

    return {"status": "deleted", "id": entry_id}


@router.post("/entries/{entry_id}/screenshot")
def upload_screenshot(entry_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    repo = _get_journal_repo()
    existing = repo.get_journal_entry(entry_id)
    if not existing:
        raise HTTPException(status_code=404, detail="交易记录不存在")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    contents = file.file.read()
    if len(contents) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(status_code=400, detail="截图不能超过 10MB")

    entry_dir = SCREENSHOTS_DIR / entry_id
    entry_dir.mkdir(parents=True, exist_ok=True)

    existing_files = list(entry_dir.glob(f"{entry_id}_*{ext}")) if ext else []
    suffix_index = len(existing_files) + 1
    filename = f"{entry_id}_{suffix_index}{ext}"
    filepath = entry_dir / filename

    with open(filepath, "wb") as f:
        f.write(contents)

    relative_path = f"journal_screenshots/{entry_id}/{filename}"

    screenshot_paths = list(existing.get("screenshotPaths") or [])
    screenshot_paths.append(relative_path)
    repo.update_journal_entry(entry_id, {"screenshotPaths": screenshot_paths})

    return {"path": relative_path, "screenshotPaths": screenshot_paths}


@router.get("/stats")
def get_stats(
    stock_code: str | None = Query(None),
) -> dict[str, Any]:
    repo = _get_journal_repo()
    return repo.get_journal_stats()
