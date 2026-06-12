# QuantBoard Backend Snapshot Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move formal snapshot production into `quant-board/backend` so scheduled MongoDB snapshots no longer depend on a Dragon Board browser page being open.

**Architecture:** Phase 1 builds a shadow-only backend collector that owns slot planning, provider reads, bundle building, quality gates, run state, API, and CLI. It writes only to `dragonboard_backend_shadow`, keeps Dragon Board's existing frontend snapshot runtime untouched, and adds the smallest `python-bridge` HTTP quote snapshot/codes capability needed to prove the backend can collect without browser WebSocket subscriptions.

**Tech Stack:** Python FastAPI, argparse CLI, pytest, MongoDB repository layer, existing QuantBoard snapshot ingest normalizer extracted from `backend/main.py`, transitional `proxy-server`, and local `python-bridge`.

---

## Source Documents

- Spec: `quant-board/docs/superpowers/specs/2026-06-11-quantboard-backend-snapshot-collector-design.md`
- QuantBoard rules: `quant-board/docs/README.md`
- Collaboration rules: `quant-board/docs/AI_COLLABORATION.md`
- MongoDB migration contract: `quant-board/docs/mongodb-migration-plan.md`
- API and CLI contract: `quant-board/docs/api-cli.md`

## Phase 1 Success Criteria

- Backend can run `snapshot-collector-run-once` for `half_hour:15:00` without Dragon Board open or browser WebSocket subscriptions.
- Backend can run `snapshot-collector-run-once` for `daily:15:00` without Dragon Board open or browser WebSocket subscriptions.
- `python-bridge` exposes a read-only quote snapshot/codes path; it does not change existing WebSocket behavior and does not claim true L2.
- Dry-run performs provider collection, build, normalizer validation, and quality checks without writing MongoDB facts.
- Apply mode writes `snapshot_records`, `snapshot_frames`, `snapshot_stock_rows`, and `snapshot_sector_rows` to `dragonboard_backend_shadow`.
- Empty or invalid formal snapshots are blocked before fact writes.
- Re-running the same slot is idempotent and reports `deduped`.
- Collector API behavior is tested for status, run-once, runs, and audit.
- Collector API behavior is tested for backfill dry-run and date-range limits.
- Collector CLI handler behavior is tested for dry-run, blocked, deduped, status, backfill, and audit JSON output.
- The first mergeable phase does not disable the existing frontend snapshot runtime and does not write `dragonboard_live`.

## File Structure

Create:

- `quant-board/backend/data/snapshot_ingest_normalizer.py`  
  Holds `normalize_snapshot_ingest()` currently located in `backend/main.py`, preventing `main -> route -> service -> main` circular imports.
- `quant-board/backend/snapshot_collector/__init__.py`
- `quant-board/backend/snapshot_collector/models.py`
- `quant-board/backend/snapshot_collector/slots.py`
- `quant-board/backend/snapshot_collector/providers.py`
- `quant-board/backend/snapshot_collector/builder.py`
- `quant-board/backend/snapshot_collector/quality_gate.py`
- `quant-board/backend/snapshot_collector/state.py`
- `quant-board/backend/snapshot_collector/repository_port.py`
- `quant-board/backend/snapshot_collector/service.py`
- `quant-board/backend/snapshot_collector/service_factory.py`
- `quant-board/backend/api/snapshot_collector_routes.py`
- `quant-board/tests/test_snapshot_collector_slots.py`
- `quant-board/tests/test_snapshot_collector_quality_gate.py`
- `quant-board/tests/test_snapshot_collector_builder.py`
- `quant-board/tests/test_snapshot_collector_service.py`
- `quant-board/tests/test_snapshot_collector_mongo_integration.py`
- `quant-board/tests/test_snapshot_collector_providers.py`
- `quant-board/tests/test_snapshot_collector_contract.py`
- `quant-board/tests/test_snapshot_collector_api.py`
- `quant-board/tests/test_snapshot_collector_cli.py`
- `python-bridge/test_quote_snapshot_api.py`

Modify:

- `quant-board/backend/main.py`  
  Import `normalize_snapshot_ingest()` from `backend.data.snapshot_ingest_normalizer` and include the collector router.
- `quant-board/backend/cli.py`  
  Add collector CLI commands and JSON handlers.
- `quant-board/backend/settings.py`  
  Add collector environment settings with disabled and shadow defaults.
- `quant-board/backend/data/mongo_repository.py`  
  Add only the minimal helpers needed for collector run state and snapshot existence if existing methods do not already cover them.
