# 回测引擎设计

## 目标

首期回测引擎用于验证 Python rankTrend 候选策略在历史快照上的表现。Dragon Board 根项目不再承载回测职责；所有回测、优化、交易模拟和报告展示统一归 QuantBoard Python 后端。

当前实现口径以 [backtest-policy.md](backtest-policy.md) 为准。本文是设计说明，若和当前运行口径冲突，优先按统一口径文档执行。

核心目标：

- 事件顺序稳定；
- 结果可复现；
- 交易成本明确；
- 指标无 `NaN`；
- 报告可被 API、CLI、前端读取。

## 迁移边界

原根项目 `src/services/strategyBacktest` 的职责已由 Python 后端承接：

- `OutcomeEvaluator` 输出候选池分布、forward validation、`byMomentumBucket` 等后验分组；
- `TradeSimulator` 负责撮合、费用、T+1、涨跌停、成交量和盘口约束；
- `BacktestEngine` 负责编排 RankTrend 回放、质量诊断、交易模拟和对照组；
- `Optimizer` 负责参数搜索、训练/验证切分、walk-forward 和过拟合风险提示。

Dragon Board 只通过 `quantBoardBridge` 提供 IndexedDB 数据读取和 TypeScript golden 导出，不再提供浏览器内回测入口。

## 输入

回测请求最少包含：

```json
{
  "dataset_id": "ds_20260430_001",
  "snapshot_type": "half_hour",
  "start_date": "2026-04-20",
  "end_date": "2026-04-30",
  "strategy_name": "rank_trend_candidate",
  "strategy_version": "0.1.0",
  "initial_capital": 100000,
  "random_seed": 20260430,
  "params": {}
}
```

没有传 `snapshot_type` 时默认 `half_hour`。`quarter_hour` 必须显式传入。

`strategy_name` 会真实控制交易模拟的入场过滤器。当前支持 `rank_trend_candidate`、`hot_top10`、`a_main_only`、`b_ignition_only`、`a_b_combined`，非法策略名会拒绝回测。

题材因子接入：

- 默认 `tradeConfig.useThemeFactorForExecution=false`，题材因子只写入候选解释、风险标记和归一化 signals，不改变交易执行。
- 设置 `useThemeFactorForExecution=true` 后，题材支持度才参与执行：强题材支持可小幅提高候选置信度，高拥挤风险会把买入降级为观察。
- 题材因子不能绕过 RankTrend 独立制造买入信号，只能辅助已有候选分层。

## 事件循环

建议采用逐快照事件循环：

1. 按 `timestamp` 升序加载标准快照。
2. 对当前快照构建 rank map 和股票行情上下文。
3. 调用 Python rankTrend 获取个股分析结果。
4. 策略根据 rankTrend 结果生成候选入场/离场意图。
5. 组合层处理已有持仓、资金、仓位上限、风控规则。
6. 撮合层使用明确的执行价、滑点和费用模型成交。
7. 每个快照做持仓盯市，记录权益曲线。
8. 回测结束时按最后有效价平仓或保留未平仓状态，需在报告中明确。

## 策略信号

首期策略只消费 `strategy.candidateTier`、`decision`、`risk`、`sampleQuality`：

建议入场候选：

- `candidateTier=A_MAIN`
- 或 `candidateTier=B_IGNITION` 且样本质量不是 `insufficient`
- 市场环境不是 `retreat`
- 风险压力低于配置阈值

建议回避：

- `candidateTier=C_CROWDED`
- `candidateTier=D_EXIT_RISK`
- `sampleQuality=insufficient`
- `risk.pressure` 超过阈值

这只是首期默认策略，最终要以配置形式暴露。

V2 起策略同时记录 `ThemeCandidateSupport`：

- `mainTheme`
- `themeHeat`
- `themeContribution`
- `themeRole`
- `themeSupportScore`
- `themeRiskFlags`
- `themeReasons`

这些字段会落到 `backtest_signals`，用于报告解释和后续分组分析。

## 撮合模型

当前使用按字段逐步增强的撮合模型：

- 入场价：优先使用 `ask1Price`，没有盘口价时回退到信号事件快照价，再叠加买入滑点。
- 出场价：优先使用 `bid1Price`，没有盘口价时回退到触发离场时的可见价格，再叠加卖出滑点。
- `executionMode=current_bar` 时，信号和成交在同一快照完成。
- `executionMode=next_bar` 时，当前快照只产生信号，下一快照才使用下一快照行情撮合；报告用 `signalSnapshotId` 标记信号来源。
- 涨停默认不可买，跌停默认不可卖。
- 盘口量和成交量字段存在时，会限制成交数量并允许部分成交。
- `high` / `low` 字段存在时，止盈止损可按盘中高低价触发。
- 价格无效、成交额无效、停牌或缺失行情时不成交。

