# RankTrend Rank-Series Read Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each code task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove RankTrend's dependency on `/api/snapshots/frames` by adding a dedicated rank-series read model that returns only snapshot metadata and per-code ranks.

**Architecture:** QuantBoard exposes `/api/ranktrend/rank-series`, backed by SQLite and Redis response cache. Dragon Board calls this endpoint through `ApiService`, and `RankTrendAnalyzer` adapts the returned series into its existing in-memory calculation format without fetching frame bundles.

**Tech Stack:** FastAPI, SQLAlchemy, Redis cache wrapper, Vue/TypeScript, Vitest, Pytest.

---

## File Structure

- Modify `quant-board/backend/data/repository.py`
  - Add `load_rank_series(...)` beside snapshot read methods.
  - Query only `snapshot_frames` and `snapshot_stock_rows`.
  - Return recent frames with `snapshotId`, timestamp metadata, `totalCount`, and `ranks`.
- Modify `quant-board/backend/main.py`
  - Add `GET /api/ranktrend/rank-series`.
  - Reuse dataset resolution, capture-mode parsing, sort validation, and Redis response cache.
- Modify `quant-board/tests/test_quant_board.py`
  - Add API tests for compact output, `codes` filtering, and cache key isolation.
- Modify `src/services/snapshot/types.ts`
  - Add `RankTrendRankSeriesQueryOptions`, `RankTrendRankSeriesFrame`, and response types.
- Modify `src/services/apiService.ts`
  - Add `getRankTrendRankSeries(...)`.
  - Serialize `dataset_id`, `snapshot_type`, dates, capture modes, `codes`, `sort`, and `limit`.
- Modify `src/services/__tests__/apiService.test.ts`
  - Verify URL mapping for `/api/ranktrend/rank-series`.
- Modify `src/services/RankTrendAnalyzer.ts`
  - Replace RankTrend history reads from `snapshotFacade.listSnapshotFrameBundles(...)` with `apiService.getRankTrendRankSeries(...)`.
  - Keep existing calculation functions unchanged.
- Modify `src/services/__tests__/RankTrendAnalyzer.test.ts`
  - Verify analyzer uses rank-series and does not call frames for historical rank data.

## Task 1: Backend Rank-Series API

**Files:**
- Modify: `quant-board/tests/test_quant_board.py`
- Modify: `quant-board/backend/data/repository.py`
- Modify: `quant-board/backend/main.py`

- [ ] **Step 1: Write failing backend API test**

Add a test that ingests two half-hour snapshots with two stocks each, calls `/api/ranktrend/rank-series`, and asserts:

```python
assert response.status_code == 200
body = response.json()
assert body["source"] == "sqlite"
assert body["count"] == 2
assert body["frames"][0]["ranks"] == {"600001": 1, "600002": 2}
assert body["frames"][0]["totalCount"] == 2
assert "hotlist" not in body["frames"][0]
assert "rows" not in body["frames"][0]
```

- [ ] **Step 2: Run backend test and confirm RED**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -k rank_series -q
```

Expected: failure because `/api/ranktrend/rank-series` is not implemented.

- [ ] **Step 3: Implement repository method**

Add `Repository.load_rank_series(...)`:

```python
def load_rank_series(
    self,
    dataset_id: str,
    snapshot_type: str = "half_hour",
    start_date: str | None = None,
    end_date: str | None = None,
    before_trading_date: str | None = None,
    allowed_capture_modes: list[str] | None = None,
    exclude_restored: bool = False,
    codes: list[str] | None = None,
    limit: int | None = 50,
    sort: str = "asc",
) -> list[dict[str, Any]]:
    ...
```

The method must:

- Select frames by dataset/type/date/capture filters.
- Apply `limit` to frames before querying stock rows.
- Query stock rows only for selected `snapshot_id`s.
- If `codes` is provided, filter stock rows by code.
- Return one item per frame with `ranks` as `{code: rank}` and `totalCount` from `stock_row_count` or loaded row count.

- [ ] **Step 4: Add FastAPI endpoint**

Add:

```python
@app.get("/api/ranktrend/rank-series")
def get_ranktrend_rank_series(...):
    ...
