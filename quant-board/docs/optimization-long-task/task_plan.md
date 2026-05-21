# QuantBoard 长任务优化计划

## Goal

在 `dragonboard_live` 的 `half_hour` 正式快照口径上，完成可复现、可追溯的 RankTrend 基线回测与第一轮参数优化，并产出只作为候选的参数研究结论。

## Current Phase

Phase 8

## Success Criteria

1. MongoDB 主库和 QuantBoard 后端健康可判定。
2. `dragonboard_live` 数据集信息已记录，默认研究口径保持 `snapshot_type=half_hour`。
3. `current_bar` 与 `next_bar` 两个基线 run 已落库并记录核心指标。
4. 第一轮优化任务通过后端 API 启动，保留 `dataset_id`、`snapshot_type`、`strategy_name`、`random_seed`、`config_hash`。
5. 优化结果只输出候选参数和风险解释，不自动写回默认参数。

## Phases

### Phase 1: Health & Dataset Discovery

- [x] 检查 `GET /api/health?deep=true`
- [x] 列出当前数据集
- [x] 记录主数据集、覆盖区间和样本量
- **Status:** complete

### Phase 2: Baseline Backtests

- [x] 跑 `current_bar` 兼容基线
- [x] 跑 `next_bar` 保守基线
- [x] 记录收益、回撤、胜率、交易数、质量报告
- **Status:** complete

### Phase 3: Optimization Plan & Launch

- [x] 落地 planning-with-files 文档
- [x] 用后端 API 启动第一轮优化任务
- [x] 记录 `optimization runId`
- **Status:** complete

### Phase 4: Monitoring & Result Review

- [x] 轮询 `GET /api/optimizations/{run_id}`
- [x] 记录完成状态、best trial、warnings 和质量提示
- [x] 若失败，记录结构化错误并调整方案
- **Status:** complete

### Phase 5: Next Decision

- [x] 对比 `current_bar`、`next_bar`、优化候选结果
- [x] 给出第二轮长任务建议
- [x] 明确是否需要扩大 trials、切换 `tpe/bayesian` 或增加样本外窗口
- **Status:** complete

### Phase 6: Quarter-Hour Research Optimization

- [x] 用 `quarter_hour` 显式研究口径启动一轮优化
- [x] 记录 runId、样本切分、best trial、质量和过拟合风险
- [x] 明确该结果不能直接覆盖 `half_hour` 默认参数
- **Status:** complete

### Phase 7: Long-Horizon Test Plan

- [x] 合并 `half_hour` 与 `quarter_hour` 证据
- [x] 制定后续长测数据积累、定期复跑和采用门槛
- [x] 标记哪些结论可用于观察，哪些可进入候选参数复核
- **Status:** complete

### Phase 8: Long-Test Baseline Automation

- [x] 新增一键复跑三条固定基线的最小 CLI 入口
- [x] 结构化记录每条 run 的核心指标、质量和配置追溯字段
- [x] 执行一次当前 checkpoint，并把结果追加到长测记录
- **Status:** complete

## Optimization Setup

第一轮优化使用保守但不太重的配置：

```text
dataset_id      = dragonboard_live
snapshot_type   = half_hour
strategy_name   = rank_trend_candidate
method          = tpe
objective       = stability
trials          = 36
random_seed     = 20260430
validation_mode = auto
validation_ratio = 0.3
walk_forward.enabled = true
walk_forward.trainWindowDays = 5
walk_forward.validationWindowDays = 1
walk_forward.stepDays = 1
walk_forward.topTrials = 5
```

## Assumptions

- 用户希望先启动一轮可控长任务，而不是先修改优化代码。
- 默认研究口径继续使用 `half_hour`，不把 `quarter_hour` 作为默认。
- 优化结果只作为候选参数，不自动更新 Python、TypeScript、API、CLI、前端默认值或文档默认值。
- `estimated_l1` 或缺失资金流不作为正式资金流策略依据；本轮 RankTrend 基线报告中的资金流缺失只作为数据质量风险记录。

## Decisions Made

