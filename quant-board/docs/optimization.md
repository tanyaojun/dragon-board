# 参数优化设计

## 定位

QuantBoard 的参数优化是研究工具，不是自动改策略默认值的工具。优化结果只能生成候选参数，必须经过样本外验证后，人工决定是否采用。

`ParameterOptimizer` 已废弃为基准。首期优化引擎只调用 Python 回测引擎。

## 输入

```json
{
  "dataset_id": "ds_20260430_001",
  "snapshot_type": "half_hour",
  "train_range": ["2026-04-01", "2026-04-20"],
  "validation_range": ["2026-04-21", "2026-04-30"],
  "strategy_name": "rank_trend_candidate",
  "strategy_version": "0.1.0",
  "method": "grid",
  "random_seed": 20260430,
  "search_space": {},
  "objective": "stability"
}
```

没有显式传入 `snapshot_type` 时使用 `half_hour`。

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

当前实现使用 Optuna `TPESampler`，不是随机候选打乱。所有搜索空间仍按离散 choices 处理，Optuna trial 会先采样每个参数的索引，再映射回真实参数值。

要求：

- `optimizer=optuna_tpe` 写入结果；
- `optimizerMeta.sampler=TPESampler` 写入结果；
- 固定 `random_seed` 时 trial 序列可复现；
- 每个 trial 保留 `optunaTrialNumber` 和 `optunaParams`。

### local

基于当前最优参数做小步扰动。可作为“局部优化”，但不要命名为严格贝叶斯优化，除非真正实现高斯过程或等价代理模型。

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
  "optimizer": "optuna_tpe",
  "optimizerMeta": {
    "sampler": "TPESampler"
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

## 测试清单

- 固定随机种子时随机搜索结果一致。
- 空搜索空间能返回清晰错误。
- 参数非法会被拒绝或归一化并记录。
- 同一 trial 不产生 `NaN` 指标。
- validation 缺失时报告过拟合风险。
- 默认快照是 `half_hour`。
