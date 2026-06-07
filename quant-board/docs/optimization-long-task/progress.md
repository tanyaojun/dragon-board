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

- **Status:** complete
- Actions taken:
  - 新增 `_price_quality_diagnostics()` 在 `BacktestService.run_ranktrend` 中，基于 `_prepare_frames_for_backtest` 后、显式研究过滤前的 `run_frames` 计算价格诊断。
  - 诊断字段：`crossMarketZeroPriceRows`（跨市场/非 A 股零行情行）、`allZeroPriceFrames`（整帧价格为 0 的异常快照）、`partialAshareZeroPriceRows`（A 股局部零价行）。
  - 诊断元数据：`role=report_only`、`autoApplyDefaults=False`、`computedBeforeResearchFilters=True`。
  - 输出位置：`quality_gate["reportOnlyDiagnostics"]["priceQuality"]`，经 `BacktestEngine._data_quality_summary` 原样透传到报告 `dataQuality.reportOnlyDiagnostics.priceQuality`。
  - long-test JSONL 摘要追加 `priceQualityDiagnostics` 字段（`summarize_longtest_baseline` 行 688）。
  - 默认回测不启用任何价格过滤，`severity`/`researchGrade` 不受诊断影响；测试验证 `runtimeFilter` 为空 `{}`。
  - 补充测试：`test_price_quality_diagnostics_classifies_zero_price_root_causes`（helper 分类）、`test_ranktrend_backtest_price_quality_diagnostics_are_report_only_by_default`（API/service 层）、`test_summarize_longtest_baseline_includes_price_quality`（long-test 摘要）。14 个相关测试全部通过。
