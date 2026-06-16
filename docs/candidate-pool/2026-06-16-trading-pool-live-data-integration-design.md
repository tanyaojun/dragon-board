# 交易池实时投影接入——补全规格设计方案

**日期**: 2026-06-16
**状态**: 已实施（2026-06-16）
**依赖**: [2026-06-15 交易池强共振自动入池规格](./2026-06-15-trading-pool-resonance-auto-entry-spec.md)
**关联**: [RankTrend Jump 跳跃检测实盘接入计划](../../quant-board/docs/superpowers/plans/2026-06-06-ranktrend-jump-signal-live-integration-plan.md)
**当前口径:** 来源边界、评分状态机、tooltip 语义、阈值真源和 limitUp 契约以 [交易池统一合同](./2026-06-16-trading-pool-unified-contract.md) 为准；本文保留实时投影接入背景与实现方案。

## 1. 问题诊断

### 1.1 数据管道断裂

6月15日A股市场4000+上涨、150+涨停，交易池零票入池。根因是三条数据管道只有一条通了：

```
RankTrendSignalService.refreshRankTrendSignals()
  │
  ├─ rankTrendAnalyzer.analyzeSignals() → stock.rankTrend (四维信号)
  ├─ evaluateJumpSignal()              → stock.rankTrend.jump (Jump跃迁)
  └─ applyJumpSignal()                 → stock.rankTrend._jumpEntry/Exit
       │
       └─→ dataLayer.getStocks() ← 📊 八平台热榜 200+ 只票实时信号
              │                       │
              │                  DataTable ✅ (能看到)
              │
       CandidatePoolPanel
              │
       candidateJournalService.listCandidates()
              │
       filter: tradeType === 'thesis'
              │
       analyzeTradingPoolCandidate()
              │
              ↓
         交易池 ← 只看 thesis 日记，完全不走 DataLayer ❌
```

**核心矛盾**：`RankTrendSignalService` 已将完整 Jump + 四维信号写入 DataLayer 的 200+ 只热榜股票，但交易池分析函数 `analyzeTradingPoolCandidate` 的输入管道只接了候选日记 thesis 条目。规格 7.1 明确写了第三来源（实时投影），但代码未实现。

### 1.2 三层 AND 过滤叠加（历史问题）

即便某只票通过了 Jump 6条件 AND（sustained surge + 动量共振 + 股价涨 + 非涨停 + MACD金叉 + 置信度≥85），还得再过交易池 8条件 AND（strongConsensus），再加上候选池 V5/Fusion 入口过滤。三层叠加在强情绪市场中也难有票通过。

> 当前实现已由统一合同改为交易池评分驱动，不再使用交易池 8 条件 AND 作为决策路径。

### 1.3 涨停过滤自伤（历史问题）

`checkEntryConditions`（jumpSignalService.ts:108）条件 4 `changePct >= limitPct - 0.3` 直接排除涨停票。在 150+ 涨停的市场中，最强势的票被入口规则系统性排除。而 DataLayer 覆盖的八平台热榜 200+ 只票恰恰是这些最活跃、最可能满足共振条件的标的。

> 当前实现已将该条件改为 `limitUp` 标记，由交易池输出 `涨停观察`，不再作为 Jump 硬排除。

## 2. 设计目标

**原始核心原则：不改阈值、不做自适应、不改 AND 门逻辑。纯粹补全规格中定义了但未实现的部分。**

后续 B+D 统一合同已进一步收敛为评分驱动 + 涨停分轨；本文以下阶段设计中与状态判定、tooltip 和 source 枚举冲突的片段均以统一合同为准。

1. 打通 DataLayer 热榜实时数据 → 交易池分析管道（规格 7.1 来源 3）
2. 补全 DataTable tooltip 信息分层（规格 9）
3. 补全候选池"强共振观察"分类（规格 6.2）
4. 补全交易池面板信息展示（规格 8.2-8.4）
5. 阈值从硬编码迁移到统一配置源（规格 7.0）
6. 补齐测试覆盖

## 3. 非目标

- 不改 `checkEntryConditions` 6条件（含涨停过滤）【已被统一合同取代：涨停改为 limitUp 标记】
- 不改 `strongConsensus` 8条件 AND 门【已被统一合同取代：交易池状态改为评分驱动】
- 不改任何阈值数值
- 不引入市场情绪自适应
- 不改 QuantBoard 回测主链
- 不做工具类重构或大范围格式化

## 4. 阶段设计

### 阶段 1：打通 DataLayer → 交易池数据管道

#### 4.1 扩展 TradingPoolInput