`tradeSimulation.matchingDiagnostics` 会记录盘口覆盖率、快照价回退率、未成交原因和部分成交次数。没有盘口/成交量/高低价字段时，回测仍可运行，但会明确降级为快照价研究模拟。
- 同一股票已有持仓时不重复开仓。
- 启用 A 股 T+1：当天买入不能当天卖出。

## 仓位与成本

默认参数建议：

```json
{
  "max_positions": 5,
  "position_size": 0.2,
  "commission_rate": 0.0003,
  "stamp_tax_rate": 0.0005,
  "slippage_rate": 0.001,
  "min_lot": 100,
  "target_holding_days": 5,
  "max_holding_bars": 40
}
```

计算原则：

- 买入成本计入佣金和滑点；
- 卖出成本计入佣金、印花税和滑点；
- A 股数量按 `min_lot=100` 向下取整；
- 现金不足则跳过交易并记录原因。
- `max_holding_bars=40` 是 5 天持仓上限，不受 MACD 稳定观察窗口影响。

## RankTrend 与 MACD 口径

当前策略不把 MACD 金叉/死叉作为独立买卖触发器。MACD 只作为入场前的辅助观察信号，真正驱动入场和出场的是多周期动量、生命周期阶段、候选池分层、市场环境、风险压力和交易风控规则。

默认 MACD 参数为 `21/34/13`。当前实现中最低 `34` 个半小时 bars 后开始计算 MACD，更稳的观察口径是 `47` 个半小时 bars。

## 离场规则

首期支持：

- 固定止损；
- 固定止盈；
- 最大持有 bars；
- rankTrend 转弱；
- 样本质量恶化；
- 保留未平仓并在报告中明确展示。

离场优先级建议：

1. 无效行情或停牌：不能成交，只记录不可成交原因。
2. 止损。
3. 止盈。
4. 强风险信号：`D_EXIT_RISK`、高 `risk.pressure`。
5. 最大持有 bars。
6. 期末未触发离场的持仓保留为未平仓，并拆分展示盯市盈亏、预估平仓成本和预估平仓后盈亏。

## 权益曲线

每个快照都要记录：

```json
{
  "timestamp": 1777514400000,
  "trading_date": "2026-04-30",
  "slot_time": "10:00",
  "cash": 75200.0,
  "market_value": 26010.0,
  "equity": 101210.0,
  "drawdown": 0.012,
  "position_count": 3
}
```

不允许只在平仓时更新权益。否则最大回撤和波动率会失真。

## 绩效指标

首期指标：

- `total_return`
- `annualized_return`
- `max_drawdown`
- `sharpe_ratio`
- `trade_sharpe`
- `win_rate`
- `profit_factor`
- `expectancy_r`
- `total_trades`
- `average_hold_bars`
- `turnover`
- `realized_return`
- `realized_profit`
- `unrealized_mark_profit`
- `unrealized_exit_cost`
- `unrealized_profit`
- `open_position_count`

指标计算必须处理空交易：

- 没有交易时返回 `0` 或 `null`，但不能返回 `NaN`、`Infinity`。
- 报告中记录 `no_trade_reason`。

当前 `Sharpe` 使用短线交易周期口径：`tradeSharpe * sqrt(252 / targetHoldingDays)`。默认 `targetHoldingDays=5`，因此 `sharpeMethod=trade_return_cycle_5d`。

未平仓收益字段必须拆分：

- `unrealizedMarkProfit`：当前市值减买入总成本；
- `unrealizedExitCost`：预估卖出手续费和印花税；
- `unrealizedProfit`：预估平仓后浮动盈亏。

## 报告结构

回测报告写入 `backtest_runs.result_json`（MongoDB 模式下优先压缩存储），可选再导出到 `data/reports/*.json`。API 返回时自动产出轻量摘要（首 120 条 signals/trades/equity 预览），完整结果通过 `runId` 追溯。