- Files created/modified:
  - `quant-board/backend/services.py`（`_price_quality_diagnostics` + `_price_is_positive` + `_is_cross_market_zero_price_stock` + `_has_zero_quote_shape` + `_raw_stock_code` + `_load_a_share_codes`）
  - `quant-board/backend/core/backtest/engine.py`（`reportOnlyDiagnostics` 透传）
  - `quant-board/backend/cli.py`（`summarize_longtest_baseline` 追加 `priceQualityDiagnostics`）
  - `quant-board/tests/test_money_flow_quality_gate.py`（helper 分类测试）
  - `quant-board/tests/test_quant_board.py`（API/service 层和 long-test 摘要测试）
  - `quant-board/docs/api-cli.md`（Phase 13 文档）
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/progress.md`

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

## Session: 2026-05-26

### Weekly Checkpoint: `checkpoint_2026-05-26_weekly`

- **Status:** complete
- Actions taken:
  - 提交 Phase 13 文档更新（commit `3bd7a06`）。
  - 执行 `run-longtest-baselines --checkpoint-id checkpoint_2026-05-26_weekly`，复跑 H1/H2/Q1 三条固定基线。
  - 对比 5/21 → 5/26 绩效、资金流和价格质量变化。
  - 首次落库 `priceQualityDiagnostics` 诊断字段。
- Key findings:
  - H2 totalReturn: -6.37% → -4.04% (+2.33pp)，Sharpe 同步改善。
  - H1 totalReturn: +4.49% → +3.98% (-0.51pp)，最近一周对乐观入场路径不利。
  - Q1 totalReturn: -3.27% → -2.10% (+1.17pp)，回撤维持 -11.06%。
  - 资金流 L2 formal 翻倍：half_hour 4,711 → 10,517，quarter_hour 8,698 → 19,672。
  - 价格质量诊断：half_hour 无全零帧，跨市场 1003 行/191 快照，局部 A 股零价 297 行。
- Files created/modified:
  - `quant-board/docs/optimization-long-task/task_plan.md`
  - `quant-board/docs/optimization-long-task/progress.md`
  - `quant-board/data/reports/long_test_runs.jsonl`（追加本次 checkpoint）

## Session: 2026-05-27 (V2 Design & Phase A-C Implementation)

### Phase 14: V2 四层框架设计

- **Status:** complete
- 完成五痛点澄清 → 四层架构设计 → 交叉评审 → P0 修复
- 输出设计文档：`2026-05-26-longtest-v2-design.md`
- 4 个 P0 修正：策略层参数分两阶段、双层止损、Layer 2 相对阈值、Layer 1 精度门槛

### Phase 15-16: V2 Phase A-C 实施 + 代码审查

- **Status:** complete
- 6 次提交，19 项测试通过
- Phase A: TradeJournal 7 字段 + TypeScript + Vue 表单
- Phase B: `compute_signal_efficacy()` + `compute_execution_quality()` 接入管线
- Phase C: `/api/backtests/alignment` + CLI 集成
- 发现并修复 `candidateTier` 字段路径错误
- Spec 合规：16 项检查，12 通过，4 延后
- 代码质量：7 项发现，修复 4 项（DRY、L2 yellow、inline import、死代码）

### Phase 17: Phase A-C 收尾

- **Status:** complete
- L1 熔断：`check_layer1_meltdown()` 连续 3 期 red 检测
- L3 跨期追踪：`check_layer3_trend()` 连续 2 期 sufficient 检测
- JSONL 历史读取：`read_checkpoint_history()`
- 补测试缺口 9 项（空信号、无下帧、不含 MongoDB、空 run_ids、history 参数、熔断、追踪）
- 测试从 20 项 → 43 项

### Files created/modified:
- `quant-board/backend/services.py` — 新增 compute_signal_efficacy, compute_execution_quality, compute_alignment, read_checkpoint_history, check_layer1_meltdown, check_layer3_trend
- `quant-board/backend/api/journal_routes.py` — 扩展 7 个执行字段
- `quant-board/backend/data/models.py` — TradeJournal 执行字段
- `quant-board/backend/core/backtest/engine.py` — Layer 1-2 透传
- `quant-board/backend/cli.py` — Layer 2 计算、Layer 3 对齐、跨期检查
- `quant-board/backend/main.py` — alignment 端点
- `quant-board/backend/data/quality_gate.py` — synthesized captureMode
- `quant-board/tests/test_money_flow_quality_gate.py` — Layer 1-2 单元测试
- `quant-board/tests/test_quant_board.py` — 集成测试
- `quant-board/docs/superpowers/plans/2026-05-26-longtest-v2-phase-a-c.md`
- `quant-board/docs/superpowers/plans/2026-05-27-phase-a-c-closeout.md`
- `quant-board/docs/optimization-long-task/findings.md`

## Session: 2026-05-29 (Bar Repair & Checkpoint)

### Phase 18: 数据修复

- **Status:** complete
- half_hour 248→290 (+42)、quarter_hour 543→756 (+213)
- v1 直接复制 → v2 前后双 bar 价格/成交量线性插值
- 删除旧复制数据（价格指纹匹配识别）
- 合成 bar 标记 `captureMode: "synthesized"` + `qualityFlags: ["synthesized"]`
- 新建 `backend/data/bar_repair.py` 修复工具

### Phase 19: Checkpoint 复跑

- **Status:** complete
- 补齐前 checkpoint: `checkpoint_2026-05-29_weekly`
- 补齐后 checkpoint: `checkpoint_2026-05-29_interpolated`
- H1 原始 +2.15% → 补齐 +5.45%，Sharpe +0.60 首次转正
- H2 原始 -6.11% → 补齐 -1.06%
- Q1 原始 -3.26% → 补齐 -1.94%，Sharpe +0.10 首次转正
- L1 方向精度 39.81%，仍低于 50% 随机基准，红灯
- L2 黄灯，偏差 6.51pp > 5.45pp 阈值
- 连续 3 期 L1 红灯 → 熔断告警

### Files created/modified:
- `quant-board/backend/data/bar_repair.py` — 修复脚本
- `quant-board/backend/data/quality_gate.py` — synthesized 捕获模式
- `quant-board/backend/cli.py` — emoji 修复
- `quant-board/data/reports/long_test_runs.jsonl` — 追加 checkpoint

## Session: 2026-06-05

### Phase 20: Weekly Checkpoint `checkpoint_2026-06-05_weekly`

- **Status:** complete
- Actions taken:
  - 执行 `run-longtest-baselines --checkpoint-id checkpoint_2026-06-05_weekly`，复跑 H1/H2/Q1 三条固定基线。
  - 新增 44 个 half_hour 帧（5 个交易日：6/01~6/05），覆盖 34 个交易日。
  - 对比 5/29 → 6/05 绩效、四层框架指标和跨期状态变化。
- Key findings:
  - H1 totalReturn: +5.45% → +3.78% (-1.67pp)，Sharpe +0.5984 → +0.1602，回撤加深。
  - H2 totalReturn: -1.06% → -3.94% (-2.88pp)，Sharpe -0.38 → -0.65，回撤 -8.87% → -11.82%。
  - Q1 totalReturn: -1.94% → -9.25% (-7.31pp)，Sharpe +0.101 → -0.3258，回撤 -12.01% → -17.53%。
  - 三条基线全面恶化，本周市场对策略极不友好。
  - L1 方向精度 39.44%（上期 39.81%），仍未突破 50% 随机基准，红灯。
  - L2 黄灯：偏差 7.72pp 超阈值（3.78pp），交易数差异 +28 笔逼近 30% 门槛。
  - L1 熔断：连续 4 期方向精度红灯 → 触发策略结构性复审建议。
  - L3 数据不足：0 笔已执行交易。
- Files created/modified:
  - `quant-board/data/reports/long_test_runs.jsonl` — 追加本次 checkpoint
  - `quant-board/docs/optimization-long-task/progress.md`
  - `quant-board/docs/optimization-long-task/findings.md`

Checkpoint results:

| Baseline | Run ID | totalReturn | maxDrawdown | Sharpe | winRate | trades |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `H1_half_hour_current_bar` | `bt_fd27ea809f3f4c42` | `+3.78%` | `-6.91%` | `+0.1602` | `46.15%` | `91` |
| `H2_half_hour_next_bar` | `bt_6f07661dd79d4962` | `-3.94%` | `-11.82%` | `-0.65` | `36.97%` | `119` |
| `Q1_quarter_hour_next_bar` | `bt_0d6bd329498441ed` | `-9.25%` | `-17.53%` | `-0.3258` | `46.34%` | `246` |

vs 5/29 interpolated 变化:

| 基线 | totalReturn Δ | maxDrawdown Δ | Sharpe Δ | trades Δ | 趋势 |
| --- | ---: | ---: | ---: | ---: | --- |
| H1 | -1.67pp | 恶化 | ↓ | +17 | 本周市场不利 |
| H2 | -2.88pp | 恶化 | ↓ | +18 | 保守路径亏损加深 |
| Q1 | -7.31pp | 恶化 | ↓ | +28 | 细粒度路径崩盘 |

四层框架:

| Layer | Status | 关键指标 |
| --- | --- | --- |
| L1 信号有效性 | red | dirAcc=39.44%, p=1.0, tierDisc=3.1pp |
| L2 执行质量 | yellow | bias=7.72pp > 3.78pp 阈值 |
| L3 实盘对齐 | insufficient_data | 0 executed trades |
| 跨期 L1 熔断 | **触发** | 连续 4 期 red (unknown→unknown→red→red→red→red) |

价格质量诊断:

| 诊断项 | half_hour | quarter_hour |
| --- | ---: | ---: |
| crossMarketZeroPriceRows | 1,676 行 / 300 快照 | 3,715 行 / 658 快照 |
| allZeroPriceFrames | 0 帧 | 1 帧 |
| partialAshareZeroPriceRows | 433 行 / 200 快照 | 1,060 行 / 411 快照 |

资金流 L2 覆盖:

| 口径 | formal | estimated_l1 | missing |
| --- | ---: | ---: | ---: |
| half_hour | 23,253 | 10,572 | 44,615 |
| quarter_hour | 45,227 | 19,888 | 128,934 |

## 5-Question Reboot Check

| Question | Answer |
| --- | --- |
| Where am I? | Phase 17 已完成：V2 Phase A-C 实施、收尾、代码审查。Phase 18-19 已完成：数据修复和 checkpoint 复跑。Phase 20 已完成：6/05 周度 checkpoint。当前数据状态：half_hour 292 帧（MongoDB 原始记录）、quarter_hour 622 帧。34 个 half_hour 交易日（4/16~6/05）。 |
| Where am I going? | 等待 ≥60 个交易日数据启动 Phase D（参数优化）。当前 34 个 half_hour 交易日，还需约 26 个交易日。预计 7 月中。L1 熔断已触发（连续 4 期红灯），需持续监控。 |
| What's the goal? | 在 `dragonboard_live` 上继续每周 checkpoint，用四层框架评估信号质量和执行偏差。数据满 60 天后启动 Layer 4 优化。L1 方向精度若持续不改善，需排查策略逻辑 vs 市场环境归因。 |
| What have I learned? | 本周新增 5 个交易日（44 帧）后三条基线全面恶化。L1 方向精度（39.44%）长期低于随机基准（50%），说明 MACD(21,34,13)+多周期动量(3,5,8,13,21) 当前参数下 A_MAIN 信号的上涨预测能力系统性偏弱。这不是单一市场事件的短期波动，而是连续 4 期的持续问题。H1-H2 偏差在扩大（7.72pp），乐观入场优势在收窄。 |
| What have I done? | 完成 V2 设计、Phase A-C 实施、代码审查修复、L1 熔断/L3 追踪、bar 补齐（线性插值）、5/29 和 6/05 checkpoint 复跑。累计 43 项测试（未新增）。11 次代码提交（未新增）。 |

## Session: 2026-06-07

### Phase 21: Early Big Move V1 长测基线切换

- **Status:** complete
- Actions taken:
  - 用户确认旧 `H1/H2/Q1` 生命周期分层长测没有继续价值。
  - 新增设计文档：`quant-board/docs/superpowers/specs/2026-06-07-ranktrend-early-big-move-longtest-baselines.md`。
  - 新增实施计划：`quant-board/docs/superpowers/plans/2026-06-07-ranktrend-early-big-move-longtest-baselines.md`。
  - 新增默认 baseline set：`early_big_move_v1`。
  - 保留旧基线为显式 `legacy_lifecycle_v1`，只服务历史复跑。
  - 已清空旧本地 JSONL：`quant-board/data/reports/long_test_runs.jsonl`。
  - 修复 `ranktrend_early_big_move` 入场取值：兼容 Python replay 的 `technical.momentumProfile` 字段。
  - 删除修复前 0 成交的中间 run：`bt_9ccb4b9eb6d141e0`、`bt_53016eb0c69b4cde`、`bt_9c6fad650c664c43`。
  - 修正 `E3_half_hour_ranked_strict_fill` 的 `fillFallbackMode=strict_fill`，并删除非 strict 中间 run：`bt_16dc52abd75d47ec`、`bt_17675fe322af4c45`、`bt_fccacc70ebc94b7b`。
  - 重新清空 JSONL 后启动最终 checkpoint：`checkpoint_2026-06-07_early_big_move_v1`。

New baselines:

| Label | Strategy | Snapshot | Execution | Purpose |
| --- | --- | --- | --- | --- |
| `E1_half_hour_signal_forward40` | `ranktrend_early_big_move` | `half_hour` | signal-only | 候选召回 |
| `E2_half_hour_ranked_current_bar` | `ranktrend_early_big_move` | `half_hour` | `current_bar` | 即时处理乐观上限 |
| `E3_half_hour_ranked_strict_fill` | `ranktrend_early_big_move` | `half_hour` | `next_bar` + strict fill | 保守可执行性 |

Checkpoint results:

| Label | Run ID | totalReturn | maxDrawdown | Sharpe | winRate | trades | buyFilled |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `E1_half_hour_signal_forward40` | `bt_359fe12a4c9c487f` | n/a | n/a | n/a | n/a | n/a | n/a |
| `E2_half_hour_ranked_current_bar` | `bt_d4732abbb1c5486e` | `-7.43%` | `-16.08%` | `-0.4157` | `48.15%` | `108` | `112` |
| `E3_half_hour_ranked_strict_fill` | `bt_2e3959f3ddb34ace` | `-5.31%` | `-15.08%` | `-0.6243` | `38.00%` | `100` | `105` |

Finding:

- 第一层 early big move 候选可进入交易模拟，不是 0 候选问题。
- 当前排序/卖出/风控组合仍为负收益，不能直接作为买入规则。
- 下一阶段应围绕二级排序、卖出规则、涨幅区间和风险过滤做长测，不再恢复旧 `final=buy` 或 H1/H2/Q1 生命周期硬买入。

### Phase 22: Early Big Move V1 交易归因

- **Status:** complete
- Actions taken:
  - 读取 E2 run：`bt_d4732abbb1c5486e`。
  - 读取 E3 run：`bt_2e3959f3ddb34ace`。
  - 用 `entrySignalSnapshotId + code` 匹配入场时 raw replay signal。
  - 发现并修正归因字段口径：`technical.signals.acceleration.score` 是 0~1 技术信号分数；真正的多周期动量加速度是 `technical.momentumProfile.acceleration`。
  - 按 `candidateTier`、`stage`、当前涨幅区间、样本质量、`zeroCross/MACD/finalSignal`、退出原因拆分 winners / losers。
  - 将 Phase 22 结论同步到 `task_plan.md` 和 `findings.md`。

Key attribution:

| 条件 | E2 胜率/收益 | E3 胜率/收益 |
| --- | --- | --- |
| 全部 | `48.15% / -32.97%` | `38.00% / -46.36%` |
| 剔除 `N_NEUTRAL` | `55.56% / +31.24%` | `43.10% / -10.41%` |
| `A_MAIN/B_IGNITION` 且涨幅 `< 6%` | `62.79% / +51.71%` | `48.84% / +32.19%` |
| 仅 `A_MAIN` | `47.62% / +2.11%` | `58.82% / +15.91%` |
| 仅 `N_NEUTRAL` | `37.78% / -64.21%` | `30.95% / -35.95%` |

Findings:

- `N_NEUTRAL` 是 V1 交易模拟的主要拖累源。
- `A_MAIN/B_IGNITION + 涨幅 < 6%` 在 E2 已达到 60% 胜率，在 E3 strict fill 中也能把收益拉正，但胜率不足 60%。
- `finalSignal=buy`、MACD 金叉、`zeroCross=buy` 不能作为 early big move 的硬确认；E3 中 `zeroCross=buy` 明显负贡献。
- 旧退出逻辑中的 `compose_decision 卖出信号` 是亏损集中区，不适合直接服务大肉策略。
- 下一轮应做 `early_big_move_v2`：收窄二级入场池，优先 `A_MAIN/B_IGNITION` 与涨幅不过热；出场改为退出热榜 3 bars、止损 5%、`rawChange < -50 + MACD death`，不设固定止盈。

Files modified:

- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/findings.md`
- `quant-board/docs/optimization-long-task/progress.md`

