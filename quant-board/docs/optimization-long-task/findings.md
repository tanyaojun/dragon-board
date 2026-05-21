# QuantBoard 长任务优化发现记录

## Requirements

- 检查 MongoDB/后端健康。
- 列出当前数据集。
- 跑一轮 `current_bar` 基线回测。
- 补一轮 `next_bar` 保守基线。
- 用 planning-with-files 形式落地长任务优化方案。
- 开始执行第一轮长任务优化。

## Research Findings

### Health

- `GET /api/health?deep=true` 返回 `status=ok`。
- QuantBoard 版本为 `0.1.0`。
- 主存储模式为 `mongodb_primary`。
- MongoDB 主库已连接，数据库为 `dragon_board_quant`。
- 题材库已连接，来源为 MongoDB。
- 备份未配置，不阻塞本次回测和优化。

### Datasets

主数据集：

- `id`: `dragonboard_live`
- `name`: `DragonBoard Live Snapshots`
- 区间：`2026-03-27` 到 `2026-05-21`
- 快照数：`755`
- frame 数：`755`
- 股票行：`162501`
- 题材/板块行：`10376`
- snapshot types：`daily`、`half_hour`、`hourly`、`quarter_hour`

实际类型分布：

| snapshot type | count | start | end |
| --- | ---: | --- | --- |
| `daily` | `22` | `2026-04-15` | `2026-05-21` |
| `half_hour` | `191` | `2026-04-16` | `2026-05-21` |
| `hourly` | `104` | `2026-04-15` | `2026-05-21` |
| `quarter_hour` | `438` | `2026-03-27` | `2026-05-21` |

注意：`755` 是所有 snapshot type 的合计，不是 `half_hour` 样本数。第一轮 RankTrend 优化按默认 `half_hour` 口径运行，因此实际进入优化的 frame 是 `191` 个；auto split 后 train 为 `122` 个，validation 为 `69` 个。

`half_hour` 日期分布显示，`2026-05-06` 之后大多为每天 `10` 个 half-hour slots，早期若干交易日存在不完整采集。因此“等了一个月”在日历上成立，但对默认 half_hour 优化来说，有效完整半小时样本主要集中在 5 月上中旬以后。

派生数据集：

- `ds_02af973509c44bf3`：`2026-05-06` 到 `2026-05-21`，`half_hour`，质量门禁存在 `non-positive price: 666 rows`。
- `ds_7ccbd7d058e34f65`：`2026-05-06` 到 `2026-05-20`，`half_hour`，质量门禁存在 `non-positive price: 630 rows`。

结论：第一轮长任务使用 `dragonboard_live`，不使用两个质量门禁失败的短派生集。

## Baseline Runs

### `current_bar` 兼容基线

- `runId`: `bt_f11b21879f804778`
- `datasetId`: `dragonboard_live`
- `snapshotType`: `half_hour`
- `strategyName`: `rank_trend_candidate`
- `randomSeed`: `20260430`
- `configHash`: `7d29591d370088e024b1167f37773e578f8ed028b5dc6d3bc151bf555306cc9e`
- `totalReturn`: `0.0449`
- `realizedReturn`: `0.0502`
- `maxDrawdown`: `-0.0282`
- `sharpe`: `-0.0003`
- `winRate`: `0.3704`
- `tradeCount`: `54`
- `openPositions`: `5`
- 质量：`qualityGate=pass`，`researchGrade=degraded`

主要质量风险：

- 样本 OK 占比 `47.78%`。
- `degraded` 样本占比 `39.64%`。
- 样本不足信号 `4730` 条。
- 资金流来源全部缺失：`missingMoneyFlowSourceCount=45081`。

### `next_bar` 保守基线

- `runId`: `bt_d8fbef53ec434fde`
- `datasetId`: `dragonboard_live`
- `snapshotType`: `half_hour`
- `strategyName`: `rank_trend_candidate`
- `randomSeed`: `20260430`
- `configHash`: `7e9b7418637eda5679ffa6db3bcb685a18ef6a583d4008a2fa545f090f0b07f9`
- `totalReturn`: `-0.0637`
- `realizedReturn`: `-0.0271`
- `maxDrawdown`: `-0.0916`
- `sharpe`: `-1.3844`
- `winRate`: `0.3438`
- `tradeCount`: `64`
- `openPositions`: `5`
- 质量：`qualityGate=pass`，`researchGrade=degraded`

撮合诊断：

