# RankTrend Live Candidate Explainability Config Design

日期：2026-06-10
状态：交叉评审后已修订
关联计划：[实施计划](../plans/2026-06-10-ranktrend-live-candidate-explainability-config-implementation-plan.md)

交叉评审处理摘要：

- 已统一缺 RankTrend 为 `blocked_candidate`，避免 DataTable 显示“未触发”但详情显示阻断。
- 已要求未自动入池 live projection 通过 DataTable 既有“候选池”列打开 CandidatePoolPanel transient 详情。
- 已要求 CandidatePoolPanel 区分当前诊断快照与待生效策略设置，避免把盯盘解释面板变成参数实验台。
- 已要求规则矩阵显示“是否硬阻断”，并补齐关键参数快照字段。

## 1. 背景与问题

当前 RankTrend V5 live 自动入池把“回测执行合同一致性”放在了用户体验之前，导致盯盘用户看到盘面信号满足，却无法直观看到为什么没有自动入池。典型问题包括：

- `v5FusionExecutionContract.ts` 中 `change >= 6` 被写成硬阻断，但现有研究记录显示 `6%-8.5%` 区间不能简单视为不可入池。
- 涨停判断只按代码前缀回退，没有优先使用 `limitUpPrice`、`ztPrice`、`upLimitPrice` 等真实行情字段。
- `accepted=true/false` 过于粗糙，未区分“自动入池”“观察候选”“被硬阻断”“未触发”。
- 未入池股票的 gate 结果没有投影到 DataTable 和 CandidatePoolPanel，用户只能看到“未触发”，无法判断策略是否与盘面一致。
- DataTable 已经有“候选池”列，继续新增“阻断原因”“策略模式”等列会分散盯盘注意力。

本设计把 live 自动入池从黑箱硬编码改为可配置、可解释、可审计的盯盘工作流。

## 2. 目标

1. 保留 DataTable 现有“候选池”列，不新增其它候选相关列。
2. 让“候选池”列在一个紧凑 badge 内表达主状态：自动入池、观察候选、被阻断、未触发。
3. CandidatePoolPanel 展示完整解释：策略模式、参数快照、规则矩阵、当前值、阈值、结果和首要原因。
4. live 入池规则通过统一配置合同表达，不再散落在 `v5FusionExecutionContract.ts` 的局部常量里。
5. `change >= 6` 默认不再硬阻断，改为 balanced 模式下的观察/降级规则；strict 模式才恢复硬门槛。
6. 涨停判断优先使用真实行情涨停价，缺字段时才按板块回退。
7. 自动入池行为与展示解释消费同一份结构化 gate 结果，避免“看板显示”和“入池事实”两套口径。

## 3. 非目标

- 不重构 RankTrend 技术指标、生命周期、风险评分的全部模型内部阈值。
- 不把 QuantBoard 回测、优化、交易模拟能力迁回 Dragon Board 根项目。
- 不新增 DataTable 列。
- 不用 tooltip 作为主要解释载体。
- 不在本轮引入大型状态管理改造或新依赖。

## 4. 设计原则

### 4.1 盯盘优先

live 看板不是回测报告。默认行为应帮助用户及时发现值得观察的票，而不是用隐藏硬规则静默否决。严格执行对齐仍要保留，但必须由用户显式选择。

### 4.2 单一事实来源

同一只股票的自动入池、候选池列状态、CandidatePoolPanel 规则矩阵必须来自同一个 `entryDecision` 对象，避免 UI 和服务层各自解释。

### 4.3 配置显性化

所有会影响 live 入池的阈值必须进入配置合同，并在 CandidatePoolPanel 显示当前版本与模式。用户至少能知道现在跑的是哪套规则。

### 4.4 表格低干扰

DataTable 是高密度盯盘表。候选解释不应拆成多列；主表只给紧凑状态，详细解释进入 CandidatePoolPanel。

## 5. 用户体验设计

### 5.1 DataTable “候选池”列

继续复用现有 `jumpSignal` 列：

- `自动入池`：满足当前 live 配置的自动入池条件。
- `观察候选`：核心召回信号成立，但存在 warn 级别规则，例如涨幅位置偏高、B 档确认不足、分层非 A/B。
- `被阻断`：存在 hard block，例如涨停不可买、缺 RankTrend、样本严重不足、生命周期 veto。
- `未触发`：没有形成候选召回结构。

单元格可显示两行：

- 第一行：状态 badge。
- 第二行：短原因，最多一条，例如“涨幅观察”“涨停阻断”“B档待确认”。

该列点击后打开 CandidatePoolPanel 并定位对应股票。若股票尚未自动入池，也应能展示 live gate 投影；不能让“未入池”成为不可解释状态。

### 5.2 CandidatePoolPanel

CandidatePoolPanel 是完整解释工作台，新增三个区块：