### Phase 23: Early Big Move V2 实现与复跑

- **Status:** complete
- Actions taken:
  - 新增 `ranktrend_early_big_move_v2` 研究策略名，保留 V1 作为对照。
  - 新增 `early_big_move_v2` baseline set：
    - `V2_E1_half_hour_signal_forward40`
    - `V2_E2_half_hour_ranked_current_bar`
    - `V2_E3_half_hour_ranked_strict_fill`
  - V2 入场只交易 `A_MAIN/B_IGNITION`，当前涨幅 `< 6%`；不要求 `finalSignal=buy`、MACD 金叉或 `zeroCross=buy`。
  - V2 出场改为：退出热榜连续 3 bars、止损 5%、`rawChange < -50 + MACD death`、40 bars 上限，不设固定止盈。
  - 补充 TDD 测试：V2 策略名、CLI baseline contract、V2 入场/出场、V2 入场说明不再声称 `finalSignal` 确认。
  - 执行 `checkpoint_2026-06-07_early_big_move_v2`，三条 run 已落库。
  - 修复 `compute_alignment()` 在实盘 journal 为空时仍解压扫描大回测 signals 的性能问题，避免长测 CLI 在 Layer 3 对齐阶段卡住。

Checkpoint results:

| Label | Run ID | totalReturn | realizedReturn | maxDrawdown | Sharpe | winRate | trades | buyFilled |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `V2_E1_half_hour_signal_forward40` | `bt_627db7e6c69446ca` | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `V2_E2_half_hour_ranked_current_bar` | `bt_0d3233550bb54280` | `+5.31%` | `+5.22%` | `-6.81%` | `+1.6033` | `42.42%` | `33` | `37` |
| `V2_E3_half_hour_ranked_strict_fill` | `bt_f34a868872404e17` | `+9.72%` | `+8.99%` | `-9.00%` | `+2.3456` | `55.26%` | `38` | `41` |

Findings:

- V2 把 V1 strict fill 从 `-5.31%` 提升到 `+9.72%`，收益接近目标。
- 胜率仍未达到 `60%`，E3 为 `55.26%`；下一步应做亏损单归因，而不是扩大入场。
- 结果 JSON 前部包含 `controlBacktests`，轻量抓字段时会先读到对照组收益，必须读取顶层主策略字段。
- 第一轮真实 CLI 在三条 run 已 completed 后超时，根因是 Layer 3 对齐扫描大结果；修复后 dry-run 正常。

Validation:

| Command | Result |
| --- | --- |
| `pytest tests/test_trade_simulator_round_trips.py tests/test_quant_board.py -k "early_big_move_v2 or early_big_move or longtest_baselines or compute_alignment_skips" -q` | `17 passed` |
| `backend.cli run-longtest-baselines --baseline-set early_big_move_v2 --checkpoint-id checkpoint_early_big_move_v2_dry_after_alignment_fix --dry-run` | payload 正常 |

Known unrelated test failures from wider run:

- `test_trade_simulator_realistic_matching_constraints`
- `test_theme_trend_backtest_generates_trade_events_for_theme_exposures`
- `test_theme_trend_report_includes_lifecycle_returns_and_trade_diagnostics`

Files modified:

- `quant-board/backend/core/backtest/execution.py`
- `quant-board/backend/core/backtest/strategy.py`
- `quant-board/backend/cli.py`
- `quant-board/backend/services.py`
- `quant-board/tests/test_trade_simulator_round_trips.py`
- `quant-board/tests/test_quant_board.py`
- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/progress.md`

### Phase 24: Early Big Move V2 亏损单归因

- **Status:** complete
- Actions taken:
  - 读取 V2 E3 strict-fill run：`bt_f34a868872404e17`。
  - 同步读取 V2 E2 current-bar run：`bt_0d3233550bb54280` 作为对照。
  - 确认胜率口径必须使用 `roundTripTrades`：E3 为 38 笔完整回合；`trades/backtest_trades` 为 56 条卖出切片。
  - 确认完整信号特征需要从 `result.signals` 读取；Mongo `backtest_signals` 归一化表缺少完整 `rankTrend` 嵌套字段。
  - 按 `(entrySignalSnapshotId, code)` 匹配入场信号，提取 `jump`、`momentumProfile`、`technical.signals`、MACD、finalSignal 和风险字段。
  - 列出 E3 17 笔亏损单，并按出场原因、候选层、zeroCross、divergence、动量阈值做对照统计。

Key findings:

| Metric | Value |
| --- | ---: |
| E3 round trips | `38` |
| E3 winners / losers | `21 / 17` |
| E3 win rate | `55.26%` |
| Winner profit | `+205,580.06` |
| Loser profit | `-115,642.62` |
| Net profit | `+89,937.44` |

Loss concentration:

| Group | Losing trades | Profit |
| --- | ---: | ---: |
| `B_IGNITION` | `17 / 17` | `-115,642.62` |
| `A_MAIN` | `0 / 4` | `+77,468.75` |
| 止损 | `7` | `-81,819.44` |
| 排名大幅下降+MACD死叉 | `5` | `-12,455.21` |
| 退出热榜连续3个bar | `3` | included in reason total |
| 到达最大持有快照 | `2` | included in reason total |

Candidate observations:

- `A_MAIN` 是本轮大肉核心：4 笔全赢，平均收益 `+12.20%`。
- `B_IGNITION` 不是不能交易，但需要二次确认；34 笔胜率 `50.00%`，利润主要被 7 笔止损吞掉。
- `zeroCross=buy` 在 V2 E3 中反而强：23 笔胜率 `73.90%`。
- `mid >= 20` 的简单观察能把胜率推到 `60.70%`，利润 `+103,315.44`；下一轮可作为验证候选。
- 本阶段只做归因，不改策略代码，不重跑回测。

Files modified:

- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/findings.md`
- `quant-board/docs/optimization-long-task/progress.md`

### 2026-06-07 V3 Loss Analysis Attempt