- `python-bridge/main.py`  
  Add read-only quote snapshot/codes endpoint without changing WebSocket behavior.
- `quant-board/docs/architecture.md`
- `quant-board/docs/api-cli.md`
- `quant-board/docs/mongodb-migration-plan.md`
- `quant-board/docs/AI_COLLABORATION.md`

Defer to later plans:

- Automatic scheduler startup for all snapshot types.
- Dragon Board frontend runtime disable switch.
- `proxy-server` migration or retirement.
- Production cutover to `dragonboard_live`.

## Settings Contract

Use the project-style `QUANT_BOARD_*` prefix:

```text
QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=0
QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID=dragonboard_backend_shadow
QUANT_BOARD_SNAPSHOT_COLLECTOR_TYPES=half_hour,daily
QUANT_BOARD_SNAPSHOT_COLLECTOR_POLL_MS=1000
QUANT_BOARD_SNAPSHOT_COLLECTOR_CLOSE_GRACE_MINUTES=5
QUANT_BOARD_SNAPSHOT_COLLECTOR_PROXY_BASE_URL=http://127.0.0.1:3000
QUANT_BOARD_SNAPSHOT_COLLECTOR_BRIDGE_BASE_URL=http://127.0.0.1:8765
QUANT_BOARD_SNAPSHOT_COLLECTOR_PROVIDER_TIMEOUT_MS=5000
QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=0
```

Tests must assert defaults are disabled, shadow-only, and do not permit `dragonboard_live` unless `ALLOW_LIVE_DATASET=1`.

## Collector API Envelope

All new `/api/snapshot-collector/*` responses use a collector-local envelope, even though older QuantBoard APIs are mixed.

Success:

```json
{
  "ok": true,
  "status": "completed",
  "data": {}
}
```

Blocked quality gate:

```json
{
  "ok": false,
  "status": "blocked",
  "quality": {
    "blockingIssues": [],
    "warnings": [],
    "sourceCounts": {}
  }
}
```

Validation or bad request:

```json
{
  "ok": false,
  "status": "error",
  "error": "invalid snapshotType"
}
```

Use HTTP `4xx` for invalid request shape or unsupported values. Use HTTP `200` for a valid request that ran and was blocked by quality gate, because blocked runs are auditable collector outcomes rather than transport failures.

Collector API 使用独立信封的原因：现有 QuantBoard API（如 `/api/snapshots/*`）直接返回业务对象并用 HTTP status 表意错误，但 collector 的操作语义不同——run-once 可能合法执行但因质量门禁被阻断，dry-run 和 apply 模式有不同的成功/失败含义，backfill 可能部分成功。这些状态不适合塞进 HTTP status code，因此 collector API 统一使用 `ok + status + data` 三元组。长期是否统一旧 API 到同一信封不在 Phase 1 范围内。

## Task 0: Isolated Workspace and Baseline

**Files:**
- No source edits.

- [ ] **Step 1: Confirm current repo and branch**

Run:

```powershell
git rev-parse --show-toplevel
git branch --show-current
git status --short
```

Expected: repository root is `D:/dragon-board`; existing dirty files are identified and not reverted.

- [ ] **Step 2: Create or enter isolated worktree**

Use `superpowers:using-git-worktrees`.

Preferred branch name:

```text
quantboard-backend-snapshot-collector
```

Expected: implementation happens outside the dirty main workspace.

- [ ] **Step 3: Run backend baseline tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongodb_migration.py tests/test_mongodb_snapshot_repair.py -q
```

Expected: current MongoDB migration and repair tests pass before collector work starts. If they fail, report in the execution summary and ask before proceeding; do not edit this plan to record runtime findings.

## Task 1: Extract Snapshot Ingest Normalizer

**Files:**
- Create: `quant-board/backend/data/snapshot_ingest_normalizer.py`
- Modify: `quant-board/backend/main.py`
- Test: existing ingest tests in `quant-board/tests/test_quant_board.py`

- [ ] **Step 1: Move normalizer without behavior change**

Move `normalize_snapshot_ingest()` and only its direct helper dependencies out of `backend/main.py` into `backend/data/snapshot_ingest_normalizer.py`.

- [ ] **Step 2: Update imports**

`backend/main.py` must import:

```python
from backend.data.snapshot_ingest_normalizer import normalize_snapshot_ingest
```

No collector module may import `backend.main`.

- [ ] **Step 3: Run ingest regression tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -q
```

