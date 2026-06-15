# 交易池强共振自动入池规格

**日期**: 2026-06-15  
**状态**: 待实现规格  
**范围**: RankTrend 候选池、交易池、DataTable 置信度 tooltip、CandidatePoolPanel 交易池面板  
**背景样本**: `002171 楚江新材`、`603738 泰晶科技`，以及同类“综合共振强但 Jump 未过严格候选池阈值”的股票

## 1. 结论

本规格不把“四维综合判断置信度”和“Jump 跃迁置信度”合并成一个分数，也不针对单只股票打补丁。

正确边界是：

- **候选池**保留 V5/Fusion 严格执行合同，继续回答“是否满足策略初筛和样本沉淀口径”。
- **交易池**新增强共振召回规则，回答“是否值得进入买点跟踪工作台”。
- **DataTable tooltip**需要同时解释 Jump、综合共振和池子动作，避免把“跃迁置信度”误读为最终买点强度。

因此，当某只股票被候选池 Jump 硬阈值阻断，但综合判断、方向一致性、动量加速度、零线交叉、MACD 等形成强共振时，应进入交易池的“强共振观察 / 观察买点”链路，而不是静默显示为未触发。

## 2. 当前问题

现有实现存在三层错位：

1. 主表 `confidence` 列显示 Jump 置信度，但 tooltip 首行展示综合判断置信度，语义容易混淆。
2. 候选池自动入池仍以 V5/Fusion `jump_confidence >= minJumpConfidence` 作为硬阻断，适合策略纪律，但不适合承接所有买点观察。
3. 交易池服务当前主要读取 Jump、方向、MACD、加速度、零线和生命周期，尚未系统纳入 `decision.final.confidence`、四维买入票数、风险扣分、候选池阻断原因和强共振召回来源。

Playwright 观察到的典型现象：

- `002171 楚江新材`: 综合判断买入且置信度约 87%，Jump 约 82.9%，方向/动量/零线均偏买入，但候选池因 Jump 阈值被阻断或降级。
- `603738 泰晶科技`: 综合判断买入、Jump 约 87.9%、MACD 金叉、方向/动量/零线均偏买入，但候选池仍可表现为未触发。

这些不是个股特例，而是候选池和交易池职责未完全拆开的系统性问题。

## 3. 目标

1. 为交易池定义可测试、可解释的自动入池规则。
2. 明确候选池严格入池、候选池强共振观察、交易池观察买点、交易池准备介入之间的边界。
3. 让交易池面板从半成品变成可用的买点跟踪工作台，至少能展示来源、状态、综合置信度、Jump、买入票数、风险标签、原因和操作。
4. 让 DataTable tooltip 同时显示“候选池结果”和“交易池召回结果”。
5. 保持真实历史交易日志边界：交易池不是成交记录，`已介入` 也不自动生成真实 `entry/exit`。

## 4. 非目标

- 不放宽 V5/Fusion 候选池严格入池主规则。
- 不把交易池做成自动下单模块。
- 不把交易池与历史交易日志合并。
- 不引入新外部依赖。
- 不在本规格中修改 QuantBoard 回测主链。

## 5. 核心概念

### 5.1 JumpScore

JumpScore 来自 `rankTrend.jump.confidence`，兼容旧字段 `jumpConfidence`。

职责：

- 衡量排名跃迁事件强度。
- 继续作为候选池严格入池的重要硬门槛。
- 在交易池里作为召回质量门槛，不单独决定买点。

数值统一为百分制 `0-100`。如果来源是 `0-1` 小数，读取层必须转换为百分制。

### 5.2 ConsensusScore

ConsensusScore 即 `rankTrend.decision.final.confidence`，是 RankTrend 自身对趋势共振质量的综合评分（0-100 百分制）。

交易池不重新发明 RankTrend 综合分，直接使用 `final.signal` 和 `final.confidence` 作为核心判断依据，同时读取分项信号（方向、加速度、零线、MACD）计算 BuyVotes 作为可解释的辅助票数。两者是互补关系：ConsensusScore 是 RankTrend 的结论，BuyVotes 是交易池自己的解释性验证。