| Decision | Rationale |
| --- | --- |
| 用后端 API 启动优化任务 | API 的异步任务运行在后端进程线程池中，适合长任务；一次性 CLI `--no-wait` 不适合作为持久后台任务入口。 |
| 第一轮使用 `method=tpe` | 比 grid 更适合中等搜索空间，固定 seed 后可复现；比 bayesian 更轻。 |
| 目标函数使用 `stability` | 当前样本质量为 `degraded`，单看收益或胜率容易过拟合。 |
| 先保留 `current_bar` 与 `next_bar` 两条基线 | `current_bar` 对齐页面兼容口径，`next_bar` 用于保守评估乐观偏差。 |

## Active Runs

| Type | Run ID | Status | Notes |
| --- | --- | --- | --- |
| Optimization | `opt_70e72a69c40143be` | completed | `tpe + stability + 36 trials + auto validation + walk-forward` |
| Quarter-hour research optimization | `opt_fcf1f30063514bb7` | completed | `grid + stability + 27 trials + next_bar + walk-forward` |
| Long-test checkpoint | `checkpoint_2026-05-21_initial` | completed | 三条固定基线，摘要追加到 `quant-board/data/reports/long_test_runs.jsonl` |

## First Optimization Result

| Field | Value |
| --- | --- |
| `runId` | `opt_70e72a69c40143be` |
| `status` | `completed` |
| `optimizer` | `optuna_tpe` |
| completed trials | `36` |
| failed trials | `0` |
| best trial | `trial_0001` |
| best parameters | `maxPositions=8`, `stopLoss=-0.06`, `takeProfit=0.16` |
| train total return | `0.0502` |
| train Sharpe | `0.8212` |
| validation total return | `0.0042` |
| validation Sharpe | `-0.2893` |
| validation max drawdown | `-0.0241` |
| validation trade count | `23` |
| overfit risk | `high` |

## Next Recommendation

不要把 `trial_0001` 写回默认参数。当前第一轮优化说明：在 23 个交易日、`researchGrade=degraded` 的样本上，TPE 找到的最优候选只有轻微 validation 正收益，且 train 明显优于 validation，过拟合风险为 `high`。

下一轮建议优先做“验证方案”而不是“继续放大搜索”：

1. 用 `next_bar` 保守成交口径，对 top 3 参数单独复跑全样本和 validation 区间。
2. 固定参数搜索空间，改用显式日期切分做一轮复核，避免 auto split 偶然性。
3. 等正式快照样本继续积累后再扩大到 `72+ trials` 或切换 `bayesian`。

## Quarter-Hour Research Setup

第二轮按用户确认，使用 `quarter_hour` 作为研究口径。它可以帮助观察更长历史和更细粒度信号，但不能直接替代 `half_hour` 默认参数。

```text
dataset_id       = dragonboard_live
snapshot_type    = quarter_hour
strategy_name    = rank_trend_candidate
method           = grid
objective        = stability
max_trials       = 27
random_seed      = 20260430
validation_mode  = auto
validation_ratio = 0.3
execution_mode   = next_bar
maxHoldingBars   = 80
targetHoldingDays = 5
walk_forward.enabled = true
walk_forward.trainWindowDays = 10
walk_forward.validationWindowDays = 2
walk_forward.stepDays = 2
walk_forward.topTrials = 5
```

选择 `grid` 的原因：默认搜索空间是 `maxPositions * takeProfit * stopLoss = 27` 组，grid 可以完整穷举，避免 TPE 在小空间内重复采样。

## Quarter-Hour Research Result

| Field | Value |
| --- | --- |
| `runId` | `opt_fcf1f30063514bb7` |
| `status` | `completed` |
| `optimizer` | `grid` |
| completed trials | `27` |
| failed trials | `0` |
| best trial | `trial_0007` |
| best parameters | `maxPositions=3`, `stopLoss=-0.04`, `takeProfit=0.16` |
| train total return | `0.0199` |
| train Sharpe | `-0.3355` |
| validation total return | `-0.0226` |
| validation Sharpe | `-1.5002` |
| validation max drawdown | `-0.0536` |
| validation trade count | `31` |
| overfit risk | `high` |

