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

## Phase 13 Report-Only Diagnostic Findings

### Planned Contract

下一阶段诊断字段只做报告观察，不参与默认过滤：

```json
{
  "dataQuality": {
    "reportOnlyDiagnostics": {
      "priceQuality": {
        "role": "report_only",
        "autoApplyDefaults": false,
        "computedBeforeResearchFilters": true,
        "crossMarketZeroPriceRows": {},
        "allZeroPriceFrames": {},
        "partialAshareZeroPriceRows": {}
      }
    }
  }
}
```

关键约束：

- 不把价格字段加回 formal `_stock_rows_for_quality()`。
- 不把诊断加入 `warnings`。
- 不改变 `severity` / `researchGrade`。
- 不自动启用 `exclude*` 过滤。

### Implementation

- `BacktestService.run_ranktrend` 在显式研究过滤前计算诊断，保证它反映过滤前源样本状态。
- `BacktestEngine._data_quality_summary` 原样透传 `reportOnlyDiagnostics`。
- `run-longtest-baselines` 摘要记录 `priceQualityDiagnostics`，用于 weekly checkpoint 横向观察。
- 当前验证通过：`14 passed`，覆盖 helper 分类、默认 report-only API 输出、显式过滤阻断和 long-test 摘要。

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

## V2 Phase A-C Implementation Review (2026-05-27)

### Scope

完成 V2 四层决策框架 Phase A-C 实现，共 12 个 tasks、6 次提交、20 项测试。

**Phase A**: TradeJournal 执行字段 (7 fields)、API request models、TypeScript types、候选池表单。
**Phase B**: `compute_signal_efficacy()` + `compute_execution_quality()` Layer 1-2 函数，接入回测管道、CLI 摘要、单元测试。
**Phase C**: `GET /api/backtests/alignment` 端点，CLI 集成，集成测试。

### Commit Log

| Commit | Scope |
| --- | --- |
| `8858b14` | docs: record weekly checkpoint 2026-05-26 |
| `3bd7a06` | docs: mark Phase 13 report-only price quality diagnostics as complete |
| `f7a4de5` | fix: persist TDX block monitor selection |
| `ab091d1` | V5 竞价弱转强落地 |
| `a416c37` | 异动精灵 事件规则逻辑文档说明 |
| `6507950` | feat: add 7 execution fields to TradeJournal model |
| `d1f6dad` | feat: extend journal API request models with execution fields |
| `eecceae` | feat: add execution record form in CandidatePoolPanel |
| `7bb4097` | feat: add Layer 1-2 computation functions |
| `853e92d` | feat: wire Layer 1-2 diagnostics into backtest pipeline |
| `6f922e8` | feat: add Layer 1-2 fields to long-test baseline summary and CLI |
| `cd96531` | test: add Layer 1-2 unit tests |
| `065a15b` | feat: add GET /api/backtests/alignment endpoint for Layer 3 |
| `573f658` | feat: integrate Layer 3 alignment into run-longtest-baselines |
| `6cb6786` | test: add Layer 1-2 and Layer 3 integration tests |
| `9eb329a` | fix: code review fixes — DRY alignment, L2 yellow status, inline import |

### Spec Compliance Review

对照 `2026-05-26-longtest-v2-design.md` 逐条检查：

| # | 层级 | 需求 | 状态 |
|---|------|------|------|
| 1 | L1 | 分层比例 (A+B)/total: 2%-15% | ✅ |
| 2 | L1 | A_MAIN 方向精度 >55% + 二项检验 p<0.10 | ✅ |
| 3 | L1 | 层级区分度 >5pp | ✅ |
| 4 | L1 | 熔断：连续 3 期方向精度不达标 → 结构性复审 | ❌ 未实现 |
| 5 | L1 | quarter_hour 对照口径 | ❌ Phase E 范围 |
| 6 | L1 | 分层异常 A+B 爆增/暴跌 → 暂停 | ❌ Phase E 范围 |
| 7 | L2 | 执行偏差 min(\|H1\|, 15pp) | ✅ |
| 8 | L2 | H1 ≥ H2 近 4 期占比 ≥75% | ✅ |
| 9 | L2 | 交易数偏差 + 回撤差异 | ✅ |
| 10 | L2 | H1>H2 偏差超门槛 → 黄灯 | ✅ 已修复 |
| 11 | L3 | 7 个执行字段 | ✅ |
| 12 | L3 | 候选池面板执行记录 | ✅ |
| 13 | L3 | 对齐报告：覆盖/重合/P&L | ✅ |
| 14 | L3 | 最小 10 笔判停 | ✅ |
| 15 | L3 | 连续 2 期 ✅ → 绿灯 | ❌ 未实现 |
| 16 | L3 | 模型失配 🚨 → 暂停优化 | ❌ 未实现 |

**符合 12/16（4 项未实现，其中 2 项属 Phase E）。**

### Code Quality Review

| # | 严重 | 问题 | 修复 |
|---|------|------|------|
| 1 | 🔴 | `.main.py` 和 `cli.py` 各 ~50 行对齐逻辑重复 | 提取为 `compute_alignment()` 共享函数 |
| 2 | 🟡 | `compute_execution_quality` 只返回 red/green，无 yellow | 增加 yellow 状态（乐观偏差） |
| 3 | 🟡 | L1 熔断未实现 | 留待下个 plan（需跨 checkpoint JSONL 状态机） |
| 4 | 🟡 | L3 跨期追踪未实现 | 留待下个 plan |
| 5 | 🟢 | `import math` 在函数体内 | 移到模块顶部 |
| 6 | 🟢 | cli.py 对齐逻辑 bare `except Exception` | 保留（对齐层非阻塞，诊断用途） |
| 7 | 🟢 | `/api/backtests/alignment` 无直接 HTTP 测试 | 留待下个 plan |

### Key Design Decisions

1. **对齐端点放 main.py**：项目没有独立 `backtest_routes.py`，所有 backtest 端点已在 main.py 中定义。
2. **CLI 对齐逻辑用共享函数**：避免 CLI 导入 FastAPI 模块。
3. **Layer 1 双重注入**：引擎 `_data_quality_summary` 从 `quality_gate` 构建 `dataQuality`；之后还需要单独注入 `result["dataQuality"]` 因为 `_summary_response` 用 result 而非 quality_gate。

### Remaining for Next Plan

- L1 熔断机制（连续 3 期方向精度不达标 → 结构性复审）
- L3 跨期状态追踪（连续 2 期 ✅ → 绿灯；🚨 → 暂停优化）
- `/api/backtests/alignment` 端点直接 HTTP 测试
- L1 quarter_hour 对照口径（Phase E）
- L1 分层异常判定（Phase E）

## Early Big Move Baseline Reset (2026-06-07)

### Decision

旧 `H1/H2/Q1` 长测基线验证的是生命周期分层买卖策略。该底层策略已经被连续 L1 红灯、新样本研究和收益表现共同证伪，因此不再继续作为默认长测主线。

旧本地长测 JSONL 记录 `quant-board/data/reports/long_test_runs.jsonl` 可以清空。文档结论保留，避免丢失审计脉络；大 JSONL 运行记录不再占用磁盘空间。

### New Baseline Set

默认 baseline set 改为：

```text
early_big_move_v1
```

| Label | Strategy | Snapshot | Execution | Purpose |
| --- | --- | --- | --- | --- |
| `E1_half_hour_signal_forward40` | `ranktrend_early_big_move` | `half_hour` | signal-only | 验证早期大肉硬候选召回 |
| `E2_half_hour_ranked_current_bar` | `ranktrend_early_big_move` | `half_hour` | `current_bar` | 验证排序后即时处理的乐观上限 |
| `E3_half_hour_ranked_strict_fill` | `ranktrend_early_big_move` | `half_hour` | `next_bar` + strict fill | 验证可执行性和成交乐观偏差 |

旧基线仍可通过显式参数复跑：

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines --baseline-set legacy_lifecycle_v1
```

但它只用于历史对照，不再作为周度默认长测。

### First Checkpoint Result

Checkpoint: `checkpoint_2026-06-07_early_big_move_v1`

| Baseline | Run ID | totalReturn | maxDrawdown | Sharpe | winRate | trades |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `E1_half_hour_signal_forward40` | `bt_359fe12a4c9c487f` | n/a | n/a | n/a | n/a | n/a |
| `E2_half_hour_ranked_current_bar` | `bt_d4732abbb1c5486e` | `-7.43%` | `-16.08%` | `-0.4157` | `48.15%` | `108` |
| `E3_half_hour_ranked_strict_fill` | `bt_2e3959f3ddb34ace` | `-5.31%` | `-15.08%` | `-0.6243` | `38.00%` | `100` |

结论：early big move 第一层信号可以进入交易模拟，但当前二级排序、卖出和风险控制仍不能直接产生正收益。下一步应优化排序/过滤，不回退到 `final=buy` 或旧生命周期分层硬买入。

## Early Big Move V1 Trade Attribution (2026-06-07)

### Method

本阶段不重跑策略，只读取已落库 run：

- E2: `bt_d4732abbb1c5486e`
- E3: `bt_2e3959f3ddb34ace`

用 `roundTripTrades.entrySignalSnapshotId + code` 回连入场时 raw replay signal，拆分 winners / losers。

字段口径修正：

- 多周期动量加速度必须取 `rankTrend.technical.momentumProfile.acceleration`。
- `rankTrend.technical.signals.acceleration.score` 是 0~1 技术信号分数，不是动量加速度本体。

### E2 Attribution

| 条件 | 交易数 | 胜率 | 平均收益 | 收益合计 |
| --- | ---: | ---: | ---: | ---: |
| 全部 E2 | 108 | 48.15% | -0.31% | -32.97% |
| 剔除 `N_NEUTRAL` | 63 | 55.56% | +0.50% | +31.24% |
| `A_MAIN/B_IGNITION` 且涨幅 `< 6%` | 43 | 62.79% | +1.20% | +51.71% |
| `A_MAIN/B_IGNITION` 且加速度 `>=20` 且涨幅 `< 6%` | 32 | 62.50% | +1.33% | +42.43% |
| `A_MAIN/B_IGNITION` 且加速度 `>=30` 且涨幅 `< 8.5%` | 33 | 63.64% | +1.14% | +37.57% |
| 仅 `N_NEUTRAL` | 45 | 37.78% | -1.43% | -64.21% |

结论：E2 的负收益不是第一层 early big move 完全失效，而是 `N_NEUTRAL` 和高涨幅追入把候选池拖坏。`A_MAIN/B_IGNITION + 涨幅不过热` 已能达到 60% 左右胜率。

### E3 Attribution

| 条件 | 交易数 | 胜率 | 平均收益 | 收益合计 |
| --- | ---: | ---: | ---: | ---: |
| 全部 E3 | 100 | 38.00% | -0.46% | -46.36% |
| 剔除 `N_NEUTRAL` | 58 | 43.10% | -0.18% | -10.41% |
| `A_MAIN/B_IGNITION` 且涨幅 `< 6%` | 43 | 48.84% | +0.75% | +32.19% |
| 仅 `A_MAIN` | 17 | 58.82% | +0.94% | +15.91% |
| 仅 `B_IGNITION` | 41 | 36.59% | -0.64% | -26.32% |
| 仅 `N_NEUTRAL` | 42 | 30.95% | -0.86% | -35.95% |
| `zeroCross=hold` | 41 | 48.78% | +1.24% | +50.91% |
| `zeroCross=buy` | 59 | 30.51% | -1.65% | -97.27% |

结论：strict fill 后，`A_MAIN` 最强，`B_IGNITION` 和 `N_NEUTRAL` 的隔 bar 成交表现弱得多。`zeroCross=buy` 在本轮不是确认优势，反而可能代表已经拥挤或被隔 bar 成交拖后。

### Exit Attribution

当前 `ranktrend_early_big_move` 仍使用默认退出逻辑，不是 early big move 专属退出。主要问题：

- `compose_decision 卖出信号` 是最大亏损集中来源，容易把早期大肉结构按旧生命周期逻辑提前打断。
- `排名跌出前50` 是死排名退出，不符合当前 RankTrend 动态结构口径。
- `D_EXIT_RISK` 并非纯坏信号，不少盈利单在这里退出；它更像风险提示或减仓提示。
- 固定止盈不适合大肉捕捉，应先不设固定 TP。

### V2 Direction

下一轮优先验证：

1. 第一层候选不再扩大。
2. 第二层交易池收窄到 `A_MAIN/B_IGNITION` 为主。
3. 当前涨幅 `< 6%` 作为优先区，`6%-8.5%` 降级观察。
4. `N_NEUTRAL` 保留在候选池解释层，但默认不进交易模拟，除非找到额外共振条件。
5. 出场改为：退出热榜连续 3 个 half_hour bar、止损 5%、`rawChange < -50 + MACD death`，不设固定止盈。

本阶段结论：策略还不能被证伪，V1 失败点更集中在二级过滤和退出规则，而不是 early big move 候选结构本身。

## Early Big Move V2 Validation (2026-06-07)

### Implementation

V2 是 V1 的独立对照分支，不覆盖 V1：

- 新策略名：`ranktrend_early_big_move_v2`
- 新 baseline set：`early_big_move_v2`
- 入场：沿用 early big move 第一层结构，第二层只交易 `A_MAIN/B_IGNITION`，当前涨幅 `< 6%`
- 不使用硬确认：`finalSignal=buy`、MACD 金叉、`zeroCross=buy` 都不作为入场门槛
- 出场：退出热榜连续 3 bars、止损 5%、`rawChange < -50 + MACD death`、40 bars 上限
- 不设固定止盈：baseline 用 `takeProfitPct=9.99` 保持大肉奔跑空间

### Checkpoint Result

Checkpoint: `checkpoint_2026-06-07_early_big_move_v2`

| Label | Run ID | totalReturn | realizedReturn | maxDrawdown | Sharpe | winRate | trades |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `V2_E1_half_hour_signal_forward40` | `bt_627db7e6c69446ca` | n/a | n/a | n/a | n/a | n/a | n/a |
| `V2_E2_half_hour_ranked_current_bar` | `bt_0d3233550bb54280` | `+5.31%` | `+5.22%` | `-6.81%` | `+1.6033` | `42.42%` | `33` |
| `V2_E3_half_hour_ranked_strict_fill` | `bt_f34a868872404e17` | `+9.72%` | `+8.99%` | `-9.00%` | `+2.3456` | `55.26%` | `38` |

### Interpretation

- V2 已经把 V1 的 strict fill 负收益扭转为接近 `10%` 的正收益：`-5.31% -> +9.72%`。
- V2 还没有达到“目的论”门槛：胜率 `55.26%`，距离 `60%` 仍差约 `4.74pp`。
- E3 strict fill 反而强于 E2 current bar，说明“严成交 + 少噪声”比即时成交更符合当前策略目标。
- 下一步不应扩大入场池；优先归因亏损单，尤其是止损单和 `B_IGNITION` 隔 bar 后兑现风险。

### Data Reading Caveat

V2 result JSON 开头包含 `controlBacktests`，其中热榜 Top10 对照组是大负收益。如果用轻量正则抓第一个 `totalReturn`，会误读成 V2 主策略亏损。后续读取 V2 指标必须取顶层主策略字段或 `tradeSimulation` 摘要，而不是 `controlBacktests`。

### Tooling Fix

第一轮 `run-longtest-baselines --baseline-set early_big_move_v2` 在三条 run 已经 completed 后超时。根因不是回测失败，而是 Layer 3 对齐在实盘 journal 为空时仍解压扫描大 backtest signals。

已修复：

- `compute_alignment()` 在 executed journal 为空时直接返回 `insufficient_data`
- 新增回归测试避免后续长测 CLI 再卡在空 journal 对齐阶段

## Early Big Move V2 Losing Trades Attribution (2026-06-07)

### Method

本阶段不改代码、不重跑策略，只读取 V2 已落库结果：

- E2 current bar：`bt_0d3233550bb54280`
- E3 strict fill：`bt_f34a868872404e17`

胜率和亏损单必须使用 `roundTripTrades` 完整交易回合口径。`backtest_trades` / `trades` 是卖出切片，E3 有 56 条切片，但只有 38 笔完整交易回合。

入场信号特征读取路径：

```text
result.roundTripTrades[*].entrySignalSnapshotId + code
  -> result.signals[*].rankTrend
  -> technical.momentumProfile / technical.signals / technical.macd / jump / risk / decision
