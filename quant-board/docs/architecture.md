# QuantBoard 架构设计

## 架构目标

首期架构只服务一个核心闭环：

`dragon-board 快照数据 -> QuantBoard 数据集 -> Python rankTrend -> 回测 -> 优化 -> API/CLI/前端报告`

这里的 Python rankTrend 必须对齐 TypeScript golden 标准。QuantBoard 是仓库内唯一回测平台，Dragon Board 根项目只提供实时看板、快照数据和 TypeScript golden 导出。

## 模块分层

```text
backend/
  data/                 # 数据库、快照导入、质量门禁、数据查询
  ranktrend/            # Python 版 rankTrend 分析链
  core/
    strategy/           # 策略接口和 rankTrend 候选策略
    engine/             # 回测事件循环、撮合、绩效统计
    portfolio/          # 现金、持仓、交易成本、风控
  optimization/         # 参数搜索、目标函数、实验记录
  api/                  # FastAPI 路由
  cli/                  # 命令行入口
  reports/              # 报告导出辅助
```

当前仓库已有 `backend/main.py`、`backend/settings.py`、`backend/data/database.py`、`backend/data/models.py`，后续实现应在这些骨架上增量补齐。

## 数据流

1. 导入阶段
   - 输入：dragon-board 导出的 IndexedDB JSON、备份文件或后续直连读取结果。
   - 输出：`datasets`、`snapshot_records`、`snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows`。

2. 分析阶段
   - 输入：按 `dataset_id + snapshot_type + date range` 查询的标准快照序列。
   - 输出：Python rankTrend 结果，结构对齐 golden case。

3. 策略阶段
   - 输入：每个快照、每只股票的 rankTrend 结果和行情字段。
   - 输出：候选标的、入场/离场意图、解释原因。

4. 回测阶段
   - 输入：策略信号、价格、交易配置、随机种子。
   - 输出：权益曲线、交易列表、绩效指标、诊断信息。

5. 优化阶段
   - 输入：参数搜索空间、目标函数、训练/验证区间。
   - 输出：候选参数排名、样本内/样本外表现、实验记录。

6. 展示阶段
   - 输入：`backtest_runs`、`optimization_runs`、报告 JSON。
   - 输出：API、CLI、前端图表。

## 关键数据库表

### datasets

记录一个可复现实验数据集：

- `id`：数据集 ID，例如 `ds_20260430_half_hour_import01`
- `source_type`：`indexeddb_export`、`json_backup`、`manual_fixture`
- `schema_fingerprint`：导入结构指纹
- `snapshot_count`、`frame_count`、`stock_row_count`
- `start_date`、`end_date`
- `snapshot_types_json`

### snapshot_records

保留原始快照记录，方便追溯和重新投影。正式分析不应直接扫描大 payload，而应优先读 frame/row 表。

### snapshot_frames

一条标准快照一行，保存市场摘要和统计上下文。

### snapshot_stock_rows

一条快照内的一只股票一行，是 rankTrend、回测、前端列表的主要事实表。

### snapshot_sector_rows

一条快照内的板块、题材、主线实体一行。首期可先导入，策略使用可后置。

### golden_ranktrend_cases

保存 TypeScript golden 输入和期望输出。Python 移植必须用它做回归校验。

### backtest_runs

保存单次回测请求和结果。必须记录：

- `dataset_id`
- `strategy_name`
- `strategy_version`
- `snapshot_type`
- `config_hash`
- `random_seed`
- `request_json`
- `result_json`

### optimization_runs

保存一次优化实验及候选参数列表。优化不是覆盖默认参数的动作，而是产生可验证候选。

## 配置来源

建议配置分三层：

1. 项目默认值：代码里的保守默认，例如 `snapshot_type=half_hour`。
2. YAML 配置：`config/*.yaml`，用于本地实验。
3. 请求参数：API/CLI 显式传入，优先级最高。

所有最终执行配置都要写入 `request_json`，并用稳定 JSON 计算 `config_hash`。

## 策略边界

首期策略名建议固定为：

```text
rank_trend_candidate
```

策略只消费 Python rankTrend 输出，不直接依赖 dragon-board UI、前端事件或浏览器全局对象。

`src/services/strategyBacktest` 的历史职责归并到 Python 后端：

- 快照回放与样本质量：`backend.data.repository`、`backend.data.quality_gate`
- RankTrend 回放：`backend.analysis.ranktrend.RankTrendPythonEngine`
- 后验分布与 forward validation：`backend.core.backtest.OutcomeEvaluator`
- 交易模拟与撮合：`backend.core.backtest.TradeSimulator`
- 回测编排与优化：`backend.core.backtest.BacktestEngine`、`backend.core.backtest.Optimizer`

策略输出不等于交易指令。它应至少包含：

- 候选分层：`A_MAIN`、`B_IGNITION`、`C_CROWDED`、`D_EXIT_RISK`、`N_NEUTRAL`
- 建议动作：`focus`、`watch`、`hold`、`avoid`、`exit_watch`
- 风险解释
- 样本质量

交易执行由回测引擎根据入场/离场规则统一处理。

## 快照类型原则

默认：

```text
snapshot_type = half_hour
```

支持：

- `half_hour`：首期默认和主要验收口径。
- `quarter_hour`：显式选择的可选研究口径。
- `hourly`、`daily`：可导入和诊断，首期不作为主回测默认。

禁止：

- 在 API、CLI、前端里把 `quarter_hour` 写成默认。
- 在 API、CLI、前端里绕过 QuantBoard 后端另做根项目回测入口。

## 可复现性

同一组输入应能得到同一结果：

- 相同 `dataset_id`
- 相同 `snapshot_type`
- 相同日期区间
- 相同策略版本
- 相同参数
- 相同 `random_seed`

若结果不同，要优先检查排序稳定性、浮点舍入、缺失字段默认值、随机数来源和数据导入顺序。

## 错误处理

所有核心服务返回结构化错误：

```json
{
  "ok": false,
  "error": {
    "code": "QUALITY_GATE_FAILED",
    "message": "样本不足",
    "details": {
      "required_sample_count": 30,
      "actual_sample_count": 12
    }
  }
}
```

不要用空数组、空报告或 `0` 指标假装成功。

## 首期非目标

- 不接实盘交易。
- 不做自动下单。
- 不把优化结果自动写回 dragon-board 默认参数。
- 不在 Dragon Board 根项目重建回测模块。
- 不为了前端演示绕过 golden 校验和质量门禁。
