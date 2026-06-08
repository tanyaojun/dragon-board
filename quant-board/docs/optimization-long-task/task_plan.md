# QuantBoard 长任务优化计划

## Goal

在 `dragonboard_live` 的 `half_hour` 正式快照口径上，完成可复现、可追溯的 RankTrend 基线回测与第一轮参数优化，并产出只作为候选的参数研究结论。

## Current Phase

Phase 33 in progress; lifecycle must be redefined as auxiliary decision system B, not an independent buy/sell strategy and not a loose report-only tag. The A+B fusion contract is now implemented behind a research-only strategy: RankTrend A finds the early-big-move structure, lifecycle B gives allow/caution/veto/exit_watch, and B veto prevents entry before execution.

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
| Long-test checkpoint | `checkpoint_2026-05-21_initial` | completed | 三条固定基线，摘要追加到 JSONL |
| Money-flow diagnostic backtest | `bt_1f012ea44bb44092` | completed | `half_hour/next_bar`，用于验证质量统计修复 |
| Positive-price filter checkpoint | `checkpoint_2026-05-21_price_filter` | completed | 显式过滤 `price<=0` 行后复跑 |
| Cross-market zero-price checkpoint | `checkpoint_2026-05-21_cross_market_zero_filter_v2` | completed | 已取代 v1 |
| All-zero frame checkpoint | `checkpoint_2026-05-21_all_zero_frame_filter` | completed | 只剔除全零价格异常帧 |
| Weekly checkpoint 5/26 | `checkpoint_2026-05-26_weekly` | completed | 5 日增量，H2 持续改善 |
| Weekly checkpoint 5/29 (repaired) | `checkpoint_2026-05-29_weekly` | completed | 数据未补齐时的基线 |
| Interpolated checkpoint 5/29 | `checkpoint_2026-05-29_interpolated` | completed | 补齐后 290 HH + 756 QH，H1 Sharpe +0.60 |
| Weekly checkpoint 6/05 | `checkpoint_2026-06-05_weekly` | completed | 292 HH + 622 QH，三条基线全面恶化，L1 熔断第 4 期 |

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

### Phase 14: V2 四层决策框架设计

- [x] 与用户交叉澄清 5 个痛点
- [x] 设计 Layer 1-4 四层架构
- [x] Layer 1 信号有效性（分层比例、方向精度、二项检验、层级区分度）
- [x] Layer 2 执行质量（H1 vs H2 偏差、相对阈值、方向占比）
- [x] Layer 3 实盘对齐（trade_journal 7 个执行字段、最小 10 笔判停）
- [x] Layer 4 参数优化（两阶段、双层止损、采用规则）
- [x] 第三方 agent 交叉评审，修入 4 个 P0 问题
- [x] 输出 V2 设计文档 `2026-05-26-longtest-v2-design.md`
- **Status:** complete

### Phase 15: V2 Phase A-C 实施

- [x] Phase A: TradeJournal 7 个执行字段 (models.py, journal_routes.py)
- [x] Phase A: TypeScript 类型 + CandidatePoolPanel 执行记录表单
- [x] Phase B: `compute_signal_efficacy()` + `compute_execution_quality()` 函数
- [x] Phase B: 接入回测管道 (services.py + engine.py)
- [x] Phase B: 接入 CLI `summarize_longtest_baseline` + `cmd_run_longtest_baselines`
- [x] Phase B: Layer 1-2 单元测试 (3 个)
- [x] Phase C: `GET /api/backtests/alignment` 端点
- [x] Phase C: CLI 内联对齐逻辑
- [x] Phase C: 集成测试 (2 个)
- [x] 修复 `candidateTier` 字段路径错误（`rankTrend.meta.sampleQuality.tier` → 顶层 `candidateTier`）
- **Status:** complete

### Phase 16: 代码审查与修复

- [x] Spec 合规审查：16 项检查，12 项通过，4 项延后
- [x] 代码质量审查：7 项发现，修复 4 项
- [x] 修复 #1: 提取 `compute_alignment()` 共享函数消除 DRY
- [x] 修复 #2: `compute_execution_quality` 增加 yellow 状态
- [x] 修复 #5: `import math` 移到模块顶部
- [x] 修复 #6: 删除死代码 `a_main_prices` / `n_neutral_prices`
- [x] 修复 #7: 对齐不可用时返回 `unavailable`
- [x] 修复 #8: 添加 `history` 参数文档
- **Status:** complete

### Phase 17: Phase A-C 收尾

- [x] `read_checkpoint_history()` 读取 JSONL 历史
- [x] `check_layer1_meltdown()` 连续 3 期 red → 熔断告警
- [x] `check_layer3_trend()` 连续 2 期 sufficient → 绿灯
- [x] 接入 `cmd_run_longtest_baselines`，写入 `crossPeriod` 字段
- [x] 补测试缺口：空信号、无下帧、不含 MongoDB、空 run_ids、带 history
- [x] 新增熔断/追踪集成测试 4 个
- [x] CLI emoji 改文本避免 Windows GBK 编码错误
- [x] `FORMAL_CAPTURE_MODES` 加入 `"synthesized"`
- [x] 更新 findings.md 记录收尾结果
- **Status:** complete