### 5.3 BuyVotes

BuyVotes 是交易池自己的解释性计数：

| 项 | 买入票条件 | 备注 |
|---|---|---|
| 方向一致性 | `direction.signal === 'buy'` | 核心趋势票 |
| 动量加速度 | `acceleration.signal === 'buy'` | 加速确认票 |
| 零线交叉 | `zeroCross.signal === 'buy'` | 位置确认票 |
| MACD | `macd.cross === 'golden'` | 金叉加一票，`none` 中性，`death` 风险 |

BuyVotes 取值 `0-4`。

### 5.4 RiskFlags

RiskFlags 至少包含：

- `lifecycle_veto`
- `macd_death_cross`
- `overheat_sell`
- `capital_divergence_sell`
- `momentum_sync_broken`
- `jump_confidence_low`
- `final_confidence_low`
- `candidate_hard_blocked`
- `data_stale`

风险用于决定降级、观察、出池，不用于遮蔽真实原因。

### 5.5 PoolSource

交易池每一行必须标明来源：

- `candidate_auto_add`: 候选池严格通过。
- `candidate_watch`: 候选池观察中。
- `jump_blocked_resonance`: 候选池主要被 Jump 阈值阻断，但强共振召回。
- `manual`: 用户手工加入。
- `persisted`: 历史交易池记录恢复。

## 6. 候选池规则

### 6.1 严格入池

候选池严格入池继续使用现有 V5/Fusion 合同：

- 执行分层存在。
- 样本质量通过。
- 生命周期不是 veto。
- Jump 方向为 `buy`。
- Jump 置信度达到当前策略模式阈值。
- 多周期动量、加速度、涨幅位置、涨停状态、候选分层、B 档确认等规则按现有合同执行。

当前策略模式阈值仍来自 `rankTrendLiveStrategyConfig`：

| 模式 | 候选池 Jump 阈值 |
|---|---:|
| `recall_first` | 80 |
| `balanced` | 85 |
| `strict_execution` | 90 |

### 6.2 强共振观察

新增候选池观察语义：`强共振观察`。

满足以下条件时，即使候选池严格入池未通过，也应在 UI 和交易池输入中被识别：

- `final.signal === 'buy'`
- `final.confidence >= 85`
- `BuyVotes >= 3`
- `jump.direction === 'buy'`
- `jump.confidence >= 80`
- 生命周期不是 veto。
- MACD 不是 death。
- 若 `overheat_sell` 与 `capital_divergence_sell` 同时出现，只能观察，不得升级为准备介入。

如果候选池阻断项包含多个硬问题，例如样本质量失败、生命周期 veto、涨幅位置失控，则不得仅凭共振召回。

## 7. 交易池自动入池规则

### 7.0 默认阈值常量

本规格使用以下命名常量。实现层应从统一配置源读取，不硬编码分散的魔术数字：

| 常量 | 值 | 用途 |
|---|---|---|
| `TRADING_POOL_RECALL_JUMP_MIN` | 80 | 交易池召回最低 Jump 置信度（观察买点门槛） |
| `TRADING_POOL_READY_JUMP_MIN` | 85 | 准备介入最低 Jump 置信度 |
| `TRADING_POOL_OBSERVE_FINAL_MIN` | 85 | 观察买点最低综合置信度 |
| `TRADING_POOL_READY_FINAL_MIN` | 88 | 准备介入最低综合置信度 |
| `TRADING_POOL_BUY_VOTES_MIN` | 3 | 强共振最低买入票数 |
| `TRADING_POOL_DOWNGRADE_JUMP_MIN` | 75 | 降级/出池 Jump 下界 |
| `TRADING_POOL_DOWNGRADE_FINAL_MIN` | 75 | 降级综合置信度下界 |
| `TRADING_POOL_EXIT_FINAL_SELL` | 80 | final=sell 强制出池置信度门槛 |