- 读取 V3/V2 多个完整 backtest run 的一次性脚本超时。
- 调整方案：改为单 run 分批读取，只提取 roundTripTrades、signals 和必要特征，避免重复解压大结果。

### Phase 25: Early Big Move V3 + 50 bars 复跑与归因

- **Status:** complete
- Actions taken:
  - 确认当前代码已新增 `ranktrend_early_big_move_v3` 和 `early_big_move_v3` baseline set。
  - V3 baseline 已按用户要求使用 `maxHoldingBars=50`。
  - 复核 checkpoint：`checkpoint_2026-06-07_early_big_move_v3`。
  - 读取 V3 E3 strict-fill run：`bt_b8061da4f92c4462`。
  - 用 `roundTripTrades` 作为胜率口径；用 `(entrySignalSnapshotId, code)` 回连 `result.signals` 读取完整入场特征。
  - 记录一次分析脚本超时：一次性读取多个完整 run 会触发大 JSON 解压瓶颈；已改为单 run 读取。

Checkpoint results:

| Label | Run ID | totalReturn | realizedReturn | maxDrawdown | Sharpe | winRate | trades | buyFilled |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `V3_E1_half_hour_signal_forward50` | `bt_4c7f44f34ab448fe` | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| `V3_E2_half_hour_ranked_current_bar` | `bt_5681c2735de646a1` | `+12.93%` | `+10.36%` | `-3.66%` | `+2.6936` | `58.06%` | `31` | `34` |
| `V3_E3_half_hour_ranked_strict_fill` | `bt_b8061da4f92c4462` | `+9.32%` | `+8.73%` | `-7.13%` | `+1.9207` | `54.84%` | `31` | `33` |

V3 E3 findings:

- 31 笔完整回合，17 赢 / 14 输，胜率 `54.84%`。
- `50 bars` 确实有利于抓大肉：到达最大持有快照 8 笔全胜，利润约 `+141,258.94`。
- 最大亏损源是止损：9 笔，合计约 `-95,119.38`。
- `A_MAIN` 在 V3 真实复跑后不再全胜：16 笔胜率 `50.00%`，但仍贡献 `+63,282.43`。
- `B_IGNITION` 经 V3 二次确认后 15 笔胜率 `60.00%`，贡献 `+24,025.48`，比 V2 的 B 层稳定。
- `final=buy` / MACD 金叉在 V3 E3 已成交样本中表现偏弱：9 笔胜率 `33.30%`，合计 `-37,048.12`；不能作为硬入场确认。

Validation:

| Command | Result |
| --- | --- |
| `pytest tests/test_trade_simulator_round_trips.py tests/test_quant_board.py -k "early_big_move_v3 or early_big_move_v2 or early_big_move or longtest_baselines" -q` | `19 passed, 64 deselected` |

Next decision:

- V3 current-bar 达到收益目标但未达胜率目标；V3 strict-fill 未超过 V2 strict-fill。
- 下一轮不继续盲目加入场硬过滤；先拆 V3 E3 止损单，看是否应增加“入场后风险确认/隔日弱化过滤/止损前风险退出”，且不能牺牲 50 bars 大肉奔跑。

### Phase 26: V3 30 bars 月度窗口回测

- **Status:** complete
- Actions taken:
  - 用户要求先不拆止损单，优先验证最大持仓 bars 的最优值。
  - 统一使用 `ranktrend_early_big_move_v3`、`half_hour`、`maxHoldingBars=30`、`takeProfitPct=9.99`、`stopLossPct=0.05`。
  - 跑 4 个窗口：4月/5月 current-bar，4月/5月 strict-fill。
  - strict-fill 使用 `executionMode=next_bar` + `tradeConfig.fillFallbackMode=strict_fill`。
  - 自然月参数为 4月 `2026-04-01~2026-04-30`、5月 `2026-05-01~2026-05-31`；Mongo 实际可用窗口分别为 `2026-04-16~2026-04-30`、`2026-05-06~2026-05-29`。

Results:

| Window | Mode | Run ID | actual dates | totalReturn | realizedReturn | winRate | trades | maxDrawdown | openPositions |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4月 | current-bar / 30 bars | `bt_a80a2e51db204882` | `2026-04-16~2026-04-30` | `+6.76%` | `+3.12%` | `90.00%` | 10 | `-2.67%` | 5 |
| 5月 | current-bar / 30 bars | `bt_24bce043660b48ec` | `2026-05-06~2026-05-29` | `+14.81%` | `+12.74%` | `64.71%` | 17 | `-4.06%` | 3 |
| 4月 | strict-fill / 30 bars | `bt_b1be9464a58a483b` | `2026-04-16~2026-04-30` | `+5.38%` | `+1.68%` | `75.00%` | 4 | `-1.26%` | 5 |
| 5月 | strict-fill / 30 bars | `bt_38dcde4453c2447c` | `2026-05-06~2026-05-29` | `+9.07%` | `+6.24%` | `57.14%` | 21 | `-8.56%` | 2 |

Immediate read:

- `30 bars` 在 current-bar 两个月都同时满足收益和胜率目标。
- strict-fill 下 4月胜率很高但交易数只有 4，样本太小；5月 strict-fill 收益接近 `10%`，但胜率低于 `60%`。
- 因为这些窗口仍有未平仓，`totalReturn` 含浮盈浮亏；同时看 `realizedReturn` 更稳。

### Phase 27: Current-bar / 30 bars 止损单归因

- **Status:** complete
- Actions taken:
  - 按用户确认，把 `current-bar / 30 bars` 作为当前主线口径，不再继续优先拆 strict-fill。
  - 读取 4 月 current-bar / 30 bars run：`bt_a80a2e51db204882`。
  - 读取 5 月 current-bar / 30 bars run：`bt_24bce043660b48ec`。
  - 用 `roundTripTrades` 口径复核完整交易回合，避免把买卖切片误算成胜率。
  - 用 `(entrySignalSnapshotId, code)` 回连 `result.signals`，提取入场 `candidateTier`、`regime`、`jump.confidence`、多周期动量、`zeroCross`、MACD 和 `finalSignal`。
  - 拉取 4 笔止损票入场前后 1-4 个 half-hour bar 的 RankTrend 信号变化。
  - 检查 `tradeEvents`、`skippedOrders` 和 Mongo 原始半小时盘口，确认 `603773` 的超额止损来自连续跌停不可卖。

Current-bar / 30 bars combined:

| Group | Trades | Win rate | Profit | Stop losses |
| --- | ---: | ---: | ---: | ---: |
| 全部 | 27 | `74.1%` | `+158,615.21` | 4 |
| `A_MAIN` | 17 | `76.5%` | `+113,687.83` | 4 |
| `B_IGNITION` | 10 | `70.0%` | `+44,927.38` | 0 |

Stop-loss trades:

| Code | Name | Entry signal | Return | Profit | Bars | Key issue |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `000070` | 特发信息 | `2026-04-22 10:00` | `-6.01%` | `-11,908.72` | 20 | `A_MAIN / retreat` 且 `long=5.62`，入场后快速变弱 |
| `603773` | 沃格光电 | `2026-05-12 09:30` | `-25.82%` | `-10,663.86` | 48 | 5/15、5/18 连续跌停不可卖，`skippedOrders=limit_down_unsellable` |
| `002281` | 光迅科技 | `2026-05-25 14:30` | `-5.36%` | `-9,619.22` | 4 | `A_MAIN / weak` 且 `long=6.50`，次日直接转弱 |
| `301666` | 大普微-UW | `2026-05-22 09:30` | `-7.75%` | `-6,134.56` | 24 | 入场涨幅为负，`final=buy/MACD golden` 仍失败 |

Findings:

- `current-bar / 30 bars` 的止损源头从 V2 的 `B_IGNITION` 转到了 V3 的 `A_MAIN` 质量漂移。
- `B_IGNITION` 这轮不应再被优先砍掉；V3 二次确认后 B 层在 current-bar / 30 bars 中没有止损。
- 需要解决的是 `A_MAIN` 假主升：弱长周期、入场涨幅为负、入场后 1-2 bar 快速掉档，尤其是 `A_MAIN + weak + long < 10`。
- `603773` 是执行风险样本：跌停不可卖会让止损远超 5%，也会让实际持仓超过 30 bars；这不能简单归因成持仓上限或止损参数问题。
- 初步离线候选中，剔除 `A_MAIN + weak + long < 10` 或 `A_MAIN + change < 0` 后，合并利润可从 `+158,615.21` 提升到 `+165,317.71`，胜率 `79.2%`，止损 4 -> 2。但这仍需要真实复跑验证。

