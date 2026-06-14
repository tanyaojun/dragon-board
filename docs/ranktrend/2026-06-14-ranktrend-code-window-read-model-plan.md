# RankTrend Code-Window Read Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each code task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 RankTrend 按 `code + snapshotType` 读取单票历史 bars，避免被最近 50 个全局快照帧截断。

**Architecture:** QuantBoard 后端 `load_rank_series` 返回两层结构——`series`（per-code 历史窗口）和 `frames`（兼容现有消费方的帧级视图）。Dragon Board 的 `RankTrendAnalyzer` 改为消耗按 code 分组的历史序列，再按特征窗口计算 MACD、动量和零线交叉。样本质量门禁改为基于单票 bars 和各特征所需窗口（`minComputableBars` / `stableBars`），而不是全局 frame 命中数。

**Tech Stack:** TypeScript、FastAPI、SQLite/MongoDB 仓库层、Vitest、Pytest。

---

## Response Envelope（目标结构）

`/api/ranktrend/rank-series` 改造后响应增加 `series` 字段，同时保留 `frames` 兼容：

```json
{
  "ok": true,
  "dataset": { ... },
  "datasetId": "...",
  "snapshotType": "half_hour",
  "frames": [ /* 兼容现有消费方，每帧含 ranks + bars */ ],
  "series": {
    "600001": {
      "code": "600001",
      "bars": [
        { "snapshotId": "...", "timestamp": 1776746400000, "rank": 96, "tradingDate": "2026-04-21", "slotTime": "10:02" },
        { "snapshotId": "...", "timestamp": 1776748200000, "rank": 95, "tradingDate": "2026-04-21", "slotTime": "10:32" }
      ],
      "totalCount": 120,
      "latestSnapshotId": "half_hour:2026-06-14:14:30:xxx",
      "latestTradingDate": "2026-06-14",
      "latestSlotTime": "14:30"
    }
  },
  "count": 8,
  "source": "mongodb"
}
```

---

## File Structure

- Modify: `quant-board/backend/data/repository.py`
  - `load_rank_series(...)` 改为返回 `{frames, series}` 两层结构，series 按 code 分组。
  - 新增 `windowBars` 参数控制单票取 bar 数量上限。
- Modify: `quant-board/backend/data/mongo_repository.py`
  - 同步改造 MongoDB 主链读口，补齐 `bars` 字段（当前 MongoDB 版本只返回 `ranks`），避免 SQLite/Mongo 口径分叉。
- Modify: `quant-board/backend/main.py`
  - `/api/ranktrend/rank-series` 响应增加 `series` 字段和 `windowBars` 查询参数。
- Modify: `src/services/snapshot/types.ts`
  - 新增 `RankTrendRankSeriesCodeWindow`、更新 `RankTrendRankSeriesResponse` 增加 `series` 字段。
- Modify: `src/services/apiService.ts`
  - `RankTrendRankSeriesApiQueryOptions` 新增 `windowBars` 参数，序列化保持一致。
- Modify: `src/services/RankTrendAnalyzer.ts`
  - `getSnapshotsByType()` 改为返回 `{frames, series}` 或新方法消费 per-code 窗口。
  - `getRankTrends()` 内部的 `computeStockRankTrend` 改为从 per-code 窗口获取该票历史序列。
- Modify: `src/services/rankTrend/utils.ts`
  - 导出 `stableBars` 常量（MACD=30, 动量=50, 零线交叉=8），明确 `minComputableBars` 与 `stableBars` 分界。
- Modify: `src/services/rankTrend/technicalSignalAnalyzer.ts`
  - 保证 bars 达到 `minComputableBars` 时一定出 MACD / 动量 / 零线交叉结果。
- Modify: `src/services/dataLoader/RankTrendSignalService.ts`
  - 适配新的 per-code 历史窗口入参（调用方适配，不改变 Jump 内部计算逻辑）。
- Modify: `quant-board/docs/api-cli.md`
  - 同步更新 `/api/ranktrend/rank-series` 接口文档。
- Test: `quant-board/tests/test_quant_board.py`
- Test: `src/services/__tests__/RankTrendAnalyzer.test.ts`
- Test: `src/services/__tests__/apiService.test.ts`
- Test: `src/services/rankTrend/__tests__/technicalSignalAnalyzer.test.ts`

