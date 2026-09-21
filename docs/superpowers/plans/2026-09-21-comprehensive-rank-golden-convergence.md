# 五维综合评分口径唯一化（前端全面消费后端 golden）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除前端五维综合评分/均榜本地计算，列表 compScore/compRank/rank/avgRankNum 一律消费后端快照行 golden 字段；降级行无排名、如实缺省（spec：`docs/superpowers/specs/2026-09-21-comprehensive-rank-golden-convergence-design.md`，用户已确认）。

**Architecture:** 单一翻转点 `framePoolSource.buildFrameSeedStock` 从「排名字段占位」改为「透传 golden」；`StockMergeCoordinator` 删除 `rankMergedStocks` 调用、只做确定性排序；引擎与四个常量整体删除；`BusinessRules` 补一处 NaN 防御。后端零改动。

**Tech Stack:** Vue3 + TypeScript + Vitest（根项目 `src/**`）；验证命令 `pnpm test` / `pnpm test:ranktrend` / `pnpm typecheck:ranktrend` / `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。

**执行约束（每个任务都适用）：**

- 本任务在主工作区 `D:\dragon-board` 直接实施（改动文件与用户未提交文件零交集）；**提交只允许 `git add <显式路径>`**，用户未提交文件不得触碰：`src/components/common/DataTable.vue`、`src/components/common/__tests__/DataTable.test.ts`、`docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md`、`quant-board/backend/api/ranktrend_routes.py`、`quant-board/tests/test_ranktrend_analyze_api.py`、`quant-board/docs/snapshot-collector/2026-09-20-pool-autonomous-source-implementation-plan.md`。
- 全量 `pnpm test` 前先跑一次 `pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts` 记录**基线状态**（该文件属用户未提交改动）；若基线红，最终验证结论以「相对基线无新增失败」口径如实说明。
- 删除文件只允许逐个明确路径 `git rm <path>`，禁止批量删除；禁 `git reset --hard` / `git checkout -- <path>`。
- 每个任务结束 `git log --oneline -1` 确认提交只含本任务文件。

---

### Task 1: 类型契约补齐（SnapshotStockRow + MergedStock）

**Files:**
- Modify: `src/services/snapshot/types.ts`（`SnapshotStockRow`，L77 `compRank` 附近）
- Modify: `src/types/data-layer.ts`（`MergedStock`，L159 `compRank` 附近）

后端行实际携带 `compScore/fundPenetration/qualityFlags/missingFields`（`comprehensive_rank.py:98-104`、`providers.py:1044`），但 TS 接口未声明；MergedStock 缺 `rank/qualityFlags/missingFields` 声明（引擎时代靠动态赋值）。先补类型，后续任务的透传代码才能通过编译。

- [ ] **Step 1: SnapshotStockRow 增加可选字段**

在 `src/services/snapshot/types.ts` 的 `SnapshotStockRow` 中 `compRank: number`（L77）之后插入：

```ts
  compScore?: number | null
  fundPenetration?: number | null
  qualityFlags?: string[]
  missingFields?: string[]
```

- [ ] **Step 2: MergedStock 增加 rank 与质量标记字段**

在 `src/types/data-layer.ts` 的 `MergedStock` 中 `compRank?: number`（L159）、`compScore?: number`（L160）之后插入：

```ts
  /** 综合排名（语义 := compRank，compScore 降序 + code 稳定序；golden 来自后端快照行） */
  rank?: number
  qualityFlags?: string[]
  missingFields?: string[]