Next decision:

- 下一步先做 A_MAIN 假主升风险验证，保持 `current-bar / 30 bars`、不恢复固定止盈、不加入固定排名门槛、不把 `final=buy/MACD golden` 当硬确认。

Files modified:

- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/findings.md`
- `quant-board/docs/optimization-long-task/progress.md`

### Phase 28: A_MAIN 假主升过滤验证

- **Status:** complete
- Actions taken:
  - 新增窄作用域研究策略：`ranktrend_early_big_move_v3_a_main_risk_filter`。
  - 策略只验证 A_MAIN 假主升过滤；B_IGNITION 完全沿用 V3 的 `mid>=20 + zeroCross=buy`。
  - 补 TDD 测试确认研究版只过滤 `A_MAIN + weak + long < 10` 或 `A_MAIN + change < 0`，不改 B 规则。
  - 发现首轮中间 run 混用了旧出场逻辑，根因是研究策略名未加入 early big move 专属出场族。
  - 补 TDD 测试复现该问题：研究版不应因 `finalSignal=sell/D_EXIT_RISK/止盈` 提前退出。
  - 修复研究策略出场分发：沿用 V2/V3 的退出热榜 3 bars、止损、`rawChange < -50 + MACD death`、持仓上限。
  - 复跑有效 4 月 current-bar / 30 bars：`bt_ef248f9bbe884b63`。
  - 复跑有效 5 月 current-bar / 30 bars：`bt_6880bb325d604045`。
  - 用 `(entrySignalSnapshotId, code)` 回连完整入场 signal，重新按入场分层统计，避免把退出分层误当入场分层。
  - 阅读 `compose_strategy`，确认 A_MAIN 进入机制：`stage=expansion + mid/short 动量 + trend_buy + 热榜高潮/发酵非高风险 + divergence 不高`；`long` 和 `regime` 不是硬拦截条件。

Effective rerun results:

| Window | Strategy | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown | stops |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4月 | V3 原始 | `bt_a80a2e51db204882` | `+6.76%` | `+3.12%` | `90.00%` | 10 | `-2.67%` | 1 |
| 4月 | A_MAIN 风险过滤 | `bt_ef248f9bbe884b63` | `+4.05%` | `+1.49%` | `80.00%` | 10 | `-4.29%` | 1 |
| 5月 | V3 原始 | `bt_24bce043660b48ec` | `+14.81%` | `+12.74%` | `64.71%` | 17 | `-4.06%` | 3 |
| 5月 | A_MAIN 风险过滤 | `bt_6880bb325d604045` | `+15.27%` | `+12.03%` | `64.71%` | 17 | `-4.06%` | 2 |

Findings:

- 简单 A_MAIN 硬过滤真实复跑不通过，不能写入 V3 默认。
- 过滤确实移除了 `002281`、`301666`，但也改变排序/资金路径，引入 `002600`、`603738` 等新增亏损。
- 4 月收益和胜率明显下降；5 月 totalReturn 略升但 realizedReturn 略降，且 B_IGNITION 变成负贡献。
- 下一步应转向路径感知风险标记/排序，而不是继续加静态 A_MAIN 硬门槛。

Invalid intermediate runs:

- `bt_ca768d6481a44cdb`
- `bt_418bbe7c4ae94bed`

这两个 run 混用了旧退出规则，不能作为研究结论。

Validation:

| Command | Result |
| --- | --- |
| `pytest tests/test_trade_simulator_round_trips.py tests/test_quant_board.py -k "a_main_risk_filter or early_big_move_v3_strategy_name" -q` | `4 passed, 82 deselected` |

Files modified:

- `quant-board/backend/core/backtest/execution.py`
- `quant-board/backend/core/backtest/strategy.py`
- `quant-board/tests/test_trade_simulator_round_trips.py`
- `quant-board/tests/test_quant_board.py`
- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/findings.md`
- `quant-board/docs/optimization-long-task/progress.md`

### Phase 33: 生命周期 A+B 融合设计审计

- **Status:** in_progress
- Actions taken:
  - 按用户最新决策重新定义生命周期定位：RankTrend 是主策略 A，生命周期是辅助决策系统 B；B 不是旧生命周期买卖主策略，也不是松散 report-only 标签。
  - 使用 `planning-with-files` 做会话接续，确认本阶段只做设计审计和计划落盘，不改 TS/Python/执行代码。
  - 复读 `AGENTS.md`、`SKILLS.md`、`quant-board/docs/README.md`、`quant-board/docs/AI_COLLABORATION.md` 与长测三份计划文件。
  - 审计 TS 字段生成链路：`attentionCycleAnalyzer.ts`、`candidateTierComposer.ts`。
  - 审计 Python 字段生成与执行链路：`ranktrend.py`、`execution.py`。
  - 梳理 `rawStage/stage/transition/entryAdvice/metrics` 如何生成、如何进入 `candidateTier`、如何被 V3 执行层间接消费。
  - 检索外部金融研究和国内论坛语义，提炼“动量延续、注意力拥挤、假突破/假主升”的设计参考；外部内容只作为语义原则，不直接生成固定参数。
  - 在 `findings.md` 输出短设计：A+B 融合合同、生命周期 B 语义定义、当前代码需要拆开的点、TDD 测试清单。

Key findings:

- 当前没有显式生命周期 B 决策层；B 被揉进 `candidateTier`，执行层再通过 `candidateTier in A_MAIN/B_IGNITION` 间接消费。
- 这会同时带来两个问题：生命周期可能制造 A/B 候选，也无法对强 A 信号做明确 veto。
- 新合同建议新增 `rankTrend.cycle.decision.action = allow | caution | veto | exit_watch`，其中 `veto` 在执行入口一票否决，`allow/caution` 只影响通过后的排序和解释。
- `entryAdvice.allowed` 后验不可靠，不能继续承担交易许可；保留为展示兼容字段即可。
- 下一步必须 TDD：先写失败测试，再改 TS/Python 输出合同和 QuantBoard 执行入口。
- 资料补充核对：52-week high momentum 与 Momentum Crashes 已写入 Phase 33 外部研究参考；本轮补充 Reddit breakout/fakeout 讨论，明确其只作为“突破后承接失败/假突破”语义提醒，不能直接变成固定参数。

Implementation update:

- 按 TDD 先写并验证失败测试：
  - TS 生命周期合同测试：`cycle.decision` 原本缺失。
  - Python 生命周期合同测试：`cycle["decision"]` 原本缺失。
  - 执行层融合测试：`ranktrend_early_big_move_v3_lifecycle_fusion` 原本未注册/未分发。
- 最小实现：
  - `src/services/rankTrend/types.ts` 新增 `LifecycleDecisionAction` 和 `cycle.decision` 类型。
  - `src/services/rankTrend/attentionCycleAnalyzer.ts` 新增 `buildLifecycleDecision()`。
  - `quant-board/backend/analysis/ranktrend.py` 新增 `lifecycle_decision()` 并输出 `cycle["decision"]`。
  - `quant-board/backend/core/backtest/strategy.py` 注册 research-only 策略 `ranktrend_early_big_move_v3_lifecycle_fusion`。
  - `quant-board/backend/core/backtest/execution.py` 新增 A+B 融合入口：A 必须先通过 V3，B veto 一票否决，B allow 不能制造买入；融合策略沿用 early big move 专属退出规则。
- 验证结果：
  - `pnpm exec vitest run src/services/rankTrend/__tests__/attentionCycleAnalyzer.test.ts`：4 passed。
  - `pytest tests/test_quant_board.py -k "lifecycle_decision_contract or lifecycle_entry" -q`：2 passed。
  - `pytest tests/test_trade_simulator_round_trips.py -k "lifecycle_fusion" -q`：2 passed。
  - `pnpm test:ranktrend`：13 files / 133 tests passed。
  - `pytest tests/test_trade_simulator_round_trips.py tests/test_quant_board.py -k "lifecycle_fusion or lifecycle_decision_contract or lifecycle_entry or no_lifecycle_gate or context_probe or a_main_risk_filter or b_long_filter or early_big_move_v3" -q`：17 passed。
  - `pnpm exec tsc --noEmit --target es2020 --module esnext --moduleResolution bundler --skipLibCheck src/services/rankTrend/types.ts src/services/rankTrend/attentionCycleAnalyzer.ts`：passed。