### Phase 18: 数据修复 — 缺失 bar 补齐

- [x] 分析 half_hour（42 条缺失）和 quarter_hour（213 条缺失）
- [x] v1: 相邻 bar 直接复制（有偏差，已弃用）
- [x] v2: 前后双 bar 价格/成交量线性插值，标记 `captureMode: "synthesized"`
- [x] 删除旧复制数据（通过价格指纹匹配识别）
- [x] 修复 5 个空热榜合成 bar，更新 `stockRowCount`
- [x] 补齐后 half_hour 290 帧、quarter_hour 756 帧，零缺口
- **Status:** complete

### Phase 19: Checkpoint 2026-05-29 复跑

- [x] 使用补齐数据跑 `checkpoint_2026-05-29_interpolated`
- [x] 对比原始数据 vs 补齐数据三条基线
- [x] 记录 Layer 1-3 指标和跨期状态
- **Status:** complete

### Phase 20: 待启动（下个 plan）

- [ ] Phase D: Layer 4 参数优化（需 ≥60 个交易日，当前 34 个，预计 7 月中）
- [ ] Phase E: P1 统计与基准扩展（需 ≥50 个交易日）
- [ ] Phase F: P2 归因与合规（需 ≥70 个交易日）
- [ ] L1 熔断正式应对（已触发连续 4 期红灯，需排查策略逻辑 vs 市场环境归因）
- [ ] L3 模型失配/系统偏差标记（需 trade_journal 数据积累）
- [x] Phase 20: 6/05 周度 checkpoint — runId: `bt_fd27ea809f3f4c42`, `bt_6f07661dd79d4962`, `bt_0d6bd329498441ed`

### Phase 21: Early Big Move V1 长测基线切换

- [x] 旧 `H1/H2/Q1` 生命周期分层长测基线标记为 retired。
- [x] 新增 baseline set：`early_big_move_v1`。
- [x] 新增研究策略名：`ranktrend_early_big_move`。
- [x] 新三线默认替代旧三线：
  - `E1_half_hour_signal_forward40`
  - `E2_half_hour_ranked_current_bar`
  - `E3_half_hour_ranked_strict_fill`
- [x] 旧三线仅保留为显式 `--baseline-set legacy_lifecycle_v1` 历史复跑入口。
- [x] 清空本地旧长测 JSONL 记录：`quant-board/data/reports/long_test_runs.jsonl`。
- [x] 修复 Python replay 字段兼容：`ranktrend_early_big_move` 入场读取 `technical.momentumProfile`，避免交易模拟 0 候选。
- [x] 正式启动 `checkpoint_2026-06-07_early_big_move_v1`。
- **Status:** complete

### Phase 22: Early Big Move V1 交易归因与 V2 方向

- [x] 读取 `E2_half_hour_ranked_current_bar` run：`bt_d4732abbb1c5486e`。
- [x] 读取 `E3_half_hour_ranked_strict_fill` run：`bt_2e3959f3ddb34ace`。
- [x] 用 `entrySignalSnapshotId + code` 匹配入场时 raw replay signal。
- [x] 修正字段口径：多周期动量加速度必须取 `rankTrend.technical.momentumProfile.acceleration`，不能误用 `technical.signals.acceleration.score`。
- [x] 拆分 winners / losers，按 `candidateTier`、`stage`、当前涨幅区间、样本状态、`zeroCross/MACD/finalSignal`、退出原因做归因。
- [x] 形成 V2 初步方向：收窄二级入场池，优先 `A_MAIN/B_IGNITION`，控制追高，重做 early big move 专属退出规则。
- **Status:** complete

### Phase 23: Early Big Move V2 实现与复跑

- [x] 新增研究策略名：`ranktrend_early_big_move_v2`，保留 V1 不覆盖。
- [x] 新增 baseline set：`early_big_move_v2`。
- [x] V2 入场：沿用第一层 early big move 结构，但默认只交易 `A_MAIN/B_IGNITION`，并要求当前涨幅 `< 6%`。
- [x] V2 入场不要求 `finalSignal=buy`、MACD 金叉或 `zeroCross=buy`。
- [x] V2 出场：退出热榜连续 3 个 half-hour bar、止损 5%、`rawChange < -50 + MACD death`、40 bars 上限；不设固定止盈。
- [x] 修复 Layer 3 对齐在实盘 journal 为空时仍解压扫描大回测结果导致 CLI 卡住的问题。
- [x] 执行 `checkpoint_2026-06-07_early_big_move_v2`，三条 run 已落库。
- **Status:** complete

### Phase 24: Early Big Move V2 亏损单归因