```

- [ ] **Step 3: 类型检查通过**

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 退出码 0，无输出（纯类型新增，无行为变化）。

- [ ] **Step 4: Commit**

```bash
git add src/services/snapshot/types.ts src/types/data-layer.ts
git commit -m "feat(types): SnapshotStockRow/MergedStock 补齐 golden 排名与质量标记字段契约"
```

---

### Task 2: buildFrameSeedStock 透传 golden 排名字段（RED→GREEN）

**Files:**
- Modify: `src/services/dataLoader/__tests__/framePoolSource.test.ts`（L117-141 `buildFrameSeedStock` describe）
- Modify: `src/services/dataLoader/framePoolSource.ts`（L78-99 `buildFrameSeedStock`）

- [ ] **Step 1: 改写既有用例 + 新增 golden 透传用例（先红）**

将 `framePoolSource.test.ts` 中 `describe('buildFrameSeedStock', ...)` 整块替换为：

```ts
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
    // 平台 rank 字段不由种子透传：合并链用实时热榜数据覆盖（展示字段，非计算输入）
    expect(seed.emRank).toBe(DEFAULT_RANK)
  })

  it('golden 排名字段逐位透传：compRank/compScore/avgRankNum/platforms/质量标记，rank := compRank', () => {
    const seed = buildFrameSeedStock(
      makeRow({
        avgRankNum: 37.5,
        avgRank: '37.5',
        compScore: 88.1234,
        compRank: 3,
        platforms: 5,
        fundPenetration: 1.23,
        qualityFlags: [],
        missingFields: [],
      }),
    )

    expect(seed.avgRankNum).toBe(37.5)
    expect(seed.avgRank).toBe('37.5')
    expect(seed.compScore).toBe(88.1234)
    expect(seed.compRank).toBe(3)
    expect(seed.rank).toBe(3)
    expect(seed.platforms).toBe(5)
    expect(seed.fundPenetration).toBe(1.23)
    expect(seed.qualityFlags).toEqual([])
    expect(seed.missingFields).toEqual([])
  })

  it('avgRank 缺失时由 golden avgRankNum 格式化派生（纯展示格式化，非计算）', () => {
    const seed = buildFrameSeedStock(makeRow({ avgRankNum: 42, avgRank: undefined }))

    expect(seed.avgRankNum).toBe(42)
    expect(seed.avgRank).toBe('42.0')
  })

  it('行无 golden 字段时如实缺省：compRank undefined、compScore 保持占位 0，不伪造', () => {
    const seed = buildFrameSeedStock(
      makeRow({
        avgRankNum: undefined,
        avgRank: undefined,
        compScore: undefined,
        compRank: undefined,
        fundPenetration: undefined,
      }),
    )

    expect(seed.avgRankNum).toBe(DEFAULT_RANK)
    expect(seed.compRank).toBeUndefined()
    expect(seed.rank).toBeUndefined()
    expect(seed.compScore).toBe(0)
    expect(seed.fundPenetration).toBeUndefined()
  })

  it('缺字段/非法值回退默认：NaN 价格、空名称不产生脏数据', () => {
    const seed = buildFrameSeedStock(makeRow({ price: undefined, name: '-', volume: Number.NaN }))

    expect(seed.price).toBe(0)
    expect(seed.volume).toBe(0)
    expect(seed.name).toBe('')
    expect(seed.platformName).toBe('')
  })
})
```

确认文件顶部 import 已含 `DEFAULT_RANK`（当前 `framePoolSource.test.ts` 已从 `@/types/config` 或 `../framePoolSource` 链路引用过 DEFAULT_RANK；若未导入则在 import 区加 `import { DEFAULT_RANK } from '@/types/config'`）。

- [ ] **Step 2: 运行确认 RED**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/framePoolSource.test.ts`
Expected: FAIL——「golden 排名字段逐位透传」「avgRank 派生」「如实缺省」三个新用例失败（现实现排名字段占位）；「帧行字段映射」用例因 `platforms` 断言改造而失败。其余 describe（fetchLatestFramePool / filterPlatformDataToCodes）保持绿。

- [ ] **Step 3: 实现 golden 透传**

将 `framePoolSource.ts` L78-99 的注释与 `buildFrameSeedStock` 整体替换为：