- 验证限制：
  - `pnpm typecheck:ranktrend` 当前失败，错误集中在 `tsconfig.ranktrend.json` 拉入大量非 RankTrend 依赖但文件列表未覆盖，以及 `lunar-javascript` 声明缺失；本轮未改该配置，避免扩大范围。

Next:

- 复跑 4 月/5 月 `ranktrend_early_big_move_v3_lifecycle_fusion / half_hour / current_bar / maxHoldingBars=30`。
- 对比 V3 主线和 `bt_6880bb325d604045`，重点看 `totalReturn/winRate/tradeCount/maxDrawdown/止损单/大肉保留/假主升减少`。

Implementation follow-up:

- 已复跑 lifecycle fusion：
  - 4 月 `bt_1dd91533206f4b6e`
  - 5 月 `bt_e84b02ef5c284f3a`、`bt_9f5e8606a93d4c59`，两次 5 月指标一致，后续采用最新 `bt_9f5e8606a93d4c59`。
- 为避免代码版本错位，又补跑同代码版本 V3：
  - 4 月 `bt_d7e06ceab8ca454c`
  - 5 月 `bt_020f7489ffe14fa1`
- 结论：fusion 与同代码版本 V3 完全一致；4 月入场集合 same=10，5 月 same=17，fusion 没有新增或剔除任何交易。
- 信号层检查：
  - 4 月 V3 可入场信号 58 个，全部 `cycle.decision.action=allow`。
  - 5 月 V3 可入场信号 146 个，全部 `cycle.decision.action=allow`。
  - 这说明首版 B 合同只是打通字段，尚未具备假突破/假主升拦截语义。
- 亏损单归因：
  - 7 笔亏损多数仍是 `cooling->expansion` / `cooling->ignition` 强跳跃路径，不是现有 `reversal veto` 能挡住的形态。
  - 大肉同样来自这些路径，不能按 transition、long 或固定路径直接硬 veto。
- 已按 TDD 修复一个合同缺口：
  - `cycle.decision.evidence.riskPressure/divergenceSeverity/overheatSeverity` 原来是 0 占位。
  - TS `RankTrendAnalyzer` 现在在算完 `risk` 后回填真实 risk evidence。
  - Python `RankTrendPythonEngine._build_signal()` 现在在算完 `risk` 后回填真实 risk evidence。
  - 本修复不改变 V3 默认策略，也不改变 fusion 的入场 action 判定。
- 验证结果：
  - `pnpm exec vitest run src/services/rankTrend/__tests__/attentionCycleAnalyzer.test.ts`：5 passed。
  - `pytest tests/test_quant_board.py -k "lifecycle_decision_contract or lifecycle_decision_evidence_accepts_risk_pressure or lifecycle_entry" -q`：3 passed。
  - `pytest tests/test_trade_simulator_round_trips.py -k "lifecycle_fusion" -q`：2 passed。
  - `pnpm test:ranktrend`：13 files / 134 tests passed。
  - `pytest tests/test_trade_simulator_round_trips.py tests/test_quant_board.py -k "lifecycle_fusion or lifecycle_decision_contract or lifecycle_decision_evidence_accepts_risk_pressure or lifecycle_entry or no_lifecycle_gate or context_probe or a_main_risk_filter or b_long_filter or early_big_move_v3" -q`：18 passed。
- 运行注意：
  - `BacktestService.run_ranktrend()` 完整回测会落库成功，但 shell 可能因大结果序列化/输出在 120-300 秒超时；后续取指标优先用 Mongo 归一化表 `backtest_trades/backtest_equity_curve`，不要反复 `get_run()` 解压完整大 JSON。

Next:

- 先写失败测试定义 B 的下一层语义：当 A 强但真实 risk evidence 明确反对时，B 应输出 `caution` 或 `veto`。
- 规则设计必须同时保护 `603459` 低 long 大肉，避免重演 B_LONG/A_MAIN 静态硬过滤的误杀。

Files modified:

- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/findings.md`
- `quant-board/docs/optimization-long-task/progress.md`

### Phase 29: 生命周期路径归因

- **Status:** complete
- Actions taken:
  - 用户确认可以重新审视生命周期分层，但要求基于 RankTrend 现有方案，不恢复旧的固定分层买卖逻辑。
  - 固定分析主线为 `ranktrend_early_big_move_v3 / half_hour / current_bar / maxHoldingBars=30`。
  - 读取 V3 原始 4 月 run：`bt_a80a2e51db204882`。
  - 读取 V3 原始 5 月 run：`bt_24bce043660b48ec`。
  - 对照读取 A_MAIN 风险过滤 run：`bt_ef248f9bbe884b63`、`bt_6880bb325d604045`。
  - 用 `roundTripTrades` 作为胜率口径，避免卖出切片误算。
  - 用 `(entrySignalSnapshotId, code)` 回连完整 `result.signals`，提取入场前 3 bars、入场 bar、入场后 2 bars 的路径。
  - 确认可用路径字段为 `rankTrend.cycle.transition`、`rankTrend.cycle.stage`、顶层 `stage` 和 `candidateTier`。
  - 对比盈利/亏损单的生命周期路径、长周期动量、`finalSignal` 和退出原因。

Key findings:

| Group | Trades | Win rate | Profit | Avg return |
| --- | ---: | ---: | ---: | ---: |
| V3 原始 4月+5月 | 27 | `74.1%` | `+158,615.21` | `+3.33%` |
| `A_MAIN` | 17 | `76.5%` | `+113,687.83` | `+3.83%` |
| `B_IGNITION` | 10 | `70.0%` | `+44,927.38` | `+2.50%` |
| `long >= 10` | 20 | `90.0%` | `+136,626.74` | `+4.03%` |
| `long < 10` | 7 | `28.6%` | `+21,988.47` | `+1.34%` |

Candidate checks, not adopted:

| Candidate | Kept trades | Win rate | Profit |
| --- | ---: | ---: | ---: |
| 剔除 `B_IGNITION + long < 10` | 23 | `82.6%` | `+164,488.97` |
| 剔除 `final=buy` | 22 | `77.3%` | `+158,012.92` |
| 剔除 A_MAIN 抖动路径 `ignition/reversal -> cooling -> expansion` | 24 | `79.2%` | `+172,077.38` |

Findings:

- 旧生命周期分层策略仍然不能恢复为主买卖系统。
- 生命周期路径可作为 RankTrend 的上下文，尤其用于识别 `A_MAIN` 假主升和 `B_IGNITION` 弱长周期点火。
- 单点 `cooling->expansion` 不是稳定过滤条件；其中既有大肉也有止损。
- `long >= 10` 很强，但不能一刀切 `long < 10`，因为 `603459 红板科技` 是 `long=4.59` 的大肉特例。
- 下一轮优先做真实复跑候选：`B_IGNITION + long < 10` 降级或剔除；A_MAIN 抖动路径先做排序/降权验证，不直接硬删。

Files modified:

- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/findings.md`
- `quant-board/docs/optimization-long-task/progress.md`

### Phase 30: B_IGNITION 长周期过滤真实复跑

- **Status:** complete
- Actions taken:
  - 延续 Phase 29 的离线候选，新增窄作用域研究策略 `ranktrend_early_big_move_v3_b_long_filter`。
  - 规则只过滤 `B_IGNITION + momentumProfile.long < 10`；`A_MAIN` 完全沿用 V3。
  - 补 TDD 测试确认研究版：
    - 保留 `A_MAIN`；
    - 过滤 `B_IGNITION + mid>=20 + zeroCross=buy + long<10`；
    - 保留 `B_IGNITION + long>=10`；
    - 策略名可被后端识别。
  - 复跑 4 月 current-bar / 30 bars：`bt_3a6339356fe44ef2`。
  - 5 月直接 CLI 输出完整 JSON 超时且输出文件为 0 字节；改用 `BacktestService.run_ranktrend()` 直接调用，只打印摘要，生成有效 run：`bt_1d12cc19e20d492e`。
  - 用 `(entrySignalSnapshotId, code)` 回连完整入场 signal，按 `A_MAIN/B_IGNITION`、`long`、退出原因和交易路径差异做归因。

