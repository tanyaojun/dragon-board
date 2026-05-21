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

## Money-Flow Quality Diagnostic Findings

### Half-hour 样本差异

用户确认：`half_hour` 样本比 `quarter_hour` 少的主要原因，是早期只用 IndexedDB 做测试时先启用了 `quarter_hour` 快照，`half_hour` 正式采集启用更晚。该问题不再作为代码缺陷继续追查。

### MongoDB 真实资金流字段

直接抽样 `dragonboard_live` 的 MongoDB `snapshot_stock_rows` 后确认，源数据并不是全缺资金流字段：

| Snapshot | Total rows | `official_l2` | `estimated_l1` | missing | formal coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| `half_hour` | `45081` | `4711` | `10802` | `29568` | `10.45%` |
| `quarter_hour` | `101581` | `8698` | `19770` | `73113` | `8.56%` |

示例字段包括：

- `moneyFlowSource=eastmoney`
- `moneyFlowEstimated=false`
- `capitalFlowSource=official_l2`
- `capitalFlowConfidence=medium`

### 根因

`BacktestService._prepare_frames_for_backtest` 调用质量门禁前，通过 `_stock_rows_for_quality(frames)` 构造股票行；旧实现只返回 `{"snapshotId": ...}`。因此 `evaluate_snapshot_quality` 无法看到 `capitalFlowSource`、`moneyFlowEstimated`、`moneyFlowSource` 等字段，最终把所有股票行统计为 `missing`。

这解释了为什么：

- MongoDB 行里实际有 `official_l2` 与 `estimated_l1`；
- 回测报告里却显示 `formalMoneyFlowCount=0`、`estimatedL1MoneyFlowCount=0`、`missingMoneyFlowSourceCount=45081/101581`。

### 修复

已最小修改 `quant-board/backend/services.py`：

- `_stock_rows_for_quality` 继续只承担回测质量统计输入，不改 RankTrend 分析和交易模拟。
- 新增资金流质量字段透传：`capitalFlowSource`、`capital_flow_source`、`capitalFlowConfidence`、`capital_flow_confidence`、`moneyFlowSource`、`money_flow_source`、`moneyFlowEstimated`、`money_flow_estimated`。
- 不直接透传完整股票行，避免历史 `price=0` 行把现有基线从 `warn/degraded` 改成 `fail/blocked`。完整价格质量门禁应作为后续单独议题处理。

验证回测：

- `runId`: `bt_1f012ea44bb44092`
- 口径：`dragonboard_live / half_hour / next_bar`
- `totalReturn`: `-6.37%`
- `maxDrawdown`: `-9.16%`
- `Sharpe`: `-1.3844`
- `tradeCount`: `64`
- 质量：`severity=warn`，`researchGrade=degraded`
- 资金流统计：`formalMoneyFlowCount=4711`，`estimatedL1MoneyFlowCount=10802`，`missingMoneyFlowSourceCount=29568`

结论：资金流统计已恢复为真实可解释状态，但正式资金流覆盖率仍低，仅 `10.45%` half-hour 行具备 `official_l2`。长测仍应把资金流视作质量风险，不应默认开启正式资金流策略。

## Non-Positive Price Diagnostic Findings

### 规模与分布

真实 MongoDB `snapshot_stock_rows` 中存在 `price <= 0` 行：

| Snapshot | Total rows | `price <= 0` | ratio | impacted snapshots | impacted codes |
| --- | ---: | ---: | ---: | ---: | ---: |
| `half_hour` | `45081` | `1165` | `2.58%` | `185` | `99` |
| `quarter_hour` | `101581` | `2673` | `2.63%` | `391` | `331` |

没有发现负价格；问题集中在 `price=0`，且无缺失 `price` 字段。

### 主要根因类型

1. 跨市场/非 A 股热榜条目缺行情：
   - `009992` 泡泡玛特：`half_hour 169/169`、`quarter_hour 352/352` 全为 `0`。
   - `001810` 小米集团-W：`half_hour 169/169`、`quarter_hour 349/349` 全为 `0`。
   - `009988` 阿里巴巴-W：`half_hour 168/168`、`quarter_hour 342/342` 全为 `0`。
   - `003690` 美团-W：`half_hour 54/54`、`quarter_hour 122/122` 全为 `0`。
   - `000000` 是美股/海外名称占位代码，出现特斯拉、英伟达、美光科技等名称。