---

## Task 1: Backend rank-series semantics

**Files:**
- Modify: `quant-board/backend/data/repository.py`
- Modify: `quant-board/backend/data/mongo_repository.py`
- Modify: `quant-board/backend/main.py`
- Test: `quant-board/tests/test_quant_board.py`

- [ ] **Step 1: Write failing backend test**

Add a test that requests `/api/ranktrend/rank-series` for two codes (600001 with 8 frames, 600601 only in last 3 frames) and asserts:
- `body["series"]["600001"]["bars"]` has 5 bars (limit=5) in ascending time order
- `body["series"]["600601"]["bars"]` has 3 bars (only appeared in 3 frames)
- `body["frames"]` still exists for backward compatibility
- `body["series"]["600001"]["totalCount"]` reflects actual total

(This test already exists at `test_ranktrend_rank_series_api_uses_per_code_window_not_global_frame_window`, currently RED.)

- [ ] **Step 2: Run backend test and confirm RED**

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -k "rank_series_code_window" -q
```

- [ ] **Step 3: Implement code-window read model in SQLite repository**

Change `repository.py:load_rank_series(...)` to:
- Accept `windowBars: int | None = None` parameter
- After building the existing `frames` list, additionally group `SnapshotStockRowModel` rows by code
- For each requested code (or all codes in frames if no filter), extract the latest `windowBars` (or `limit`) rows
- Build `series` dict keyed by code, each containing `code`, `bars`, `totalCount`, `latestSnapshotId`, `latestTradingDate`, `latestSlotTime`
- Return `{"frames": frames, "series": series}` dict (change return type from `list` to `dict`)

- [ ] **Step 4: Implement code-window read model in MongoDB repository**

Change `mongo_repository.py:load_rank_series(...)` to:
- Accept `windowBars` parameter (same signature as SQLite)
- After building `frames`, query `snapshot_stock_rows` by code to build per-code `bars` arrays
- Add bars to series dict (MongoDB currently only returns `ranks`, must also query and return `bars`)
- Return `{"frames": frames, "series": series}`

- [ ] **Step 5: Update API endpoint**

Change `main.py:get_ranktrend_rank_series(...)` to:
- Accept `windowBars: int | None = None` query parameter
- Pass `windowBars` to `repo.load_rank_series(...)`
- Unpack the returned dict: `frames = result["frames"]; series = result["series"]`
- Add `"series": series` to the response body
- Snapshot cache key includes `windowBars`

- [ ] **Step 6: Run backend test and confirm GREEN**

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -k "rank_series_code_window" -q
```

---

## Task 2: Frontend contract alignment

**Files:**
- Modify: `src/services/snapshot/types.ts`
- Modify: `src/services/apiService.ts`
- Test: `src/services/__tests__/apiService.test.ts`

- [ ] **Step 1: Update types**

Add to `snapshot/types.ts`:
```typescript
export interface RankTrendRankSeriesCodeWindow {
  code: string
  bars: RankTrendRankSeriesBar[]
  totalCount: number
  latestSnapshotId: string
  latestTradingDate: string
  latestSlotTime: string
}

export interface RankTrendRankSeriesBar {
  snapshotId: string
  timestamp: number
  rank: number
  tradingDate: string
  slotTime: string
}
```

Add `series: Record<string, RankTrendRankSeriesCodeWindow>` to `RankTrendRankSeriesResponse`.

- [ ] **Step 2: Add `windowBars` to API query options**

In `apiService.ts`, add `windowBars?: number` to the `RankTrendRankSeriesQueryOptions` interface; verify `buildMongoSnapshotQuery` serializes it.

- [ ] **Step 3: Write/update API contract test**

Add a Vitest case asserting `getRankTrendRankSeries(...)` serializes `windowBars` correctly and the response type includes `series`.

- [ ] **Step 4: Run API test and confirm GREEN**

```powershell
pnpm exec vitest run src/services/__tests__/apiService.test.ts
```

---

## Task 3: RankTrendAnalyzer history sourcing

**Files:**
- Modify: `src/services/RankTrendAnalyzer.ts`
- Test: `src/services/__tests__/RankTrendAnalyzer.test.ts`

- [ ] **Step 1: Write failing analyzer test**

