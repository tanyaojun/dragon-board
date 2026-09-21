# 前端列表池对齐后端快照帧池（池源替换）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 前端列表池（`dataLayer.getStocks()`）membership 改为后端最新 half_hour 帧池，消除 30min 热榜缓存导致的时点错位，实现「列表 = 帧池」。

**Architecture:** 新增 `framePoolSource.ts` 帧池读取模块（复用现有 `snapshotBackendRead` 读通道，无新 API）；在 `DataLoaderFacade.mergeData()` 单点切换 membership 来源（帧池 codes 优先、热榜合并池回退 + provenance 打标）；`DragonBreathPanel` 注脚语义同步更新。

**Tech Stack:** Vue 3 + TypeScript + Vitest；后端读通道 `src/services/snapshot/backendRead.ts`（已存在）。

**Spec:** `docs/superpowers/specs/2026-09-21-frontend-pool-frame-alignment-design.md`

## Global Constraints

- **禁止覆盖用户未提交改动**：`src/components/panels/DragonBreathPanel.vue`、`src/components/panels/__tests__/DragonBreathPanel.test.ts`、`src/components/common/DataTable.vue`、`src/components/common/__tests__/DataTable.test.ts` 有用户未提交修改。改这些文件前必须先 Read 当前内容，只做最小增量编辑，不回退、不格式化用户的既有改动。
- TDD：每个任务先写失败测试，再写实现（项目 memory 硬约束）。
- 不改 QuantBoard 后端/采集器任何代码；不新增 API/MongoDB 集合。
- 不改 RankTrend 信号计算与热度算法；`PLATFORM_CACHE_TTL_MS` 保留不动。
- 代码风格：无分号、单引号、printWidth 100（`.prettierrc.json`）；中文注释说明「为什么」。
- 破坏性 Git 命令禁止（`git reset --hard`、`git checkout -- <path>` 等）；每次只 add 明确路径。
- 测试文件放被测模块旁 `__tests__/*.test.ts`；测试间互相独立（现有 DataLoaderFacade 测试用模块级 vi.mock + 可变局部变量模式，新用例遵循同一模式）。
- 常用命令（仓库根目录）：`pnpm exec vitest run <file>` 单文件测试；`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` 类型检查；`pnpm test:ranktrend` golden 回归。

---

### Task 1: 类型、配置与 DataLayer provenance 状态位

**Files:**
- Modify: `src/types/data-layer.ts`（新增 `ListPoolSource` / `ListPoolProvenance` 类型）
- Modify: `src/types/index.ts`（data-layer 类型导出块加两行）
- Create: `src/config/listPool.ts`（池源模式开关 + 探测参数）
- Modify: `src/services/DataLayer.ts`（provenance 内存状态 + set/get + 节流通知）
- Test: `src/services/__tests__/DataLayer.test.ts`（新增 describe 块）

**Interfaces:**
- Consumes: 无（本任务为基座）。
- Produces（后续任务依赖的精确签名）:
  - `type ListPoolSource = 'frame-pool' | 'hotlist-merged' | 'startup-bundle'`（`@/types`）
  - `interface ListPoolProvenance { source: ListPoolSource; slotTime?: string; tradingDate?: string; degradeReason?: string; updatedAt: number }`（`@/types`）
  - `dataLayer.setListPoolProvenance(provenance: ListPoolProvenance | null): void`
  - `dataLayer.getListPoolProvenance(): ListPoolProvenance | null`
  - `const LIST_POOL_SOURCE_MODE: 'frame-pool' | 'hotlist-merged'`（`@/config/listPool`，默认 `'frame-pool'`）
  - `const FRAME_POOL_PROBE_INTERVAL_MS = 60000`、`const FRAME_POOL_ROW_LIMIT = 500`（`@/config/listPool`）

- [ ] **Step 1: 写失败测试**

在 `src/services/__tests__/DataLayer.test.ts` 文件末尾追加（沿用现有 `describe('DataLayer ...')` 风格，直接 import 顶部已有的 `dataLayer`）：

```typescript
describe('DataLayer list pool provenance', () => {
  it('默认 provenance 为 null，set/get 返回同一对象', () => {
    dataLayer.setListPoolProvenance(null)
    expect(dataLayer.getListPoolProvenance()).toBeNull()

    const provenance = {
      source: 'frame-pool' as const,
      slotTime: '10:30',
      tradingDate: '2026-09-21',
      updatedAt: 1758426600000,
    }
    dataLayer.setListPoolProvenance(provenance)
    expect(dataLayer.getListPoolProvenance()).toEqual(provenance)

    dataLayer.setListPoolProvenance(null)
    expect(dataLayer.getListPoolProvenance()).toBeNull()
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm exec vitest run src/services/__tests__/DataLayer.test.ts`
Expected: FAIL，报 `dataLayer.setListPoolProvenance is not a function`

- [ ] **Step 3: 实现**

3a. `src/types/data-layer.ts` 末尾追加（该文件是 DataLayer 公开结构类型文件）：

```typescript
/** 行情列表池来源（2026-09-21 池源替换）：frame-pool=后端最新 half_hour 帧池 */
export type ListPoolSource = 'frame-pool' | 'hotlist-merged' | 'startup-bundle'

/** 列表池 provenance：对账注脚与诊断依据，随每次池发布更新 */
export interface ListPoolProvenance {
  source: ListPoolSource
  slotTime?: string
  tradingDate?: string
  degradeReason?: string
  updatedAt: number
}
```

3b. `src/types/index.ts` 的 `export type { ... } from './data-layer'` 块内按字母序插入两行：

```typescript
  ListPoolProvenance,
  ListPoolSource,
```

3c. 创建 `src/config/listPool.ts`：