2. 历史采集异常帧：
   - `quarter_hour:2026-04-03:14:15` 为 `187/187` 行价格全 `0`。
   - `quarter_hour:2026-04-01:09:45` 为 `98/185` 行价格为 `0`。
   - 这些行通常 `change/volume/turnover` 也为 `0`，盘口价为空或 `0`。
3. 少量 A 股/北交所/新股行局部报价缺失：
   - 示例：`301666` 大普微-UW 在后续部分 snapshot 中 `price=0`，但早期 `N大普微-UW` 有正常价格。
   - 示例：`600537` 亿晶光电、`002082` 万邦德有少量 `price=0` 行。

### 对当前长测基线的影响

已落库三条固定基线没有以 `price=0` 完成实际成交：

| Baseline | Run ID | zero-price events | zero-price trades | source bad refs |
| --- | --- | ---: | ---: | ---: |
| `half_hour/current_bar` | `bt_7493e60c21574bd8` | `0` | `0` | `0` |
| `half_hour/next_bar` | `bt_923ecfa4517948f4` | `0` | `0` | `0` |
| `quarter_hour/next_bar` | `bt_359953a7dba24206` | `0` | `0` | `0` |

`matchingDiagnostics.missingPriceRows` 不能直接等同于 `price=0` 成交失败；其中还包含持仓代码在当前执行帧找不到对应信号/热榜行的情况。实际成交事件和 trade 里的价格均大于 `0`。

### 信号层污染

虽然成交层没有直接污染，RankTrend 信号层仍会包含 `price=0` 行：

| Baseline | zero-price signals | A_MAIN | B_IGNITION | C_CROWDED | D_EXIT_RISK | N_NEUTRAL |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `half_hour/current_bar` / `next_bar` | `976/37618` | `0` | `7` | `11` | `478` | `480` |
| `quarter_hour/next_bar` | `2568/95585` | `1` | `29` | `46` | `1219` | `1273` |

这说明价格缺失多数落在后排、退出风险或中性层，但不能完全忽略。尤其 `quarter_hour` 早期整帧异常会制造少量 A/B 档观察信号。

### Recommendation

不要直接把完整股票行透传给当前回测质量门禁，否则历史 `price=0` 会把既有长测从 `warn/degraded` 变为 `fail/blocked`，导致无法持续比较。

更稳妥的下一步：

1. 新增独立的价格质量诊断字段，报告 `priceZeroRowCount`、`zeroPriceFrameCount`、`allZeroPriceFrameCount`、`crossMarketZeroPriceCount`。
2. 增加一个显式研究开关或过滤口径，用于剔除 `price<=0` 行后复跑三条固定基线。
3. 对 `quarter_hour` 早期全零帧做候选修复/剔除评估，但不要默认改历史数据。
4. 若后续开启正式“可成交股票池”过滤，必须用 H1/H2/Q1 固定基线对比过滤前后指标和信号分布。

## Explicit Positive-Price Filter Findings

### Implementation

已新增显式研究口径 `excludeNonPositivePriceRows`：

- API payload 字段：`excludeNonPositivePriceRows`，默认 `false`。
- CLI 参数：`run-ranktrend --exclude-non-positive-price-rows`。
- 长测 CLI 参数：`run-longtest-baselines --exclude-non-positive-price-rows`。
- 过滤发生在 RankTrend replay 前，只剔除每个 frame `stocks` 中 `price <= 0` 或无法解析为正数的行。
- 过滤统计写入 `dataQuality.runtimeFilter.priceFilter`，并进入 long-test checkpoint 摘要。

该开关不改变默认回测行为，也不修改 MongoDB 源快照事实。

### Filtered Runs

`checkpoint_2026-05-21_price_filter` 已落库：

| Baseline | Before Run | Filtered Run | dropped rows | impacted snapshots | empty snapshots |
| --- | --- | --- | ---: | ---: | ---: |
| H1 `half_hour/current_bar` | `bt_7493e60c21574bd8` | `bt_a5e56233f6fb4805` | `1165` | `185` | `0` |
| H2 `half_hour/next_bar` | `bt_923ecfa4517948f4` | `bt_801abe6f44e146df` | `1165` | `185` | `0` |
| Q1 `quarter_hour/next_bar` | `bt_359953a7dba24206` | `bt_56d52c783fd84776` | `2673` | `391` | `1` |

