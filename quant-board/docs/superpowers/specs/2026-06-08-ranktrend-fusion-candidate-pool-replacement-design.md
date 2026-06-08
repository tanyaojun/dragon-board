# RankTrend Fusion 候选池替代信号字段——设计规格

日期：2026-06-08 | 状态：待用户审阅

## 背景

当前 Dragon Board 主表的 `【信号】` 列已经演变成一套前端本地解释系统：

- 它消费 `rankTrend` 分析结果；
- 它自行映射 `A主升买点 / 转弱卖出 / 持有观察 / 无信号`；
- 它还维护一套前端本地“伪持仓 / 伪退出”状态。

这套链路与 QuantBoard 主线策略 `ranktrend_early_big_move_v3_lifecycle_fusion` 的真实消费口径不一致。主线策略的真实执行依赖：

- 候选筛选；
- 候选排序；
- `maxPositions`；
- 持仓状态；
- T+1；
- 退出规则；
- 路径级资金与仓位占用。

因此，继续在 `【信号】` 字段上堆叠规则没有实际价值，只会保留第二套错误语义系统。

现有项目里已经有更合适的载体：`【候选池】`。候选池已经具备：

- `trade_journal` 持久化；
- `signalsSnapshot` 快照存档；
- 状态流转；
- 人工决策与复盘字段；
- Layer 3 实盘对齐入口。

本设计的目标不是“修好信号列”，而是彻底废弃它，让主表只承担候选池入口职责，真实动作统一进入候选池。

## 目标

1. 废弃主表 `【信号】` 语义，不再显示交易动作标签。
2. 将主表列改为 `【候选池】`，只显示候选池状态。
3. 当 `ranktrend_early_big_move_v3_lifecycle_fusion` 命中真实入场候选时，自动写入候选池。
4. 自动入池记录的初始状态固定为 `triggered`。
5. 后续跟踪、人工确认、退出复盘统一在候选池完成，不再在主表维护第二套交易语义。

## 非目标

- 不把主表改造成回测终端。
- 不在主表直接显示“买入 / 卖出 / 持有观察”。
- 不新增前端本地持仓账本。
- 不在第一版重做 QuantBoard 后端交易引擎。
- 不强行让主表逐笔成交结果等同回测成交回放。

---

## 1. 核心设计决策

### 1.1 废弃 `【信号】` 字段语义

主表不再解释：

- `A主升买点`
- `B点火买点`
- `止损卖出`
- `转弱卖出`
- `离榜卖出`
- `持有观察`
- `无信号`

这些词以后只允许出现在：

- 候选池详情说明；
- 候选快照解释；
- 复盘备注；
- 必要的通知文案。

主表层不再承担交易动作判断。

### 1.2 主表改成 `【候选池】` 状态入口

原 `【信号】` 列保留位置，但改名为 `【候选池】`。

该列只展示候选池状态：

1. `未入池`
2. `观察`
3. `候选`
4. `已触发`
5. `跟踪中`
6. `已复盘`

对应关系：

- `observe` → `观察`
- `candidate` → `候选`
- `triggered` → `已触发`
- `tracking` → `跟踪中`
- `reviewed` → `已复盘`
- 不存在 open candidate → `未入池`

### 1.3 自动入池状态固定为 `triggered`

`ranktrend_early_big_move_v3_lifecycle_fusion` 命中自动入池时：

- 不进入 `observe`
- 不进入 `candidate`
- 直接进入 `triggered`

理由：

- 这不是人工初筛候选；
- 这是“主线策略已触发”的事实记录；
- `triggered` 能与普通观察候选清晰区分。

---

## 2. 候选池驱动的数据流

### 2.1 主线入口

实时行情刷新后，仍先产出统一的 `rankTrend` 分析结果。

然后不再进入 `liveV3SignalMapper` 这类前端动作映射，而是进入 `fusionCandidateNotifier`：

```text
行情刷新
  -> RankTrendAnalyzer / runRankTrendAnalysisPipeline
  -> fusion 主线入场判定
  -> 命中则自动写入候选池
  -> 主表读取候选池状态并展示
```

### 2.2 自动入池条件

自动入池必须基于主线策略 `ranktrend_early_big_move_v3_lifecycle_fusion` 的真实入场条件，而不是基于旧 UI 标签。

第一版只要求与当前前端可复用的 fusion 入场判定保持一致：

- 先满足 V3 early-big-move 入场门槛；
- 再满足 `lifecycle_action != veto`；
- 满足后写入候选池。

注意：

- 第一版自动入池是“候选触发事实”，不是“已成交事实”；
- 候选池记录依然允许人工决定是否真正执行。

### 2.3 自动入池去重规则

自动入池不允许重复创建 open candidate。

规则：

- 先按 `stockCode` 查询 open candidate；
- 若已存在 `observe / candidate / triggered / tracking` 中任一 open entry：
  - 不再新建；
  - 仅更新 `signalsSnapshot` 或补充 `reviewNotes`；
- 若不存在 open entry：
  - 创建新记录，`status=triggered`。

### 2.4 自动写入字段

自动入池时至少写入：

- `tradeType=thesis`
- `status=triggered`
- `stockCode`
- `stockName`
- `signalsSnapshot`
- `entryReason`
- `tradeHypothesis`
- `entryPrerequisites`
- `invalidationRules`
- `reviewNotes`
- `reviewTags`