```typescript
// src/config/listPool.ts
/**
 * 行情列表池来源配置（2026-09-21 池源替换，spec:
 * docs/superpowers/specs/2026-09-21-frontend-pool-frame-alignment-design.md）
 */
export const LIST_POOL_SOURCE_MODE: 'frame-pool' | 'hotlist-merged' = 'frame-pool'

/** 新帧槽探测最小间隔：帧槽 30min 闭合，1min 探测延迟足够，且避免 10s 行情刷新链打后端 */
export const FRAME_POOL_PROBE_INTERVAL_MS = 60_000

/** 单帧股票行读取上限：实测自治帧池 240-250 行，500 为安全余量 */
export const FRAME_POOL_ROW_LIMIT = 500
```

3d. `src/services/DataLayer.ts`：在 `setMergedStocks`（约 line 1120）方法附近新增状态与方法。先 Read 当前文件确认 state 结构声明位置，然后：

state 字段声明（与 `merged` 等同级，找到 state 初始化对象按现有风格加入）：

```typescript
    listPoolProvenance: null as ListPoolProvenance | null,
```

方法（放在 `setMergedStocks` 后面）：

```typescript
  /**
   * 行情列表池 provenance（2026-09-21 池源替换）：
   * 记录当前列表 membership 来自哪个池（帧池/热榜合并池/启动缓存），
   * 供面板对账注脚与诊断使用，不参与任何业务计算。
   */
  setListPoolProvenance(provenance: ListPoolProvenance | null) {
    this.state.listPoolProvenance = provenance
    this.throttledNotify('listPool.provenance', provenance)
  }

  getListPoolProvenance(): ListPoolProvenance | null {
    return this.state.listPoolProvenance
  }
```

顶部 import：该文件已从 `@/types` 或 `../types` 导入 `MergedStock` 等，按现有 import 路径补 `ListPoolProvenance`（type-only import）。注意 `state` 的类型声明处若为显式接口，需同步加 `listPoolProvenance: ListPoolProvenance | null` 字段（先 Read 确认 state 类型写法再改）。

- [ ] **Step 4: 运行测试确认通过**

Run: `pnpm exec vitest run src/services/__tests__/DataLayer.test.ts`
Expected: PASS（全部用例，含新增）