1. 策略模式
   - `balanced`：默认均衡，硬阻断只保留不可交易/严重失真类规则。
   - `recall_first`：召回优先，尽量进入观察候选。
   - `strict_execution`：严格执行，恢复回测合同型硬门槛。

2. 参数快照
   - 配置版本。
   - `minJumpConfidence`。
   - `changeGate.mode` 与 `maxEntryChangePct`。
   - `accelerationMin` / `accDeltaMin`。
   - `allowedCandidateTiers`。

3. 规则矩阵
   - 规则名。
   - 当前值。
   - 要求。
   - 结果：通过、观察、阻断、关闭。
   - 是否硬阻断。

该面板不把解释藏进 tooltip；规则矩阵必须是可见内容。

## 6. 策略模式

### 6.1 balanced 默认模式

默认模式面向日常盯盘：

- `change >= 6`：warn，不硬阻断。
- `candidateTier` 非 A/B：warn，不硬阻断。
- `B_IGNITION` 缺 `mid >= 20` 或 `zeroCross=buy`：warn，不硬阻断。
- 涨停不可买、RankTrend 缺失、Jump 方向非 buy、Jump 置信度不足、多周期动量不转正、加速度不足、生命周期 veto：block。
- `minJumpConfidence` 默认 85。
- `allowDegradedSample` 默认 true。

### 6.2 recall_first 模式

召回优先模式用于盘中排查漏票：

- 降低 `minJumpConfidence` 到 80。
- 允许 `N_NEUTRAL` 进入观察候选。
- 更多解释字段作为 warn，而不是 block。
- 仍阻断涨停不可买、无效行情、RankTrend 缺失。

### 6.3 strict_execution 模式

严格执行模式用于与历史回测合同对齐：

- `minJumpConfidence` 90。
- `change < 6` 硬门槛恢复。
- `candidateTier` 必须 A/B。
- B 档必须 `mid >= 20` 且 `zeroCross=buy`。
- `allowDegradedSample=false`。

## 7. 数据合同

### 7.1 Live 配置

新增 `RankTrendLiveStrategyConfig`：

```ts
interface RankTrendLiveStrategyConfig {
  version: string
  mode: 'recall_first' | 'balanced' | 'strict_execution'
  minJumpConfidence: number
  allowDegradedSample: boolean
  requireCandidateTier: boolean
  allowedCandidateTiers: CandidateTier[]
  requireTierBMidAndZeroCross: boolean
  tierBMidMin: number
  accelerationMin: number
  accDeltaMin: number
  changeGate: {
    mode: 'off' | 'warn' | 'block'
    maxEntryChangePct: number | null
  }
  limitUpPolicy: 'quote_first'
}
```

配置默认值放在 `src/config/rankTrendLiveStrategyConfig.ts`。类型放在 `src/types/rankTrendLiveStrategy.ts`。

### 7.2 Gate Check

每条规则输出结构化结果：

```ts
interface RankTrendLiveGateCheck {
  key: string
  label: string
  status: 'pass' | 'warn' | 'fail' | 'disabled'
  hardBlock: boolean
  actual: string | number | boolean | null
  expected: string
  message: string
}
```

### 7.3 Entry Decision

`evaluateV5FusionEntry()` 输出：

```ts
interface RankTrendLiveEntryDecision {
  decisionState: 'auto_add' | 'watch_candidate' | 'blocked_candidate' | 'not_candidate'
  accepted: boolean
  label: string
  summary: string
  firstBlockingCheck?: RankTrendLiveGateCheck
  checks: RankTrendLiveGateCheck[]
  configSnapshot: RankTrendLiveStrategyConfig
}
```

旧字段如 `candidateTier`、`jumpConfidence`、`lifecycleAction`、`blockedReasons` 暂时保留兼容。

### 7.4 Fusion Projection

`FusionStrategyProjection` 增加 `entryDecision`，用于 DataTable 与 CandidatePoolPanel 共享解释：

```ts
entryDecision?: {
  decisionState: RankTrendLiveDecisionState
  label: string
  summary: string
  checks: RankTrendLiveGateCheck[]
  firstBlockingCheck?: RankTrendLiveGateCheck
  configSnapshot: RankTrendLiveStrategyConfig
}
```

## 8. 涨停判断

新增 `resolveLiveLimitState()`，判断顺序：

1. 读取真实字段：`limitUpPrice`、`ztPrice`、`upLimitPrice`、`涨停价`。
2. 若有最新价和涨停价，用价格接近涨停价判断。
3. 若缺真实涨停价，用板块回退：
   - `300/301/688/689`：约 20%，阈值 19.8。
   - `8/4/9`：约 30%，阈值 29.8。
   - 其它：约 10%，阈值 9.8。
4. 后续可扩展 ST、新股、停牌/复牌特殊状态；本轮不做过度推测。

规则矩阵必须显示判断来源：`quote_limit_price`、`board_fallback`、`missing_quote`。