### 7.1 输入范围

交易池自动入池应扫描以下来源：

1. 已有候选池 thesis 记录。
2. 已有 `tradeType=trading_pool` 持久化记录。
3. 当前 DataTable / RankTrend live projection 中的强共振观察对象。

第三类来源不等于候选池严格通过；它是交易池为了避免遗漏强共振买点而新增的召回入口。

### 7.2 观察买点

进入 `观察买点` 需要：

- `final.signal === 'buy'`
- `final.confidence >= 85`
- `BuyVotes >= 3`
- `jump.direction === 'buy'`
- `jump.confidence >= 80`
- 方向、加速度、零线三项中至少两项为 `buy`
- MACD 不是 death。
- 生命周期不是 veto。
- 数据质量不是 stale。

允许存在单一风险项，例如过热卖出或资金背离卖出，但原因必须展示。

### 7.3 准备介入

进入 `准备介入` 需要比观察买点更强：

- `final.signal === 'buy'`
- `final.confidence >= 88`
- `BuyVotes >= 3`
- `jump.confidence >= 85`
- MACD 为 `golden`，或零线交叉为 `buy` 且方向一致性为 `buy`
- 没有 `overheat_sell + capital_divergence_sell` 双风险。
- 没有候选池非 Jump 类硬阻断。

`603738 泰晶科技` 这类“综合买入、Jump 接近严格阈值、MACD 金叉、三趋势共振”的股票应优先进入这一层或至少显示为高优先级观察。

### 7.4 降级观察

满足以下任一条件时，交易池保留但降为 `观察中`：

- `final.confidence` 低于 `TRADING_POOL_OBSERVE_FINAL_MIN`(85) 且不低于 `TRADING_POOL_DOWNGRADE_FINAL_MIN`(75)。
- `BuyVotes === 2`。
- `jump.confidence` 低于 `TRADING_POOL_RECALL_JUMP_MIN`(80) 但不低于 `TRADING_POOL_DOWNGRADE_JUMP_MIN`(75)。
- 动量同步破坏。
- 存在过热卖出或资金背离卖出，且另一个风险项不为 `buy`。

`002171 楚江新材` 如果 MACD 无、风险项偏弱，应进入 `观察买点` 或 `观察中`，不能直接升级为准备介入。

### 7.4a 单风险项处理

单个风险项不直接触发降级，但影响状态上限：

- 仅有 `overheat_sell` 或仅有 `capital_divergence_sell`：可进入 `观察买点`，但原因和风险标签必须展示该风险项。
- `overheat_sell` 与 `capital_divergence_sell` 同时出现（双风险）：最高 `观察中`，不得升级为 `准备介入`。已在 `准备介入` 或 `观察买点` 的，降为 `观察中`。
- 任一风险项为 sell，且另一风险项不为 buy（如 hold、sell、缺失）：降为 `观察中`。
- 单风险项不影响 `已介入` 状态的保持（见 7.7）。

### 7.5 强制出池

满足以下条件时，交易池标记 `已退出`：

- lifecycle veto。
- MACD death 且方向转弱或零线转空。
- `final.signal === 'sell'` 且 `final.confidence >= TRADING_POOL_EXIT_FINAL_SELL`(80)。
- `BuyVotes <= 1` **且** `jump.confidence < TRADING_POOL_DOWNGRADE_JUMP_MIN`(75)（两项同时满足才出池，仅单项满足按 7.4 降级）。
- 若 `rankTrend.jump.confidence` 缺失，但候选池规则矩阵 `jump_confidence.actual` 存在，则交易池必须使用该值作为同源兜底；若两者都缺失，不得把 Jump 当成 0 分触发强制出池，只能进入观察/过期链路。
- 数据连续过期超过实现层定义的有效刷新窗口。

### 7.6 数据过期

数据缺失或 stale 时：

- 保留上一状态。
- 标记 `signal_stale`。
- 不自动从观察买点降为已退出。
- 不创建真实交易日志。

