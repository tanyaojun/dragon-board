# QuantBoard 回测统一口径

本文记录当前 QuantBoard 平台的统一回测口径。后续修改回测、优化、报告和前端展示时，先对齐本文，再改实现。

## 策略边界

QuantBoard 回测平台不修改 RankTrend 信号算法。RankTrend 负责输出多周期动量、生命周期阶段、风险压力、市场环境和候选池分层；回测平台只负责把这些信号放进历史事件流里撮合、持仓、计费和生成报告。

Dragon Board 根项目不承载回测平台职责。所有回测、优化、交易模拟、参数搜索和报告展示统一在 QuantBoard 中实现与验收。

## 默认快照

默认快照类型是：

```text
half_hour
```

`quarter_hour` 只作为显式选择的细颗粒度研究样本。不同快照类型的回测结果不能直接横向比较，也不能把 `quarter_hour` 优化出的参数直接覆盖 `half_hour` 默认参数。

## 默认交易参数

当前回测运行页默认参数：

```text
strategyName       = rank_trend_candidate
snapshotType       = half_hour
initialCash        = 1000000
maxPositions       = 5
executionMode      = current_bar
targetHoldingDays  = 5
maxHoldingBars     = 40
takeProfitPct      = 0.12
stopLossPct        = 0.06
macdFast/Slow/Signal = 21/34/13
randomSeed         = 20260430
```

半小时快照按每天约 8 个 bars 估算，`maxHoldingBars=40` 表示最多持有约 5 个交易日。这个限制是交易持仓周期，不是 MACD 预热窗口。

## MACD 定位

MACD 只作为入场前的辅助观察信号，不是独立买卖触发器。

实际买卖依据仍然是：

- 多周期动量；
- 生命周期阶段；
- A/B/C/D/N 候选池分层；
- 市场环境；
- 风险压力；
- 排名变化；
- 止损、止盈、最大持有 bars 等交易规则。

默认 MACD 参数为 `21/34/13`。当前实现中：

```text
最低开始计算：34 个 half_hour bars
更稳观察口径：34 + 13 = 47 个 half_hour bars
```

47 bars 约等于 5.9 个交易日，用于理解 MACD 稳定性；它不会改变 5 天、40 bars 的最大持仓规则。

## 入场规则

`strategyName` 会真实控制交易模拟的入场过滤器。当前默认正式策略是：

```text
rank_trend_candidate
```

支持的策略名：

- `rank_trend_candidate`：默认正式策略，买入 `A_MAIN` 与连续确认后的 `B_IGNITION`；
- `hot_top10`：只按热榜前 10 入场；
- `a_main_only`：只买 `A_MAIN`；
- `b_ignition_only`：只买连续确认后的 `B_IGNITION`；
- `a_b_combined`：只买 `A_MAIN + B_IGNITION`，与默认正式策略同一入场过滤口径，用作显式对照名。

入场候选：

- `A_MAIN`：核心入场候选；
- `B_IGNITION`：必须已有连续确认后才允许入场；
- 市场环境为 `retreat` 时不入场；
- 同一股票已有持仓时不重复开仓；
- 达到最大持仓数后不再开仓。

注意：`rankTrend.decision.final.signal=buy` 不是直接开仓指令，只作为技术方向的一部分。

## 对照组

报告中会同时输出 `controlBacktests`，用于判断正式策略是否真的优于朴素规则。对照组只用于研究比较，不会改变正式策略。

当前内置对照组：

- `hot_top10`：只看热榜排名前 10；
- `a_main_only`：只买 `A_MAIN`；
- `b_ignition_only`：只买连续确认后的 `B_IGNITION`；
- `a_b_combined`：只买 `A_MAIN + B_IGNITION`。

`hot_top10` 的意义是建立朴素热榜基线。它不是建议实盘只买前 10，而是用来衡量 RankTrend 分层是否比“单纯追热榜”更有效。

## 出场规则

当前出场条件：

- `D_EXIT_RISK`；
- `C_CROWDED` 且动量加速度转弱；
- 排名跌出前 50；
- 达到 `maxHoldingBars`；
- 触发止损；
- 触发止盈。

MACD 死叉不会单独触发卖出。

## A 股交易规则

当前撮合层启用：

- T+1：当天买入不能当天卖出；
- 100 股整数手；
- 买入滑点；
- 卖出滑点；
- 买入手续费；
- 卖出手续费；
- 卖出印花税。
- 有 `ask1Price` / `bid1Price` 时按盘口对手价优先成交，缺失时回退为快照价；
- 有涨跌停状态、涨跌停价或涨跌幅字段时，涨停默认不可买，跌停默认不可卖；
- 有盘口量或成交量字段时，按盘口参与率和成交量参与率限制成交数量，可部分成交；
- 有盘中 `high` / `low` 字段时，止盈止损按高低价触发；同一 bar 同时触发时默认按先止损处理。

