# Trading Pool 实时投影接入+UI补全——实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 DataLayer 热榜实时数据到交易池分析的输入管道，补全 DataTable tooltip 信息分层、候选池"强共振观察"语义和交易池面板展示字段，使交易池在强情绪日能从八平台热榜 200+ 只票中发现共振标的。

**Architecture:** `CandidatePoolPanel.vue` 从 `dataLayer.getStocks()` 读取热榜实时投影，与候选日记 thesis 条目合并后传入 `analyzeTradingPoolCandidate`；DataTable tooltip 通过 `CandidatePoolStatusProjector` 获取分层的综合判断/Jump/共振/交易池动作信息；不改变任何阈值和 AND 门逻辑。

**Tech Stack:** Vue 3 + TypeScript + Vite, Vitest, existing `dataLayer`, `TradingPoolAnalysisService`, `CandidatePoolStatusProjector`, `CandidatePoolPanel.vue`, `DataTable.vue`

**实施状态:** 已完成（2026-06-16）

| Task | 状态 | 备注 |
|------|------|------|
| Task 1: 扩展 TradingPoolInput + types + 合并逻辑 | ✅ | `liveStocks` 可选字段，thesis 优先去重 |
| Task 2: 实时投影管道测试 | ✅ | 4 个新增用例：来源标记、去重、空 rankTrend 回退、混合输入 |
| Task 3: CandidatePoolPanel 接入 DataLayer | ✅ | `dataLayer.getStocks()` → `liveStocks` 传入 |
| Task 4: 强共振观察分类 | ✅ | `isResonanceObserve()` + 7 个边界测试 |
| Task 5: DataTable tooltip 分层 | ✅ | 此前已实现，无需改动 |
| Task 6: 交易池面板字段补全 | ✅ | 此前已实现，无需改动 |
| Task 7: 面板测试 | ✅ | 源码模式断言已更新 |
| Task 8: 验收 | ✅ | 104 文件 / 783 测试通过，类型检查 exit 0 |
| Task 9: 自审清单 | ✅ | 配置统一化延后 |

---

## Guardrails

- 不放宽任何阈值数值。
- 不改 `checkEntryConditions` 6条件、`strongConsensus` 8条件 AND 门。
- 不改 V5/Fusion 候选池严格合同。
- 不改 QuantBoard 回测主链。
- 不引入新依赖。
- DataLayer 覆盖范围是八平台热榜 200+ 只票，不是全市场 5000+ 只票。

## File Map

- Modify: `src/services/candidate/types.ts`
  - 新增 `'live_projection'` 到 `TradingPoolSource` 联合类型
- Modify: `src/services/candidate/TradingPoolAnalysisService.ts`
  - `TradingPoolInput` 新增 `liveStocks` 可选字段；`analyzeTradingPoolCandidate` 内实现 thesis/实时投影去重合并
- Modify: `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`
  - 新增实时投影来源、去重、DataLayer 裸 stock 输入等测试
- Modify: `src/services/candidate/CandidatePoolStatusProjector.ts`
  - 新增强共振观察判定逻辑，为 DataTable 提供分层信息
- Modify: `src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts`
  - 锁定额共振观察分类规则
- Modify: `src/components/panels/CandidatePoolPanel.vue`
  - `tradingPoolEvaluation` computed 新增 `dataLayer.getStocks()` 实时投影输入；补全交易池面板字段
- Modify: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - 锁定 live_projection 来源行渲染
- Modify: `src/components/common/DataTable.vue`
  - `confidence` 列 tooltip 拆分综合判断/Jump/共振/交易池动作四段

---

## Task 1: 扩展交易池输入类型和合并逻辑

**Files:**
- Modify: `src/services/candidate/types.ts`
- Modify: `src/services/candidate/TradingPoolAnalysisService.ts`

- [ ] **Step 1: 新增 `live_projection` 来源类型**

```ts
// types.ts — TradingPoolSource 联合类型新增成员
export type TradingPoolSource =
  | 'candidate_auto_add'
  | 'candidate_watch'
  | 'jump_blocked_resonance'
  | 'live_projection'  // 新增：来自 DataLayer 热榜实时投影
  | 'manual'
  | 'persisted'
  | 'unknown'
```

- [ ] **Step 2: 扩展 `TradingPoolInput` 接口，新增 `liveStocks` 可选字段**