建议额外写入：

- `signalsSnapshot.source = ranktrend_early_big_move_v3_lifecycle_fusion`
- `signalsSnapshot.triggerType = auto`
- `signalsSnapshot.triggeredAt`
- `signalsSnapshot.rankTrendVersion`

---

## 3. 主表展示设计

### 3.1 主表列行为

主表 `【候选池】` 列不再展示交易动作，只展示状态 badge。

badge 文案：

- `未入池`
- `观察`
- `候选`
- `已触发`
- `跟踪中`
- `已复盘`

### 3.2 主表 tooltip

tooltip 只解释候选池状态，不解释买卖信号。

最少包含：

- 当前候选池状态；
- 最近一次入池/更新时间；
- 来源：
  - `ranktrend_early_big_move_v3_lifecycle_fusion 自动触发`
  - 或 `人工加入`
- 当前快照中的主要候选解释摘要。

### 3.3 主表交互

点击 `【候选池】` 列或其按钮时：

- 若已存在对应候选记录：
  - 打开候选池面板并定位到该记录；
- 若不存在：
  - 打开候选池面板，并可提供“手动加入候选池”入口。

主表不再保留旧 `【信号】` tooltip 解释。

---

## 4. 候选池面板职责增强

候选池面板成为唯一的“动作解释工作台”。

它负责：

- 展示自动触发来源；
- 展示 `signalsSnapshot`；
- 展示结构化条件和失效条件；
- 允许人工从 `triggered` 推进到 `tracking`；
- 允许后续记录：
  - 是否执行；
  - 何时进场；
  - 何时退出；
  - 退出原因；
  - 复盘结论。

主表只做入口和状态概览，不再承担动作解释。

---

## 5. 旧链路删除范围

### 5.1 必删内容

- `src/services/rankTrend/liveV3SignalMapper.ts`
- `src/services/rankTrend/__tests__/liveV3SignalMapper.test.ts`
- `RankTrendSignalService` 中对 `applyLiveV3SignalDecisions()` 的调用
- `DataTable.vue` 中旧 `【信号】` 列文案、tooltip 与样式语义
- `resetLiveV3SignalState` 相关调用链

### 5.2 保留但复用的内容

- `RankTrendAnalyzer`
- `runRankTrendAnalysisPipeline`
- `CandidateJournalService`
- `CandidatePoolPanel.vue`
- `trade_journal`
- `signalsSnapshot`

### 5.3 新增内容

建议新增一个与 `JumpSignalNotifier` 并列但职责更窄的 notifier，例如：

- `src/services/rankTrend/FusionCandidateNotifier.ts`

职责只包括：

1. 命中 fusion 入场候选时自动入池；
2. 已存在 open candidate 时避免重复创建；
3. 必要时更新候选池记录快照和备注；
4. 如需通知，围绕候选池事件发送，而不是围绕主表信号标签发送。

---

## 6. 状态推进规则

第一版只定义最小闭环：

1. `未入池`
2. `triggered`
3. `tracking`
4. `reviewed`

其中：

- `triggered`：策略自动触发，已自动入池
- `tracking`：人工确认继续盘中跟踪或已执行
- `reviewed`：本次候选生命周期结束，已完成复盘

`observe` 与 `candidate` 继续保留给人工发现型候选，不与自动触发型候选混淆。

---

## 7. 测试策略

本次重构的测试重点不是“信号标签显示是否正确”，而是“候选池是否成为唯一真实入口”。

至少覆盖：

1. 主线 fusion 条件命中时，自动创建 `status=triggered` 的候选记录。
2. 已存在 open candidate 时，不重复建新记录。
3. 主表状态列能正确反映候选池状态，而不是旧信号语义。
4. 删除 `liveV3SignalMapper` 后，`RankTrendSignalService` 仍能完成 `rankTrend` 和 jump 链路刷新。
5. `signalsSnapshot` 中保留 fusion 来源和触发时上下文。

如果实现阶段接入自动退出/失效更新，再补：

6. 触发失效事实时，候选池记录会更新 `reviewNotes / reviewOutcome / executionResult`。

---

## 8. 风险与边界

### 8.1 本设计解决的问题

- 消灭主表与回测之间的第二套前端信号语义；
- 把“主线策略命中”变成有持久化记录的候选池事件；
- 让实盘验证、人工执行、复盘对齐回到同一条数据链。

### 8.2 本设计不承诺的事情

本设计不承诺主表状态等于真实成交结果。

因为：

- 自动入池是“策略触发候选”；
- 真实成交仍需人工执行或后续专门的执行投影链路；
- 候选池是统一事实入口，不是自动交易执行器。

这是刻意保留的边界，而不是缺陷。

---

## 9. 推荐实施顺序

1. 先删除主表 `【信号】` 语义链路。
2. 把主表列改为 `【候选池】` 状态展示。
3. 新增 fusion 自动入池 notifier。
4. 接通 `CandidateJournalService` 自动创建 `triggered` 记录。
5. 主表点击进入候选池定位详情。
6. 最后补通知和复盘更新细节。

---

## 10. 结论

本设计明确放弃“修好主表信号列”的方向。

新的统一口径是：

- 主表只显示候选池状态；
- 主线策略命中自动入候选池；
- 候选池是唯一真实动作入口；
- `triggered` 是 fusion 自动入池的默认状态；
- 不再维护前端本地第二套买卖信号系统。