Q1 过滤后唯一空 frame 为 `quarter_hour:2026-04-03:14:15`，与前一阶段发现的全零价异常帧一致。

### Metric Comparison

| Baseline | totalReturn before -> after | realizedReturn before -> after | maxDrawdown before -> after | Sharpe before -> after | winRate before -> after | trades before -> after |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| H1 | `+4.49%` -> `+6.47%` | `+5.02%` -> `+6.68%` | `-2.82%` -> `-2.81%` | `-0.0003` -> `0.4117` | `37.04%` -> `40.74%` | `54` -> `54` |
| H2 | `-6.37%` -> `-2.47%` | `-2.71%` -> `+0.93%` | `-9.16%` -> `-5.52%` | `-1.3844` -> `-0.8583` | `34.38%` -> `39.06%` | `64` -> `64` |
| Q1 | `-3.27%` -> `-3.26%` | `-0.10%` -> `-0.02%` | `-11.06%` -> `-14.67%` | `-0.5817` -> `-1.5199` | `46.03%` -> `39.13%` | `126` -> `138` |

### Signal Distribution

| Baseline | signals before -> after | A_MAIN | B_IGNITION | C_CROWDED | D_EXIT_RISK | N_NEUTRAL | zero-price signals |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H1/H2 | `37618` -> `36642` | `448` -> `452` | `1283` -> `1264` | `1847` -> `1804` | `19398` -> `19044` | `14642` -> `14078` | `976` -> `0` |
| Q1 | `95585` -> `93017` | `775` -> `752` | `2776` -> `2759` | `5891` -> `5806` | `46472` -> `45466` | `39671` -> `38234` | `2568` -> `0` |

### Interpretation

- 过滤后所有零价信号清零，说明显式过滤对信号层污染有效。
- H1/H2 过滤后收益、回撤、Sharpe 均改善，尤其 H2 从 `-6.37%` 收窄到 `-2.47%`。
- Q1 过滤后总收益几乎不变，但最大回撤从 `-11.06%` 加深到 `-14.67%`，Sharpe 从 `-0.5817` 降到 `-1.5199`，交易数增加到 `138`。
- Q1 结果说明，剔除早期全零帧和跨市场零价行会改变 rank history 与后续入场路径；它不是单纯“去掉坏数据必然改善”的线性修复。

结论：`excludeNonPositivePriceRows` 应保留为显式 research option 与 report-only diagnostic。证据不足以把它升级为默认 formal quality gate；若未来要默认开启，至少需要更长 `half_hour` 样本和按“跨市场无行情 vs 全帧采集异常”拆分后的独立复核。

## Price Quality Attribution Findings

### Implementation

已新增两个显式研究口径，默认均关闭：

- `excludeCrossMarketZeroPriceRows`：只过滤零行情形态下的跨市场/非 A 股/代码失配行，统计进入 `dataQuality.runtimeFilter.crossMarketPriceFilter`。
- `excludeAllZeroPriceFrames`：只剔除整帧股票价格全为 `0` 或不可解析的异常快照，统计进入 `dataQuality.runtimeFilter.allZeroPriceFrameFilter`。

`excludeCrossMarketZeroPriceRows` 使用 MongoDB `stock_names` A 股代码表辅助判断，并跳过整帧全零异常帧，避免与全零帧口径混淆。第一版 checkpoint `checkpoint_2026-05-21_cross_market_zero_filter` 已落库但不作为正式比较口径；正式采用 v2。

### Checkpoints

| Checkpoint | Purpose | Runs |
| --- | --- | --- |
| `checkpoint_2026-05-21_cross_market_zero_filter_v2` | 只过滤跨市场/非 A 股/代码失配零行情行 | H1 `bt_57371fbc97ad4371`；H2 `bt_4fe7fd28fcce4146`；Q1 `bt_b59b804884ae465a` |
| `checkpoint_2026-05-21_all_zero_frame_filter` | 只剔除全零价格异常帧 | H1 `bt_ac33b22a9f974170`；H2 `bt_70c9e89288504b24`；Q1 `bt_751dbc4783614ace` |

### Filter Stats

| Baseline | Cross-market dropped rows | skipped all-zero frames | All-zero dropped frames | All-zero dropped rows |
| --- | ---: | ---: | ---: | ---: |
| H1 | `902` | `0` | `0` | `0` |
| H2 | `902` | `0` | `0` | `0` |
| Q1 | `1886` | `1` | `1` | `187` |

