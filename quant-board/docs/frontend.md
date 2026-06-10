# 前端设计说明

## 定位

QuantBoard 前端是个人量化研究工作台，不是营销页。首期重点是高密度、可扫描、可复盘：

- 数据集管理；
- golden 校验结果；
- 回测运行与报告；
- 参数优化对比；
- 交易明细和权益曲线。

前端可以复用 dragon-board 的 Vue 3 + Vite + TypeScript 经验，但不要直接耦合 dragon-board 运行态 store。

## 页面结构

建议首期页面：

1. 数据集
   - 从 SQLite 快照库生成研究数据集；
   - JSON 文件上传迁移辅助；
   - 数据集列表；
   - 快照类型分布；
   - 日期覆盖；
   - 质量问题。

2. Golden 校验
   - case 列表；
   - 通过/失败统计；
   - 差异详情；
   - Python 与 TypeScript 输出对比。

3. 回测
   - 参数表单；
   - 运行状态；
   - 核心指标；
   - 权益曲线；
   - 回撤曲线；
   - 交易列表；
   - 信号诊断；
   - 对照组回测；
   - 样本与 MACD 诊断；
   - 交易贡献分析。

4. 优化
   - 搜索空间配置；
   - 目标函数选择；
   - trial 结果表；
   - 样本内/样本外对比；
   - 最优参数详情。

5. 报告历史
   - backtest runs；
   - optimization runs；
   - 过滤、排序、打开详情。

## 信息优先级

回测详情页首屏建议展示：

- `dataset_id`
- `snapshot_type`
- 日期区间
- 策略版本
- `config_hash`
- `random_seed`
- `total_return`
- `max_drawdown`
- `win_rate`
- `total_trades`
- `realized_return`
- `unrealized_mark_profit`
- `unrealized_exit_cost`
- `unrealized_profit`
- `open_position_count`

这样能快速判断一次结果是否可复现、是否可比较。

当前回测指标、持仓周期、MACD 定位和未平仓收益口径以 [backtest-policy.md](backtest-policy.md) 为准。

## 快照类型 UI

默认选项必须是：

```text
half_hour
```

`quarter_hour` 可以出现在下拉框，但要作为用户显式选择项。切换快照类型后：

- 清空旧回测结果预览；
- 提示不同快照口径不可直接横向比较；
- 请求体明确传入选中的 `snapshot_type`。

## 数据导入 UI

数据导入区默认只展示两种方式：

- `SQLite 快照库`：日常推荐路径，从后端 `snapshot_*` 正式事实表派生新的研究数据集。
- `JSON 文件上传`：迁移或排障辅助，用于导入历史 JSON/备份文件。

旧的浏览器运行页桥接、LevelDB 和当前页面 IndexedDB 预览不再作为主界面入口。正式快照已经由 Dragon Board 写入 SQLite，QuantBoard 前端不应再引导用户从浏览器存储重复采集。

`SQLite 快照库` 表单字段：

- 源快照数据集，默认 `dragonboard_live`；
- 数据集名；
- 快照类型；
- 开始日期；
- 结束日期；
- 最大快照数，`0` 表示不限制；
- 试运行。

“检查 SQLite 源”只读取四张快照事实表的行数，不生成数据集；“生成数据集”才会创建新的研究 `dataset_id`。

## 回测表单

首期字段（已全部实现，前端 `backtestForm` + 后端 `POST /api/backtests/rank-trend` 合同）：

**基础配置：**
- 数据集 (`datasetId`)
- 快照类型 (`snapshotType`)，默认 `half_hour`
- 策略名称 (`strategyName`)，默认 `rank_trend_candidate`
- 随机种子 (`randomSeed`)，默认 `20260430`

**资金与持仓：**
- 初始资金 (`initialCash`)，默认 1,000,000
- 最大持仓数 (`maxPositions`)，默认 5
- 目标持仓天数 (`targetHoldingDays`)，默认 5
- 最大持有 bars (`maxHoldingBars`)，half_hour 默认 40
- Jump 置信度门槛 (`minJumpConfidence`)，V5 默认 90

**策略层参数：**
- MACD 快线 (`macdFast`)，默认 21
- MACD 慢线 (`macdSlow`)，默认 34
- MACD 信号线 (`macdSignal`)，默认 13
- 动量周期组 (`momentumPeriods`)，默认 `[3, 5, 8, 13, 21]`