```ts
/**
 * 帧行 → 种子行：名称与快照时点行情为兜底值（实时行情到达后被覆盖）；
 * 排名字段直接透传后端 golden（2026-09-21 口径唯一化裁决 A，
 * spec: docs/superpowers/specs/2026-09-21-comprehensive-rank-golden-convergence-design.md），
 * 前端零排名计算；前端 rank 语义 := 后端 compRank（compScore 降序 + code 稳定序）。
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

  // golden 排名字段逐位透传，缺失不伪造（保持 createEmptyMergedStock 占位语义）
  const avgRankNum = toFiniteNumber(row?.avgRankNum)
  if (avgRankNum !== null) {
    stock.avgRankNum = avgRankNum
    stock.avgRank = row?.avgRank ?? avgRankNum.toFixed(1)
  }
  if (toFiniteNumber(row?.platforms) !== null) stock.platforms = row.platforms
  const compRank = toFiniteNumber(row?.compRank)
  if (compRank !== null) {
    stock.compRank = compRank
    stock.rank = compRank
  }
  const compScore = toFiniteNumber(row?.compScore)
  if (compScore !== null) stock.compScore = compScore
  const fundPenetration = toFiniteNumber(row?.fundPenetration)
  if (fundPenetration !== null) stock.fundPenetration = fundPenetration
  if (Array.isArray(row?.qualityFlags)) stock.qualityFlags = [...row.qualityFlags]
  if (Array.isArray(row?.missingFields)) stock.missingFields = [...row.missingFields]
  return stock
}
```

- [ ] **Step 4: 运行确认 GREEN**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/framePoolSource.test.ts`
Expected: 全部 PASS（含既有 fetchLatestFramePool / filterPlatformDataToCodes 用例）。

- [ ] **Step 5: Commit**

```bash
git add src/services/dataLoader/framePoolSource.ts src/services/dataLoader/__tests__/framePoolSource.test.ts
git commit -m "feat(framePool): 帧池种子行透传后端 golden 排名字段（compRank/compScore/avgRankNum），rank := compRank"
```

---

### Task 3: StockMergeCoordinator 收敛——删除本地排名计算（RED→GREEN）

**Files:**
- Modify: `src/services/dataLoader/__tests__/StockMergeCoordinator.test.ts`
- Modify: `src/services/dataLoader/StockMergeCoordinator.ts`（L1-9 import 区、L80-89 merge）

- [ ] **Step 1: 新增收敛行为用例（先红）**

在 `StockMergeCoordinator.test.ts` 的 `describe` 块末尾（L187 `})` 之前）追加：

```ts
  it('口径唯一化：golden compRank 不被本地重算覆盖（2026-09-21 裁决 A）', async () => {
    const stocks = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '000001', name: '样本股', rank: 1 }],
      },
      latestQuotes: new Map(),
      existingMap: new Map([
        ['000001', { code: '000001', name: '样本股', compRank: 7, compScore: 55.5, avgRankNum: 37.5, rank: 7 }],
      ]),
    })

    expect(stocks[0].compRank).toBe(7)
    expect(stocks[0].compScore).toBe(55.5)
    expect(stocks[0].avgRankNum).toBe(37.5)
    expect(stocks[0].rank).toBe(7)
  })

  it('列表排序按 golden compRank 降序稳定（缺省垫底，并列按 code）', async () => {
    const stocks = await new StockMergeCoordinator().merge({
      platformData: {},
      latestQuotes: new Map(),
      existingMap: new Map([
        ['300002', { code: '300002', name: '丙', compRank: undefined }],
        ['000001', { code: '000001', name: '乙', compRank: 3 }],
        ['600001', { code: '600001', name: '甲', compRank: 1 }],
      ]),
    })

    expect(stocks.map((s: { code: string }) => s.code)).toEqual(['600001', '000001', '300002'])
  })

  it('平台 rank 字段仍实时合并（展示字段），降级行无排名不伪造', async () => {
    const stocks = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '000001', name: '样本股', rank: 2 }],
      },
      latestQuotes: new Map(),
      existingMap: new Map([['000001', { code: '000001', name: '样本股' }]]),
    })

    expect(stocks[0].emRank).toBe(2)
    expect(stocks[0].compRank).toBeUndefined()
    expect(stocks[0].compScore).toBe(0)
  })
```

- [ ] **Step 2: 运行确认 RED**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/StockMergeCoordinator.test.ts`
Expected: FAIL——「golden compRank 不被本地重算覆盖」（现实现重算出 compRank=1）与「排序」用例失败；既有量比/资金流用例保持绿。

- [ ] **Step 3: 实现收敛**

3a. 删除 L5 的引擎 import：

```ts
// 删除这一行：
import { getRankField, rankMergedStocks } from './ComprehensiveRankEngine'
```