- [ ] **Step 5: 类型检查**

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add src/types/data-layer.ts src/types/index.ts src/config/listPool.ts src/services/DataLayer.ts src/services/__tests__/DataLayer.test.ts
git commit -m "feat(dataLoader): 列表池 provenance 状态位与池源模式配置基座"
```

---

### Task 2: framePoolSource 模块（帧池读取 + 种子行 + platformData 过滤）

**Files:**
- Create: `src/services/dataLoader/framePoolSource.ts`
- Modify: `src/services/dataLoader/StockMergeCoordinator.ts`（抽出可导出的 `createEmptyMergedStock`）
- Test: `src/services/dataLoader/__tests__/framePoolSource.test.ts`

**Interfaces:**
- Consumes: `snapshotBackendRead.listSnapshotFrames({ type, tradingDate, sort, limit })` / `listSnapshotStockRows({ type, tradingDate, slotTime, sort, limit })`（`src/services/snapshot/backendRead.ts`，已存在）；`toLocalTradingDate`（`src/services/snapshot/identity.ts`）；Task 1 的 `FRAME_POOL_ROW_LIMIT`。
- Produces（Task 3/4 依赖）:
  - `interface FramePoolSnapshot { codes: Set<string>; slotTime: string; tradingDate: string; rowsByCode: Map<string, SnapshotStockRow> }`
  - `type FramePoolUnavailableReason = 'http-error' | 'no-frame' | 'empty-rows' | 'mode-disabled'`
  - `interface FramePoolFetchResult { pool: FramePoolSnapshot | null; reason?: FramePoolUnavailableReason; message?: string }`
  - `function fetchLatestFramePool(options?: { tradingDate?: string }): Promise<FramePoolFetchResult>`（任何失败返回结构化 null，不抛异常）
  - `function buildFrameSeedStock(row: SnapshotStockRow): MergedStock`
  - `function filterPlatformDataToCodes(platformData: Record<string, any[]>, codes: Set<string>): Record<string, any[]>`
  - `createEmptyMergedStock(code: string): MergedStock`（从 `./StockMergeCoordinator` 导出）

- [ ] **Step 1: 写失败测试**

创建 `src/services/dataLoader/__tests__/framePoolSource.test.ts`：

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SnapshotStockRow } from '../../snapshot/types'

const listSnapshotFrames = vi.fn()
const listSnapshotStockRows = vi.fn()

vi.mock('../../snapshot/backendRead', () => ({
  snapshotBackendRead: {
    listSnapshotFrames: (...args: unknown[]) => listSnapshotFrames(...args),
    listSnapshotStockRows: (...args: unknown[]) => listSnapshotStockRows(...args),
  },
}))

import {
  buildFrameSeedStock,
  fetchLatestFramePool,
  filterPlatformDataToCodes,
} from '../framePoolSource'

function makeRow(overrides: Partial<SnapshotStockRow> = {}): SnapshotStockRow {
  return {
    id: 'half_hour:2026-09-21:10:30:600000',
    snapshotId: 'half_hour:2026-09-21:10:30',
    type: 'half_hour',
    tradingDate: '2026-09-21',
    slotTime: '10:30',
    timestamp: 1758426600000,
    captureMode: 'real_time',
    source: 'quantboard_collector',
    code: '600000',
    name: '浦发银行',
    rank: 1,
    compRank: 1,
    platforms: 5,
    price: 12.34,
    change: 2.1,
    volume: 123456,
    turnoverRate: 3.2,
    ...overrides,
  } as SnapshotStockRow
}

describe('fetchLatestFramePool', () => {
  beforeEach(() => {
    listSnapshotFrames.mockReset()
    listSnapshotStockRows.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('正常路径：先取最新帧，再按 slotTime 取全量行', async () => {
    listSnapshotFrames.mockResolvedValue([
      { slotTime: '10:30', tradingDate: '2026-09-21', stockRowCount: 2 },
    ])
    listSnapshotStockRows.mockResolvedValue([makeRow(), makeRow({ code: '000001', name: '平安银行' })])

    const result = await fetchLatestFramePool()

    expect(listSnapshotFrames).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'half_hour', sort: 'desc', limit: 1 }),
    )
    expect(listSnapshotStockRows).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'half_hour', slotTime: '10:30', limit: 500 }),
    )
    expect(result.pool).not.toBeNull()
    expect(result.pool!.slotTime).toBe('10:30')
    expect(result.pool!.codes).toEqual(new Set(['600000', '000001']))
    expect(result.pool!.rowsByCode.get('600000')?.name).toBe('浦发银行')
  })

  it('当日无帧：返回结构化 no-frame，不抛异常', async () => {
    listSnapshotFrames.mockResolvedValue([])

    const result = await fetchLatestFramePool()

    expect(result.pool).toBeNull()
    expect(result.reason).toBe('no-frame')
    expect(listSnapshotStockRows).not.toHaveBeenCalled()
  })

  it('股票行为空：返回结构化 empty-rows', async () => {
    listSnapshotFrames.mockResolvedValue([{ slotTime: '10:30', tradingDate: '2026-09-21' }])
    listSnapshotStockRows.mockResolvedValue([])

    const result = await fetchLatestFramePool()

    expect(result.pool).toBeNull()
    expect(result.reason).toBe('empty-rows')
  })

  it('HTTP 失败：返回结构化 http-error 且带 message', async () => {
    listSnapshotFrames.mockRejectedValue(new Error('snapshot_backend_read_failed'))

    const result = await fetchLatestFramePool()

    expect(result.pool).toBeNull()
    expect(result.reason).toBe('http-error')
    expect(result.message).toContain('snapshot_backend_read_failed')
  })

  it('显式 tradingDate 透传（跨交易日场景由调用方决定日期）', async () => {
    listSnapshotFrames.mockResolvedValue([{ slotTime: '15:00', tradingDate: '2026-09-19' }])
    listSnapshotStockRows.mockResolvedValue([makeRow()])

    const result = await fetchLatestFramePool({ tradingDate: '2026-09-19' })

    expect(listSnapshotFrames).toHaveBeenCalledWith(
      expect.objectContaining({ tradingDate: '2026-09-19' }),
    )
    expect(result.pool!.tradingDate).toBe('2026-09-19')
  })
})

describe('buildFrameSeedStock', () => {
  it('帧行字段映射：名称/价格等为兜底值，平台排名保持 DEFAULT_RANK 占位', () => {
    const seed = buildFrameSeedStock(makeRow())

    expect(seed.code).toBe('600000')
    expect(seed.name).toBe('浦发银行')
    expect(seed.platformName).toBe('浦发银行')
    expect(seed.price).toBe(12.34)
    expect(seed.change).toBe(2.1)
    expect(seed.volume).toBe(123456)
    expect(seed.turnoverRate).toBe(3.2)
    // 排名字段仅占位：合并链由 ComprehensiveRankEngine 统一重算
    expect(seed.emRank).toBeDefined()
    expect(seed.platforms).toBe(0)
  })

  it('缺字段/非法值回退默认：NaN 价格、空名称不产生脏数据', () => {
    const seed = buildFrameSeedStock(makeRow({ price: undefined, name: '-', volume: Number.NaN }))

    expect(seed.price).toBe(0)
    expect(seed.volume).toBe(0)
    expect(seed.name).toBe('')
    expect(seed.platformName).toBe('')
  })
})

describe('filterPlatformDataToCodes', () => {
  it('只保留帧池 codes 内的行，空平台不保留键', () => {
    const platformData = {
      eastmoney: [
        { code: '600000', rank: 1 },
        { code: '999999', rank: 2 },
      ],
      ths: [{ code: '999999', rank: 1 }],
      kpl: [],
    }
    const filtered = filterPlatformDataToCodes(platformData, new Set(['600000']))

    expect(filtered.eastmoney).toEqual([{ code: '600000', rank: 1 }])
    expect(filtered.ths).toBeUndefined()
    expect(filtered.kpl).toBeUndefined()
  })

  it('非数组值原样透传，防御脏 platformData', () => {
    const platformData = { eastmoney: null } as any
    expect(filterPlatformDataToCodes(platformData, new Set(['600000']))).toEqual({ eastmoney: null })
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/framePoolSource.test.ts`
Expected: FAIL，报 `Cannot find module '../framePoolSource'`

- [ ] **Step 3: 实现**

3a. `src/services/dataLoader/StockMergeCoordinator.ts`：把 `private createEmptyStock(code: string): MergedStock` 方法体抽为模块级导出函数，类方法委托调用（保持类内行为不变）。在文件中 `export interface StockMergeCoordinatorInput` 之前加入：

```typescript
/**
 * 构建 MergedStock 全字段空壳（含各平台 DEFAULT_RANK 占位）。
 * 供合并链与帧池种子行共用，保证种子行结构与普通合并行同形。
 */
export function createEmptyMergedStock(code: string): MergedStock {
  // 函数体 = 原 createEmptyStock 方法体原样搬移（stockCodeManager 名称回退 + 全字段默认值）
}
```

类内改为：

```typescript
  private createEmptyStock(code: string): MergedStock {
    return createEmptyMergedStock(code)
  }
```