**交易管理层参数（V2 Phase 1 优化搜索空间）：**
- Jump 置信度门槛 (`minJumpConfidence`)，V5 默认 90
- 止盈比例 (`takeProfit` / `takeProfitPct`)，默认 0.12
- 止损比例 (`stopLoss` / `stopLossPct`)，默认 0.06

**执行模式：**
- 执行模式 (`executionMode`)：`current_bar`（乐观） / `next_bar`（保守），手工回测默认 `current_bar`，长测 H2 默认 `next_bar`
- 使用盘口价 (`useOrderBookPrice`)，默认 true
- 限制涨停/跌停 (`enforceLimitStatus`)，默认 true
- 限制成交量 (`enforceVolumeLimit`)，默认 true
- 遵守盘口排队 (`enforceOrderBookQueue`)，默认 true
- 允许部分成交 (`allowPartialFills`)，默认 true
- 成交量参与率 (`volumeParticipationRate`)，默认 0.05
- 盘口参与率 (`orderBookParticipationRate`)，默认 0.3
- 使用 K 线内止损 (`useIntrabarStops`)，默认 true
- K 线内止损优先级 (`intrabarAmbiguity`)，默认 `"stop_first"`

**费率：**
- 手续费率 (`feeRate`)，默认 0.0003
- 印花税率 (`stampTaxRate`)，默认 0.0005
- 滑点率 (`slippageRate`)，默认 0.001

**研究过滤（默认关闭）：**
- `excludeNonPositivePriceRows`：剔除 `price <= 0` 行
- `excludeCrossMarketZeroPriceRows`：剔除跨市场/非 A 股零行情行
- `excludeAllZeroPriceFrames`：剔除全帧价格为零的异常快照

默认展示值：
```text
targetHoldingDays = 5
maxHoldingBars = 40
minJumpConfidence = 90
macdFast/macdSlow/macdSignal = 21/34/13
momentumPeriods = [3, 5, 8, 13, 21]
```

前端文案必须明确：MACD 只作为辅助观察信号，不是独立买卖触发器。

表单提交前要做前端校验，但最终以后端校验为准。

## 图表

建议图表：

- 权益曲线；
- 回撤曲线；
- 每日/每快照收益分布；
- 持仓数量曲线；
- 交易盈亏分布；
- 参数优化散点或表格。

图表数据来自 API，不在前端重算核心指标。前端可以做展示格式化。

## 交易列表

交易列表字段：

- 入场时间；
- 出场时间；
- 股票代码和名称；
- 入场价；
- 出场价；
- 数量；
- 盈亏；
- 收益率；
- 持有 bars；
- 入场原因；
- 出场原因；
- RankTrend 候选池分层；
- 生命周期阶段；
- 市场环境；
- 技术信号和动量解释；
- 样本质量；
- 交易成本。

列表需要支持排序和筛选：

- 盈利/亏损；
- 入场 tier；
- 出场原因；
- 日期；
- 股票代码。

## Golden 差异展示

失败时展示：

- case id；
- 字段路径；
- expected；
- actual；
- tolerance；
- 差异值。

不要只显示“校验失败”。Python 移植阶段最需要明确差异路径。

当前页面支持两类 Golden 操作：

- `保存当前输出为基线`：保存 Python 当前输出，只用于临时回归；
- `导入 TS Golden`：选择 TypeScript 端导出的 JSON，按当前 `caseId` 写入后端；
- `执行校验`：读取同一 `caseId`，比较 Python 当前输出和已保存 expected。

正式验收只能以 `source=ts_golden_import` 的用例为准，Python 自基线不能替代 TypeScript golden。

TS Golden 的生成入口在 DragonBoard 当前页面控制台，而不是 QuantBoard 自动打开新页：

```js
await window.quantBoardExportRankTrendGolden({
  caseId: 'rank_trend_default',
  datasetId: 'ds_xxx',
  snapshotType: 'half_hour',
  limit: 500,
  sampleLimit: 100
})
```

执行后下载 JSON，再回到 QuantBoard Golden 页导入。

## 报告诊断展示

回测报告页应展示：

