# QuantBoard 长任务优化计划

## Goal

在 `dragonboard_live` 的 `half_hour` 正式快照口径上，完成可复现、可追溯的 RankTrend 基线回测与第一轮参数优化，并产出只作为候选的参数研究结论。

## Current Phase

Phase 13 in progress

## Success Criteria

1. MongoDB 主库和 QuantBoard 后端健康可判定。
2. `dragonboard_live` 数据集信息已记录，默认研究口径保持 `snapshot_type=half_hour`。
3. `current_bar` 与 `next_bar` 两个基线 run 已落库并记录核心指标。
4. 第一轮优化任务通过后端 API 启动，保留 `dataset_id`、`snapshot_type`、`strategy_name`、`random_seed`、`config_hash`。
5. 优化结果只输出候选参数和风险解释，不自动写回默认参数。
6. 资金流质量统计能解释 `0 formal / 全 missing` 的根因，并用真实数据复核。
7. `price=0` / 非正价格行有独立诊断结论，明确它是否影响当前固定基线成交。
8. 显式 `price<=0` 过滤研究口径已复跑 H1/H2/Q1，并记录过滤前后指标和信号分布。
9. `price=0` 来源已拆分为跨市场无行情与全零异常帧两类研究过滤，并分别复跑 H1/H2/Q1。
10. 默认回测报告包含 report-only 价格质量诊断字段，且不改变默认过滤、收益、质量等级和交易逻辑。

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

### Phase 9: Money-Flow Quality Diagnostics

- [x] 确认 `half_hour` 样本少于 `quarter_hour` 的原因：早期只启用了 IndexedDB 测试快照，且 `quarter_hour` 启用早于 `half_hour`
- [x] 抽样 MongoDB `snapshot_stock_rows`，确认真实历史行里存在资金流来源字段
- [x] 定位回测质量门禁把股票行压成 `snapshotId` only，导致资金流字段在统计前被丢弃
- [x] 最小修复：回测质量门禁只透传资金流来源字段，不改变价格质量门禁和交易逻辑
- [x] 补测试并用真实 `half_hour/next_bar` 回测验证资金流统计恢复
- **Status:** complete

### Phase 10: Non-Positive Price Diagnostics

- [x] 统计 `dragonboard_live` 中 `price <= 0` 行在 `half_hour` 与 `quarter_hour` 的分布
- [x] 抽样定位涉及的交易日、slot、股票代码和是否集中在特定快照
- [x] 检查非正价格行是否进入当前固定基线的实际成交记录
- [x] 给出后续质量门禁建议，但本阶段不改变默认交易逻辑
- **Status:** complete

### Phase 11: Explicit Positive-Price Filter Rerun

- [x] 新增显式研究开关 `excludeNonPositivePriceRows`，默认关闭
- [x] 复跑 H1/H2/Q1 三条 fixed baseline
- [x] 对比过滤前后收益、回撤、Sharpe、交易数和候选层分布
- [x] 记录结论：该过滤只作为显式研究口径，暂不设为默认质量门禁
- **Status:** complete

### Phase 12: Price Quality Attribution Rerun

- [x] 新增显式研究开关：只过滤跨市场/非 A 股/代码失配零行情行
- [x] 新增显式研究开关：只剔除全零价格异常帧
- [x] 分别复跑 H1/H2/Q1 三条 fixed baseline
- [x] 对比两类过滤与全量 `price<=0` 过滤的收益、回撤、交易数和信号分布
- [x] 判断哪一类适合 report-only diagnostic，哪一类可进入后续 formal quality gate 候选
- **Status:** complete

### Phase 13: Report-Only Price Quality Diagnostics

- [x] 新增只读价格质量诊断：`crossMarketZeroPriceRows`、`allZeroPriceFrames`、`partialAshareZeroPriceRows`
- [x] 将诊断透传到 `dataQuality.reportOnlyDiagnostics.priceQuality`
- [x] 确保默认回测不启用任何价格过滤，不改变 `severity/researchGrade`
- [x] 让 long-test 摘要记录该诊断，便于后续 weekly checkpoint 观察
- [x] 补充 API/service 与 helper 测试
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
| Money-flow diagnostic backtest | `bt_1f012ea44bb44092` | completed | `half_hour/next_bar`，用于验证质量统计修复 |
| Positive-price filter checkpoint | `checkpoint_2026-05-21_price_filter` | completed | 显式过滤 `price<=0` 行后复跑 H1/H2/Q1 |
| Cross-market zero-price checkpoint | `checkpoint_2026-05-21_cross_market_zero_filter_v2` | completed | 只过滤跨市场/非 A 股/代码失配零行情行后复跑 H1/H2/Q1；v1 因未隔离全零帧，已被 v2 取代 |
| All-zero frame checkpoint | `checkpoint_2026-05-21_all_zero_frame_filter` | completed | 只剔除全零价格异常帧后复跑 H1/H2/Q1 |

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

