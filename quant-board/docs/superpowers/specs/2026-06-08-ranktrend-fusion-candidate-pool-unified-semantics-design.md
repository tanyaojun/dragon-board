# RankTrend Fusion 候选池统一语义——设计规格

日期：2026-06-08 | 状态：已按审查意见修订，待实施

> 本方案取代 `2026-06-08-ranktrend-fusion-candidate-pool-replacement-design.md` 的“`trade_journal + 候选池状态` 为主中心”方向。
> 这里的“唯一 Golden”仅指**候选池语义层**，不改写 QuantBoard / Dragon Board 全局口径中“TypeScript `rankTrend` 链仍是项目 golden 标准”的事实。

## 1. 背景与结论

当前 Dragon Board 的【候选池】链路存在三套互相打架的语义：

1. 主表【候选池】字段展示的是 `trade_journal.status` 投影。
2. 候选池面板主体是 `CandidateJournalService + CandidateAnalysisService` 驱动的“通用候选工作台”。
3. 自动入池又来自 `ranktrend_early_big_move_v3_lifecycle_fusion` 主线策略命中。

这三套语义并不等价。

真正的问题不是文案，而是系统把“策略事实”和“人工执行事实”倒置了：

- 现在是 `trade_journal` 在定义什么是候选池；
- 正确方向应该是 `ranktrend_early_big_move_v3_lifecycle_fusion` 在定义什么是候选池；
- `trade_journal` 只负责补充“人后来怎么执行和复盘”。

因此，本次设计不是修补现有候选池面板，而是重建主语义。

### 1.1 当前代码基线（2026-06-08，`3fdf8be` 之后）

以下文件已经由旧 replacement 方案落地，本设计是在这些实现之上做语义重构，不是从空白状态开始：

| 文件 | 当前已落地职责 | 统一语义目标职责 | 冲突类型 |
| --- | --- | --- | --- |
| `CandidatePoolStatusProjector.ts` | `trade_journal.status -> 主表标签` | `FusionStrategyProjection -> 主表字段 facade` | 职责重写 |
| `FusionCandidateNotifier.ts` | 自动建 `status=triggered` journal entry + 飞书 | 建壳 + 通知，不再暗示 journal 是主真相 | 职责收窄 |
| `fusionStrategy.ts` | `isFusionEntryCandidate()` 纯规则 helper | 保留，被 `FusionStrategyProjector` 复用 | 调用链变更 |
| `DataTable.vue` | 展示 journal workflow 态 badge | 展示 strategyState badge + projection tooltip | 数据源替换 |
| `RankTrendSignalService.ts` | `notifier.process() + applyCandidatePoolStatus()` | `notifier.process() + FusionStrategyProjector + 新 facade` | 刷新链路替换 |
| `CandidatePoolPanel.vue` | 通用候选研究台 | fusion 生命周期工作台 | 信息架构重构 |

## 2. 目标

1. 以 `ranktrend_early_big_move_v3_lifecycle_fusion` 作为**候选池语义层**唯一策略锚点。
2. 用统一的策略投影模型表达：
   - 是否已触发
   - 是否进入策略持有
   - 是否进入退出观察
   - 是否策略关闭
   - 持有 bars
   - 仓位占用
   - 退出原因
3. 主表【候选池】字段改成“策略态投影”，不再显示 `trade_journal` 工作流态。
4. 候选池面板重做为“fusion 主线策略池工作台”，但保留人工录入执行与复盘的入口。
5. `trade_journal` 降级为 execution overlay，只表达人工实际执行、偏差和复盘。

## 3. 非目标

- 不改写 QuantBoard / Dragon Board 全局 golden 定义。
- 不让 `CandidateDiscoveryService` 继续作为主候选池面板入口。
- 不继续把 `CandidateAnalysisService` 的评分/等级作为主状态来源。
- 不让主表继续承担“实时买卖信号解释器”职责。
- 不用人工执行记录去反向推断策略是否持有、是否退出。

## 4. 候选池语义 Golden 与主事实源

### 4.1 Golden 边界

项目全局口径保持不变：

- `src/services/RankTrendAnalyzer.ts`
- `src/services/rankTrend/**`
- `src/types/rankTrendDefaults.ts`

仍然是 QuantBoard Python 迁移与对齐的 golden 标准。

本设计新增的是一个更窄的约束：