3b. 创建 `src/services/dataLoader/framePoolSource.ts`：

```typescript
// src/services/dataLoader/framePoolSource.ts
// 行情列表池帧源（2026-09-21 池源替换）：读取后端最新 half_hour 帧池作为
// 前端列表 membership 的事实源。复用既有 snapshotBackendRead 正式读通道，
// 不新增后端 API；任何失败返回结构化 null（fail-visible，不抛异常打断加载链）。
import type { MergedStock } from '@/types'
import { FRAME_POOL_ROW_LIMIT } from '@/config/listPool'
import { snapshotBackendRead } from '../snapshot/backendRead'
import { toLocalTradingDate } from '../snapshot/identity'
import type { SnapshotStockRow } from '../snapshot/types'
import { createEmptyMergedStock } from './StockMergeCoordinator'

export interface FramePoolSnapshot {
  codes: Set<string>
  slotTime: string
  tradingDate: string
  rowsByCode: Map<string, SnapshotStockRow>
}

export type FramePoolUnavailableReason = 'http-error' | 'no-frame' | 'empty-rows' | 'mode-disabled'

export interface FramePoolFetchResult {
  pool: FramePoolSnapshot | null
  reason?: FramePoolUnavailableReason
  message?: string
}

/** 读取当日最新 half_hour 帧的全量股票行；两步读取（先帧后行），失败逐级结构化降级 */
export async function fetchLatestFramePool(
  options: { tradingDate?: string } = {},
): Promise<FramePoolFetchResult> {
  const tradingDate = options.tradingDate || toLocalTradingDate(new Date())
  try {
    const frames = await snapshotBackendRead.listSnapshotFrames({
      type: 'half_hour',
      tradingDate,
      sort: 'desc',
      limit: 1,
    })
    const frame = frames[0]
    if (!frame?.slotTime) {
      return { pool: null, reason: 'no-frame', message: `当日(${tradingDate})无 half_hour 帧` }
    }

    const rows = await snapshotBackendRead.listSnapshotStockRows({
      type: 'half_hour',
      tradingDate,
      slotTime: frame.slotTime,
      sort: 'asc',
      limit: FRAME_POOL_ROW_LIMIT,
    })
    const rowsByCode = new Map<string, SnapshotStockRow>()
    for (const row of rows || []) {
      const code = String(row?.code || '')
      if (code && !rowsByCode.has(code)) rowsByCode.set(code, row)
    }
    if (!rowsByCode.size) {
      return {
        pool: null,
        reason: 'empty-rows',
        message: `帧 ${tradingDate} ${frame.slotTime} 无有效股票行`,
      }
    }
    return { pool: { codes: new Set(rowsByCode.keys()), slotTime: frame.slotTime, tradingDate, rowsByCode } }
  } catch (error) {
    return {
      pool: null,
      reason: 'http-error',
      message: error instanceof Error ? error.message : String(error),
    }
  }
}

function toFiniteNumber(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

/**
 * 帧行 → 种子行：名称与快照时点行情为兜底值（实时行情到达后被覆盖）；
 * 排名字段保持 DEFAULT_RANK 占位——合并链由 ComprehensiveRankEngine 对全列表
 * 统一重算（2026-08-24 回滚口径），列表排序口径单一，不混用后端帧内排名。
 */
export function buildFrameSeedStock(row: SnapshotStockRow): MergedStock {
  const stock = createEmptyMergedStock(String(row?.code || ''))
  const seedName = String(row?.name || '').trim()
  if (seedName && seedName !== '-') {
    stock.name = seedName
    stock.platformName = seedName
  }
  const price = toFiniteNumber(row?.price)
  if (price !== null && price > 0) stock.price = price
  const change = toFiniteNumber(row?.change)
  if (change !== null) stock.change = change
  const volume = toFiniteNumber(row?.volume)
  if (volume !== null && volume > 0) stock.volume = volume
  const turnoverRate = toFiniteNumber(row?.turnoverRate)
  if (turnoverRate !== null && turnoverRate > 0) stock.turnoverRate = turnoverRate
  return stock
}

/** 帧池模式下 platformData 行过滤到帧池范围；空平台不保留键（calculatePlatformTotals 按行数计 0） */
export function filterPlatformDataToCodes(
  platformData: Record<string, any[]>,
  codes: Set<string>,
): Record<string, any[]> {
  const filtered: Record<string, any[]> = {}
  for (const [platform, rows] of Object.entries(platformData || {})) {
    if (!Array.isArray(rows)) {
      filtered[platform] = rows
      continue
    }
    const kept = rows.filter((row) => codes.has(String(row?.code || '')))
    if (kept.length) filtered[platform] = kept
  }
  return filtered
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/framePoolSource.test.ts src/services/dataLoader/__tests__/StockMergeCoordinator.test.ts`
Expected: PASS（新模块全部用例 + StockMergeCoordinator 既有用例无回归；若后者文件名不同，先 `ls src/services/dataLoader/__tests__/` 确认实际文件名再运行）

- [ ] **Step 5: 类型检查**

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 无错误

- [ ] **Step 6: Commit**

```bash
git add src/services/dataLoader/framePoolSource.ts src/services/dataLoader/StockMergeCoordinator.ts src/services/dataLoader/__tests__/framePoolSource.test.ts
git commit -m "feat(dataLoader): framePoolSource 帧池读取模块（两步读取/种子行/platformData 过滤）"
```

---

### Task 3: mergeData 池源切换 + 启动缓存 provenance

**Files:**
- Modify: `src/services/dataLoader/DataLoaderFacade.ts`（`mergeData` 入口段约 line 869-911、`publishStartupBundle` 约 line 378-396）
- Test: `src/services/dataLoader/__tests__/DataLoaderFacade.test.ts`