Expected: existing snapshot ingest behavior still passes.

## Task 2: Slot Model and Time Rules

**Files:**
- Create: `quant-board/backend/snapshot_collector/__init__.py`
- Create: `quant-board/backend/snapshot_collector/models.py`
- Create: `quant-board/backend/snapshot_collector/slots.py`
- Test: `quant-board/tests/test_snapshot_collector_slots.py`

- [ ] **Step 1: Write slot tests**

Assert:

- `half_hour` slots include `15:00`.
- `daily` slot is exactly `15:00`.
- `quarter_hour` has 18 slots.
- `2026-06-11 15:00` Asia/Shanghai produces `half_hour:2026-06-11:15:00`.
- `15:00` remains eligible inside the close grace window.

- [ ] **Step 2: Implement models and slot helpers**

Implement:

```python
@dataclass(frozen=True)
class SnapshotSlot:
    snapshot_type: str
    trading_date: str
    slot_time: str
    timestamp_ms: int

    @property
    def snapshot_id(self) -> str:
        return f"{self.snapshot_type}:{self.trading_date}:{self.slot_time}"
```

and the slot table from the design document.

- [ ] **Step 3: Run slot tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_slots.py -q
```

Expected: PASS.

## Task 3: Settings, Repository Port, and Service Factory

**Files:**
- Modify: `quant-board/backend/settings.py`
- Create: `quant-board/backend/snapshot_collector/repository_port.py`
- Create: `quant-board/backend/snapshot_collector/service_factory.py`
- Test: `quant-board/tests/test_snapshot_collector_service.py`

- [ ] **Step 1: Write configuration and wiring tests**

Assert:

- defaults match the Settings Contract section.
- `dragonboard_live` is blocked by default.
- API and CLI can obtain the same service wiring through `service_factory`.
- repository port exposes snapshot existence, ingest save, run insert, run list, audit summary, and status methods.

- [ ] **Step 2: Implement settings fields**

Use `QUANT_BOARD_*` names from the Settings Contract section. Do not introduce `QUANTBOARD_*` aliases.

- [ ] **Step 3: Implement repository protocol**

The protocol must include these methods. `snapshot_exists` can be a thin wrapper around the existing `mongo_repository.existing_snapshot_ids(dataset_id, [snapshot_id])`; `save_snapshot_ingest` reuses the existing `mongo_repository.save_snapshot_ingest()` and its built-in idempotency/dedupe logic. New methods (`insert_run`, `list_runs`, `collector_status`, `audit_dataset`) operate on the new operational collections `snapshot_collector_runs` / `snapshot_collector_state`.

```python
snapshot_exists(dataset_id: str, snapshot_id: str) -> bool
save_snapshot_ingest(dataset: dict, records: list[dict], frames: list[dict], stock_rows: list[dict], sector_rows: list[dict], idempotency_key: str | None) -> dict
insert_run(run: dict) -> None
list_runs(filters: dict) -> dict
collector_status() -> dict
audit_dataset(dataset_id: str, snapshot_type: str, trading_date: str | None = None) -> dict
```

- [ ] **Step 4: Run wiring tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_service.py -q
```

Expected: PASS for settings and wiring tests added in this task.

## Task 4: Quality Gate

**Files:**
- Create: `quant-board/backend/snapshot_collector/quality_gate.py`
- Modify: `quant-board/backend/snapshot_collector/models.py`
- Test: `quant-board/tests/test_snapshot_collector_quality_gate.py`

- [ ] **Step 1: Write quality gate tests**

Assert these hard blockers:

- `empty_stock_rows`
- `missing_snapshot_identity`
- `all_hotlist_sources_failed`
- `invalid_stock_code`
- `timestamp_outside_slot`
- `invalid_live_dataset_in_shadow_mode`

Assert these warnings do not block:

- `quote_provider_partial`
- `depth_provider_missing`
- `money_flow_estimated_l1`
- `theme_mapping_partial`
- `delayed_capture`

- [ ] **Step 2: Implement quality result and gate**

Use:

```python
@dataclass(frozen=True)
class QualityResult:
    ok: bool
    blocking_issues: list[str]
    warnings: list[str]
    source_counts: dict[str, int]
```