### Checkpoint `checkpoint_2026-05-26_weekly`

| Baseline | Run ID | totalReturn | realizedReturn | maxDrawdown | Sharpe | winRate | trades | researchGrade |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| H1 `half_hour/current_bar` | `bt_e98bfe15b70f46c3` | `+3.98%` | `+4.14%` | `-2.82%` | `-0.5615` | `33.85%` | `65` | `degraded` |
| H2 `half_hour/next_bar` | `bt_393b49917ff14962` | `-4.04%` | `-3.77%` | `-9.16%` | `-1.121` | `35.00%` | `80` | `degraded` |
| Q1 `quarter_hour/next_bar` | `bt_c15400995d16466c` | `-2.10%` | `-2.10%` | `-11.06%` | `-0.5124` | `45.75%` | `153` | `degraded` |

vs 5/21 变化：

| 基线 | totalReturn Δ | Sharpe Δ | trades Δ | 趋势 |
| --- | ---: | ---: | ---: | --- |
| H1 | -0.51pp | ↓ | +11 | 最近一周对乐观成交路径不利 |
| H2 | +2.33pp | ↑ | +16 | 保守成交正式验收持续改善 |
| Q1 | +1.17pp | ↑ | +27 | 研究口径同步收窄亏损 |

价格质量诊断（首次落库）：

| 诊断项 | H1/H2 (half_hour) | Q1 (quarter_hour) |
| --- | ---: | ---: |
| crossMarketZeroPriceRows | 1,003 行 / 191 快照 | 2,070 行 / 393 快照 |
| allZeroPriceFrames | 0 帧 | 1 帧 |
| partialAshareZeroPriceRows | 297 行 / 131 快照 | 658 行 / 259 快照 |

资金流 L2 覆盖变化：

| 口径 | formal (5/21) | formal (5/26) | 增长率 |
| --- | ---: | ---: | ---: |
| half_hour | 4,711 | 10,517 | +123% |
| quarter_hour | 8,698 | 19,672 | +126% |

解读：5 个新交易日对 H2 保守成交持续改善（-6.37% → -4.04%），Sharpe 和 winRate 均有小幅提升。资金流 L2 覆盖翻倍。H1 反而回撤，说明最近市场对乐观入场不利。H2 距离参数采用门槛（Sharpe > 0、trade ≥ 30）仍在接近中但尚未达标。继续按周复跑观察。

## Money-Flow Diagnostics

结论：此前回测报告里的 `formalMoneyFlowCount=0`、`estimatedL1MoneyFlowCount=0`、`missingMoneyFlowSourceCount=全部` 不是 MongoDB 源数据全缺，而是回测质量统计前把股票行简化成 `{"snapshotId": ...}`，把 `capitalFlowSource`、`moneyFlowEstimated` 等字段丢掉了。

真实 MongoDB 抽样：

| Snapshot | formal `official_l2` | `estimated_l1` | missing | formal coverage |
| --- | ---: | ---: | ---: | ---: |
| `half_hour` | `4711` | `10802` | `29568` | `10.45%` |
| `quarter_hour` | `8698` | `19770` | `73113` | `8.56%` |

已修复 `BacktestService` 的质量门禁输入，只透传资金流来源字段，避免把历史 `price=0` 行纳入本轮门禁而改变既有回测可运行性。验证回测 `bt_1f012ea44bb44092` 的核心绩效与原 `half_hour/next_bar` 基线一致，资金流统计已恢复为非零。

## Non-Positive Price Diagnostics

本轮只做诊断，不改变默认回测口径。真实 MongoDB 源数据中存在 `price <= 0` 行，但当前固定基线没有用这些行完成实际成交。

| Snapshot | total rows | `price <= 0` | ratio | impacted snapshots | impacted codes |
| --- | ---: | ---: | ---: | ---: | ---: |
| `half_hour` | `45081` | `1165` | `2.58%` | `185` | `99` |
| `quarter_hour` | `101581` | `2673` | `2.63%` | `391` | `331` |

主要来源分两类：

1. 非 A 股或跨市场热榜条目缺行情，例如 `009992` 泡泡玛特、`001810` 小米集团-W、`009988` 阿里巴巴-W、`003690` 美团-W、`000000` 美股占位代码。这些通常有热榜排名，但 `price/change/volume/turnover` 均为 `0`。
2. 早期历史采集异常帧，例如 `quarter_hour:2026-04-03:14:15` 全帧 `187/187` 行价格为 `0`，`quarter_hour:2026-04-01:09:45` 有 `98/185` 行价格为 `0`。