3b. 在 import 区之后（`isValidStockName` 之前）加入模块私有映射：

```ts
// 8 平台 rank 字段映射（原 ComprehensiveRankEngine 导出，2026-09-21 口径唯一化后仅剩
// 展示合并这一处消费方，收编为模块私有）。平台 rank 是原始平台数据展示字段，非计算输入。
const RANK_FIELD_MAP: Record<string, string> = {
  eastmoney: 'emRank',
  ths: 'thsRank',
  kpl: 'kplRank',
  tdx: 'tdxRank',
  xueqiu: 'xqRank',
  cls: 'clsRank',
  tgb: 'tgbRank',
  dzh: 'dzhRank',
}

function getRankField(platform: string): string | null {
  return RANK_FIELD_MAP[platform] || null
}
```

3c. 将 `merge` 方法（L80-89）整体替换为：

```ts
export class StockMergeCoordinator {
  async merge(input: StockMergeCoordinatorInput): Promise<any[]> {
    const stockMap = await this.buildStockMap(input)
    this.applyStockNameFallbacks(stockMap)
    // 2026-09-21 口径唯一化（spec: 2026-09-21-comprehensive-rank-golden-convergence-design.md）：
    // 删除本地综合排名/均榜计算（2026-08-24 回滚口径作废），compScore/compRank/avgRankNum
    // 一律消费后端 golden（帧池种子行透传，framePoolSource.buildFrameSeedStock）；
    // 降级链行无排名，如实缺省并由 poolSource provenance 打标（fail-visible，不伪造）。
    const merged = Array.from(stockMap.values())
    return merged.sort(
      (a, b) =>
        (a.compRank ?? DEFAULT_RANK) - (b.compRank ?? DEFAULT_RANK) ||
        String(a.code).localeCompare(String(b.code)),
    )
  }
```

- [ ] **Step 4: 运行确认 GREEN**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/StockMergeCoordinator.test.ts`
Expected: 全部 PASS（新增 3 用例 + 既有 5 用例）。注意此时 `ComprehensiveRankEngine.ts` 已无生产消费方（仅测试引用），Task 5 再删除，本任务提交保持可独立回退。

- [ ] **Step 5: Commit**

```bash
git add src/services/dataLoader/StockMergeCoordinator.ts src/services/dataLoader/__tests__/StockMergeCoordinator.test.ts
git commit -m "feat(merge): 列表排名收敛为消费后端 golden——删除 rankMergedStocks 本地重算，仅保留确定性排序"
```

---

### Task 4: BusinessRules compRank NaN 防御（RED→GREEN）

**Files:**
- Create: `src/services/dragon/__tests__/BusinessRules.test.ts`
- Modify: `src/services/dragon/BusinessRules.ts`（L149、import 区）

降级行 `compRank` 为 undefined 时 `100 - stock.compRank * 5` 产生 NaN（被 `>= 80` 布尔比较吞成 false，属静默污染）；改显式 `?? DEFAULT_RANK` 回退。

- [ ] **Step 1: 写失败测试**

创建 `src/services/dragon/__tests__/BusinessRules.test.ts`：

```ts
import { describe, expect, it } from 'vitest'

import { DEFAULT_RANK } from '@/types/config'
import { DragonBusinessRules } from '../BusinessRules'
import type { MarketContext, SectorContext, StockContext } from '../types'

function makeStock(overrides: Partial<StockContext> = {}): StockContext {
  return {
    code: '600001',
    compRank: 1,
    turnoverRank: 1,
    limitDays: 1,
    turnoverRate: 10,
    change: 6,
    totalMV: 200e8,
    ma5: 11,
    ma10: 10,
    ma20: 9,
    volumeRatio: 2,
    zlje: 5e9,
    attributes: [],
    ...overrides,
  } as StockContext
}

const market: MarketContext = { marketPhase: '高潮期' } as MarketContext
const sector: SectorContext = {
  sectorHeat: 6000,
  sectorZtCount: 5,
  firstLimitCode: '600001',
  maxFengdanCode: '600001',
  ztIncrease: 2,
  followerCodes: ['000002', '000003'],
} as SectorContext