```text
候选池语义层的唯一策略锚点 = ranktrend_early_big_move_v3_lifecycle_fusion
```

也就是说，主表【候选池】和候选池面板不再由 `trade_journal.status`、`CandidateDiscoveryService` 或 `CandidateAnalysisService.suggestedStatus` 定义，而统一围绕 fusion 主线策略解释。

### 4.2 主事实源

主事实源分两种，但输出必须同构：

1. 历史 / 回测模式
   - 来源：QuantBoard `backtest_signals`、`backtest_trades`、必要时补充 `tradeEvents / openPositions / lifecycle segments`
   - 含义：在既定样本上，fusion 策略实际如何触发、入场、持有、退出

2. 实时 / 盘中模式
   - 来源：当前 live snapshots 上复用同一套 fusion 规则做 projection
   - 含义：在当前时点，fusion 策略此刻处于哪一步

不允许再出现“历史看一套状态、实时再额外发明一套前端状态对象”的情况。

## 5. 统一策略投影模型

系统新增一个主语义模型：

```ts
type FusionSnapshotType = 'half_hour' | 'quarter_hour'

interface FusionStrategyProjection {
  stockCode: string
  stockName: string

  strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion'
  snapshotType: FusionSnapshotType
  tradingDate: string
  snapshotId: string
  frameTime: string
  projectionSource: 'live' | 'backtest'

  strategyState:
    | 'idle'
    | 'triggered_wait_entry'
    | 'active_holding'
    | 'exit_signaled'
    | 'closed'

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

  executionOverlay?: {
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
  } | null
}
```

### 5.1 这层模型要解决的问题

它用来明确表达这些事实，而这些事实在旧 `trade_journal + candidateAnalysis` 体系里都不是一等公民：

1. 候选与持仓不是一回事。
2. 策略时间轴与人工执行时间轴不是一回事。
3. `holdingBars` 是主线策略核心字段，不是附属计算值。
4. `slotIndex / maxPositions` 只有在策略路径级仓位事实存在时才能展示，不能靠人工记录猜。
5. 退出原因必须结构化，不能只留自然语言备注。

### 5.2 状态来源硬约束

`strategyState` 的来源必须满足以下约束：

1. `triggered_wait_entry`
   - 来自 fusion 入场条件命中
   - 不要求人工已成交

2. `active_holding`
   - 来自策略事实层确认“该路径存在未关闭持仓”
   - 可以来自回测 trade / lifecycle segment
   - live 模式必须来自专门的策略持仓投影，不得由 `trade_journal.entryTime` 反推

3. `exit_signaled`
   - 来自策略事实层确认“已进入退出观察或退出条件成立，但策略持仓段尚未关闭”
   - 不得用“人工写了卖出计划”代替

4. `closed`
   - 来自策略事实层确认“该策略路径已关闭”
   - 历史模式可来自 backtest 闭环交易
   - live 模式若尚无可靠主事实源，第一版宁可不展示，也不能拿 `trade_journal.exitTime` 伪装成策略关闭

5. `executionOverlay`
   - 永远只表达“人后来怎么做”
   - 不能反向决定上述四类策略状态

### 5.3 live / backtest 字段可用性矩阵

`FusionStrategyProjection` 是统一 view model，但不代表 live 与 backtest 模式下所有字段同时可用。

| 字段 | 历史 / 回测模式 | 实时 / 盘中模式 |
| --- | --- | --- |
| `strategyState` | 来自 lifecycle segment / trade 闭环 | 至少保证 `idle / triggered_wait_entry`；若无可靠持仓事实源，不强行给出完整持仓态 |
| `strategyEntryAt` | 来自 trade / signal 时间轴 | 无可靠 live 持仓事实源时为空 |
| `strategyExitAt` | 来自 trade / signal 时间轴 | 无可靠 live 持仓事实源时为空 |
| `strategyEntryPrice` | 来自 trade 成交价 | 通常为空 |
| `strategyExitPrice` | 来自 trade 成交价 | 通常为空 |
| `strategyReturnPct` | 可计算 | 通常为空 |
| `holdingBars` | 可计算 | 无可靠持仓事实源时为空 |
| `slotIndex / maxPositions` | 来自持仓路径 | 无路径级事实源时为空 |

因此，前端不得把这些字段视为“live 模式一定有值”的强合同。

### 5.4 `candidateTier` 的跨语言来源说明