- `controlBacktests`：热榜 Top10、A_MAIN only、B_IGNITION only、A+B；
- `sampleDiagnostics`：快照数、技术最小 bars、样本 OK 占比和诊断提示；
- `macdDiagnostics`：MACD 最小 bars、稳定观察 bars，并明确“辅助观察”；
- `tradeDiagnostics`：按出场原因和 RankTrend 分层统计利润贡献；
- `researchDiagnostics`：展示 1/2/5 bars 后验表现、市场环境 × 候选分层、生命周期 × 候选分层、展示状态分布和对照组表现。页面必须标注其为研究诊断，不得提示用户自动采用参数。

这些字段用于复盘和排错，不改变 RankTrend 策略算法。

Phase 6 起，报告页读取顺序固定为：

1. 先调用 `GET /api/backtests/{run_id}` 或 `GET /api/backtests/{run_id}/report` 读取兼容摘要、请求参数和指标。
2. 再调用 `GET /api/backtests/{run_id}/trades` 分页读取交易列表，字段来源是 `backtest_trades`。
3. 调用 `GET /api/backtests/{run_id}/equity` 读取权益曲线，字段来源是 `backtest_equity_curve`。
4. 调用 `GET /api/backtests/{run_id}/signals?tier=...&regime=...&limit=...&offset=...` 读取信号诊断，字段来源是 `backtest_signals`。
5. 候选池历史视图调用 `GET /api/backtests/{run_id}/fusion-projections`，字段来源是原始 `signals + tradeSimulation.roundTripTrades/trades + tradeEvents/openPositions` 的统一投影。
6. 调用 `GET /api/backtests/{run_id}/quality` 读取质量报告，字段来源是 `backtest_quality_reports`。

交易列表和信号诊断必须分开展示：交易列表只展示真实成交和持仓生命周期，不能用 `signals` 伪造成交；信号表用于解释候选分层、市场状态、过滤原因和风险。权益图只消费后端 API 数据，前端不得重算核心收益指标。

候选池历史视图必须只读 `fusion-projections`：

- 主状态来自 `strategyState`，不能从 `trade_journal.status`、`entryTime` 或 `exitTime` 反推。
- `snapshotType` 默认展示 `half_hour`；只有用户显式切到 `quarter_hour` 时才请求对应 run。
- `trade_journal` 只作为 execution overlay；即使有人工买卖记录，也不能覆盖回测投影里的 `active_holding / exit_signaled / closed`。

归一化回测结果是 QuantBoard 后端 research SQLite 的 `local-only` 数据。前端只调用 QuantBoard API，不直连 SQLite 或 Supabase；Supabase 不作为报告页读取源，也不承担回测报告 failover。若新归一化端点返回 404 或结构化错误，页面应展示错误原因，并可保留旧报告摘要，但不得把缺失明细渲染成空成功状态。

## 优化页

### 基础配置

优化结果必须同时展示：

- train 指标；
- validation 指标；
- score；
- 交易数；
- 参数摘要；
- 过拟合风险提示。

高胜率但交易数过少的 trial 要有明显标识，避免误判。

### 搜索空间（Phase 1：< 60 交易日）

当前阶段只搜索交易管理层参数（策略层参数固定不变）：

| 参数 | 搜索范围 | 说明 |
|---|---|---|
| `maxPositions` | 3, 5, 8 | 最大持仓数 |
| `minJumpConfidence` | 90 | V5 Jump 置信度默认门槛；低于 90 的值只可手动输入做研究对照，不作为默认基线 |
| `takeProfit` | 0.08, 0.12, 0.16 | 止盈比例 |
| `stopLoss` | -0.04, -0.06, -0.08 | 止损比例 |

策略层参数敏感度报告（不纳入搜索，仅作观察）：
- `macdFast`：当前 21，上下扰动 1-2 档观察指标变化
- `macdSlow`：当前 34，同上
- `momentumPeriods`：当前 [3,5,8,13,21]，测试 [5,8,13] 和 [5,10,20]

前端优化表单已实现 `parameterGrid`，支持多动量周期组的并行搜索：
```typescript
parameterGrid: {
  momentumPeriods: [[3,5,8,13,21], [2,4,6,10,16], [5,8,13,21,34]],
  minJumpConfidence: [90],
  takeProfitPct: [0.08, 0.12, 0.16],
  stopLossPct: [0.04, 0.06, 0.08],
  maxPositions: [3, 5, 8],
}
```