对已落库固定基线的影响：

| Baseline | Run ID | zero-price trade events | zero-price trades | source bad refs |
| --- | --- | ---: | ---: | ---: |
| H1 `half_hour/current_bar` | `bt_7493e60c21574bd8` | `0` | `0` | `0` |
| H2 `half_hour/next_bar` | `bt_923ecfa4517948f4` | `0` | `0` | `0` |
| Q1 `quarter_hour/next_bar` | `bt_359953a7dba24206` | `0` | `0` | `0` |

信号层仍有污染风险：`half_hour` 固定基线中 `price=0` 信号为 `976/37618`，其中 `B_IGNITION=7`、`A_MAIN=0`；`quarter_hour` 固定基线中 `price=0` 信号为 `2568/95585`，其中 `B_IGNITION=29`、`A_MAIN=1`。交易模拟会跳过缺价格成交，但 RankTrend 信号分布和研究解释仍会被这些行轻微污染。

下一步建议：把价格质量收口拆成单独 Phase，而不是立刻打开 fatal 门禁。优先新增研究口径过滤或诊断字段，区分“跨市场热榜无行情”和“整帧采集异常”，再用固定三基线对比过滤前后绩效和信号分布。

## Explicit Positive-Price Filter Rerun

本阶段新增显式研究开关，不改变默认回测行为：

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines `
  --checkpoint-id checkpoint_2026-05-21_price_filter `
  --exclude-non-positive-price-rows
```

### Filtered Checkpoint

| Baseline | Run ID | dropped rows | impacted snapshots | empty snapshots |
| --- | --- | ---: | ---: | ---: |
| H1 `half_hour/current_bar` | `bt_a5e56233f6fb4805` | `1165` | `185` | `0` |
| H2 `half_hour/next_bar` | `bt_801abe6f44e146df` | `1165` | `185` | `0` |
| Q1 `quarter_hour/next_bar` | `bt_56d52c783fd84776` | `2673` | `391` | `1` |

Q1 的空帧为 `quarter_hour:2026-04-03:14:15`，即此前诊断中的全零价异常帧。

### Metrics Before vs After

| Baseline | totalReturn before -> after | maxDrawdown before -> after | Sharpe before -> after | trades before -> after |
| --- | ---: | ---: | ---: | ---: |
| H1 | `+4.49%` -> `+6.47%` | `-2.82%` -> `-2.81%` | `-0.0003` -> `0.4117` | `54` -> `54` |
| H2 | `-6.37%` -> `-2.47%` | `-9.16%` -> `-5.52%` | `-1.3844` -> `-0.8583` | `64` -> `64` |
| Q1 | `-3.27%` -> `-3.26%` | `-11.06%` -> `-14.67%` | `-0.5817` -> `-1.5199` | `126` -> `138` |

### Signal Distribution Before vs After

| Baseline | signals before -> after | A_MAIN | B_IGNITION | C_CROWDED | D_EXIT_RISK | N_NEUTRAL | zero-price signals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H1/H2 | `37618` -> `36642` | `448` -> `452` | `1283` -> `1264` | `1847` -> `1804` | `19398` -> `19044` | `14642` -> `14078` | `976` -> `0` |
| Q1 | `95585` -> `93017` | `775` -> `752` | `2776` -> `2759` | `5891` -> `5806` | `46472` -> `45466` | `39671` -> `38234` | `2568` -> `0` |

结论：过滤能清零信号层的零价污染；H1/H2 指标改善明显，但 Q1 的回撤和 Sharpe 变差，说明更细粒度历史里的异常帧会改变后续路径。该过滤适合作为显式研究选项和 report-only diagnostic，暂不作为默认 formal quality gate。

## Price Quality Attribution Rerun

Phase 12 将 `price=0` 问题拆成两个显式研究口径：

1. `excludeCrossMarketZeroPriceRows`：只过滤零行情形态下的跨市场/非 A 股/代码失配行。实现中使用 MongoDB `stock_names` A 股代码表辅助识别，并跳过整帧全零异常帧，避免把两类问题混在一起。
2. `excludeAllZeroPriceFrames`：只剔除整帧股票价格全为 `0` 或不可解析的异常快照。

### Cross-Market Zero-Price Filter

正式比较采用 v2 checkpoint：

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines `
  --checkpoint-id checkpoint_2026-05-21_cross_market_zero_filter_v2 `
  --exclude-cross-market-zero-price-rows
```

v1 `checkpoint_2026-05-21_cross_market_zero_filter` 已落库，但因第一版跨市场过滤会在全零异常帧里做行级过滤，归因不够干净；v2 已改为跳过全零帧，作为 Phase 12 正式结论。