`candidateTier` 在历史 / 实时两条链路上的来源不同：

- live projection：来自 Dragon Board TypeScript 端 `composeCandidateTier()` / `stock.rankTrend.strategy.candidateTier`
- backtest projection：来自 QuantBoard Python 端 `compose_strategy()` / 回测输出字段

两者的对齐状态以 `quant-board/docs/ranktrend-golden.md` 的当前验证结果为准。若某一阶段仍存在 TS / Python 漂移，这属于已知风险，不阻塞候选池统一语义上线，但必须在诊断 / 报告中标注来源差异。

## 6. 语义边界重定义

### 6.1 主表【候选池】

主表只读 `FusionStrategyProjection`。

禁止再直接消费：

- `CandidateJournalEntry.status`
- `CandidateAnalysisResult.suggestedStatus`
- `CandidateDiscoveryRecommendation`

主表状态映射如下：

- `idle` → `未触发`
- `triggered_wait_entry` → `待入场`
- `active_holding` → `策略持有中`
- `exit_signaled` → `策略退出观察`
- `closed` → `策略已关闭`

主表 tooltip 至少展示：

- 当前策略状态
- 首次触发时间
- 策略入场时间
- 已持有 bars
- 候选层级
- 生命周期动作
- 退出原因
- 仓位槽位 / 最大持仓
- 若存在执行 overlay，再补充实际执行偏差

### 6.2 候选池面板

候选池面板改成 `fusion 主线策略池工作台`。

它不再是“通用候选研究台”，也不再以“当前重分析 vs 入池快照评分”作为主体。

但它仍需保留三类人工操作入口：

1. 假设编辑
2. 执行记录录入
3. 对齐复盘保存

原因很简单：`trade_journal` 虽然降级为 overlay，但它仍然是人工执行与复盘事实的正式写口。

### 6.3 trade_journal

`trade_journal` 的新定位：

- 不是主策略状态源
- 不是主表候选池状态源
- 只负责保存人工实际执行与复盘
- 只作为 `FusionStrategyProjection.executionOverlay` 的来源

### 6.4 CandidateAnalysis / CandidateDiscovery

`CandidateAnalysisService` 与 `CandidateDiscoveryService` 不再定义主候选池语义。

它们要么：

- 降级为辅助解释模块；
- 要么拆成独立“人工观察池”能力；

但不能继续出现在主候选池面板中心链路里。

这里的“移除”指的是：

- 从 `CandidatePoolPanel.vue` 主链路移除 import / 调用 / UI 区域；
- 不要求第一版立即删除 `CandidateDiscoveryService.ts` 源文件；
- 独立模块和测试文件可以保留，供未来“人工观察池”场景复用。

## 7. 候选池面板新信息架构

### 7.1 左侧列表

列表按策略生命周期分组，而不是按候选评分分组：

1. `待入场`
2. `持有中`
3. `已退出待复盘`
4. `已完成`

排序主键优先级：

1. 策略状态优先级
2. 触发时间
3. 当前持有 bars
4. 当前仓位占用 / 风险摘要

### 7.2 中央主详情：策略事实卡

主详情以策略事实为中心，展示：

- 当前策略状态
- 首次触发时间
- 策略入场时间
- 策略退出时间
- 当前持有 bars
- 候选层级
- 生命周期动作
- 退出原因
- 当前是否仍占用仓位槽位

### 7.3 右侧辅助区

右侧只保留两块主内容，但允许带保存操作：

1. `执行事实`
   - 实际买卖时间
   - 实际买卖价格
   - 实际仓位
   - 止损止盈线

2. `对齐复盘`
   - 是否按策略执行
   - 提前 / 延后多少 bars
   - 错过 / 追高 / 卖早 / 卖晚
   - 复盘结论

### 7.4 从主面板中剔除的模块

以下模块从主候选池面板彻底移除：

- `建议入池`
- `CandidateDiscoveryService` 推荐列表
- `候选质量`
- `候选漏斗`
- `当前重分析 / 入池快照` 双评分中心结构
- `候选研究，不含交易盈亏` 这类以通用候选研究为主的统计视图

## 8. 主表与面板的统一数据流

新的统一链路：

```text
live frames / backtest artifacts
  -> ranktrend_early_big_move_v3_lifecycle_fusion
  -> strategy lifecycle facts
  -> FusionStrategyProjection
  -> 主表【候选池】字段
  -> 候选池面板主详情
  -> trade_journal execution overlay
```