**Interfaces:**
- Consumes: Task 1 的 `LIST_POOL_SOURCE_MODE`、`dataLayer.setListPoolProvenance/getListPoolProvenance`；Task 2 的 `fetchLatestFramePool/buildFrameSeedStock/filterPlatformDataToCodes`。
- Produces: `mergeData()` 的 membership 语义 = 帧池 codes（帧池模式）；`dataLayer.getListPoolProvenance()` 在每次合并后可观测。Task 4 的探测复用 `this.loadPlatformAndMerge`，无需新接口。

- [ ] **Step 1: 写失败测试**

先 Read `src/services/dataLoader/__tests__/DataLoaderFacade.test.ts` 当前完整内容。在既有 `vi.mock('../PlatformHotlistService', ...)` 等 mock 声明附近加入：

```typescript
let framePoolResult: any = { pool: null, reason: 'http-error' as const }

vi.mock('../framePoolSource', () => ({
  fetchLatestFramePool: vi.fn(async () => framePoolResult),
  buildFrameSeedStock: vi.fn((row: any) => ({
    code: String(row.code),
    name: String(row.name || ''),
    platformName: String(row.name || ''),
    price: Number(row.price) || 0,
    change: Number(row.change) || 0,
    volume: Number(row.volume) || 0,
    turnoverRate: Number(row.turnoverRate) || 0,
    platforms: 0,
  })),
  filterPlatformDataToCodes: vi.fn(
    (platformData: Record<string, any[]>, codes: Set<string>) => {
      const filtered: Record<string, any[]> = {}
      for (const [platform, rows] of Object.entries(platformData || {})) {
        if (!Array.isArray(rows)) {
          filtered[platform] = rows
          continue
        }
        const kept = rows.filter((row) => codes.has(String(row?.code || '')))
        if (kept.length) filtered[platform] = kept
      }
      return filtered
    },
  ),
}))
```

注意：mock 中 `fetchLatestFramePool` 读取模块级变量 `framePoolResult`；`vi.mock` 工厂被提升（hoisted），引用外部 let 变量需放进 `vi.hoisted`：

```typescript
const framePoolState = vi.hoisted(() => ({
  result: { pool: null, reason: 'http-error' } as any,
}))
```

mock 工厂内用 `framePoolState.result`；测试内直接改 `framePoolState.result = {...}`。既有用例默认 `framePoolState.result` 为 `{ pool: null, reason: 'http-error' }` → 走热榜合并池降级路径，既有断言不受影响。

在文件中新增 describe 块（沿用现有测试的 `loadPlatformAndMerge`/`mergeData` 调用方式——先阅读现有用例如何驱动 mergeData，如 `await dataLoader.mergeData()` 或经 `loadAllPlatforms()`；按现有驱动方式写）：

```typescript
describe('mergeData frame-pool membership', () => {
  beforeEach(() => {
    framePoolState.result = {
      pool: {
        codes: new Set(['600000', '300750', '000001']),
        slotTime: '10:30',
        tradingDate: '2026-09-21',
        rowsByCode: new Map([
          ['600000', { code: '600000', name: '浦发银行', price: 12.34 }],
          ['300750', { code: '300750', name: '宁德时代', price: 300 }],
          ['000001', { code: '000001', name: '平安银行', price: 15 }],
        ]),
      },
    }
    // platformRows（现有测试夹具）含 000001；帧池另有 600000/300750 无平台行
  })

  afterEach(() => {
    framePoolState.result = { pool: null, reason: 'http-error' }
  })

  it('membership 等于帧池 codes：平台行被过滤、帧行种子补齐', async () => {
    // 按现有用例方式驱动一次完整 merge（含行情 quoteBatchResult 提供 600000 实时价）
    const stocks = dataLayer.getStocks()
    const codes = new Set(stocks.map((s: any) => s.code))
    expect(codes).toEqual(new Set(['600000', '300750', '000001']))
    // 600000 无平台行 → 来自种子，名称取帧行
    const seedStock = stocks.find((s: any) => s.code === '600000')
    expect(seedStock?.name).toBe('浦发银行')
  })

  it('帧池模式打 provenance frame-pool + slotTime', async () => {
    const provenance = dataLayer.getListPoolProvenance()
    expect(provenance?.source).toBe('frame-pool')
    expect(provenance?.slotTime).toBe('10:30')
  })

  it('帧池不可用回退热榜合并池并打 provenance', async () => {
    framePoolState.result = { pool: null, reason: 'http-error', message: 'boom' }
    // 再次驱动一次 merge
    const provenance = dataLayer.getListPoolProvenance()
    expect(provenance?.source).toBe('hotlist-merged')
    expect(provenance?.degradeReason).toBe('http-error')
    // membership 回到热榜合并池（现有夹具 platformRows 的 000001）
    const codes = new Set(dataLayer.getStocks().map((s: any) => s.code))
    expect(codes.has('000001')).toBe(true)
  })
})

describe('publishStartupBundle provenance', () => {
  it('启动缓存发布打 startup-bundle provenance', async () => {
    // 沿用现有 startup-bundle 缓存命中用例的驱动方式（startupBundle 夹具 + bootstrapInitialData）
    expect(dataLayer.getListPoolProvenance()?.source).toBe('startup-bundle')
  })
})
```

（执行者按现有用例的 beforeEach 重置模式与驱动函数补全 `// 驱动` 处的实际调用；关键断言不得删减。）

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/DataLoaderFacade.test.ts`
Expected: 新增用例 FAIL（membership 仍是热榜并集、provenance 为 null），既有用例 PASS

- [ ] **Step 3: 实现**

3a. import 区（`DataLoaderFacade.ts` 顶部现有 import 附近）：

```typescript
import { LIST_POOL_SOURCE_MODE } from '@/config/listPool'
import {
  buildFrameSeedStock,
  fetchLatestFramePool,
  filterPlatformDataToCodes,
} from './framePoolSource'
```

3b. `mergeData()`（line 869 起）入口段改写。原：

```typescript
    const allCodes = this.getAllHotCodes()
    const codesArray = Array.from(allCodes)