describe('DragonBusinessRules.calculateTotalLeaderScore NaN 防御', () => {
  it('compRank 存在时得分路径正常（isTotalLeader 黑盒）', () => {
    expect(DragonBusinessRules.isTotalLeader(makeStock(), market, sector)).toBe(true)
  })

  it('compRank 缺失按 DEFAULT_RANK 垫底计分，不产生 NaN（白盒锁防御）', () => {
    const score = (DragonBusinessRules as any).calculateTotalLeaderScore(
      makeStock({ compRank: undefined }),
      market,
      sector,
    )
    expect(Number.isNaN(score)).toBe(false)
    // rankScore = max(0, 100 - 999*5) = 0；heat 25 + money 25 + 情绪 16 = 66
    expect(score).toBeCloseTo(66, 5)
  })

  it('DEFAULT_RANK 常量语义为 999（占位缺省，缺测试则防御无意义）', () => {
    expect(DEFAULT_RANK).toBe(999)
  })
})
```

若 `makeStock` 缺 `StockContext` 必填字段导致编译错，按 `src/services/dragon/types.ts` 的 `StockContext` 定义补齐 fixture 字段（值不影响断言路径）。

- [ ] **Step 2: 运行确认 RED**

Run: `pnpm exec vitest run src/services/dragon/__tests__/BusinessRules.test.ts`
Expected: FAIL——「compRank 缺失按 DEFAULT_RANK 垫底」用例 `Number.isNaN(score)` 为 true；黑盒用例可能 PASS。

- [ ] **Step 3: 实现防御**

`src/services/dragon/BusinessRules.ts` L149 改为：

```ts
    // 排名因子 (30%)；compRank 缺失（降级行无 golden 排名）按 DEFAULT_RANK 垫底，不产生 NaN
    const rankScore = Math.max(0, 100 - (stock.compRank ?? DEFAULT_RANK) * 5)
```

文件头部加 import：

```ts
import { DEFAULT_RANK } from '@/types/config'
```

- [ ] **Step 4: 运行确认 GREEN**

Run: `pnpm exec vitest run src/services/dragon/__tests__/BusinessRules.test.ts`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/services/dragon/BusinessRules.ts src/services/dragon/__tests__/BusinessRules.test.ts
git commit -m "fix(dragon): compRank 缺失按 DEFAULT_RANK 垫底计分——堵降级行 NaN 静默污染"
```

---

### Task 5: 删除引擎与常量 + 注记同步

**Files:**
- Delete: `src/services/dataLoader/ComprehensiveRankEngine.ts`
- Delete: `src/services/dataLoader/__tests__/ComprehensiveRankEngine.test.ts`
- Delete: `src/types/__tests__/config.test.ts`（整文件仅剩 golden 权重锁一条用例，锁的对象已删；防漂移锁在后端 `quant-board/tests/test_comprehensive_rank.py`）
- Modify: `src/types/config.ts`（L436-447）
- Modify: `src/types/index.ts`（L64-80 re-export）
- Modify: `src/services/dataLoader/RankTrendSignalService.ts`（L222-224 注记）
- Modify: `src/services/dataLoader/DataLoaderFacade.ts`（L961 注释）
- Modify: `src/services/dataLoader/framePoolSource.ts`（L101 注释）

- [ ] **Step 1: 逐文件删除（禁批量，逐条执行）**

```bash
git rm src/services/dataLoader/ComprehensiveRankEngine.ts
git rm src/services/dataLoader/__tests__/ComprehensiveRankEngine.test.ts
git rm src/types/__tests__/config.test.ts
```

- [ ] **Step 2: 删除常量定义**

`src/types/config.ts` 中删除以下四个导出（`DEFAULT_RANK` 保留）：

```ts
// —— 删除开始 ——
export const COMPREHENSIVE_WEIGHTS = {
  HOT_RANK: 0.45,
  MONEY_RATIO: 0.25,
  FUND_PENETRATION: 0.1,
  TURNOVER_RATE: 0.12,
  VOLUME: 0.08,
} as const

export const PENALTY_SCORE = 100
export const DEFAULT_RANK = 999
export const OPTIMAL_TURNOVER = 15
export const TURNOVER_SIGMA = 10
// —— 删除结束 ——
```