### 7.7 已介入后的自动流转

`已介入` 是人工确认的执行意向状态，不等于真实成交。该状态下仍需参与自动信号评估，但门槛比"观察买点"更高：

- **保持 `已介入`**：单风险项出现、BuyVotes 降到 2、Jump 小幅回落（≥ `TRADING_POOL_DOWNGRADE_JUMP_MIN`(75)）时，保持 `已介入` 状态，但面板必须展示风险变化和警告。
- **降为 `观察中`**：`final.signal` 变为 `hold` 且 `final.confidence < TRADING_POOL_OBSERVE_FINAL_MIN`(85)，或 `BuyVotes <= 1` 且 `jump.confidence < TRADING_POOL_DOWNGRADE_JUMP_MIN`(75)。
- **强制出池（`已退出`）**：lifecycle veto、MACD death 且方向转弱或零线转空、`final.signal === 'sell'` 且 `final.confidence >= TRADING_POOL_EXIT_FINAL_SELL`(80)。
- 降级或出池时清除 `已介入` 标记，不自动创建历史交易日志（`entry/exit`）。
- 信号过期时保持 `已介入` 状态，标记 `signal_stale`，不降级。

## 8. 交易池面板规格

### 8.1 总览指标

面板顶部至少展示：

- 总数
- 观察买点
- 准备介入
- 已介入
- 已退出
- 信号过期

### 8.2 左侧列表

左侧列表不能长期停留在“暂无交易记录”。它应显示交易池记录或投影行，支持：

- 搜索代码/名称。
- 按决策筛选：全部、观察买点、准备介入、观察中、已退出、已介入、信号过期。
- 按状态筛选：跟踪中、已退出、过期。
- 新建交易池记录入口保留，但不得替代自动入池。

### 8.3 主表字段

交易池主表至少包含：

- 股票
- 来源
- 状态
- 决策
- 综合置信度
- Jump 置信度
- BuyVotes
- MACD
- 风险标签
- 自动入池/降级/出池原因
- 更新时间
- 操作

### 8.4 详情区

选中交易池行后展示：

- 候选池结果：严格通过、强共振观察、Jump 阻断、非 Jump 硬阻断。
- 交易池判定：观察买点、准备介入、观察中、已退出。
- 信号矩阵：final、Jump、方向、加速度、零线、MACD。
- 风险矩阵：过热、资金背离、生命周期、动量同步、数据质量。
- 快照对比：入池快照与当前实时信号。

### 8.5 操作

操作必须保持语义清晰：

- `标记已介入`: 只改变交易池状态，不生成真实成交。
- `降为观察`: 人工降级。
- `退出跟踪`: 标记交易池已退出。
- `打开候选详情`: 跳到候选池 thesis。
- `打开排名趋势`: 打开 RankTrend 面板。

## 9. DataTable Tooltip 规格

`confidence` 列建议改名为 `Jump置信`，tooltip 顶部显示：

```text
综合判断: 买入 (置信度: 87%)
Jump跃迁: 82.9% (候选池阈值: 85 / 未过)
共振评级: 强共振 (BuyVotes: 3/4)
交易池动作: 观察买点
```

候选池 tooltip 或 badge 应补充：

```text
候选池: Jump 阈值阻断
交易池: 强共振召回观察
```

这样用户能一眼区分“策略严格入池没过”和“交易池仍值得盯”。

## 10. 数据契约

交易池分析结果建议扩展为：

```ts
interface TradingPoolSignalSnapshot {
  finalSignal: string | null
  finalConfidence: number | null
  jumpDirection: string | null
  jumpConfidence: number | null
  directionSignal: string | null
  directionConfidence: number | null
  accelerationSignal: string | null
  accelerationConfidence: number | null
  zeroCrossSignal: string | null
  zeroCrossConfidence: number | null
  macdCross: string | null
  buyVotes: number
  riskFlags: string[]
  source: TradingPoolSource
  dataQuality: 'fresh' | 'stale' | 'missing'
}
```

