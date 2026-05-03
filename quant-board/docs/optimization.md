# 参数优化设计

## 定位

QuantBoard 的参数优化是研究工具，不是自动改策略默认值的工具。优化结果只能生成候选参数，必须经过样本外验证后，人工决定是否采用。任何优化任务都不得自动写回 Python、TypeScript、API、CLI 或前端表单的默认参数。

优化是 QuantBoard 后端的独立模块，职责边界在 `backend/optimization/**`：搜索方法、目标函数、任务状态和实验记录都放在该模块内维护。`runner.py` 只做入口编排，搜索空间、采样器、trial 执行、评分、验证、walk-forward 和稳定性分析分别由独立模块承载。优化模块只调用 QuantBoard Python 回测引擎执行 trial，不把搜索逻辑塞回 `backend.core.backtest`。Dragon Board 根项目不提供参数搜索、交易模拟或优化入口。

## 输入

```json
{
  "dataset_id": "ds_20260430_001",
  "snapshot_type": "half_hour",
  "train_range": ["2026-04-01", "2026-04-20"],
  "validation_range": ["2026-04-21", "2026-04-30"],
  "strategy_name": "rank_trend_candidate",
  "strategy_version": "0.1.0",
  "method": "bayesian",
  "random_seed": 20260430,
  "search_space": {},
  "objective": "stability"
}
```

没有显式传入 `snapshot_type` 时使用 `half_hour`。正式搜索方法是 `grid`、`random`、`bayesian`、`tpe`。`optuna_tpe` 只作为后端兼容别名保留，不在前端和 CLI 作为独立方法展示。搜索方法的详细计算口径、结果字段和使用方法见 [search-methods.md](search-methods.md)。

## 可优化参数

首期建议从交易层参数开始，不先改 rankTrend golden 算法参数：

- `entry_candidate_tiers`
- `min_final_confidence`
- `max_risk_pressure`
- `max_positions`
- `position_size`
- `stop_loss`
- `take_profit`
- `max_hold_bars`

rankTrend 运行参数可以作为第二阶段开放：

- `macdFast`
- `macdSlow`
- `macdSignal`
- `buyScoreThreshold`
- `sellScoreThreshold`
- 权重参数

开放 rankTrend 参数前，必须保证 Python 与 golden 对齐测试稳定。

## 搜索方法

### grid

离散网格搜索。适合首期实现，优点是可解释、可复现。

要求：

- 生成候选参数顺序稳定；
- 记录总组合数和实际执行数；
- 支持 `max_trials` 截断；
- 每个 trial 都有独立 `config_hash`。

### random

随机搜索。适合较大空间。

要求：

- 必须传入或生成 `random_seed`；
- 使用本地可控随机源；
- 报告记录采样到的参数。

### bayesian

`method=bayesian` 表示 Optuna `GPSampler` 高斯过程优化，不再等同于 TPE。它用于样本成本较高、希望用代理模型平衡探索和利用的搜索场景。

要求：

- `optimizer=optuna_gp` 写入结果；
- `optimizerMeta.sampler=GPSampler` 写入结果；
- `optimizerMeta.model=gaussian_process` 写入结果；
- 固定 `random_seed` 时 trial 序列可复现；
- 每个 trial 保留 `optunaTrialNumber` 和 `optunaParams`。

### tpe

Optuna TPE 采样保留为正式搜索方法 `tpe`。旧配置里的 `optuna_tpe` 仅作为后端兼容别名，不在前端和 CLI 展示为独立方法。所有搜索空间仍按离散 choices 处理，Optuna trial 会先采样每个参数的索引，再映射回真实参数值。

要求：

- `optimizer=optuna_tpe` 写入结果；
- `optimizerMeta.sampler=TPESampler` 写入结果；
- 后端兼容别名 `method=optuna_tpe` 与 `method=tpe` 的结果口径一致；
- 固定 `random_seed` 时 trial 序列可复现；
- 每个 trial 保留 `optunaTrialNumber` 和 `optunaParams`。

## 目标函数

建议首期支持：

| objective | 排序逻辑 |
| --- | --- |
| `return` | 总收益优先，回撤作为惩罚 |
| `win_rate` | 胜率优先，但惩罚交易数过少 |
| `risk_adjusted` | Sharpe、回撤、收益综合 |
| `stability` | 样本内和样本外都稳定 |

默认建议：

```text
objective = stability
```

`stability` 示例：

```text
score = validation_return
      - 1.5 * validation_max_drawdown
      + 0.2 * validation_sharpe
      - overfit_penalty
      - low_trade_count_penalty
```

