# 回测引擎设计

## 目标

首期回测引擎用于验证 Python rankTrend 候选策略在历史快照上的表现。它不复用旧 `ParameterOptimizer` 回测逻辑，也不把前端 `finalSignal` 直接当成交易指令。

当前实现口径以 [backtest-policy.md](backtest-policy.md) 为准。本文是设计说明，若和当前运行口径冲突，优先按统一口径文档执行。

核心目标：

- 事件顺序稳定；
- 结果可复现；
- 交易成本明确；
- 指标无 `NaN`；
- 报告可被 API、CLI、前端读取。

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
  "metrics": {},
  "equity_curve": [],
  "trades": [],
  "signals": [],
  "diagnostics": {
    "quality": {},
    "skipped_orders": [],
    "warnings": []
  }
}
```

报告写入 `backtest_runs.result_json`，可选再导出到 `data/reports/*.json`。

当前实现还会在报告里写入：

- `sampleDiagnostics`：样本数、样本质量状态、MACD 稳定窗口、诊断提示；
- `macdDiagnostics`：MACD 参数、最小 bars、稳定观察 bars、辅助观察定位；
- `tradeDiagnostics`：按出场原因、RankTrend 分层统计利润贡献，并列出最好/最差交易和未平仓；
- `controlBacktests`：热榜 Top10、A_MAIN only、B_IGNITION only、A+B 四组对照回测。

对照组复用同一批 Python RankTrend 信号和同一交易成本模型，只改变入场过滤器，用于判断正式策略的边际价值。

## 质量门禁

回测启动前必须检查：

- 数据集存在；
- 快照类型存在；
- 日期区间内样本数足够；
- 核心字段完整；
- 时间顺序稳定；
- 价格字段可用于撮合；
- `snapshot_type` 合法。

失败返回结构化错误，不创建 `completed` 状态的 run。

## 测试清单

- 空数据集会失败并返回原因。
- 样本不足会失败或进入明确 degraded 模式。
- 固定 `random_seed` 重复运行结果一致。
- 无交易时指标没有 `NaN`。
- 止损、止盈、最大持有 bars 可独立触发。
- 默认请求使用 `half_hour`。
- 显式 `quarter_hour` 请求不会污染 half_hour 结果。