废弃的旧链路：

```text
rankTrend
  -> addCandidateFromStock
  -> trade_journal.status
  -> CandidateAnalysis reanalyze
  -> 主表/面板各自拼解释
```

## 9. 旧代码的去留

### 9.1 降级为辅助解释

- `CandidateJournalService.reanalyzeCandidate()`
- `CandidateAnalysisService`

这些模块以后最多只服务“辅助解释卡片”，不能再决定主状态、主排序、主统计。

### 9.2 从主候选池领域移除

- `CandidateDiscoveryService`
- `建议入池`
- `人工观察型通用候选推荐`

### 9.3 必须重写职责

- `CandidatePoolStatusProjector`
  - 现状：`trade_journal` 状态投影器
  - 目标：`FusionStrategyProjection -> 主表字段 facade`

- `FusionCandidateNotifier`
  - 现状：命中后写入 `trade_journal`
  - 目标：只负责自动建壳 / 通知，不能再暗示 `trade_journal` 是主状态真相

- `CandidatePoolPanel`
  - 现状：通用候选研究台
  - 目标：fusion 生命周期工作台 + overlay 录入面板

## 10. 分阶段实施建议

### Phase 1：语义收口

1. 新增 `FusionStrategyProjection` 合同与 projector 层。
2. 主表【候选池】改读 projection，而不是 journal status。
3. 保留 `trade_journal`，但只作为 execution overlay。

### Phase 2：面板重构

1. 候选池面板改成策略池视图。
2. 删除 `建议入池 / 候选质量 / 候选漏斗 / 双评分中心`。
3. 改成“策略事实 + 执行事实 + 对齐复盘”。
4. 保留 `假设编辑 / 执行记录 / 复盘保存` 的正式录入能力。

### Phase 3：历史与实时对齐

1. 历史视图对接 QuantBoard 回测结果投影。
2. 实时视图对接同构的 live projection。
3. 保证历史 / 实时共享同一个 view model。
4. 若 live 模式暂时缺少可靠持仓事实源，第一版允许只准确落地 `idle / triggered_wait_entry`，不允许用 `trade_journal` 伪造 `active_holding / closed`。

## 11. 风险与明确取舍

### 11.1 本方案刻意做出的取舍

- 不追求兼容现有“通用候选研究台”心智模型。
- 不保留 discovery 在主候选池面板中的位置。
- 不继续让 `trade_journal.status` 承担主状态真相。
- 不在第一版为求完整而让人工执行记录反向定义策略持仓状态。
- 不保留旧 `candidatePoolStatus = none / observe / candidate / triggered / tracking / reviewed` 作为主表后备展示。一旦主表切到 `FusionStrategyProjection.strategyState`，就不再回退到 journal workflow 态标签。

### 11.2 本方案不承诺的事情

- 不承诺第一版就把实时与回测做到逐笔完全一致。
- 不承诺第一版移除所有旧辅助解释模块。
- 不承诺主表状态等于人工真实成交结果。
- 不承诺在没有可靠 live 持仓事实源时立刻完整展示所有生命周期状态。

本方案承诺的是：主语义先统一，主状态先纠正。

## 12. 验收标准

完成后至少应满足：

1. 主表【候选池】字段只表达 fusion 策略态，不再表达 journal workflow 态。
2. 候选池面板主列表与主详情都以 `FusionStrategyProjection` 为中心。
3. `trade_journal` 只作为 execution overlay，不再反向定义候选池主状态。
4. `CandidateDiscoveryService` 与“建议入池”不再出现在主候选池面板。
5. 历史 / 实时两条链路输出统一的策略投影结构。
6. `active_holding / exit_signaled / closed` 的来源必须来自策略事实层，而不是人工执行记录。
7. `snapshotType` 合同允许显式传入 `quarter_hour`，但默认口径仍是 `half_hour`。

## 13. 结论

这次不是“优化候选池面板”，而是：

- 废弃“通用候选工作台”主语义；
- 建立“fusion 主线策略生命周期工作台”主语义；
- 把 `trade_journal` 从主中心降级为执行覆盖层；
- 把主表与面板都统一到 fusion 策略语义锚点；
- 同时保留人工执行与复盘的正式录入链路。