| Baseline | Run ID | dropped rows | skipped all-zero frames | zero-price signals |
| --- | --- | ---: | ---: | ---: |
| H1 `half_hour/current_bar` | `bt_57371fbc97ad4371` | `902` | `0` | `257` |
| H2 `half_hour/next_bar` | `bt_4fe7fd28fcce4146` | `902` | `0` | `257` |
| Q1 `quarter_hour/next_bar` | `bt_b59b804884ae465a` | `1886` | `1` | `683` |

### All-Zero Frame Filter

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines `
  --checkpoint-id checkpoint_2026-05-21_all_zero_frame_filter `
  --exclude-all-zero-price-frames
```

| Baseline | Run ID | dropped frames | dropped rows | zero-price signals |
| --- | --- | ---: | ---: | ---: |
| H1 `half_hour/current_bar` | `bt_ac33b22a9f974170` | `0` | `0` | `976` |
| H2 `half_hour/next_bar` | `bt_70c9e89288504b24` | `0` | `0` | `976` |
| Q1 `quarter_hour/next_bar` | `bt_751dbc4783614ace` | `1` | `187` | `2381` |

被剔除的全零帧为 `quarter_hour:2026-04-03:14:15`。

### Metrics Attribution

| Baseline | base totalReturn | cross-market filter | all-zero-frame filter | all `price<=0` filter |
| --- | ---: | ---: | ---: | ---: |
| H1 | `+4.49%` | `+6.47%` | `+4.49%` | `+6.47%` |
| H2 | `-6.37%` | `-1.40%` | `-6.37%` | `-2.47%` |
| Q1 | `-3.27%` | `-5.85%` | `-2.79%` | `-3.26%` |

| Baseline | base maxDrawdown | cross-market filter | all-zero-frame filter | all `price<=0` filter |
| --- | ---: | ---: | ---: | ---: |
| H1 | `-2.82%` | `-2.81%` | `-2.82%` | `-2.81%` |
| H2 | `-9.16%` | `-5.46%` | `-9.16%` | `-5.52%` |
| Q1 | `-11.06%` | `-14.80%` | `-9.20%` | `-14.67%` |

| Baseline | base trades | cross-market filter | all-zero-frame filter | all `price<=0` filter |
| --- | ---: | ---: | ---: | ---: |
| H1 | `54` | `54` | `54` | `54` |
| H2 | `64` | `64` | `64` | `64` |
| Q1 | `126` | `133` | `105` | `138` |

### Interpretation

- `half_hour` 的改善几乎全部来自跨市场/非 A 股/代码失配零行情过滤；全零帧过滤对 H1/H2 没有影响，因为 half_hour 当前没有全零价格帧。
- `quarter_hour` 的异常来源是混合的：全零帧过滤能改善 Q1 回撤（`-11.06% -> -9.20%`）并减少交易数（`126 -> 105`），但跨市场过滤会使 Q1 回撤变差（`-11.06% -> -14.80%`）。
- 全量 `price<=0` 过滤清零信号污染，但它把跨市场行、全零帧和局部 A 股报价缺失合并处理，不适合作为当前默认 formal quality gate。

结论：下一步正式质量诊断可以优先加入 report-only 字段：`crossMarketZeroPriceRows`、`allZeroPriceFrames`、`partialAshareZeroPriceRows`。默认回测口径仍不自动开启任何价格过滤；若要候选默认化，优先考虑“跨市场/非 A 股/代码失配零行情”作为研究过滤，而“全零异常帧”作为更高优先级的数据采集修复/人工审计项。

## Phase 13 Implementation Plan

Phase 13 只做报告诊断，不做过滤：

1. 在 `BacktestService.run_ranktrend` 中，基于 `_prepare_frames_for_backtest` 后、显式研究过滤前的 `run_frames` 计算价格诊断。
2. 将结果挂到 `quality_gate["reportOnlyDiagnostics"]["priceQuality"]`。
3. 在 `BacktestEngine._data_quality_summary` 中原样透传到 `dataQuality.reportOnlyDiagnostics`。
4. 在 `summarize_longtest_baseline` 中追加 `priceQualityDiagnostics` 摘要字段。
5. 增加测试确认默认行为不变，显式过滤时诊断仍基于过滤前 frames。

## Errors Encountered

| Error | Attempt | Resolution |
| --- | --- | --- |
| CLI 回测完整 JSON 输出过大导致 shell 超时 | 1 | run 已落库；改用小脚本读取 `bt_1f012ea44bb44092` 的质量字段完成验证。 |
| 一次性读取 6 个完整回测报告提取信号分布超时 | 1 | 改为按 run 分批读取完整报告，最终取得 H1/H2/Q1 过滤前后信号分布。 |