```

MongoDB `backtest_signals` 归一化表只保留 `candidateTier/confidence/rank/reasons` 等压缩字段，不能用于完整信号画像。

### E3 Strict Fill Loss List

Run: `bt_f34a868872404e17`

| # | Code | Name | Entry signal | Return | Profit | Bars | Exit reason | Entry regime | Change | Confidence | ZeroCross | Final | Momentum short/mid/long/acc |
| ---: | --- | --- | --- | ---: | ---: | ---: | --- | --- | ---: | ---: | --- | --- | --- |
| 1 | `301217` | 铜冠铜箔 | `2026-05-12 11:00` | `-7.79%` | `-15208.17` | 26 | 止损 | weak | `2.48` | `77.67` | hold | hold | `40.27/19.44/7.52/26.18` |
| 2 | `688525` | 佰维存储 | `2026-05-18 09:30` | `-7.84%` | `-13260.73` | 9 | 止损 | weak | `0.56` | `78.83` | buy | hold | `13.89/2.66/4.24/44.60` |
| 3 | `603019` | 中科曙光 | `2026-05-13 14:30` | `-6.28%` | `-12029.47` | 11 | 止损 | normal | `2.24` | `83.29` | hold | hold | `23.50/25.44/1.66/12.54` |
| 4 | `603778` | 国晟科技 | `2026-05-26 09:30` | `-5.91%` | `-11711.33` | 12 | 止损 | retreat | `-9.07` | `88.49` | buy | hold | `43.18/17.87/22.26/67.20` |
| 5 | `002975` | 博杰股份 | `2026-05-26 09:30` | `-5.86%` | `-11634.44` | 10 | 退出热榜连续3个bar | retreat | `4.92` | `79.70` | hold | hold | `23.15/1.51/26.43/24.15` |
| 6 | `600667` | 太极实业 | `2026-05-18 09:30` | `-5.72%` | `-11381.62` | 10 | 止损 | weak | `4.53` | `82.83` | hold | hold | `24.30/26.36/4.42/25.49` |
| 7 | `000815` | 美利云 | `2026-05-13 13:30` | `-5.58%` | `-11098.81` | 18 | 止损 | normal | `3.89` | `88.81` | hold | buy | `42.46/41.04/38.07/35.00` |
| 8 | `001309` | 德明利 | `2026-05-27 09:30` | `-5.34%` | `-7129.31` | 27 | 止损 | retreat | `3.17` | `84.09` | hold | hold | `45.76/33.68/12.05/46.50` |
| 9 | `603019` | 中科曙光 | `2026-05-18 10:30` | `-3.06%` | `-6086.26` | 30 | 排名大幅下降+MACD死叉 | retreat | `5.77` | `86.77` | hold | buy | `39.80/47.24/11.89/15.33` |
| 10 | `301013` | 利和兴 | `2026-05-28 10:00` | `-2.90%` | `-5747.17` | 15 | 退出热榜连续3个bar | weak | `1.91` | `74.79` | hold | hold | `48.48/12.25/3.11/39.29` |
| 11 | `001309` | 德明利 | `2026-05-22 09:30` | `-2.17%` | `-4331.66` | 21 | 排名大幅下降+MACD死叉 | retreat | `2.27` | `91.98` | buy | buy | `38.02/31.33/9.91/38.92` |
| 12 | `601727` | 上海电气 | `2026-05-18 11:00` | `-2.12%` | `-3208.26` | 51 | 到达最大持有快照 | weak | `3.17` | `83.16` | hold | hold | `21.81/26.63/17.94/10.15` |
| 13 | `600498` | 烽火通信 | `2026-04-27 09:30` | `-0.85%` | `-1675.72` | 21 | 排名大幅下降+MACD死叉 | weak | `-2.32` | `87.98` | buy | hold | `35.34/32.63/3.93/40.56` |
| 14 | `000063` | 中兴通讯 | `2026-05-06 10:30` | `-0.44%` | `-865.02` | 12 | 排名大幅下降+MACD死叉 | normal | `5.45` | `92.38` | buy | hold | `23.58/28.45/23.79/29.02` |
| 15 | `000938` | 紫光股份 | `2026-06-03 10:30` | `-6.57%` | `-192.74` | 17 | 退出热榜连续3个bar | weak | `3.40` | `89.19` | buy | hold | `24.58/30.17/17.89/36.18` |
| 16 | `600744` | 华银电力 | `2026-06-02 13:00` | `-1.78%` | `-47.12` | 6 | 排名大幅下降+MACD死叉 | weak | `2.67` | `85.34` | hold | hold | `34.07/27.75/26.81/31.94` |
| 17 | `002185` | 华天科技 | `2026-05-18 09:30` | `-0.78%` | `-34.79` | 40 | 到达最大持有快照 | weak | `0.00` | `80.08` | hold | hold | `3.34/19.96/24.10/12.11` |

共同点：

- 17 笔亏损全部是 `B_IGNITION / ignition`，没有 `A_MAIN`。
- `止损` 是最大亏损源：7 笔合计 `-81,819.44`。
- 低质量亏损多集中在中长动量没有真正同步的 B 点火票：例如 `mid < 20` 或 `long < 10`。
- `zeroCross=hold` 在亏损中占 11/17；全体样本里 `zeroCross=buy` 胜率 `73.9%`，说明 V2 后 zeroCross 不再是 V1 strict-fill 中的负反馈。

### Winner Comparison

E3 全部 38 笔：

| Group | Trades | Win rate | Profit | Avg return |
| --- | ---: | ---: | ---: | ---: |
| All | 38 | `55.26%` | `+89,937.44` | `+2.44%` |
| `A_MAIN` | 4 | `100.00%` | `+77,468.75` | `+12.20%` |
| `B_IGNITION` | 34 | `50.00%` | `+12,468.69` | `+1.29%` |
| `zeroCross=buy` | 23 | `73.90%` | `+81,288.64` | `+3.88%` |
| `zeroCross=hold` | 15 | `26.70%` | `+8,648.80` | `+0.23%` |
| `divergence=buy` | 18 | `72.20%` | `+75,470.93` | `+3.75%` |
| `divergence=hold` | 3 | `0.00%` | `-23,467.87` | `-3.94%` |

退出原因不是简单越早越好：

| Exit reason | Trades | Win rate | Profit | Avg return |
| --- | ---: | ---: | ---: | ---: |
| 到达最大持有快照 | 12 | `83.30%` | `+110,014.74` | `+8.09%` |
| 退出热榜连续3个bar | 12 | `75.00%` | `+74,197.35` | `+3.82%` |
| 排名大幅下降+MACD死叉 | 7 | `28.60%` | `-12,455.21` | `-0.82%` |
| 止损 | 7 | `0.00%` | `-81,819.44` | `-6.35%` |

### Candidate Next Filters

这些只是下一轮验证候选，不是已采用默认规则：

| Candidate check | Kept trades | Win rate | Profit | Losing trades |
| --- | ---: | ---: | ---: | ---: |
| `mid >= 20` | 28 | `60.70%` | `+103,315.44` | 11 |
| `long >= 10` | 25 | `60.00%` | `+83,481.98` | 10 |
| `divergence != sell` | 21 | `61.90%` | `+52,003.06` | 8 |

下一轮更合理的方向不是砍 `A_MAIN`，而是把 `B_IGNITION` 从“可交易层”改成“必须二次确认的点火层”：

1. `A_MAIN` 保持优先交易。
2. `B_IGNITION` 需要补一条结构确认，例如 `mid >= 20` 或 `long >= 10`。
3. 对 `divergence=hold` 暂停交易或降级观察。
4. 不恢复固定止盈，因为大肉主要来自持有到 40 bars 或退出热榜后的利润奔跑。

### V3 Offline Rule Candidate Check

在不改代码、不重跑策略的前提下，用 V2 已成交完整回合离线枚举下一轮候选过滤。口径是：`A_MAIN` 一律保留，只调整 `B_IGNITION` 的二次确认条件。

E2 current-bar 对照 run：`bt_0d3233550bb54280`。

| Candidate | Trades | Win rate | Profit | Losses | Stop losses |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 base | 33 | `42.4%` | `+52,238.72` | 19 | 7 |
| A only | 6 | `66.7%` | `+22,885.65` | 2 | 1 |
| `B: mid>=20 and zeroCross=buy` | 18 | `61.1%` | `+80,089.44` | 7 | 3 |
| `B: mid>=20 and long>=10` | 21 | `57.1%` | `+64,672.30` | 9 | 3 |
| `B: zeroCross=buy` | 22 | `50.0%` | `+61,045.31` | 11 | 4 |
| `B: mid>=20` | 26 | `50.0%` | `+60,639.76` | 13 | 4 |

E3 strict-fill 主线 run：`bt_f34a868872404e17`。

| Candidate | Trades | Win rate | Profit | Losses | Stop losses |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 base | 38 | `55.3%` | `+89,937.44` | 17 | 7 |
| A only | 4 | `100.0%` | `+77,468.75` | 0 | 0 |
| `B: mid>=20 and zeroCross=buy` | 20 | `80.0%` | `+154,203.89` | 4 | 0 |
| `B: zeroCross=buy` | 25 | `76.0%` | `+133,834.37` | 6 | 2 |
| `B: mid>=20 and long>=10` | 23 | `69.6%` | `+156,272.23` | 7 | 2 |
| `B: mid>=20` | 29 | `62.1%` | `+142,931.53` | 11 | 4 |

阶段判断：

- `A only` 胜率最高，但交易太少，容易变成漏掉 B 点火大肉。
- `B: mid>=20 and zeroCross=buy` 是当前最平衡的 V3 候选：E2 仍超过 `60%`，E3 达到 `80%`，且 E3 止损从 7 笔降到 0 笔。
- `B: mid>=20 and long>=10` 的 E3 利润略高，但 E2 胜率未到 `60%`，不适合作为第一条 V3 主规则。
- `zeroCross=buy` 在 V2 E3 变成正反馈，但单独使用还不够；需要和中周期动量确认叠加，避免只抓到表面转正。

### V3 Real Rerun With 50 Bars

按用户要求，“大肉需要长留”，V3 baseline 使用 `maxHoldingBars=50` 复跑。

Checkpoint: `checkpoint_2026-06-07_early_big_move_v3`

| Label | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `V3_E2_half_hour_ranked_current_bar` | `bt_5681c2735de646a1` | `+12.93%` | `+10.36%` | `58.06%` | 31 | `-3.66%` |
| `V3_E3_half_hour_ranked_strict_fill` | `bt_b8061da4f92c4462` | `+9.32%` | `+8.73%` | `54.84%` | 31 | `-7.13%` |

真实复跑结论：

- V3 current-bar 收益突破 `10%`，但胜率未过 `60%`。
- V3 strict-fill 收益接近 V2 strict-fill，但没有超过 V2，也没有过 `60%` 胜率。
- 离线过滤只适合生成假设；真实策略复跑会改变成交顺序、现金占用、仓位空位、跳过成交、T+1 和退出路径。
- `50 bars` 对抓大肉是正贡献：V3 E3 中“到达最大持有快照”8 笔全胜，合计约 `+141,258.94`。
- 最大问题变成止损：V3 E3 止损 9 笔，合计约 `-95,119.38`。

V3 E3 亏损结构：

| Group | Trades | Win rate | Profit |
| --- | ---: | ---: | ---: |
| 全部 | 31 | `54.84%` | `+87,307.91` |
| `A_MAIN` | 16 | `50.00%` | `+63,282.43` |
| `B_IGNITION` | 15 | `60.00%` | `+24,025.48` |
| `zeroCross=buy` | 20 | `65.00%` | `+45,863.92` |
| `zeroCross=hold` | 11 | `36.40%` | `+41,443.99` |
| `final=hold` | 22 | `63.60%` | `+124,356.03` |
| `final=buy` | 9 | `33.30%` | `-37,048.12` |

退出原因：

| Exit reason | Trades | Win rate | Profit |
| --- | ---: | ---: | ---: |
| 到达最大持有快照 | 8 | `100.00%` | `+141,258.94` |
| 退出热榜连续3个bar | 10 | `80.00%` | `+47,103.09` |
| 排名大幅下降+MACD死叉 | 4 | `25.00%` | `-5,934.74` |
| 止损 | 9 | `0.00%` | `-95,119.38` |

下一轮判断：

1. 不应取消 `50 bars`，因为它负责放大利润。
2. 不应恢复固定止盈，因为最大盈利仍来自“持有到上限”和“退出热榜”。
3. 不应再简单强化 `mid>=20` 这类硬过滤；V3 真实复跑后 `mid>=25` 反而在已成交样本中亏损。
4. 下一步要专门拆止损单：看是否存在“弱长周期、过早 A_MAIN、final=buy/MACD 金叉后隔日兑现、个股流动性/盘口不利”等共同特征。

### Current-bar / 30 Bars Stop-loss Attribution (2026-06-07)

本轮按用户确认，把 `current-bar / 30 bars` 作为当前主线口径，先不改代码、不重跑策略，只读取已落库月度 run：

- 4 月 current-bar / 30 bars：`bt_a80a2e51db204882`
- 5 月 current-bar / 30 bars：`bt_24bce043660b48ec`

合并结果：

| Group | Trades | Win rate | Profit | Stop losses |
| --- | ---: | ---: | ---: | ---: |
| 全部 | 27 | `74.1%` | `+158,615.21` | 4 |
| `A_MAIN` | 17 | `76.5%` | `+113,687.83` | 4 |
| `B_IGNITION` | 10 | `70.0%` | `+44,927.38` | 0 |

关键判断：

- 这条主线下，止损不是来自 `B_IGNITION`，而是全部来自 `A_MAIN`。
- `B_IGNITION` 经 V3 二次确认后，在 current-bar / 30 bars 中没有止损，应保留，不应再盲目砍 B。
- `A_MAIN` 需要识别“假主升/快速衰减”：入场时看似高置信，但下一两个 bar 很快掉到 `C_CROWDED/D_EXIT_RISK/N_NEUTRAL`，或动量加速度转负。

4 笔止损单：

| Code | Name | Entry signal | Return | Profit | Bars | Entry feature | Key after-entry signal |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| `000070` | 特发信息 | `2026-04-22 10:00` | `-6.01%` | `-11,908.72` | 20 | `A_MAIN / retreat`，`long=5.62` | 下 1 bar 变 `C_CROWDED/weak` 且 `acc=-0.73` |
| `603773` | 沃格光电 | `2026-05-12 09:30` | `-25.82%` | `-10,663.86` | 48 | `A_MAIN / retreat`，`zeroCross=hold` | 5/15、5/18 连续跌停不可卖 |
| `002281` | 光迅科技 | `2026-05-25 14:30` | `-5.36%` | `-9,619.22` | 4 | `A_MAIN / weak`，`long=6.50` | 下 1 bar 变 `N_NEUTRAL/weak`，次日转 `D_EXIT_RISK/retreat` |
| `301666` | 大普微-UW | `2026-05-22 09:30` | `-7.75%` | `-6,134.56` | 24 | `A_MAIN / retreat`，入场涨幅为负，`final=buy/MACD golden` | 入场后持续 `C_CROWDED/D_EXIT_RISK`，价格快速下行 |

执行风险发现：

- `603773` 在 5/15 与 5/18 多个 half-hour bar 触发卖出，但 `skippedOrders` 显示全部为 `limit_down_unsellable`。
- Mongo 原始盘口显示该票连续跌停期间 `bid1Price=0`、`ask1Price` 堆量，卖单不可成交，因此回测最终到 5/19 才以 `-25.82%` 成交。
- 因此 `30 bars` 上限不是逻辑失效，而是“到了该卖但跌停/无买盘不能卖”。这类风险不能靠调小止损解决，只能靠入场前风险识别或 T+1 可卖后的第一时间风险标记。

候选风险检查，仅作为下一轮验证，不直接写入默认规则：

| Candidate check | Effect on current-bar / 30 observed trades |
| --- | --- |
| 剔除 `A_MAIN + weak + long < 10` | 移除 `002281`，利润从 `+158,615.21` 提升到 `+168,234.43`，止损 4 -> 3 |
| 剔除 `A_MAIN + change < 0` | 移除 `002560`、`301666`，利润小降到 `+155,698.49`，止损 4 -> 3 |
| 剔除 `A_MAIN + zeroCross=hold + change < 0` | 只移除 `301666`，利润提升到 `+164,749.77`，止损 4 -> 3 |
| 剔除 `A_MAIN + weak + long < 10` 或 `A_MAIN + change < 0` | 移除 `002560`、`002281`、`301666`，利润提升到 `+165,317.71`，胜率 `79.2%`，止损 4 -> 2 |

下一轮优先级：

1. 先验证 `A_MAIN` 假主升过滤，不动 `B_IGNITION`。
2. 增加“入场后 1-2 bar 快速衰减”的 report-only 诊断或离线枚举：例如入场后首个可观察 bar 若从 `A_MAIN` 跌到 `D_EXIT_RISK/N_NEUTRAL` 且 `acc < 0`，标记为高危。
3. 对 `603773` 这类连续跌停不可卖，应单列为执行风险：记录 `limit_down_unsellable` 次数和不可卖损失，不把它简单归因成普通止损。
4. 不恢复固定止盈，不加入固定排名门槛，不把 `final=buy/MACD golden` 当成硬确认；`301666` 已证明这类信号也可能是陷阱。

### A_MAIN False-strength Filter Validation (2026-06-07)

本轮只验证 A_MAIN 假主升过滤，不改变 B_IGNITION，不引入固定排名门槛。

新增研究策略：

```text
ranktrend_early_big_move_v3_a_main_risk_filter
```

规则口径：

- 先完全满足 V3 入场。
- `B_IGNITION` 完全沿用 V3：`momentumProfile.mid >= 20` 且 `zeroCross=buy`。
- `A_MAIN` 额外过滤两类已归因风险：
  - `regime=weak` 且 `momentumProfile.long < 10`
  - `change < 0`
- 出场必须沿用 V2/V3 early big move 专属规则：退出热榜连续 3 bars、止损 5%、`rawChange < -50 + MACD death`、`30 bars` 上限，不恢复旧 `finalSignal/D_EXIT_RISK/rank>50/止盈` 出场。

有效复跑结果：

| Window | Strategy | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown | stops |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4月 | V3 原始 | `bt_a80a2e51db204882` | `+6.76%` | `+3.12%` | `90.00%` | 10 | `-2.67%` | 1 |
| 4月 | A_MAIN 风险过滤 | `bt_ef248f9bbe884b63` | `+4.05%` | `+1.49%` | `80.00%` | 10 | `-4.29%` | 1 |
| 5月 | V3 原始 | `bt_24bce043660b48ec` | `+14.81%` | `+12.74%` | `64.71%` | 17 | `-4.06%` | 3 |
| 5月 | A_MAIN 风险过滤 | `bt_6880bb325d604045` | `+15.27%` | `+12.03%` | `64.71%` | 17 | `-4.06%` | 2 |

交易路径差异：

| Window | Removed by filter | Added after ranking/cash-path changed |
| --- | --- | --- |
| 4月 | `002560` | `000988` |
| 5月 | `002281`、`301217`、`301666` | `002600`、`601138`、`603738` |

入场分层归因（按 `entrySignalSnapshotId + code` 回连完整 signal）：

| Window | Strategy | A_MAIN trades | A_MAIN win/profit/stops | B_IGNITION trades | B win/profit/stops |
| --- | --- | ---: | --- | ---: | --- |
| 4月 | V3 原始 | 7 | `85.7% / +19,595.36 / 1` | 3 | `100.0% / +11,650.04 / 0` |
| 4月 | A_MAIN 风险过滤 | 7 | `71.4% / +3,231.29 / 1` | 3 | `100.0% / +11,650.04 / 0` |
| 5月 | V3 原始 | 10 | `70.0% / +94,092.47 / 3` | 7 | `57.1% / +33,277.34 / 0` |
| 5月 | A_MAIN 风险过滤 | 9 | `88.9% / +124,079.48 / 1` | 8 | `37.5% / -3,782.36 / 1` |

结论：

- 简单 A_MAIN 硬过滤真实复跑 **不通过**，不能写入 V3 默认。
- 它确实移除了 `002281`、`301666` 这类假主升止损，但也改变了排序、现金占用和仓位空位，导致新增 `002600/603738` 等 B 侧亏损，4 月还误伤收益路径。
- 5 月 totalReturn 略升 `+0.46pp`，但 realizedReturn 略降，且 B_IGNITION 从正贡献变为负贡献；这不是稳定改善。
- 4 月 totalReturn 从 `+6.76%` 降到 `+4.05%`，胜率从 `90.00%` 降到 `80.00%`，最大回撤恶化到 `-4.29%`。
- 因此下一步不应继续叠加静态 A_MAIN 硬门槛，而应做“路径感知”的排序/风险标记：例如入场后首个可观察 bar 的快速掉档、不可卖风险、以及同一 bar 中 A/B 候选的优先级竞争。

A_MAIN 进入机制源码链路：

```text
compose_strategy(...)
  stage == "expansion"
  momentum.mid >= tierAMainMidMomentumMin
  momentum.short >= tierAMainShortMomentumMin
  trend_buy = direction buy OR acceleration buy OR MACD golden
  hotlist stage in 高潮/发酵 且 riskLevel != 高
  divergence severity < tierAMainDivergenceSeverityMax