`momentumPeriods` 在优化搜索空间中是策略层参数。在 Phase 1（< 60 交易日）阶段，它只出现在优化表单的 `parameterGrid` 中供用户手动配置，不纳入 `default_search_space()`。Phase 2（≥ 60 交易日）才会正式纳入 TPE 搜索。

### 搜索空间（Phase 2：≥ 60 交易日，预计 7 月中）

策略层参数纳入搜索：
- `macdFast`：上下扰动 1-3 档
- `macdSlow`：上下扰动 1-3 档
- `macdSignal`：上下扰动 1-3 档
- `momentumPeriods`：多组周期组合

采用 walk-forward 滚动窗口而非单次切分。

### 双层止损机制（V2 Layer 4）

**条件 A（实盘路径，每期 checkpoint 自动检查）：**
- 当前默认参数 H1 totalReturn 连续 2 期 < 0，且 H2 Sharpe 连续 2 期 < -1
- 触发"实盘策略风险告警"

**条件 B（优化路径，Layer 4 点火后检查）：**
- 连续 2 轮优化，所有 trial validation Sharpe < 当前默认参数
- 触发"搜索空间内无法找到更优参数"

条件 A 或 B 满足任一 → 策略复审。前端应在优化页展示止损状态和复审建议。

### 采用规则（V2 Layer 4）

候选参数满足以下全部条件才标记"可采纳"：
1. 主线 validation Sharpe > 0 且 > 当前默认参数
2. next_bar 交叉验证 totalReturn 不转负
3. quarter_hour 压力测试回撤不恶化 > 5pp

前端展示：默认 vs 候选 × 三线对比表。

### 三线交叉验证

| 口径 | 方法 | 用途 |
|---|---|---|
| half_hour, current_bar | TPE, 72 trials | 主线搜索 |
| half_hour, next_bar | top 3 交叉验证 | 排除乐观偏差 |
| quarter_hour, next_bar | top 3 压力测试 | 排除粒度敏感 |

### 过拟合风险级别

优化结果中的 `overfitRisk.level` 为：
- `low`：train 与 validation 指标接近
- `medium`：存在一定 train/validation 差距
- `high`：train 显著优于 validation

前端应针对 `high` 级别给出醒目警告。

## 状态与错误

前端要展示后端结构化错误：

- `QUALITY_GATE_FAILED`
- `DATASET_NOT_FOUND`
- `INVALID_SNAPSHOT_TYPE`
- `GOLDEN_MISMATCH`
- `BACKTEST_FAILED`

不要把错误吞成空图表。

## V2 四层决策框架面板

后端已产出 Layer 1-3 诊断数据并写入长测 JSONL。前端展示为待开发项。

### Layer 1：信号有效性面板

数据来源：`dataQuality.layer1SignalEfficacy`。

展示字段：
| 字段 | 含义 | 绿灯门槛 |
|---|---|---|
| `tierRatio` | (A_MAIN + B_IGNITION) / 总信号 | 2% ~ 15% |
| `directionAccuracy` | A_MAIN 信号下一 bar 上涨比例 | > 55% |
| `binomialPValue` | 二项检验 p 值 | < 0.10 |
| `tierDiscrimination` | A_MAIN 精度 - N_NEUTRAL 精度 | > 5pp |
| `layer1Status` | 综合判定 | green / red |

状态视觉：
- 绿灯：四项全达标
- 红灯：任一不达标（显示具体不达标指标）
- 熔断警告：跨期检查显示连续 3 期红灯时展示告警横幅

### Layer 2：执行质量面板

数据来源：`dataQuality.layer2ExecutionQuality`（H1/H2 基线含）。

展示字段：
| 字段 | 含义 | 绿灯门槛 |
|---|---|---|
| `bias` | H1 - H2 收益偏差 | < min(\|H1\|, 15pp) |
| `biasThreshold` | 当前期偏差阈值 | — |
| `directionRatio` | 近 4 期 H1 ≥ H2 比例 | ≥ 75% |
| `tradeCountDiff` | H2 - H1 交易数差异 | < H1 的 30% |
| `drawdownDiff` | H1 - H2 回撤差异 | < 5pp |
| `layer2Status` | 综合判定 | green / yellow / red |

状态视觉：
- 绿灯：current_bar 和 next_bar 无显著偏差
- 黄灯：H1 > H2 但偏差超阈值（乐观偏差，实盘可能不可复现）
- 红灯：H2 反超 H1（next_bar 更优，当前入场在追高/抢跑）

