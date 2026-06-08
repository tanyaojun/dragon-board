# RankTrend Fusion 候选池统一语义——设计 & 实施计划审计报告

日期：2026-06-08 | 审计范围：设计规格 + 实施计划 | 审计结论：方向正确，但需先补齐与已落地代码的冲突面说明

## 审计对象

- **设计规格**：[2026-06-08-ranktrend-fusion-candidate-pool-unified-semantics-design.md](../specs/2026-06-08-ranktrend-fusion-candidate-pool-unified-semantics-design.md)
- **实施计划**：[2026-06-08-ranktrend-fusion-candidate-pool-unified-semantics-implementation-plan.md](2026-06-08-ranktrend-fusion-candidate-pool-unified-semantics-implementation-plan.md)

## 审计方法

1. 通读全部 33 个 Phase 的长测文档（`task_plan.md`、`findings.md`、`progress.md`），追溯 V2 四层框架设计、early_big_move V1→V2→V3 策略迭代、生命周期 A+B 融合的完整演进路径。
2. 通读两篇被取代的旧设计/计划文档。
3. 逐文件 grep/read 确认当前实际代码状态（`src/services/candidate/`、`src/services/rankTrend/`、`src/components/`）。
4. 以 `AGENTS.md`、`SKILLS.md`、`quant-board/docs/README.md`、`quant-board/docs/AI_COLLABORATION.md` 中记录的业务硬约束作为审计基线。

## 背景事实确认

经阅读全部长测文档 + 两篇被取代的旧设计/计划 + 当前实际代码状态，确认以下事实：

1. **旧生命周期分层买卖策略已被多轮长测证伪**：H1/H2/Q1 基线于 Phase 21 退役，旧本地 JSONL 记录已清空。

2. **`ranktrend_early_big_move_v3_lifecycle_fusion`** 是当前主线策略，经 Phase 22-33 的 V1→V2→V3→A+B 融合迭代，连续回测达到 `+31.00% / 65.79%`（run `bt_682d3abc164d4177`，`2026-04-01~2026-05-31`）。

3. **"替换方案"（旧 design `2026-06-08-ranktrend-fusion-candidate-pool-replacement-design.md`，对应 commit `385c4bd` + `3fdf8be`）已经落地**：

   | 文件 | 当前状态 | 旧方案中的职责 |
   |------|---------|--------------|
   | `CandidatePoolStatusProjector.ts` | **已存在** | 投影 `trade_journal.status` → 主表（未入池/观察/候选/已触发/跟踪中/已复盘） |
   | `fusionStrategy.ts` | **已存在** | `isFusionEntryCandidate()` 纯规则 helper |
   | `FusionCandidateNotifier.ts` | **已存在** | 命中 fusion 后自动建 `status=triggered` journal entry + 飞书推送 |
   | `liveV3SignalMapper.ts` | **已删除** | 旧 `【信号】` 列映射器 |
   | `DataTable.vue` | **已修改** | `jumpSignal` 列展示候选池 badge，点击打开候选池面板 |
   | `RankTrendSignalService.ts` | **已修改** | 接入 `fusionCandidateNotifier.process()` + `applyCandidatePoolStatus()` |

4. **`CandidateDiscoveryService.ts`** 仍存在于 `src/services/candidate/`，仍在 `CandidatePoolPanel.vue` 中被引用。

---

## Critical 问题（必须修复后才能实施）

### C1. 文档声称"已按审查意见修订/重写"，但未说明与已落地代码的冲突面

**问题：** 设计规格开头说"本方案取代 `2026-06-08-ranktrend-fusion-candidate-pool-replacement-design.md` 的 trade_journal 为主中心方向"，实施计划开头说"本计划已根据审查意见重写"。但两篇文档都没有明确列出哪些能力**已经通过旧方案落地**、哪些需要**回退/改写**、哪些是**纯新增**。

当前代码状态与统一语义方案目标状态的冲突矩阵：

