# RankTrend Fusion Candidate Pool Unified Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status note (2026-06-08):** 本计划已根据审查意见重写。旧版计划中“用 `trade_journal` 反推策略持有状态”“按股票代码把历史 trade 折叠成单条 projection”“把 `snapshotType` 写死为 `half_hour`”等步骤已废弃，不应继续作为执行依据。

> **Scope note (2026-06-10):** 本计划只解决候选池 projection / execution overlay 语义，不等同于 V5 回测执行合同完整接入。V5 live execution contract 以 `2026-06-10-ranktrend-v5-live-execution-contract-implementation-plan.md` 为准。

**Goal:** 以 `ranktrend_early_big_move_v3_lifecycle_fusion` 作为候选池语义层唯一策略锚点，重建 Dragon Board 主表【候选池】和候选池面板的统一语义，让两者都只展示“策略生命周期事实 + execution overlay”，不再以 `trade_journal.status`、`CandidateAnalysisService` 或 `CandidateDiscoveryService` 充当主状态真相。

**Architecture:** 先新增 `FusionStrategyProjection` 合同与 live projector，让主表【候选池】从“journal 工作流态”切换为“策略态投影”。随后把候选池面板从“通用候选研究台”重构为“fusion 主线策略生命周期工作台”，保留 `trade_journal` 仅作为执行和复盘 overlay。最后在 QuantBoard 补历史 projection 能力，但必须基于时间序列 / lifecycle segment 构建，不能按股票代码把整次回测 trade 折叠成一条。

**Tech Stack:** Vue 3, TypeScript, Vitest, FastAPI, Python, QuantBoard journal API, QuantBoard backtest API

---

## 0. 实施前必须锁定的口径

1. 本次“唯一 Golden”只作用于**候选池语义层**。
   - QuantBoard / Dragon Board 全局 golden 仍然是 TypeScript `rankTrend` 链。

2. `trade_journal` 只能提供 execution overlay。
   - 不得由 `entryTime / exitTime / status` 反推 `active_holding / exit_signaled / closed`。

3. `snapshotType` 合同必须允许：
   - 默认 `half_hour`
   - 显式 `quarter_hour`
   - 不能在类型层写死为 `'half_hour'`

4. 候选池面板虽然要摆脱“通用候选研究台”，但不能丢掉正式录入入口：
   - 假设编辑
   - 执行记录
   - 复盘保存

5. 历史 projection 不能用 `trade_by_code` 简单拼接。
   - 必须按 `snapshotId / signalSnapshotId / sequence / lifecycle segment` 对齐。

### 0.1 当前代码基线（2026-06-08，`3fdf8be` 之后）

以下文件已经由 `2026-06-08-ranktrend-fusion-candidate-pool-replacement-design.md` 旧方案落地，本计划是在这些实现之上做二次改写，不是从零开始：

| 文件 | 当前已落地职责 | 本计划目标职责 | 操作类型 |
| --- | --- | --- | --- |
| `src/services/candidate/CandidatePoolStatusProjector.ts` | `trade_journal.status -> 主表标签` | `FusionStrategyProjection -> 主表字段 facade` | **重写** |
| `src/services/rankTrend/FusionCandidateNotifier.ts` | 自动建 `status=triggered` journal entry + 飞书 | 自动建壳 + 通知，只写不读 | **收窄** |
| `src/services/rankTrend/fusionStrategy.ts` | `isFusionEntryCandidate()` 基础 gate | 保留，同步被 `FusionStrategyProjector` 复用 | **保留 + 调用方变更** |
| `src/components/common/DataTable.vue` | 展示 journal workflow 态 badge | 展示 `strategyState` badge + projection tooltip | **数据源替换** |
| `src/services/dataLoader/RankTrendSignalService.ts` | `notifier.process() + applyCandidatePoolStatus()` | `notifier.process() + FusionStrategyProjector + 新 facade` | **刷新链路改写** |
| `src/components/panels/CandidatePoolPanel.vue` | 通用候选研究台 | fusion 生命周期工作台 | **信息架构重构** |

以下文件是本计划的纯新增：

| 文件 | 职责 |
| --- | --- |
| `src/types/fusionStrategyProjection.ts` | `FusionStrategyProjection` 类型合同 |
| `src/services/rankTrend/FusionStrategyProjector.ts` | live projection 主入口 |
| `quant-board/backend/services/fusion_strategy_projection_service.py` | 历史 projection 构建服务 |
| `quant-board/backend/api/fusion_strategy_projection_routes.py` | 历史 projection API |