```ts
// TradingPoolAnalysisService.ts
interface TradingPoolInput {
  candidates: TradingPoolCandidateLike[]
  previousRows?: Array<Partial<TradingPoolAnalysisRow> & { code: string }>
  liveStocks?: TradingPoolCandidateLike[]  // 新增：DataLayer 实时热榜投影
}
```

- [ ] **Step 3: 实现 thesis/实时投影去重合并逻辑**

在 `analyzeTradingPoolCandidate` 函数体开头（`previousRows` 构建之后、遍历循环之前）插入：

```ts
export function analyzeTradingPoolCandidate(input: TradingPoolInput): TradingPoolAnalysisResult {
  const previousRows = buildPreviousRowMap(input.previousRows)

  // 去重合并：thesis 候选优先，同名 code 以 thesis 为准
  const thesisCodes = new Set<string>()
  const mergedCandidates: TradingPoolCandidateLike[] = []

  for (const candidate of input.candidates || []) {
    const code = normalizeCode(candidate.code)
    if (!code) continue
    thesisCodes.add(code)
    mergedCandidates.push(candidate)
  }

  if (input.liveStocks) {
    for (const stock of input.liveStocks) {
      const code = normalizeCode(stock.code)
      if (!code || thesisCodes.has(code)) continue  // thesis 优先，跳过重复
      mergedCandidates.push({
        ...stock,
        tradingPoolSource: 'live_projection' as TradingPoolSource,
      })
    }
  }

  const rows: TradingPoolAnalysisRow[] = []
  // ... 后续遍历 mergedCandidates 替代原来的 input.candidates
```

将后续 `for (const candidate of input.candidates || [])` 改为 `for (const candidate of mergedCandidates)`。

- [ ] **Step 4: 实时投影 source 保持优先级**

`resolveTradingPoolSource` 中，实时投影行已在合并时预设 `tradingPoolSource: 'live_projection'`：

```ts
function resolveTradingPoolSource(stock: TradingPoolCandidateLike): TradingPoolSource {
  if (stock.tradingPoolSource === 'manual') return 'manual'
  if (stock.tradingPoolSource === 'persisted') return 'persisted'
  if (stock.tradingPoolSource === 'live_projection') return 'live_projection'  // 新增
  const decision = getEntryDecision(stock)
  if (decision?.accepted) return 'candidate_auto_add'
  if (isJumpBlockedOnly(stock)) return 'jump_blocked_resonance'
  if (decision) return 'candidate_watch'
  return 'unknown'
}
```

- [ ] **Step 5: 实时投影行跳过 candidateEntryDecision 相关判断**

实时投影行没有 `candidateEntryDecision`（它来自 DataLayer，不由候选日记管理）。`isJumpBlockedOnly` 和 `hasNonJumpHardBlock` 对实时投影行应返回 `false`：

```ts
function getEntryDecision(stock: TradingPoolCandidateLike): Record<string, any> | null {
  // 实时投影没有候选日记 entry decision
  if (stock.tradingPoolSource === 'live_projection') return null
  return stock.candidateEntryDecision || stock.entryDecision || null
}
```

- [ ] **Step 6: 类型检查**

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: 无新增类型错误。

---

## Task 2: 锁定实时投影管道测试

**Files:**
- Modify: `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`

- [ ] **Step 1: 实时投影来源标记测试**

```ts
it('marks DataLayer live projection stocks with live_projection source', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [],
    liveStocks: [
      {
        code: '002171',
        name: '楚江新材',
        rankTrend: {
          decision: { final: { signal: 'buy', confidence: 87 } },
          jump: { direction: 'buy', confidence: 82.9 },
          technical: {
            macd: { cross: 'none' },
            signals: {
              direction: { signal: 'buy', confidence: 90 },
              acceleration: { signal: 'buy', confidence: 90 },
              zeroCross: { signal: 'buy', confidence: 90 },
            },
          },
          cycle: { decision: { action: 'allow' } },
        },
      },
    ],
  })

  expect(result.rows).toHaveLength(1)
  expect(result.rows[0].code).toBe('002171')
  expect(result.rows[0].signalSnapshot.source).toBe('live_projection')
})
```

- [ ] **Step 2: 实时投影与 thesis 去重测试（thesis 优先）**