- `buyAttempts`: `60`
- `buyFilled`: `47`
- `sellAttempts`: `64`
- `sellFilled`: `64`
- `blockedByLimit`: `13`
- `nextBarEntries`: `47`
- `nextBarExits`: `64`
- `orderBookCoverage`: `1.0`

结论：`next_bar` 相比 `current_bar` 明显更保守，收益从 `+4.49%` 变为 `-6.37%`，回撤从 `-2.82%` 扩大到 `-9.16%`。后续优化必须同时参考保守基线，避免只优化 `current_bar` 的乐观偏差。

## Technical Decisions

| Decision | Rationale |
| --- | --- |
| 使用 `dragonboard_live` 作为第一轮优化数据集 | 它是当前正式 MongoDB 主数据集，覆盖完整；两个派生数据集质量门禁失败。 |
| 第一轮优化不启用题材因子执行 | 当前目标是 RankTrend 主链参数优化，题材因子默认只做解释，不绕过 RankTrend 制造买入信号。 |
| 第一轮优化选择 `tpe + stability + validation + walk-forward` | 兼顾搜索效率、样本外约束和过拟合控制。 |

## Optimization Results

### First Run

- `runId`: `opt_70e72a69c40143be`
- `status`: `completed`
- `method`: `tpe`
- `optimizer`: `optuna_tpe`
- `sampler`: `TPESampler`
- `completedTrialCount`: `36`
- `failedTrialCount`: `0`
- `configHash`: `f8030a2be94cd2c1fd061c4ed3d5f63ecf9e999fd39a12c9143487a0666c4490`

样本切分：

- train: `2026-04-16` 到 `2026-05-12`，`122` 个 half-hour snapshots。
- validation: `2026-05-13` 到 `2026-05-21`，`69` 个 half-hour snapshots。
- validation warmup signal frames: `2026-05-07` 到 `2026-05-21`，`109` 个 snapshots。
- walk-forward: enabled，`18` 个 segments。

最佳 trial：

- `trialId`: `trial_0001`
- 参数：`maxPositions=8`，`stopLoss=-0.06`，`takeProfit=0.16`
- score: `-0.056401`
- train run: `bt_02870f96bbf64d24`
- train total return: `0.0502`
- train realized return: `0.0522`
- train max drawdown: `-0.0198`
- train Sharpe: `0.8212`
- train win rate: `0.449`
- train trade count: `49`
- validation run: `bt_963b3b90162747b1`
- validation total return: `0.0042`
- validation realized return: `0.0065`
- validation max drawdown: `-0.0241`
- validation Sharpe: `-0.2893`
- validation win rate: `0.3913`
- validation trade count: `23`

Top 5 观察：

- Top 5 的 score 都是 `-0.056401`，validation 指标完全相同或近似相同。
- Top 5 都偏向 `maxPositions=8`。
- `takeProfit` 在 `0.08`、`0.12`、`0.16` 之间没有形成稳定区分。
- `stopLoss` 在 `-0.06` 和 `-0.08` 之间没有形成足够强的稳定结论。

风险判断：

- `overfitRisk.level`: `high`
- 原因：train 明显优于 validation，存在参数贴合样本内的风险。
- `returnGap`: `0.046`
- `sharpeGap`: `1.1105`
- `tradeCountGap`: `26`
- 数据质量仍是 `researchGrade=degraded`，样本 OK 占比 `47.78%`。

结论：本轮优化完成了链路验证，但不产生可直接采用的默认参数。`maxPositions=8` 是候选方向，`stopLoss` 和 `takeProfit` 需要独立复核；当前更应该补保守成交复跑和显式日期切分，而不是直接扩大搜索。

### Quarter-Hour Research Run

- `runId`: `opt_fcf1f30063514bb7`
- `status`: `completed`
- `method`: `grid`
- `optimizer`: `grid`
- `completedTrialCount`: `27`
- `failedTrialCount`: `0`
- `configHash`: `6c5fc5fbbd67009d1f2d9a5a6fbabe381d528bd8bed0bc712be368d440d2fc82`
- 口径：`quarter_hour`，`next_bar`，`maxHoldingBars=80`

样本切分：

- train: `2026-03-27` 到 `2026-05-06`，`242` 个 quarter-hour snapshots。
- validation: `2026-05-07` 到 `2026-05-21`，`196` 个 quarter-hour snapshots。
- validation warmup signal frames: `2026-04-24` 到 `2026-05-21`，`276` 个 snapshots。
- walk-forward: enabled，`13` 个 segments。

质量：