### 0.2 当前刷新链路 vs 目标刷新链路

```ts
// --- 当前已落地链路（旧 replacement 方案）---
async refreshRankTrendSignals() {
  const updates = this.rankTrendAnalyzer.analyze(/* ... */)
  const mergedStocks = this.updateStockSignals(updates)
  this.applyJumpSignals(mergedStocks)
  await this.fusionCandidateNotifier.process(mergedStocks)
  await applyCandidatePoolStatus(mergedStocks)
  return mergedStocks
}
```

```ts
// --- 本计划目标链路（统一语义方案）---
async refreshRankTrendSignals() {
  const updates = this.rankTrendAnalyzer.analyze(/* ... */)
  const mergedStocks = this.updateStockSignals(updates)
  this.applyJumpSignals(mergedStocks)
  await this.fusionCandidateNotifier.process(mergedStocks) // 保留：自动建壳 + 通知（只写不读）
  const projections = this.fusionProjector.buildProjections(mergedStocks, {
    executionOverlayByCode: await this.candidateJournal.getExecutionOverlayMap(
      mergedStocks.map((item) => item.code),
    ),
  })
  this.projectorFacade.applyToStocks(mergedStocks, projections)
  return mergedStocks
}
```

---

## 1. File Map

- Create: `src/types/fusionStrategyProjection.ts`
  - `FusionStrategyProjection`、`FusionStrategyState`、`FusionSnapshotType`、`FusionExecutionOverlay`
- Create: `src/services/rankTrend/FusionStrategyProjector.ts`
  - live projection 主入口，基于 `stock.rankTrend` + 策略运行态事实 + execution overlay 生成统一 projection
- Create: `src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts`
  - 锁定 `idle / triggered_wait_entry` 的稳定合同
  - 若已有可靠 live 持仓事实源，再补 `active_holding / exit_signaled / closed`
- Modify: `src/services/candidate/CandidatePoolStatusProjector.ts`
  - 从 “journal status 投影器” 改为 “FusionStrategyProjection -> 主表字段 facade”
- Modify: `src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts`
- Modify: `src/services/dataLoader/RankTrendSignalService.ts`
  - 刷新链路改成 `rankTrend -> FusionStrategyProjector -> 主表候选池字段`
- Modify: `src/components/common/DataTable.vue`
  - `jumpSignal` 列 tooltip / badge / 点击行为全部改读 projection 字段
- Modify: `src/components/common/__tests__/DataTable.test.ts`
- Modify: `src/services/candidate/types.ts`
  - 新增 projection-oriented view types
- Modify: `src/services/candidate/CandidateJournalService.ts`
  - 保留 add / thesis / review / execution 写口
  - 新增 `toExecutionOverlay()` / `getExecutionOverlayMap()`
- Modify: `src/services/rankTrend/FusionCandidateNotifier.ts`
  - 降级为“自动建壳 + 通知器”
- Modify: `src/services/rankTrend/fusionStrategy.ts`
  - 保留 `isFusionEntryCandidate()`，作为 live projection 的 base gate，不新增重复规则 helper
- Modify: `src/components/panels/CandidatePoolPanel.vue`
  - 重做为 “fusion 生命周期工作台”
- Modify: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - 删除 discovery / 候选质量 / 双评分中心断言
  - 保留“执行记录 / 对齐复盘 / 假设编辑”断言
- Modify: `src/services/candidate/CandidateAnalysisService.ts`
  - 降级为辅助解释模块
- Modify: `src/services/candidate/CandidateDiscoveryService.ts`
  - 从主候选池链路移除
- Modify: `src/services/candidate/CandidateQualityStatsService.ts`
  - 从主候选池链路移除
- Create: `quant-board/backend/services/fusion_strategy_projection_service.py`
  - 基于 backtest 时间序列构建历史 projection rows
- Create: `quant-board/backend/api/fusion_strategy_projection_routes.py`
  - 暴露历史 projection API
- Create: `quant-board/tests/test_fusion_strategy_projection_api.py`
  - 锁定 QuantBoard 输出合同
- Modify: `quant-board/backend/main.py`
  - 注册新的 projection routes
- Modify: `quant-board/docs/api-cli.md`
- Modify: `quant-board/docs/frontend.md`
- Modify: `quant-board/docs/AI_COLLABORATION.md`
  - 同步 `trade_journal` 降级为 execution overlay、主候选池状态来自 projection 的新口径