```ts
it('deduplicates live projection when thesis candidate exists for same code', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [
      {
        code: '603738',
        name: '泰晶科技-thesis',
        rankTrend: {
          decision: { final: { signal: 'buy', confidence: 91 } },
          jump: { direction: 'buy', confidence: 87.9 },
          technical: {
            macd: { cross: 'golden' },
            signals: {
              direction: { signal: 'buy', confidence: 88 },
              acceleration: { signal: 'buy', confidence: 90 },
              zeroCross: { signal: 'buy', confidence: 90 },
            },
          },
          cycle: { decision: { action: 'allow' } },
        },
        candidateEntryDecision: {
          accepted: false,
          checks: [{ key: 'jump_confidence', status: 'fail', hardBlock: true }],
        },
      },
    ],
    liveStocks: [
      {
        code: '603738',
        name: '泰晶科技-live',
        rankTrend: {
          decision: { final: { signal: 'buy', confidence: 88 } },
          jump: { direction: 'buy', confidence: 84 },
          technical: {
            macd: { cross: 'none' },
            signals: {
              direction: { signal: 'buy', confidence: 80 },
              acceleration: { signal: 'buy', confidence: 80 },
              zeroCross: { signal: 'buy', confidence: 80 },
            },
          },
          cycle: { decision: { action: 'allow' } },
        },
      },
    ],
  })

  // 只应有一行，且使用 thesis 来源（jump_blocked_resonance，不是 live_projection）
  expect(result.rows).toHaveLength(1)
  expect(result.rows[0].name).toBe('泰晶科技-thesis')
  expect(result.rows[0].signalSnapshot.source).toBe('jump_blocked_resonance')
})
```

- [ ] **Step 3: 实时投影空 rankTrend 回退测试**

```ts
it('handles live projection stock without rankTrend gracefully', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [],
    liveStocks: [
      {
        code: '000001',
        name: '无信号票',
        // 无 rankTrend 字段
      },
    ],
  })

  expect(result.rows).toHaveLength(1)
  expect(result.rows[0].signalSnapshot.dataQuality).toBe('missing')
  // 无信号时应降级为观察中，不进入观察买点
  expect(result.rows[0].status).toBe('观察中')
})
```

- [ ] **Step 4: 实时投影 + thesis 混合输入**

```ts
it('processes mixed thesis and live projection inputs correctly', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [
      {
        code: '002171',
        name: '楚江-thesis',
        rankTrend: {
          decision: { final: { signal: 'buy', confidence: 87 } },
          jump: { direction: 'buy', confidence: 82.9 },
          technical: {
            macd: { cross: 'none' },
            signals: {
              direction: { signal: 'buy', confidence: 90 },
              acceleration: { signal: 'buy', confidence: 90 },
              zeroCross: { signal: 'buy', confidence: 90 },
            },
          },
          cycle: { decision: { action: 'allow' } },
        },
        candidateEntryDecision: {
          accepted: false,
          checks: [{ key: 'jump_confidence', status: 'fail', hardBlock: true }],
        },
      },
    ],
    liveStocks: [
      {
        code: '603738',
        name: '泰晶-live',
        rankTrend: {
          decision: { final: { signal: 'buy', confidence: 91 } },
          jump: { direction: 'buy', confidence: 87.9 },
          technical: {
            macd: { cross: 'golden' },
            signals: {
              direction: { signal: 'buy', confidence: 88 },
              acceleration: { signal: 'buy', confidence: 90 },
              zeroCross: { signal: 'buy', confidence: 90 },
            },
          },
          cycle: { decision: { action: 'allow' } },
        },
      },
    ],
  })

  expect(result.rows).toHaveLength(2)
  const chuJiang = result.rows.find((r) => r.code === '002171')
  const taiJing = result.rows.find((r) => r.code === '603738')
  expect(chuJiang!.signalSnapshot.source).toBe('jump_blocked_resonance')
  expect(taiJing!.signalSnapshot.source).toBe('live_projection')
  expect(taiJing!.status).toBe('准备介入')
})
```

