# RankTrend 跳跃检测实盘接入——设计规格

日期：2026-06-06 | 状态：设计中 | 依赖：[策略演进记录](2026-06-06-ranktrend-jump-detection-evolution.md)

## 动机

Python 端内生阈值跳跃检测策略在回测中达到 +55% 收益、79% 胜率、19 笔/月，但前端 Dragon Board 仍运行旧四层框架（37% 胜率）。实盘接入需要：

1. 将跳跃检测算法移植到 TypeScript，前端自给自足实时计算
2. 在龙头看板 DataTable 中直接展示入场/出场信号
3. 预留候选池接口，为下一阶段自动写入做准备

## 范围

- 新建 `jumpDetector.ts`：1:1 移植 Python `detect_rank_jumps()`
- 新建 `jumpSignalService.ts`：六入场条件 AND + 四出场条件 OR
- 改造 `RankTrendSignalService`：在现有刷新链路末尾追加跳跃检测
- 改造 `DataTable.vue`：新增"信号"列，展示入场▲ / 出场▼标记
- 预留 `CandidatePoolPanel` 接入接口：信号结构兼容 `candidateJournalService`，本阶段不实现自动写入

## 非范围

- 不删除旧的 compose_decision / compose_strategy / entry_signal 代码（保留为诊断参考）
- 不修改 QuantBoard Python 后端
- 不改变 DataTable 现有的置信度列和 buy/sell 徽章
- 不做止损计算（那是回测逻辑，实盘由人工判断）

---

## 1. 数据流

```
RankTrendAnalyzer.getRankTrends()
  → 缓存 percentiles 到 rankHistoryCache
  ↓
RankTrendSignalService.refreshRankTrendSignals()
  → applyJumpSignals()
    → 对每个 stock:
      1. rankTrendAnalyzer.getCachedPercentiles(code) → percentiles[]
      2. detectRankJumps(percentiles, deltaPct=15) → JumpResult  // 15 为优化候选值，非正式默认
      3. checkEntryConditions(stock, rankTrend, jump) → bool
      4. checkExitConditions(stock, rankTrend, jump, isInFrame) → [bool, reason]
      5. applyJumpSignal(stock, result) → 注入 stock.rankTrend.jump / _jumpEntry / _jumpExit
  ↓
DataTable "信号"列 读取 isJumpEntry / isJumpExit → 渲染标记
```

## 2. 模块设计

### 2.1 `jumpDetector.ts`（纯函数）

```typescript
function detectRankJumps(
  percentiles: number[],
  ranks?: number[] | null,
  deltaPct?: number,  // TS 函数默认 15，Python RankTrendConfig.jumpDeltaPct 默认 10。待 walk-forward 后统一正式默认值
): JumpResult
```

- 输入：排名百分位历史序列（来自 RankTrendAnalyzer 缓存）
- 输出：`{ event, direction, signal, magnitude, confidence, sustained, events[] }`
- 核心算法：累计变化 > delta 触发 → 重置参考点到近 3 帧均值 → 继续追踪
- 边界：< 3 帧返回 none，confidence 范围 [50, 95]

### 2.2 `jumpSignalService.ts`（业务判断）

```typescript
checkEntryConditions(stock, rankTrend, jump): boolean       // 六条件 AND
checkExitConditions(stock, rankTrend, jump, isInFrame): [boolean, string]  // 四条件 OR
evaluateJumpSignal(stock, rankTrend, percentiles, isInFrame): JumpSignalResult
```

入场条件：
1. jump.event == "jump" AND direction == "buy" AND sustained == true
2. technical.signals.direction == "buy" AND technical.signals.acceleration == "buy"
3. change > 0（股价同向确认）
4. change < dailyLimitPct(code) - 0.3（涨停板过滤）
5. MACD cross == "golden"
6. jump.confidence >= 85

出场条件（七条件 OR）：
1. code 不在当前帧 → true
2. jump.event == "jump" AND direction == "sell" AND sustained == true
3. MACD cross == "death"
4. rawChange < -80
5. 达到最大持有周期：holdingBars >= maxHoldingBars（默认 40）
6. 硬止损：unrealizedPnl <= stopLossPct（默认 -5%）
7. 止盈：unrealizedPnl >= takeProfitPct（默认 +12%）

### 2.3 `RankTrendAnalyzer` 改动

新增公开方法 `getCachedPercentiles(code: string): number[] | null`，读取 `rankHistoryCache` 中的百分位历史。只读、不修改缓存。

### 2.4 `compat.ts` 改动

新增挂载/读取函数：
- `applyJumpSignal(target, signal)` — 注入 jump / _jumpEntry / _jumpExit
- `isJumpEntry(target)` — 是否为入场信号
- `isJumpExit(target)` — 是否为出场信号
- `getJumpExitReason(target)` — 出场原因文本

### 2.5 `RankTrendSignalService` 改动

在 `refreshRankTrendSignals()` 和 `applySignalsToMerged()` 末尾追加 `applyJumpSignals()` 私有方法。

### 2.6 `DataTable.vue` 改动

- 新增列 `{ key: 'jumpSignal', label: '信号', group: 'comprehensive' }`，插入在"变化"和"置信度"之间
- 入场信号：金色 `▲` 标记 (#e8a800)
- 出场信号：天蓝 `▼` 标记 (#4da6ff)
- 无信号：`-`

### 2.7 候选池集成（暂不实现，在本 spec 中预留）

本阶段只做信号展示，候选池自动写入留到下一阶段。原因：
- 候选池写入逻辑需要先确认 `candidateJournalService` 的 API 合同
- 需要区分"实时信号"和"已确认交易"，避免重复创建
- 需要用户确认写入策略（每日一仓 max、去重规则）

## 3. 错误处理

- `getCachedPercentiles` 返回 null → 跳过该股票，不报错
- `rankTrend` 不存在或 `meta.code` 缺失 → 跳过
- percentiles < 3 → `detectRankJumps` 返回 event="none"，不触发信号
- NaN/Infinity → `clamp` 防护

## 4. 测试策略

- `jumpDetector.test.ts`：12 个用例覆盖核心算法、边界、震荡过滤、置信度
- 类型检查：`pnpm exec vue-tsc --noEmit -p tsconfig.app.json`
- 浏览器验证：启动 dev server，确认"信号"列正确渲染，入场/出场标记出现

## 5. 与现有系统的关系

| 现有功能 | 关系 |
|----------|------|
| DataTable 置信度列（buy/sell/hold 徽章） | 保留不变，新的信号列是互补展示 |
| 旧四层框架（RankTrendAnalyzer） | 保留不变，jump 检测作为追加步骤 |
| RankTrendPanel（策略详情面板） | 不修改，可后续考虑增加 jump 视图 |
| CandidatePoolPanel | 本阶段不修改，下一阶段接入 |
| QuantBoard Python 回测 | 不修改，作为研究实现 / 回测验证源。Golden 标准为 `src/services/rankTrend/**` 和 `RankTrendAnalyzer.ts`（TypeScript），Python 端需通过 TS/Python 对齐 fixture 验证一致性 |