```

改为：

```typescript
    // 池源切换（2026-09-21 spec）：帧池优先，失败/关闭回退热榜合并池（结构化降级）
    const framePool =
      LIST_POOL_SOURCE_MODE === 'frame-pool' ? await fetchLatestFramePool() : null
    const framePoolMode = Boolean(framePool?.pool && framePool.pool.codes.size > 0)
    const allCodes = framePoolMode ? framePool!.pool!.codes : this.getAllHotCodes()
    const codesArray = Array.from(allCodes)
```

原 existingMap 段之后（`const existingMap = new Map(...)` 建立后）追加种子注入：

```typescript
    if (framePoolMode) {
      // 帧池中无热榜行的股票以帧行做种子，保证 membership 精确等于帧池
      for (const [code, row] of framePool!.pool!.rowsByCode) {
        if (!existingMap.has(code)) existingMap.set(code, buildFrameSeedStock(row))
      }
    }
```

原 `stockMergeCoordinator.merge({ platformData: this.state.value.data || {}, ... })` 调用中 `platformData` 实参改为：

```typescript
        platformData: framePoolMode
          ? filterPlatformDataToCodes(this.state.value.data || {}, allCodes)
          : this.state.value.data || {},
```

在第 6 步 `const basePublishVersion = this.publishStocks(merged, { reason: 'base-merge' })` 之后（deferSignalEnrichment 早返回分支**之前**，保证两条返回路径都已打标）加入：

```typescript
    dataLayer.setListPoolProvenance(
      framePoolMode
        ? {
            source: 'frame-pool',
            slotTime: framePool!.pool!.slotTime,
            tradingDate: framePool!.pool!.tradingDate,
            updatedAt: Date.now(),
          }
        : {
            source: 'hotlist-merged',
            degradeReason: framePool?.reason || 'mode-disabled',
            updatedAt: Date.now(),
          },
    )
```

3c. `publishStartupBundle()`（line 378 起）在 `this.publishStocks(bundle.stocks || [], {...})` 之前加入：

```typescript
    // 启动缓存快路径：membership 仍为上次启动时点的热榜池，如实打标（后台刷新随即对齐帧池）
    dataLayer.setListPoolProvenance({ source: 'startup-bundle', updatedAt: Date.now() })
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/DataLoaderFacade.test.ts`
Expected: PASS（新增用例 + 全部既有用例；既有用例依赖默认降级路径 framePoolState.result）

- [ ] **Step 5: 全量相关回归**

Run: `pnpm test`
Expected: PASS（关注 RankTrendSignalService、snapshot 相关测试无回归——信号重算发布路径 map 现有 stocks，membership 不变）

- [ ] **Step 6: Commit**

```bash
git add src/services/dataLoader/DataLoaderFacade.ts src/services/dataLoader/__tests__/DataLoaderFacade.test.ts
git commit -m "feat(dataLoader): mergeData 池源切换——帧池 membership 优先 + provenance 打标 + 启动缓存标记"
```

---

### Task 4: 新帧槽探测（30min 槽位跟随）

**Files:**
- Modify: `src/services/dataLoader/DataLoaderFacade.ts`（新增 `maybeRefreshFramePool`，接线到 `runQuoteRefresh` 末尾 `maybeRefreshPlatformCache()` 附近，约 line 679）
- Test: `src/services/dataLoader/__tests__/DataLoaderFacade.test.ts`

**Interfaces:**
- Consumes: Task 2 `fetchLatestFramePool`；Task 1 `FRAME_POOL_PROBE_INTERVAL_MS`、`dataLayer.getListPoolProvenance`。
- Produces: 槽位切换后 ≤1min 内列表自动重建为最新帧池；探测失败静默跳过（不打扰行情刷新链，下次再探）。

- [ ] **Step 1: 写失败测试**

在 DataLoaderFacade.test.ts 追加（`framePoolState` 与 Task 3 相同；探测用例需同时控制时间间隔——用 `vi.useFakeTimers` 或把「上次探测时间」注入；实现用私有字段，测试经可观测行为断言：同一 slotTime 不重复触发 `loadAllPlatforms`/merge，新 slotTime 触发后 provenance 更新）：

```typescript
describe('maybeRefreshFramePool slot probe', () => {
  it('同槽不重复重建；新槽出现则重建并更新 provenance', async () => {
    // 1. 已处于帧池模式（先驱动一次 Task 3 的帧池 merge）
    framePoolState.result = {
      pool: {
        codes: new Set(['600000']),
        slotTime: '10:30',
        tradingDate: '2026-09-21',
        rowsByCode: new Map([['600000', { code: '600000', name: '浦发银行', price: 12 }]]),
      },
    }
    // 驱动一次 merge（现有用例驱动方式）…

    // 2. 模拟 10s 行情刷新 tick（现有用例如何触发 runQuoteRefresh/refeshScheduler 按现有模式）
    //    provenance.slotTime === 最新帧 slotTime → 不触发重建（mergeData 调用计数不变）

    // 3. framePoolState.result.pool.slotTime 改为 '11:00' → 再触发 tick →
    //    provenance.slotTime === '11:00'，membership 更新为新槽 codes
    expect(dataLayer.getListPoolProvenance()?.slotTime).toBe('11:00')
  })

  it('探测失败（http-error）静默跳过，不影响当前列表与 provenance', async () => {
    framePoolState.result = { pool: null, reason: 'http-error' }
    // 触发 tick 后：provenance 保持原值，列表不变，无未捕获异常
  })
})
```

（执行者按现有测试文件中行情刷新链用例的驱动方式补全 tick 触发；探测间隔门限若使第二跳不触发，用 `vi.useFakeTimers().setSystemTime(...)` 前移 `FRAME_POOL_PROBE_INTERVAL_MS + 1`。）

- [ ] **Step 2: 运行测试确认失败**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/DataLoaderFacade.test.ts`
Expected: 新增 describe FAIL（无探测逻辑，新槽 provenance 仍是 '10:30'）