- [ ] **Step 5: 运行测试确认 RED**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot
```

Expected: 新增断言失败（`liveStocks` 参数尚不支持，或合并逻辑尚未实现）。

---

## Task 3: CandidatePoolPanel 接入 DataLayer 实时投影

**Files:**
- Modify: `src/components/panels/CandidatePoolPanel.vue`

- [ ] **Step 1: 在 `tradingPoolEvaluation` 中接入 DataLayer**

在 `<script setup>` 顶部新增 import：

```ts
import { dataLayer } from '@/services/DataLayer'
```

修改 `tradingPoolEvaluation` computed（约 line 982-999），将 `dataLayer.getStocks()` 作为 `liveStocks` 传入：

```ts
const tradingPoolEvaluation = computed(() => {
  tradingPoolRefreshTick.value
  if (activePoolTab.value !== 'trading') {
    return { rows: [], staleCount: 0, exitedCount: 0 }
  }

  const thesisCandidates = candidates.value
    .filter((entry) => entry.tradeType === 'thesis')
    .map((entry) => {
      const review = candidateJournalService.reanalyzeCandidate(entry)
      return {
        ...review.currentAnalysis.signalsSnapshot?.quote,
        code: entry.stockCode,
        name: entry.stockName,
        rankTrend: review.currentAnalysis.signalsSnapshot?.rankTrend ?? null,
      }
    })

  // DataLayer 八平台热榜实时投影，每只票已有 rankTrend + jump 信号
  const liveStocks = (dataLayer.getStocks() || [])
    .filter((stock) => stock.rankTrend)
    .map((stock) => ({
      code: stock.code,
      name: stock.name,
      rankTrend: stock.rankTrend,
      // 实时投影通过 rankTrend 直接读取信号，不经过 candidateJournalService
    }))

  return analyzeTradingPoolCandidate({
    candidates: thesisCandidates,
    liveStocks,
    previousRows: previousTradingPoolRows.value,
  })
})
```

- [ ] **Step 2: 来源标签显示 `live_projection`**

在 `tradingPoolSourceLabel` 函数（或模板中等价逻辑）新增映射：

```ts
function tradingPoolSourceLabel(source: string): string {
  switch (source) {
    case 'candidate_auto_add': return '候选池通过'
    case 'candidate_watch': return '候选池观察'
    case 'jump_blocked_resonance': return 'Jump阻断强共振'
    case 'live_projection': return '热榜实时'
    case 'manual': return '手工加入'
    case 'persisted': return '历史恢复'
    default: return '未知'
  }
}
```

- [ ] **Step 3: 类型检查**

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: 无新增类型错误。

---

## Task 4: 补全候选池"强共振观察"投影分类

**Files:**
- Modify: `src/services/candidate/CandidatePoolStatusProjector.ts`
- Modify: `src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts`（追加测试到已有 describe 块之后）

- [ ] **Step 1: 新增强共振观察判定函数**

```ts
// CandidatePoolStatusProjector.ts

interface ResonanceObserveInput {
  finalSignal: string | null | undefined
  finalConfidence: number | null | undefined
  buyVotes: number
  jumpDirection: string | null | undefined
  jumpConfidence: number | null | undefined
  macdCross: string | null | undefined
  lifecycleAction: string | null | undefined
  hasOverheatAndDivergenceSell: boolean
}

export function isResonanceObserve(input: ResonanceObserveInput): boolean {
  return (
    input.finalSignal === 'buy' &&
    (input.finalConfidence ?? 0) >= 85 &&
    input.buyVotes >= 3 &&
    input.jumpDirection === 'buy' &&
    (input.jumpConfidence ?? 0) >= 80 &&
    input.lifecycleAction !== 'veto' &&
    input.macdCross !== 'death' &&
    !input.hasOverheatAndDivergenceSell
  )
}
```

- [ ] **Step 2: 在候选池投影中集成强共振观察标签**

在 `projectCandidatePoolStatus` 函数中，为每个 stock 计算共振观察标签：

```ts
// 在 projectCandidatePoolStatus 循环内新增
const projection = projectionByCode.get(normalizeCode(stock.code)) || null
// ... 现有逻辑 ...