```

这解释了假主升为何能进入 A_MAIN：

- `long` 长周期动量不是 A_MAIN 的硬条件。
- `regime=weak/retreat` 不是 A_MAIN 分层自身的拦截条件。
- `trend_buy` 是三选一，只要方向、加速度或 MACD 任一偏多即可。
- 所以 `000070` 的 `long=5.62`、`002281` 的 `weak + long=6.50`、`301666` 的 `change<0` 都可能先被打成 A_MAIN，再在交易路径里失败。

无效中间 run：

- `bt_ca768d6481a44cdb`
- `bt_418bbe7c4ae94bed`

这两个 run 生成于研究策略尚未加入 early big move 专属出场族之前，实际混用了旧 `compose_decision/D_EXIT_RISK/rank>50/止盈` 出场，交易数异常放大，不能作为策略结论。

### Lifecycle Path Attribution For RankTrend V3 (2026-06-07)

本轮只做离线路径归因，不改代码、不新增默认策略、不复活旧生命周期分层买卖逻辑。

读取 run：

| Window | Strategy | Run ID | totalReturn | winRate | trades |
| --- | --- | --- | ---: | ---: | ---: |
| 4月 | V3 原始 | `bt_a80a2e51db204882` | `+6.76%` | `90.00%` | 10 |
| 5月 | V3 原始 | `bt_24bce043660b48ec` | `+14.81%` | `64.71%` | 17 |
| 4月 | A_MAIN 风险过滤 | `bt_ef248f9bbe884b63` | `+4.05%` | `80.00%` | 10 |
| 5月 | A_MAIN 风险过滤 | `bt_6880bb325d604045` | `+15.27%` | `64.71%` | 17 |

读取口径：

- 胜率使用 `roundTripTrades`，不使用卖出切片。
- 入场信号按 `(entrySignalSnapshotId, code)` 回连 `result.signals`。
- 生命周期路径取 `rankTrend.cycle.transition`、`rankTrend.cycle.stage` 和顶层 `stage`。
- 每笔交易提取入场前 3 bars、入场 bar、入场后 2 bars 的路径。

#### V3 原始 4月+5月合并

| Group | Trades | Win rate | Profit | Avg return |
| --- | ---: | ---: | ---: | ---: |
| 全部 | 27 | `74.1%` | `+158,615.21` | `+3.33%` |
| `A_MAIN` | 17 | `76.5%` | `+113,687.83` | `+3.83%` |
| `B_IGNITION` | 10 | `70.0%` | `+44,927.38` | `+2.50%` |
| `long >= 10` | 20 | `90.0%` | `+136,626.74` | `+4.03%` |
| `long < 10` | 7 | `28.6%` | `+21,988.47` | `+1.34%` |
| `final != buy` | 22 | `77.3%` | `+158,012.92` | `+4.38%` |
| `final = buy` | 5 | `60.0%` | `+602.29` | `-1.26%` |

关键发现：

- 单点 `stage` 或 `cycle.transition` 不能直接当买卖规则。`cooling->expansion` 13 笔胜率 `69.2%`，利润 `+59,783.69`，里面既有大肉也有止损。
- 旧生命周期分层不能恢复为主策略；但“路径”有价值，尤其是入场前是否经历异常抖动、入场后是否快速掉档。
- `long >= 10` 是本轮最强的单因子稳定性特征：20 笔胜率 `90.0%`。
- `long < 10` 胜率只有 `28.6%`，但不能简单全删，因为 `603459 红板科技` 是 `long=4.59` 却贡献 `+49,390.17` 的大肉。
- `final=buy` 仍不是好确认：5 笔利润几乎归零，均值为负；不能把最终信号或 MACD 金叉恢复为硬入场条件。

#### `long < 10` 明细

| Code | Name | Tier | Return | Profit | Reason | Path issue |
| --- | --- | --- | ---: | ---: | --- | --- |
| `000070` | 特发信息 | A_MAIN | `-6.01%` | `-11,908.72` | 止损 | `ignition>cooling>cooling>expansion`，长周期未接上 |
| `002281` | 光迅科技 | A_MAIN | `-5.36%` | `-9,619.22` | 止损 | `expansion>reversal>cooling>expansion`，反转后再扩散 |
| `002181` | 粤 传 媒 | B_IGNITION | `-1.48%` | `-2,942.52` | 排名大幅下降+MACD死叉 | 入场后 `ignition>cooling>cooling` |
| `001309` | 德明利 | B_IGNITION | `-3.12%` | `-2,094.64` | 排名大幅下降+MACD死叉 | `final=buy` 但长周期弱 |
| `301526` | 国际复材 | B_IGNITION | `-0.68%` | `-1,349.87` | 到达最大持有快照 | 早期点火但后续走弱 |
| `600498` | 烽火通信 | B_IGNITION | `+1.11%` | `+513.27` | 排名大幅下降+MACD死叉 | 小赢，非主要贡献 |
| `603459` | 红板科技 | A_MAIN | `+24.91%` | `+49,390.17` | 到达最大持有快照 | 特例大肉，`mid=39.91`、`acc=34.13` 极强 |

#### 候选检查，仅供下一轮复跑

这些是离线归因，不是已通过的真实复跑规则：

| Candidate check on V3 original trades | Kept trades | Win rate | Profit | Avg return |
| --- | ---: | ---: | ---: | ---: |
| 保留全部 | 27 | `74.1%` | `+158,615.21` | `+3.33%` |
| 只保留 `long >= 10` | 20 | `90.0%` | `+136,626.74` | `+4.03%` |
| 剔除 `B_IGNITION + long < 10` | 23 | `82.6%` | `+164,488.97` | `+4.10%` |
| 剔除 `final=buy` | 22 | `77.3%` | `+158,012.92` | `+4.38%` |
| 剔除 `A_MAIN` 中 `ignition>cooling>cooling>expansion` 或 `cooling>ignition>cooling>expansion` | 24 | `79.2%` | `+172,077.38` | `+4.89%` |

阶段结论：

1. 生命周期分层可以重新审视，但必须改成“RankTrend 路径上下文”，不能恢复旧的生命周期独立买卖策略。
2. 下一轮更有希望的方向是路径排序/降权，而不是硬过滤：
   - `A_MAIN` 若入场前路径出现 `ignition/reversal -> cooling -> expansion` 的抖动，降权；
   - `B_IGNITION + long < 10` 可以作为第一条真实复跑候选，因为它在离线样本中同时提高胜率和利润；
   - `final=buy` 仍应视为滞后/兑现风险提示，不做入场确认。
3. 不建议一刀切 `long < 10`，否则会漏掉 `603459` 这种中周期和加速度极强的低长周期早期大肉。

### B_IGNITION Long-Momentum Filter Rerun (2026-06-07)

本轮把 Phase 29 的离线候选变成真实研究策略复跑：

```text
ranktrend_early_big_move_v3_b_long_filter
```

规则口径：

- 先完全满足 V3 入场。
- `A_MAIN` 完全沿用 V3，不增加任何 A_MAIN 硬过滤。
- `B_IGNITION` 在 V3 的 `mid >= 20 + zeroCross=buy` 基础上，额外要求 `momentumProfile.long >= 10`。
- 出场仍为 early big move 专属规则：退出热榜连续 3 bars、止损 5%、`rawChange < -50 + MACD death`、`30 bars` 上限；不恢复固定止盈、旧生命周期退出或最终信号退出。

真实复跑结果：

| Window | Strategy | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown | stops |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4月 | V3 原始 | `bt_a80a2e51db204882` | `+6.76%` | `+3.12%` | `90.00%` | 10 | `-2.67%` | 1 |
| 4月 | B_LONG 过滤 | `bt_3a6339356fe44ef2` | `+3.64%` | `+3.07%` | `80.00%` | 10 | `-2.86%` | 2 |
| 5月 | V3 原始 | `bt_24bce043660b48ec` | `+14.81%` | `+12.74%` | `64.71%` | 17 | `-4.06%` | 3 |
| 5月 | B_LONG 过滤 | `bt_1d12cc19e20d492e` | `+5.33%` | `+3.08%` | `56.25%` | 16 | `-4.99%` | 5 |

分层归因：

| Window | Strategy | A_MAIN trades | A_MAIN win/profit/stops | B_IGNITION trades | B win/profit/stops |
| --- | --- | ---: | --- | ---: | --- |
| 4月 | V3 原始 | 7 | `85.7% / +19,595.36 / 1` | 3 | `100.0% / +11,650.04 / 0` |
| 4月 | B_LONG 过滤 | 8 | `75.0% / +19,540.47 / 2` | 2 | `100.0% / +11,136.77 / 0` |
| 5月 | V3 原始 | 10 | `70.0% / +94,092.47 / 3` | 7 | `57.1% / +33,277.34 / 0` |
| 5月 | B_LONG 过滤 | 10 | `60.0% / +50,785.20 / 3` | 6 | `50.0% / -20,026.69 / 2` |

交易路径差异：

| Window | Removed by B_LONG filter | Added after ranking/cash-path changed |
| --- | --- | --- |
| 4月 | `600498` 小赢 `+513.27` | `600208` 小止损 `-54.89` |
| 5月 | `002181`、`301526`、`001309` 三笔弱 B 小亏；同时路径丢失 `603459` 大肉 `+49,390.17`、`600667` `+9,110.41`、`600900` `+2,855.25` | 新增 `603993` `-25,496.02`、`000657` `-30,992.56`、`600379` `-1,395.54` 等强 long 假突破亏损 |

关键结论：

- B_LONG 硬过滤真实复跑不通过，不能写入 V3 默认。
- 离线剔除 `B_IGNITION + long < 10` 看起来有效，是因为它只在既有成交集合上做删减；真实复跑会改变排序、现金占用、仓位空位和后续可买票。
- `long >= 10` 不是假突破解药。5 月新增的 `603993`、`000657` 都是 `B_IGNITION + long >= 10`，但分别出现 `-12.79%`、`-15.85%` 的止损。
- 更严重的是，它间接漏掉 `603459 红板科技` 这笔 `A_MAIN + long=4.59` 的 `+24.91%` 大肉。虽然规则没有直接过滤 A_MAIN，但交易路径改变后资金和仓位没有等到它。
- 下一步不应继续做静态硬过滤，而应研究“排序/降权”：
  - 对 `B_IGNITION` 的强 long 假突破，检查是否有入场前急拉后兑现、入场后首个可观察 bar 掉档、或同 bar A_MAIN 竞争失败特征；
  - 对低 long 但中周期/加速度极强的 A_MAIN，不应被间接挤出；
  - 优先做候选排序和仓位优先级，而不是继续砍信号池。

## Phase A-C Closeout (2026-05-27)

### Implementation

补齐 L1 熔断和 L3 跨期追踪，修复 code review 发现的所有问题。

新增函数 (`services.py`):
- `read_checkpoint_history(jsonl_path, limit)` — 读 JSONL 历史记录
- `check_layer1_meltdown(history, label_filter)` — 连续 3 期 red → 熔断
- `check_layer3_trend(history)` — 连续 2 期 sufficient → 绿灯

CLI 集成 (`cli.py`):
- `cmd_run_longtest_baselines` 在 Layer 3 对齐后调用跨期检查
- 结果写入 `result["crossPeriod"]` 字段

### Test Results

| 类型 | 数量 | 状态 |
|---|---|---|
| 新增单元测试（边界条件） | 5 | ✅ |
| 新增集成测试（熔断/追踪） | 4 | ✅ |
| 回归测试 | 43 | ✅ |

### Spec Compliance Final

| # | 需求 | 状态 |
|---|------|------|
| L1 熔断：连续3期方向精度不达标 | ✅ 已实现 |
| L2 黄灯：乐观偏差 | ✅ 已实现 |
| L3 跨期追踪：连续2期 ✅ | ✅ 已实现 |
| L3 模型失配 🚨 | ❌ 待 trade journal 数据积累 |
| L1 quarter_hour 对照 | ❌ Phase E |
| L1 分层异常判定 | ❌ Phase E |

### Commit

`c3174e9` — 5 files, +475/-1 lines

## Bar Repair & Interpolation Findings (2026-05-29)

### Problem

half_hour 缺失 42 个 bar（14/29 日期不完整），quarter_hour 缺失 213 个 bar（25/42 日期不完整）。早期日期（如 4/16、4/20）缺失集中在上午盘前时段，反映采集启用时间晚于交易开盘。

### v1: 单向复制（已弃用）

从同日期最近 bar 直接深拷贝 frame + rows。引入偏差：合成 bar 和源 bar 热榜数据完全相同，导致回测中产生重复信号。

### v2: 线性插值

取缺失 bar 的前一个和后一个 bar，对每只股票分别线性插值：

```
price_target = price_prev + (price_next - price_prev) × (T_target - T_prev) / (T_next - T_prev)
volume_target = volume_prev + (volume_next - volume_prev) × ratio
turnover_target = 同上
```

板块数据不插值，复制最近邻。所有合成 bar 标记 `captureMode: "synthesized"`。

### Data Cleanup

第一轮复制的数据与真实数据混合，通过"价格指纹"匹配识别：在同一日期的 bar 中，若两个 bar 的前 5 只股票的 `(code, price)` 完全相同，则判定为复制品。共识别并删除 228 条旧复制数据。

### Impact on Backtest

| 基线 | 原始 (248 HH) | 补齐后 (290 HH) | 差异 |
|---|---|---|---|
| H1 totalReturn | +2.15% | +5.45% | +3.30pp |
| H1 Sharpe | -0.34 | +0.60 | +0.94 |
| H2 totalReturn | -6.11% | -1.06% | +5.05pp |
| Q1 totalReturn | -3.26% | -1.94% | +1.32pp |

补齐后所有基线改善，H1/H2/Q1 Sharpe 均首次转正（或大幅收窄）。主要原因是早期缺失 bar 集中在 4 月下旬的下跌区间，补齐后回测路径更平滑。

### Caveats

1. 合成数据本质是估算值，不反映真实市场价格
2. L1 方向精度 39.81%（补齐前后均低于 50%）—— 信号方向预测能力不足是真实问题，不是数据缺口导致的
3. 合成 bar 已标记 `captureMode: "synthesized"`，未来回测可选择性排除

## 5/29 Checkpoint Cross-Period Analysis

## Frontend 代码调查：前后端实现 vs 文档覆盖 (2026-05-29)

### 方法

逐项对比 `quant-board/docs/frontend.md` 与当前代码实现（`quant-board/frontend/src/App.vue`、`src/components/panels/CandidatePoolPanel.vue`、`quant-board/backend/services.py`、`quant-board/backend/cli.py`）。

### 结果

**代码已实现 + 文档已覆盖 (13 项)：**
回测表单基础字段、图表、交易列表、Golden 差异、报告诊断基础、错误码、视觉原则、联调约定、验收清单

**代码已实现 + 文档缺失 (11 项)：**
| 功能 | 代码位置 | 缺失的文档 |
|---|---|---|
| 多动量周期参数 | `App.vue:220` `backtestForm.momentumPeriods` | 回测表单未列出 |
| 多动量周期优化搜索 | `App.vue:244-248` `parameterGrid.momentumPeriods` | 优化页未列出 |
| MACD 三参数 | `App.vue:221-223` | 表单有但未在默认值外列出 |
| 候选池执行记录 7 字段 | `CandidatePoolPanel.vue:341-373` | 整个执行记录区域未提及 |
| 执行模式 `executionMode` | 后端 `services.py:888` | 表单未列出 |
| 撮合参数（6 项） | `App.vue:210-219` | 表单未列出 |
| 费率（3 项） | `App.vue` + 后端 | 表单未列出 |
| Walk-forward 配置 | `App.vue:236-241` | 优化页未细化 |
| 价格过滤三开关 | `App.vue` + 后端 | 表单未列出 |
| 止损机制（A/B 双触发） | V2 设计 | 优化页未提及 |
| 两阶段参数设计 | V2 设计 | 优化页未提及 |

**后端已产出数据 + 前端无展示 (7 项)：**
- Layer 1 信号诊断（`layer1SignalEfficacy`）
- Layer 2 执行质量（`layer2ExecutionQuality`）
- Layer 3 对齐报告（`/api/backtests/alignment`）
- 跨期状态（`crossPeriod.meltdown` / `crossPeriod.trend`）
- 价格质量诊断（`reportOnlyDiagnostics.priceQuality`）
- 合成 bar 标记（`captureMode: "synthesized"`）
- 长测 checkpoint 趋势比较

### 结论

`frontend.md` 停留在 Phase 9 时期，缺少 Phase 10-17 的全部新增能力文档。多动量周期前后端均已实现但文档完全未提——用户观察正确。文档现已更新补全。

### Checkpoints in JSONL History

| checkpoint_id | H1 ret | H1 L1 | H2 ret | Q1 ret |
|---|---|---|---|---|
| `checkpoint_2026-05-26_weekly` | +3.98% | red (bug: all "?") | -4.04% | -2.10% |
| `checkpoint_2026-05-29_weekly` | +2.15% | red (41.73%) | -6.11% | -3.26% |
| `checkpoint_2026-05-29_repaired` | +5.91% | red (37.64%) | -2.29% | -4.03% |
| `checkpoint_2026-05-29_interpolated` | +5.45% | red (39.81%) | -1.06% | -1.94% |
| `checkpoint_2026-06-05_weekly` | +3.78% | red (39.44%) | -3.94% | -9.25% |

### Cross-Period State

- L1 meltdown H1: **4 期连续 red**（unknown→unknown→red→red→red→red）—— **熔断已触发**
  - 根因：A_MAIN 信号方向精度持续低于 50% 随机基准（39.44%），不是数据质量问题
  - 568 个 A_MAIN 样本中仅 39.44% 在下一 bar 价格上涨，比随机掷硬币还差
  - 建议：排查当前策略参数 MACD(21,34,13)+动量(3,5,8,13,21) 在 A_MAIN 层信号中的方向预测逻辑
- L3 trend: insufficient_data（无 trade_journal 执行记录）
- 趋势逆转：H2 保守成交从 5/29 的 -1.06% 恶化至 -3.94%，回撤 -11.82%；H1 乐观收益从 +5.45% 下降至 +3.78%；Q1 崩盘 -9.25%（-7.31pp）
- 6/05 是 V2 四层框架实施后最差的一次 checkpoint，三条基线全面恶化
- 本周新增 44 个 half_hour 帧（5 个交易日）对策略极不友好，可能与市场风格切换相关

## Lifecycle Implementation Audit (2026-06-07)

审计文档：

- `quant-board/docs/optimization-long-task/2026-06-07-lifecycle-implementation-audit.md`

审计范围：

- TS：`src/services/rankTrend/attentionCycleAnalyzer.ts`
- TS：`src/services/rankTrend/candidateTierComposer.ts`
- Python：`quant-board/backend/analysis/ranktrend.py`
- 回测执行：`quant-board/backend/core/backtest/execution.py`
- 策略注册/说明：`quant-board/backend/core/backtest/strategy.py`

核心实现发现：

1. 生命周期阶段不是纯 RanTrend 动量加速度模型，内部仍混合固定分位、近期最好名次、热区连续次数和回撤判断。
2. `normalize_stage` / `normalizeAttentionStage` 有状态惯性，能减少抖动，也可能把假主升继续平滑成 `expansion`。
3. Python 回测主链和 TS golden 在候选分层输入上已有合同漂移：TS `composeCandidateTier` 使用 `market_regime`，Python `compose_strategy` 主要使用 `hotlistSentiment` 控制 A/B 放行。
4. V3 交易层通过 `candidateTier in A_MAIN/B_IGNITION` 消费生命周期分层，生命周期不是纯展示字段，而是实质参与入场候选生成。
5. 当前测试不足以证明生命周期在真实路径上可靠：缺少大肉、假主升、强 long 假突破、低 long 大肉四类 TS/Python 对齐样本。

只读回测证据：

| Group | Trades | Win rate | Profit | Avg return |
| --- | ---: | ---: | ---: | ---: |
| V3 原始 4月+5月 | 27 | `74.1%` | `+158,615.21` | `+3.33%` |
| `stage=expansion` | 17 | `76.5%` | `+113,687.83` | `+3.83%` |
| `stage=ignition` | 10 | `70.0%` | `+44,927.38` | `+2.50%` |
| `entryAdvice=preferred` | 12 | `75.0%` | `+66,799.92` | `+3.10%` |
| `entryAdvice=watch` | 15 | `73.3%` | `+91,815.29` | `+3.50%` |
| `long >= 10` | 20 | `90.0%` | `+136,626.74` | `+4.03%` |
| `long < 10` | 7 | `28.6%` | `+21,988.47` | `+1.34%` |
| `final=buy` | 5 | `60.0%` | `+602.29` | `-1.26%` |
| `final!=buy` | 22 | `77.3%` | `+158,012.92` | `+4.38%` |

审计结论：

- 生命周期阶段不是完全无效；V3 主线收益确实来自 `expansion/ignition`。
- 但 `stage`、`transition`、`entryAdvice` 都不能单独当作可靠买点。
- `entryAdvice=preferred` 并不强于 `watch`，说明生命周期建议语义偏强。
- `final=buy` / MACD golden 继续偏弱，不能恢复成硬入场确认。
- 静态硬过滤已经被 A_MAIN 风险过滤和 B_LONG 过滤复跑证明不稳，下一步应转向“生命周期 report-only / 排序降权”的研究对照。

下一步建议：

1. 做一个 research-only 对照策略：不把 `candidateTier=A_MAIN/B_IGNITION` 当硬门槛，入场主轴回到 `jump 高置信 + 多周期动量同步 + 加速度抬升 + 可成交性`。
2. 生命周期只参与排序降权和报告解释，不制造买点、不硬过滤。
3. 补 TS/Python 生命周期路径对齐样本，至少覆盖真实大肉、假主升、强 long 假突破、低 long 大肉。

## Phase 32: No-Lifecycle-Gate / Context-Probe Contrast Reruns (2026-06-07)

### 第一轮：`ranktrend_early_big_move_v3_no_lifecycle_gate`

真实复跑结果：

| Window | Strategy | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 4月 | no_lifecycle_gate | `bt_efe08f9fb3954988` | `-4.44%` | `-6.15%` | `15.38%` | `13` | `-8.14%` |
| 5月 | no_lifecycle_gate | `bt_9c00f69c9b09426c` | `-0.24%` | `-0.18%` | `29.63%` | `27` | `-11.70%` |

结论先行：

- 直接移除 `candidateTier=A_MAIN/B_IGNITION` 硬门槛后，策略不是“更早抓大肉”，而是明显跑崩。
- 这条路离用户目标更远：胜率远低于 `60%`，收益率也没有向 `20%` 靠近。

根因不是“早期结构方向错了”，而是交易路径被大量非主线候选污染：

| Window | 主要拖累 | 证据 |
| --- | --- | --- |
| 4月 | `N_NEUTRAL` | 8 笔，胜率 `25.0%`，利润 `-22,732.25` |
| 5月 | `N_NEUTRAL` | 11 笔，胜率 `9.1%`，利润 `-54,884.12` |

进一步拆解显示：

- 新进入的大量失败票并不是 `A_MAIN/B_IGNITION` 主线候选，而是 `N_NEUTRAL + entryAdvice=watch/avoid`。
- 很多失败票同时具备 `jump=95`、`zeroCross=buy`、中长周期动量不差，但生命周期上下文明确不是优选路径。
- 典型失败样本：
  - `001330 博纳影业`：`N_NEUTRAL + cooling->expansion + watch`，`-6.66%`
  - `300303 聚飞光电`：`N_NEUTRAL + cooling->ignition + preferred`，`-8.31%`
  - `603538 美诺华`：`N_NEUTRAL + ignition->expansion + preferred`，`-5.52%`

结论：

- “生命周期不能硬拦 buy”成立。
- 但“完全去掉生命周期路径约束”同样不成立。
- 下一步不能继续放开非 A/B 候选池。

### 第二轮：`ranktrend_early_big_move_v3_context_probe`

设计目标：

- 保留 V3 现有 `A_MAIN/B_IGNITION` 主干。
- 只额外探测极少数 `entryAdvice=preferred` 的非 A/B 早期结构候选。

真实复跑结果：

| Window | Strategy | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 4月 | context_probe | `bt_69232223f3024f02` | `+6.76%` | `+3.12%` | `90.00%` | `10` | `-2.67%` |
| 5月 | context_probe | `bt_a23990ecc8084021` | `+9.52%` | `+11.26%` | `50.00%` | `18` | `-6.32%` |

对比现有 V3 主线 5 月 run `bt_24bce043660b48ec`：

| Strategy | totalReturn | realizedReturn | winRate | trades | maxDrawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| V3 原始 | `+14.81%` | `+12.74%` | `64.71%` | `17` | `-4.06%` |
| context_probe | `+9.52%` | `+11.26%` | `50.00%` | `18` | `-6.32%` |

失败原因：

- 即使只额外放行少量 `preferred` 非 A/B 候选，真实复跑仍会改变排序、现金和仓位路径。
- 5 月新增的探针票里，关键负贡献包括：
  - `603399 永杉锂业`：`N_NEUTRAL + cooling->ignition + preferred`，`-11.61%`
  - `600118 中国卫星`：`N_NEUTRAL + cooling->ignition + preferred`，`-6.06%`
  - `000981 山子高科`：`N_NEUTRAL + cooling->ignition + preferred`，`-5.93%`
- 虽然也新增了 `688981 中芯国际` 这类正贡献样本，但整体仍把 5 月主线拉弱。

阶段结论：

1. `no_lifecycle_gate` 已被真实复跑证伪，不能继续推进。
2. `context_probe` 也未把结果推向 `60%+` 胜率和 `20%+` 收益目标。
3. 下一步不应再沿“开放非 A/B 候选池”继续试错。
4. 更合理的主线应回到现有 V3 有效口径，研究：
   - 同 bar 候选竞争与仓位优先级
   - 生命周期 report-only 诊断降权
   - A_MAIN 假主升与 B 侧强结构假突破的路径级排序，而不是直接加新入场池

## Phase 33: 生命周期 A+B 融合设计审计 (2026-06-07)

### 用户决策更新

本阶段修正 Phase 31/32 的后续方向：生命周期不再定义为松散的 report-only 降权标签，而是定义为 RankTrend 之后的辅助决策系统 B。

新的合同不是恢复旧生命周期买卖策略。旧策略已经被多轮长测证伪。新的合同是：

```text
A = RankTrend 主策略：识别早期大肉结构
B = 生命周期辅助决策系统：判断 A 的结构是否处在可交易路径
最终候选 = A 通过 AND B 未否决
```

B 有一票否决权。只要 B 明确反对，即使 A 侧出现强 jump、强多周期动量、强加速度、MACD/零线配合，也不能进入买入候选池。

### 当前字段如何生成

生命周期字段当前在 TS 与 Python 中语义基本一致，但没有显式 B 决策层。

| 字段 | TS 生成 | Python 生成 | 当前语义问题 |
| --- | --- | --- | --- |
| `rawStage` | `determineRawAttentionStage()` | `raw_stage()` | 原始阶段，较敏感；当前没有被执行层直接使用。 |
| `stage` | `normalizeAttentionStage()` | `normalize_stage()` | 平滑后的阶段；当前是 `candidateTier` 的核心输入，可能掩盖假主升走弱。 |
| `previousStage` | 前缀演化中的上一 normalized stage | 同上 | 只用于生成 transition，未形成独立交易合同。 |
| `transition` | `buildTransition(previousStage, stage)` | 字符串拼接 | 主要用于解释和 `entryAdvice`，执行层只在 context probe 中窄用。 |
| `confidence` | `calculateCycleConfidence()` | `cycle_confidence()` | 阶段证据分，但没有进入 V3 主执行判断。 |
| `rankVelocity` | `cycle.metrics.rankVelocity` | `cycle_metrics()` | 影响 raw/stage/risk，但执行层不直接消费。 |
| `rankAcceleration` | `cycle.metrics.rankAcceleration` | 同上 | 影响 raw/stage/risk；未作为 B 决策输出。 |
| `rankShock` | `cycle.metrics.rankShock` | 同上 | 影响风险；未被 V3 入场显式消费。 |
| `hotZoneStreak` | `cycle.metrics.hotZoneStreak` | 同上 | 影响 raw/stage/confidence；当前容易和固定热区语义混在一起。 |
| `bestRecentRank` | `cycle.metrics.bestRecentRank` | 同上 | 影响 raw/stage/confidence；当前不是独立合同字段。 |
| `drawdownFromPeak` | `cycle.metrics.drawdownFromPeak` | 同上 | 可识别高位回撤/假突破，但当前没有单独进入 B veto。 |
| `entryAdvice` | `buildEntryAdvice(stage, transition)` | `entry_advice()` | `preferred` 后验不强于 `watch`，不能继续表达成“允许买入”。 |

### 当前如何进入 `candidateTier`

TS `composeCandidateTier()` 当前直接用 `cycle.stage` 判定 A/B/C/D/N：

- `stage=expansion` 加中短周期动量、技术趋势、市场环境和资金背离，生成 `A_MAIN`。
- `stage=ignition` 加短周期动量、加速度、市场不退潮和风险压力，生成 `B_IGNITION`。
- `stage=crowded` 或长周期高热叠加转弱，生成 `C_CROWDED`。
- `stage=reversal/cooling` 叠加短周期或加速度走弱，生成 `D_EXIT_RISK`。

Python `compose_strategy()` 也直接用 `cycle.stage`，但与 TS 有合同漂移：

- Python A/B 放行更多依赖 `frame.hotlistSentiment` 的阶段和风险。
- TS 使用 `market_regime` 控制弱势/退潮。
- 因此 Python 当前不是“纯 TS golden 复制”，而是 `RankTrend + hotlistSentiment` 的执行版。

关键问题：生命周期 B 现在不是独立决策系统，而是被揉进了 `candidateTier`。这会导致两种错误：

- B 可能制造候选：只要 stage 被平滑成 expansion/ignition，A/B tier 就被制造出来。
- B 无法明确否决：执行层看不到“B 反对但 A 很强”的显式状态，只能通过 `candidateTier` 间接判断。

### 当前如何进入执行层

QuantBoard 执行入口在 `TradeSimulator._entry_candidates()`。

V3 当前路径：

```text
_entry_candidates()
  -> strategy_key == ranktrend_early_big_move_v3
  -> _is_early_big_move_v3_entry_signal()
  -> _is_early_big_move_v2_entry_signal()
  -> _is_early_big_move_entry_signal()