Results:

| Window | Strategy | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown | stops |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4月 | V3 原始 | `bt_a80a2e51db204882` | `+6.76%` | `+3.12%` | `90.00%` | 10 | `-2.67%` | 1 |
| 4月 | B_LONG 过滤 | `bt_3a6339356fe44ef2` | `+3.64%` | `+3.07%` | `80.00%` | 10 | `-2.86%` | 2 |
| 5月 | V3 原始 | `bt_24bce043660b48ec` | `+14.81%` | `+12.74%` | `64.71%` | 17 | `-4.06%` | 3 |
| 5月 | B_LONG 过滤 | `bt_1d12cc19e20d492e` | `+5.33%` | `+3.08%` | `56.25%` | 16 | `-4.99%` | 5 |

Findings:

- B_LONG 硬过滤真实复跑不通过，不能写入 V3 默认。
- 4 月收益从 `+6.76%` 降到 `+3.64%`，胜率从 `90.00%` 降到 `80.00%`。
- 5 月收益从 `+14.81%` 降到 `+5.33%`，胜率从 `64.71%` 降到 `56.25%`，止损从 3 笔增加到 5 笔。
- 真实复跑变差的核心原因不是 long 阈值本身，而是排序/现金/仓位路径被改变：弱 B 小亏被删后，资金进入 `603993`、`000657` 这类 `long>=10` 强 long 假突破，同时漏掉 `603459` 大肉。
- 下一步应转向候选排序/降权，重点处理强 long 假突破和 A/B 同 bar 竞争，不继续加静态硬过滤。

Errors:

| Error | Resolution |
| --- | --- |
| 5 月 CLI 完整 JSON 输出超时，输出文件 0 字节 | 改用现有 `BacktestService.run_ranktrend()` 直接调用并只打印摘要，run 已落库 |
| 首次归因脚本导入 `loads_json_field` 模块错误 | 改从 `backend.data.json_codec` 导入后重跑成功 |

Files modified:

- `quant-board/backend/core/backtest/execution.py`
- `quant-board/backend/core/backtest/strategy.py`
- `quant-board/tests/test_trade_simulator_round_trips.py`
- `quant-board/tests/test_quant_board.py`
- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/findings.md`
- `quant-board/docs/optimization-long-task/progress.md`

### Phase 31: 生命周期实现审计

- **Status:** complete
- Actions taken:
  - 按用户要求做一次“生命周期实现审计”，本阶段只读代码和已落库回测，不改策略代码。
  - 审计 TS 生命周期本体：`src/services/rankTrend/attentionCycleAnalyzer.ts`。
  - 审计 TS 候选分层：`src/services/rankTrend/candidateTierComposer.ts`。
  - 审计 Python 回测主链：`quant-board/backend/analysis/ranktrend.py`。
  - 审计交易执行消费点：`quant-board/backend/core/backtest/execution.py`。
  - 搜索现有测试，确认生命周期只有少量边界用例，缺少真实交易路径级 TS/Python 对齐。
  - 读取已落库回测：
    - 4 月 V3 current-bar / 30 bars：`bt_a80a2e51db204882`
    - 5 月 V3 current-bar / 30 bars：`bt_24bce043660b48ec`
    - 5 月 A_MAIN 风险过滤：`bt_6880bb325d604045`
    - 5 月 B_LONG 过滤：`bt_1d12cc19e20d492e`
  - 用只读脚本按 `(entrySignalSnapshotId, code)` 回连完整 `result.signals`，聚合 `rawStage/stage/transition/entryAdvice/finalSignal/long` 与盈亏。
  - 新增审计文档：`quant-board/docs/optimization-long-task/2026-06-07-lifecycle-implementation-audit.md`。

Key findings:

| Finding | Conclusion |
| --- | --- |
| 生命周期阶段仍混合固定分位、近期最好名次、热区连续次数和回撤 | 不是纯 RanTrend 动量加速度模型 |
| `normalize_stage` 有状态惯性 | 能降噪，也可能把假主升平滑成 `expansion` |
| TS/Python 候选分层输入漂移 | TS 用 `market_regime`，Python 回测主要用 `hotlistSentiment` |
| V3 交易层消费 `candidateTier=A_MAIN/B_IGNITION` | 生命周期不是纯展示字段，实质参与入场 |
| `entryAdvice=preferred` 不强于 `watch` | 不能作为强买点 |
| `final=buy` / MACD golden 仍偏弱 | 不能恢复为硬确认 |

V3 原始 4 月+5 月只读聚合：

| Group | Trades | Win rate | Profit | Avg return |
| --- | ---: | ---: | ---: | ---: |
| 全部 | 27 | `74.1%` | `+158,615.21` | `+3.33%` |
| `stage=expansion` | 17 | `76.5%` | `+113,687.83` | `+3.83%` |
| `stage=ignition` | 10 | `70.0%` | `+44,927.38` | `+2.50%` |
| `entryAdvice=preferred` | 12 | `75.0%` | `+66,799.92` | `+3.10%` |
| `entryAdvice=watch` | 15 | `73.3%` | `+91,815.29` | `+3.50%` |
| `long >= 10` | 20 | `90.0%` | `+136,626.74` | `+4.03%` |
| `long < 10` | 7 | `28.6%` | `+21,988.47` | `+1.34%` |
| `final=buy` | 5 | `60.0%` | `+602.29` | `-1.26%` |
| `final!=buy` | 22 | `77.3%` | `+158,012.92` | `+4.38%` |

Conclusion:

- 生命周期实现不是完全错误，但当前使用方式过重。
- 旧生命周期分层买卖系统不能恢复。
- 生命周期应降级为 RankTrend 路径上下文、排序降权和 report-only 诊断。
- 下一步应验证 research-only “无生命周期硬门槛”对照：入场主轴回到 `jump 高置信 + 多周期动量同步 + 加速度抬升 + 可成交性`，生命周期不制造买点、不硬过滤。

Files modified:

- `quant-board/docs/optimization-long-task/2026-06-07-lifecycle-implementation-audit.md`
- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/findings.md`
- `quant-board/docs/optimization-long-task/progress.md`

### Phase 32: 无生命周期硬门槛 / 路径探针对照复跑

- **Status:** complete
- Actions taken:
  - 新增 research-only 策略 `ranktrend_early_big_move_v3_no_lifecycle_gate`。
  - 补 TDD 测试，确认：
    - 新策略名可注册；
    - 强 early big move 结构即使不是 `A_MAIN/B_IGNITION` 也能进入研究候选；
    - 默认 V3 行为不被污染。
  - 复跑 4 月 current-bar / 30 bars：`bt_efe08f9fb3954988`。
  - 复跑 5 月 current-bar / 30 bars：`bt_9c00f69c9b09426c`。
  - 读取完整报告，按 `(entrySignalSnapshotId, code)` 回连信号，确认失败主因是大量 `N_NEUTRAL + watch/avoid` 候选挤占交易路径。
  - 在此基础上新增更窄的 research-only 策略 `ranktrend_early_big_move_v3_context_probe`：
    - 保留 V3 原有 `A_MAIN/B_IGNITION` 主干；
    - 只额外探测极少数 `entryAdvice=preferred` 的非 A/B 早期结构候选。
  - 补 TDD 测试，确认 context probe 只在 V3 主干外额外放行 `preferred` 非 A/B 探针，不放行 `watch` 候选。
  - 复跑 4 月 current-bar / 30 bars：`bt_69232223f3024f02`。
  - 复跑 5 月 current-bar / 30 bars：`bt_a23990ecc8084021`。
  - 对比 5 月现有最佳主线 `bt_24bce043660b48ec`，确认 context probe 仍显著劣化胜率和收益。

Results:

| Window | Strategy | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 4月 | no_lifecycle_gate | `bt_efe08f9fb3954988` | `-4.44%` | `-6.15%` | `15.38%` | `13` | `-8.14%` |
| 5月 | no_lifecycle_gate | `bt_9c00f69c9b09426c` | `-0.24%` | `-0.18%` | `29.63%` | `27` | `-11.70%` |
| 4月 | context_probe | `bt_69232223f3024f02` | `+6.76%` | `+3.12%` | `90.00%` | `10` | `-2.67%` |
| 5月 | context_probe | `bt_a23990ecc8084021` | `+9.52%` | `+11.26%` | `50.00%` | `18` | `-6.32%` |

