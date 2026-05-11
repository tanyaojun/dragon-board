# RankTrend Redis Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Redis-first caching for QuantBoard snapshot read models and make Dragon Board RankTrend columns stable during refresh.

**Architecture:** QuantBoard keeps SQLite as the formal fact source and adds a Redis read-through cache for snapshot read APIs. Dragon Board keeps previous RankTrend display fields during `base-merge` and only overwrites them when fresh signal results are available.

**Tech Stack:** Python FastAPI, SQLAlchemy, Redis Python client, Vue/TypeScript, Vitest, pytest.

---

## Files

- Create: `quant-board/backend/data/snapshot_cache.py`
- Modify: `quant-board/backend/settings.py`
- Modify: `quant-board/backend/main.py`
- Modify: `quant-board/requirements.txt`
- Test: `quant-board/tests/test_snapshot_cache.py`
- Test: `quant-board/tests/test_quant_board.py`
- Modify: `src/services/dataLoader/StockMergeCoordinator.ts`
- Test: `src/services/dataLoader/__tests__/RankTrendSignalService.test.ts` or `DataLoaderFacade.test.ts`
- Docs: `docs/ranktrend-redis-cache/*`

## Task 1: Cache Key And Settings

- [ ] Add failing pytest tests for key normalization, namespace isolation, CSV normalization, and resolved dataset id.
- [ ] Run the test and verify it fails because `snapshot_cache.py` does not exist.
- [ ] Add Redis settings to `Settings`.
- [ ] Implement `SnapshotCacheKeyBuilder` in `snapshot_cache.py`.
- [ ] Run the key tests and verify they pass.

## Task 2: Read-Through Cache Client

- [ ] Add failing tests using an in-memory fake Redis client for miss/hit/set behavior.
- [ ] Implement optional Redis client creation with short timeouts and fail-open behavior.
- [ ] Implement `get_response()` and `set_response()` with JSON serialization.
- [ ] Preserve original response `source`; add `cache` diagnostic without changing business data.
- [ ] Run tests.

## Task 3: Reverse Index Invalidation

- [ ] Add failing tests for dataset/date/snapshot index registration and invalidation.
- [ ] Implement index set registration.
- [ ] Implement `invalidate_dependencies()` that deletes response keys via indexes.
- [ ] Use `delete` or `unlink` when available; do not use broad `KEYS`.
- [ ] Run tests.

## Task 4: Integrate GET APIs

- [ ] Add integration tests for `/api/snapshots/frames` miss then hit.
- [ ] Add integration tests for `/records`, `/stock-rows`, `/sector-rows` miss then hit.
- [ ] Refactor each API to build response through a small cached read helper.
- [ ] Use resolved dataset id in cache key.
- [ ] Run targeted pytest tests.

## Task 5: Ingest Invalidation

- [ ] Add failing tests that ingest invalidates cached frames and stock rows for the affected date/snapshot.
- [ ] Add a test that `backup_only` does not write or refresh Redis cache.
- [ ] In `ingest_snapshot`, call cache invalidation only after `save_snapshot_ingest()` returns a SQLite-backed success.
- [ ] Run targeted pytest tests.

## Task 6: Frontend RankTrend Field Preservation

- [ ] Add failing Vitest test showing `base-merge` preserves old `rankTrend`, `rankChange`, and `finalConfidence`.
- [ ] Implement explicit preservation in merge path or signal service.
- [ ] Ensure new signal results still overwrite old fields.
- [ ] Run targeted Vitest tests.

## Task 7: Verification

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests\test_snapshot_cache.py tests\test_quant_board.py -q` in `quant-board`.
- [ ] Run targeted frontend tests with `pnpm exec vitest run`.
- [ ] Run `pnpm test:ranktrend`.
- [ ] Update docs with final behavior and known boundaries.