| 文件 | 旧方案落地的当前职责 | 统一方案要求的新职责 | 冲突类型 |
|------|-------------------|-------------------|---------|
| `CandidatePoolStatusProjector.ts` | 投影 `trade_journal.status` → 主表字段 | 改为 `FusionStrategyProjection` → 主表字段 facade | **职责重写** |
| `FusionCandidateNotifier.ts` | 自动建 `status=triggered` journal entry + 飞书 | 降级为"只建壳 + 通知"，不再暗示 journal 是主真相 | **职责收窄** |
| `fusionStrategy.ts` | `isFusionEntryCandidate()`，被 notifier 调用 | `FusionStrategyProjector` 引用同名函数，但消费方不同 | **调用链变更** |
| `DataTable.vue` | `jumpSignal` 列展示 journal status badge | tooltip/badge/点击改为读 `FusionStrategyProjection` 字段 | **数据源替换** |
| `RankTrendSignalService.ts` | `rankTrend → notifier.process() → applyCandidatePoolStatus()` | `rankTrend → FusionStrategyProjector → 主表候选池字段` | **刷新链路替换** |

**建议修复：** 在设计规格第 1 节或实施计划第 0 节增加一个"**当前代码基线**"小节，逐文件列出旧方案已落地的实现 vs 统一方案的目标状态差异。否则执行 agent 会面对"同名文件存在但职责不同"的混淆——例如 `CandidatePoolStatusProjector.ts` 现在是 journal status 投影器，实施计划 Task 2.2 要把它改成 `FusionStrategyProjection` facade，这需要先理解当前实现才能安全改写。

### C2. `CandidatePoolStatusProjector` 存在两个互不兼容的合同定义

**问题：** 同一个文件名/模块名在两套方案中承担了不同的职责：

- **当前已落地的实现**：从 `CandidateJournalService.listCandidates()` 读取 journal entries，把 `status` 映射为 `未入池/观察/候选/已触发/跟踪中/已复盘`，写回 `stock.candidatePoolStatus/Label/EntryId/Source/UpdatedAt`。源码中 `STATUS_LABELS` 的 key 是 `CandidatePoolProjectedStatus = CandidateStatus | 'none'`，即 `none | observe | candidate | triggered | tracking | reviewed`。

- **统一语义方案要求**：读取 `FusionStrategyProjection`，把 `strategyState` 映射为 `未触发/待入场/策略持有中/策略退出观察/策略已关闭`，字段变为 `candidatePoolProjection`。新 `TABLE_LABELS` 的 key 是 `FusionStrategyState = 'idle' | 'triggered_wait_entry' | 'active_holding' | 'exit_signaled' | 'closed'`。

这两个合同的状态值域完全不同（journal workflow 态 vs 策略生命周期态），字段 shape 也不同。实施计划 Task 2.2 的代码骨架里写了 `stock.candidatePoolStatus = projection?.strategyState || 'idle'` 和 `stock.candidatePoolLabel = TABLE_LABELS[stock.candidatePoolStatus]`——这里 `candidatePoolStatus` 的类型从 `CandidateStatus | 'none'` 变成了 `FusionStrategyState`，但代码骨架没有展示旧 `STATUS_LABELS` 的定义替换。

**建议修复：** 在实施计划 Task 2.2 中增加显式的"**先删除旧投影逻辑，再实现新投影逻辑**"分步说明。具体包括：
- 删除现有 `STATUS_LABELS`（journal workflow 态 → 中文映射表）。
- 新增 `TABLE_LABELS: Record<FusionStrategyState, string>`（策略态 → 中文映射表）。
- 新增 `candidatePoolProjection` 字段挂载到 stock。
- 明确旧的 `candidatePoolSource / candidatePoolUpdatedAt` 等字段在新方案中是否保留（建议：`candidatePoolSource` 改为从 `projection.projectionSource` 取值；`candidatePoolUpdatedAt` 改为从 `projection.frameTime` 取值）。

### C3. `FusionStrategyProjection` 类型在 live 模式下包含不可用字段，缺乏模式区分