Mock the new code-window series response (with `series` field) and verify:
- `getRankTrends()` extracts per-code bars from `series` instead of scanning `frames`
- A code with 5 bars in `series` but only appearing in 1 frame still gets 5 data points for technical calculation

- [ ] **Step 2: Run analyzer test and confirm RED**

```powershell
pnpm exec vitest run src/services/__tests__/RankTrendAnalyzer.test.ts
```

- [ ] **Step 3: Switch analyzer to per-code windows**

- In `getSnapshotsByType()`, preserve the `frames`-based backward-compatible path but also extract and return `series`
- In `getRankTrends()`, change `computeStockRankTrend` to accept a per-code bar array extracted from `series[code]?.bars`
- If `series` is unavailable (old backend), fall back to existing frame-scanning logic
- Derive sample quality from per-code bars count vs `minComputableBars` / `stableBars`

- [ ] **Step 4: Run analyzer test and confirm GREEN**

```powershell
pnpm exec vitest run src/services/__tests__/RankTrendAnalyzer.test.ts
```

---

## Task 4: Technical-window behavior

**Files:**
- Modify: `src/services/rankTrend/utils.ts`
- Modify: `src/services/rankTrend/technicalSignalAnalyzer.ts`
- Test: `src/services/rankTrend/__tests__/technicalSignalAnalyzer.test.ts`

- [ ] **Step 1: Export stableBars constants**

In `utils.ts`, export:
```typescript
export const STABLE_BARS = {
  macd: 30,
  momentum: 50,
  zeroCross: 8,
} as const

export function getMaxStableBars(): number {
  return Math.max(STABLE_BARS.macd, STABLE_BARS.momentum, STABLE_BARS.zeroCross)
}
```

Keep existing `getMacdMinSamples` and `getTechnicalMinSamples` as `minComputableBars` equivalents.

- [ ] **Step 2: Add failing tests for minimal windows**

Cover cases:
- MACD bars just reach `macdSlow` → produces non-zero DIF/DEA/histogram
- MACD bars below `macdSlow` → returns zero values with `sampleQuality` marker
- zero-cross bars reach minimum confirm window → detects cross when actual crossing occurs
- momentum bars reach `max(momentumPeriods)+1` → produces momentum signal

- [ ] **Step 3: Run technical tests and confirm RED**

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/technicalSignalAnalyzer.test.ts
```

- [ ] **Step 4: Implement sample quality markers**

In `technicalSignalAnalyzer.ts`, when bars < `minComputableBars`, return zero values AND set `sampleQuality.reason` indicating insufficient data. When bars ≥ `minComputableBars` but < `stableBars` for a given feature, compute the value but mark it as unstable.

- [ ] **Step 5: Run technical tests and confirm GREEN**

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/technicalSignalAnalyzer.test.ts
```

---

## Task 5: Regression verification

**Files:**
- Modify: `src/services/dataLoader/RankTrendSignalService.ts` (adapter change only)
- Modify: `quant-board/docs/api-cli.md`
- No new files unless tests reveal a defect.

- [ ] **Step 1: Adapt Jump signal chain**

In `RankTrendSignalService.ts`, update `applyJumpSignals` to consume per-code windows from the new `series` response format when available, falling back to frame-based scanning. The Jump calculation logic (`jumpDetector`, `jumpSignalService`) remains unchanged.

- [ ] **Step 2: Update API documentation**

Update `quant-board/docs/api-cli.md` to document:
- New `windowBars` query parameter for `/api/ranktrend/rank-series`
- New `series` response field structure
- The `frames` field remains for backward compatibility

- [ ] **Step 3: Run focused RankTrend tests**

```powershell
pnpm exec vitest run src/services/__tests__/apiService.test.ts src/services/__tests__/RankTrendAnalyzer.test.ts src/services/rankTrend/__tests__/technicalSignalAnalyzer.test.ts src/services/dataLoader/__tests__/RankTrendSignalService.test.ts
pnpm test:ranktrend
pnpm typecheck:ranktrend
```

- [ ] **Step 4: Run backend regression**

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -k "rank_series" -q
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -k "rank_series_code_window" -q
```

- [ ] **Step 5: Check diff scope**

```powershell
git diff --stat
git status --short
```
