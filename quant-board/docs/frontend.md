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
   - 导入入口；
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

## 回测表单

首期字段：

- 数据集；
- 快照类型；
- 开始日期；
- 结束日期；
- 初始资金；
- 最大持仓数；
- 单票仓位；
- 止损；
- 止盈；
- 最大持有 bars；
- 目标持仓天数；
- MACD 快线、慢线、信号线；
- 风险压力阈值；
- 随机种子。

默认展示值：

```text
targetHoldingDays = 5
maxHoldingBars = 40
macdFast/macdSlow/macdSignal = 21/34/13
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
- `tradeDiagnostics`：按出场原因和 RankTrend 分层统计利润贡献。

这些字段用于复盘和排错，不改变 RankTrend 策略算法。

## 优化页

优化结果必须同时展示：

- train 指标；
- validation 指标；
- score；
- 交易数；
- 参数摘要；
- 过拟合风险提示。

高胜率但交易数过少的 trial 要有明显标识，避免误判。

## 状态与错误

前端要展示后端结构化错误：

- `QUALITY_GATE_FAILED`
- `DATASET_NOT_FOUND`
- `INVALID_SNAPSHOT_TYPE`
- `GOLDEN_MISMATCH`
- `BACKTEST_FAILED`

不要把错误吞成空图表。

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