- [x] 以 `V2_E3_half_hour_ranked_strict_fill` run `bt_f34a868872404e17` 为主线。
- [x] 使用 `roundTripTrades` 口径，而不是 `backtest_trades` 卖出切片口径。
- [x] 用 `entrySignalSnapshotId + code` 回连 `result.signals`，读取完整 RankTrend 入场特征。
- [x] 列出 17 笔亏损单，记录收益、出场原因、候选层、市场状态、涨幅、多周期动量、zeroCross、MACD、finalSignal、风险信号。
- [x] 对照 21 笔盈利单，确认亏损集中在 `B_IGNITION`，`A_MAIN` 在本轮 4 笔全部盈利。
- **Status:** complete

### Phase 25: Early Big Move V3 二次确认验证

- [x] 离线枚举 V2 已成交完整回合上的候选二次确认条件。
- [x] 确认第一条 V3 候选：`A_MAIN` 原样保留；`B_IGNITION` 必须满足 `momentumProfile.mid >= 20` 且 `zeroCross=buy`。
- [x] TDD 增加 V3 入场规则测试。
- [x] 新增 `ranktrend_early_big_move_v3` 和 `early_big_move_v3` baseline set。
- [x] 按用户要求把 V3 baseline 的持仓上限改为 `50 bars`。
- [x] 复跑 `checkpoint_2026-06-07_early_big_move_v3`。
- [x] 对比 V2/V3 的收益、胜率、止损数、交易数和大肉持有结果。
- **Status:** complete

### Phase 26: V3 30 bars 月度窗口回测

- [x] 固定 `ranktrend_early_big_move_v3 / half_hour / maxHoldingBars=30`
- [x] 跑 4 月 current-bar / 30 bars：`bt_a80a2e51db204882`
- [x] 跑 5 月 current-bar / 30 bars：`bt_24bce043660b48ec`
- [x] 跑 4 月 strict-fill / 30 bars：`bt_b1be9464a58a483b`
- [x] 跑 5 月 strict-fill / 30 bars：`bt_38dcde4453c2447c`
- [x] 确认 current-bar / 30 bars 两个月均满足收益与胜率目标
- **Status:** complete

### Phase 27: Current-bar / 30 bars 止损单归因

- [x] 固定主线为 `ranktrend_early_big_move_v3 / half_hour / current_bar / maxHoldingBars=30`
- [x] 读取 4 月 run `bt_a80a2e51db204882` 与 5 月 run `bt_24bce043660b48ec`
- [x] 用 `roundTripTrades` 口径复核胜率，避免卖出切片误算
- [x] 用 `(entrySignalSnapshotId, code)` 回连 `result.signals`，提取入场 RankTrend 特征
- [x] 拉取止损票入场前后 1-4 个 half-hour bar 的信号变化
- [x] 检查 `skippedOrders` 和 Mongo 原始盘口，确认跌停不可卖导致的超额止损
- **Status:** complete

### Phase 28: A_MAIN 假主升过滤真实复跑

- [x] 新增窄作用域研究策略 `ranktrend_early_big_move_v3_a_main_risk_filter`
- [x] 保持 B_IGNITION 完全沿用 V3：`mid >= 20` 且 `zeroCross=buy`
- [x] 只验证 A_MAIN 假主升过滤：`A_MAIN + weak + long < 10` 或 `A_MAIN + change < 0`
- [x] 修复研究策略必须沿用 early big move 专属出场规则，避免回退到旧 `finalSignal/D_EXIT_RISK/rank>50/止盈` 出场
- [x] 复跑 4 月 current-bar / 30 bars：`bt_ef248f9bbe884b63`
- [x] 复跑 5 月 current-bar / 30 bars：`bt_6880bb325d604045`
- [x] 用 `(entrySignalSnapshotId, code)` 回连完整入场 signal，区分入场分层与退出分层
- [x] 排查假主升进入 A_MAIN 的源码链路
- **Status:** complete

### Phase 29: 生命周期路径归因

- [x] 固定主线为 `ranktrend_early_big_move_v3 / current_bar / 30 bars`
- [x] 读取 4 月 run `bt_a80a2e51db204882` 与 5 月 run `bt_24bce043660b48ec`
- [x] 对照读取 A_MAIN 风险过滤 run `bt_ef248f9bbe884b63` 与 `bt_6880bb325d604045`
- [x] 用 `roundTripTrades` + `(entrySignalSnapshotId, code)` 回连完整 `result.signals`
- [x] 抽取入场前 3 bars、入场 bar、入场后 2 bars 的 `cycle.transition/stage/candidateTier/momentumProfile`
- [x] 对比盈利/亏损交易的生命周期路径、长周期动量和退出原因
- **Status:** complete

### Phase 30: B_IGNITION 长周期过滤真实复跑