持久化到 `signalsSnapshot.tradingPool` 时必须保存：

- `version`
- `source`
- `status`
- `decision`
- `signalSnapshot`
- `reasons`
- `riskFlags`
- `lastRecomputedAt`

**向前兼容**：读取 Phase 18 V2 持久化交易池记录（`tradeType=trading_pool`）时，若 `signalsSnapshot.tradingPool` 缺少 `buyVotes`、`riskFlags`、`source`、`momentumSyncBroken` 等本次新增字段：

- 若当前实时 RankTrend 数据可用，以当前信号重新计算补齐缺失字段，并更新 `lastRecomputedAt`。
- 若 `rankTrend` 不可用，保留旧快照原样，`dataQuality` 标记为 `stale`，不因字段缺失而降级或出池。
- 不修改旧记录的 `status` / `decision`，除非重算结果与当前持久化状态不同且规则要求变更。

## 11. 验收样例

### 11.1 楚江新材型

输入：

- final buy / confidence 87
- Jump buy / confidence 82.9
- direction buy
- acceleration buy
- zeroCross buy
- MACD none
- 生命周期 allow
- 存在单项风险

期望：

- 候选池严格入池可以继续被 Jump 阈值阻断。
- 交易池不得忽略。
- 交易池状态为 `观察买点` 或因风险降为 `观察中`，原因必须含 `jump_blocked_resonance`。

### 11.2 泰晶科技型

输入：

- final buy / confidence >= 85
- Jump buy / confidence 87.9
- direction buy
- acceleration buy
- zeroCross buy
- MACD golden
- 生命周期 allow

期望：

- 若 strict 候选池要求 Jump >= 90，候选池可阻断。
- 交易池应进入 `准备介入` 或高优先级 `观察买点`。
- tooltip 显示“候选池未过 Jump 阈值，交易池强共振召回”。

### 11.3 高 Jump 弱共振型

输入：

- Jump confidence 95
- final hold 或 buy confidence < `TRADING_POOL_OBSERVE_FINAL_MIN`(85)
- BuyVotes <= 1
- MACD death 或方向弱

期望：

- 若此前不在交易池中：不自动入池（不出现在交易池列表中）。Jump 高但共振不足，交易池不应被单一高 Jump 误导。
- 若已有交易池记录（来自此前强共振或其它来源）：降为 `观察中` 或标记 `已退出`（视 MACD 和方向严重程度，按 7.4/7.5 判定）。

### 11.4 风险双杀型

输入：

- final buy
- BuyVotes >= 3
- Jump >= 85
- overheat sell
- capital divergence sell

期望：

- 不进入 `准备介入`。
- 最多 `观察中`，原因展示双风险。

## 12. 验证要求

实现后至少运行：

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot
pnpm test:ranktrend
pnpm typecheck:ranktrend
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

涉及面板或 tooltip 改动时，必须用 Playwright 打开 `http://localhost:5173` 验证：

- 主表 tooltip 中 Jump、综合置信和交易池动作分离展示。
- 候选池 badge 能显示 Jump 阻断和交易池召回。
- 交易池面板不再空白，自动入池结果可见。
- 交易池行展示来源、综合置信度、Jump、BuyVotes、风险和原因。

## 13. 风险与边界

- 交易池召回会提高观察覆盖率，但可能增加噪声；因此必须用风险标签和状态分层控制，不直接变成”买入”。
- 候选池严格入池不能被交易池召回反向放宽，否则会破坏 V5/Fusion 策略纪律。
- 若实时 RankTrend 数据缺失，不得用旧快照制造”看似新鲜”的买点。
- `已介入` 仍是人工操作状态，不等于真实成交。
- Phase 18 V2 持久化交易池记录（`tradeType=trading_pool`）在规格升级后可能存在字段缺失。加载旧记录时应以当前实时信号重新计算缺失字段；重算不可行时保留旧状态并标记 `stale`。不可因字段缺失而降级或出池。
