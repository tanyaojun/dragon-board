# QuantBoard 长任务优化进度

## Session: 2026-05-21

### Phase 1: Health & Dataset Discovery

- **Status:** complete
- Actions taken:
  - 调用 `GET /api/health?deep=true`。
  - 运行 `.\.venv\Scripts\python.exe -m backend.cli list-datasets`。
  - 确认 MongoDB 主库和题材库连通。
  - 确认主数据集为 `dragonboard_live`。
- Files created/modified:
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/findings.md`
  - `quant-board/docs/optimization-long-task/progress.md`

### Phase 2: Baseline Backtests

- **Status:** complete
- Actions taken:
  - 跑 `current_bar` 基线，生成 `bt_f11b21879f804778`。
  - 读取 `GET /api/backtests/bt_f11b21879f804778/report`，确认指标。
  - 跑 `next_bar` 保守基线，生成 `bt_d8fbef53ec434fde`。
  - 记录两条基线的收益、回撤、胜率、交易数和质量风险。
- Files created/modified:
  - `quant-board/docs/optimization-long-task/findings.md`
  - `quant-board/docs/optimization-long-task/progress.md`

### Phase 3: Optimization Plan & Launch

- **Status:** complete
- Actions taken:
  - 确认后端 API 的异步优化任务在后端进程线程池运行。
  - 决定用后端 API 启动第一轮优化任务，而不是用一次性 CLI `--no-wait`。
  - 通过 `POST /api/optimizations/rank-trend` 启动任务 `opt_70e72a69c40143be`。
- Files created/modified:
  - `quant-board/docs/optimization-long-task/task_plan.md`

### Phase 4: Monitoring & Result Review

- **Status:** complete
- Actions taken:
  - 开始轮询 `GET /api/optimizations/opt_70e72a69c40143be`。
  - 任务完成，状态为 `completed`。
  - 记录 best trial、样本切分、质量风险和 top trials 观察。
- Files created/modified:
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/progress.md`
  - `quant-board/docs/optimization-long-task/findings.md`

### Phase 5: Next Decision

- **Status:** complete
- Actions taken:
  - 对比 `current_bar`、`next_bar`、第一轮优化结果。
  - 确认第一轮优化结果过拟合风险为 `high`，不应写回默认参数。
  - 建议下一轮先用 `next_bar` 对 top 参数做显式复核，再考虑扩大搜索。
  - 回答用户关于 `755` 快照数量的疑问：`755` 为多 snapshot type 合计，默认 half_hour 实际为 `191` 帧。
- Files created/modified:
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/findings.md`

### Phase 6: Quarter-Hour Research Optimization

- **Status:** complete
- Actions taken:
  - 用户确认接受建议：使用 `quarter_hour` 跑一轮研究口径优化。
  - 决定使用 `grid` 穷举默认 27 组交易层参数。
  - 明确 `quarter_hour` 结果只作为研究候选，不覆盖 `half_hour` 默认值。
  - 通过 `POST /api/optimizations/rank-trend` 启动任务 `opt_fcf1f30063514bb7`。
  - 轮询完成，任务状态为 `completed`。
  - 记录 best trial、样本切分、质量风险和 top trials 观察。
- Files created/modified:
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/progress.md`
  - `quant-board/docs/optimization-long-task/findings.md`

### Phase 7: Long-Horizon Test Plan

- **Status:** complete
- Actions taken:
  - 合并 half_hour 与 quarter_hour 两轮优化证据。
  - 制定后续长测固定基线、复跑节奏和参数采用门槛。
  - 明确当前没有可直接写回默认参数的候选。
- Files created/modified:
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/findings.md`
  - `quant-board/docs/optimization-long-task/progress.md`
  - `quant-board/docs/optimization-long-task/progress.md`

### Phase 8: Long-Test Baseline Automation

- **Status:** complete
- Actions taken:
  - 复用 QuantBoard 现有 `BacktestService.run_ranktrend`，新增一个很薄的批量 CLI。
  - 固定执行三条基线：`half_hour/current_bar`、`half_hour/next_bar`、`quarter_hour/next_bar`。
  - 把 checkpoint 摘要写入 `quant-board/data/reports/long_test_runs.jsonl`，并同步归档到本进度文档。
  - 执行 `checkpoint_2026-05-21_initial`，生成三条新回测 run。
- Files created/modified:
  - `quant-board/backend/cli.py`
  - `quant-board/tests/test_quant_board.py`
  - `quant-board/docs/api-cli.md`
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/progress.md`
  - `quant-board/data/reports/long_test_runs.jsonl`