- [ ] **Step 3: 实现**

3a. import 补 `FRAME_POOL_PROBE_INTERVAL_MS`（Task 1 已 import `LIST_POOL_SOURCE_MODE`，同语句合并）。

3b. 类字段（与其他私有状态字段一起）：

```typescript
  private framePoolProbeRunning = false
  private lastFramePoolProbeAt = 0
```

3c. 新增方法（放在 `maybeRefreshPlatformCache` 之后）：

```typescript
  /**
   * 帧池新槽探测（2026-09-21 spec）：行情刷新链尾部低频探测后端最新帧，
   * 发现新 slotTime 即以帧池重建列表。探测失败静默跳过——不打扰实时行情主链，
   * 下次再探；全量路径的降级已在 mergeData 内如实打标。
   */
  private async maybeRefreshFramePool(): Promise<void> {
    if (LIST_POOL_SOURCE_MODE !== 'frame-pool') return
    if (this.framePoolProbeRunning) return
    const now = Date.now()
    if (now - this.lastFramePoolProbeAt < FRAME_POOL_PROBE_INTERVAL_MS) return
    this.lastFramePoolProbeAt = now
    this.framePoolProbeRunning = true
    try {
      const result = await fetchLatestFramePool()
      if (!result.pool) return
      const current = dataLayer.getListPoolProvenance()
      if (
        current?.source === 'frame-pool' &&
        current.slotTime === result.pool.slotTime &&
        current.tradingDate === result.pool.tradingDate
      ) {
        return
      }
      debugLog('[DataLoader] 发现新帧槽，重建列表池', result.pool.slotTime)
      await this.loadPlatformAndMerge(false, { allowWhileLoading: true })
    } catch (error) {
      console.warn('[DataLoader] 帧池探测失败，跳过本轮:', error)
    } finally {
      this.framePoolProbeRunning = false
    }
  }
```

3d. `runQuoteRefresh` 末尾（line 679 `await this.maybeRefreshPlatformCache()` 之后）：

```typescript
    await this.maybeRefreshFramePool()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/DataLoaderFacade.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/services/dataLoader/DataLoaderFacade.ts src/services/dataLoader/__tests__/DataLoaderFacade.test.ts
git commit -m "feat(dataLoader): 帧池新槽探测——行情刷新链尾部 1min 低频跟随最新 half_hour 帧"
```

---

### Task 5: DragonBreathPanel 对账注脚语义更新

**Files:**
- Modify: `src/components/panels/DragonBreathPanel.vue`（`hotListPoolGapNote` computed 约 line 978-998 + `marketListPoolCount` 订阅处约 line 1656-1664）
- Test: `src/components/panels/__tests__/DragonBreathPanel.test.ts`

**⚠️ 用户未提交改动警告**：这两个文件有用户未提交修改。动手前必须 Read 当前内容，只做下述最小增量编辑；用户的既有行一行不动。

**Interfaces:**
- Consumes: Task 1 `dataLayer.getListPoolProvenance()`；面板现有 `hotListToday`、`hotListSentimentSlotTime`、`marketListPoolCount`。
- Produces: 注脚按 provenance 语义显示（一致时不显示差异；降级/启动缓存/槽位滞后如实透出）。

- [ ] **Step 1: 阅读现有测试断言与面板源码**

Read 两个文件全文，确认：
1. 现有源码断言测试引用了哪些精确字符串（已知 `const hotListPoolGapNote = computed(() => {` 必须保留原样）。
2. `hotListSentimentSlotTime` computed 的当前实现。

- [ ] **Step 2: 写失败测试**

在 DragonBreathPanel.test.ts 现有 hotListPoolGapNote 相关 describe 内追加/改造断言（保留用户既有断言不删；新增源码断言遵循该文件既有的 `expect(source).toContain(...)` 模式）：

```typescript
  it('hotListPoolGapNote 按 provenance 语义透出（帧池一致不提示、降级提示回退、滞后提示槽位）', () => {
    const source = readComponentSource()
    // provenance 读取接入（订阅 + computed 依赖）
    expect(source).toContain('dataLayer.getListPoolProvenance()')
    // 降级提示：热榜合并池回退必须可见
    expect(source).toContain("'hotlist-merged'")
    expect(source).toContain('回退热榜合并池')
    // 槽位滞后提示
    expect(source).toContain('槽位暂不同步')
    // 一致时不产生两池差异文案（旧文案关键词必须消失）
    expect(source).not.toContain('两池进出榜时点不同')
  })
```

（`readComponentSource` 为该测试文件现有的源码读取 helper 名——先 Read 测试文件确认实际 helper 名，若不存在则按文件现有模式实现同功能。）

- [ ] **Step 3: 运行测试确认失败**

Run: `pnpm exec vitest run src/components/panels/__tests__/DragonBreathPanel.test.ts`
Expected: FAIL（新断言未满足；确认用户既有断言仍 PASS）

- [ ] **Step 4: 实现面板改动**

4a. script 区适当位置（`marketListPoolCount` ref 声明附近）加本地 ref：