```json
{
  "run_id": "bt_20260430_001",
  "dataset_id": "ds_20260430_001",
  "snapshot_type": "half_hour",
  "strategy_name": "rank_trend_candidate",
  "strategy_version": "0.1.0",
  "config_hash": "sha256...",
  "random_seed": 20260430,
  "status": "completed",
  "totalReturn": 0.0545,
  "maxDrawdown": -0.0504,
  "sharpe": 0.60,
  "winRate": 0.42,
  "tradeCount": 74,
  "dataQuality": {
    "severity": "warn",
    "researchGrade": "degraded",
    "snapshotCount": 290,
    "sampleOkShare": 0.4966,
    "qualityGate": { "passed": true, "issues": [], "stats": {} },
    "reportOnlyDiagnostics": {},
    "layer1SignalEfficacy": {},
    "layer2ExecutionQuality": {},
    "warnings": []
  },
  "equity_curve": [],
  "trades": [],
  "signals": [],
  "tradeSimulation": {
    "matchingDiagnostics": {}
  }
}
```

核心诊断字段说明：

- `sampleDiagnostics`：样本数、样本质量状态（ok/degraded/insufficient）、MACD 稳定窗口、诊断提示；
- `macdDiagnostics`：MACD 参数、最小 bars、稳定观察 bars、辅助观察定位；
- `tradeDiagnostics`：按出场原因、RankTrend 分层统计利润贡献，并列出最好/最差交易和未平仓；
- `controlBacktests`：热榜 Top10、A_MAIN only、B_IGNITION only、A+B 四组对照回测；
- `dataQuality.layer1SignalEfficacy`：V2 Layer 1 信号有效性诊断（分层比例、方向精度、二项检验），详见 [V2 四层框架设计](optimization-long-task/2026-05-26-longtest-v2-design.md#layer-1信号有效性)；
- `dataQuality.layer2ExecutionQuality`：V2 Layer 2 执行质量诊断（H1-H2 偏差、回撤差异），详见 [设计文档](optimization-long-task/2026-05-26-longtest-v2-design.md#layer-2执行质量)；
- `dataQuality.reportOnlyDiagnostics.priceQuality`：只读价格质量诊断（跨市场零行情、全零异常帧、A股局部零价），不参与过滤，不改变收益和等级；
- `tradeSimulation.matchingDiagnostics`：盘口覆盖率、快照价回退率、`blockedByLimit`、`nextBarEntries`/`nextBarExits`、未成交原因。

对照组复用同一批 Python RankTrend 信号和同一交易成本模型，只改变入场过滤器，用于判断正式策略的边际价值。

## 质量门禁

回测启动前必须检查：

- 数据集存在；
- 快照类型存在；
- 日期区间内样本数足够（≥ `minSnapshotCount`）；
- 核心字段完整（无 NaN/Inf 致命行）；
- 时间顺序稳定（无时间戳倒序）；
- `snapshot_type` 合法（`half_hour` / `quarter_hour`）；
- `captureMode` 合法（`real_time` / `delayed` / `synthesized`）。

失败返回结构化错误（`qualityGate.passed=false`），不创建 `completed` 状态的 run。

门禁统计维度（写入 `qualityGate.stats`）：

- 热榜覆盖：`lowHotlistCount`、`emptyHotlistCount`、`hotlistCountMin/Avg/Max`
- 资金流覆盖：`formalMoneyFlowCount`、`estimatedL1MoneyFlowCount`、`missingMoneyFlowSourceCount`
- 价格质量：`negativePriceCount`、`nonPositivePriceCount`、`nonPositivePriceExamples`
- 非法帧：`invalidCaptureMode`、`duplicateSnapshotId`、`nonMonotonicTimestamp`
- 样本质量：`totalFrames`、`coveredTradingDates`、`coverageRatio`

### 研究过滤开关

以下开关只作为显式研究口径，默认关闭，不改变默认回测行为和 MongoDB 源数据：

- `excludeNonPositivePriceRows`：剔除 `price <= 0` 行，统计写入 `runtimeFilter.priceFilter`
- `excludeCrossMarketZeroPriceRows`：剔除跨市场/非 A 股零行情行，统计写入 `runtimeFilter.crossMarketPriceFilter`
- `excludeAllZeroPriceFrames`：剔除整帧全零价格异常快照，统计写入 `runtimeFilter.allZeroPriceFrameFilter`

显式过滤后会再次检查可用帧数量，低于 `minSnapshotCount` 则返回质量门禁失败。

### 合成帧标记

通过 `bar_repair.py` 补齐的缺失 bar 标记为 `captureMode: "synthesized"`、`qualityFlags: ["synthesized"]`。质量门禁接受此模式不报 `invalidCaptureMode`。回测报告可通过此标记识别合成数据，选择性排除。

## V2 四层决策框架诊断

V2 长测方案在原有回测引擎基础上新增四层分层决策框架，每层有独立指标和门槛。回测引擎在完成交易模拟后自动计算 Layer 1-2 诊断并写入 `dataQuality`。

完整设计以 [2026-05-26-longtest-v2-design.md](optimization-long-task/2026-05-26-longtest-v2-design.md) 为准。以下是引擎层面的简要约定：

### Layer 1：信号有效性

- 数据来源：回测信号中的 `candidateTier` 字段
- 计算函数：`services.compute_signal_efficacy()`
- 写入位置：`dataQuality.layer1SignalEfficacy`
- 核心指标：`tierRatio`（A+B占比）、`directionAccuracy`（方向精度）、`binomialPValue`（二项检验）、`tierDiscrimination`（层级区分度）
- 门槛：方向精度 > 55% + p < 0.10 + 区分度 > 5pp + 比例 2%-15%
- 不达标时 `layer1Status = "red"`，不阻塞回测运行，仅做诊断

### Layer 2：执行质量

- 数据来源：H1（current_bar）和 H2（next_bar）两条基线的绩效对比
- 计算函数：`services.compute_execution_quality()`
- 写入位置：`dataQuality.layer2ExecutionQuality`
- 核心指标：`bias`（H1-H2收益差）、`biasThreshold`（相对阈值 min(|H1|, 15pp)）、`drawdownDiff`
- 状态：green（偏差在阈值内）/ yellow（H1 > H2 但偏差超标，乐观偏差）/ red（H2 反超 H1，追高风险）

### Layer 3：实盘对齐

- 独立于单次回测，通过 `GET /api/backtests/alignment` 端点交叉比对 trade_journal 执行记录与回测信号
- 至少需要 10 笔含 `entryPrice` 的 journal 记录才能产出有效报告
- 不阻塞回测运行

### Layer 4：参数优化

- 触发条件：Layer 1-3 连续 2 期绿灯 + 上次优化距今 ≥10 交易日
- 双层止损：条件A（实盘路径 H1/H2 连续亏损）+ 条件B（优化器无法找到更优参数）
- 两阶段：<60 交易日仅搜索交易管理层参数，≥60 交易日纳入策略层参数
- 详见 [optimization.md](optimization.md) 和 V2 设计文档

### 跨期状态追踪

- `check_layer1_meltdown()`：连续 3 期 Layer 1 红灯 → 触发策略结构性复审告警
- `check_layer3_trend()`：连续 2 期 Layer 3 sufficient → 对齐绿灯
- 结果写入长测 JSONL 的 `crossPeriod` 字段

## 长测 Checkpoint 系统

量化工作台支持通过固定基线复跑形成可追溯的 checkpoint 序列：

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines `
  --checkpoint-id checkpoint_2026-05-29_weekly `
  --dataset-id dragonboard_live
```

每次 checkpoint 固定执行三条基线：

| Label | snapshot | execution | maxHoldingBars | 用途 |
|---|---|---|---|---|
| H1_half_hour_current_bar | half_hour | current_bar | 40 | 页面兼容/乐观上限 |
| H2_half_hour_next_bar | half_hour | next_bar | 40 | 正式保守验收主线 |
| Q1_quarter_hour_next_bar | quarter_hour | next_bar | 80 | 研究压力测试 |

结果以 JSONL 追加到 `data/reports/long_test_runs.jsonl`，包含完整的三层指标、价格质量诊断和跨期状态。

前端可通过"长测趋势"标签页（QuantBoard 前端）查看多期 checkpoint 对比表。

详细计划和发现以 [optimization-long-task/task_plan.md](optimization-long-task/task_plan.md) 和 [optimization-long-task/findings.md](optimization-long-task/findings.md) 为准。

## 测试清单

- 空数据集会失败并返回原因。
- 样本不足会失败或进入明确 degraded 模式。
- 固定 `random_seed` 重复运行结果一致。
- 无交易时指标没有 `NaN`。
- 止损、止盈、最大持有 bars 可独立触发。
- 默认请求使用 `half_hour`。
- 显式 `quarter_hour` 请求不会污染 half_hour 结果。
- 合成帧（`captureMode=synthesized`）不触发质量门禁失败。