```

执行层当前消费方式：

- 第一层 A 结构：`jump.direction`、`jump.confidence`、short/mid/long 动量、acceleration/accDelta、可成交性。
- 第二层生命周期间接门槛：`candidateTier in A_MAIN/B_IGNITION`。
- V3 额外确认：`A_MAIN` 直接通过；`B_IGNITION` 需要中周期动量与零线同步。
- 排序：`_early_big_move_score()` 继续给 `stage in expansion/ignition` 和 `candidateTier in A/B` 加权。

这说明当前没有“B 决策输出 -> 执行层显式 veto”的接口。所谓生命周期门槛实际是 `candidateTier` 的副作用。

### 外部研究和论坛语义参考

这些材料只用来提炼语义，不直接变成参数：

- Jegadeesh & Titman 的经典动量研究说明过去赢家在中期维度存在延续性，但异常收益后续会部分消散。这支持 A 侧必须识别“动量延续”，也提醒 B 侧要识别“延续后的衰减”。来源：The Journal of Finance, 1993, DOI `10.1111/j.1540-6261.1993.tb04702.x`，可访问 PDF 备份 https://moneytothemasses.com/wp-content/uploads/2014/08/Jegadeesh_Titman_1993.pdf
- George & Hwang 的 52-week high momentum 研究表明“接近高点”能解释大量动量收益，且与简单过去收益不同。这支持 B 侧不能只看一阶动量，而要看相对位置、回撤和是否接近有效突破路径。来源：The Journal of Finance, 2004, PDF 备份 https://financialfactory.com/wp-content/uploads/2013/10/the52weekhighandmomentuminvesting.pdf
- Daniel & Moskowitz 的 momentum crashes 研究指出动量策略在特定状态会出现集中亏损，尤其和市场下跌后反弹、波动状态相关。这支持 B 侧要成为“状态风险识别器”，而不是继续用单点 stage 当买点。来源：Journal of Financial Economics, 2016, https://www.kentdaniel.net/papers/published/jfe_16.pdf
- Barber & Odean 的注意力驱动买入研究说明散户更容易买入新闻、高异常成交量、极端单日收益这类“抓眼球”的股票。这支持 B 侧必须识别热度拥挤与承接失败，不能把注意力上升等同于可买。来源：Review of Financial Studies, 2008, PDF 备份 https://www.empirical.net/wp-content/uploads/2014/12/Barber-and-Odean-All-that-Glitters-The-Effect-of-Attention-and-News-on-the-Buying-Behavior-of-Individual-and-Institutional-Investors.pdf
- 国内论坛/股吧常见“分歧转一致”“放量假突破”“顶背离/兑现”语义，本质对应路径判断：突破是否有承接、是否从分歧走向一致、是否出现价格创新但动能不跟随。可作为 B 侧 reasons 的业务语言来源，但不能直接当统计证据。参考：淘股吧分歧一致讨论 https://www.tgb.cn/a/2sdNTlxTpwN ，雪球假突破讨论 https://xueqiu.com/2166671964/321609229 ，东方财富放量滞涨观察 https://m.eastmoney.com/blog/article/1078335887
- Reddit breakout/fakeout 讨论不能作为学术证据，但可作为交易语义提醒：不少交易者把“突破时放量”视为能量确认而不是方向确认，真正需要看突破前量能堆积、突破后的价格行为质量和后续数个 bar 是否承接；这与 B 侧 `caution/veto/exit_watch` 的路径语义一致。参考：r/Daytrading breakout volume filter https://www.reddit.com/r/Daytrading/comments/1r19lax/i_analyzed_2877_breakouts_and_built_a_volume/ ，r/pinescript volume breakout test https://www.reddit.com/r/pinescript/comments/1sfvn0y/volume_on_a_breakout_doesnt_predict_whether_the/ ，r/Daytrading breakout confirmation discussion https://www.reddit.com/r/Daytrading/comments/1qj2obi/what_confirms_a_breakout_for_you/

可落地原则：

- A 负责找“动量延续的早期结构”，B 负责判断“延续是否处在可交易生命周期”。
- B 的 veto 应聚焦路径冲突，不做固定名次过滤。
- B 的 reasons 应表达为路径事实：原始阶段转弱、平滑阶段滞后、热区停留后回撤、注意力拥挤但资金/动能未同步、突破后承接失败。
- Reddit/论坛语义只能提醒“假突破风险来自承接失败”，不能直接落成固定成交量、固定排名或固定 bar 数阈值；实现时必须用亏损单/盈利单证据验证。

### A+B 融合合同

建议新增显式字段，不复用 `entryAdvice.allowed`：

```text
rankTrend.cycle.decision = {
  action: allow | caution | veto | exit_watch,
  confidence: 0..100,
  reasons: string[],
  evidence: {
    rawStage,
    stage,
    transition,
    rankVelocity,
    rankAcceleration,
    drawdownFromPeak,
    hotZoneStreak,
    riskPressure,
    divergenceSeverity,
    overheatSeverity
  }
}
```

语义：

- `allow`：B 支持 A 的早期结构进入候选池。
- `caution`：B 不反对，但路径不干净；可以进入候选池，但排序/仓位优先级低于 allow。
- `veto`：B 反对；不能进入候选池，一票否决。
- `exit_watch`：持仓后生命周期恶化；不制造卖出，但降低卖出触发门槛，服务已有 early big move 出场逻辑。

合同边界：

- B 不能独立制造 buy。
- B veto 可以拦截 A。
- `entryAdvice` 保留为展示/旧兼容字段，但不能再作为交易许可。
- `candidateTier` 应逐步拆成 “A 结构分层” 与 “B 决策结果” 两部分，避免把生命周期阶段继续混进主策略命名。

### 生命周期 B 语义定义

B 应当回答四个问题：

1. 当前 A 的强结构是否处于真实点火/扩散路径，而不是平滑 stage 的滞后错觉。
2. 是否存在假主升：`stage` 仍强，但 `rawStage`、速度、加速度、回撤或风险已经反对。
3. 是否存在强动量假突破：动量看似强，但热区停留、回撤、背离、过热或承接不足同时出现。
4. 持仓后是否进入 exit_watch：不是立刻卖出，而是让既有出场规则更敏感。

B 不应该回答：

- 不应该决定 A 是否存在早期大肉结构。
- 不应该用固定排名位置制造买点。
- 不应该恢复旧生命周期独立买卖策略。
- 不应该把 `preferred` 解释成可以买。

### 当前代码需要拆开的点

1. TS：在 `attentionCycleAnalyzer.ts` 后新增或拆出 `composeLifecycleDecision()`，使用 cycle + risk + technical context，输出 `cycle.decision`。
2. TS：在 `candidateTierComposer.ts` 中停止把 `cycle.stage` 当作唯一生命周期判断来源；短期可保留现有 `candidateTier` 兼容输出，但增加 B 决策 reasons。
3. Python：在 `ranktrend.py` 中对齐新增 `lifecycle_decision()`，并在 `_build_signal()` 输出 `rankTrend.cycle.decision`。
4. Python：`compose_strategy()` 不再承担 B 决策语义，只保留 A/B/C/D 兼容分层或迁移为结构分层。
5. 执行层：`_is_early_big_move_v3_entry_signal()` 先判断 A 结构，再读取 `cycle.decision.action`；若为 `veto` 直接返回 false。
6. 排序层：`_early_big_move_score()` 对 `allow/caution` 做排序差异；不要让 `caution` 挤掉高质量 `allow`。
7. 报告层：入场原因和 skipped/diagnostic 需要记录 B veto reasons，便于亏损/错杀复盘。

### TDD 测试清单

先写失败测试，再改实现：

1. TS 生命周期输出包含 `cycle.decision.action/confidence/reasons/evidence`。
2. Python 生命周期输出合同与 TS 字段名一致，至少包含 `rawStage/stage/transition/rankVelocity/rankAcceleration/drawdownFromPeak/hotZoneStreak` evidence。
3. `stage=expansion` 但 `rawStage` 转弱且回撤/风险同步恶化时，B 输出 `veto` 或高置信 `caution`，不能普通 allow。
4. 强 A 信号加 B `veto` 时，`ranktrend_early_big_move_v3` 不进入候选池。
5. A 不通过时，即使 B `allow`，也不能进入候选池。
6. B `caution` 可进入候选池，但同等 A 条件下排序低于 B `allow`。
7. `entryAdvice=preferred` 不能绕过 B，也不能制造 buy。
8. 兼容测试确认默认 V3 未接入新策略前行为不被旧字段破坏；接入版本应使用显式 strategy/version 或受控开关。
9. 真实路径样本测试至少覆盖四类：大肉、假主升、强 long 假突破、低 long 大肉。

### 实施顺序建议

1. 文档确认后，先写 TS/Python 合同失败测试。
2. 实现 `cycle.decision`，只输出字段，不改默认 V3 入场。
3. 增加 research-only 融合策略，例如 `ranktrend_early_big_move_v3_lifecycle_fusion`，执行层启用 B veto。
4. 跑 4 月/5 月 current-bar / 30 bars，对比 V3 主线与用户认可结果。
5. 只有满足 `winRate >= 60%` 且收益继续向 `20%` 靠近，才讨论是否替代 V3。

### Phase 33 Implementation Checkpoint

已按 TDD 完成第一步实现：

- TS `analyzeAttentionCycle()` 输出 `cycle.decision.action/confidence/reasons/evidence`。
- Python `analyze_cycle()` 输出同名合同字段，保持 camelCase。
- 新增 research-only 策略 `ranktrend_early_big_move_v3_lifecycle_fusion`。
- 执行层融合逻辑为：A 结构必须先通过 V3；随后若 B `decision.action == veto`，一票否决；B `allow` 不能独立制造买入。
- 融合策略已纳入 early big move 专属退出族，避免回退到旧生命周期/最终信号退出。

当前 B 语义只是合同打通版：`reversal -> veto`，`ignition/expansion -> allow`，`crowded -> exit_watch`，`cooling -> caution`。这不是最终优化模型，后续仍必须通过 4 月/5 月真实复跑和亏损单归因验证。

### Phase 33 Fusion Rerun Findings

结论先行：首版 `ranktrend_early_big_move_v3_lifecycle_fusion` 没有提升收益/胜率，因为它和同代码版本 V3 的交易集合完全一致。原因不是 A+B 合同方向错，而是当前 B 语义太浅：所有 V3 可入场信号的 `cycle.decision.action` 都是 `allow`，没有任何 veto 样本。

真实复跑口径：

- `strategyName=ranktrend_early_big_move_v3_lifecycle_fusion`
- `snapshotType=half_hour`
- `executionMode=current_bar`
- `maxHoldingBars=30`

有效 run：

| Window | Strategy | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown | stops |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4月 | V3 同代码版本 | `bt_d7e06ceab8ca454c` | `+6.43%` | `+2.79%` | `90.00%` | 10 | `-2.99%` | 1 |
| 4月 | lifecycle_fusion | `bt_1dd91533206f4b6e` | `+6.43%` | `+2.79%` | `90.00%` | 10 | `-2.99%` | 1 |
| 5月 | V3 同代码版本 | `bt_020f7489ffe14fa1` | `+14.56%` | `+12.49%` | `64.71%` | 17 | `-4.06%` | 3 |
| 5月 | lifecycle_fusion | `bt_9f5e8606a93d4c59` | `+14.56%` | `+12.49%` | `64.71%` | 17 | `-4.06%` | 3 |

对照已确认：

- 4 月 V3 与 fusion：入场集合 `same=10 / onlyV3=0 / onlyFusion=0`。
- 5 月 V3 与 fusion：入场集合 `same=17 / onlyV3=0 / onlyFusion=0`。
- 4 月 V3 可入场信号：58 个，`allow=58`，无 veto。
- 5 月 V3 可入场信号：146 个，`allow=146`，无 veto。

亏损/盈利样本给出的关键提醒：

- 亏损单不是典型“生命周期已转弱”形态，多数仍是 `cooling->expansion` 或 `cooling->ignition`，且 `rankVelocity/rankAcceleration` 很强。
- 大肉也大量来自同样路径，例如 `603459 红板科技` 是 `cooling->expansion + long=4.59` 的大肉；所以不能简单把某个 transition 或低 long 直接硬 veto。
- 当前 `cycle.decision.evidence` 原本把 `riskPressure/divergenceSeverity/overheatSeverity` 写成 0，占位字段无法支持 B 做真实辅助决策。

已按 TDD 修复合同证据：

- TS `analyzeAttentionCycle()` 支持写入风险 evidence；`RankTrendAnalyzer` 在算完 `risk` 后回填 `cycle.decision.evidence`。
- Python `lifecycle_decision()` 支持可选 `risk`，`RankTrendPythonEngine._build_signal()` 在算完 `risk` 后回填 `cycle["decision"]`。
- 该修复只改变诊断/合同 evidence，不改变 V3 默认策略，不改变 fusion 的入场 action 规则。

下一步方向：

1. 不再继续重跑首版 fusion；它已经证明“合同通了，但 B 没有实际拦截语义”。
2. 下一轮必须先写失败测试，让 B 在真实风险证据明确反对时输出 `caution/veto`。
3. B 语义应优先研究“强 A + 风险背离/过热/反向承接失败”的组合，而不是按固定排名、单一 long 或单一 transition 硬过滤。
4. 任何 veto 规则必须同时验证是否误杀 `603459` 这类低 long 大肉，以及是否能减少 `002281/301666/603773` 这类止损来源。

### Phase 33 纠偏：生命周期本体重审

结论先行：前一版审计只证明了合同接通，但没有真正审视生命周期判定本体。当前本体达不到辅助决策系统 B 的要求，根因是它把 `ignition/expansion` 直接翻译成 `allow`，没有回答两个关键问题：

- 该阻止进入候选池的假突破/假主升，是否有明确反对证据。
- RankTrend 漏选的结构里，是否有生命周期认可但 A 侧未完整满足的研究机会。

只读重放同代码版本 V3 后得到的关键证据：

| Window | V3 可入场信号 | B action | 亏损单特征 |
| --- | ---: | --- | --- |
| 4月 | `57` | 全部 `allow` | 唯一亏损 `000070` 为 `A_MAIN + cooling->expansion`，风险证据偏低 |
| 5月 | `154` | 全部 `allow` | 6 笔亏损均为 `A_MAIN/B_IGNITION + cooling->expansion/ignition` |

这说明单纯把高 `riskPressure/divergence/overheat` 变成 veto 仍不够。亏损单里既有风险偏高样本，也有低风险样本；大肉同样来自 `cooling->expansion/ignition`，所以不能按 transition、long 或风险单点硬拦。

漏选侧也有反向证据：`base_not_v3` 中确实存在大肉，例如 `301217 铜冠铜箔`、`301666 大普微-UW`、`600183 生益科技`、`603459 红板科技` 等，但同一池子也有大量深回撤假突破。结论不是重新放开非 A/B 候选，而是新增 `B.discovery` 研究提示通道：生命周期可以标记“RankTrend 漏选但值得复盘”，但在没有新证据前不直接进入交易候选池。

新的实现方向：

1. `B.veto`：只针对 A 已通过的候选，识别路径冲突。第一批 TDD 覆盖高风险背离、过热回落、阶段平滑滞后造成的假主升。
2. `B.discovery`：只输出诊断标签，不制造买入。第一批 TDD 覆盖“强生命周期恢复 + A 未完整通过”的研究提示，防止继续无视漏选。
3. `candidateTier` 短期保留兼容，但不再作为 B 语义唯一来源；B 必须输出独立 reasons/evidence，便于复盘错杀和漏选。

第一轮实现结果：

- 已新增 `cycle.decision.discovery.action = none | research_watch`。
- 已新增高风险冲突 veto：当点火/扩散路径同时出现明确风险反对时，B 不再普通 `allow`。
- 已确认 `discovery=research_watch` 只作为研究诊断，fusion 执行入口不会让它绕过 V3 主结构制造买入。
- 已修正 TS/Python 合同漂移：TS 端原先算完 risk 后只回填 evidence，不重算 action；现在与 Python 一样在 risk 完整后生成最终 `cycle.decision`。

重要限制：

- 信号层复核显示，4 月/5 月 V3 可入场信号仍没有被高风险 veto 拦截：4 月 `57 -> 57`，5 月 `154 -> 154`。
- 这说明假突破的主因不是简单“当前风险数值极端高”，而更像“最后一跳很强但整段排名路径承接不足”。
- 下一轮应补 `rankPathCommitment` / 突破承接质量语义：结合整段 `rawChange`、当前跳跃、短中长动量承接、上一段状态和风险冲突，多证据同时反对才 veto。
- 不应把 `rawChange`、long、volumeRatio、transition 任一单点直接变成硬门槛；样本里每个单点都有大肉反例。

第二轮 TDD 已完成：

- `rankPathCommitment` 进入 TS/Python `cycle.metrics` 与 `cycle.decision.evidence` 合同。
- 语义不是固定排名过滤，而是路径承接质量：最后一跳之前是否已有持续向上承接，以及最后一跳是否占掉几乎全部改善。
- 当 `stage=ignition/expansion` 且最后一跳很强、加速度很强、但 `rankPathCommitment` 很弱时，B 输出 `veto`，理由包含“承接不足/假突破”。
- 低 long 但路径连续改善的样本不会因为长周期弱被 veto，用于保护 `603459 红板科技` 这类低 long 大肉形态。

限制：这一步只完成合同与单元级语义，尚未证明 4 月/5 月真实 V3 候选集合会改善。下一步必须先做信号层复核，再决定是否跑完整回测。

### Phase 33 Signal-Layer Review: rankPathCommitment veto

结论先行：`rankPathCommitment` 方向能识别一部分“最后一跳很猛但整段承接不足”的假突破，但当前 veto 语义过宽，不能直接复跑并采用。它命中了 `000070`、`301526`、`001309` 这类亏损/弱票，但也会误杀 4 月原 V3 成交路径中的多笔盈利票；同时没有挡住 5 月核心亏损 `603773`、`301666`、`002281`。

复核口径：

- 数据：`dragonboard_live / half_hour`
- 窗口：4 月 `2026-04-01..2026-04-30`，5 月 `2026-05-01..2026-05-31`
- 方法：本地 replay 当前 Python RankTrend signals，不落库；用原 V3 run 的 `(entrySignalSnapshotId, code)` 回连新 B `cycle.decision`
- 原 V3 对照：4 月 `bt_a80a2e51db204882`，5 月 `bt_24bce043660b48ec`

信号层整体：

| Window | signals | base early structure | base veto | no-lifecycle candidates | no-lifecycle veto | current V3 candidates | fusion candidates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4月 | `20237` | `467` | `90` | `413` | `75` | `40` | `40` |
| 5月 | `34770` | `968` | `169` | `798` | `132` | `107` | `107` |

当前 `compose_strategy()` 已经尊重 `cycle.decision.action=veto`，因此 replay 后 `current V3` 与 `fusion` 集合一致。也就是说，被 B veto 的票会先从 `candidateTier=A_MAIN/B_IGNITION` 降出去，执行层再看 V3 时已经不可入场。这是 A+B 融合合同生效的表现，但也意味着必须用原 V3 成交路径回连新 B 来判断误杀。

原 V3 成交路径回连新 B：

| Window | 原 V3 交易 | 原胜率 | 原利润 | B veto 交易 | veto 亏损 | veto 盈利 | 原路径保留胜率 | 原路径保留利润 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4月 | `10` | `90.0%` | `+31,245.40` | `6` | `1` | `5` | `100.0%` | `+18,419.30` |
| 5月 | `17` | `64.7%` | `+127,369.81` | `4` | `2` | `2` | `69.2%` | `+127,716.42` |

命中亏损：

- `000070 特发信息`：4 月止损，`rankPathCommitment=0.112`，B veto 命中，符合“最后一跳过强但承接不足”。
- `301526 国际复材`：5 月小亏，`rankPathCommitment=0.336`，B veto 命中。
- `001309 德明利`：5 月亏损，`rankPathCommitment=0.442`，B veto 命中。

未命中核心亏损：

- `603773 沃格光电`：5 月止损大亏，B 仍 `allow`，`rankPathCommitment=0.503`。
- `301666 大普微-UW`：5 月止损，B 仍 `allow`，`rankPathCommitment=0.534`。
- `002281 光迅科技`：5 月止损，B 仍 `allow`，`rankPathCommitment=0.839`。

大肉保护：

- `300308 中际旭创`、`300502 新易盛`、`603459 红板科技`、`301217 铜冠铜箔` 在 5 月原 V3 成交路径均为 `allow`，未被误杀。
- 其中 `603459 红板科技` 是低 long 大肉，`long=4.59` 但 `rankPathCommitment=0.751`，说明当前语义确实没有用 low long 硬杀。

误杀问题：

- 4 月误杀过重：原路径 6 笔 veto 中 5 笔盈利，移除的是 `+12,826.10` 正利润。
- 典型误杀包括 `000890 法尔胜`、`002560 通达股份`、`603618 杭电股份` 等，它们虽被判“承接不足”，但原 V3 持有到上限后盈利。

当前判断：

- 暂不复跑完整 fusion，不把当前 B veto 当成可采用策略。
- 下一步应收窄 veto 触发语义，避免把“承接不足但仍能沿题材/趋势延续盈利”的票一刀切。
- 新的 B 需要引入更明确的失败确认，例如承接不足叠加价格/排名回落、风险压力、后续确认缺失、或和 A_MAIN/B_IGNITION 结构冲突，而不是只看最后一跳占比。

### Phase 33 Narrowed veto and rerun

结论先行：已把 `rankPathCommitment` veto 从“弱承接直接否决”收窄为“弱承接且中长动量承接未建立才否决”。这修复了 4 月过度误杀，但完整复跑仍未优于历史 V3 最佳，原因是 B veto 改变排序/仓位路径后，资金转入 `000657` 这类更大的假点火，挤掉了 `603459` 大肉。

实现变化：

- TS/Python `cycle.decision.evidence` 增加 `momentumShort/momentumMid/momentumLong/momentumAcceleration`。
- TS `RankTrendAnalyzer` 在生成 lifecycle decision 时传入 `technical.momentumProfile`。
- Python `RankTrendPythonEngine._build_signal()` 在生成 `lifecycle_decision()` 时传入 `technical["momentumProfile"]`。
- weak path veto 现在要求：路径承接弱、速度/加速度强、阶段为点火/扩散，且没有“中长动量承接已建立”的例外。

TDD 覆盖：

- 弱承接且无中长承接仍 veto，用于保留 `000070` 类假突破识别。
- 弱承接但中长动量已建立不 veto，用于减少 `000890/603618` 类原路径盈利票误杀。

信号层复核变化：

| Window | base early structure | base veto before | base veto after | 原 V3 交易被 veto before | 原 V3 交易被 veto after |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4月 | `467` | `90` | `45` | `6` | `4` |
| 5月 | `968` | `169` | `70` | `4` | `2` |

原 V3 成交路径回连新 B：

| Window | 原 V3 交易 | 原利润 | after veto 交易 | after veto 亏损 | after veto 盈利 | 原路径保留胜率 | 原路径保留利润 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4月 | `10` | `+31,245.40` | `4` | `1` | `3` | `100.0%` | `+33,542.85` |
| 5月 | `17` | `+127,369.81` | `2` | `2` | `0` | `73.3%` | `+130,814.32` |

完整复跑结果：

| Window | Strategy | Run ID | totalReturn | winRate | trades | maxDrawdown | stops |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 4月 | current V3 | `bt_aeb105e5cb6c401d` | `+4.33%` | `70.00%` | `10` | `-3.53%` | `0` |
| 4月 | lifecycle_fusion | `bt_ddbdb8c0424e4279` | `+4.33%` | `70.00%` | `10` | `-3.53%` | `0` |
| 5月 | current V3 | `bt_6a450032ac644fe0` | `+8.63%` | `62.50%` | `16` | `-4.51%` | `3` |
| 5月 | lifecycle_fusion | `bt_327565ed14484c70` | `+8.63%` | `62.50%` | `16` | `-4.51%` | `3` |

对比历史 V3：

- 4 月历史 V3 `bt_a80a2e51db204882` 为 `+6.76% / 90.00% / 10 trades`，当前收窄 B 后降为 `+4.33% / 70.00%`。
- 5 月历史 V3 `bt_24bce043660b48ec` 为 `+14.81% / 64.71% / 17 trades`，当前收窄 B 后降为 `+8.63% / 62.50%`。
- 当前 V3 与 lifecycle_fusion 一致，因为 Python `compose_strategy()` 已在 candidateTier 组合层尊重 `cycle.decision.action=veto`，fusion 执行层不再额外改变交易集合。

交易路径差异：

- 4 月删除 `000070` 亏损有效，但同时删除 `002560/600498/600110` 等盈利；新增 `000938` 大赚后抵消部分影响，最终仍低于历史 V3。
- 5 月删除 `301526/001309/002281` 三个亏损有效，但也删掉 `603459` 大肉与 `600900` 小赚；新增 `000657` 大亏 `-30,992.56`，是收益下滑主因。
- `603459` 不是被 B veto 直接误杀，它在 `2026-05-20 13:30` 仍为 `allow` 且 V3/fusion 可入场；它是被更早的替代交易/仓位路径挤掉。

下一步判断：

- 不应继续扩大 `rankPathCommitment` veto。
- 需要新增 B 的“低可见度点火/仓位挤占”语义，重点处理 `B_IGNITION` 中技术信号漂亮但热榜注意力位置尚未进入主流承接、容易抢占后续大肉仓位的样本。
- 下一轮 TDD 应以 `000657` vs `603459` 同窗/路径竞争为真实 case：B 不能独立制造买入，但可以对低可见度点火输出 `caution/veto` 或排序降权，保护后续更高质量 A_MAIN 大肉。

### Phase 33 B_IGNITION low-visibility ignition findings

结论先行：低可见度点火诊断能命中 `000657 中钨高新` 这类抢仓风险，但硬阻止进入 `B_IGNITION` 后，完整复跑仍未改善到历史最佳，不能采用为默认策略。

实现语义：

- 生命周期本体不直接把低可见度首段点火判为全局 `veto`，而是输出 `cycle.decision.action=caution`。
- Python `compose_strategy()` 在准备生成 `B_IGNITION` 时消费该 caution；若原因包含“低可见度首段点火”，则暂缓进入 A/B 候选池。
- A_MAIN、已扩散路径、普通 caution 不受该规则影响，避免把 B 恢复成旧生命周期主策略。

真实样本：

- `000657@2026-05-13 10:30`：原为 `B_IGNITION`，技术信号漂亮，`short=21.83`、`mid=28.95`、`long=23.83`、`acc=24.29`、`zeroCross=buy`，但 `hotZoneStreak=0`、`rankPathCommitment=0.669`，属于首段点火承接尚未扩散。本轮被降为 `N_NEUTRAL + caution`。
- `603459@2026-05-20 13:30`：仍为 `A_MAIN + allow`，`rankPathCommitment=0.751`、短中动量和加速度强，未被低可见度点火规则直接否决。

复跑结果：

| Window | Strategy | Run ID | totalReturn | winRate | trades | maxDrawdown | stops |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 4月 | current V3 | `bt_8e495a48dc024110` | `+2.97%` | `60.00%` | 10 | `-3.54%` | 1 |
| 4月 | lifecycle_fusion | `bt_596abcbebc9c43f6` | `+2.97%` | `60.00%` | 10 | `-3.54%` | 1 |
| 5月 | current V3 | `bt_c68f244cf33a40fa` | `+7.64%` | `62.50%` | 16 | `-3.75%` | 3 |
| 5月 | lifecycle_fusion | `bt_ea1d956df3c24758` | `+7.64%` | `62.50%` | 16 | `-3.75%` | 3 |

解释：

- 5 月去掉 `000657` 后，收益没有回到历史 V3 `+14.81%`，说明真实问题已经不是单个假点火，而是排序/现金/仓位路径会继续寻找替代候选。
- 当前 V3 与 lifecycle_fusion 仍一致，说明 B 的候选池融合已在 `compose_strategy()` 层提前生效。
- 这个方向适合作为诊断和后续排序降权依据，但不适合继续扩大硬过滤。

下一步建议：

1. 暂停新增生命周期硬 veto。
2. 研究 `B caution` 的排序/仓位降权，而不是直接删候选。
3. 对 5 月 `bt_c68f244cf33a40fa` 的新增替代路径做归因，找出删除 `000657` 后资金流向哪里，以及为什么仍未等到 `603459`。

### Phase 33 Sorting boundary rerun: B caution not hard veto

结论先行：本轮达成当前目标。根因不是生命周期 B 不能用，而是 B 的承接不足诊断被放得太重：它在 `compose_strategy()` 候选分层层提前改写了所有策略的 A/B 候选池，导致 V3 对照和 fusion 被绑在同一条被削弱的路径上。修正后，fusion 与 V3 在 4 月+5 月合并达到 `+20.29%` 总收益、`70.37%` 胜率。

关键改法：

- TS `rankTrend.strategy` 只保留展示/结构分层，不再代替 V5 执行分层。
- Python `compose_strategy(... hotlist ...)` 是 V5 execution tier 来源；当 B 明确 veto 时不再输出 A/B，Dragon Board live 通过 `rankTrend.executionStrategy` 消费同一口径。
- `rankPathCommitment` 承接不足从 `veto` 降为 `caution`，作为假突破诊断而不是硬删候选。
- 低可见度首段点火仍为 `caution`，候选保留，只在同等结构排序时轻微降权。

复跑口径：

- `dataset_id=dragonboard_live`
- `snapshot_type=half_hour`
- `executionMode=current_bar`
- `maxHoldingBars=30`
- `takeProfitPct=9.99`
- `stopLossPct=0.05`

复跑结果：

| Window | Strategy | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown | stops |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 4月 | V3 | `bt_5943a9c125484bd3` | `+8.97%` | `+5.34%` | `90.00%` | 10 | `-2.68%` | 1 |
| 4月 | lifecycle_fusion | `bt_3874b02c9bc3444a` | `+8.97%` | `+5.34%` | `90.00%` | 10 | `-2.68%` | 1 |
| 5月 | V3 | `bt_66a2b8b195914ec7` | `+11.32%` | `+12.14%` | `58.82%` | 17 | `-4.55%` | 3 |
| 5月 | lifecycle_fusion | `bt_e4e30e6dbf0b4946` | `+11.32%` | `+12.14%` | `58.82%` | 17 | `-4.55%` | 3 |

合并结果：

| Strategy | totalReturn sum | combined winRate | wins/trades |
| --- | ---: | ---: | ---: |
| V3 | `+20.29%` | `70.37%` | `19/27` |
| lifecycle_fusion | `+20.29%` | `70.37%` | `19/27` |

关键样本复核：

- `603459 红板科技`：5 月 fusion 保留，入场 `2026-05-20 13:30`，B `allow`，利润 `+49,390.17`，没有误杀低 long 大肉。
- `000657 中钨高新`：未进入 5 月实际成交路径；低可见度点火不再靠硬删除触发路径替换。
- `000070 特发信息`：4 月仍入场并亏损，B 标记 `caution`，`rankPathCommitment=0.112`，说明承接不足诊断有效但暂不硬删。
- `301526 国际复材`、`001309 德明利`：5 月入场亏损，B 标记 `caution`，属于后续排序降权候选，而不是当前一票否决对象。
- `002281 光迅科技`、`301666 大普微-UW`：B 为 `allow`，亏损来源不是承接不足型，不能用当前生命周期规则硬拦。

结论：当前阶段不继续扩大生命周期硬 veto。B 的正确融合方式是：少数明确反转/高风险冲突才一票否决；承接不足、低可见度首段点火作为 caution 诊断和排序依据。这样既保留 `603459` 等大肉，又避免删除候选后引发新的仓位路径替换。

### Phase 33 Continuous 4-5月 rerun

结论先行：单次连续窗口复核通过，而且强于简单月度相加口径。`2026-04-01~2026-05-31` 连续回测 run `bt_6bad357f332b4197` 达到 `+24.68%`，胜率 `71.43%`。这是真正同一个回测窗口内的连续资金路径，不是 `4月 + 5月` 两个 run 的收益相加。

复跑口径：

- `dataset_id=dragonboard_live`
- `snapshot_type=half_hour`
- `strategy_name=ranktrend_early_big_move_v3_lifecycle_fusion`
- `start_date=2026-04-01`
- `end_date=2026-05-31`
- `executionMode=current_bar`
- `maxHoldingBars=30`
- `takeProfitPct=9.99`
- `stopLossPct=0.05`

结果：

| Run ID | totalReturn | realizedReturn | winRate | wins/trades | maxDrawdown | Sharpe | stops | openPositions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bt_6bad357f332b4197` | `+24.68%` | `+21.43%` | `71.43%` | `25/35` | `-7.41%` | `2.8168` | 7 | 2 |