## 成交时点

`executionMode` 支持两种口径：

- `current_bar`：默认兼容口径，当前快照产生信号并在当前快照撮合。
- `next_bar`：保守口径，当前快照产生信号，下一快照才撮合。下一快照的价格、盘口、涨跌停和容量字段决定是否成交；报告中的 `signalSnapshotId` 记录信号来源快照，`snapshotId` 记录实际成交快照。

`next_bar` 用于降低“同一快照看到信号又成交”的乐观偏差。它仍然不等价于真实逐笔交易，只是在现有快照级撮合模型上延后一档执行。

交易模拟只做研究，不连接真实券商，不作为实盘交易指令。

报告中的 `tradeSimulation.matchingDiagnostics` 会展示撮合覆盖情况，例如盘口覆盖率、快照价回退率、未成交原因和部分成交次数。如果历史数据没有盘口、成交量或盘中高低价字段，相关约束会自动降级，并在 warning 中说明。

## 收益口径

## 数据质量 warning

回测报告会输出 `dataQuality`：

- `research_ready`：数据质量满足正式研究口径；
- `degraded`：可用于候选观察，但低热榜、样本 OK 占比偏低或 MACD 预热不足会降低可信度；
- `blocked`：存在空热榜、非法快照或其他阻断问题，不建议用于验收。

低热榜样本阈值当前按 DragonBoard 回放端一致口径：单个快照热榜行数低于 `20` 记为低热榜。低热榜不会直接阻断回测，但会进入顶层 `warnings`、报告页质量结论和优化实验提示。

报告里几个收益字段含义不同：

- `totalReturn`：总收益，按 `现金 + 当前持仓市值` 计算，包含未平仓市值。
- `realizedReturn`：已实现收益率，只统计已平仓交易。
- `realizedProfit`：已实现盈亏金额。
- `unrealizedMarkProfit`：持仓盯市盈亏，即当前市值减买入总成本。
- `unrealizedExitCost`：按当前市值估算的卖出手续费和印花税。
- `unrealizedProfit`：预估平仓后浮动盈亏，即 `unrealizedMarkProfit - unrealizedExitCost`。

因此，当 `unrealizedProfit` 为负时，不一定代表股票价格明显下跌，也可能主要来自买入滑点、买入手续费和预估卖出成本。

## Sharpe 口径

当前 `Sharpe` 使用短线交易周期口径：

```text
tradeSharpe = 平均单笔收益 / 单笔收益标准差
Sharpe      = tradeSharpe * sqrt(252 / targetHoldingDays)
```

默认 `targetHoldingDays=5`，所以报告中的 `sharpeMethod` 为：

```text
trade_return_cycle_5d
```

该指标只适合在相同数据集、相同快照类型、相同持仓周期和相同交易成本设置下比较。交易笔数很少时，Sharpe 只能作为参考。

## 单票回放解释

单票回放优先展示交易事件，并补充 RankTrend 细节：

- 时间使用可读日期时间；
- 价格保留 2 位小数；
- 显示动作、排名、信心、持有 bars；
- 显示候选池分层、生命周期阶段和市场环境；
- 解释包含技术信号、多周期动量、风险压力、策略原因、入场或退出原因。

看到 MACD 金叉或死叉时，应理解为辅助观察信息，不应理解为机械买卖依据。

## 当前限制

- 样本期较短时，交易笔数可能很少，收益和 Sharpe 容易受少数交易影响；
- 当前回测仍是研究平台，已经按可用字段处理涨跌停、盘口价、容量约束和盘中高低价触发，但仍不是逐笔/逐档队列级实盘撮合；
- Golden 对齐仍以 TypeScript RankTrend 为唯一标准，Python 自基线只能用于临时回归检查；
- 历史 `bt_xxx` 报告不会因为代码升级自动回填新字段，需要重新运行回测。

## 报告新增诊断

当前报告会额外输出：

- `sampleDiagnostics`：样本数量、样本质量状态分布、MACD 稳定观察窗口；
- `macdDiagnostics`：MACD 参数、最小 bars、稳定观察 bars、辅助观察定位；
- `tradeDiagnostics`：按出场原因和 RankTrend 分层汇总的交易贡献、最好/最差交易、未平仓明细；
- `matchingDiagnostics`：盘口覆盖、快照价回退、涨跌停/流动性导致的未成交和部分成交；
- `controlBacktests`：上述对照组表现。