**问题：** 设计规格第 5 节定义的 `FusionStrategyProjection` 包含 `strategyEntryPrice / strategyExitPrice / strategyReturnPct / holdingBars / slotIndex / maxPositions` 等字段。这些字段在历史/回测模式下可以来自 `backtest_signals` / `backtest_trades`，但在实时/盘中模式下没有可靠数据源。

设计规格自身也承认这一点——Phase 3 实施建议说"若 live 模式暂时缺少可靠持仓事实源，第一版允许只准确落地 `idle / triggered_wait_entry`，不允许用 `trade_journal` 伪造 `active_holding / closed`"——但类型系统没有区分两种模式下的字段可用性。

实施计划 Phase 2 的 `buildFusionStrategyProjection()` 实现已经体现了这一点：只在 `lifecycle` 输入存在时才填 `entryAt / exitAt / holdingBars` 等。但类型层面没有对应的区分，调用方无法通过类型系统知道哪些字段在 live 模式下预期为 `undefined`。

**建议修复：** 在设计规格中增补一个"**live 模式字段可用性矩阵**"，标明哪些字段在 live 模式下预期为空/不展示。或者在 `FusionStrategyProjection` 的类型注释中对来自策略持仓事实层的字段标注"回测模式专属 / live 模式为空"。

| 字段 | 历史/回测模式 | 实时/盘中模式 |
|------|------------|------------|
| `strategyState` | 来自 lifecycle segment | `idle` 或 `triggered_wait_entry`（除非有可靠 live 持仓源） |
| `strategyEntryAt` | 来自 trade/signal 时间轴 | 空 |
| `strategyExitAt` | 来自 trade/signal 时间轴 | 空 |
| `strategyEntryPrice` | 来自 trade 成交价 | 空 |
| `strategyExitPrice` | 来自 trade 成交价 | 空 |
| `strategyReturnPct` | 计算值 | 空 |
| `holdingBars` | 计算值 | 空 |
| `slotIndex / maxPositions` | 来自持仓路径 | 空 |

---

## Important 问题（建议修复，可在 Phase 1 前解决）

### I1. `CandidateDiscoveryService` 的处置方式不明确

**问题：** 设计规格 6.4 节和 9.2 节说 `CandidateDiscoveryService` "从主候选池领域移除"，"不再出现在主候选池面板中心链路"。实施计划 File Map 说 "Modify: 从主候选池链路移除"。但都没有说明：
- 是删除源文件？保留文件但不再被 import？改为独立入口？
- 当前代码里 `CandidatePoolPanel.vue` 仍在引用 `CandidateDiscoveryService`——这个引用如何处理？删除 import 后页面上的对应区域用什么替代？

当前 `CandidatePoolPanel.vue` 对 `CandidateDiscoveryService` 的引用（经 grep 确认）：

```text
src/components/panels/CandidatePoolPanel.vue
src/services/candidate/CandidateDiscoveryService.ts
src/services/candidate/__tests__/CandidateDiscoveryService.test.ts
```

**建议修复：** 在实施计划 Task 3.2 中明确：
- 删除 `CandidatePoolPanel.vue` 中对 `CandidateDiscoveryService` 的 import 和调用。
- **不删除** `CandidateDiscoveryService.ts` 源文件，保留为独立模块供未来可能的"人工观察池"场景使用。
- 不删除对应的测试文件，但确认测试不再被 import 到主面板测试中。

### I2. 设计规格的 `candidateTier` 来源与当前实现存在合同漂移

**问题：** 设计规格第 5 节的 `FusionStrategyProjection` 将 `candidateTier` 列为策略投影的核心字段。但长测审计文档（Phase 31/33）已经明确指出：Python 回测的 `compose_strategy()` 与 TS 的 `composeCandidateTier()` 在候选分层输入上存在合同漂移——Python 更多依赖 `hotlistSentiment`，TS 使用 `market_regime`。

如果 `FusionStrategyProjector` 的 live 端直接从 `stock.rankTrend.strategy.candidateTier`（TS 输出）取值，而历史 projection 来自 Python 回测 `backtest_signals.candidateTier`（Python 输出），这两个值在 TS/Python golden 对齐尚未完成前可能不是同一个语义。