- Modify: `quant-board/docs/superpowers/specs/2026-06-08-ranktrend-fusion-candidate-pool-unified-semantics-design.md`
  - 实施后回填状态与偏差

---

## 2. Phase 1：先收紧合同，不让状态来源跑偏

### Task 1.1：引入 `FusionStrategyProjection` 主合同

**Files**
- Create: `src/types/fusionStrategyProjection.ts`
- Modify: `src/services/candidate/types.ts`

**Contract**

```ts
export type FusionSnapshotType = 'half_hour' | 'quarter_hour'

export type FusionStrategyState =
  | 'idle'
  | 'triggered_wait_entry'
  | 'active_holding'
  | 'exit_signaled'
  | 'closed'

export interface FusionExecutionOverlay {
  executed: boolean
  entryPrice?: number
  entryTime?: string
  exitPrice?: number
  exitTime?: string
  stopLossPrice?: number
  takeProfitPrice?: number
  positionPct?: number
  reviewOutcome?: string
  executionResult?: string
  reviewNotes?: string
}

export interface FusionStrategyProjection {
  stockCode: string
  stockName: string
  strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion'
  snapshotType: FusionSnapshotType
  tradingDate: string
  snapshotId: string
  frameTime: string
  projectionSource: 'live' | 'backtest'
  strategyState: FusionStrategyState
  candidateTier: 'A_MAIN' | 'B_IGNITION' | 'C_CROWDED' | 'D_EXIT_RISK' | 'N_NEUTRAL'
  lifecycleAction: 'allow' | 'caution' | 'veto' | 'exit_watch'
  triggerAt?: string
  strategyEntryAt?: string
  strategyExitAt?: string
  holdingBars?: number
  slotIndex?: number
  maxPositions?: number
  tPlusOneUnlocked?: boolean
  entryReason?: string
  exitReason?: string
  strategyEntryPrice?: number
  strategyExitPrice?: number
  strategyReturnPct?: number
  executionOverlay?: FusionExecutionOverlay | null
}
```

**验收**
- 类型中不再把 `snapshotType` 写死成 `'half_hour'`
- `executionOverlay` 与 `strategyState` 在合同层分离

### Task 1.2：先写失败测试，锁定“状态不能来自 execution overlay”

**Files**
- Create: `src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts`

```ts
it('does not infer active_holding from manual execution overlay alone', () => {
  const projection = buildFusionStrategyProjection({
    stock: createFusionStock('600001'),
    snapshotType: 'half_hour',
    tradingDate: '2026-06-08',
    snapshotId: 'snap-1',
    frameTime: '2026-06-08T10:00:00+08:00',
    strategyLifecycle: {
      triggered: true,
      hasOpenPosition: false,
    },
    executionOverlay: {
      executed: true,
      entryTime: '2026-06-08T10:30:00+08:00',
      entryPrice: 12.5,
    },
  })

  expect(projection.strategyState).toBe('triggered_wait_entry')
})

it('does not infer closed from execution exitTime when strategy lifecycle has not confirmed closure', () => {
  const projection = buildFusionStrategyProjection({
    stock: createFusionStock('600001'),
    snapshotType: 'half_hour',
    tradingDate: '2026-06-08',
    snapshotId: 'snap-2',
    frameTime: '2026-06-08T14:00:00+08:00',
    strategyLifecycle: {
      triggered: true,
      hasOpenPosition: true,
      closed: false,
      entryAt: '2026-06-08T10:30:00+08:00',
    },
    executionOverlay: {
      executed: true,
      entryTime: '2026-06-08T10:30:00+08:00',
      entryPrice: 12.5,
      exitTime: '2026-06-08T13:30:00+08:00',
      exitPrice: 11.8,
    },
  })

  expect(projection.strategyState).toBe('active_holding')
})
```