- [ ] **Step 3: Run quality tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_quality_gate.py -q
```

Expected: PASS.

## Task 5: Bridge Quote Snapshot Endpoint

**Files:**
- Modify: `python-bridge/main.py`
- Test: `python-bridge/test_quote_snapshot_api.py`

- [ ] **Step 1: Write bridge tests**

Assert:

- `GET /api/quotes/snapshot?codes=000001,600000` returns a structured payload.
- when codes are supplied, the handler does not require an existing browser WebSocket subscription.
- bridge offline or quote failure returns `ok=false` with an error field.
- existing WebSocket route behavior remains untouched.

- [ ] **Step 2: Implement read-only endpoint**

Add endpoint:

```text
GET /api/quotes/snapshot?codes=000001,600000
```

Payload shape:

```json
{
  "ok": true,
  "source": "python_bridge",
  "serverTs": 1781170800000,
  "subscribedCount": 2,
  "quotes": [],
  "depth": [],
  "ticks": [],
  "moneyFlow": [],
  "quoteStats": {},
  "l2": {}
}
```

Do not label current L1 or estimated money-flow data as official L2.

- [ ] **Step 3: Run bridge tests**

Run:

```powershell
python -m unittest discover python-bridge -p "test_*.py"
```

Expected: PASS.

## Task 6: Builder Minimal Ingest Payload

**Files:**
- Create: `quant-board/backend/snapshot_collector/builder.py`
- Modify: `quant-board/backend/snapshot_collector/models.py`
- Test: `quant-board/tests/test_snapshot_collector_builder.py`

- [ ] **Step 1: Write builder tests**

Build a fake `MarketDataContext` with two stocks and one sector. Assert output:

- has `datasetId=dragonboard_backend_shadow`.
- has `snapshotId=half_hour:2026-06-11:15:00`.
- has one frame with count `2`.
- has two stock rows with code, name, rank, price, pctChange, volume, amount, turnover, heat, and themes.
- has at least one sector row.
- sets `source=quantboard_backend_collector`.
- sets `captureMode`.
- includes `qualityFlags` for partial provider, delayed capture, and estimated L1 money flow.

- [ ] **Step 2: Implement builder**

The builder must produce a dict or `SnapshotIngestRequest` accepted by `backend.data.snapshot_ingest_normalizer.normalize_snapshot_ingest()`.

- [ ] **Step 3: Run builder tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_builder.py -q
```

Expected: PASS.

## Task 7: Transitional Providers and Contract Test

**Files:**
- Create: `quant-board/backend/snapshot_collector/providers.py`
- Test: `quant-board/tests/test_snapshot_collector_providers.py`
- Test: `quant-board/tests/test_snapshot_collector_contract.py`

- [ ] **Step 1: Write provider tests with mocked HTTP/Mongo clients**

Cover:

- proxy hotlist response maps to normalized provider rows.
- bridge snapshot response maps to quote/depth/money-flow rows.
- bridge offline returns `SourceHealth(ok=False, error=...)`.
- provider timeout returns structured health and does not raise out of collection.
- Mongo theme provider maps code to theme list.

- [ ] **Step 2: Write provider-builder-normalizer contract test**

Mock raw proxy, bridge, and theme responses, then run:

```text
providers -> MarketDataContext -> builder -> normalize_snapshot_ingest
```

Expected: normalizer accepts the generated payload and returns non-empty records, frames, stock rows, and sector rows without writing MongoDB.

- [ ] **Step 3: Implement providers**

Use only standard library HTTP or an existing QuantBoard dependency. Do not add a new HTTP client package unless the repository already depends on it.

- [ ] **Step 4: Run provider and contract tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_providers.py tests/test_snapshot_collector_contract.py -q
```

Expected: PASS.

## Task 8: Service Run-Once and Mongo Integration

**Files:**
- Create: `quant-board/backend/snapshot_collector/state.py`
- Create: `quant-board/backend/snapshot_collector/service.py`
- Test: `quant-board/tests/test_snapshot_collector_service.py`
- Test: `quant-board/tests/test_snapshot_collector_mongo_integration.py`

- [ ] **Step 1: Write service tests with fake provider and fake repository**

Cover:

- dry-run returns `created=false`, `dryRun=true`, and does not call repository fact write.
- apply writes one valid snapshot.
- repeated apply returns `deduped=true`.
- empty provider data returns `status=blocked` and no fact write.
- invalid stock code and timestamp mismatch are blocked.
- run state records success, deduped, dry-run, and blocked attempts.

- [ ] **Step 2: Write MongoRepository integration tests**

Use the existing fake Mongo database pattern from `quant-board/tests/test_mongo_repository.py`. Cover:

- dry-run writes no facts.
- apply writes records, frames, stock rows, and sector rows.
- repeated apply dedupes.
- blocked quality writes run record but no fact collections.
- audit reports missing or blocked slots in structured form.

- [ ] **Step 3: Implement service orchestration**

`SnapshotCollectorService.run_once(request)` order:

1. create `SnapshotSlot`.
2. if `dry_run=false`, check existing `dataset_id + snapshot_id` and return deduped when present.
3. if `dry_run=true`, do not short-circuit on existing snapshots; dry-run must still collect providers, build, normalize, and evaluate quality.
4. collect providers into `MarketDataContext`.
5. build ingest payload.
6. normalize payload through `snapshot_ingest_normalizer`.
7. evaluate quality.
8. record and return blocked when blocked.
9. record and return dry-run when dry-run.
10. save through repository port.
11. record and return completed.

- [ ] **Step 4: Run service and integration tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_service.py tests/test_snapshot_collector_mongo_integration.py -q
```