关键路径差异：

- 该连续窗口不是月度结果的拼接，交易路径会因为现金、持仓和 T+1 状态连续滚动而变化。
- `603459` 没有进入这条连续路径，但总收益仍提升到 `+24.68%`。
- `000657` 也没有进入这条连续路径。
- 已知亏损样本中，`000070` 止损 `-11,908.72`，`001309` 排名大幅下降+MACD死叉 `-4,189.28`，`301666` 止损 `-12,269.11`。

解释：这次复核修正了上一轮“月度相加”的表达问题。当前可以说：严格连续回测已经达到 `20%+ / 70%+` 目标；但仍需保留风险提示，连续窗口最大回撤为 `-7.41%`，止损单 7 笔，后续优化不应扩大硬 veto，而应继续研究 `000070/301666` 等亏损形态。

### Phase 33 Stop-Loss Attribution and B-assisted exit

结论先行：突破 `30%` 的关键不是继续扩大入场硬过滤，也不是把 `caution` 票简单往后排，而是让生命周期 B 在持仓后承担“辅助退出决策”。当 B 已经明确反对，且持仓还没有盈利时，应降低卖出门槛提前撤；如果持仓已经盈利，则继续让利润奔跑。

止损拆解基线：

- 对照 run：`bt_6bad357f332b4197`
- 口径：`dragonboard_live / half_hour / current_bar / 30 bars / 2026-04-01~2026-05-31`
- 结果：`+24.68%`，胜率 `71.43%`，止损 `7` 笔，最大回撤 `-7.41%`
- 7 笔止损合计约 `-85,253.20`，最大亏损来自 `002929 润建股份`，其次是 `601869 长飞光纤`、`301666 大普微-UW`、`000070 特发信息`、`600111 北方稀土`。