- [x] 新增窄作用域研究策略 `ranktrend_early_big_move_v3_b_long_filter`
- [x] 只过滤 `B_IGNITION + momentumProfile.long < 10`
- [x] `A_MAIN` 完全沿用 V3，不加 A_MAIN 硬过滤
- [x] 出场沿用 early big move 专属规则，不恢复旧生命周期/最终信号退出
- [x] 复跑 4 月 current-bar / 30 bars：`bt_3a6339356fe44ef2`
- [x] 复跑 5 月 current-bar / 30 bars：`bt_1d12cc19e20d492e`
- [x] 对比 V3 原始、A_MAIN 风险过滤与 B_LONG 过滤的交易路径差异
- [x] 确认 B_LONG 硬过滤真实复跑不通过，不能写入 V3 默认
- **Status:** complete

### Phase 31: 生命周期实现审计

- [x] 审计 TS 生命周期实现：`attentionCycleAnalyzer.ts`、`candidateTierComposer.ts`
- [x] 审计 Python 回测主链：`ranktrend.py`、`execution.py`、`strategy.py`
- [x] 检查现有生命周期测试覆盖，确认缺少真实路径级 TS/Python 对齐
- [x] 读取 V3 原始 4 月/5 月与研究过滤 run，按 `rawStage/stage/transition/entryAdvice` 聚合盈亏
- [x] 确认生命周期不能作为硬买卖标签，只能作为路径上下文、排序降权和报告诊断
- [x] 产出审计文档：`2026-06-07-lifecycle-implementation-audit.md`
- **Status:** complete

### Phase 32: 无生命周期硬门槛对照复跑

- [x] 新增 research-only 策略 `ranktrend_early_big_move_v3_no_lifecycle_gate`
- [x] 保持默认 V3 不变，只把入场硬门槛回退到早期大肉结构本身
- [x] 跑 4 月 current-bar / 30 bars：`bt_efe08f9fb3954988`
- [x] 跑 5 月 current-bar / 30 bars：`bt_9c00f69c9b09426c`
- [x] 归因失败来源，确认大量 `N_NEUTRAL + watch/avoid` 候选挤占交易路径
- [x] 新增更窄 research-only 策略 `ranktrend_early_big_move_v3_context_probe`
- [x] 跑 4 月 current-bar / 30 bars：`bt_69232223f3024f02`
- [x] 跑 5 月 current-bar / 30 bars：`bt_a23990ecc8084021`
- [x] 确认 context probe 仍未优于现有 V3 主线
- **Status:** complete

### Phase 33: 生命周期 A+B 融合设计审计