- `qualityGate=pass`
- `researchGrade=degraded`
- `sampleOkShare=51.75%`
- `sampleDegradedShare=37.18%`
- `sampleInsufficientShare=11.06%`
- `missingMoneyFlowSourceCount=101581`

最佳 trial：

- `trialId`: `trial_0007`
- 参数：`maxPositions=3`，`stopLoss=-0.04`，`takeProfit=0.16`
- score: `-0.159727`
- train run: `bt_02467a33c2fa4afb`
- train total return: `0.0199`
- train realized return: `0.0254`
- train max drawdown: `-0.0262`
- train Sharpe: `-0.3355`
- train win rate: `0.48`
- train trade count: `25`
- validation run: `bt_2db505a72d9b41f0`
- validation total return: `-0.0226`
- validation realized return: `-0.014`
- validation max drawdown: `-0.0536`
- validation Sharpe: `-1.5002`
- validation win rate: `0.3548`
- validation trade count: `31`

Top 10 观察：

- Top 3 都是 `maxPositions=3`、`takeProfit=0.16`，stopLoss 在 `-0.04/-0.06/-0.08` 之间不敏感。
- Top 10 validation 全部为负收益。
- `maxPositions=5` 的验证交易更多，但 validation 回撤和收益更差。
- 参数稳定性显示 top trials 偏向较低持仓数 `3` 和较高止盈 `0.16`，但这只是相对排序，不是可采用结论。

风险判断：

- `overfitRisk.level`: `high`
- 原因：train 明显优于 validation，存在参数贴合样本内的风险。
- `returnGap`: `0.0425`
- `sharpeGap`: `1.1647`
- validation best 为负收益，说明更细粒度样本没有改变近期验证阶段不利的事实。

结论：`quarter_hour` 有助于扩大研究视野，但当前结果不支持把任何参数写回默认值。它更像是验证了一个市场阶段信号：近期 validation 对 RankTrend 候选交易不友好，继续放大搜索容易制造样本内错觉。

## Long-Horizon Plan Findings

结合两轮优化：

- `half_hour` 默认正式口径样本较少，但 validation 仍略正，过拟合风险高。
- `quarter_hour` 研究口径样本更多，但 validation 为负，过拟合风险高。
- 两者共同说明：当前更缺的是跨市场阶段样本和稳定复核，而不是更大的参数搜索。

后续长测应固定口径，定期复跑，而不是每次换参数空间：

1. `half_hour current_bar` 保留为乐观兼容基线。
2. `half_hour next_bar` 作为正式保守验收主线。
3. `quarter_hour next_bar` 作为研究压力测试主线。
4. 每周记录三个 run 的核心指标和质量报告。
5. 只有连续多轮样本外改善，才把候选参数列入人工采用讨论。

## Long-Test Automation Findings

已新增 `run-longtest-baselines` CLI，用于固定复跑三条长测基线。它只调用现有 RankTrend 回测服务，不启动优化，不改默认参数，不写回候选参数。

默认命令：

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines --checkpoint-id checkpoint_2026-05-21_initial
```

结果追加到 `quant-board/data/reports/long_test_runs.jsonl`。该文件是本地长测运行记录，适合后续定期追加和横向比较。

首次 checkpoint：

| Baseline | Run ID | totalReturn | maxDrawdown | Sharpe | tradeCount | Quality |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `half_hour/current_bar` | `bt_7493e60c21574bd8` | `+4.49%` | `-2.82%` | `-0.0003` | `54` | `degraded` |
| `half_hour/next_bar` | `bt_923ecfa4517948f4` | `-6.37%` | `-9.16%` | `-1.3844` | `64` | `degraded` |
| `quarter_hour/next_bar` | `bt_359953a7dba24206` | `-3.27%` | `-11.06%` | `-0.5817` | `126` | `degraded` |

结论：长测自动化链路可用，但本 checkpoint 仍不支持采用或写回任何参数。下一步应优先调查 `half_hour` 样本缺口和资金流缺失，而不是扩大参数搜索。

## Issues Encountered

| Issue | Resolution |
| --- | --- |
| PowerShell 控制台中部分中文输出乱码 | 数值字段和 runId 不受影响；文档中用结构化数字记录关键结论。 |

## Resources

- `quant-board/docs/README.md`
- `quant-board/docs/AI_COLLABORATION.md`
- `quant-board/docs/backtest-policy.md`
- `quant-board/docs/optimization.md`
- `quant-board/docs/api-cli.md`
- `quant-board/backend/services.py`
- `quant-board/backend/optimization/jobs.py`