**建议修复：** 在设计规格中增加一条说明：

> live projection 的 `candidateTier` 来源是 TS 端 `composeCandidateTier()` 的输出；历史 projection 的 `candidateTier` 来源是 Python 回测 `compose_strategy()` 的输出。两者的对齐状态以 `ranktrend-golden.md` 的当前验证结果为准。若存在漂移，应标记为已知风险，不阻塞候选池面板统一语义上线，但必须在报告/诊断中标注来源差异。

### I3. 实施计划 Task 1.2 的失败测试对 `executionOverlay` 的约束覆盖不足

**问题：** 实施计划 Task 1.2 写了一个失败测试：当 `executionOverlay.executed=true` 且有 `entryTime / entryPrice` 但 `strategyLifecycle.hasOpenPosition=false` 时，`strategyState` 仍应为 `triggered_wait_entry`。这个测试覆盖了"不能从 execution 反推 holding"这一条约束，但没有覆盖其他反推路径：

- `executionOverlay.exitTime` 存在但策略层未确认关闭 → 不应反推 `closed`
- `executionOverlay` 存在且 `status=tracking` → 不应反推 `active_holding`

设计规格 5.2 节明确写了这两条约束，但测试只锁了一条。

**建议修复：** 在 Task 1.2 中至少增加第二个测试 case：

```ts
it('does not infer closed from execution exitTime when strategy lifecycle has not confirmed closure', () => {
  const projection = buildFusionStrategyProjection({
    stock: createFusionStock('600001'),
    snapshotType: 'half_hour',
    tradingDate: '2026-06-08',
    snapshotId: 'snap-1',
    frameTime: '2026-06-08T10:00:00+08:00',
    strategyLifecycle: {
      triggered: true,
      hasOpenPosition: true,
      closed: false,
    },
    executionOverlay: {
      executed: true,
      entryTime: '2026-06-07T10:30:00+08:00',
      entryPrice: 12.5,
      exitTime: '2026-06-08T09:30:00+08:00',
      exitPrice: 11.8,
    },
  })

  // 策略层未确认关闭，即使 execution overlay 有 exitTime 也不能是 closed
  expect(projection.strategyState).toBe('active_holding')
})
```

实施计划 Phase 2 的 `buildFusionStrategyProjection()` 实现骨架已经正确处理了这一点（先判断 lifecycle，后判断 execution），但测试应显式锁住。

### I4. 实施计划 Task 2.2 对 `DataTable.vue` 的改动范围不完整

**问题：** 实施计划 Task 2.2 说 `jumpSignal` 列 tooltip / badge / 点击行为全部改读 projection 字段。但当前 `DataTable.vue` 的候选池点击行为（`openCandidatePoolFromCell`）依赖 `stock.candidatePoolEntryId`（journal entry ID）来定位候选池面板中的对应条目。改成 `FusionStrategyProjection` 后，`candidatePoolEntryId` 不再直接可用——需要从 `executionOverlay` 中反查对应的 journal entry，或者改为按 `stockCode` 定位候选池面板。

**建议修复：** 在 Task 2.2 中增加一步：

> 修改 `openCandidatePoolFromCell` 的定位逻辑：若 `projection.executionOverlay` 存在且有关联的 journal entry ID，优先按 entry ID 定位；否则按 `stock.code` 打开候选池面板并滚动到对应股票的条目。

### I5. 文档同步清单遗漏 `AI_COLLABORATION.md`

**问题：** 实施计划 Task 5.4 的文档同步列表只有 `api-cli.md` 和 `frontend.md`。但 `quant-board/docs/AI_COLLABORATION.md` 中存在以下与本次改动直接相关的描述：

- 第 25 行：`trade_journal` 集合的当前定位说明。
- 第 38 行：Layer 3 实盘对齐（"候选池 trade_journal 执行记录"）。
- 第 47 行：候选池面板的执行记录区域。

当 `trade_journal` 降级为 execution overlay、主表从 journal workflow 态切换到策略态后，这些描述需要同步更新。