- [x] 重新确认用户决策：生命周期不是主策略，也不是松散辅助门槛，而是 RankTrend A 之后的辅助决策系统 B。
- [x] 审计当前生命周期字段从 TS/Python 生成、进入 `candidateTier`、进入执行层的完整路径。
- [x] 检索外部金融研究和国内论坛语义，提炼“动量延续、注意力拥挤、假突破/假主升”的可用融合原则。
- [x] 输出短设计：A+B 融合合同、生命周期 B 语义定义、当前代码需要拆开的点、TDD 测试清单。
- [x] 等用户确认设计后，再进入 TDD：先写失败测试，再改 TS/Python 输出合同和 QuantBoard 执行入口。
- [x] 新增 TS/Python `cycle.decision` 合同，保留 `entryAdvice` 为兼容展示字段。
- [x] 新增 research-only 策略 `ranktrend_early_big_move_v3_lifecycle_fusion`，只在 A 结构通过后消费 B veto，不让 B 独立制造买入。
- [x] 复跑 4 月/5 月 `current-bar / 30 bars`，确认首版 fusion 与同版本 V3 交易集合完全一致，尚未发挥 B 拦截能力。
- [x] 修复 `cycle.decision.evidence` 合同：TS/Python 均写入真实 `riskPressure/divergenceSeverity/overheatSeverity`，不再保留 0 占位。
- [x] 重新审视生命周期本体逻辑：确认首版 B 失败根因是 `stage=ignition/expansion -> allow` 的直译过浅，没有识别“该阻止的假突破”和“RankTrend 漏选但生命周期结构有效”的双向问题。
- [x] 基于已成交亏损/漏选大肉证据完成第一轮 B 语义 TDD：新增 `veto` 反对通道与 `discovery` 研究提示通道，后者不进入交易候选池。
- [x] 对齐 TS/Python 合同：TS 在 risk 生成后重新生成 `cycle.decision`，避免 live 端 action 和 evidence 漂移。
- [x] 下一轮 TDD 聚焦 `rankPathCommitment` / 突破承接质量：识别“最后一跳很猛但整段承接不足”的假突破，同时保护低 long 但路径连续改善的大肉形态。
- [x] 用 4 月/5 月 V3 可入场信号做信号层复核：统计 `rankPathCommitment` veto 数量、被拦截票、是否命中亏损来源、是否误伤大肉。
- [x] 收窄 `rankPathCommitment` veto 语义：引入中长动量承接例外，避免只凭弱路径承接一票否决。
- [x] 复跑 4 月/5 月 `current_bar / 30 bars`，确认当前 V3 与 fusion 一致，但收益低于历史最佳。
- [x] 下一轮 TDD 聚焦 `B_IGNITION` 低可见度点火/仓位挤占：`000657` 被标记为低可见度首段点火并降出 `B_IGNITION`，但完整复跑仍低于历史最佳，不能采用为默认策略。
- [x] 下一轮聚焦排序/仓位路径归因：分析删除 `000657` 后资金进入哪些替代候选，为什么没有等到 `603459`，优先验证 B caution 排序降权而不是继续硬过滤。
- [x] 拆开候选分层与融合执行职责：`compose_strategy()` 保留 RankTrend 结构分层，B veto 只由 lifecycle fusion 执行入口消费，避免污染 V3 对照。
- [x] 将 `rankPathCommitment` 承接不足从硬 veto 降为 caution 诊断，只保留反转/高风险冲突作为一票否决来源。
- [x] 复跑 4 月/5 月 `current_bar / 30 bars`，fusion 达到 `+20.29%` 合计收益、`70.37%` 合并胜率。
- [x] 复跑 `2026-04-01~2026-05-31` 单次连续回测：`bt_6bad357f332b4197`，`+24.68%`，胜率 `71.43%`，确认不是月度相加口径。
- [x] 拆解连续 run 的 7 笔止损单，确认单纯 B caution 排序降权无法改善，真正突破口是持仓后 B 明确反对且未盈利时降低卖出门槛。
- [x] 按 TDD 新增 fusion 专属退出规则：`cycle.decision.action in veto/exit_watch` 且持仓未盈利时提前退出；盈利仓不因 B veto 被提前砍掉。
- [x] 复跑 `2026-04-01~2026-05-31` 单次连续回测：`bt_b8c73ecf67e24d78`，`+31.00%`，胜率 `65.79%`，最大回撤 `-3.19%`，确认突破 `30%+ / 60%+` 目标。
- [x] Review 复核：按同一 `volumeParticipationRate=0.1` 口径重跑 `bt_682d3abc164d4177` 复现 `+31.00% / 65.79%`；CLI 默认 `0.05` 口径为 `bt_7eaaa1f656764be8`，`+28.93% / 68.42%`，后续不得混用。
- [x] 拆解 `bt_682d3abc164d4177` 剩余 4 笔止损与 2 个未平仓浮盈：确认收益不是单票偶然，最大单票仅占最终利润约 `17.1%`，但 `30%` 目标依赖多只大肉簇和最大持有退出组。
- [x] 按用户要求将 `maxHoldingBars` 临时调为 `40` 复跑当前策略：`bt_6f2909499d3e4865` 仅 `+11.87% / 53.85%`，新鲜复跑 `bt_7f4b3d2472d64629` 复现同结果，明显弱于 30 bars，暂不采用。
- [x] 按用户要求将 `maxHoldingBars` 临时调为 `25` 复跑当前策略：`bt_1f4d5b6492b44ee7` 为 `+26.22% / 60.47%`，优于 40 bars 但弱于 30 bars，暂不替换主线。
- [x] 按用户要求分别复跑 `32/35/28 bars`：`32 bars` 为 `bt_d896884168dc4081`，`+25.33% / 64.86%`；`35 bars` 为 `bt_ce6d1767f5fa4f0a`，`+21.29% / 54.05%`；`28 bars` 为 `bt_eb657d60cbeb4b17`，`+21.15% / 58.97%`。三者均弱于 30 bars。
- **Status:** in_progress

## Retired Baselines

旧生命周期分层策略已被证伪，不再作为默认长测基线：

| Label | Status | Reason |
| --- | --- | --- |
| `H1_half_hour_current_bar` | retired | 单靠生命周期分层买卖不能稳定产生收益 |
| `H2_half_hour_next_bar` | retired | 单靠生命周期分层买卖不能稳定产生收益 |
| `Q1_quarter_hour_next_bar` | retired | 新策略主证据来自 `half_hour`，quarter_hour 只保留为后续压力测试 |

## Active Baselines

当前默认 baseline set：

```text
early_big_move_v1
```

| Label | Snapshot | Execution | Purpose |
| --- | --- | --- | --- |
| `E1_half_hour_signal_forward40` | `half_hour` | signal-only | 验证第一层早期大肉候选召回 |
| `E2_half_hour_ranked_current_bar` | `half_hour` | `current_bar` | 验证排序后实盘即时处理的乐观上限 |
| `E3_half_hour_ranked_strict_fill` | `half_hour` | `next_bar` + strict fill | 验证 E2 的成交乐观偏差 |

显式 V2 对照 baseline set：

```text
early_big_move_v2
```

| Label | Snapshot | Execution | Purpose |
| --- | --- | --- | --- |
| `V2_E1_half_hour_signal_forward40` | `half_hour` | signal-only | 验证 V2 第一层候选召回 |
| `V2_E2_half_hour_ranked_current_bar` | `half_hour` | `current_bar` | 验证 V2 即时处理上限 |
| `V2_E3_half_hour_ranked_strict_fill` | `half_hour` | `next_bar` + strict fill | 验证 V2 保守可执行性 |