替换为：

```ts
// 综合排名五维口径 golden 在后端（backend/analysis/ranktrend/ranking/comprehensive_rank.py，
// 2026-09-21 口径唯一化裁决 A）；前端仅保留缺省占位语义。
export const DEFAULT_RANK = 999
```

- [ ] **Step 3: 同步 types/index.ts re-export**

`src/types/index.ts` L64-80 的 re-export 块中删除 `COMPREHENSIVE_WEIGHTS`、`PENALTY_SCORE`、`OPTIMAL_TURNOVER`、`TURNOVER_SIGMA` 四行，`DEFAULT_RANK` 保留；`// 权重相关` 注释改为 `// 平台权重与缺省占位`。

- [ ] **Step 4: 注记同步（三处）**

`RankTrendSignalService.ts` L222-224 注记替换为：

```ts
      // 2026-09-21 口径唯一化：compRank/avgRankNum 消费后端 golden（帧池种子透传），
      // analyze 不注入/回填，此处不覆盖种子值。
```

`DataLoaderFacade.ts` L961 注释替换为：

```ts
    // 3. 构建股票数据（综合排名消费后端 golden，帧池种子行透传；2026-09-21 口径唯一化）
```

`framePoolSource.ts` L101 函数注释中「（calculatePlatformTotals 按行数计 0）」改为「（platformTotals 由后端帧内计算）」。

- [ ] **Step 5: 全量单测 + 类型检查，对齐残留断言**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/ src/services/snapshot/ src/services/hotness/ 2>&1 | tail -20`
Expected: 除 `DataTable.test.ts`（用户文件，以基线为准）外全绿。若有测试因「引擎重算出的 compRank/avgRankNum」断言失败（候选：`DataLoaderFacade.test.ts` L211-213/L664-667、`RealtimeQuoteCoordinator.test.ts`——已核实它们只自备字段值，预计不失败），逐个改为自备 golden 值口径；不得为过测试改生产语义。

Run: `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
Expected: 退出码 0（引擎/常量已无任何 import 方——Task 3 已解除唯一生产引用，config.test.ts 已删）。

- [ ] **Step 6: Commit**

```bash
git add src/types/config.ts src/types/index.ts src/services/dataLoader/RankTrendSignalService.ts src/services/dataLoader/DataLoaderFacade.ts src/services/dataLoader/framePoolSource.ts
git commit -m "refactor(ranking): 删除前端五维综合评分引擎与常量——口径唯一化收尾（golden 在后端）"
```

（三个 `git rm` 已在 Step 1 暂存，随本提交一并入库；`git status --short` 确认无用户未提交文件被暂存。）

---

### Task 6: 全量验证门禁

- [ ] **Step 1: 基线记录**

Run: `pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts 2>&1 | tail -5`
记录结果（用户未提交文件的当前状态，作为最终对比基线）。

- [ ] **Step 2: 全量验证**