```

The endpoint must validate `snapshot_type` and `sort`, parse `codes`, call repository, and wrap result in:

```python
{
    "ok": True,
    "dataset": Repository.dataset_to_dict(dataset),
    "datasetId": resolved_dataset_id,
    "snapshotType": snapshot_type,
    "frames": frames,
    "count": len(frames),
    "source": "sqlite",
}
```

- [ ] **Step 5: Run backend test and confirm GREEN**

Run the same pytest command. Expected: selected tests pass.

## Task 2: Frontend API Contract

**Files:**
- Modify: `src/services/snapshot/types.ts`
- Modify: `src/services/apiService.ts`
- Modify: `src/services/__tests__/apiService.test.ts`

- [ ] **Step 1: Write failing API mapping test**

Add a Vitest case that calls:

```ts
await api.getRankTrendRankSeries({
  datasetId: 'dragonboard_live',
  type: 'half_hour',
  startDate: '2026-04-21',
  allowedCaptureModes: ['real_time', 'delayed'],
  excludeRestored: true,
  sort: 'desc',
  limit: 50,
  codes: ['600001', '600002'],
})
```

Assert URL contains:

```text
/api/ranktrend/rank-series?
dataset_id=dragonboard_live
snapshot_type=half_hour
codes=600001%2C600002
```

- [ ] **Step 2: Run frontend API test and confirm RED**

Run:

```powershell
pnpm exec vitest run src/services/__tests__/apiService.test.ts
```

Expected: failure because `getRankTrendRankSeries` does not exist.

- [ ] **Step 3: Add types and ApiService method**

Add rank-series query/response types to `src/services/snapshot/types.ts`, import them in `apiService.ts`, and implement:

```ts
async getRankTrendRankSeries(params: RankTrendRankSeriesQueryOptions = {}, options?: RequestConfig)
```

Use the same QuantBoard request policy as snapshot reads, but target `/api/ranktrend/rank-series`.

- [ ] **Step 4: Run frontend API test and confirm GREEN**

Run the same Vitest command. Expected: pass.

## Task 3: RankTrendAnalyzer Switch

**Files:**
- Modify: `src/services/__tests__/RankTrendAnalyzer.test.ts`
- Modify: `src/services/RankTrendAnalyzer.ts`

- [ ] **Step 1: Write failing analyzer test**

Mock `apiService.getRankTrendRankSeries` to return six compact frames. Mock `snapshotFacade.listSnapshotFrameBundles` to throw if called. Call:

```ts
await rankTrendAnalyzer.getRankTrends(new Map([['600001', 33]]), {
  updateSignalStore: false,
})
```

Assert:

```ts
expect(apiService.getRankTrendRankSeries).toHaveBeenCalled()
expect(snapshotFacade.listSnapshotFrameBundles).not.toHaveBeenCalled()
expect(results.get('600001')?.change).toBeTypeOf('number')
expect(results.get('600001')?.confidence).toBeTypeOf('number')
```

- [ ] **Step 2: Run analyzer test and confirm RED**

Run:

```powershell
pnpm exec vitest run src/services/__tests__/RankTrendAnalyzer.test.ts
```

Expected: failure because analyzer still calls the snapshot facade.

- [ ] **Step 3: Replace history read source**

In `RankTrendAnalyzer.getSnapshotsByType(...)`, call `apiService.getRankTrendRankSeries(...)`, then map each frame to the existing internal snapshot shape:

```ts
hotlist = Object.entries(frame.ranks).map(([code, rank]) => ({ code, rank }))
```

Preserve:

- `limit`
- `minRequired`
- `fromDate` / `toDate`
- formal capture policy
- timestamp sorting
- sample-quality metadata

- [ ] **Step 4: Run analyzer test and confirm GREEN**

Run the same Vitest command. Expected: pass.

## Task 4: Focused Regression Verification

**Files:**
- No new files unless tests reveal a defect.

- [ ] **Step 1: Run RankTrend-related frontend tests**

Run:

```powershell
pnpm exec vitest run src/services/__tests__/apiService.test.ts src/services/__tests__/RankTrendAnalyzer.test.ts src/services/dataLoader/__tests__/RankTrendSignalService.test.ts src/services/dataLoader/__tests__/DataLoaderFacade.test.ts
pnpm test:ranktrend
pnpm typecheck:ranktrend
```

- [ ] **Step 2: Run backend endpoint tests**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -k "rank_series or snapshot_frames_api_ranktrend_projection_returns_lightweight_hotlist or snapshot_frames_api_uses_snapshot_cache" -q
```

- [ ] **Step 3: Confirm no RankTrend frames read remains**

Run:

```powershell
rg -n "listSnapshotFrameBundles\\(|/api/snapshots/frames|projection: 'ranktrend'" src/services/RankTrendAnalyzer.ts src/services/dataLoader src/services/__tests__
```

Expected: `RankTrendAnalyzer.ts` no longer contains `listSnapshotFrameBundles` or `projection: 'ranktrend'`.

## Task 5: Commit

**Files:**
- Commit only files touched for rank-series implementation.
- Do not commit unrelated `src/types/rankTrendDefaults.ts` if it remains user-modified.

- [ ] **Step 1: Review diff**

Run:

```powershell
git diff --check
git status --short
git diff -- src/services/RankTrendAnalyzer.ts src/services/apiService.ts src/services/snapshot/types.ts quant-board/backend/main.py quant-board/backend/data/repository.py
```

- [ ] **Step 2: Commit**

Run:

```powershell
git add docs/ranktrend/rank-series-read-model-plan.md quant-board/backend/main.py quant-board/backend/data/repository.py quant-board/tests/test_quant_board.py src/services/apiService.ts src/services/snapshot/types.ts src/services/__tests__/apiService.test.ts src/services/__tests__/RankTrendAnalyzer.test.ts
git commit -m "feat: add ranktrend rank series read model"
```