**文件**：`src/services/candidate/TradingPoolAnalysisService.ts`

```ts
interface TradingPoolInput {
  candidates: TradingPoolCandidateLike[]
  previousRows?: Array<Partial<TradingPoolAnalysisRow> & { code: string }>
  liveStocks?: TradingPoolCandidateLike[]  // 新增：DataLayer 实时投影
}
```

`analyzeTradingPoolCandidate` 内部合并逻辑：

1. 将 `candidates`（thesis 候选）和 `liveStocks`（实时投影）按 code 去重合并
2. thesis 候选优先（同名 code 以 thesis 为准）
3. 实时投影行标记 `source: 'live_projection'`
4. 新增来源类型 `'live_projection'` 到 `TradingPoolSource` 联合类型

**合并逻辑**（在 `analyzeTradingPoolCandidate` 内部，使用 `liveStocks` 可选参数）：

```ts
// thesis 候选优先，同名 code 以 thesis 为准
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
    if (!code || thesisCodes.has(code)) continue
    mergedCandidates.push({
      ...stock,
      tradingPoolSource: 'live_projection' as TradingPoolSource,
    })
  }
}
// 后续遍历 mergedCandidates 替代原来的 input.candidates
```

**同时修改 `resolveTradingPoolSource`**：在检查 `manual`/`persisted` 之后、检查 `candidateEntryDecision` 之前，新增 `if (stock.tradingPoolSource === 'live_projection') return 'live_projection'`，防止实时投影行被误标为 `'unknown'`。

#### 4.2 CandidatePoolPanel 接入 DataLayer

**文件**：`src/components/panels/CandidatePoolPanel.vue`

在 `tradingPoolEvaluation` computed 中：

```ts
const thesisCandidates = candidates.value
  .filter(entry => entry.tradeType === 'thesis')
  .map(entry => {
    const review = candidateJournalService.reanalyzeCandidate(entry)
    return {
      ...review.currentAnalysis.signalsSnapshot?.quote,
      code: entry.stockCode,
      name: entry.stockName,
      rankTrend: review.currentAnalysis.signalsSnapshot?.rankTrend ?? null,
    }
  })

// CandidatePoolPanel.vue <script setup> 新增 import
import { dataLayer } from '@/services/DataLayer'

const liveStocks = (dataLayer.getStocks() || [])
  .filter(stock => stock.rankTrend)  // 只纳入有 RankTrend 信号的
  .map(stock => ({
    code: stock.code,
    name: stock.name,
    rankTrend: stock.rankTrend,
    // 实时投影无 thesis 元数据，通过 rankTrend 直接读取信号
  }))

return analyzeTradingPoolCandidate({
  candidates: thesisCandidates,
  liveStocks,
  previousRows: previousTradingPoolRows.value,
})
```

#### 4.3 数据来源类型扩展

**文件**：`src/services/candidate/types.ts`

`TradingPoolSource` 新增：
```ts
type TradingPoolSource =
  | 'thesis'
  | 'jump_blocked_resonance'
  | 'live_projection'     // 新增
  | 'manual'
  | 'persisted'
  | 'unknown'
```

当前输出 source 仅使用 `thesis`、`live_projection`、`manual`、`persisted`、`unknown`；`jump_blocked_resonance` 只保留类型兼容，不再由 `resolveTradingPoolSource` 产出。旧输入 `candidate_auto_add` / `jump_blocked_resonance` 兼容归并为 `thesis`。

### 阶段 2：补全 UI 信息层

#### 4.4 DataTable Tooltip 信息分层（规格 9）

**文件**：`src/components/common/DataTable.vue`

`confidence` 列 tooltip 从当前的单一 Jump 置信度改为分层展示：

```
综合判断: 买入 (置信度: 87%)
Jump跃迁: 82.9%
共振评分: 21.9 分 (MACD金叉+3, Jump持有0, 连续+18.9)
交易池动作: 观察买点
```

实现方式：
- 读取 `stock.rankTrend.decision.final` 获取综合判断
- 读取 `stock.rankTrend.jump` 获取 Jump
- 读取 `stock.rankTrend.technical.signals` 计算 BuyVotes
- 读取交易池投影结果获取交易池动作

#### 4.5 候选池"强共振观察"分类（规格 6.2）

**文件**：`src/services/candidate/CandidatePoolStatusProjector.ts`

在候选池投影中新增 `'强共振观察'` 状态判定：
- `final.signal === 'buy'`
- `final.confidence >= 85`
- `BuyVotes >= 3`
- `jump.direction === 'buy'`
- `jump.confidence >= 80`
- 非 lifecyle veto
- MACD 非 death