**Run**

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts
```

Expected: FAIL

---

## 3. Phase 2：落地 live projection，只先承诺有可靠事实源的状态

### Task 2.1：实现 `FusionStrategyProjector`

**Files**
- Create: `src/services/rankTrend/FusionStrategyProjector.ts`

**实现原则**

1. `triggered_wait_entry`
   - 来自 `isFusionEntryCandidate(stock)` 命中

2. `active_holding / exit_signaled / closed`
   - 只允许来自 `strategyLifecycle` 这类显式策略事实输入
   - 若当前 live 模式没有可靠事实源，第一版不强行产出

3. `executionOverlay`
   - 只是附着到 projection
   - 不参与主状态判定

**最小实现草图**

```ts
export function buildFusionStrategyProjection(input: BuildProjectionInput): FusionStrategyProjection {
  const execution = input.executionOverlay || null
  const lifecycle = input.strategyLifecycle
  const baseTriggered = lifecycle?.triggered ?? isFusionEntryCandidate(input.stock)

  let strategyState: FusionStrategyState = 'idle'
  if (baseTriggered) strategyState = 'triggered_wait_entry'
  if (lifecycle?.hasOpenPosition) strategyState = 'active_holding'
  if (lifecycle?.exitWatch && lifecycle?.hasOpenPosition) strategyState = 'exit_signaled'
  if (lifecycle?.closed) strategyState = 'closed'

  return {
    stockCode: normalizeCode(input.stock.code),
    stockName: String(input.stock.name || input.stock.code || ''),
    strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
    snapshotType: input.snapshotType,
    tradingDate: input.tradingDate,
    snapshotId: input.snapshotId,
    frameTime: input.frameTime,
    projectionSource: 'live',
    strategyState,
    candidateTier: normalizeCandidateTier(input.stock.rankTrend?.strategy?.candidateTier),
    lifecycleAction: normalizeLifecycleAction(input.stock.rankTrend?.cycle?.decision?.action),
    triggerAt: baseTriggered ? lifecycle?.triggerAt || input.frameTime : undefined,
    strategyEntryAt: lifecycle?.entryAt,
    strategyExitAt: lifecycle?.exitAt,
    holdingBars: lifecycle?.holdingBars,
    slotIndex: lifecycle?.slotIndex,
    maxPositions: lifecycle?.maxPositions,
    tPlusOneUnlocked: lifecycle?.tPlusOneUnlocked,
    exitReason: lifecycle?.exitReason,
    executionOverlay: execution,
  }
}
```

**Run**

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts
```

Expected: PASS

### Task 2.2：主表【候选池】改读 projection，而不是 `trade_journal.status`

**Files**
- Modify: `src/services/candidate/CandidatePoolStatusProjector.ts`
- Modify: `src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts`
- Modify: `src/services/dataLoader/RankTrendSignalService.ts`
- Modify: `src/components/common/DataTable.vue`
- Modify: `src/components/common/__tests__/DataTable.test.ts`
- Modify: `src/services/dataLoader/__tests__/RankTrendSignalService.test.ts`

**关键改法**

1. 先删除旧的 journal workflow 态映射表：

```ts
// 删除旧定义
// const STATUS_LABELS: Record<CandidatePoolProjectedStatus, string> = {
//   none: '未入池',
//   observe: '观察',
//   candidate: '候选',
//   triggered: '已触发',
//   tracking: '跟踪中',
//   reviewed: '已复盘',
// }
```

2. 再新增策略态映射表：

```ts
const TABLE_LABELS: Record<FusionStrategyState, string> = {
  idle: '未触发',
  triggered_wait_entry: '待入场',
  active_holding: '策略持有中',
  exit_signaled: '策略退出观察',
  closed: '策略已关闭',
}
```

```ts
stock.candidatePoolStatus = projection?.strategyState || 'idle'
stock.candidatePoolLabel = TABLE_LABELS[stock.candidatePoolStatus]
stock.candidatePoolProjection = projection || null
stock.candidatePoolSource = projection?.projectionSource || ''
stock.candidatePoolUpdatedAt = projection?.frameTime || ''
```

3. 删除旧的 `CandidateJournalEntry[] -> stock` 投影测试用例，改成 `FusionStrategyProjection facade` 测试用例。

4. `openCandidatePoolFromCell` 改为双路径定位：

```ts
function openCandidatePoolFromCell(stock: any) {
  const entryId = stock?.candidatePoolEntryId || ''
  EventManager.emit('candidate-pool:open', {
    candidateId: entryId || '',
    stockCode: stock?.code || '',
  })
}
```

**新的测试重点**

- 不再断言 `candidatePoolStatus = entry.status`
- DataTable tooltip 直接读 `candidatePoolProjection.strategyState / holdingBars / candidateTier`
- 不再显示 `candidatePoolSource = journal workflow`
- 若无 journal entry ID，仍能按 `stock.code` 打开候选池面板

**链路替换说明**