关键证据：

- `weak_commitment caution` 组 7 笔，胜率 `42.9%`，利润 `-14,103.35`，但包含 `002560 通达股份` 这类盈利反例，不能硬杀。
- `low_visibility caution` 组 8 笔，胜率 `87.5%`，利润 `+26,267.92`，但包含最大止损 `002929`；同组还有 `688256 寒武纪` 大肉，所以不能硬杀低可见度点火。
- 入场排序降权离线复跑无效：加大 `low_visibility/weak_commitment/低量能` 排序惩罚后，没有改善连续 run，部分组合还会引入新的弱路径。
- 多笔止损在入场后很快出现 `cycle.decision.action=veto/exit_watch`、`stage=reversal` 或 `D_EXIT_RISK`，但旧退出只认 `止损`、退出热榜、`rawChange < -50 + MACD死叉` 或到达持仓上限，导致亏损继续扩大。

新规则：

```text
仅对 ranktrend_early_big_move_v3_lifecycle_fusion 生效：
如果持仓已过 T+1 可卖限制，
且 cycle.decision.action 为 veto 或 exit_watch，
且当前 gross_return <= 0，
则退出，原因为“生命周期B反对且未盈利”。
```

这条规则的边界：

- 不改变普通 V3。
- 不改变入场候选池。
- 不让生命周期 B 独立制造买入。
- 不在盈利仓上触发，避免砍掉大肉。
- 不恢复旧生命周期独立买卖策略。