Checkpoint results:

| Baseline | Run ID | totalReturn | realizedReturn | maxDrawdown | Sharpe | winRate | trades | quality |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `H1_half_hour_current_bar` | `bt_7493e60c21574bd8` | `+4.49%` | `+5.02%` | `-2.82%` | `-0.0003` | `37.04%` | `54` | `degraded` |
| `H2_half_hour_next_bar` | `bt_923ecfa4517948f4` | `-6.37%` | `-2.71%` | `-9.16%` | `-1.3844` | `34.38%` | `64` | `degraded` |
| `Q1_quarter_hour_next_bar` | `bt_359953a7dba24206` | `-3.27%` | `-0.10%` | `-11.06%` | `-0.5817` | `46.03%` | `126` | `degraded` |

### Phase 9: Money-Flow Quality Diagnostics

- **Status:** complete
- Actions taken:
  - 用户确认 `half_hour` 样本比 `quarter_hour` 少，是因为 IndexedDB 测试阶段更早启用了 `quarter_hour`。
  - 抽样 MongoDB `snapshot_stock_rows`，确认源数据并非全缺资金流字段。
  - 定位 `BacktestService._stock_rows_for_quality` 旧实现只保留 `snapshotId`，导致回测质量统计看不到资金流来源字段。
  - 最小修复 `_stock_rows_for_quality`，只透传资金流来源/置信度/估算标记字段，不改变交易逻辑和价格质量门禁。
  - 新增资金流质量统计回归测试。
  - 跑真实 `half_hour/next_bar` 回测 `bt_1f012ea44bb44092`，确认资金流统计恢复。
- Files created/modified:
  - `quant-board/backend/services.py`
  - `quant-board/tests/test_money_flow_quality_gate.py`
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/findings.md`
  - `quant-board/docs/optimization-long-task/progress.md`

Diagnostic results:

| Snapshot | formal | estimated_l1 | missing | formal coverage |
| --- | ---: | ---: | ---: | ---: |
| `half_hour` | `4711` | `10802` | `29568` | `10.45%` |
| `quarter_hour` | `8698` | `19770` | `73113` | `8.56%` |

Validation backtest:

| Run ID | Snapshot | Execution | totalReturn | maxDrawdown | Sharpe | trades | formal | estimated_l1 | missing |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bt_1f012ea44bb44092` | `half_hour` | `next_bar` | `-6.37%` | `-9.16%` | `-1.3844` | `64` | `4711` | `10802` | `29568` |

### Phase 10: Non-Positive Price Diagnostics

- **Status:** complete
- Actions taken:
  - 用 MongoDB 真实 `snapshot_stock_rows` 统计 `price <= 0` 行分布。
  - 抽样检查异常股票、异常 snapshot、字段形态和 source。
  - 读取已落库的 H1/H2/Q1 固定基线 run，检查实际成交事件和 trades 是否包含零价格。
  - 统计零价格信号在 A/B/C/D/N 候选层的分布。
  - 同步长任务文档，保持本阶段只做诊断，不改变回测逻辑。