// 强共振观察判定（规格 6.2）
const rankTrend = (stock as any)?.rankTrend
if (rankTrend) {
  const signals = rankTrend.technical?.signals
  const buyVotes = [
    signals?.direction?.signal === 'buy',
    signals?.acceleration?.signal === 'buy',
    signals?.zeroCross?.signal === 'buy',
    rankTrend.technical?.macd?.cross === 'golden',
  ].filter(Boolean).length

  const hasDoubleRisk =
    (rankTrend.risk?.overheatReversal?.signal === 'sell' || rankTrend.risk?.overheat?.signal === 'sell') &&
    (rankTrend.risk?.capitalDivergence?.signal === 'sell' || rankTrend.risk?.divergence?.signal === 'sell')

  const resonanceEligible = isResonanceObserve({
    finalSignal: rankTrend.decision?.final?.signal,
    finalConfidence: rankTrend.decision?.final?.confidence,
    buyVotes,
    jumpDirection: rankTrend.jump?.direction,
    jumpConfidence: rankTrend.jump?.confidence,
    macdCross: rankTrend.technical?.macd?.cross,
    lifecycleAction: rankTrend.cycle?.decision?.action,
    hasOverheatAndDivergenceSell: hasDoubleRisk,
  })

  if (resonanceEligible && (!projection || !projection.entryDecision?.accepted)) {
    ;(stock as any).candidateResonanceObserve = true
  }
}
```

- [ ] **Step 3: 锁定强共振观察分类测试**

```ts
// CandidatePoolStatusProjector.test.ts

import { isResonanceObserve } from '../CandidatePoolStatusProjector'
import { describe, it, expect } from 'vitest'

describe('isResonanceObserve', () => {
  it('returns true for full resonance with jump blocked', () => {
    expect(isResonanceObserve({
      finalSignal: 'buy',
      finalConfidence: 87,
      buyVotes: 3,
      jumpDirection: 'buy',
      jumpConfidence: 82.9,
      macdCross: 'none',
      lifecycleAction: 'allow',
      hasOverheatAndDivergenceSell: false,
    })).toBe(true)
  })

  it('returns false when final signal is not buy', () => {
    expect(isResonanceObserve({
      finalSignal: 'hold',
      finalConfidence: 90,
      buyVotes: 4,
      jumpDirection: 'buy',
      jumpConfidence: 85,
      macdCross: 'golden',
      lifecycleAction: 'allow',
      hasOverheatAndDivergenceSell: false,
    })).toBe(false)
  })

  it('returns false when buyVotes < 3', () => {
    expect(isResonanceObserve({
      finalSignal: 'buy',
      finalConfidence: 86,
      buyVotes: 2,
      jumpDirection: 'buy',
      jumpConfidence: 82,
      macdCross: 'none',
      lifecycleAction: 'allow',
      hasOverheatAndDivergenceSell: false,
    })).toBe(false)
  })

  it('returns false when jump confidence < 80', () => {
    expect(isResonanceObserve({
      finalSignal: 'buy',
      finalConfidence: 86,
      buyVotes: 3,
      jumpDirection: 'buy',
      jumpConfidence: 75,
      macdCross: 'none',
      lifecycleAction: 'allow',
      hasOverheatAndDivergenceSell: false,
    })).toBe(false)
  })

  it('returns false with lifecycle veto', () => {
    expect(isResonanceObserve({
      finalSignal: 'buy',
      finalConfidence: 90,
      buyVotes: 4,
      jumpDirection: 'buy',
      jumpConfidence: 88,
      macdCross: 'golden',
      lifecycleAction: 'veto',
      hasOverheatAndDivergenceSell: false,
    })).toBe(false)
  })

  it('returns false with MACD death cross', () => {
    expect(isResonanceObserve({
      finalSignal: 'buy',
      finalConfidence: 86,
      buyVotes: 3,
      jumpDirection: 'buy',
      jumpConfidence: 82,
      macdCross: 'death',
      lifecycleAction: 'allow',
      hasOverheatAndDivergenceSell: false,
    })).toBe(false)
  })

  it('returns false with double risk (overheat + capital divergence)', () => {
    expect(isResonanceObserve({
      finalSignal: 'buy',
      finalConfidence: 90,
      buyVotes: 4,
      jumpDirection: 'buy',
      jumpConfidence: 88,
      macdCross: 'golden',
      lifecycleAction: 'allow',
      hasOverheatAndDivergenceSell: true,
    })).toBe(false)
  })
})
```

- [ ] **Step 4: 运行测试确认**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts --reporter=dot
```

Expected: 强共振观察测试全部通过。

---

## Task 5: DataTable tooltip 信息分层

**Files:**
- Modify: `src/components/common/DataTable.vue`

- [ ] **Step 1: 导入所需工具函数**

```ts
// DataTable.vue <script setup> 新增 import
import { isResonanceObserve } from '@/services/candidate/CandidatePoolStatusProjector'
```