**建议修复：** 在 Task 5.4 和 File Map 中增加 `quant-board/docs/AI_COLLABORATION.md`。具体修改点：
- 将 `trade_journal` 的描述从"候选池执行记录主表"更新为"execution overlay，只表达人工实际执行与复盘"。
- 在 Layer 3 描述中标注"对齐报告的标的来自 FusionStrategyProjection 的策略态投影"。

### I6. 实施计划缺失对 `RankTrendSignalService` 现有调用链的变更说明

**问题：** 当前 `RankTrendSignalService.refreshRankTrendSignals()` 的链路（经 grep 确认）是：

```text
updateStockSignals → applyJumpSignals → fusionCandidateNotifier.process() → applyCandidatePoolStatus()
```

统一方案要求的链路是：

```text
rankTrend → FusionStrategyProjector → 主表候选池字段
```

实施计划 Task 2.2 列出要修改 `RankTrendSignalService.ts`，但没有说明：
- 是否删除 `applyCandidatePoolStatus()` 调用？
- 是否删除 `fusionCandidateNotifier.process()` 调用？（设计规格说 notifier 降级为"只建壳+通知"——建壳仍需调 journal API，但主表状态不再从 journal 读。那么 notifier.process() 是否仍保留在刷新链路中？）
- 新的 `FusionStrategyProjector.buildFusionStrategyProjection()` 应该插在刷新链路的哪个位置？

**建议修复：** 在 Task 2.2 中增加刷新链路的前后对比伪代码：

```ts
// --- 旧链路（替换方案落地的）---
async refreshRankTrendSignals() {
  const updates = this.rankTrendAnalyzer.analyze(/* ... */)
  const mergedStocks = this.updateStockSignals(updates)
  this.applyJumpSignals(mergedStocks)
  await this.fusionCandidateNotifier.process(mergedStocks)  // 自动建 journal entry
  await applyCandidatePoolStatus(mergedStocks)               // 从 journal 读状态投影到 stock
  return mergedStocks
}

// --- 新链路（统一语义方案）---
async refreshRankTrendSignals() {
  const updates = this.rankTrendAnalyzer.analyze(/* ... */)
  const mergedStocks = this.updateStockSignals(updates)
  this.applyJumpSignals(mergedStocks)
  await this.fusionCandidateNotifier.process(mergedStocks)    // 保留：建壳 + 通知（只写不读）
  const projections = this.fusionProjector.buildProjections(mergedStocks, /* ... */)
  this.projectorFacade.applyToStocks(mergedStocks, projections) // 新增：策略态 → 主表字段
  return mergedStocks
}
```

---

## Minor 问题（可在实施中顺带解决）

### M1. 设计规格第 5 节缺少 live 模式 `projectionSource` 的具体来源说明

类型定义了 `projectionSource: 'live' | 'backtest'`，但没有说明 live 模式下这个值的具体判定逻辑——是从 DataLayer 的运行模式取？从 websocket 连接状态判断？还是由调用方显式传入？

### M2. 实施计划 Phase 2 的 `buildFusionStrategyProjection()` 引用了 `isFusionEntryCandidate(stock)` 但未列出 import 来源

代码骨架里写了 `const baseTriggered = lifecycle?.triggered ?? isFusionEntryCandidate(input.stock)`，但 `isFusionEntryCandidate` 定义在 `fusionStrategy.ts`（旧方案创建的文件）。实施计划 File Map 没有把 `fusionStrategy.ts` 列为依赖，也没有说明是否复用现有的 `isFusionEntryCandidate` 还是需要修改其逻辑。

**建议：** 在 File Map 中增加 `fusionStrategy.ts` 为隐式依赖，或在 Task 2.1 中注明"复用 `src/services/rankTrend/fusionStrategy.ts` 的 `isFusionEntryCandidate()` 作为 base gate 判断，不新增重复逻辑"。

### M3. 设计规格 11.1 节"刻意做出的取舍"中缺少一条关键取舍

应该增加：