显式 V3 对照 baseline set：

```text
early_big_move_v3
```

| Label | Snapshot | Execution | Purpose |
| --- | --- | --- | --- |
| `V3_E1_half_hour_signal_forward50` | `half_hour` | signal-only | 验证 V3 第一层候选召回，持有观察窗口 50 bars |
| `V3_E2_half_hour_ranked_current_bar` | `half_hour` | `current_bar` | 验证 V3 即时处理上限 |
| `V3_E3_half_hour_ranked_strict_fill` | `half_hour` | `next_bar` + strict fill | 验证 V3 保守可执行性 |

## Phase 21 Checkpoint

Checkpoint: `checkpoint_2026-06-07_early_big_move_v1`

| Label | Run ID | totalReturn | maxDrawdown | Sharpe | winRate | trades | buyFilled |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `E1_half_hour_signal_forward40` | `bt_359fe12a4c9c487f` | n/a | n/a | n/a | n/a | n/a | n/a |
| `E2_half_hour_ranked_current_bar` | `bt_d4732abbb1c5486e` | `-7.43%` | `-16.08%` | `-0.4157` | `48.15%` | `108` | `112` |
| `E3_half_hour_ranked_strict_fill` | `bt_2e3959f3ddb34ace` | `-5.31%` | `-15.08%` | `-0.6243` | `38.00%` | `100` | `105` |

结论：第一层候选能进入交易模拟，但当前二级排序、卖出和风险控制不能直接产生正收益。下一阶段应优化排序/过滤，不回退到旧 `final=buy` 或生命周期分层基线。

## Phase 22 Attribution

本阶段只做归因，不改代码、不重跑策略。

### 字段口径修正

`rankTrend_early_big_move` 的核心加速度是：

```text
rankTrend.technical.momentumProfile.acceleration
```

不是：

```text
rankTrend.technical.signals.acceleration.score
```

后者是 0~1 的技术信号分数，只能表示 acceleration signal 的强弱，不能代表多周期动量加速度。后续排序、过滤和分析必须统一使用 `momentumProfile`。

### E2 当前 bar 归因

Run: `bt_d4732abbb1c5486e`

| 条件 | 交易数 | 胜率 | 平均收益 | 收益合计 |
| --- | ---: | ---: | ---: | ---: |
| 全部 E2 | 108 | 48.15% | -0.31% | -32.97% |
| 剔除 `N_NEUTRAL` | 63 | 55.56% | +0.50% | +31.24% |
| `A_MAIN/B_IGNITION` 且涨幅 `< 6%` | 43 | 62.79% | +1.20% | +51.71% |
| `A_MAIN/B_IGNITION` 且加速度 `>=20` 且涨幅 `< 6%` | 32 | 62.50% | +1.33% | +42.43% |
| `A_MAIN/B_IGNITION` 且加速度 `>=30` 且涨幅 `< 8.5%` | 33 | 63.64% | +1.14% | +37.57% |
| 仅 `B_IGNITION` | 42 | 59.52% | +0.69% | +29.13% |
| 仅 `N_NEUTRAL` | 45 | 37.78% | -1.43% | -64.21% |

E2 结论：

- `N_NEUTRAL` 是主要拖累源：45 笔贡献 `-64.21%` 的单笔收益合计。
- `A_MAIN/B_IGNITION + 涨幅不过热` 已经接近高胜率目标，其中涨幅 `< 6%` 达到 `62.79%`。
- 继续硬等 `finalSignal=buy` 或 MACD 金叉没有帮助；E2 中 `final=buy` / MACD 金叉样本胜率反而低于整体。

### E3 strict fill 归因

Run: `bt_2e3959f3ddb34ace`

| 条件 | 交易数 | 胜率 | 平均收益 | 收益合计 |
| --- | ---: | ---: | ---: | ---: |
| 全部 E3 | 100 | 38.00% | -0.46% | -46.36% |
| 剔除 `N_NEUTRAL` | 58 | 43.10% | -0.18% | -10.41% |
| `A_MAIN/B_IGNITION` 且涨幅 `< 6%` | 43 | 48.84% | +0.75% | +32.19% |
| `A_MAIN/B_IGNITION` 且加速度 `>=20` 且涨幅 `< 6%` | 37 | 45.95% | +0.67% | +24.91% |
| 仅 `A_MAIN` | 17 | 58.82% | +0.94% | +15.91% |
| 仅 `B_IGNITION` | 41 | 36.59% | -0.64% | -26.32% |
| 仅 `N_NEUTRAL` | 42 | 30.95% | -0.86% | -35.95% |
| `zeroCross=hold` | 41 | 48.78% | +1.24% | +50.91% |
| `zeroCross=buy` | 59 | 30.51% | -1.65% | -97.27% |

E3 结论：