正式复跑：

| Run ID | totalReturn | realizedReturn | winRate | wins/trades | maxDrawdown | Sharpe | stops | exit by B |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bt_b8c73ecf67e24d78` | `+31.00%` | `+27.74%` | `65.79%` | `25/38` | `-3.19%` | `3.6986` | 4 | 6 |

改善来源：

- 止损从 `7` 降到 `4`。
- 最大回撤从 `-7.41%` 收窄到 `-3.19%`。
- `601869 长飞光纤` 从原止损 `-13,463.40` 改为 B 反对提前退出 `-918.01`。
- `600111 北方稀土` 从原止损 `-10,478.88` 改为 B 反对提前退出 `-6,236.53`。
- Top winners 仍由最大持有退出贡献，`603256`、`688256`、`301217`、`300394`、`000988` 等大肉没有被 B 反对提前砍掉。

仍未解决：

- `301666 大普微-UW` 仍止损 `-12,269.11`，它在入场后曾大幅浮盈再回落，属于“利润保护/回撤保护”问题，不适合用未盈利 B 退出解决。
- `000070 特发信息` 仍止损 `-11,908.72`，入场后 B 已谨慎但早期未触发未盈利 veto，需要后续研究更细的假突破确认。
- `002929 润建股份` 是基线 run 的最大止损，但新退出规则改变资金路径后不再出现在最差交易中；它提醒低可见度 caution 有风险，但同类有大肉反例，不能升级成硬过滤。

复核备注：

- 交付前复跑同窗口、同策略、同 `volumeParticipationRate=0.1`，新 run `bt_682d3abc164d4177` 复现 `+31.00% / 65.79%`，说明 `bt_b8c73ecf67e24d78` 不是文档手写数字。
- 用 CLI 默认 `volumeParticipationRate=0.05` 重跑得到 `bt_7eaaa1f656764be8`，结果为 `+28.93% / 68.42%`；该差异来自成交容量约束，不应混用口径。
- 因 `totalReturn` 含 2 个未平仓浮盈，后续报告应同时列出 `realizedReturn=+27.74%`，避免把浮盈当成完全落袋利润。

V5 基线决策：

- 默认长测 baseline set 调整为 `early_big_move_v5`。
- V5 主口径固定为 `ranktrend_early_big_move_v3_lifecycle_fusion / half_hour / current_bar / maxHoldingBars=30 / volumeParticipationRate=0.1 / stopLossPct=0.05 / takeProfitPct=9.99`。
- 采用原因是该口径已被 `bt_b8c73ecf67e24d78`、`bt_682d3abc164d4177`、`bt_01d35aac6fcf4d6c` 多次复现到 `+31.00% / 65.79%`，并且 25/28/32/35/40 bars 对照均未超过 30 bars。
- V5 不是恢复生命周期独立买卖策略；生命周期 B 只作为 RankTrend A 之后的辅助决策系统，可以 veto 入场和在未盈利时触发提前退出，但不能独立制造买入。
- 页面趋势数据来自 `long_test_runs.jsonl`，不是来自 CLI 默认 baseline set；已补正式 checkpoint `checkpoint_2026-06-09_early_big_move_v5_vpr01`，run `bt_c78fb2ad8df84946` 为 `+31.00% / 65.79%`。
- `/api/backtests/checkpoints` 已保留 V5 标签，趋势页在后端重启后显示 `V5 E1` / `V5 E2`。

### Phase 34 Remaining stops and open-profit attribution

结论先行：`bt_682d3abc164d4177` 的 `+31.00%` 不是单票偶然大肉撑出来的，但也不是均匀小胜堆出来的。它主要来自“多只大肉簇 + 最大持有退出”贡献：最大单票 `603256 宏和科技` 占最终利润约 `17.1%`，剔除最大 1 笔后仍约 `+25.69%`，剔除最大 3 笔后仍约 `+17.51%`。因此方向可靠性强于单票奇迹，但要冲更高收益，必须继续保护大肉簇并减少剩余止损。

收益结构：

- `realizedProfit=277,426.33`，`unrealizedProfit=32,350.45`，最终利润约 `309,776.78`。
- 盈利交易 `25` 笔，合计 `+324,241.45`；亏损交易 `13` 笔，合计 `-46,815.12`。
- 最大持有退出 `26` 笔，胜率 `92.31%`，利润 `+320,528.51`，是主要利润来源。
- B 辅助退出 `6` 笔，全部小亏，合计 `-11,844.91`；它的价值不是赚钱，而是防止亏损扩大。
- 止损 `4` 笔，合计 `-28,094.53`，仍是下一轮主要亏损来源。

按入场层级拆分：

- `A_MAIN + allow`：`16` 笔，胜率 `50.0%`，利润 `+111,291.89`，含 `3` 笔止损，波动大但贡献仍为正。
- `A_MAIN + caution`：`5` 笔，胜率 `40.0%`，利润 `-7,255.25`，含 `000070`，是假突破优先研究组。
- `B_IGNITION + allow`：`7` 笔，胜率 `85.71%`，利润 `+81,271.22`，无止损。
- `B_IGNITION + caution`：`10` 笔，胜率 `90.0%`，利润 `+92,118.47`，无止损。说明低可见度/承接 caution 不能硬杀，很多仍是大肉或强趋势延续。

剩余 4 笔止损：

- `000070 特发信息`：入场 `A_MAIN + expansion + caution`，`rankPathCommitment=0.112`，最后一跳强但整段承接弱。入场后最大浮盈仅 `+0.97%`，次日可卖时已是 `D_EXIT_RISK` 且亏 `-2.38%`，但 B 仍是 `caution`，未触发“B 反对且未盈利”退出；最终止损 `-11,908.72`。这是真假突破识别应继续优化的样本。
- `301666 大普微-UW`：入场 `A_MAIN + allow`，动量极强，入场当日最大浮盈 `+12.28%`；次日首次 B veto 时仍盈利 `+7.35%`，按“盈利仓不因 B veto 砍掉”被保留，之后回撤到止损 `-12,269.11`。它不是入场拦截问题，而是利润保护/高位回撤保护问题。
- `603115 海星股份`：入场 `A_MAIN + allow`，`rankPathCommitment=0.282` 但仍 allow；入场后几乎没有浮盈，次日最低曾到 `-15.27%`，最终止损 `-2,547.32`。B 全程 caution，未给 veto/exit_watch；属于“承接失败但 B 反对不足”的样本。
- `002149 西部材料`：入场 `A_MAIN + allow`，`rankPathCommitment=0.756`，入场后最大浮盈 `+3.43%`，次日转 `D_EXIT_RISK` 时亏 `-2.96%`，最终止损 `-1,369.38`。这是短线兑现失败，可能适合后续研究小幅浮盈后的回撤保护，而不是入场硬过滤。

2 个未平仓浮盈：

- `600759 ST洲际`：入场 `B_IGNITION + caution`，低可见度首段点火；最终浮盈 `+1,798.55`，仅占最终利润约 `0.6%`。期间 B veto 首次出现时已盈利 `+10.39%`，所以未触发未盈利退出。
- `603618 杭电股份`：入场 `B_IGNITION + caution`，最终浮盈 `+30,551.90`，占最终利润约 `9.9%`。B veto 首次出现时已盈利 `+12.28%`，因此按利润奔跑原则保留。它说明 `B_IGNITION + caution` 不能硬杀，否则会误伤强趋势。

当前判断：

- 利润不是靠单票偶然，但 `+30%` 级别收益依赖大肉簇，不能引入固定止盈或过早卖出。
- 下一步不应扩大 B 入场 veto；优先研究两类退出：`301666` 这类大幅浮盈后回撤保护，以及 `000070/603115` 这类入场后次日已转弱但 B 只 caution 的假突破升级条件。

### Phase 35 Max holding bars 40 rerun

结论先行：把当前 fusion 策略的 `maxHoldingBars` 从 `30` 改成 `40` 后，结果显著变差，不能采用。`40 bars` 不是简单“多拿 10 个 bar 多吃利润”，而是改变了现金和仓位路径，错过 30 bars 路径里的多只大肉，同时引入新的大止损和未平仓浮亏。

复跑口径：

- `run_id=bt_6f2909499d3e4865`
- `fresh_rerun_id=bt_7f4b3d2472d64629`
- `dataset_id=dragonboard_live`
- `snapshot_type=half_hour`
- `strategy_name=ranktrend_early_big_move_v3_lifecycle_fusion`
- `window=2026-04-01~2026-05-31`
- `executionMode=current_bar`
- `maxHoldingBars=40`
- `stopLossPct=0.05`
- `takeProfitPct=9.99`
- `volumeParticipationRate=0.1`

结果对比：

| maxHoldingBars | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown | stops | B exits | openPositions |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `30` | `bt_682d3abc164d4177` | `+31.00%` | `+27.74%` | `65.79%` | 38 | `-3.19%` | 4 | 6 | 2 |
| `40` | `bt_6f2909499d3e4865` | `+11.87%` | `+12.47%` | `53.85%` | 26 | `-4.32%` | 4 | 5 | 5 |
| `40` fresh rerun | `bt_7f4b3d2472d64629` | `+11.87%` | `+12.47%` | `53.85%` | 26 | `-4.32%` | 4 | 5 | 5 |

主要差异：

- 40 bars 交易数从 `38` 降到 `26`，说明持仓时间拉长后资金被旧仓位占用，错过后续机会。
- 30 bars 的多只大肉没有进入 40 bars 路径，包括 `603256 宏和科技 +52,859.93`、`688256 寒武纪 +45,295.17`、`301217 铜冠铜箔 +36,499.96`、`300308 中际旭创 +25,183.27`、`002902 铭普光磁 +11,709.78`、`002560 通达股份 +10,159.54`。
- 40 bars 虽然拿到了 `603459 红板科技 +51,234.84`，但新增 `603993 洛阳钼业` 大止损 `-25,496.02`，抵消了大量收益。
- 40 bars 未平仓 `5` 个，合计浮亏 `-6,414.99`；其中 `603993 洛阳钼业` 未平仓浮亏 `-17,675.19`。
- 成交诊断中 `skippedOrderCount=6`，全部来自 `000925 众合科技` 跌停不可卖；这是残留持仓解释之一，但不是收益下降主因。
- 新鲜复跑 `bt_7f4b3d2472d64629` 与旧 40 bars 对照指标完全一致，说明这不是单次落库偶然。

当前判断：

- `30 bars` 仍是当前主线最佳持仓上限。
- 40 bars 会牺牲换仓效率，并引发路径替换，不能作为“让利润奔跑”的直接方案。
- 后续如要延长大肉持有，应做“盈利仓条件式延长/利润保护”，而不是全局把所有仓位拉长到 40 bars。

### Phase 36 Max holding bars 25 rerun

结论先行：25 bars 明显优于 40 bars，但仍弱于 30 bars，暂不替换当前主线。它满足 `60%+` 胜率底线，但收益从 30 bars 的 `+31.00%` 降到 `+26.22%`，且止损从 `4` 笔升到 `8` 笔，说明全局缩短持仓会提高换仓频率，同时也更容易引入新的亏损路径。

复跑口径：

- `run_id=bt_1f4d5b6492b44ee7`
- `dataset_id=dragonboard_live`
- `snapshot_type=half_hour`
- `strategy_name=ranktrend_early_big_move_v3_lifecycle_fusion`
- `window=2026-04-01~2026-05-31`
- `executionMode=current_bar`
- `maxHoldingBars=25`
- `stopLossPct=0.05`
- `takeProfitPct=9.99`
- `volumeParticipationRate=0.1`

结果对比：

| maxHoldingBars | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown | stops | B exits | openPositions | unrealizedProfit |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `25` | `bt_1f4d5b6492b44ee7` | `+26.22%` | `+25.07%` | `60.47%` | 43 | `-4.01%` | 8 | 6 | 2 | `+11,179.39` |
| `30` | `bt_682d3abc164d4177` | `+31.00%` | `+27.74%` | `65.79%` | 38 | `-3.19%` | 4 | 6 | 2 | `+32,350.45` |
| `40` | `bt_7f4b3d2472d64629` | `+11.87%` | `+12.47%` | `53.85%` | 26 | `-4.32%` | 4 | 5 | 5 | `-6,414.99` |

主要差异：

- 25 bars 交易数增加到 `43`，说明缩短持仓提高了换仓频率，但新增路径质量并不稳定。
- 25 bars 保留多只大肉，包括 `301217 铜冠铜箔 +45,982.87`、`688256 寒武纪 +42,802.66`、`603459 红板科技 +34,303.36`、`603618 杭电股份 +30,678.96`。
- 25 bars 新增或放大亏损：`002929 润建股份 -26,215.32`、`301217 铜冠铜箔 -21,431.46`、`600884 杉杉股份 -8,609.42`，止损数升到 `8`。
- 25 bars 未平仓仍有 `603993 洛阳钼业 -17,675.19`，但被 `603618 杭电股份 +28,854.58` 抵消后总浮盈仍为正。

当前判断：

- 25 bars 是比 40 bars 更可用的压力测试，但不是当前最优主线。
- 30 bars 仍兼顾收益、胜率、回撤和止损数量，继续作为主线。
- 下一步不应继续盲扫持仓 bars；更值得研究的是“盈利仓条件式利润保护”和“亏损路径早识别”，避免 25 bars 这种多交易带来的新止损。

### Phase 37 Max holding bars 32/35/28 rerun

结论先行：`32/35/28 bars` 三个对照均未超过 30 bars 主线。32 bars 是三者里最接近主线的口径，胜率仍有 `64.86%`，但收益只有 `+25.33%`；35 bars 和 28 bars 同时跌破 `60%` 胜率线。当前证据进一步支持 `30 bars` 不是偶然点，而是这组参数附近收益、胜率、回撤和换仓效率的较优平衡。

复跑口径统一为：

- `dataset_id=dragonboard_live`
- `snapshot_type=half_hour`
- `strategy_name=ranktrend_early_big_move_v3_lifecycle_fusion`
- `window=2026-04-01~2026-05-31`
- `executionMode=current_bar`
- `stopLossPct=0.05`
- `takeProfitPct=9.99`
- `volumeParticipationRate=0.1`

结果对比：

| maxHoldingBars | Run ID | totalReturn | realizedReturn | winRate | trades | maxDrawdown | stops | B exits | openPositions | unrealizedProfit |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `25` | `bt_1f4d5b6492b44ee7` | `+26.22%` | `+25.07%` | `60.47%` | 43 | `-4.01%` | 8 | 6 | 2 | `+11,179.39` |
| `28` | `bt_eb657d60cbeb4b17` | `+21.15%` | `+21.15%` | `58.97%` | 39 | `-3.55%` | 5 | 5 | 0 | `0.00` |
| `30` | `bt_682d3abc164d4177` | `+31.00%` | `+27.74%` | `65.79%` | 38 | `-3.19%` | 4 | 6 | 2 | `+32,350.45` |
| `32` | `bt_d896884168dc4081` | `+25.33%` | `+23.25%` | `64.86%` | 37 | `-3.35%` | 3 | 6 | 2 | `+20,509.39` |
| `35` | `bt_ce6d1767f5fa4f0a` | `+21.29%` | `+19.48%` | `54.05%` | 37 | `-5.74%` | 6 | 7 | 4 | `+17,698.50` |
| `40` | `bt_7f4b3d2472d64629` | `+11.87%` | `+12.47%` | `53.85%` | 26 | `-4.32%` | 4 | 5 | 5 | `-6,414.99` |

主要差异：

- `32 bars` 少了一些止损，但新增 `603993 洛阳钼业 -25,496.02`，同时头部利润低于 30 bars；它接近但没有超过 30 bars。
- `35 bars` 出现 `002929 润建股份 -26,215.32`、`603993 洛阳钼业 -25,496.02`、`600330 天通股份 -13,515.71` 等大亏，胜率降到 `54.05%`。
- `28 bars` 没有未平仓浮盈，收益全部落袋，但胜率 `58.97%` 未达目标，且少吃了 30 bars 路径里的 `603256 宏和科技` 等头部收益。
- 30 bars 的优势不是单靠更长持有，而是在“留住大肉”和“不过度锁仓”之间更平衡。

当前判断：

- `30 bars` 继续作为主线。
- 不建议继续用全局 bars 参数盲扫；当前更像是退出机制的形态问题，而不是固定持仓上限问题。
- 后续重点仍应放在盈利仓利润保护、假突破早识别和路径级亏损来源，而不是把持仓上限改成另一个固定值。
