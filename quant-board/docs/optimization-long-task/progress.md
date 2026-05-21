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

## Error Log

| Timestamp | Error | Attempt | Resolution |
| --- | --- | --- | --- |
| 2026-05-21 | PowerShell 输出中文乱码 | 1 | 以 runId 和数值字段为准，将关键结论写入 Markdown。 |

## 5-Question Reboot Check

| Question | Answer |
| --- | --- |
| Where am I? | Phase 7 已完成：长测方案已形成。 |
| Where am I going? | 等待用户确认是否按长测方案执行定期复跑。 |
| What's the goal? | 在 `dragonboard_live/half_hour` 上完成可追溯的 RankTrend 基线和第一轮参数优化。 |
| What have I learned? | `current_bar` 乐观、`next_bar` 保守；`755` 是多类型合计，默认 half_hour 只有 `191` 帧。 |
| What have I done? | 完成健康检查、数据集枚举、两条基线回测、计划文档落地、half_hour TPE 优化、quarter_hour grid 优化和长测方案。 |