- 严格成交后，`A_MAIN` 明显强于 `B_IGNITION` 和 `N_NEUTRAL`。
- `zeroCross=buy` 在本轮 strict fill 中是负贡献，不应作为硬确认条件；它可能代表信号已经进入更拥挤、更容易隔日兑现的阶段。
- `A_MAIN/B_IGNITION + 涨幅 < 6%` 能把 E3 从负收益拉到正收益，但胜率仍不足 60%，说明还需要独立出场和持有逻辑。

### 退出规则归因

当前 `ranktrend_early_big_move` 仍沿用默认退出逻辑，主要退出原因包括：

| 退出原因 | 问题 |
| --- | --- |
| `compose_decision 卖出信号` | 旧生命周期/最终信号退出，和 early big move 捕捉大肉目标冲突最大；E2/E3 亏损主要集中在这里。 |
| `D_EXIT_RISK` | 并非纯坏信号，很多盈利单最终在 D_EXIT_RISK 退出，适合保留为风险提示。 |
| `排名跌出前50` | 属于死排名退出，和 RankTrend 动态结构目标冲突；后续应改成“退出热榜 3 个 half_hour bar”或“排名大幅下降 + MACD 死叉”。 |
| `止盈` | 当前不适合做固定止盈；大肉策略需要让利润奔跑。 |

### V2 初步规则方向

V2 不应继续扩大第一层候选，而应把第二层变成“高胜率候选排序/过滤”：

1. 第一层仍保留：`jump buy 高置信 + short/mid/long 同步转正 + momentumProfile.acceleration 抬升 + 可成交`。
2. 第二层优先交易：
   - `candidateTier in A_MAIN/B_IGNITION`；
   - 当前涨幅优先 `< 6%`，`6%-8.5%` 只作为次优观察；
   - `N_NEUTRAL` 不删除出候选池，但默认不进自动交易模拟，除非后续能找到额外共振条件。
3. 辅助信号只排序，不硬门禁：
   - `finalSignal=buy` 不作为入场前置；
   - MACD 金叉不作为入场前置；
   - `zeroCross=buy` 不作为入场前置，strict fill 下反而需要谨慎。
4. 出场从默认生命周期逻辑改为 early big move 专属逻辑：
   - 退出热榜连续 3 个 half_hour bar；
   - 止损 5%；
   - 排名大幅下降沿用 `rawChange < -50`，但必须叠加 MACD 死叉；
   - 不设固定止盈。

下一轮应实现 `early_big_move_v2` 或通过显式配置复跑上述规则，目标不是增加交易次数，而是先验证：

```text
胜率 >= 60%
总收益转正
交易数可少，但必须解释清楚每一笔入场理由和退出理由
```

## Phase 23 Checkpoint

Checkpoint: `checkpoint_2026-06-07_early_big_move_v2`

| Label | Run ID | totalReturn | realizedReturn | maxDrawdown | Sharpe | winRate | trades | buyFilled |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `V2_E1_half_hour_signal_forward40` | `bt_627db7e6c69446ca` | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `V2_E2_half_hour_ranked_current_bar` | `bt_0d3233550bb54280` | `+5.31%` | `+5.22%` | `-6.81%` | `+1.6033` | `42.42%` | `33` | `37` |
| `V2_E3_half_hour_ranked_strict_fill` | `bt_f34a868872404e17` | `+9.72%` | `+8.99%` | `-9.00%` | `+2.3456` | `55.26%` | `38` | `41` |

结论：

- V2 明显修复了 V1 负收益问题：E3 strict fill 从 `-5.31%` 提升到 `+9.72%`，接近 `10%` 收益目标。
- 胜率仍未达到 `60%`：E3 为 `55.26%`，下一步重点不是扩大交易次数，而是减少低质量止损单。
- `current_bar` 的收益低于 strict fill，说明 V2 下“更严格成交 + 更少噪声入场”反而更接近目标。
- 这轮不能误读 `controlBacktests`：run 结果开头包含热榜 Top10 等对照组，轻量脚本如果只抓第一个 `totalReturn` 会读到对照组负收益，不是 V2 主策略收益。
- `run-longtest-baselines` 第一轮真实执行时三条 run 已落库，但 CLI 在 Layer 3 对齐阶段因实盘 journal 为空仍扫描大 signals 结果而超时；已补早退测试和修复，后续 dry-run 正常。

下一步方向：

1. 对 V2 的亏损单做归因，重点看止损单的入场形态、涨幅区间、`A_MAIN/B_IGNITION` 差异和是否隔日兑现。
2. 不恢复固定止盈；先研究移动退出或风险降级退出是否能把 E3 胜率推到 `60%`。
3. 暂不扩大入场池，除非能证明新增条件不会牺牲 E3 strict fill 的收益和回撤。

## Phase 24 Loss Attribution

主线 run：`bt_f34a868872404e17`（`V2_E3_half_hour_ranked_strict_fill`）。

读取口径：