Expected: PASS.

## Task 9: API Routes

**Files:**
- Create: `quant-board/backend/api/snapshot_collector_routes.py`
- Modify: `quant-board/backend/main.py`
- Test: `quant-board/tests/test_snapshot_collector_api.py`

- [ ] **Step 1: Write API tests**

Use FastAPI `TestClient`. Cover:

- `GET /api/snapshot-collector/status`.
- `POST /api/snapshot-collector/run-once`.
- `POST /api/snapshot-collector/backfill-slots`.
- `GET /api/snapshot-collector/runs`.
- `POST /api/snapshot-collector/audit`.
- invalid `snapshotType` returns HTTP `4xx`.
- blocked run returns HTTP `200` with `status=blocked`, `ok=false`, and quality issues.
- successful `status`, `run-once`, `backfill-slots`, `runs`, and `audit` responses all include `ok`.
- `runs` response includes `items`, `total`, `limit`, and `offset`.
- `audit` response includes `datasetId`, `snapshotType`, `missingSlots`, `emptyFrames`, `missingRecords`, and `countDrifts`.

Backfill API behavior tests must assert:

- default `dryRun=true` writes no facts.
- date range is inclusive and limited to the requested `startDate` / `endDate`.
- existing slots are skipped when `force=false`.
- partial slot failure returns `ok=false` with per-slot results and still records run attempts.
- apply mode writes only missing slots.

- [ ] **Step 2: Implement and register routes**

Add:

```python
from backend.api.snapshot_collector_routes import router as snapshot_collector_router
app.include_router(snapshot_collector_router)
```

Routes must use `service_factory` and must not duplicate CLI logic.

- [ ] **Step 3: Run API tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_api.py -q
```

Expected: PASS.

## Task 10: CLI Commands

**Files:**
- Modify: `quant-board/backend/cli.py`
- Test: `quant-board/tests/test_snapshot_collector_cli.py`

- [ ] **Step 1: Write CLI parser and handler tests**

Assert parser and JSON output for:

```powershell
snapshot-collector-status
snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --trading-date 2026-06-11 --slot-time 15:00 --dry-run
snapshot-collector-backfill --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --start-date 2026-06-11 --end-date 2026-06-11 --dry-run
snapshot-collector-audit --dataset-id dragonboard_backend_shadow --snapshot-type half_hour
```

Handler tests must cover dry-run, blocked, deduped, status, backfill, and audit output.

- [ ] **Step 2: Implement CLI handlers**

Handlers must print JSON through existing `print_json()` and use `service_factory`.

- [ ] **Step 3: Run CLI tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_cli.py -q
```

Expected: PASS.

## Task 11: Documentation Update for Phase 1

**Files:**
- Modify: `quant-board/docs/architecture.md`
- Modify: `quant-board/docs/api-cli.md`
- Modify: `quant-board/docs/mongodb-migration-plan.md`
- Modify: `quant-board/docs/AI_COLLABORATION.md`

- [ ] **Step 1: Update architecture narrowly**

Document that an experimental backend collector exists in shadow mode. Do not describe it as the production source until cutover.

- [ ] **Step 2: Update API/CLI**

Add request/response examples for:

```text
GET /api/snapshot-collector/status
POST /api/snapshot-collector/run-once
POST /api/snapshot-collector/backfill-slots
GET /api/snapshot-collector/runs
POST /api/snapshot-collector/audit
```

and matching CLI commands.

- [ ] **Step 3: Update MongoDB migration plan**

Document `dragonboard_backend_shadow`, collector run collections, quality gate, and audit requirement before live cutover.