Q1 的全零帧为 `quarter_hour:2026-04-03:14:15`。跨市场过滤 v2 跳过该帧，只记录 `skippedAllZeroPriceFrames=1`。

### Metric Attribution

| Baseline | totalReturn base | cross-market | all-zero-frame | all `price<=0` |
| --- | ---: | ---: | ---: | ---: |
| H1 | `+4.49%` | `+6.47%` | `+4.49%` | `+6.47%` |
| H2 | `-6.37%` | `-1.40%` | `-6.37%` | `-2.47%` |
| Q1 | `-3.27%` | `-5.85%` | `-2.79%` | `-3.26%` |

| Baseline | maxDrawdown base | cross-market | all-zero-frame | all `price<=0` |
| --- | ---: | ---: | ---: | ---: |
| H1 | `-2.82%` | `-2.81%` | `-2.82%` | `-2.81%` |
| H2 | `-9.16%` | `-5.46%` | `-9.16%` | `-5.52%` |
| Q1 | `-11.06%` | `-14.80%` | `-9.20%` | `-14.67%` |

| Baseline | trades base | cross-market | all-zero-frame | all `price<=0` |
| --- | ---: | ---: | ---: | ---: |
| H1 | `54` | `54` | `54` | `54` |
| H2 | `64` | `64` | `64` | `64` |
| Q1 | `126` | `133` | `105` | `138` |

### Signal Attribution

| Baseline | zero-price signals base | cross-market | all-zero-frame | all `price<=0` |
| --- | ---: | ---: | ---: | ---: |
| H1/H2 | `976` | `257` | `976` | `0` |
| Q1 | `2568` | `683` | `2381` | `0` |

跨市场过滤保留的剩余零价信号主要是局部 A 股报价缺失或新股/北交所代码表缺口；全零帧过滤只解决整帧异常，不处理跨市场热榜无行情。

### Interpretation

- H1/H2 的收益和回撤改善主要来自跨市场/非 A 股/代码失配零行情过滤，而不是全零帧过滤。
- Q1 更敏感：全零帧过滤改善回撤并减少交易数；跨市场过滤会改变 rank history 和入场路径，使回撤加深。
- 全量 `excludeNonPositivePriceRows` 虽能清零 zero-price signals，但混合了多类问题，暂不适合作为默认 formal quality gate。
- 更稳妥的下一步是增加 report-only 诊断字段，拆成 `crossMarketZeroPriceRows`、`allZeroPriceFrames`、`partialAshareZeroPriceRows`，再持续观察 half_hour 后续样本。

### Review Fixes

- 显式过滤后会再次检查可用股票帧数量；如果低于质量门禁 `minSnapshotCount`，不再产出 completed/零信号报告，而是返回结构化 `qualityGate` 失败。
- 跨市场零行情判断保留原始数字代码前缀；例如港股 `00700` 不会先补零成 `000700` 再与 A 股代码表比对，避免漏判或代码混淆。

## Issues Encountered

| Issue | Resolution |
| --- | --- |
| PowerShell 控制台中部分中文输出乱码 | 数值字段和 runId 不受影响；文档中用结构化数字记录关键结论。 |
| `run-ranktrend` CLI 输出完整 JSON 过大，shell 在 120 秒超时 | run 已成功落库为 `bt_1f012ea44bb44092`；改用小脚本读取落库报告中的质量字段完成验证。 |
| 一次性读取 6 个完整 backtest result 提取信号分布超过 120 秒 | 改为给足超时时间并按 run 分批解压读取，最终得到过滤前后 tier 与 zero-price signal 分布。 |
| 第一版跨市场过滤会在全零异常帧中做行级过滤，归因不够干净 | 调整为跨市场过滤跳过全零帧并记录 `skippedAllZeroPriceFrames`，重跑 `checkpoint_2026-05-21_cross_market_zero_filter_v2`。 |

## Resources

- `quant-board/docs/README.md`
- `quant-board/docs/AI_COLLABORATION.md`
- `quant-board/docs/backtest-policy.md`
- `quant-board/docs/optimization.md`
- `quant-board/docs/api-cli.md`
- `quant-board/backend/services.py`
- `quant-board/backend/optimization/jobs.py`