- Files created/modified:
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/findings.md`
  - `quant-board/docs/optimization-long-task/progress.md`

Diagnostic results:

| Snapshot | total rows | `price <= 0` | ratio | impacted snapshots | impacted codes |
| --- | ---: | ---: | ---: | ---: | ---: |
| `half_hour` | `45081` | `1165` | `2.58%` | `185` | `99` |
| `quarter_hour` | `101581` | `2673` | `2.63%` | `391` | `331` |

Baseline impact:

| Baseline | Run ID | zero-price events | zero-price trades | source bad refs |
| --- | --- | ---: | ---: | ---: |
| `H1_half_hour_current_bar` | `bt_7493e60c21574bd8` | `0` | `0` | `0` |
| `H2_half_hour_next_bar` | `bt_923ecfa4517948f4` | `0` | `0` | `0` |
| `Q1_quarter_hour_next_bar` | `bt_359953a7dba24206` | `0` | `0` | `0` |

Signal-level findings:

| Baseline | zero-price signals | A_MAIN | B_IGNITION | C_CROWDED | D_EXIT_RISK | N_NEUTRAL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `half_hour/current_bar` and `half_hour/next_bar` | `976/37618` | `0` | `7` | `11` | `478` | `480` |
| `quarter_hour/next_bar` | `2568/95585` | `1` | `29` | `46` | `1219` | `1273` |

Interpretation:

- 非正价格主要来自跨市场热榜条目缺行情，以及早期历史采集异常帧。
- `quarter_hour:2026-04-03:14:15` 是最明显异常帧，`187/187` 行价格全为 `0`。
- 当前固定基线没有以 `price=0` 完成实际成交；交易模拟会跳过缺价格成交。
- 信号层仍有轻微污染，下一步应做显式过滤复跑，而不是直接修改默认质量门禁。

### Phase 11: Explicit Positive-Price Filter Rerun

- **Status:** complete
- Actions taken:
  - 新增显式研究开关 `excludeNonPositivePriceRows`，默认关闭。
  - `run-ranktrend` 和 `run-longtest-baselines` CLI 增加 `--exclude-non-positive-price-rows`。
  - 过滤发生在 RankTrend replay 前，只剔除 `price <= 0` 或无法解析为正价格的股票行，不修改源快照事实。
  - 执行 `checkpoint_2026-05-21_price_filter`，复跑 H1/H2/Q1 三条 fixed baseline。
  - 从完整报告提取过滤前后收益、回撤、交易数、候选层分布和 zero-price signal 分布。
- Files created/modified:
  - `quant-board/backend/services.py`
  - `quant-board/backend/cli.py`
  - `quant-board/tests/test_money_flow_quality_gate.py`
  - `quant-board/tests/test_quant_board.py`
  - `quant-board/docs/api-cli.md`
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/findings.md`
  - `quant-board/docs/optimization-long-task/progress.md`
  - `quant-board/data/reports/long_test_runs.jsonl`

Filtered checkpoint:

| Baseline | Run ID | totalReturn | realizedReturn | maxDrawdown | Sharpe | winRate | trades | dropped rows |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `H1_half_hour_current_bar` | `bt_a5e56233f6fb4805` | `+6.47%` | `+6.68%` | `-2.81%` | `0.4117` | `40.74%` | `54` | `1165` |
| `H2_half_hour_next_bar` | `bt_801abe6f44e146df` | `-2.47%` | `+0.93%` | `-5.52%` | `-0.8583` | `39.06%` | `64` | `1165` |
| `Q1_quarter_hour_next_bar` | `bt_56d52c783fd84776` | `-3.26%` | `-0.02%` | `-14.67%` | `-1.5199` | `39.13%` | `138` | `2673` |

Before/after interpretation:

| Baseline | totalReturn change | maxDrawdown change | trade count change | zero-price signals |
| --- | ---: | ---: | ---: | ---: |
| H1 | `+1.98pp` | `+0.01pp` | `0` | `976 -> 0` |
| H2 | `+3.90pp` | `+3.64pp` | `0` | `976 -> 0` |
| Q1 | `+0.01pp` | `-3.61pp` | `+12` | `2568 -> 0` |

Conclusion:

- 显式过滤能清零信号层零价污染。
- H1/H2 指标改善，但 Q1 的回撤和 Sharpe 明显变差。
- 当前证据支持把该过滤保留为显式研究选项和报告诊断，不支持默认开启为 formal quality gate。

### Phase 12: Price Quality Attribution Rerun