`countBuyVotes` 是 `TradingPoolAnalysisService` 的私有函数，不在 DataTable 中重复依赖。直接在 DataTable.vue 内联一个轻量版本：

```ts
function getBuyVotes(stock: any): number {
  const s = stock?.rankTrend?.technical?.signals
  return [
    s?.direction?.signal === 'buy',
    s?.acceleration?.signal === 'buy',
    s?.zeroCross?.signal === 'buy',
    stock?.rankTrend?.technical?.macd?.cross === 'golden',
  ].filter(Boolean).length
}
```

- [ ] **Step 2: 读取交易池动作（从 CandidatePoolPanel 共享状态或独立计算）**

由于 tooltip 在 DataTable 中展示，而交易池分析结果在 CandidatePoolPanel 中，采用方案：DataTable 不依赖 CandidatePoolPanel 状态，而是独立调用轻量预览。

```ts
function getTradingPoolPreview(stock: any): { label: string; buyVotes: number } | null {
  const rankTrend = stock?.rankTrend
  if (!rankTrend) return null

  const buyVotes = [
    rankTrend?.technical?.signals?.direction?.signal === 'buy',
    rankTrend?.technical?.signals?.acceleration?.signal === 'buy',
    rankTrend?.technical?.signals?.zeroCross?.signal === 'buy',
    rankTrend?.technical?.macd?.cross === 'golden',
  ].filter(Boolean).length

  const finalSignal = rankTrend?.decision?.final?.signal
  const finalConf = rankTrend?.decision?.final?.confidence ?? 0
  const jumpDirection = rankTrend?.jump?.direction
  const jumpConf = rankTrend?.jump?.confidence ?? 0
  const macdCross = rankTrend?.technical?.macd?.cross
  const lifecycle = rankTrend?.cycle?.decision?.action

  const hasDoubleRisk =
    (rankTrend?.risk?.overheatReversal?.signal === 'sell' || rankTrend?.risk?.overheat?.signal === 'sell') &&
    (rankTrend?.risk?.capitalDivergence?.signal === 'sell' || rankTrend?.risk?.divergence?.signal === 'sell')

  const resonance = isResonanceObserve({
    finalSignal,
    finalConfidence: finalConf,
    buyVotes,
    jumpDirection,
    jumpConfidence: jumpConf,
    macdCross,
    lifecycleAction: lifecycle,
    hasOverheatAndDivergenceSell: hasDoubleRisk,
  })

  const trendBuyCount = [
    rankTrend?.technical?.signals?.direction?.signal,
    rankTrend?.technical?.signals?.acceleration?.signal,
    rankTrend?.technical?.signals?.zeroCross?.signal,
  ].filter((s) => s === 'buy').length

  // 简化版判定（不重复完整状态机，只给出预览信息）
  let label = '—'
  if (resonance && finalConf >= 88 && jumpConf >= 85 && (macdCross === 'golden' || (rankTrend?.technical?.signals?.zeroCross?.signal === 'buy' && rankTrend?.technical?.signals?.direction?.signal === 'buy'))) {
    label = '准备介入'
  } else if (resonance && trendBuyCount >= 2) {
    label = '观察买点'
  } else if (finalSignal === 'sell' && finalConf >= 80) {
    label = '已退出'
  } else if (buyVotes >= 3 && jumpConf >= 80) {
    label = '观察中'
  }

  return { label, buyVotes }
}
```

- [ ] **Step 3: 改造 tooltip 模板**

在 `confidence` 列的 tooltip 模板中，从当前的单一 Jump 展示改为分层：

```ts
// 在 DataTable.vue 中 confidence 列的 tooltip 生成处
function buildConfidenceTooltip(stock: any): string {
  const rankTrend = stock?.rankTrend
  const finalSignal = rankTrend?.decision?.final?.signal ?? stock?.finalSignal ?? '—'
  const finalConf = rankTrend?.decision?.final?.confidence ?? stock?.finalConfidence ?? '—'
  const jumpConf = rankTrend?.jump?.confidence ?? stock?.jumpConfidence ?? '—'
  const preview = getTradingPoolPreview(stock)
  const buyVotes = preview?.buyVotes ?? 0

  const finalSignalLabel = finalSignal === 'buy' ? '买入' : finalSignal === 'sell' ? '卖出' : finalSignal === 'hold' ? '持有' : String(finalSignal)

  const lines = [
    `综合判断: ${finalSignalLabel} (置信度: ${typeof finalConf === 'number' ? finalConf.toFixed(1) : finalConf}%)`,
    `Jump跃迁: ${typeof jumpConf === 'number' ? jumpConf.toFixed(1) : jumpConf}%`,
    `共振评级: ${buyVotes >= 3 ? '强共振' : buyVotes >= 2 ? '中' : '弱'} (BuyVotes: ${buyVotes}/4)`,
    `交易池动作: ${preview?.label ?? '—'}`,
  ]

  // 追加原有的四维信号行（如果 tooltip 原来有的话）
  return lines.join('\n')
}
```