> 不保留旧 `candidatePoolStatus` 字段（journal workflow 态：`none/observe/candidate/triggered/tracking/reviewed`）作为主表后备展示。一旦主表切到 `FusionStrategyProjection.strategyState`，就不再能回退到 journal workflow 态标签。如果 fusion 策略在某个时段不可用（如策略版本切换），主表将统一展示 `idle`（未触发），而不是回退到 journal 状态。

### M4. 两个 `CandidatePoolStatusProjector` 的测试文件处理不够清晰

旧方案创建了 `src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts`，里面的测试 case 围绕 journal status 投影（例如 `projectCandidatePoolStatus` 的入参是 `CandidateJournalEntry[]`）。统一方案要把它改成测试 `FusionStrategyProjection` facade——入参变为 `FusionStrategyProjection[]`，断言的状态值域从 `triggered/tracking/reviewed` 变为 `triggered_wait_entry/active_holding/closed`。

实施计划 Task 2.2 只说 "Modify" 测试文件，但没有说明旧的测试 case 是删除还是重写。

**建议：** 在 Task 2.2 中增加一句"删除旧的 journal status 投影测试 case，替换为 FusionStrategyProjection facade 测试 case"。

### M5. `FusionCandidateNotifier` 的飞书推送逻辑的去留

当前 `FusionCandidateNotifier.ts`（经 read 确认，108 行）包含完整的飞书推送逻辑（`pushFeishuEvent`），向 `/api/notifications/jump-signal` 发送 POST 请求。实施计划 Task 4.2 说降级为"自动建壳 + 通知器"，但没有明确飞书推送是保留、删除还是改为发 candidate pool 事件而不是 jump signal 事件。

注意 git log 中有 `59281a9 fix: disable legacy jump feishu notification flow`——说明飞书推送链路近期已经被改动过，可能存在多个通知路径的冲突。

**建议：** 在 Task 4.2 中增加一句：

> 飞书推送保留，但内容从"jump signal 命中"改为"fusion 策略候选池触发"，推送 event 中增加 `candidateTier`、`lifecycleAction` 字段，移除对旧 `signalType/label` 的依赖。

### M6. 实施计划 Phase 3 的移除清单与当前 `CandidatePoolPanel.vue` 实际 UI 区域的对齐

设计规格 7.4 节列了六个要移除的模块（建议入池、发现推荐列表、候选质量、候选漏斗、双评分中心结构、通用候选研究统计视图）。实施计划 Task 3.1 的测试骨架断言了前五个字符串的否定匹配。但设计规格还有一个"候选研究，不含交易盈亏"统计视图——这个在测试骨架中没有对应的否定断言。

**建议：** 在 Task 3.1 的测试骨架中补充 `expect(source).not.toContain('不含交易盈亏')` 或等价断言。

---

## 总体评价

### 设计规格

**正确之处：**
- 核心问题识别准确：三套语义（journal status、CandidateAnalysis、fusion auto-entry）互相打架，`trade_journal` 倒置了策略事实和人工执行事实的关系。
- `FusionStrategyProjection` 模型设计方向正确，明确分离了策略事实层和人工执行层。
- 状态来源硬约束（5.2 节）是全文最有价值的部分——它显式禁止了 execution overlay 反推策略状态这条最容易出错的路径。
- Golden 边界声明（4.1 节）严格不触碰项目全局 golden，只锁定候选池语义层。
- 非目标（3 节）和风险取舍（11 节）写得到位，不夸大承诺。

**不足之处：**
- 缺少与已落地代码的显式 diff（见 C1/C2）。
- `FusionStrategyProjection` 类型缺少 live/backtest 模式区分（见 C3）。
- `candidateTier` 的跨语言来源一致性风险未标注（见 I2）。

### 实施计划

**正确之处：**
- Section 0 "实施前必须锁定的口径"是一个好的防御性设计，五条原则全部正确。
- TDD 节奏合理：Phase 1 先写失败测试锁合同 → Phase 2 最小实现 → Phase 3/4 重构 → Phase 5 补历史 API。
- Phase 5 的历史 projection 约束（禁止 `trade_by_code` 折叠、要求按 lifecycle segment 构建）与长测 Phase 33 的教训一致——这是从真实踩坑中提炼出的正确约束。
- 分阶段执行顺序（Phase 1+2 先 → Phase 3+4 再 → Phase 5 最后）的依赖关系合理。
- Verification 章节的验证命令准确。