Key findings:

- `no_lifecycle_gate` 已被真实复跑证伪：放开非 A/B 候选后，4 月和 5 月都远离 `60%+` 胜率目标。
- 失败主因不是 A/B 主干本身，而是 `N_NEUTRAL + watch/avoid` 候选进入了真实交易路径。
- `context_probe` 比 no_lifecycle_gate 收敛，但仍未优于现有 V3 主线：
  - 5 月新增 `603399`、`600118`、`000981` 等 `preferred` 非 A/B 探针后，真实路径被拖弱；
  - 即使拿到 `688981` 这类正贡献票，整体仍把 winRate 从 `64.71%` 拉到 `50.00%`。
- 当前证据不支持继续沿“开放非 A/B 候选池”方向推进。

Validation:

| Command | Result |
| --- | --- |
| `pytest tests/test_trade_simulator_round_trips.py tests/test_quant_board.py -k "no_lifecycle_gate or context_probe or early_big_move" -q` | `26 passed` |

Files modified:

- `quant-board/backend/core/backtest/strategy.py`
- `quant-board/backend/core/backtest/execution.py`
- `quant-board/tests/test_trade_simulator_round_trips.py`
- `quant-board/tests/test_quant_board.py`
- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/findings.md`
- `quant-board/docs/optimization-long-task/progress.md`

### Phase 33 Re-audit: 生命周期本体纠偏

- **Status:** in_progress
- Actions taken:
  - 按用户最新反馈重新审视生命周期本体，不再沿用“旧审计有效”的前提。
  - 复读 QuantBoard 协作文档和长测三份计划文件，确认当前目标仍是 `half_hour/current_bar/maxHoldingBars=30`，默认 V3 暂不改。
  - 审计 `attentionCycleAnalyzer.ts` / `ranktrend.py` 的 `rawStage -> normalizeStage -> lifecycle_decision`，确认当前 B 语义只是 `stage=ignition/expansion -> allow`。
  - 审计 `execution.py`，确认 fusion 执行层已经接入 B veto，但 B 本体没有产生有效 veto。
  - 只读重放 4 月/5 月 RankTrend signals，并用 Mongo `backtest_trades` 回连 `(entrySignalSnapshotId, code)` 做入场归因。
  - 第一次尝试批量 `get_backtest_run()` 解压多个大结果超时；已改走 Mongo 归一化表 + 本地重放 signals。

Key findings:

- 4 月同代码 V3：57 个 V3 可入场信号全部为 `allow`；10 笔交易中 1 笔亏损，亏损票 `000070` 为 `A_MAIN + cooling->expansion`。
- 5 月同代码 V3：154 个 V3 可入场信号全部为 `allow`；17 笔交易中 6 笔亏损，亏损票均为 `A_MAIN/B_IGNITION + cooling->expansion/ignition`。
- 亏损单并不稳定表现为高风险，说明“只用 risk evidence 高低做 veto”不够。
- `base_not_v3` 漏选池确实包含大肉，但同池也包含大量深回撤假突破；下一步应输出 `B.discovery` 研究提示，不直接放入交易候选。

Next:

- 先写失败测试，定义 `B.veto` 与 `B.discovery` 的独立合同。
- 最小实现后只接 research-only fusion，不修改默认 V3。

Implementation update:

- 按 TDD 写入失败测试并确认 RED：
  - TS：高风险点火/扩散不能继续普通 `allow`。
  - TS：生命周期需要输出 `discovery.research_watch`，但不制造交易许可。
  - Python：同名 `lifecycle_decision` 合同测试失败。
- 最小实现：
  - `src/services/rankTrend/types.ts` 新增 `LifecycleDiscoveryAction` 和 `cycle.decision.discovery`。
  - `src/services/rankTrend/attentionCycleAnalyzer.ts` 新增高风险冲突 veto 与 discovery 诊断。
  - `src/services/RankTrendAnalyzer.ts` 改为 risk 生成后重新生成 `cycle.decision`，避免 TS live 端 action/evidence 漂移。
  - `quant-board/backend/analysis/ranktrend.py` 对齐 Python `lifecycle_decision` 合同。
  - `quant-board/tests/test_trade_simulator_round_trips.py` 补测试确认 `discovery=research_watch` 不能绕过 V3 主结构进入 fusion 买入。
- 信号层复核：
  - 4 月 V3 可入场信号 `57`，fusion 仍 `57`，高风险 veto 拦截 `0`。
  - 5 月 V3 可入场信号 `154`，fusion 仍 `154`，高风险 veto 拦截 `0`。
  - 结论：第一轮合同纠偏必要但还不足以改善交易集合；下一轮应研究突破承接质量，而不是继续提高风险阈值。
- 入场归因补充：
  - 亏损单平均 `rawChange` 明显弱于盈利单，但单点 rawChange 有大肉反例，不能变成硬门槛。
  - 亏损更像“最后一跳很强、整段承接不足”的假突破；需要 `rankPathCommitment` 这类组合语义。

Validation:

| Command | Result |
| --- | --- |
| `pnpm exec vitest run src/services/rankTrend/__tests__/attentionCycleAnalyzer.test.ts` | `7 passed` |
| `pnpm test:ranktrend` | `13 files / 136 tests passed` |
| `pytest tests/test_quant_board.py -k "lifecycle_decision_vetoes_high_risk_breakout or lifecycle_decision_outputs_discovery_diagnostic or lifecycle_decision_contract or lifecycle_decision_evidence_accepts_risk_pressure or lifecycle_entry" -q` | `5 passed` |
| `pytest tests/test_trade_simulator_round_trips.py -k "lifecycle_fusion" -q` | `3 passed` |
| `pytest tests/test_trade_simulator_round_trips.py tests/test_quant_board.py -k "lifecycle_fusion or lifecycle_decision_vetoes_high_risk_breakout or lifecycle_decision_outputs_discovery_diagnostic or lifecycle_decision_contract or lifecycle_decision_evidence_accepts_risk_pressure or lifecycle_entry or no_lifecycle_gate or context_probe or a_main_risk_filter or b_long_filter or early_big_move_v3" -q` | `21 passed` |

Files modified:

- `quant-board/docs/optimization-long-task/task_plan.md`
- `quant-board/docs/optimization-long-task/findings.md`
- `quant-board/docs/optimization-long-task/progress.md`

Implementation update 2:

- 按 TDD 先写失败测试并确认 RED：
  - TS：最后一跳很猛但整段承接不足时，生命周期 B 应输出 `rankPathCommitment` 并 veto。
  - TS：低 long 但路径连续改善时，生命周期 B 不得因为长周期弱误杀。
  - Python：`lifecycle_decision` 同步要求 `rankPathCommitment` evidence 和相同行为。
- 最小实现：
  - TS `buildAttentionTrajectoryMetrics()` 新增 `rankPathCommitment`，并写入 `cycle.decision.evidence`。
  - Python `cycle_metrics()` 新增同名字段，`lifecycle_decision()` 兼容显式传入该字段。
  - B veto 只作用于“最后一跳强 + 加速度强 + 路径承接弱 + 点火/扩散阶段”的组合，不新增固定排名过滤，也不按 low long 硬拦。
- 验证：
  - `pnpm exec vitest run src/services/rankTrend/__tests__/attentionCycleAnalyzer.test.ts`：9 passed。
  - `pytest tests/test_quant_board.py -k "ranktrend_lifecycle_decision_vetoes_last_jump_without_path_commitment or ranktrend_lifecycle_decision_preserves_low_long_big_move_when_path_commits" -q`：2 passed。
  - `pnpm test:ranktrend`：13 files / 138 tests passed。
  - `pytest tests/test_trade_simulator_round_trips.py tests/test_quant_board.py -k "lifecycle_fusion or lifecycle_decision or lifecycle_entry or early_big_move_v3" -q`：23 passed。

Next:

- 先做 4 月/5 月 V3 可入场信号层复核，统计新 B veto 是否真正命中亏损假突破，以及是否误杀 `603459` 等大肉；未验证前不跑完整策略复盘、不改默认 V3。