- [ ] **Step 4: 类型检查**

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: 无新增类型错误。

---

## Task 6: 补全交易池面板字段和详情区

**Files:**
- Modify: `src/components/panels/CandidatePoolPanel.vue`

- [ ] **Step 1: 补齐交易池表头**

在交易池左侧列表表头区域（约 line ~200 附近），确保表头包含以下列：

```vue
<div class="trading-pool-row trading-pool-head">
  <span style="width:100px">股票</span>
  <span style="width:72px">来源</span>
  <span style="width:72px">状态</span>
  <span style="width:64px">综合</span>
  <span style="width:64px">Jump</span>
  <span style="width:48px">票数</span>
  <span style="width:48px">MACD</span>
  <span style="width:80px">风险</span>
  <span style="flex:1">原因</span>
  <span style="width:72px">操作</span>
</div>
```

- [ ] **Step 2: 补齐每行字段渲染**

```vue
<template v-for="row in visibleTradingPoolRows" :key="row.code">
  <div class="trading-pool-row" @click="selectTradingPoolRow(row)">
    <span style="width:100px">{{ row.name || row.code }}</span>
    <span style="width:72px">{{ tradingPoolSourceLabel(row.signalSnapshot.source) }}</span>
    <span style="width:72px">{{ row.status }}</span>
    <span style="width:64px">{{ row.signalSnapshot.finalConfidence?.toFixed(0) ?? '-' }}</span>
    <span style="width:64px">{{ row.signalSnapshot.jumpConfidence?.toFixed(1) ?? '-' }}</span>
    <span style="width:48px">{{ row.signalSnapshot.buyVotes }}/4</span>
    <span style="width:48px">{{ macdLabel(row.signalSnapshot.macdCross) }}</span>
    <span style="width:80px">{{ riskSummary(row.signalSnapshot.riskFlags) }}</span>
    <span style="flex:1">{{ row.reasons.join(', ') }}</span>
    <span style="width:72px">
      <button v-if="row.status !== '已介入' && row.decision !== 'exit'" @click.stop="markIntervened(row)">介入</button>
      <button v-if="row.status !== '已退出'" @click.stop="downgradeToWatch(row)">降级</button>
      <button v-if="row.decision !== 'exit'" @click.stop="exitTracking(row)">退出</button>
    </span>
  </div>
</template>
```

- [ ] **Step 3: 添加工具函数**

```ts
function macdLabel(cross: string | null | undefined): string {
  if (cross === 'golden') return '金叉'
  if (cross === 'death') return '死叉'
  return '—'
}

function riskSummary(flags: string[]): string {
  if (!flags.length) return '无'
  const map: Record<string, string> = {
    lifecycle_veto: '周期否决',
    macd_death_cross: '死叉',
    overheat_sell: '过热',
    capital_divergence_sell: '背离',
    momentum_sync_broken: '动量断',
    jump_confidence_low: 'Jump低',
    final_confidence_low: '综合低',
    candidate_hard_blocked: '候选阻断',
    data_stale: '过期',
  }
  return flags.slice(0, 2).map((f) => map[f] || f).join('+')
}
```

- [ ] **Step 4: 扩展已有筛选逻辑**

**注意**：`tradingDecisionFilter`（line 579）和 `tradingStatusFilter`（line 580）ref 已在 CandidatePoolPanel.vue 中存在；`visibleTradingPoolRows` computed（line 1019-1029）也已包含三级过滤。**不要重新声明**这些 ref 和 computed，而是扩展现有逻辑：