## 9. 数据流

```text
RankTrendSignalService
  -> rankTrendAnalyzer.getRankTrends()
  -> applyRankTrendAnalysis()
  -> buildFusionStrategyProjections()
       -> evaluateV5FusionEntry(stock, liveConfig)
       -> entryDecision
  -> applyCandidatePoolProjections()
       -> stock.candidatePoolLabel / projection / firstReason
  -> DataTable existing 候选池 column
  -> CandidatePoolPanel detail workbench

FusionCandidateNotifier
  -> evaluateV5FusionEntry(stock, liveConfig)
  -> only decisionState === auto_add creates trade_journal candidate
```

## 10. CandidatePoolPanel 与未入池股票

当前 CandidatePoolPanel 主要读取 `trade_journal` 候选记录。为了让“未自动入池但已形成观察候选/被阻断”的股票也能解释，后续实现必须确保 DataTable 点击候选池 badge 时，可以用 live projection 打开详情。

首期可以复用当前事件：

- 如果已有 `candidatePoolEntryId`，显示 journal entry + projection。
- 如果没有 entry，但有 `candidatePoolProjection.entryDecision`，显示临时 live projection 详情，不提供删除候选和 execution overlay 保存。

实施计划首版若未覆盖临时 projection 详情，必须在交叉评审中标为 Important，因为否则“未入池解释”仍可能不可见。

## 11. 错误与降级

- 缺 RankTrend：`blocked_candidate`，规则矩阵显示 RankTrend 缺失。它属于数据门禁失败，不显示为“未触发”。
- 缺行情价格但有涨跌幅：使用板块回退，显示 `board_fallback`。
- 缺涨跌幅和价格：涨停判断 `missing_quote`，不直接伪造涨停状态。
- localStorage 配置损坏：回退 balanced 默认配置。
- CandidatePoolPanel 无 gate checks：显示“暂无规则诊断”，不显示空白区。

## 12. 测试策略

### 12.1 单元测试

- `change=6.5` 在 balanced 模式为 `watch_candidate`，不是 hard block。
- `change=6.5` 在 strict 模式为 `blocked_candidate`。
- 000 主板真实涨停价优先于代码前缀。
- 北交前缀 `8/4/9` 回退 29.8。
- `B_IGNITION` 二次确认在 balanced 为 warn，在 strict 为 block。
- `FusionStrategyProjection` 投影 `entryDecision`。
- `FusionCandidateNotifier` 只对 `auto_add` 入池。

### 12.2 UI 合同测试

- DataTable 仍只有既有“候选池”列，不新增“阻断原因/策略模式/入池原因”等列。
- CandidatePoolPanel 包含“策略模式”“参数快照”“规则矩阵”。

### 12.3 浏览器验收

- 000970 类似场景在候选池列显示“观察候选”或“被阻断”，不再静默“未触发”。
- 点击候选池列能看到规则矩阵。
- 候选池列文字不溢出、不遮挡相邻列。
- CandidatePoolPanel 在现有宽度下不出现文本重叠。

## 13. 风险与取舍

### 13.1 最大风险：未入池股票仍进不了 CandidatePoolPanel

如果 CandidatePoolPanel 只读取 journal entry，则未自动入池但有 projection 的股票仍不能解释。这会破坏本设计核心目标。实现时必须支持从 DataTable 传入 live projection 详情。

### 13.2 配置 UI 与实时生效

策略模式选择如果只写 localStorage，不触发 RankTrend 刷新，用户可能误以为立即生效。首期必须显示“刷新信号后生效”，后续再考虑主动刷新。

### 13.3 strict_execution 与 live UX 冲突

strict 模式是历史回测合同兼容，不应作为默认 live 模式。默认 balanced 是产品决策，不是回测结论。

### 13.4 过度配置风险

本轮只配置 live 入池可见 gate，不把 lifecycle/risk/technical 内部模型全部暴露给用户。否则界面会变成参数实验台，偏离盯盘。

## 14. 验收标准

- DataTable 未新增候选相关列。
- CandidatePoolPanel 可见展示策略模式、参数快照、规则矩阵。
- `change >= 6` 默认不再阻断 live 候选，只在 strict 模式阻断。
- 涨停判断优先 quote limit price。
- 自动入池只发生在 `decisionState=auto_add`。
- 未自动入池但有 live candidate 诊断的股票可以通过候选池列看到解释。
- RankTrend 相关测试、类型检查、浏览器验收通过。

## 15. 与实施计划的关系

实施计划必须覆盖以下设计要求：

1. Live 配置合同。
2. Quote-first 涨停判断。
3. 结构化 gate checks。
4. `entryDecision` 投影。
5. Fusion notifier 只自动加入 `auto_add`。
6. DataTable 单列约束。
7. CandidatePoolPanel 规则矩阵。
8. 未入池 live projection 的解释入口。