- **Status:** complete
- Actions taken:
  - 新增 `excludeCrossMarketZeroPriceRows` 显式研究开关，用于过滤零行情形态下的跨市场/非 A 股/代码失配行。
  - 新增 `excludeAllZeroPriceFrames` 显式研究开关，用于剔除整帧价格全为 `0` 或不可解析的异常快照。
  - 跨市场过滤使用 MongoDB `stock_names` A 股代码表辅助判断，并跳过全零帧，避免归因混淆。
  - 运行 `checkpoint_2026-05-21_cross_market_zero_filter_v2` 与 `checkpoint_2026-05-21_all_zero_frame_filter`。
  - 提取 H1/H2/Q1 的收益、回撤、交易数和 zero-price signal 分布。
  - Code review 后补充两处防护：显式过滤后若可用股票帧低于 `minSnapshotCount`，直接返回结构化质量失败；跨市场零行情判断保留原始港股代码前缀，避免 `00700` 被归一化成 `000700` 后漏判。
- Files created/modified:
  - `quant-board/backend/services.py`
  - `quant-board/backend/cli.py`
  - `quant-board/tests/test_money_flow_quality_gate.py`
  - `quant-board/tests/test_quant_board.py`
  - `quant-board/docs/api-cli.md`
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/findings.md`
  - `quant-board/docs/optimization-long-task/progress.md`
  - `quant-board/data/reports/long_test_runs.jsonl`

Cross-market / code-mismatch zero-price checkpoint:

| Baseline | Run ID | totalReturn | maxDrawdown | Sharpe | trades | dropped rows | zero-price signals |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `H1_half_hour_current_bar` | `bt_57371fbc97ad4371` | `+6.47%` | `-2.81%` | `0.4117` | `54` | `902` | `257` |
| `H2_half_hour_next_bar` | `bt_4fe7fd28fcce4146` | `-1.40%` | `-5.46%` | `-0.7370` | `64` | `902` | `257` |
| `Q1_quarter_hour_next_bar` | `bt_b59b804884ae465a` | `-5.85%` | `-14.80%` | `-1.6658` | `133` | `1886` | `683` |

All-zero frame checkpoint:

| Baseline | Run ID | totalReturn | maxDrawdown | Sharpe | trades | dropped frames | zero-price signals |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `H1_half_hour_current_bar` | `bt_ac33b22a9f974170` | `+4.49%` | `-2.82%` | `-0.0003` | `54` | `0` | `976` |
| `H2_half_hour_next_bar` | `bt_70c9e89288504b24` | `-6.37%` | `-9.16%` | `-1.3844` | `64` | `0` | `976` |
| `Q1_quarter_hour_next_bar` | `bt_751dbc4783614ace` | `-2.79%` | `-9.20%` | `-1.0975` | `105` | `1` | `2381` |

Conclusion:

- H1/H2 的改善主要来自跨市场/非 A 股/代码失配零行情过滤；half_hour 当前没有全零价格帧。
- Q1 中，全零帧过滤改善回撤并减少交易数，但跨市场过滤使回撤加深，说明 quarter_hour 入场路径对早期历史样本很敏感。
- 全量 `price<=0` 过滤仍只适合作为显式研究口径；下一步更适合新增 report-only 价格质量诊断字段，而不是默认开启任何价格过滤。

## Session: 2026-05-22

### Phase 12 Review Fixes

- **Status:** complete
- Actions taken:
  - 修复显式过滤后可用股票帧不足仍继续产出 completed 报告的问题。
  - 修复跨市场零行情判断中港股短码被 A 股 6 位归一化混淆的问题。
  - 补 helper 与 API/service 层回归测试。
  - 已提交：`73c788b Add RankTrend price quality research filters`。
- Remaining local files:
  - `.playwright-cli/` 为无关未跟踪工具产物，未纳入提交。

### Phase 13: Report-Only Price Quality Diagnostics

- **Status:** in_progress
- Actions taken:
  - 新增默认开启的只读诊断字段，不改变默认过滤、交易逻辑和质量等级。
  - 诊断字段：`crossMarketZeroPriceRows`、`allZeroPriceFrames`、`partialAshareZeroPriceRows`。
  - 输出位置：`dataQuality.reportOnlyDiagnostics.priceQuality`。
  - long-test JSONL 摘要追加 `priceQualityDiagnostics`，用于后续 checkpoint 横向观察。
  - 补充 helper 分类测试、API/service 默认 report-only 测试和 long-test 摘要测试。

## Test Results

| Test | Input | Expected | Actual | Status |
| --- | --- | --- | --- | --- |
| Health check | `GET /api/health?deep=true` | 后端和 MongoDB 可用 | `status=ok`，MongoDB connected | pass |
| List datasets | `backend.cli list-datasets` | 返回 `dragonboard_live` | 返回 3 个数据集，主数据集完整 | pass |
| Baseline current_bar | `run-ranktrend --execution-mode current_bar` | 生成基线报告 | `bt_f11b21879f804778` | pass |
| Baseline next_bar | `run-ranktrend --execution-mode next_bar` | 生成保守基线报告 | `bt_d8fbef53ec434fde` | pass |
| Launch optimization | `POST /api/optimizations/rank-trend` | 返回 running runId | `opt_70e72a69c40143be` | pass |
| Poll optimization | `GET /api/optimizations/opt_70e72a69c40143be` | 返回 completed 或 failed | `completed`，36 trials，0 failed | pass |
| Snapshot type distribution | `GET /api/snapshots/records?dataset_id=dragonboard_live` | 解释 755 与 half_hour 差异 | half_hour `191`，quarter_hour `438`，hourly `104`，daily `22` | pass |
| Launch quarter_hour optimization | `POST /api/optimizations/rank-trend` | 返回 running runId | `opt_fcf1f30063514bb7` | pass |
| Poll quarter_hour optimization | `GET /api/optimizations/opt_fcf1f30063514bb7` | 返回 completed 或 failed | `completed`，27 trials，0 failed | pass |
| Long-test CLI unit tests | `pytest tests/test_quant_board.py -k "longtest_baselines or longtest_baseline_summary"` | 新增用例通过 | 2 passed | pass |
| Long-test checkpoint | `backend.cli run-longtest-baselines --checkpoint-id checkpoint_2026-05-21_initial` | 三条固定基线落库并追加 JSONL | `bt_7493e60c21574bd8`、`bt_923ecfa4517948f4`、`bt_359953a7dba24206` | pass |
| Money-flow quality tests | `pytest tests/test_money_flow_quality_gate.py tests/test_quant_board.py -k "money_flow or longtest_baseline_summary"` | 资金流统计回归通过 | 6 passed | pass |
| Money-flow gate dry check | `_prepare_frames_for_backtest` on live half/quarter frames | 资金流统计非零且不触发本轮价格门禁 | half formal `4711`；quarter formal `8698` | pass |
| Money-flow validation backtest | `run-ranktrend --snapshot-type half_hour --execution-mode next_bar` | 报告质量统计恢复 | `bt_1f012ea44bb44092`，formal `4711`，estimated `10802` | pass |
| Non-positive price Mongo stats | direct Mongo query on `snapshot_stock_rows` | 统计 half/quarter 非正价格分布 | half `1165`，quarter `2673` | pass |
| Non-positive price baseline impact | persisted H1/H2/Q1 runs | 确认实际成交未使用零价格 | zero-price events/trades/source refs 均为 `0` | pass |
| Positive-price filter tests | `pytest tests/test_money_flow_quality_gate.py tests/test_quant_board.py -k "money_flow or positive_price or longtest_baseline or cli_run_ranktrend_exposes_ui_backtest_parameters"` | 显式开关和过滤统计测试通过 | `10 passed` | pass |
| Positive-price filtered checkpoint | `run-longtest-baselines --checkpoint-id checkpoint_2026-05-21_price_filter --exclude-non-positive-price-rows` | 三条 filtered baseline 落库并追加 JSONL | `bt_a5e56233f6fb4805`、`bt_801abe6f44e146df`、`bt_56d52c783fd84776` | pass |
| Filtered signal distribution extraction | 完整回测报告读取 | 对比 H1/H2/Q1 过滤前后 tier 与 zero-price signals | zero-price signals 全部归零；H1/H2 改善，Q1 回撤变差 | pass |
| Split price filter tests | `pytest tests/test_money_flow_quality_gate.py tests/test_quant_board.py -k "money_flow or positive_price or cross_market or all_zero or longtest_baseline or cli_run_ranktrend_exposes_ui_backtest_parameters"` | 分拆过滤开关、统计和 CLI payload 通过 | `14 passed` | pass |
| Phase 12 review regression tests | `pytest tests/test_money_flow_quality_gate.py tests/test_quant_board.py -k "money_flow or positive_price or cross_market or all_zero or runtime_price or longtest_baseline or cli_run_ranktrend_exposes_ui_backtest_parameters"` | 过滤后样本不足阻断、港股原始前缀识别和既有过滤开关通过 | `16 passed` | pass |
| Phase 12 service/API regression tests | `pytest tests/test_money_flow_quality_gate.py tests/test_quant_board.py -k "price or cross_market or all_zero or runtime_price_filters or cli_run_ranktrend or longtest_baselines"` | helper、CLI、API/service 层价格过滤回归通过 | `12 passed` | pass |
| Phase 13 report-only diagnostics tests | `pytest tests/test_money_flow_quality_gate.py tests/test_quant_board.py -k "price or cross_market or all_zero or runtime_price_filters or cli_run_ranktrend or longtest_baselines or price_quality_diagnostics"` | report-only 价格诊断、默认不过滤和 long-test 摘要通过 | `14 passed` | pass |
| Cross-market zero-price checkpoint | `run-longtest-baselines --checkpoint-id checkpoint_2026-05-21_cross_market_zero_filter_v2 --exclude-cross-market-zero-price-rows` | 三条 split baseline 落库并追加 JSONL | `bt_57371fbc97ad4371`、`bt_4fe7fd28fcce4146`、`bt_b59b804884ae465a` | pass |
| All-zero frame checkpoint | `run-longtest-baselines --checkpoint-id checkpoint_2026-05-21_all_zero_frame_filter --exclude-all-zero-price-frames` | 三条 split baseline 落库并追加 JSONL | `bt_ac33b22a9f974170`、`bt_70c9e89288504b24`、`bt_751dbc4783614ace` | pass |
| Split signal distribution extraction | 完整回测报告读取 | 对比分拆过滤后的 zero-price signal 分布 | cross-market 后 H1/H2 `257`、Q1 `683`；all-zero 后 H1/H2 `976`、Q1 `2381` | pass |

## Error Log

| Timestamp | Error | Attempt | Resolution |
| --- | --- | --- | --- |
| 2026-05-21 | PowerShell 输出中文乱码 | 1 | 以 runId 和数值字段为准，将关键结论写入 Markdown。 |
| 2026-05-21 | `run-ranktrend` CLI 完整 JSON 输出过大导致 shell 超时 | 1 | run 已落库为 `bt_1f012ea44bb44092`；改用小脚本读取落库质量字段。 |
| 2026-05-21 | 一次性读取 6 个完整回测报告提取信号分布超时 | 1 | 改为给足超时时间并分批读取完整报告，最终取得过滤前后信号分布。 |
| 2026-05-21 | 第一版跨市场过滤把全零异常帧里的行也按行过滤，归因不够干净 | 1 | 改为跨市场过滤跳过全零帧并记录 skipped，再重跑 v2 checkpoint。 |

## 5-Question Reboot Check

| Question | Answer |
| --- | --- |
| Where am I? | Phase 11 已完成：显式 `price<=0` 过滤复跑和前后对比已完成。 |
| Where am I going? | Phase 12 已完成；下一步可新增 report-only 价格质量诊断字段，拆出跨市场零行情、全零帧和局部 A 股报价缺失。 |
| What's the goal? | 在 `dragonboard_live` 上形成可追溯、可复跑、质量字段真实可信的 RankTrend 长测链路。 |
| What have I learned? | H1/H2 的零价影响主要来自跨市场/非 A 股/代码失配零行情；Q1 同时受全零异常帧和过滤后路径变化影响。 |
| What have I done? | 完成健康检查、数据集枚举、基线回测、优化、长测自动化、资金流质量统计修复、非正价格诊断、显式过滤复跑和 Phase 12 分拆归因复跑。 |