具体公式可以迭代，但必须写入 `result_json`，不能只保存最终分数。

## 防过拟合

必须区分：

- train：搜索参数；
- validation：验证候选；
- holdout：最终人工评估，可后续加入。

当前实现已经支持：

- `validation_mode=auto`：按时间顺序把后段样本作为 validation；
- `validation_ratio`：控制自动 validation 占比；
- `validation_warmup_bars`：validation 计算 RankTrend 信号时向前带入预热 bars；
- `train_range` / `validation_range`：显式日期区间，适合固定样本外窗口。
- `walk_forward.enabled=true`：按交易日滚动验证 Top trials，并记录每段 train/validation 表现。

当前 walk-forward 的实现口径是“Top trials 滚动复核/重选”：先在主 train/validation 流程里完成搜索，再把排名靠前的 trials 放入滚动窗口逐段验证，并在每段中选择验证表现最好的候选。它不是每个滚动窗口都重新完整跑一遍 grid/random/Optuna 搜索。这个口径适合首期控制耗时和复现复杂度；如果后续要做严格 walk-forward re-optimization，需要在每个 segment 内重新生成 trials，并单独记录 segment 级搜索空间、seed 和 config hash。

## API 任务状态

优化任务按异步任务处理：

- `POST /api/optimizations/rank-trend` 只创建任务并返回 `status=running` 和 `runId`，不要求同步返回完整 trial 结果；
- `GET /api/optimizations/{run_id}` 返回任务当前状态，`status` 只能是 `running`、`completed` 或 `failed`；
- `running` 状态可以返回已完成 trial 的进度预览，但 `best` 只能作为临时候选；
- `completed` 状态返回完整 `result_json`；
- `failed` 状态必须返回结构化错误原因，不能返回空结果冒充成功。

首期至少要支持 train/validation。只跑全样本优化的结果必须标记：

```json
{
  "overfit_risk": "high",
  "reason": "未设置 validation_range"
}
```

## 实验记录

使用已有表：

```text
optimization_runs
```

当前 `result_json` 包含：

```json
{
  "experiment": {
    "split": {
      "mode": "auto_split",
      "hasValidation": true
    },
    "overfitRisk": {
      "level": "medium",
      "reason": "validation 交易数偏少。"
    }
  },
  "status": "completed",
  "optimizer": "optuna_gp",
  "optimizerMeta": {
    "sampler": "GPSampler",
    "model": "gaussian_process"
  },
  "best": {
    "trialId": "trial_0001",
    "parameters": {},
    "train": {"runId": "bt_...", "metrics": {}},
    "validation": {"runId": "bt_...", "metrics": {}},
    "score": 0.82
  },
  "trials": [
    {
      "trialId": "trial_0001",
      "parameters": {},
      "configHash": "sha256...",
      "train": {"runId": "bt_..."},
      "validation": {"runId": "bt_..."},
      "scoreDetails": {},
      "score": 0.71,
      "status": "completed"
    }
  ],
  "walkForward": {
    "enabled": true,
    "segmentCount": 3,
    "aggregate": {
      "positiveReturnSegmentRate": 0.6667
    }
  },
  "parameterStability": {},
  "warnings": []
}
```

每个 trial 的 train/validation `runId` 都会落到 `backtest_runs`，可通过回测报告接口或 CLI 继续追溯交易、权益曲线和退出原因。

## 并发与缓存

首期先单进程串行，确保正确性。后续可加：

- 相同 `config_hash` 的回测复用；
- trial 并行；
- 失败 trial 重试。

缓存命中必须保证 `dataset_id`、`snapshot_type`、日期区间、策略版本、参数完全一致。

## 输出解释

优化结果页面和 CLI 输出要强调：

- 排名第 1 只是本次搜索空间内最好；
- 样本内好不代表实盘有效；
- `quarter_hour` 优化结果不能直接套到 `half_hour`；
- 交易数过少的高胜率要降权。
- 如果 `dataQuality.researchGrade=degraded` 或 `warnings` 包含低热榜/样本质量提示，优化结果只能作为候选参数线索，不能直接定参数。
- 优化完成后不会自动写回默认参数；采用任何候选参数都必须人工复核、另行修改配置并记录原因。

## 测试清单

- 固定随机种子时随机搜索结果一致。
- 空搜索空间能返回清晰错误。
- 参数非法会被拒绝或归一化并记录。
- 同一 trial 不产生 `NaN` 指标。
- validation 缺失时报告过拟合风险。
- 默认快照是 `half_hour`。