```typescript
// 列表池 provenance（2026-09-21 池源替换）：dataLayer 状态非 Vue 响应式，
// 跟随 merged.stocks 订阅同步到本地 ref 供 computed 依赖
const listPoolProvenance = ref<ListPoolProvenance | null>(dataLayer.getListPoolProvenance())
```

类型 import：`import type { ListPoolProvenance } from '@/types'`（并入现有 `@/types` import）。

4b. `onMounted` 中两处 `marketListPoolCount.value = ...`（订阅回调内与初始行）各补一行：

```typescript
    listPoolProvenance.value = dataLayer.getListPoolProvenance()
```

4c. `hotListPoolGapNote` computed 改写（**保留首行 `const hotListPoolGapNote = computed(() => {`**；其上方 line 978-981 的旧注释块一并改写为新语义说明——旧注释含「两池进出榜时点不同」字样，测试断言 `not.toContain` 会连注释一起扫，必须整段替换不保留）：

```typescript
const hotListPoolGapNote = computed(() => {
  const provenance = listPoolProvenance.value
  const listPool = marketListPoolCount.value
  const snapshotPool = hotListToday.value?.topN || 0
  if (!listPool) return ''
  // 降级：帧池不可用回退热榜合并池，与快照池口径不同，必须如实透出
  if (!provenance || provenance.source === 'hotlist-merged') {
    const reason = provenance?.degradeReason ? `（${provenance.degradeReason}）` : ''
    return `后端帧池暂不可用${reason}，行情列表已回退热榜合并池 ${listPool} 只，各格计数只统计快照池`
  }
  // 启动缓存快路径：后台刷新随即对齐帧池，短暂透出
  if (provenance.source === 'startup-bundle') {
    return `行情列表暂为启动缓存池 ${listPool} 只，正在对齐快照帧池`
  }
  // 槽位滞后：列表帧槽落后于情绪区块最新槽
  const sentimentSlot = hotListSentimentSlotTime.value
  if (
    snapshotPool &&
    provenance.slotTime &&
    sentimentSlot &&
    provenance.slotTime !== sentimentSlot
  ) {
    return `行情列表为 ${provenance.slotTime} 帧池 ${listPool} 只，情绪区块为 ${sentimentSlot} 槽，槽位暂不同步`
  }
  // 同槽理论上一致；若仍不等（如分析文档滞后），保留最小差异提示
  if (snapshotPool && snapshotPool !== listPool) {
    return `快照池 ${snapshotPool} 只 ≠ 行情列表 ${listPool} 只（列表帧槽 ${provenance.slotTime || '--'}），各格计数只统计快照池`
  }
  return ''
})
```

注意：`hotListStatusSourceNote`（line 991-998）引用 `hotListPoolGapNote.value` 的拼接逻辑不动。

- [ ] **Step 5: 运行测试确认通过**

Run: `pnpm exec vitest run src/components/panels/__tests__/DragonBreathPanel.test.ts`
Expected: PASS（新增断言 + 用户既有断言）

- [ ] **Step 6: 类型检查**

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 无错误

- [ ] **Step 7: Commit**

```bash
git add src/components/panels/DragonBreathPanel.vue src/components/panels/__tests__/DragonBreathPanel.test.ts
git commit -m "feat(panels): 龙息面板对账注脚按列表池 provenance 语义透出"
```

---

### Task 6: 全量验证、实测核对与文档回填

**Files:**
- Modify: `docs/superpowers/specs/2026-09-21-frontend-pool-frame-alignment-design.md`（状态行回填实施状态）
- Modify: `docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md`（§3 非目标「前端零改动」处补一行交叉引用：2026-09-21 池源替换 spec 已取代该非目标）

**Interfaces:**
- Consumes: Task 1-5 全部完成。
- Produces: 验证结论与文档口径同步。

- [ ] **Step 1: 全量单元测试**

Run: `pnpm test`
Expected: PASS，无回归

- [ ] **Step 2: RankTrend golden 回归**

Run: `pnpm test:ranktrend && pnpm typecheck:ranktrend`
Expected: PASS（信号计算未改动，golden 无漂移）

- [ ] **Step 3: 类型检查**

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 无错误

- [ ] **Step 4: 实测核对（需本地服务在线，条件不满足则记录为待办）**

前置：QuantBoard 后端 8000 在线且当日有 half_hour 帧（非交易日可显式传上一交易日验证读取链）。
1. `pnpm dev` 打开 `http://localhost:5173`，等待启动后台刷新完成。
2. 浏览器控制台验证 provenance：
   ```js
   // dataLayer 未挂 window，经面板效果验证；直接验证经网络面板确认
   // /api/snapshots/frames + /api/snapshots/stock-rows 两次请求发出且 200
   ```
3. 对账：龙息监测 → 热榜情绪「全池状态结构」的快照池只数 vs 行情列表行数一致（同槽），注脚无两池差异文案。
4. 降级演练：停掉 8000 后触发列表刷新 → 注脚出现「已回退热榜合并池」，列表仍有数据。
5. 盘后重载：列表 codes 与收盘帧 stock-rows codes 完全一致（`GET /api/snapshots/stock-rows?dataset_id=dragonboard_live&snapshot_type=half_hour&trading_date=<今日>&slot_time=15:00` 导出比对）。

- [ ] **Step 5: 文档回填并提交**

spec 状态行（line 3 `> 状态：` ）追加：`；实施完成（2026-09-21，实施计划 docs/superpowers/plans/2026-09-21-frontend-pool-frame-alignment.md）`（若实测留待办则写明未覆盖项）。

```bash
git add docs/superpowers/specs/2026-09-21-frontend-pool-frame-alignment-design.md docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md
git commit -m "docs(specs): 前端列表池帧池对齐实施状态回填 + 2026-09-19 spec 非目标交叉引用"
```