结论：`quarter_hour` 样本更多，但在 `next_bar` 保守成交和稳定性目标下，validation 全部偏弱，最佳 trial 仍为负收益。它不支持直接定参，只能说明当前策略在最近 validation 阶段处于不利市场/信号环境。

## Long-Horizon Test Plan

### 1. 固定三条基线，不频繁换口径

每次新增交易日后保留三条固定复跑：

| Baseline | Snapshot | Execution | Purpose |
| --- | --- | --- | --- |
| H1 | `half_hour` | `current_bar` | 对齐页面兼容口径，观察策略乐观上限 |
| H2 | `half_hour` | `next_bar` | 正式默认口径的保守验收主线 |
| Q1 | `quarter_hour` | `next_bar` | 研究口径，用于更细粒度压力测试 |

### 2. 暂停扩大参数搜索，先做滚动复核

短期不要继续扩大到 `72+ trials` 或 `bayesian`。当前两个优化 run 都显示 `overfitRisk=high`，继续放大搜索更可能强化样本内贴合。

优先执行：

1. 每周新增样本后复跑固定三条基线；
2. 每满 `5` 个交易日，复跑一次 `quarter_hour grid 27`；
3. 每满 `10` 个 half-hour 交易日，复跑一次 `half_hour tpe/grid`；
4. 只有连续两轮 validation 和 walk-forward 都改善，才把候选参数列入人工复核。

### 3. 参数采用门槛

任何候选参数进入默认配置前，至少满足：

- `half_hour next_bar` validation 总收益为正；
- validation Sharpe 大于 `0`；
- validation 最大回撤不劣于当前保守基线；
- trade count 不低于 `30`；
- walk-forward 多数 segment 不为负；
- `overfitRisk` 不高于 `medium`；
- `researchGrade` 不为 `blocked`，并记录资金流缺失风险。

### 4. 当前候选状态

- `half_hour` 候选：`maxPositions=8` 有观察价值，但 validation 只 `+0.42%`，不采用。
- `quarter_hour` 候选：`maxPositions=3`、`takeProfit=0.16` 在相对排名靠前，但 validation 为 `-2.26%`，不采用。
- 两条口径都显示 `takeProfit=0.16` 在 top trials 中较常出现，可作为后续观察项，不是默认参数。

## Long-Test Automation

已新增 CLI：

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines --checkpoint-id checkpoint_2026-05-21_initial
```

固定输出到 `quant-board/data/reports/long_test_runs.jsonl`，每行是一个 checkpoint。三条基线分别为：

| Label | Snapshot | Execution | Max holding bars |
| --- | --- | --- | ---: |
| `H1_half_hour_current_bar` | `half_hour` | `current_bar` | `40` |
| `H2_half_hour_next_bar` | `half_hour` | `next_bar` | `40` |
| `Q1_quarter_hour_next_bar` | `quarter_hour` | `next_bar` | `80` |

### Checkpoint `checkpoint_2026-05-21_initial`

| Baseline | Run ID | totalReturn | realizedReturn | maxDrawdown | Sharpe | winRate | trades | researchGrade |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| H1 `half_hour/current_bar` | `bt_7493e60c21574bd8` | `+4.49%` | `+5.02%` | `-2.82%` | `-0.0003` | `37.04%` | `54` | `degraded` |
| H2 `half_hour/next_bar` | `bt_923ecfa4517948f4` | `-6.37%` | `-2.71%` | `-9.16%` | `-1.3844` | `34.38%` | `64` | `degraded` |
| Q1 `quarter_hour/next_bar` | `bt_359953a7dba24206` | `-3.27%` | `-0.10%` | `-11.06%` | `-0.5817` | `46.03%` | `126` | `degraded` |

解读：当前 checkpoint 仍不支持写回默认参数。`quarter_hour` 的交易数更高，但回撤更深，说明更细粒度样本没有自动改善保守成交表现。

## Errors Encountered

| Error | Attempt | Resolution |
| --- | --- | --- |
| 暂无 | 1 | 暂无 |