```ts
// --- 旧链路 ---
await this.fusionCandidateNotifier.process(mergedStocks)
await applyCandidatePoolStatus(mergedStocks)

// --- 新链路 ---
await this.fusionCandidateNotifier.process(mergedStocks)
const projections = this.fusionProjector.buildProjections(mergedStocks, {
  executionOverlayByCode: await this.candidateJournal.getExecutionOverlayMap(
    mergedStocks.map((item) => item.code),
  ),
})
this.projectorFacade.applyToStocks(mergedStocks, projections)
```

**Run**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts src/components/common/__tests__/DataTable.test.ts src/services/dataLoader/__tests__/RankTrendSignalService.test.ts
```

Expected: PASS

---

## 4. Phase 3：候选池面板重构，但保留 overlay 写口

### Task 3.1：重写主信息架构

**Files**
- Modify: `src/components/panels/CandidatePoolPanel.vue`
- Modify: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`

**保留**

- 假设编辑
- 执行记录
- 对齐复盘 / 保存复盘

**移除**

- 建议入池
- 候选质量
- 候选漏斗
- 当前重分析 / 入池快照 双评分中心

**新的测试重点**

```ts
expect(source).toContain('策略事实')
expect(source).toContain('执行事实')
expect(source).toContain('对齐复盘')
expect(source).toContain('假设编辑')
expect(source).toContain('执行记录')
expect(source).not.toContain('建议入池')
expect(source).not.toContain('候选质量')
expect(source).not.toContain('候选漏斗')
expect(source).not.toContain('当前重分析')
expect(source).not.toContain('入池快照')
expect(source).not.toContain('候选研究，不含交易盈亏')
```

### Task 3.2：`CandidateAnalysisService` / `CandidateDiscoveryService` / `CandidateQualityStatsService` 降级

**Files**
- Modify: `src/services/candidate/CandidateAnalysisService.ts`
- Modify: `src/services/candidate/CandidateDiscoveryService.ts`
- Modify: `src/services/candidate/CandidateQualityStatsService.ts`

**原则**

- `CandidateAnalysisService` 只做辅助解释
- `CandidateDiscoveryService` 不再参与主候选池列表 / 主统计 / 主排序
- `CandidateDiscoveryService.ts` 源文件保留，不删除，只从 `CandidatePoolPanel.vue` 的 import / 调用链移除
- `CandidateQualityStatsService` 不再参与主面板中心链路
- 旧测试保留，但改成“独立模块仍可存在，不再被主候选池消费”的断言

**Run**

```powershell
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateDiscoveryService.test.ts src/services/candidate/__tests__/CandidateQualityStatsService.test.ts
```

Expected: PASS

---

## 5. Phase 4：把 `trade_journal` 明确降级为 execution overlay

### Task 4.1：给 `CandidateJournalService` 增加 overlay helper

**Files**
- Modify: `src/services/candidate/CandidateJournalService.ts`
- Modify: `src/services/candidate/__tests__/CandidateJournalService.test.ts`

```ts
toExecutionOverlay(entry: CandidateJournalEntry | null | undefined): FusionExecutionOverlay | null {
  if (!entry) return null
  const hasExecution =
    !!entry.entryTime ||
    !!entry.exitTime ||
    Number.isFinite(Number(entry.entryPrice)) ||
    Number.isFinite(Number(entry.exitPrice))

  return {
    executed: hasExecution,
    entryPrice: entry.entryPrice,
    entryTime: entry.entryTime,
    exitPrice: entry.exitPrice,
    exitTime: entry.exitTime,
    stopLossPrice: entry.stopLossPrice,
    takeProfitPrice: entry.takeProfitPrice,
    positionPct: entry.positionPct,
    reviewOutcome: entry.reviewOutcome,
    executionResult: entry.executionResult,
    reviewNotes: entry.reviewNotes,
  }
}
```

### Task 4.2：`FusionCandidateNotifier` 只做自动建壳 + 通知

**Files**
- Modify: `src/services/rankTrend/FusionCandidateNotifier.ts`
- Modify: `src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts`

**原则**

- 允许 `statusOverride: 'triggered'` 作为 journal shell 初始值
- 但 UI 主状态不得再读取这个字段
- 飞书推送保留，但内容改为“fusion 策略候选池触发”，增加 `candidateTier`、`lifecycleAction` 字段，弱化旧 `signalType / signalLabel` 语义