```bash
pnpm test 2>&1 | tail -15
pnpm test:ranktrend 2>&1 | tail -8
pnpm typecheck:ranktrend 2>&1 | tail -5
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: `pnpm test` 全绿（相对 Step 1 基线无新增失败）；`test:ranktrend` 全绿；两个 typecheck 退出码 0。任何失败按 systematic-debugging 先定位根因再修，禁止为绿改生产语义。

- [ ] **Step 3: 无独立提交**（本任务只验证；修复若发生，按所属文件归入对应任务补充提交）

---

### Task 7: 文档同步

**Files:**
- Modify: `docs/single-source-of-truth-architecture.md`（§3 表第 6 行、§5 P1 段）
- Modify: `docs/superpowers/specs/2026-09-21-comprehensive-rank-golden-convergence-design.md`（状态行）

- [ ] **Step 1: 盘点表更新**

§3 表第 6 行「状态」改为：`✅ 已收敛（2026-09-21 用户裁决方向 A）`，「权威侧」改为 `后端`，「收敛路径」填 `2026-09-21 口径唯一化 spec`。

§5 P1 段末尾追加一行：

```markdown
- **裁决与落地（2026-09-21）**：用户裁决方向 A（口径唯一）；前端删除 ComprehensiveRankEngine 本地计算，帧池种子行透传后端 golden，降级行无排名如实缺省。代价（排名帧内冻结 ≤30min）已由用户接受。
```

- [ ] **Step 2: spec 状态行更新**

spec 头部状态行追加：`；实施完成（实施计划 docs/superpowers/plans/2026-09-21-comprehensive-rank-golden-convergence.md，全量验证见提交记录）`。

- [ ] **Step 3: Commit**

```bash
git add docs/single-source-of-truth-architecture.md docs/superpowers/specs/2026-09-21-comprehensive-rank-golden-convergence-design.md
git commit -m "docs(single-source): 盘点表第 6 行五维综合评分标记已收敛——2026-09-21 用户裁决方向 A"
```

---

### Task 8: 浏览器真实验收（playwright-cli，AGENTS §6.3 强制）

前置：本机常驻服务 5173（前端）/ 8000（QuantBoard 后端）在运行（挂了先告知用户再重启）。操作流程遵循 `skills/playwright-cli/SKILL.md`；注意已知坑：Git Bash 下 run-code 多行 JS 报 SyntaxError——用单行脚本或解析 snapshot yml 提取值。

- [ ] **Step 1: 打开 `http://localhost:5173`，等待列表渲染完成**（provenance 注脚显示 `frame-pool@<槽位>`）。
- [ ] **Step 2: 提取列表前 10 行的 code/compRank/compScore/avgRank**（snapshot yml 或单行 JS），同时 curl 后端同帧数据对账：

```bash
# 参数名以 src/services/snapshot/backendRead.ts 实际请求为准；先读该文件确认 query 拼法
curl -s "http://127.0.0.1:8000/api/snapshots/frames?type=half_hour&limit=1" 
curl -s "http://127.0.0.1:8000/api/snapshots/stock-rows?type=half_hour&trading_date=<当日>&slot_time=<槽>" | head -c 2000
```

Expected: 前端列表 compRank 与后端同槽 stock-rows 的 compRank **逐位一致**；`rank` 值等于 `compRank`。
- [ ] **Step 3: 检查控制台无新增错误**（NaN/undefined 渲染告警重点关注排名列与龙头面板）。
- [ ] **Step 4: 截图留证**（列表整页 + 排名列局部），确认排名列、龙头面板、个股热度渲染正常。
- [ ] **Step 5: 降级语义静态核对**（不启停用户生产服务）：以 Task 3/Task 2 的单测作为降级行为证据；真实停 8000 演练仅在有用户授权时进行。
- [ ] **Step 6: 无提交**；验收结论（含截图路径与对账数值）写入最终交付报告。

---

### Task 9: 首交易日人工对账（交付后观察项，AGENTS §11 必查清单）

- [ ] 交易日盘中（或盘后）人工核对：前端列表 compRank 与 `GET /api/snapshots/stock-rows` 同槽值逐位一致；降级注脚出现时如实透出「降级期间无综合排名」。
- [ ] 结果（一致/差异明细）回填到交付报告；发现不一致按 systematic-debugging 立项排查，不许静默。

---

## Self-Review 记录（计划完成后已核对）

1. **Spec 覆盖**：§3 改造点 1-4 ↔ Task 1/2/3；§4 降级语义与 NaN 加固 ↔ Task 2 用例 4 + Task 3 用例 3 + Task 4；§5 删除清单 ↔ Task 5；§6 测试 ↔ Task 2-4 + Task 6；§7 文档与首日对账 ↔ Task 7/8/9。无缺口。
2. **占位符扫描**：Task 8 Step 2 的 curl 参数以「读 backendRead.ts 确认」为明确动作而非 TBD；Task 4 fixture 字段按 types.ts 补齐为明确指令。其余步骤均含完整代码/命令。
3. **类型一致性**：`buildFrameSeedStock(row: SnapshotStockRow): MergedStock`、`getRankField`（模块私有）、`rank/qualityFlags/missingFields`（Task 1 定义，Task 2 消费）签名一致；Task 3 排序用 `DEFAULT_RANK`（import 已存在于 StockMergeCoordinator L2）。