- [ ] **Step 4: Update AI collaboration guide narrowly**

State that collector changes must be tested through backend pytest, bridge tests, and MongoDB audit commands. Keep true L2 wording constrained to verified bridge source capabilities.

## Task 12: Phase 1 Verification

**Files:**
- No source edits unless verification exposes defects.

- [ ] **Step 1: Run focused pytest**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_slots.py tests/test_snapshot_collector_quality_gate.py tests/test_snapshot_collector_builder.py tests/test_snapshot_collector_providers.py tests/test_snapshot_collector_contract.py tests/test_snapshot_collector_service.py tests/test_snapshot_collector_mongo_integration.py tests/test_snapshot_collector_api.py tests/test_snapshot_collector_cli.py -q
```

Expected: PASS.

- [ ] **Step 2: Run bridge tests**

Run:

```powershell
python -m unittest discover python-bridge -p "test_*.py"
```

Expected: PASS.

- [ ] **Step 3: Run MongoDB migration/repair regression tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongodb_migration.py tests/test_mongodb_snapshot_repair.py -q
```

Expected: PASS.

- [ ] **Step 4: Run manual dry-run for the execution trading day**

Replace `2026-06-11` with the current execution trading day if this plan is executed on a later date.

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --trading-date 2026-06-11 --slot-time 15:00 --dry-run
```

Expected: JSON contains `dryRun: true`, no fact write, and either `ok: true` with source counts or structured provider errors.

Phase 1 cannot be considered complete if this dry-run only proves a browser-subscription error. Passing evidence must be `ok: true`, or an `ok=false` response whose source health shows the failure is unrelated to Dragon Board browser WebSocket subscription state.

- [ ] **Step 5: Run manual apply only when data sources are available**

Replace `2026-06-11` with the current execution trading day if this plan is executed on a later date.

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --trading-date 2026-06-11 --slot-time 15:00
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --trading-date 2026-06-11 --slot-time 15:00
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type daily --trading-date 2026-06-11 --slot-time 15:00 --dry-run
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type daily --trading-date 2026-06-11 --slot-time 15:00
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type daily --trading-date 2026-06-11 --slot-time 15:00
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_backend_shadow --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_backend_shadow --snapshot-type daily
```

Expected: shadow dataset has record, frame, stock rows, sector rows for `half_hour` and `daily`; second run for each type reports `deduped`.

## Task 13: Follow-Up Plan Split

**Files:**
- Create later: `quant-board/docs/superpowers/plans/YYYY-MM-DD-quantboard-backend-snapshot-collector-scheduler-plan.md`
- Create later: `quant-board/docs/superpowers/plans/YYYY-MM-DD-quantboard-backend-snapshot-collector-frontend-retirement-plan.md`
- Create later: `quant-board/docs/superpowers/plans/YYYY-MM-DD-quantboard-backend-snapshot-collector-cutover-plan.md`
- Create later: `quant-board/docs/superpowers/plans/YYYY-MM-DD-quantboard-market-data-service-plan.md`

- [ ] **Step 1: Do not start scheduler or frontend retirement work in Phase 1 branch**

Phase 1 must stay mergeable and shadow-only.

- [ ] **Step 2: Create separate plans after Phase 1 passes**

Phase 1 must pass focused tests, bridge tests, Mongo regression tests, and at least one successful shadow dry-run before later plans begin.

Later plans must cover:

- four snapshot types and automatic scheduler.
- Dragon Board frontend production runtime retirement.
- production cutover and rollback runbook.
- proxy-server migration or Market Data Service split.

## Self-Review

Spec coverage:

- Backend ownership: covered by Tasks 1, 3, 6, 8, 9, and 10.
- Shadow dataset and production safety: covered by Tasks 3, 4, 8, 11, and 12.
- API and CLI: covered by Tasks 9 and 10.
- Quality gate: covered by Task 4.
- MongoDB fact write and dedupe: covered by Task 8 and Task 12.
- Bridge independence from browser WebSocket: covered by Task 5 and Task 7.
- Scheduler, frontend retirement, production cutover, and proxy migration: explicitly deferred to Task 13 follow-up plans.

Placeholder scan:

- No unresolved placeholder tokens or unnamed file paths remain in executable Phase 1 tasks.

Type consistency:

- The plan consistently uses `SnapshotSlot`, `MarketDataContext`, `QualityResult`, `SnapshotCollectorService.run_once()`, repository port, and service factory.