**不足之处：**
- 没有与已落地代码的显式 diff 章节（见 C1）。
- File Map 中标记为 "Create" 的文件（`FusionStrategyProjector.ts`、`FusionStrategyProjector.test.ts`、`fusion_strategy_projection_service.py` 等）确实不存在，可以创建；但标记为 "Modify" 的文件中有多个已由旧方案创建/修改，需要先理解当前实现才能安全改写（见 C2、I6）。
- 文档同步清单遗漏 `AI_COLLABORATION.md`（见 I5）。

### 总评

两篇文档共享一个结构性问题：它们都声称"取代"旧方案，但没有做与已落地代码的显式 diff。五个关键文件（`CandidatePoolStatusProjector.ts`、`FusionCandidateNotifier.ts`、`fusionStrategy.ts`、`DataTable.vue`、`RankTrendSignalService.ts`）已经通过旧方案被修改/创建，统一方案需要在这些文件上做二次手术。当前文档对此只字未提，执行 agent 看到 File Map 中 "Create: FusionCandidateNotifier.ts"（实际已存在）或 "Modify: CandidatePoolStatusProjector.ts"（但不了解当前实现）时会做出错误判断。

**最小修复方案：** 在实施计划中增加一个 "0.1 Pre-condition: Current Code Baseline" 小节（约 30 行），逐文件列出当前状态 vs 目标状态，然后进入 Phase 1。这是最小的修复成本，但能避免实施阶段的大量返工。具体格式建议：

```markdown
### 0.1 当前代码基线（2026-06-08，commit 3fdf8be 之后）

以下文件已由 `2026-06-08-ranktrend-fusion-candidate-pool-replacement-design.md` 方案落地，本计划将在其基础上改写：

| 文件 | 旧方案落地的职责 | 本计划的目标职责 | 操作类型 |
|------|----------------|----------------|---------|
| CandidatePoolStatusProjector.ts | journal status → 主表标签 | FusionStrategyProjection → 主表 facade | **重写** |
| FusionCandidateNotifier.ts | 自动建 journal entry + 飞书 | 建壳 + 通知（只写不读） | **收窄** |
| fusionStrategy.ts | isFusionEntryCandidate() | 不变，但消费方从 notifier 变为 FusionStrategyProjector | **保留+引用变更** |
| DataTable.vue | 展示 journal status badge | 展示 strategyState badge + projection tooltip | **数据源替换** |
| RankTrendSignalService.ts | notifier.process() + applyCandidatePoolStatus() | notifier.process() + FusionStrategyProjector + 新 facade | **链路改写** |

以下文件为本次纯新增：

| 文件 | 职责 |
|------|------|
| src/types/fusionStrategyProjection.ts | FusionStrategyProjection 类型合同 |
| src/services/rankTrend/FusionStrategyProjector.ts | live projection 主入口 |
| quant-board/backend/services/fusion_strategy_projection_service.py | 历史 projection 构建 |
| quant-board/backend/api/fusion_strategy_projection_routes.py | 历史 projection API |
```

---

## 审计结论

**设计规格：通过，带 3 个 Critical 条件。** 方向正确，核心模型合理。但必须在实施前补齐：(1) 与已落地代码的差异说明；(2) `CandidatePoolStatusProjector` 新旧合同的显式切割方案；(3) live/backtest 模式字段可用性矩阵。

**实施计划：通过，带 3 个 Critical 条件。** TDD 节奏和分阶段策略合理。但必须在实施前补齐：(1) 当前代码基线小节；(2) `CandidatePoolStatusProjector` 的重写分步说明；(3) `RankTrendSignalService` 刷新链路的前后对比。

C1（代码基线缺失）是两份文档的共同根因——修复这一个问题即可连带解决 C2、I1、I6、M2、M4、M5 的大部分执行歧义。建议优先修复 C1，其他问题可以在进入对应 Phase 时逐条对照解决。