**Run**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts
```

Expected: PASS

---

## 6. Phase 5：历史 projection API 单独落地，不再偷懒按 code 折叠

### Task 5.1：先选正确 API 形态

不建议使用松散的：

```text
GET /api/fusion-strategy/projections?dataset_id=...&run_id=...
```

更贴合现有 QuantBoard backtest 体系的是：

```text
GET /api/backtests/{run_id}/fusion-projections
```

原因：

1. 当前已有：
   - `/api/backtests/{run_id}/trades`
   - `/api/backtests/{run_id}/signals`
   - `/api/backtests/{run_id}/quality`
2. `run_id` 已经隐含 `dataset_id / snapshot_type / strategy_version / config_hash / random_seed`
3. 可以直接复用 BacktestService / run metadata

### Task 5.2：先构建历史 lifecycle segment，再投影 rows

**Files**
- Create: `quant-board/backend/services/fusion_strategy_projection_service.py`
- Create: `quant-board/backend/api/fusion_strategy_projection_routes.py`
- Create: `quant-board/tests/test_fusion_strategy_projection_api.py`
- Modify: `quant-board/backend/main.py`

**禁止做法**

```python
trade_by_code = {code: trade for trade in trades}
```

这会把一只股票整次回测的多次 signal / 多段持仓压成一条，直接错配时间轴。

**正确方向**

1. 先读取：
   - run metadata
   - `backtest_signals`
   - `backtest_trades`
   - 若需要，再读取 `tradeEvents / openPositions / lifecycle segments`
2. 按时间序列构建 `FusionLifecycleSegment`
3. 再把 segment 投影成前端 `FusionStrategyProjection[]`

**建议返回**

```python
{
    "ok": True,
    "runId": run_id,
    "datasetId": run.dataset_id,
    "snapshotType": run.snapshot_type,
    "strategyName": run.strategy_name,
    "strategyVersion": run.strategy_version,
    "configHash": run.config_hash,
    "randomSeed": run.random_seed,
    "rows": [...],
}
```

### Task 5.3：测试必须 mock repo，不连真实 Mongo

**理由**

- `create_repository()` 在 Mongo 模式下会返回运行仓储
- pytest 下还有生产库保护
- 这里要做的是合同测试，不是环境连通测试

**推荐测试方式**

```python
def test_fusion_projection_api_returns_projection_rows(monkeypatch):
    fake_repo = FakeRepo(...)
    monkeypatch.setattr('backend.api.fusion_strategy_projection_routes.create_repository', lambda *_args, **_kwargs: fake_repo)
```

**Run**

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_fusion_strategy_projection_api.py
```

Expected: PASS

### Task 5.4：同步文档

**Files**
- Modify: `quant-board/docs/api-cli.md`
- Modify: `quant-board/docs/frontend.md`
- Modify: `quant-board/docs/AI_COLLABORATION.md`

同步说明：

- 新路由路径
- 响应字段
- 历史 / 实时同构 view model
- `trade_journal` 只做 execution overlay
- Layer 3 / 候选池执行记录描述改为“执行 overlay，主状态来自 projection”

---

## 7. Final Verification

### 前端

```powershell
pnpm test:ranktrend
pnpm typecheck:ranktrend
```

### QuantBoard

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_fusion_strategy_projection_api.py
```

### 文档回填

实施后回填设计文档：

```md
状态：已实施 / 部分实施

已落地：
- 主表【候选池】改读 `FusionStrategyProjection`
- 候选池面板改为“策略事实 + 执行事实 + 对齐复盘”
- `trade_journal` 降级为 execution overlay

暂未落地：
- live 模式完整持仓事实源
- 逐笔级别历史 / 实时完全一致
```

---

## 8. Self-Review

- 已修正“用 `executionOverlay` 定义策略状态”的错误路径
- 已修正“`snapshotType` 写死 `half_hour`”的合同错误
- 已修正“历史 projection 用 `trade_by_code` 折叠”的时间轴错误
- 已保留候选池面板上的正式 overlay 录入能力
- 已把历史 API 设计收口到现有 `/api/backtests/{run_id}/...` 体系

## 9. Execution Handoff

推荐执行顺序：

1. Phase 1 + Phase 2
   - 先把 live projection 和主表语义纠正
2. Phase 3 + Phase 4
   - 再重构面板与 overlay 写口
3. Phase 5
   - 最后单独补 QuantBoard 历史 projection API

不要把三段一次性混做。第一优先级是先停止让 `trade_journal` 继续定义候选池真相。