- `roundTripTrades`：38 笔完整交易回合，21 赢 / 17 输，胜率 `55.26%`。
- `trades`：56 条卖出切片，只能做退出原因辅助统计，不能直接算胜率。
- 入场特征来源：`result.signals`，按 `(entrySignalSnapshotId, code)` 匹配；Mongo `backtest_signals` 只保留压缩解释字段，不包含完整 `rankTrend.technical.momentumProfile`。

核心结论：

- 17 笔亏损单全部来自 `B_IGNITION`；`A_MAIN` 4 笔全部盈利，合计 `+77,468.75`。
- 最大亏损来源是 `止损`：7 笔，合计 `-81,819.44`，平均单笔约 `-6.35%`。
- `退出热榜连续3个bar` 不是坏退出：全体 12 笔中 9 赢 3 输，合计 `+74,197.35`。
- `到达最大持有快照` 也不是坏退出：全体 12 笔中 10 赢 2 输，合计 `+110,014.74`。
- 本轮 `zeroCross=buy` 不再是负反馈，E3 V2 中 23 笔胜率 `73.9%`；亏损更多集中在 `B_IGNITION + zeroCross=hold` 的弱确认段。
- `divergence=hold` 是明显坏样本：3 笔全亏，合计 `-23,467.87`；`divergence=buy` 胜率 `72.2%`。
- 简单观察口径中，`mid >= 20` 可把胜率推到 `60.7%` 且保留 `+103,315.44` 利润；`long >= 10` 可到 `60.0%`，但会损失部分大肉。下一轮只能作为候选验证，不直接写成默认规则。

## Phase 25 V3 Candidate

离线枚举 V2 已成交完整回合后，下一轮 V3 只验证一个最窄规则：

```text
A_MAIN: 保持 V2 入场，不额外加确认
B_IGNITION: 仍满足 V2 基础 early big move 条件，同时要求：
  - momentumProfile.mid >= 20
  - technical.signals.zeroCross.signal == buy
```

选择原因：

- E3 strict-fill：交易 20 笔，胜率 `80.0%`，利润 `+154,203.89`，止损 `0`。
- E2 current-bar：交易 18 笔，胜率 `61.1%`，利润 `+80,089.44`，仍过 60%。
- 比 `A only` 更不容易漏掉 B 点火大肉；比单独 `mid>=20` 更能过滤弱确认亏损；比 `mid>=20 and long>=10` 更稳过 E2 胜率线。

V3 不改变：

- 不加固定排名门槛。
- 不恢复固定止盈。
- 不把 MACD 金叉或 finalSignal 作为入场硬门槛。
- 出场沿用 V2：退出热榜连续 3 bars、止损 5%、`rawChange < -50 + MACD death`。
- 按用户要求验证“大肉需要长留”，V3 baseline 的持仓上限从 `40 bars` 调整为 `50 bars`。

## Phase 25 Checkpoint

Checkpoint: `checkpoint_2026-06-07_early_big_move_v3`

| Label | Run ID | totalReturn | realizedReturn | maxDrawdown | Sharpe | winRate | trades | buyFilled |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `V3_E1_half_hour_signal_forward50` | `bt_4c7f44f34ab448fe` | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `V3_E2_half_hour_ranked_current_bar` | `bt_5681c2735de646a1` | `+12.93%` | `+10.36%` | `-3.66%` | `+2.6936` | `58.06%` | `31` | `34` |
| `V3_E3_half_hour_ranked_strict_fill` | `bt_b8061da4f92c4462` | `+9.32%` | `+8.73%` | `-7.13%` | `+1.9207` | `54.84%` | `31` | `33` |

结论：

- V3 current-bar 收益达到 `+12.93%`，但胜率 `58.06%`，仍未达到 `60%`。
- V3 strict-fill 收益 `+9.32%`，接近 V2 strict-fill 的 `+9.72%`，但胜率 `54.84%`，也未达标。
- 离线过滤在 V2 已成交样本上看起来很强，但真实复跑后会改变排序、资金占用、跳过成交、T+1 和持仓路径，不能把离线结果直接当成策略结果。
- `50 bars` 对放大利润有效：V3 E3 中“到达最大持有快照”8 笔全胜，合计约 `+141,258.94`。
- 未达标的主要原因不是大肉拿不住，而是止损单仍重：V3 E3 止损 9 笔，合计约 `-95,119.38`。
- 下一轮不应继续盲目加硬过滤，应优先拆 V3 E3 的止损单和 A_MAIN 质量漂移。

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
| V2 checkpoint 三条 run 已 completed，但 CLI 在 Layer 3 对齐阶段超时 | 1 | 根因是实盘 journal 为空时仍解压扫描大 backtest signals；已新增早退修复，后续 dry-run 正常。 |
| 轻量读取 V2 指标时误抓到 `controlBacktests` 对照组字段 | 1 | 改为只扫描顶层主策略字段和 `tradeSimulation` 摘要，确认 V2 主策略 E2/E3 均为正收益。 |