1. 确认现有 `tradingDecisionFilter` 的 `<select>` 模板中是否已包含 `enter`、`watch`、`downgrade`、`exit`、`stale` 选项；缺失的补上
2. 确认现有 `tradingStatusFilter` 的 `<select>` 模板中是否已包含 `观察买点`、`准备介入`、`观察中`、`已介入`、`已退出` 选项；缺失的补上

- [ ] **Step 5: 类型检查**

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: 无新增类型错误。

---

## Task 7: 面板测试锁定

**Files:**
- Modify: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`

- [ ] **Step 1: 锁定 live_projection 行渲染**

```ts
it('renders live_projection source rows in trading pool', async () => {
  const wrapper = mountCandidatePoolPanelWithTradingRows([
    {
      code: '603738',
      name: '泰晶科技',
      status: '准备介入',
      decision: 'enter',
      reasons: ['strong_consensus'],
      signalSnapshot: {
        finalSignal: 'buy',
        finalConfidence: 91,
        jumpDirection: 'buy',
        jumpConfidence: 87.9,
        directionSignal: 'buy',
        directionConfidence: 88,
        accelerationSignal: 'buy',
        accelerationConfidence: 90,
        zeroCrossSignal: 'buy',
        zeroCrossConfidence: 90,
        macdCross: 'golden',
        buyVotes: 4,
        riskFlags: [],
        source: 'live_projection',
        momentumSyncBroken: false,
        lifecycleAction: 'allow',
        dataQuality: 'fresh',
      },
    },
  ])

  await wrapper.find('[data-testid="candidate-pool-tab-trading"]').trigger('click')

  expect(wrapper.text()).toContain('泰晶科技')
  expect(wrapper.text()).toContain('热榜实时')
  expect(wrapper.text()).toContain('4/4')
})
```

- [ ] **Step 2: 运行面板测试确认**

```powershell
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot
```

Expected: PASS.

---

## Task 8: 验收

**Files:**
- No source edits beyond previous tasks.

- [ ] **Step 1: 运行交易池服务测试**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot
```

Expected: 全部通过（含新增 live_projection 用例）。

- [ ] **Step 2: 运行强共振观察分类测试**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts --reporter=dot
```

Expected: 全部通过。

- [ ] **Step 3: 运行候选池面板测试**

```powershell
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot
```

Expected: 全部通过。

- [ ] **Step 4: 运行 RankTrend 全量回归**

```powershell
pnpm test:ranktrend
pnpm typecheck:ranktrend
```

Expected: 零回归。

- [ ] **Step 5: 运行应用类型检查**

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: exit code 0，无新增错误。

- [ ] **Step 6: Playwright 浏览器验收 — 交易池面板**

启动 dev server 后：

```powershell
npx playwright-cli -s=ranktrend open http://localhost:5173 --headed
```

验收项：
- 打开候选池 → 切换到交易池 tab
- 交易池面板不空白，有行展示
- `live_projection` 来源行显示"热榜实时"标签
- 有综合置信度、Jump 置信度、BuyVotes、MACD、风险标签列
- 至少存在状态为 `观察买点` 或 `准备介入` 的行

- [ ] **Step 7: Playwright 浏览器验收 — DataTable tooltip**

```powershell
npx playwright-cli -s=ranktrend eval "
await page.hover('[data-testid=\"confidence-cell\"]');
await page.waitForTimeout(500);
const tooltip = await page.textContent('.tooltip, [role=\"tooltip\"]');
console.log('Tooltip:', tooltip);
"
```

验收项：
- tooltip 包含"综合判断"
- tooltip 包含"Jump跃迁"
- tooltip 包含"共振评级"
- tooltip 包含"交易池动作"
- `confidence` 列表头显示"Jump置信"

---

## Task 9: 自审清单

- [ ] DataLayer 来源描述为"八平台热榜 200+ 只票"，不是"全市场"
- [ ] `liveStocks` 为可选字段，传空数组或 undefined 即恢复旧行为
- [ ] thesis 候选与 live projection 同名 code 时 thesis 优先
- [ ] 实时投影行不依赖 `candidateEntryDecision`
- [ ] 候选池 V5/Fusion 合同未被放宽
- [ ] 无新阈值引入，无阈值数值变更
- [ ] tooltip 没有再把 Jump 置信度称为综合置信度
- [ ] 未修改 QuantBoard 后端或历史交易日志
- [ ] 配置统一化（spec 7.0 / design Phase 3）不在本次计划范围内，后续单独出计划