满足以上条件但候选池严格入池未通过的，候选池 label 显示"强共振观察"。

#### 4.6 交易池面板信息补全（规格 8.2-8.4）

**文件**：`src/components/panels/CandidatePoolPanel.vue`

- **概览指标栏**：总数、观察买点、准备介入、已介入、已退出、信号过期（规格 8.1）
- **左侧列表**：搜索框（按代码/名称）、决策筛选下拉、状态筛选下拉
- **主表列**：来源、状态、综合置信度、Jump置信度、BuyVotes、MACD、风险标签、原因、操作
- **详情区**：信号矩阵（final/Jump/方向/加速度/零线/MACD）、风险矩阵、快照对比（入池 vs 当前）

### 4.7 实时投影边界说明

- **Jump 置信度回退**：实时投影行没有 `candidateEntryDecision`，无法走 `readGateCheckNumber` 回退路径。如果 `rankTrend.jump.confidence` 缺失，Jump 置信度为 null，交易池状态机将其视为缺少召回质量门槛，自动降为观察/过期链路，不会强制出池（符合规格 7.5）。
- **持久化策略**：实时投影行不持久化。面板关闭后，下次打开时根据当前 DataLayer 热榜数据重新生成。只有 thesis 来源和手工加入的交易池行才走 `CandidateJournalService` 持久化。

### 阶段 3：配置统一化（规格 7.0，已被统一合同收敛）

**文件**：`src/services/candidate/TradingPoolAnalysisService.ts` + `src/config/rankTrendLiveStrategyConfig.ts`

当前实现已将交易池评分阈值和连续权重放入 `rankTrendLiveStrategyConfig`。`analyzeTradingPoolCandidate` 只读默认配置的 `tradingPool.scoring` / `tradingPool.weights`，不接受 per-call 覆盖。旧单体字段保留兼容但不参与决策。

```ts
tradingPool: {
  scoring: { exitMax: 8, observeMin: 8, buyPointMin: 15, readyMin: 20, readyJumpMin: 80 },
  weights: { jumpConfidence: 2.0, finalConfidence: 1.5, directionConfidence: 1.0, accelerationConfidence: 1.0, zeroCrossConfidence: 0.5 },
  // deprecated compatibility fields
  recallJumpMin: 80,
  readyJumpMin: 85,
}
```

### 阶段 4：测试补齐

#### 4.7 新增测试用例

**文件**：`src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`

- `live_projection` 来源：实时投影股票正确标记 source
- 实时投影与 thesis 去重：同名 code thesis 优先
- DataLayer 裸 stock 输入（只有 rankTrend，无 candidateEntryDecision）
- 实时投影无 Jump 信号时的降级/观察链路

**文件**：`src/components/panels/__tests__/CandidatePoolPanel.test.ts`

- 交易池表格渲染实时投影行
- tooltip / 来源列显示 `live_projection`

## 5. 验收标准

实现后至少运行：

```powershell
# 交易池分析测试
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot

# 面板测试
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot

# RankTrend 回归
pnpm test:ranktrend

# 类型检查
pnpm typecheck:ranktrend
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

浏览器验证（Playwright）：
- 交易池面板在强情绪日至少展示 `live_projection` 来源的观察行
- DataTable tooltip 正确分层展示综合判断/Jump/共振/交易池动作
- 候选池 badge/babel 展示"强共振观察"状态

## 6. 影响范围

| 文件 | 改动类型 | 风险 |
|------|---------|------|
| `src/services/candidate/TradingPoolAnalysisService.ts` | 扩展输入接口 + 合并逻辑 | 低 — 新增可选字段，向后兼容 |
| `src/services/candidate/types.ts` | 新增联合类型成员 | 低 |
| `src/components/panels/CandidatePoolPanel.vue` | 新增 DataLayer 接入 + 面板补全 | 中 — 涉及 UI 渲染逻辑 |
| `src/components/common/DataTable.vue` | tooltip 分层 | 中 — 改动现有 tooltip |
| `src/services/candidate/CandidatePoolStatusProjector.ts` | 新增强共振观察 | 低 |
| `src/config/rankTrendLiveStrategyConfig.ts` | 新增交易池阈值预设 | 低 |
| 测试文件 | 新增用例 | 无风险 |

## 7. 回退策略

- 阶段 1 的 `liveStocks` 改为可选字段，传空数组即恢复旧行为
- UI 改动通过 feature flag（`liveStocks` 是否为空）自然控制
- 每个阶段独立可验证、独立可回退