### Layer 3：实盘对齐面板

数据来源：`GET /api/backtests/alignment`，或 checkpoint JSONL 的 `layer3Alignment`。

展示内容：
- 数据覆盖：本期候选 N 只 / 已执行 M 只 / 回测信号 K 只
- 标的重合度：交集 L 只 / 交集加权收益
- 执行偏差（待数据积累）
- 最小样本标识：执行记录 < 10 笔 → "数据不足，暂不判定"
- 对齐状态：`sufficient` / `insufficient_data` / `unavailable`

### 跨期状态追踪面板

数据来源：checkpoint JSONL 的 `crossPeriod` 字段。

展示内容：
- L1 熔断指示器：连续红灯期数，≥ 3 → 策略结构性复审告警
- L3 趋势指示器：连续 sufficient 期数，≥ 2 → 对齐绿灯

### 回测报告扩展

回测详情页新增诊断区域：

1. **数据质量统一入口**：展示 `dataQuality` 的 `severity`、`researchGrade`、`recommendation`
2. **价格质量诊断**（`reportOnlyDiagnostics.priceQuality`）：
   - `crossMarketZeroPriceRows`：跨市场/非 A 股零行情行数和受影响快照数
   - `allZeroPriceFrames`：全零异常帧数
   - `partialAshareZeroPriceRows`：A 股局部报价缺失行数
   - 标注 `role=report_only`，不改变过滤和交易逻辑
3. **合成 bar 标记**：合成帧（`captureMode: "synthesized"`）在页面展示时应有视觉区分（如浅色背景或标记图标），提示用户该帧数据来自线性插值补齐

## 长测 Checkpoint 趋势页（待开发）

目标：展示多个 checkpoint 的 Layer 1-3 指标走势。

数据来源：`quant-board/data/reports/long_test_runs.jsonl`。

建议展示：
- H1/H2/Q1 收益趋势折线图
- Sharpe 趋势对比
- Layer 1 方向精度趋势（含 55% 参考线）
- Layer 2 偏差趋势（含阈值参考线）
- Layer 3 对齐状态时间线
- 熔断/绿灯标注点
- okShare 和样本量趋势

长测页应提供 checkpoint 选择器，支持加载任意历史 checkpoint 的完整报告。

## 候选池执行记录

候选池面板（`CandidatePoolPanel.vue`）已实现 V2 Layer 3 的 7 个执行字段表单：

| 字段 | 类型 | 含义 |
|---|---|---|
| `entryPrice` | float | 实际买入价 |
| `entryTime` | str (ISO 8601) | 实际买入时间 |
| `exitPrice` | float | 实际卖出价 |
| `exitTime` | str (ISO 8601) | 实际卖出时间 |
| `stopLossPrice` | float | 设置的止损线 |
| `takeProfitPrice` | float | 设置的止盈线 |
| `positionPct` | float | 仓位占比 |

这些字段在复盘卡片内以"执行记录"区域展示，通过 `POST/PUT /api/journal/entries` 持久化到 MongoDB `trade_journal` 集合。

这里的执行记录只属于 execution overlay：

- 可以补充人工实际买卖时间、价格、仓位和复盘备注。
- 不能反推 fusion 主状态。
- 候选池主状态必须来自 `GET /api/backtests/{run_id}/fusion-projections` 或对应 live projection。

## 视觉原则

- 工具型布局，信息密度高但层次清楚。
- 少用大面积装饰和营销式 hero。
- 表格、筛选、图表、详情抽屉优先。
- 卡片只用于独立指标或列表项，不做层层嵌套。
- 关键数字保留单位和小数规则。

## 联调约定

- 所有 API 请求和响应类型在前端建立 TypeScript 类型。
- 后端新增字段默认前端忽略，避免展示崩溃。
- 前端接口按 QuantBoard 当前 API 合同命名；回测、优化和报告展示只调用 QuantBoard 后端。
- 前端展示 `finalSignal` 时必须同时展示 `candidateTier`、风险和样本质量。

## 验收清单

- 默认快照类型显示为 `half_hour`。
- 可显式切换 `quarter_hour`。
- 后端质量门禁失败时前端显示原因。
- 回测报告刷新后可通过 run id 复现展示。
- 优化页能区分 train/validation。
- 所有核心指标无 `NaN`、`Infinity`。
