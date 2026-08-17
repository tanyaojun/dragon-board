# 四维信号长期回测计划与性能优化方案

> 状态：阶段 1-5 已落地，阶段 6（四维信号有效性研究）完成，**生命周期分层重构落地**：
> 默认策略 rank_trend_candidate 入场主轴切换为 four_dim（synergy S/A + 资金 zljzb>=0 + 非 veto），
> 交易模拟 pf>1（maxPos10 1.038）、样本外 7/7 段全胜基线（commit `8f28324`/`d60f019`）。
> 阶段 1（性能改造）已落地（commit `b4c9091`~`dce716b`），阶段 2（数据质量治理）已落地（commit `58878dc`），阶段 3（四维信号区分度诊断 + 三方向修复 + 语义校准）**验收达成**（commit `2f905b5`/`dc01019`/`40ddc7f`），阶段 4（参数搜索）**四线碰壁归档**（commit `1fb7384`/`cf73491`/`4a6a443`/`a31af1b`/`1adf47b`），验收口径调整为**胜率×盈亏比组合**，阶段 5（信号→收益映射缺口诊断）**已落地，缺口归属=退出机制（exit）**，阶段 6 待立项
> 日期：2026-08-15
> 归档位置：本文档与四份四维信号方案文档统一存入 `quant-board/docs/ranktrend-tier-backtest/`

## 0. 背景与目标

RankTrend 四维信号（共振 / 趋势 / 量价 / 周期，合并为 `synergy` 总档）的档位阈值参数化与交易门已落地（见 `ranktrend-signal-tier-backtest-plan.md`）。目标是让四维信号作为买入/卖出的重要决策依据。

**2026-08-15 目标口径调整（2026-08-15 二次修正）**：阶段 4 四线参数搜索证明参数搜索无法把绝对胜率推到 0.80——热榜排名收益强均值回归（90-99 分位桶 h1 acc 仅 0.36），追强档位（S/A）天然处于高分位；信号有相对增量（synergy S 档 excess +0.088）但未转化为交易收益（详见 §阶段 4 归档）。**主验收从"绝对胜率"改为"胜率×盈亏比组合"**（用户决策：胜率改收益不如胜率×盈亏比——保留胜率主指标地位，用 profitFactor 防紧止损刷胜率）：

```
交易层主验收：winRate × profitFactor ≥ 0.78（组合线，等价 winRate ≥ 0.60 且 pf ≥ 1.3；可随诊断校准）
信号层前置门（阶段 3 已达成，持续监测）：synergy S/A 档 excessDirectionAccuracy ≥ 0.05 且 S/A/B excess 正单调
约束：tradeCount ≥ 60 且 maxDrawdown ≤ 10%
样本外：连续两个 walk-forward 窗口 winRate × profitFactor ≥ 0.78 稳定
```

基线实况（`bt_78f14b1c814e4d90`，`rank_trend_candidate` / `next_bar`，2026-04-15~08-14）：

- 胜率 **51.96%**、102 笔、总收益 +2.69%、最大回撤 -12.57%
- 对照组：`a_main_only` 56.0%（最优）、`hot_top10` 39.1%
- 信号方向精度 **37.6%**（低于随机 50%）、样本 ok 占比仅 46%

结论：**先修地基（性能 + 数据质量 + 信号区分度），再谈调参**。否则参数搜索只在噪声上过拟合。

## 1. 现状评估

### 1.1 数据层面（MongoDB）

| 项 | 实况 |
|---|---|
| 数据存量 | `dragonboard_live` 2026-03-27 ~ 08-14（约 5 个月）；`snapshot_stock_rows` 1.65GB / 57.3 万行，`snapshot_frames` 12.1MB / 2618 帧 |
| 单行结构 | 83 字段 / 3012 字节（`themes`、`platforms` 等为大字段） |
| 索引 | 股票行 9 个 + 帧 3 个，覆盖 `datasetId+snapshotId+rank`、`code+timestamp` 等查询路径 |

**问题**：`load_frames` 用 `projection="full"` 拉全部 83 字段，但引擎实际只需约 15 字段（`code/change/volumeRatio/zlje/zljzb/price/volume/turnover/rank/avgRankNum/timestamp/tradingDate` 等）→ 传输量浪费约 5 倍。

### 1.2 计算层面（回测引擎）

| 瓶颈 | 实况 |
|---|---|
| 信号重复计算（核心） | `TrialExecutor.evaluate_phase` 的 `signal_cache` 键 = `freeze(strategy_config)`；信号层参数（macd/tier 阈值）一变键就变 → 缓存全 miss → 每 trial 全量 `replay`（逐帧逐股票跑 `_build_signal` 全链纯 Python） |
| 单线程 | `jobs.py` 为 `ThreadPoolExecutor(max_workers=1)`；`replay` 是 CPU 密集，GIL 下多线程无加速 |
| 无中间缓存 | 帧、信号、中间量不跨运行复用，无 Redis |
| 无游标分批 | `_stock_rows_by_snapshot` 一次拉全窗口股票行 |

### 1.3 结论

当前架构**能跑单次回测，但无法支撑长期参数搜索**：24 trials ≈ 48 次全量 replay（1–4 小时），叠加 walk-forward 多段与周度滚动，几周即算不动且反复压库。

## 2. 性能优化方案（三层组合，分层落地）

### 2.1 方案 A — 数据访问层瘦身（最小，最先）

- `load_frames` 增加**字段白名单 projection**（只拉引擎需要的 ~15 字段），替代 `projection="full"`。**已落地**：`BACKTEST_RANKTREND_STOCK_FIELDS`（`backend/services/shared.py`）+ `load_frames(fields=...)`（`backend/data/repositories/mongo_repository.py`）+ 优化链路传参（`backend/services/optimization_service.py:293`）。
- 股票行查询改**游标分批**（`limit + batch`），避免一次全拉 57 万行到内存。**已落地**：`_stock_rows_by_snapshot` 按 `_STOCK_ROWS_BATCH_SIZE=200` 分批（`mongo_repository.py`，组内保持 rank 排序）。
- 日期过滤补全到回测服务（优化侧已做，见 `optimization_service._build_request`）。
- Mongo 连接/服务器选择超时已调大（`connect 10000ms` / `serverSelection 15000ms`）。

### 2.2 方案 B — 信号/中间量缓存（核心收益，Redis）

- **参数分组**：搜索空间参数拆成「信号层参数」（macd/tier 阈值，决定 `replay` 输出）与「交易层参数」（stopLoss/takeProfit/maxPositions，只影响撮合）。
- 交易层参数变化时**复用已算信号**（`signal_cache` 键去掉交易层参数）。**已落地（进程内）**：`_signal_cache_key`（`backend/optimization/trial.py`）键只含 `to_strategy_config` 过滤后的 `RankTrendConfig` 字段，`strategyRunCount` 可用于度量复用率；Redis 跨运行缓存为后续里程碑。
- Redis 缓存帧 + 信号（以 `config_hash` 为键），跨优化运行复用，避免每次重算。
- 中间量（动量 / 技术 / 生命周期）按参数独立性分层缓存，能复用则复用。

### 2.3 方案 C — 多进程并行（配合 B）

- `ProcessPoolExecutor` 并行跑 trial（每个 trial 独立 replay + 撮合，无共享状态）。
- 进程数 = 可用 CPU 核数（如 4–8）。
- trial 结果聚合回主进程写库。

### 2.4 组合收益预估

A 减约 80% 传输 + B 让交易层 trial 秒级完成 + C 并行 → 24 trials 从 1–4 小时降到 **10–20 分钟**量级，且不再压垮 MongoDB。

## 3. 长期回测计划（四阶段，顺序推进，各有验收）

### 阶段 1：性能改造（让搜索跑得动）

落地 2.1–2.3 三层。

**验收**：同一优化任务（24 trials + walk-forward）耗时 ≤ 20 分钟，且 MongoDB 不再因反复全量拉取被压垮。

### 阶段 2：数据质量治理

**已落地（commit `58878dc`，2026-08-15）**。真实 Mongo 只读诊断（2026-04-15~08-14，869 帧 half_hour 窗口）排除三个候选根因、锁定真实根因：

- **非正价格**：15839 行 `price=0` 全部为停牌股合理数据（688836/603221/001810 连续多日 0 价），且回测链路传给 quality_gate 的行不含 `price` → 不触发 fatal。**排除**。
- **空热榜**：当前数据 0 个（快照最小 50 行/平均 224 行）；早期 4 帧空快照已由运行时过滤剔除。**排除**。
- **`moneyFlowSource` 缺失**：26.19 万行（45.6%，集中于 2026-04），但优化/回测链路 `require_formal_money_flow` 默认 False → 统计不致命。**观察项**（正式资金流强校验时需补采历史）。
- **MACD 预热不足（真实根因）**：`sampleQuality.status` 的 ok 判定用 `get_technical_min_samples`（`max(macdSlow, momentum.max+1, 30)`=34 帧，混入 MACD 预热需求）；half_hour 快照 50 帧滑动窗口 + 热榜轮动 + 跨周末断档稀释在榜帧数 → 20 个历史回测全部 `researchGrade=degraded`（ok_share 仅 46%~52%，<60% 达标线）。

修复（fail-visible，不改信号数值、不动 replay warmup）：
- ok 判定改 `get_momentum_min_samples`（`momentumPeriods.max+1`=22 帧，动量可计算门槛）；degraded(5~21)/insufficient(<5) 档不变。
- `requiredSampleCount`/`requiredTechnicalBars` 同步为 22，与判定口径一致；MACD 预热状态由 `_macd_diagnostics.hasStableObservationBars` 单独暴露（不隐藏）。
- 实现位置：`backend/analysis/ranktrend/engine.py`（`_build_signal` sample_status / `requiredSampleCount`）、`backend/core/backtest/engine.py`（`_sample_diagnostics.requiredTechnicalBars`）；新增 `tests/test_ranktrend_sample_status.py` 3 用例（TDD RED→GREEN）。

验收状态：50 帧滑动窗口模拟新口径 ok≈60.0%（达标线 60%，warmup 后实际预计更高）；全量 pytest 1518 passed、golden 信号对齐无回归。**真实回测 ok_share 验收留手动**（同阶段 1 性能验收，避免重操作压垮本机）。

### 阶段 3：四维信号区分度诊断

- 分层诊断共振/趋势/量价/周期各维的 `directionAccuracy`、tier 单调性、`tierDiscrimination`。
- 排查方向定义、阈值、权重，以及「量价涨停可交易性」等已改口径是否引入偏差。
- **验收**：各维 `directionAccuracy ≥ 0.55`、tierDiscrimination 呈正单调；否则先修信号算法，**暂停阶段 4**。

**已落地（commit `2f905b5`，2026-08-15）**。诊断工具：`tier_monotonicity.py` 扩展按维度分层
（`DIMENSION_PATHS` + `tier_forward_returns(dimension=...)` + `tier_discrimination`），
诊断脚本 `backend/operations/diagnose_tier_discrimination.py`（只读 Mongo → replay → 五维诊断，
报告 `data/reports/tier-discrimination.json`）。真实数据窗口与阶段 2 一致（2026-04-15~08-14，
**769 帧 / 156647 信号**，half_hour），horizon 1/3/8：

| 维度 | S/A/B 方向精度 (h1) | sMinusC (h1) | 单调性 (h1) | 结构问题 |
|---|---|---|---|---|
| 共振 resonance | 无样本（全部 unknown） | None | 不可评 | **replay 链路 100% 缺共振维**（`_build_signal` 不调 `analyze_rank_resonance`，缺横截面 median → 缺票 vote=0） |
| 趋势 rankTrend | S 0.468 / A 0.445 | +0.0092 | spearman 0.8 但 B<C 反转 | S/A 精度 < 0.5；**D 档（卖出）未来收益为正**（h3 +0.016 / h8 +0.035，acc 0.52~0.55）→ 热榜排名均值回归主导 |
| 量价 volumePrice | A 0.416 | None（无 S 档） | spearman −0.5 | **状态机无 S 档**（最高 A）；unknown 15.7% |
| 周期 lifecycle | A 0.444 | None（无 S 档） | h1 −1.0 / h3+ 正（仅 A/B 两档） | **无 S/C 档**；A（优选）收益为负 −0.0097 |
| 合并 synergy | S 0.468（A 档 n=0） | **−0.0054（负区分度）** | spearman −0.5 | **S 收益 −0.0056 < B +0.0022，档位序反向**；A 档不可达（`_synergy_tier` 投票需 v≥2 且 lc∉{A,B,D}，而周期只有 A/B/D/E → A 分支永远落空，全被降档/否决） |

**验收判定：FAIL**——按原始验收线（各维 directionAccuracy≥0.55、tierDiscrimination 正单调），五维全部未达标
（方向精度 0.36~0.49）。**按计划暂停阶段 4，先修信号算法。**

**重要补充——均值回归基准（2026-08-15，同窗口 769 帧）**：对"当前排名百分位"分桶（0-9…90-99）统计未来
percentileDelta（不加任何信号），热榜排名收益存在**强均值回归**：

| 当前分位桶 | h1 mean / acc | h3 mean / acc | h8 mean / acc |
|---|---|---|---|
| 0-9（垫底） | +0.062 / 0.58 | +0.121 / 0.73 | +0.194 / 0.84 |
| 40-49 | −0.010 / 0.41 | −0.008 / 0.47 | +0.007 / 0.49 |
| 90-99（榜首） | −0.012 / 0.36 | −0.034 / 0.33 | −0.077 / 0.27 |

含义：**"追强"档位（S/A）天然处于高分位，其原始 directionAccuracy 会被均值回归基线拉低到 0.5 以下**——
原始验收线对强信号不可达。对照同分位基准：趋势维 S 档 acc 0.468 vs 90-99 分位基线 0.363（h1），
**高出约 10 个百分点 → 信号在控制分位后仍有正增量信息**，不能据此断言信号无效。
真正的结构问题见 §5.1（共振维缺失 / 档位分布畸形 / 评估口径未条件化）。

### 阶段 4：参数搜索 + 样本外验证 + 滚动迭代

- 4.1 交易层参数粗搜（random，win_rate + 盈亏比约束）。
- 4.2 信号层参数精搜（tpe/bayesian，围绕粗搜 best 缩窄空间）。
- 4.3 walk-forward 滚动复核 + 固定样本外窗口裁决。
- 4.4 周度滚动：新样本入库 → 重跑 → 监控参数漂移。

**阶段 4 前置能力（commit `be2cd05`，2026-08-15）**：
- `TradeSimulator` 输出 `profitFactor`（盈亏比 = 盈利/亏损总额，`execution.py _profit_factor`；
  无交易/无亏损 → None 不伪造，fail-visible），`BacktestEngine` metrics 透传。
- objective 新增 `win_rate_pf`（阶段 4.1 目标：winRate 主 + profitFactor 约束——<1.0 罚 0.2、
  <1.3 罚 0.1，压制紧止损刷胜率；tradeCount<30 温和惩罚，验收线 60 由报告筛选）。
- 链路验证：8 trials random 交易层粗搜（train 2026-05-15~07-15，tier_risk_adjusted）全部完成
  0 failed（阶段 3 改动后 replay 带共振 + tierStats 注入正常）；发现交易层搜索下
  `tierConstraintFailed` 恒定（tierStats 不受交易参数影响，属信号层约束）→ 4.1 改用 `win_rate_pf`。

**阶段 4.1 交易层粗搜（commit `1fb7384`，2026-08-15）**：random 20 trials + 基线对照
（train 2026-05-15~07-15 / validation chronological 0.3 / objective `win_rate_pf`），
run_id：基线 `opt_a1fdd46851254991`、搜索 `opt_34a91f83279f4988`：

| 指标 | 基线（默认） | best（20 trials） |
|---|---|---|
| win_rate_pf score | 0.2286 | **0.4441**（+94%） |
| winRate | 0.4286 | **0.5441**（+11.5pp） |
| tradeCount | 112 | 68（≥60 ✓） |
| totalReturn | −0.1296 | **+0.006**（转正） |
| maxDrawdown | −0.1622 | **−0.096**（减半） |
| 参数 | 默认 | maxPositions=3, stopLoss=−0.08, takeProfit=0.16, **synergyEntryTierMin="a"**, synergyExitOnDanger=true |

**发现**：
1. **synergyEntryTierMin="a"（S/A 入场门）是最大区分因子**：top 12 trials 全为 "a"，
   "a" 组 winRate 0.48~0.54 vs "none" 组 0.41~0.46 → 阶段 3 的 synergy S/A 档位有真实交易价值；
2. **maxPositions=3（集中持仓）显著降回撤**：3 仓 dd −0.10 / 5 仓 −0.14~−0.17 / 8 仓 −0.18~−0.21；
3. best 组合 totalReturn 转正、回撤减半，**显著优于基线**（win_rate_pf 提升 94%）。
未达最终验收（winRate 0.80 / profitFactor 1.3）——交易层参数只能改交易结构，信号质量提升需
4.2 信号层精搜；best 参数仅候选，不自动写回默认值（硬约束）。

（trial metrics 补 profitFactor 透传：commit `1fb7384`）

**阶段 4.2 信号层粗搜（commit 待补，2026-08-15）**：20 trials optuna_tpe（固定 4.1 best 交易层，
搜索 8 信号层阈值），run_id：基线 `opt_280e332857a046e1`、搜索 `opt_880147e7ea2b40b4`，
耗时 55.6 分钟（信号层参数变化 → signal_cache 不命中 → 每次 trial 全量 replay ~90-115s）。

**结论：信号层阈值在现有 vote 语义下无优化空间（默认即最优）**。逐层排查证据：
1. 20 trials 中 16 个（VoteStrong=2）交易/score 完全相同（68/0.5441，score -0.6346），
   仅 VoteStrong=3 的 4 个不同但更差（65/0.5231，score -0.87）；
2. `TrialExecutor.evaluate` 链路正常（A 组 68 笔 vs B 组 65 笔，signal_cache 正确区分）；
3. **根因**：`_synergy_tier`（`volume_price.py:260-269`）vote 只取各维度 direction（buy/sell ±1），
   **忽略 signalTier 档位** → tierResonance*/tierRankTrend* 阈值只改单维档位标签不改 vote；
4. 单维敏感性分析（min/max 边界，15 次 replay）证实：
   - 6 个共振/趋势阈值参数变化率 **0.0**（完全无效）；
   - `tierSynergyVoteReverse` -1→0 改档位分布（D 35295→51286，变化率 0.41）但**不影响交易**
     （D/C 均不入 S/A 入场门）；
   - `tierSynergyVoteStrong` 2→3 影响交易但**变差**（67→64，pf 1.3171→0.9975，winRate 0.5672→0.5312）。

**后续可选**（不阻塞阶段 4）：提升信号区分度的方向是改 vote 语义（S/A 档强度加权投票），
属策略语义变更（触碰 golden 算法），需独立 TDD + 文档 + golden 对比，另行立项。

**阶段 4.3 walk-forward 复核（commit 待补，2026-08-15）**：验证 4.1 best 组合
（maxPositions=3/stopLoss=-0.08/takeProfit=0.16/synergyEntryTierMin="a"/synergyExitOnDanger=true），
全窗口 2026-04-15~08-14，run_id：`opt_a072e2268ce34f43`（walk_forward：train 30 交易日 / val 10 / step 10 / top_trials=1，耗时 636s）：

| 段 | validation 窗口 | trades | winRate | pf | ret |
|---|---|---|---|---|---|
| seg1 | 06-01~06-12 | 22 | 0.4545 | 0.56 | −0.082 |
| seg2 | 06-15~06-29 | 22 | **0.6818** | 1.76 | +0.050 |
| seg3 | 06-30~07-15 | 15 | 0.4000 | 0.17 | −0.073 |
| seg4 | 07-16~07-30 | 5 | 0.0000 | 0.00 | −0.049 |
| seg5 | 07-31~08-13 | 26 | **0.6538** | 2.78 | +0.039 |

**裁决：4.1 best 组合未通过样本外验证（不采纳）**：
- validation winRate 最高 0.6818 < 0.70 验收线；样本外胜率均值 0.438；
- 5 段仅 2 段正收益（positiveReturnSegmentRate 0.4）；seg4 仅 5 笔交易全亏（样本不足噪声大）；
- seg2/seg5 表现好（winRate 0.68/0.65、pf 1.76/2.78）→ 组合有正向窗口但整体不稳定。

**阶段 4 重启（vote v4，2026-08-15）**：vote 语义改进（`51df5bf`）后重跑 4.1/4.3，验证档位质量改进是否转化为交易收益。

**4.1 重跑**（run：基线 `opt_47a689010bb34053`、搜索 `opt_d5d982e3f2594884`）：
- 基线（synergy 门关）与旧完全一致（score 0.2286/trades 112）——vote 语义不影响门关闭状态 ✓；
- 搜索 best 参数与旧相同（maxPositions=3/stopLoss=-0.08/takeProfit=0.16/a 门/exitOnDanger），
  但 train 窗口交易略降：winRate 0.5303 vs 旧 0.5441、ret -0.0117 vs +0.006；
  pf=1.032（profitFactor 透传生效）。

**4.3 walk-forward 重跑**（run `opt_bb2a69bd18684a44`）：

| 段 | val 窗口 | trades | winRate | pf | ret | 对比旧(v0) |
|---|---|---|---|---|---|---|
| seg1 | 06-01~06-12 | 22 | 0.4545 | 0.56 | −0.082 | 同 |
| seg2 | 06-15~06-29 | 21 | **0.7143** | 1.84 | +0.052 | 0.68→**0.71**（改善） |
| seg3 | 06-30~07-15 | 13 | 0.3077 | 0.13 | −0.070 | 0.40→0.31（降） |
| seg4 | 07-16~07-30 | 3 | 0.0000 | 0.00 | −0.015 | 同（样本不足） |
| seg5 | 07-31~08-13 | 26 | 0.5769 | 2.24 | +0.023 | 0.65→0.58（略降） |

样本外胜率均值 0.41（旧 0.44）、positiveReturnSegmentRate 0.4（不变）——
**仍未过验收线**（validation winRate ≥0.70 且连续两段 ≥0.7 未达）。

**结论**：vote v4 提升档位质量（单调性 passHard=True、saEx 0.0651），但**未转化为交易收益**
（train 与 walk-forward 样本外均无显著改善）。synergy S/A 档 excess 相对分位桶为正，
但绝对收益仍受均值回归主导。4.1 best 组合**仍不采纳**（样本外不稳定）。
8000 服务需重启后前端/API 才使用 vote v4 语义。

**阶段 4 策略层改进（2026-08-15，方向 1/3/4）**：用户决策：更长时间窗口不做（性能不允许），
策略层改进才是正确方向。基于 4.2 诊断（"S/A 档相对强势 ≠ 绝对盈利，均值回归主导入场后回落"），
选定三个 trade 层改进方向并 TDD 落地（全部**默认关闭**，行为与现状一致）：

| 方向 | 配置键（默认） | 行为 |
|---|---|---|
| 1 入场时机 | `entryMomentumConfirm: "off"` | `"short_positive"`：A_MAIN 入场要求 `momentum.short > 0` |
| 3 止损结构 | `useAtrStops: False`、`atrStopMultiplier: 2.0`、`atrTakeMultiplier: 3.0` | 止损/止盈价 = entry ∓ 倍数×ATR(14)，缺 K 线历史时回退固定 %（fail-visible） |
| 3 止损结构 | `breakevenTrailing: False`、`breakevenThreshold: 0.02` | 盈利达阈值后止损上移至入场价（粘性，pos.breakevenActivated） |
| 4 档位联动 | `tierPositionScale: False`、`tierPositionScales: {S:1.0, A:1.0, B:0.5}` | 按 synergy 档位缩放入场仓位 |
| 4 档位联动 | `synergyExitOnDowngrade: False`、`synergyDowngradeSteps: 2` | 持仓档位相对入场降 ≥2 档退出 |

实现：`backend/core/backtest/config.py`（DEFAULT_TRADE_CONFIG 新键）+ `execution.py`
（`_entry_momentum_confirmed` / `_exit_prices` / `_atr_of` / `_tier_downgrade_steps` /
`_synergy_downgrade_exit`，run() 维护个股 K 线历史供 ATR 计算）；
测试 `tests/test_trade_simulator_entry_refinements.py`（12 用例，含默认关闭回归）。
全量 pytest **1551 passed**。

**开关 grid 主效应（门关 + maxPositions=5 基线，32 组合，run `opt_65fd17fc603f46c5`）**：
entryMomentumConfirm / useAtrStops / breakevenTrailing on=off 无差异（A_MAIN 本就要求短周期动量正；
数据缺 high/low 时 ATR 回退固定 %）；tierPositionScale +0.005 边际正；synergyExitOnDowngrade
−0.02 负效应（过早退出减损）。开关效果需配合 synergy `a` 门验证（4.1 best 前提）。

**网页端可操作性（用户要求）**：原前端 `OptimizationRequest.parameterGrid` 是固定白名单
（momentumPeriods/minJumpConfidence/takeProfitPct/stopLossPct/maxPositions/macd），synergy 门与
新开关网页端均不可配（此前只能脚本硬编码）。后端 `search_space`/`parameterGrid` 自由透传
（`optimization_service._build_request` 不校验白名单），前端为唯一瓶颈。后续落地：
types.ts 扩展 parameterGrid + App.vue 优化表单"交易策略开关"折叠块 + objective 加 `win_rate_pf`。

**网页端可配置能力落地（2026-08-15，commit 后补）**：

- `frontend/src/types.ts`：`OptimizationRequest.objective` 加 `win_rate_pf`；
  `parameterGrid` 加 10 个可选键（synergyEntryTierMin/synergyExitOnDanger/entryMomentumConfirm/
  useAtrStops/atrStopMultiplier/atrTakeMultiplier/breakevenTrailing/breakevenThreshold/
  tierPositionScale/synergyExitOnDowngrade/synergyDowngradeSteps）。
- `frontend/src/App.vue`：优化表单新增"交易策略开关"折叠块（11 个控件，逗号分隔候选、
  留空=不参与搜索，与现有 takeProfitPct 等输入风格一致）；objective 下拉加"胜率×盈亏比"；
  新增 `parseStringList`/`parseBoolList` 解析。`styles.css` 加 `.adv-params` 折叠块样式。
- `backend/core/backtest/execution.py`：新增 `_config_bool` 统一布尔解析（容忍 bool 与
  `"true"/"1"/"yes"/"on"` 字符串——前端 search_space 提交字符串数组），替换 5 处开关读取；
  测试 +2（字符串形态），全量 pytest **1553 passed**。前端 `npm run build` 通过。
- **效果**：不再硬编码——网页端可直接配置 synergy 门与全部新开关并搜索，后端自由透传。

**开关×a门协同搜索结论（run `opt_ca96af636c814f94`，4.1 best + 5 开关 grid 32）**：
32 组合 **score 全部 0.4303 / winRate 0.5303 / trades 66，完全无差异**。原因：
A_MAIN 分层已含短周期动量约束（`tierAMainShortMomentumMin=-2.0`），`short>0` 不过滤任何入场；
`synergyExitOnDanger`（D/E 强制退出）已覆盖 S/A 持仓降级场景；`dragonboard_live` 缺
high/low K 线（ATR 回退固定 %）；`win_rate_pf` 目标下仓位缩放不改变胜率、保本触发稀疏。
**结论：trade 层开关在当前数据/目标下无增量（保持默认关闭不污染现状），
瓶颈仍在选股/信号层（均值回归主导）**。后续提升路径：A_MAIN 入场条件本身（信号层）、
补齐 high/low 数据后重验 ATR 止损、或大盘 regime 过滤（方向 2，需指数数据确认）。

**验收（2026-08-15 更新）**：阶段 4 原验收线（绝对 winRate ≥ 0.80）已被四线搜索证据推翻，不再作为硬性验收；主验收口径见第 0 节（**胜率×盈亏比组合**，winRate × profitFactor ≥ 0.78）。阶段 4 结论：**参数搜索在固定信号结构 + 固定目标口径下无提升空间，瓶颈在选股/信号层（均值回归主导），转入阶段 5 诊断。**

### 阶段 5：信号→收益映射缺口诊断（2026-08-15 用户决策新增）

**动机**：阶段 3 证明 synergy S/A 档有正 excess（相对同分位基准），阶段 4 证明该 excess **未转化为交易收益**（vote v4 重跑 train 与样本外均无显著改善）。先回答"S/A 档 excess 为什么不赚钱"，再决定下一阶段主攻方向，避免继续在错误层上投入。

**诊断内容（只读，不改信号数值、不动默认参数）**：

1. **入场后收益分布拆解**：S/A 档信号触发后 1/3/8 horizon 的收益分布（mean/median/分位数/亏损占比），对照同分位桶未入场样本——区分"入场后整体回落（均值回归主导）"与"尾部亏损吞噬利润"。
2. **分位桶条件化**：S/A 档触发时股票当前排名分位桶分布，及各分位桶下入场后收益差异——验证"追强入场被均值回归吃掉"假设。
3. **与 A_MAIN 候选重叠度**：synergy S/A 档信号 ∩ A_MAIN 入场集合的 Jaccard 重叠；A_MAIN 实际入场股票中 S/A 档占比——定位信号到交易之间的损耗环节。
4. **退出机制检验**：若入场后 horizon 收益为正而交易收益为负 → 缺口在退出（止损/止盈/降档退出过早吞利润）；若入场后 horizon 收益本身为负 → 缺口在入场时机（选股/均值回归）。
5. **判定规则**：产出诊断报告（`data/reports/signal-to-return-gap.json`），明确缺口归属（入场 / 退出 / 两者），作为阶段 6 立项依据。

**验收**：诊断报告产出 + 缺口归属结论明确（入场 / 退出 / 两者）；不改变任何信号数值与默认参数，全量 pytest 保持绿。

**已落地（commit 待补，2026-08-15）**。实现 `backend/analysis/ranktrend/signal_return_gap.py`（纯函数：
`horizon_price_return_stats` / `sa_bucket_distribution` / `sa_vs_amain_overlap` / `assess_gap`）+
`backend/operations/diagnose_signal_return_gap.py`（只读诊断脚本，复用阶段 3 的 Mongo 加载/replay 链路，
另接一次默认配置 TradeSimulator 取 S/A 档入场净收益对照）；测试 `tests/test_signal_return_gap.py`
11 用例（TDD RED→GREEN，含 rank 超界占位修复的 fail-visible 用例）。全量 pytest 1564 passed。

**真实诊断（769 帧 / 156647 信号，2026-04-15~08-14，half_hour，报告 `data/reports/signal-to-return-gap.json`）**：

| 项 | 结果 | 解读 |
|---|---|---|
| S/A 档 h1/h3 价格收益 | median=0.0，winRate 0.371~0.416 | 短期（1-3 帧）追强无优势，均值回归主导（与阶段 3 一致） |
| S/A 档 h8 价格收益 | median **+0.0028**，winRate **0.5272** vs control 0.5073 | **8 帧后信号方向正确**（winRate 超 control +2pp） |
| 分位桶分布 | S/A 档集中桶 6-9（995/1079/1038/868） | 追强确实集中高分位，印证均值回归假设 |
| S/A ∩ A_MAIN 重叠 | Jaccard **0.60**，saShareInAmain **0.90**，amainShareInSa 0.65 | A_MAIN 入场 90% 是 S/A 档（入场在追强）；S/A 档仅 65% 进 A_MAIN 候选 |
| 默认配置交易（S/A 入场 97 笔） | netReturn median **−0.0095**，winRate **0.3711** | 交易执行把 h8 的正信号收益吞掉了 |

**缺口归属判定：exit（退出机制吞利润）**——S/A 档信号在 8 帧 horizon 有正方向信息
（winRate 0.5272 vs 交易 0.3711，差 15.6pp），但默认交易配置（stopLoss −0.06 / takeProfit 0.12 /
maxHoldingBars 等退出路径）在收益兑现前打断持仓。h1/h3 无优势说明**入场后 1-3 帧均值回归吃掉短期收益**，
真正的问题不是"入场错了"，而是**持有时间不足以等到 h8 的正期望兑现，且退出路径过早截断**。

### 阶段 6（候选，待用户决策立项）

基于阶段 5 缺口归属（exit），候选方向：

1. **延长持有/退出结构重估**：h8 收益为正说明 8 帧是正期望窗口，maxHoldingBars/止盈过早截断；
   对比"8 帧强制持有"vs 当前退出路径的收益差（需确认 T+1 与流动性约束下可执行性）。
2. **退出触发条件去噪**：D_EXIT_RISK / 降档退出在均值回归 h1-h3 窗口内触发过多，可验证
   "持仓 ≥N 帧后才允许 synergy 降档退出"（当前 `synergyExitOnDowngrade` 默认关闭，grid 曾证无增量——
   需结合 h8 正期望重新校准）。
3. **入场时机叠加分位条件**：h1-h3 无优势而 h8 有优势 → 若叠加"低分位桶入场"或"入场后先忍 3 帧"，
   可能提高绝对胜率；与阶段 4 的 excess 口径诊断联动。
4. **补齐 high/low 数据后重验 ATR 止损**：ATR 止损在缺 high/low 时回退固定 %，重验后才算完整退出结构。

**阶段 6 立项量化已完成（commit `405e776` 之后追加，2026-08-15，报告 `data/reports/exit-holding-research.json`）**：

给 TradeSimulator 新增 `minHoldingBars`（最小持有帧数，默认 0 不改变行为，容忍字符串/负数形态；
`backend/core/backtest/config.py` / `execution.py` / 测试 5 用例），跑真实数据对比三组退出结构
（769 帧 / 156647 信号，S/A 档入场口径与阶段 5 一致）：

| 变体 | S/A 入场 | winRate | profitFactor | winRate×pf | median 净收益 |
|---|---|---|---|---|---|
| baseline（现状，min=0） | 97 | 0.3711 | 0.8066 | **0.2993** | −0.0095 |
| min8（强制持有 8 帧） | 87 | 0.4023 | 0.6227 | **0.2505** | −0.0094 |
| min8_wide_stop（+止损放宽 −0.12） | 87 | 0.4023 | 0.6003 | **0.2415** | −0.0094 |

**结论：延长持有被证伪。** minHoldingBars=8 确实让 winRate 升 3.12pp（与 h8 horizon 正期望一致），
但强制持有的"硬扛"放大单笔亏损，profitFactor 从 0.8066 跌到 0.6227，**组合线 winRate×pf 反而
从 0.2993 降到 0.2505**。baseline 退出原因分布显示信号驱动退出占绝对主导：
`D_EXIT_RISK` 38 笔 + `compose_decision 卖出信号` 28 笔 + `排名跌出前50` 19 笔 = 85/97（88%），
价格止损/止盈合计仅 9 笔。**真正的缺口是"信号驱动退出太频繁"（D_EXIT_RISK / final sell / rank>50
在均值回归震荡窗口内把持仓过早踢出），不是止损太紧、也不是持有太短。**

因此阶段 6 候选方向权重更新（用户决策立项前）：
- **方向 2（信号驱动退出去噪）权重最高**——直击 88% 退出原因；可研究"持仓 ≥N 帧后才允许
  D_EXIT_RISK / final sell 退出"（minHoldingBars 已实现，可直接验证）；
- 方向 1（延长持有）**降权**——本轮量化证明 winRate×pf 恶化，除非与去噪组合；
- 方向 3 / 4 保持候选（分位入场、ATR 重验），但优先级低于方向 2。

阶段 6 立项需用户决策方向；验收走第 4 节胜率×盈亏比组合线（winRate×pf ≥ 0.78）。

**阶段 6 方向 2 已实现并量化（commit `9e02a85` 之后追加，2026-08-15）**：

实现 `signalExitDelayBars`（信号驱动退出去噪，默认 0 不改变行为，`backend/core/backtest/config.py` /
`execution.py`：退出判定拆分为 price_exit（止损/止盈/maxHoldingBars 立即生效，保留风控）与
signal_exit（D_EXIT_RISK / final sell / C_CROWDED 转弱 / rank>50 / synergy 风控，可延迟））+ 6 测试用例。
真实数据量化（769 帧 / 156647 信号，S/A 档入场口径）：

| 变体 | S/A 入场 | winRate | profitFactor | winRate×pf | median 净收益 |
|---|---|---|---|---|---|
| baseline | 97 | 0.3711 | 0.8066 | **0.2993** | −0.0095 |
| denoise8（方向2） | 88 | 0.3977 | 0.6178 | **0.2457** | −0.0094 |
| denoise8_wide_stop | 87 | 0.4023 | 0.6020 | **0.2422** | −0.0094 |

**结论：方向 2（信号驱动退出去噪）量化证伪**——denoise8 与 min8 效果几乎一致（winRate +2.7pp 但
pf 从 0.81 跌到 0.62，winRate×pf 从 0.2993 恶化到 0.2457）。**退出时机（早/晚）不是瓶颈**：
无论延迟全部退出还是只延迟信号驱动退出，S/A 档入场的 winRate×pf 都稳定在 0.24~0.30 区间。

**新发现（入场子集 vs 全量 S/A 档的 h8 差异）**：全量 S/A 档 h8 收益为正（4590 样本，median
+0.0028、winRate 0.5272 > control 0.5073，阶段 5 结论），但**实际入场的 97 笔 h8 收益接近零/略负**
（93 样本，median −0.0020、winRate 0.4839 < control 0.5073）。两处含义：
1. A_MAIN 入场筛选（regime 非 weak + final buy + 动量确认）可能选出的子集不在 S/A 档正期望内——
   "入场筛选偏差"而非"退出过早"；样本量小（93 笔）需更大窗口/更多数据集复核；
2. S/A 档 h8 正期望本身微弱（+0.28pp median），双边交易成本约 0.36%（fee+stamp+slippage）
   即可吃平——**信号优势薄 + 交易成本**可能是更根本的瓶颈。

方向 2 实现（signalExitDelayBars）保留为研究开关（默认关闭不改变行为），后续如需复核
"入场子集 h8 负期望"或与其他方向组合可复用。

**阶段 6 综合评估：生命周期分层策略 vs RankTrend 分析方法匹配度（commit 待补，2026-08-15，
报告 `data/reports/strategy-signal-fit.json`）**：

用户提出"A_MAIN 入场条件只是其中一环，策略到底匹不匹配 RankTrend 分析方法，要综合评估"。
实现 `backend/analysis/ranktrend/strategy_signal_fit.py`（纯函数：`tier_distribution_by_candidate` /
`amain_funnel_by_regime` / `entered_vs_unentered`，6 测试）+ `backend/operations/evaluate_strategy_signal_fit.py`
（只读综合评估），逐环节拆解漏斗：synergy S/A 档 → candidateTier 分层 → regime 过滤 → 实际入场。

**真实数据（769 帧 / 156647 信号，h8 价格收益，S/A 档口径，winRate 为 h8 方向胜率）**：

| 环节 | 子集 | 样本 | winRate | winRateDelta vs S/A 基线(0.5272) |
|---|---|---|---|---|
| 分层 | A_MAIN（入场档） | 967 | 0.5140 | **−0.0132** |
| 分层 | B_IGNITION | 1040 | 0.5308 | +0.0036 |
| 分层 | C_CROWDED | 496 | 0.4899 | −0.0373 |
| 分层 | D_EXIT_RISK（风控档） | 155 | **0.6065** | **+0.0793** |
| 分层 | N_NEUTRAL | 1932 | 0.5352 | +0.0080 |
| regime | A_MAIN 内 strong | 245 | **0.6041** | **+0.0901** |
| regime | A_MAIN 内 normal | 722 | 0.4834 | **−0.0306** |
| 执行 | A_MAIN 实际入场 | 85 | 0.4706 | **−0.0475**（vs 未入场 0.5181） |
| 档位 | A_MAIN 内 S 档 / A 档 | 386/581 | 0.513/0.515 | 几乎无差异 |

**综合结论：生命周期分层策略与 RankTrend 分析方法存在结构性不匹配**：

1. **分层方向与信号收益背离**：被判定"退出风险"的 D_EXIT_RISK 档 h8 收益最高（winRate 0.6065，
   +7.9pp），被判定"入场"的 A_MAIN 档反而低于 S/A 基线（−1.3pp）。生命周期分层（stage 驱动的
   reversal/cooling/crowded/expansion/ignition 判定）与"未来 8 帧哪个方向赚"的 RankTrend 信号
   没有对齐——D_EXIT_RISK 高收益可能是低分位均值回归，但至少证明**当前分层把强弱信号分反了**。
2. **regime 过滤方向正确但阈值偏低**：A_MAIN 内 strong 环境 h8 winRate 0.6041（+9pp 超额），
   normal 环境 0.4834（−3.1pp）；A_MAIN 候选 75%（722/967）落在 normal，负超额拖累整体。
   → "A_MAIN 仅限 strong/高分 regime"可能是首个可落地的改进，但需样本外复核。
3. **执行环节系统性损耗**：A_MAIN 内实际入场（85 笔）h8 winRate 0.4706，显著低于未入场
   （882 笔）0.5181（−4.8pp）。入场排序（按 confidence 降序 + maxPositions 资金约束）选出的
   子集方向更差——confidence 高 ≠ 未来收益高，**排序依据需要重估**。
4. **A_MAIN 内 S/A 档位无区分度**：S 档 0.513 vs A 档 0.515，几乎相同——档位强度没有转化为
   A_MAIN 内部的差异化，分层只用了 lifecycle 维度，synergy 档位没有参与 A_MAIN 内排序。

**下一步（待用户决策）**：
- 候选 A：A_MAIN 入场加 regime 强过滤（strong 才入场，normal 降级）——证据最强（+9pp 超额），
  但 n=245 需样本外验证；
- 候选 B：重估入场排序（弃 confidence，改用 regime×synergy 联合分或 h8 期望代理）——直击
  执行环节 −4.8pp 损耗；
- 候选 C：重构分层语义（验证 D_EXIT_RISK 高收益是否为均值回归，A_MAIN 档与生命周期判定
  是否应引入 synergy 档位）——工作量大，属算法层重设计；
- 候选 D：接受"信号优势薄 + 执行损耗"结论，暂停交易层研究。

**阶段 6 业务口径决策（2026-08-15，用户确认，不改代码）**：

用户判断（与数据一致）：**A_MAIN 入场基本都是高位出货——市场注意力已高度集中，不能作为买点；
四维信号（synergy）不能作为分层策略的投票源，只能作为观察信号。**

高位出货特征画像（真实数据，报告 `data/reports/amain-high-position-profile.json`，
h8 = 未来 8 帧价格收益 median）：

| 分层 | 触发时当日涨幅 | 排名分位 | 资金占比 zljzb | h8 收益 median |
|---|---|---|---|---|
| A_MAIN | **+5.94%**（全场最高） | 83.5 | **5.54**（注意力高度集中） | ≈0（追进去 8 帧不赚） |
| B_IGNITION | +2.70% | 59.0 | 1.72 | ≈0 |
| C_CROWDED | +3.38% | **93.0**（最高分位） | 1.23 | 0 |
| D_EXIT_RISK | +0.11% | 38.6（低分位） | 0 | **+0.0025**（全场最高，低位均值回归） |
| N_NEUTRAL | +0.89% | 56.2 | 0 | 0 |

**结论与后续口径**（本轮只固化，不改运行代码；如需落地改代码需另行立项）：
1. A_MAIN 触发 = 高位出货形态（当日大涨 + 高分位 + 资金集中），追进去 h8 收益归零——**不作为买点**；
2. synergy 四维信号目前代码层面仅产出到 `observation.synergy`（观察），A_MAIN 判定用
   "expansion 阶段 + 动量确认"——**追强买点与 RankTrend 方法不匹配**；四维信号保持观察信号，
   不参与分层投票/入场决策；
3. 候选新买点方向（未验证）：D_EXIT_RISK 低位均值回归（h8 +0.25pp，全场最高）提示
   "低分位反转入场"可能是唯一有正期望的方向，需另行探索验证；
4. 评估脚本 `evaluate_strategy_signal_fit.py` / 画像脚本可重复运行，供后续立项复核。

**阶段 6 趋势反转层落地（commit `f3ae177`，2026-08-15，用户决策实施）**：

**A_MAIN 降级观察档（已实施）**：
- `compose_strategy` / `compose_analysis_candidate_tier`：A_MAIN action 从 focus 降为 **watch**（观察档）；
- 默认策略 `rank_trend_candidate` 不再自动入场 A_MAIN（高位出货不作买点）；
- 对照组策略 `a_main_only` / `a_b_combined` 显式保留 A_MAIN 入场供研究对比；
- 题材引擎独立信号（`theme_rotation`：rotationState=mainline/inflow）与 RankTrend 分层不同源，
  保留 A_MAIN/B_IGNITION 入场（不随降级）；
- 受影响测试同步（entry_refinements/synergy_gate 改 a_b_combined、backtest_core/money_flow 改
  a_main_only 断言），全量 pytest 1587 passed。

**趋势反转层（新增，观察信号）**：
- `backend/analysis/ranktrend/trend_reversal.py`：`trend_reversal_of` 纯函数判定
  **低位趋势反转**（当前分位 ≤50 + 此前下行确认 + 当前 rankVelocity>0），6 测试 TDD；
- `RankTrendPythonEngine.replay` 注入 `rankTrend.trendReversal` 观察标记（分层/前端可消费）；
- **真实数据验证（769 帧，h8）：trend_reversal 判定 n=6641，winRate 0.491 < 全量 0.5082、
  无正期望** → 趋势反转层仅作观察/候选标记，**不能直接作为买点**（与研究 v2 结论一致，
  与"四维信号仅观察"口径统一）；低位反转买点需结合量价/资金/情绪进一步搜索验证。

**趋势反转 × jump 跳跃度搭配分析（commit `3e39b34`，2026-08-16，用户方向）**：
- 新分析模块 `backend/analysis/ranktrend/trend_reversal_jump.py`：trendReversal 信号按 jump 参数
  （事件方向 / 幅度 / 新鲜度 / 组合）分桶统计 h1/h3/h8 价格收益（fail-visible skipped* 计数）；
- 只读诊断脚本 `backend/operations/diagnose_trend_reversal_jump.py`，报告 `data/reports/trend-reversal-jump.json`；
- **真实数据结论（769 帧 / 9560 trendReversal）**：

| 分桶（trendReversal 子集） | h8 n | h8 winRate | h8 median |
|---|---|---|---|
| 全量 trendReversal（基线） | 6641 | 0.4910 | 0.0 |
| jump_buy（跳跃上升） | 1887 | 0.4976 | 0.0 |
| **jump_buy + 大幅（mag≥20）** | 779 | **0.5212** | **+0.0026** |
| **jump_buy + 大幅 + 新鲜（fresh≥0.5）** | 252 | **0.5278** | **+0.0022** |

- 规律：幅度是主因子（jump buy + mag≥20 首次 h8 median 转正，winRate +3.0pp）；
  新鲜度仅作增强（叠加大幅后 +3.7pp，超过 S/A 档基线 0.5272）；方向必须 buy（含 collapse 的
  0.5045 < 0.5212）。→ **"低位弱转强 + 排名跳跃(buy) + 大幅"组合可作为新买点候选**。

**trend_reversal_jump 策略接入回测（commit `4fb6fe4`，2026-08-16）**：
- 新研究策略 `trend_reversal_jump`（非默认实盘）：`_is_trend_reversal_jump_entry_signal`
  判定 trendReversal ∧ jump buy ∧ mag≥magMin 且 fresh≥freshMin；默认 magMin=20/freshMin=0
  （不改变现有行为）；retreat 退潮不入场；`SUPPORTED_STRATEGY_NAMES` 注册。
- **真实数据回测（769 帧，默认交易配置，winRate×pf 验收线 0.78）**：

| 配置 | tradeCount | winRate | profitFactor | winRate×pf |
|---|---|---|---|---|
| 默认（mag≥20） | 150 | 0.4400 | 0.8799 | 0.387 |
| fresh≥0.5 | 143 | 0.4755 | 0.9164 | 0.436 |
| **mag≥30** | 77 | **0.5455** | 0.9847 | **0.537** |
| fresh≥0.5 + mag≥30 | 54 | 0.5185 | 0.7949 | 0.412 |

- 结论：全部配置未过 0.78 验收线，与阶段 5 结论一致（**缺口在退出机制，非入场信号**）；
  但 mag≥30 使 winRate 0.44→0.5455（+10.5pp）、tradeCount 77 仍 ≥60——**信号层幅度阈值提升
  显著改善胜率，作为信号层参数候选保留**；后续若修复退出机制（阶段 6 方向 2 信号退出去噪
  已落地但默认关闭），重跑本策略验证。

**退出机制修复验证：rankExitField 配置化（commit `6fea158`，2026-08-16）**：
- 定位：trend_reversal_jump 低位入场（percentile≤50 → attention 重排序号 median=117）**入场即触发
  rank>50 退出**（signal.rank 是 avgRankNum attention 重排序号，非 compRank）；价格止损/止盈
  因此几乎无触发机会（退出原因 73/77=95% 为信号驱动：final sell 26 + D_EXIT_RISK 25 + rank>50 22）。
- 实现：engine `_build_signal` 输出补 `avgRankNum`；execution 新增 `_rank_exit_triggered` +
  `rankExitField` 配置（默认 "rank" 现状不变 / "avgranknum" 用 avgRankNum 百分位>avgRankNumExitMax），
  `_exit_reason` 透传 strategy_key；测试 +4。
- **真实数据验证（trend_reversal_jump mag≥30，769 帧）**：

| 配置 | tradeCount | winRate | pf | winRate×pf |
|---|---|---|---|---|
| rank 退出（现状） | 77 | 0.5455 | 0.9847 | **0.537** |
| avgranknum 70 | 77 | 0.5455 | 0.8851 | 0.483 |
| avgranknum 80 | 77 | 0.5325 | 0.8802 | 0.469 |
| avgranknum 90 | 77 | 0.5195 | 0.8760 | 0.455 |

- **结论：avgRankNum 绝对阈值退出被证伪**——rank>50（attention 重排"跌出前 50"）对低位弱转强是
  有效及时止损（22 笔提前离场避免更大回撤），换成 avgRankNum 绝对阈值延迟退出反而放大亏损
  （pf 0.98→0.88）。开关保留为研究工具，默认不变；**signal.rank 本身已是 avgRankNum 派生**
  （attention_rank_lookup 按 avgRankNum 重排），不存在 compRank/rank 混用问题。

**avgRankNum 相对恶化退出（commit `59610ff`，2026-08-16，用户确认方向）**：
- 按用户指示把 avgranknum 模式改为**相对恶化**：position 存入场 avgRankNum（entryAvgRankNum），
  当前 avgRankNum − 入场 avgRankNum > avgRankNumExitDelta（默认 20 个百分点）才退出
  （config `avgRankNumExitMax` → `avgRankNumExitDelta`，绝对阈值证伪归档）；测试更新 5 用例。
- **真实数据验证（trend_reversal_jump mag≥30，769 帧）**：

| 配置 | tradeCount | winRate | pf | winRate×pf |
|---|---|---|---|---|
| rank 退出（基线） | 77 | 0.5455 | 0.9847 | **0.537** |
| avgdelta 10/15/20/25/30 | 76 | 0.5526 | 0.8741 | **0.483**（全部相同） |
| avgdelta20 + delay4 | 76 | 0.5658 | 0.8704 | 0.492 |

- **结论：avgRankNum 相对恶化退出同样证伪**（delta 10~30 无区分度）——被保留的仓位最终仍经
  final sell / D_EXIT_RISK 退出但已亏更多（pf 0.98→0.87）。**"入场即触发 rank>50"的表面矛盾
  在数据上不成立**：22 笔 rank>50 退出中 21 笔同时/稍后被 final sell / D_EXIT_RISK 覆盖，
  提前退出反而减少亏损。排名止损保持 `rank>50`（attention 重排）为最优，rankExitField 开关
  保留为研究工具（默认 "rank" 不变）。

**趋势反转层语义对比研究（2026-08-16，用户提出课题：排名趋势反转 vs 档位转向）**：
三种"趋势反转"信号在真实数据（769 帧 / 156647 信号）上的 h8 价格收益对比：

| 信号 | n | median | winRate | meanPct |
|---|---|---|---|---|
| 全体基线 | 104100 | +0.0008 | 0.5076 | 58.5 |
| A. 排名拐点（现状 trend_reversal：低位+此前下行+当前回升） | 6642 | 0.0 | **0.4910** | 27.8 |
| A + jump buy | 1887 | 0.0 | 0.4976 | 28.5 |
| B. candidateTier 档位转向 D→B_IGNITION/A_MAIN | 3008 | +0.0017 | **0.5166** | 62.8 |
| B + jump | 2180 | +0.0029 | 0.5234 | 65.9 |
| **B2. candidateTier 档位转向 D→B_IGNITION（只点火）** | 2197 | +0.0021 | **0.5198** | 55.9 |
| **B2 + jump buy** | 1471 | +0.0036 | **0.5309** | 58.3 |
| C. synergy 档位转向 D/E→A/B | 5013 | +0.0027 | **0.5264** | 71.7 |
| C + jump | 4161 | +0.0025 | 0.5220 | 72.3 |
| A∧B 交集（低位 + 档位转向） | 307 | −0.0008 | 0.4691 | 34.2 |
| D_EXIT_RISK 全体（低分位持有对照） | 40459 | +0.0025 | 0.5264 | 45.6 |
| B_IGNITION 全体 | 4309 | +0.0003 | 0.5022 | 56.2 |

**核心发现（用户课题结论）**：
1. **现状"排名拐点"（A）是最差的**——低位回升拐点 h8 无正期望（winRate 0.4910 < 全体 0.5076），
   连续排名指标对低位弱转强无预测力；
2. **档位转向信号全部优于排名拐点**：B（D→B/A 买档）0.5166、C（synergy D/E→A/B）0.5264、
   **B2（D→B_IGNITION）0.5198、B2+jump 0.5309 为最优**（n=1471 样本充足）；
3. **交集 A∧B 很差（0.4691）**——"低位"（A 的核心约束）与"档位转向"（B 的核心）在语义上矛盾：
   B 的样本 meanPct=55.9（中位），A 的样本 meanPct=27.8（低位）——档位转向捕获的是
   "风险档转点火档"的中位状态跃迁，不是低位反弹；
4. **立项建议**：趋势反转层判定从"排名拐点"切换为"档位转向 D→B_IGNITION"（可配置模式），
   并叠加 jump buy 放大（0.5309）；属策略语义变更，待用户确认后 TDD 落地。

**reversalMode 开关落地（commit `85b7c9c`，2026-08-16，用户立项确认）**：
- 实现：`trend_reversal.py` 新增 `tier_shift_reversal_of`（前一帧 D_EXIT_RISK → 当前
  B_IGNITION/A_MAIN 档位转向；C_CROWDED 高位拥挤偏卖不纳入）；engine replay 跟踪
  `prev_candidate_by_code` + `meta.reversalMode`（默认 `rank_cross` 零行为变化，`tier_shift`
  用档位转向）；测试 +7。
- **真实数据交易模拟验证（trend_reversal_jump，769 帧）**：

| 配置 | tradeCount | winRate | pf | winRate×pf |
|---|---|---|---|---|
| rank_cross mag30（基线） | 77 | 0.5455 | 0.9847 | **0.537** |
| tier_shift mag25 | 79 | 0.5190 | 0.9244 | 0.480 |
| tier_shift mag30 | 77 | 0.4416 | 0.6245 | 0.276（崩） |

- **结论：tier_shift 交易模拟未优于 rank_cross**——h8 信号统计正期望（0.53 > 0.49）
  再次未转化为交易收益（双边成本 0.36% + 执行吃平），与历次信号层发现一致；
  reversalMode 保留为研究工具（默认 rank_cross），tier_shift 作观察信号有效但交易不转化。
  后续若继续，方向是降低交易成本敏感度（更长持有/更少换手），而非换信号。

**量价维度拐点信号研究（2026-08-16，用户课题：四维拐点信号溯源）**：
对照用户三维框架（共振拐点=jump、趋势拐点=零线交叉/MACD、周期拐点=D→B 档位跃迁），
研究量价维度的拐点来源（769 帧 / 156647 信号，h8 价格收益）：

| 信号 | n | median | winRate |
|---|---|---|---|
| 全体基线 | 104100 | +0.0008 | 0.5076 |
| 量价状态跃迁 fall→rise_volume | 2356 | 0.0 | 0.4987 |
| 量价状态跃迁 fall→rise_any | 4958 | +0.0017 | 0.5196 |
| 量价跃迁 + 资金负转正 | 495 | +0.0025 | 0.5414 |
| 量能突变 shrink→volume | 5948 | 0.0 | 0.4877 |
| rise_volume 全体（放量上涨状态） | 32168 | +0.0042 | 0.5374 |
| rise_volume + zljzb>0 | 21593 | +0.0052 | 0.5460 |
| rise_volume + zljzb>5 | 15791 | +0.0056 | 0.5487 |
| **rise_volume + zljzb>0 非jump** | 7905 | +0.0064 | **0.5566** |
| **全体 zljzb>5（资金净流入，不看量价）** | 30358 | +0.0063 | **0.5538** |

**结论（回答"量价拐点来自哪里"）**：
1. **量价拐点信号来自资金流向（zljzb），不是量价状态跃迁**——"下跌态→上涨态"跃迁（0.5196）
   与量能突变（0.4877）均弱于基线内有效但有限；**zljzb 资金净流入本身（>5）就是全维度最强
   信号之一（0.5538，n=30358）**，无需量价状态配合；
2. 放量上涨状态（rise_volume 0.5374）**强于跃迁**——量价维度的"状态"（动量延续）优于
   "拐点"（状态转换），与生命周期 D→B 跃迁有效的结论相反（生命周期是质变，量价是延续）；
3. **jump 对量价信号是稀释的**（rise_volume+zljzb>0 含 jump 0.5398 < 非 jump 0.5566）——
   共振拐点（jump 异动）与量价资金信号在 h8 上互斥：jump 推高追高位置（meanPct 66+），
   资金持续流入要的是低吸；
4. **四维拐点信号溯源完整映射**：共振=jump 异动（0.5119）、趋势=零线/MACD 交叉（既有）、
   周期=D→B 档位跃迁（0.5166）、量价=**资金净流入 zljzb**（0.5538 最强）；
   量价维度的"拐点"应定义为**资金流向由负转正或持续为正**（B 类信号 0.5414 / zljzb>5 0.5538），
   而非量价状态跃迁。待立项（资金因子单独成层）。

**四维拐头向下信号研究（2026-08-16，用户课题：卖出/风控拐点，h8 未来收益）**：
卖出信号有效性 = 未来 8 帧 winRate 显著 < 基线(0.5076)（预测继续下跌）：

| 信号 | n | median | winRate | 卖出有效性 |
|---|---|---|---|---|
| 全体基线 | 104100 | +0.0008 | 0.5076 | — |
| B/A→D 档位回落（跃迁） | 2155 | +0.0044 | **0.5415** | ✗ 反了（预测反弹） |
| D_EXIT_RISK 状态 | 40459 | +0.0025 | 0.5264 | ✗ 反了（低分位均值回归） |
| rise→fall 量价反转（跃迁） | 1663 | +0.0046 | **0.5400** | ✗ 反了（预测反弹） |
| **fall_volume 状态（放量下跌）** | 15006 | −0.0012 | **0.4778** | ✓ **最强卖出信号** |
| zljzb 正→负（跃迁） | 3000 | +0.0013 | 0.5117 | ✗ 无效 |
| **zljzb<0 状态** | 41589 | 0.0 | 0.4910 | ✓ 弱有效 |
| **zljzb<-5 强流出** | 27411 | 0.0 | **0.4832** | ✓ 有效 |
| jump sell | 39945 | +0.0011 | 0.5105 | ✗ 无效 |
| synergy A/B→D/E | 5422 | 0.0 | 0.4967 | ✓ 弱有效 |
| **expansion→reversal 周期回落** | 6780 | 0.0 | **0.4898** | ✓ 有效 |
| zljzb转负∧fall_volume | 653 | +0.0009 | 0.5069 | ✗ 无效 |

**结论（回答"拐头向下控回撤的点在哪里"）**：
1. **拐头向下的有效卖出信号是"持续弱势状态"，不是"高位→低位跃迁"**——fall_volume 状态
   （放量下跌 0.4778）与 zljzb<-5（资金强流出 0.4832）预测继续下跌；而 B/A→D 档位回落
   （0.5415）、rise→fall 量价反转（0.5400）**反而预测反弹**（低分位超卖均值回归）；
2. **与拐头向上不对称**：买点靠"资金流入+放量上涨"（动量延续，0.5538），卖点靠"资金强流出+
   放量下跌"（弱势延续，0.4778）——**两侧都是"状态延续"，不是"状态反转"**；"拐头"跃迁
   （D→B 除外，那是唯一的质变买点）在卖出侧全部失效；
3. **对退出机制的启示**：现有 95% 信号驱动退出中，D_EXIT_RISK 退出（25 笔）实际在低分位
   均值回归区过早离场——控回撤应改用"fall_volume 或 zljzb<-5 持续弱势状态"触发退出
   （预测继续下跌），而非"档位回落"（预测反弹）。待立项（退出触发信号改造）。

**weakStateExit 落地（commit `3c311e3`，2026-08-16，用户立项确认）**：
- 实现：engine `_build_signal` 输出补 `zljzb`；`weakStateExit=True` 时 D_EXIT_RISK 档位退出
  替换为"持续弱势状态"退出（fall_volume 或 zljzb < weakStateExitZljzb 默认 -5）；
  `_exit_reason` 同步弱势状态分支；config 加开关；测试 +4（默认关闭回归 / fall_volume 触发 /
  zljzb 强流出触发 / 阈值可配）。
- **真实数据验证（769 帧）**：

| 配置 | tradeCount | winRate | pf | winRate×pf | maxDD |
|---|---|---|---|---|---|
| rtc 默认（现状） | 99 | 0.3030 | 0.4070 | 0.123 | 0.3207 |
| rtc weakStateExit(-5) | 99 | 0.2929 | 0.3908 | 0.114 | 0.3287 |
| trj mag30 默认 | 77 | 0.5455 | 0.9847 | 0.537 | 0.1151 |
| trj mag30 weakStateExit(-5) | 77 | 0.5455 | 0.9778 | 0.533 | 0.1151 |

- **结论：weakStateExit 交易模拟无效果**（tradeCount 完全不变 99/77）——D_EXIT_RISK 档位与
  弱势状态在真实数据**同帧共现**（档位判定已含"短动量弱+风险压力"，持仓走到 D 档时通常已
  放量下跌/资金流出，两种触发同一帧，替换无差异）。开关保留为研究工具（默认关闭），
  归档结论：h8 统计上弱势状态预测下跌有效，但交易执行层面与 D_EXIT_RISK 退出等效。

**后续待办（未立项）**：
- 把 trendReversal ∧ jumpBuy ∧ mag≥20（可选 + fresh≥0.5）接入候选分层/回测验证
  （winRate×pf 验收线），若通过再决定作为入场候选；
- 趋势反转层接入分层档位（若搜索验证有正期望，再决定是否作为入场候选）；
- cycle stage 的 reversal（高位反转）与 cooling（降温）语义边界审视（阶段6 steer 记录：两者
  位置分离——reversal 分位 84.9 / cooling 39.9，不合并；缺口在 cooling 内缺"低位回升"细分层）。

## 4. 验收标准汇总

> 2026-08-15 更新（二次修正）：原绝对胜率口径（winRate ≥ 0.80 / validation ≥ 0.70 / walkForward ≥ 0.7）在均值回归主导的目标变量上不可达，已废弃；**主验收改为胜率×盈亏比组合**（用户决策：胜率改收益不如胜率×盈亏比）。

| 约束 | 达标线 | 防什么 |
|---|---|---|
| winRate × profitFactor | ≥ 0.78（主验收组合线，等价 winRate ≥ 0.60 且 pf ≥ 1.3） | 紧止损刷胜率 / 低胜率高盈亏比钻空 |
| tradeCount | ≥ 60 | 小样本刷指标 |
| 样本外 winRate×pf | 连续两个 walk-forward 窗口 ≥ 0.78 | 过拟合 |
| maxDrawdown | ≤ 10% | 高指标偶发大回撤 |
| 信号层前置门（阶段 3 已达成，持续监测） | synergy S/A 档 `excessDirectionAccuracy` ≥ 0.05 且 S/A/B excess 正单调（spearman 正、无反转） | 信号质量回落即停后续阶段 |

## 5. 关键约束与风险

1. 优化结果只产候选参数，**永不自动写回默认值**（沿用现有硬约束）。
2. 每个 trial 保留 `dataset_id/snapshot_type/strategy_version/config_hash/random_seed` 全溯源。
3. 阶段 3 若诊断出信号算法需改，先修信号，不修地基就调参是浪费算力。
4. 纯 win_rate 目标会倾向「少而精 / 紧止损」刷胜率，必须配合 profitFactor / tradeCount 约束。
5. 阶段 1 的方案 B/C 引入 Redis 与多进程，需评估部署影响（Redis 缓存已有专题文档：仓库根目录 `docs/ranktrend-redis-cache/`，含 `design.md`/`implementation-plan.md` 等）。

### 5.1 阶段 3 修复方向（验收未过，暂停阶段 4）

阶段 3 诊断结论（见上文）：按原始验收线五维方向精度全部 < 0.55、tierDiscrimination 全部非正单调；
但均值回归基准表明"追强"档位原始 acc 被高分位基线拉低，信号在控制分位后仍有正增量信息。
修复候选方向（按影响面排序，均需先做根因量化、再 TDD 小步落地、跑 golden + 全量 pytest + 重跑诊断验收）：

1. **补共振维进 replay 链路**（结构性缺失，最优先）：replay 的 `_build_signal` 不计算
   `analyze_rank_resonance`（缺横截面市场 median），synergy 实际是 3 维投票，共振维 100% 缺票。
   方案：在 replay 内按帧计算 market median / market_median_percentile（与 API 链路 `_analyze_one_stock`
   同口径），组装时传入 resonance 参与投票；golden 对齐 API 输出。这是唯一能恢复"四维"语义的修复。
2. **评估口径升级为分位条件化（方法论修正，基准已完成量化）**：排名收益强均值回归（高 90-99 分位桶
   h1 acc 仅 0.36 / h8 0.27），原始 directionAccuracy 验收线对追强档位不可达。诊断与验收改为
   **对照同分位桶基线的超额精度（excess accuracy）**：S 档 acc 0.468 vs 90-99 分位基线 0.363 → +0.105 增量。
   验收线从"abs ≥ 0.55"改为"excess ≥ 0.05 且正单调"（具体阈值随修复落地校准）。
3. **重排档位投票/降档逻辑**：synergy A 档不可达（投票需 v≥2 且 lc∉{A,B,D}，而周期只有 A/B/D/E）、
   量价无 S 档、周期无 S/C 档——S/A 强档样本量不足且语义被降档规则扭曲；修复后需重跑诊断确认
   档位分布与区分度。

验收线（修复后重跑诊断）：各维 excess accuracy（对照同分位基准）≥ 0.05 且 tierDiscrimination 正单调，
再进入阶段 4 参数搜索。

### 5.2 修复落地（commit `dc01019`，2026-08-15）

三个方向已全部实现并 TDD 落地：

1. **方向 1 — 补共振维进 replay（已完成）**：engine 层下沉横截面函数
   （`median_of` / `frame_cross_section` / `frame_market_median` / `frame_market_median_percentile`，
   自 routes 迁入），`replay` 每帧计算 market 上下文传入 `_build_signal`（assemble=True 时计算
   `analyze_rank_resonance` 写入 `rank_trend.resonance` 并参与 synergy 投票）；routes 改为 import
   engine 层函数（API 链路 assemble=False 行为不变）。顺带修复 **resonance NaN 泄漏**：
   横截面不足时 `marketMedianShortChange` 输出 None（原 NaN 导致回测严格 JSON 序列化崩溃，
   fail-visible：无效横截面标记为缺失）。
2. **方向 3 — 重排档位投票/降档逻辑（已完成）**：`_synergy_tier` 改为票数分级
   **S = v≥strong+1（高票一致）、A = v==strong（可达）**，B/D/C 语义不变、周期 B/D 降档保留；
   旧规则 `v≥strong 且 lc==A → S` 独占 S 判定，而周期只有 A/B/D/E → A 分支永远不可达（synergy A 档 n=0 根因）。
3. **方向 2 — 分位条件化评估（已完成）**：`tier_forward_returns` 记录样本当前分位桶，输出
   `excessDirectionAccuracy`（档位 acc − 同桶基线 acc）与顶层 `bucketBaselines`；诊断脚本摘要含 ex 字段。

**修复后真实诊断（769 帧 / 156647 信号，h1）**：

| 维度 | S 档 excess | A 档 excess | 结构变化 |
|---|---|---|---|
| 共振 resonance | −0.021 | −0.007 | **不再 100% unknown**（unknownRate 18.8%，S/A/B/C/D 分布齐全）|
| 趋势 rankTrend | **+0.064** ✓ | +0.037 | — |
| 量价 volumePrice | 无 S 档 | +0.013 | — |
| 周期 lifecycle | 无 S 档 | **+0.055** ✓（B +0.097 ✓） | — |
| 合并 synergy | **+0.088** ✓ | +0.039 | **A 档可达（n=7172，之前 0）** |

**修复后验收判定**：S 档 excess 达标（synergy +0.088 / rankTrend +0.064 / lifecycle A+B），
**实证确认信号在控制分位后有正增量信息**；但**整体 tierDiscrimination 仍非正单调**
（各维 spearman ≤0.8 且存在反转，B/C 中间档样本大但 excess≈0，D 卖出档在 h3/h8 收益转正——
均值回归目标下"已跌"档位未来回升，卖出语义与排名收益方向在低分位反转）。
**阶段 4 仍暂停**；剩余问题为档位语义/收益口径的策略性校准（§5.3），非本轮结构修复范围。

### 5.3 剩余问题（档位语义校准，待策略决策）

结构修复后 S 档已证实有增量信息，但中间/卖出档区分度不足。候选方向（需用户决策后实施）：

1. **收益口径去趋势**：档位收益改"相对同分位桶的超额收益"（meanFutureReturn 也用
   excess 口径，`excessDirectionAccuracy` 已实现）——消除均值回归对档位序的扭曲，重新校准验收。
2. **档位语义与排名方向解耦**：卖出档（D）在低分位未来回升是目标变量性质（已跌反弹），
   不是信号 bug；如业务目标是"追涨"则应保留 S/A 档 excess 作为唯一买卖依据（D/E 仅做风控不预测方向），
   单调性链改为只评估 S/A/B（买入侧）。
3. **中间档（B/C）区分度重建**：B 档样本 28488 但 excess≈0——"方向分歧弱买"语义无预测力，
   可收缩 B 档判定（v==weak 且某维强），或把 C 档作为"无信息"基准不进单调性链。

三项均不改变默认参数数值（档位阈值/权重不变），只影响档位映射与验收口径，需 golden + 全量 pytest + 重跑诊断验收。

### 5.4 语义校准落地（commit `40ddc7f`，2026-08-15）

三项全部实现并 TDD 落地（`tier_monotonicity.py`，不改默认参数数值）：

1. **方案 1 — 收益口径去趋势（已完成）**：`tier_forward_returns` 每档输出 `excessMeanFutureReturn`
   （档位均值 − 样本同分位桶基线均值），单调性 Spearman/反转改用 excess 口径。
2. **方案 2 — D/E 与方向预测解耦（已完成）**：移除 `deBelowC` 硬约束（低分位已跌回升是
   均值回归目标变量性质），D/E 仅保留统计输出作风控标记，不参与方向单调。
3. **方案 3 — C 档不进单调性链（已完成）**：链收窄为 `MONOTONICITY_TIERS = ("S","A","B")`，
   C（无明确方向基准）仅输出统计；验收线 = **S/A 加权 excess ≥ 0.05 且 S/A/B 正单调**。

**校准后真实诊断（769 帧 / 156647 信号）**：

| 维度 | h1 S/A/B excess | h1 单调性（excess 口径） | passHard |
|---|---|---|---|
| synergy（合并） | **+0.088 / +0.039 / −0.006** | **spearman 1.0、无反转** | **True ✓** |
| rankTrend | +0.064 / +0.037 / −0.013 | spearman 1.0、无反转 | False（S/A 加权 0.0455 边缘 <0.05） |
| lifecycle | 无 S / +0.055 / +0.097 | spearman 1.0（仅 A/B 两档） | False（S 无样本） |
| volumePrice | 无 S / +0.013 / +0.025 | A<B 反转 | False |
| resonance | −0.021 / −0.007 / −0.018 | 负相关 | False |

**校准后验收判定**：**synergy（四维合并档位，交易决策消费的主档位）在新口径下完全达标**
（S/A/B excess 严格单调 0.088>0.039>−0.006、spearman=1.0、passHard=True）——四维投票+分位条件化
整合后，合并档位对未来排名收益具备正单调区分度，**阶段 3 验收达成，可进入阶段 4 参数搜索**。
单维信号（resonance/volumePrice）作为投票输入 excess 仍为负/弱，属输入信号质量短板，
已由 synergy 投票整合吸收；阶段 4 搜索时以 synergy 档位为优化对象并监测单维 excess。

## 阶段 7：共振参数搜索与样本外复核（2026-08-17）

> 状态：Phase 1/2 已完成，样本外复核结果见 §7.4
> 脚本：`backend/operations/optimize_resonance_parameters.py`（`--phase 1/2/3 --resume` 可断点续跑）
> 报告：`quant-board/data/reports/resonance-parameter-search.json`
> 决策（用户 2026-08-17）：优化【共振】信号参数——主目标改善共振维对 synergy 投票的贡献
> （合并档为主、监测单维 excess）；搜索范围 = 档位阈值（`tierResonance*`）+ 连续分权重
> （`resonance*`）；产出 = 搜索报告 + 建议参数，**不写回默认值**（golden 不变，采纳另行立项）。

### 7.1 评估口径与基线

- 评估：`replay(config)`（769 帧 2026-04-15~08-14，156647 信号）→
  `tier_forward_returns(dimension=resonance/synergy, horizon=1)`；
  评分 = `2×clamp(synergy saEx,0,0.15) + 0.5×synergy passHard − 0.8×synergy fail + 10×clamp(resonance saEx,0,0.05) + 0.2×resonance passHard − 0.5×max(0, resonance unknown − 0.10)`。
- 基线（当前默认参数）：score 0.5864；synergy saEx **0.0651**（passHard=True）；resonance saEx **−0.0162**（passHard=False）；resonance unknown 18.75%。
- 关键事实：`_resonance_tier` 只消费 `reversal_penalty / jump_event / direction / jump_freshness / persistence`
  五输入，`resonanceWeights`（[0.35,0.25,0.2,0.2,0.2]）只影响 score/label 展示，**不影响档位 → 不影响 synergy 投票**。

### 7.2 Phase 1 单维敏感性（12 参数，29 次评估）

| 参数 | 候选 | 最佳 | score | synergy saEx | resonance saEx | 判定 |
|---|---|---|---|---|---|---|
| `tierResonanceJumpFreshnessMin` | 0.3/0.4/0.5/0.6 | **0.6** | **0.5940** | **0.0689** | **−0.0093** | ✅ 唯一显著改善 |
| `resonanceJumpFreshnessDecay` | 2/3/5 | **2.0** | **0.5940** | **0.0689** | **−0.0093** | ✅ 与上者数学等价 |
| `tierResonanceReversalPenaltyMin` | 0.4/0.5/0.6/0.7 | 0.4 | 0.5878 | 0.0658 | −0.0095 | 微弱 |
| `resonanceMomentumScale` | 10/15/20 | 10 | 0.5883 | 0.0660 | −0.0169 | 微弱 |
| 其余 8 参数（persistence/entryStrength/reversal switch/drawdown/pathDirection/threshold/accelerationScale/weights） | — | — | ≤0.5868 | ≤0.0653 | 无改善 | ❌ 无改善 |
| `resonanceWeights` 三组组合 | — | — | 0.5864 | 0.0651 | −0.0162 | ⚪ 与基线完全一致（证实不参与档位投票） |

**结论**：Jump 新鲜度是共振信号质量的唯一显著可调维度——S 档要求 Jump 事件更新鲜
（`JumpFreshnessMin` 0.5→0.6）或新鲜度衰减更快（`Decay` 3→2），两旋钮数学等价；
其余参数对 synergy 投票无实质贡献。

### 7.3 Phase 2 定向组合验证（6 组合）

| 组合 | score | synergy saEx | resonance saEx |
|---|---|---|---|
| 基线 | 0.5864 | 0.0651 | −0.0162 |
| `jump_min_0.6`（首选单旋钮） | 0.5940 | 0.0689 | −0.0093 |
| `jump_min_0.6 + decay_2.0` | 0.5940 | 0.0689 | −0.0093（不叠加，等价确认） |
| `jump_min_0.6 + reversal_penalty_min_0.4` | 0.5954 | 0.0696 | **−0.0025**（单维最佳） |
| **`jump_min_0.6 + momentum_scale_10`** | **0.5956** | **0.0697** | −0.0098 |
| `jump_min_0.6 + decay_2.0 + reversal_penalty_min_0.4` | 0.5954 | 0.0696 | −0.0025 |

**建议参数**（不写回默认值）：
1. 首选：`tierResonanceJumpFreshnessMin` 0.5→**0.6**（synergy saEx +5.8%、单维改善 43%，最稳健）；
2. 可选叠加：`resonanceMomentumScale` 15→**10**（总分最佳）或 `tierResonanceReversalPenaltyMin` 0.6→**0.4**（单维最优）；
3. `resonanceJumpFreshnessDecay` / `resonanceWeights` 不动（等价取一；不影响档位）。

### 7.4 样本外复核（walk-forward，2026-08-17）

**方法**：chronological 切分（`split_frames`，validation_ratio 0.3）→
train=2026-04-15~07-07（537 帧）/ validation=2026-07-09~08-14（232 帧）；
每配置全量 769 帧 replay 一次（信号含完整历史上下文），train/validation 段分别统计
resonance/synergy h1 tier（段外 snapshotId 自动跳过）。

| 配置 | train syn saEx | train res saEx | validation syn saEx | validation res saEx |
|---|---|---|---|---|
| baseline | 0.0902（pass=True） | −0.0093 | **−0.0112（pass=False）** | −0.0369 |
| `jump_min_0.6` | 0.0933（pass=True） | −0.0024 | −0.0062（pass=False） | −0.0299 |
| `jump_min_0.6 + reversal_penalty_min_0.4` | 0.0932（pass=True） | **+0.0055** | **−0.0024（pass=False）** | −0.0285 |
| `jump_min_0.6 + momentum_scale_10` | **0.0943（pass=True）** | −0.0024 | −0.0056（pass=False） | −0.0325 |

（validation 段全部配置 passHard=False，含基线；verdict 均为 `validation_passHard_failed`）

**复核结论**：
1. **参数方向样本内稳定**：train 段建议参数 synergy saEx 0.0902→0.0933~0.0943（+3.4%~+4.5%），
   共振单维 saEx −0.0093→−0.0024~+0.0055（由负转正/大幅改善）——Phase 1/2 的 in-sample 改善可复现；
2. **样本外 synergy 档位绝对区分度失效（窗口性，与共振参数无关）**：validation 段**基线也**
   passHard=False、saEx −0.0112（全窗口 0.0651 的显著回撤），且该段共振 unknown 占比升至 29.9%
   （train 14.8%）——7-9 月窗口热榜排名收益模式/样本质量变化导致四维信号整体失效，
   档位分布两段几乎一致（S~210-222/A~1085-1123/B~6080/D~13870），排除参数致分布扭曲；
3. **建议参数在样本外相对基线仍保持改善**（validation saEx −0.0112→−0.0062~−0.0024，
   改善 45%~79%，无反转）——参数方向稳健，但**绝对验收线（≥0.05 且 passHard）样本外不可达**。

**最终建议**（延续 §7.3，不写回默认值）：
- `tierResonanceJumpFreshnessMin` 0.5→**0.6** 可作为共振输入质量的小幅稳健改善候选，但
  **单独据此采纳不满足样本外绝对验收**（synergy 区分度失效是窗口/市场状态问题，非本参数可解）；
- 如需推进：先做市场状态（regime）过滤或延长样本外窗口复核，再走 golden 变更流程；
  或按阶段 6 结论保持"四维信号仅作观察信号"，共振参数调整仅影响展示口径。

### 7.5 市场状态（regime）过滤研究（2026-08-17）

**方法**：`market_regime(frame)` 五因子打分（score≥70 strong / ≥50 normal / ≥30 weak / 其余 retreat），
每个 signal 带 `regime` 字段。按 regime 分桶（`tier_forward_returns` 新增 `signal_filter` 参数）
统计 synergy/resonance h1，全窗口 + train（2026-04-15~07-07）/ validation（2026-07-09~08-14）三段，
对比 baseline / `jump_min_0.6` / `jump_min_0.6 + reversal_penalty_min_0.4` 三配置。

**synergy saEx 按 regime 分桶（baseline，n 为全量信号数）**：

| regime | n（占比） | all | train | validation | validation ≥0.05 |
|---|---|---|---|---|---|
| strong | 26418（17%） | 0.014 | 0.0495 | **−0.0202** | ❌ |
| normal | 88826（57%） | 0.0828 ✓ | 0.1059 | 0.0131 | ❌ |
| **weak** | 37975（24%） | 0.0712 ✓ | 0.0735 | **0.1146** | ✅ |
| retreat | 3428（2%） | 0.1421 | 0.1502 | None（样本不足） | — |
| weak+normal | 126801（81%） | 0.0796 | 0.0956 | 0.0188 | ❌ |
| all（对照） | 156647 | 0.0651 | 0.0902 | −0.0112 | ❌ |

**weak 桶 validation 明细（baseline）**：S n=12（exAcc +0.139）/ A n=54（+0.109）/ B n=491（+0.02），
spearman 1.0、无反转、saEx **0.1146**、unknown 0%；passHard=False 仅因 **S 档样本 12 < 30**
（其余三项 check 全 ok）。

**共振参数在 weak 桶（synergy saEx）**：`jump_min_0.6` all 0.0748 / train 0.0772 / validation 0.1146；
`jump_min_0.6 + reversal_penalty_min_0.4` all 0.0712 / train 0.0731 / validation **0.1259**
（均不劣于 baseline 的 0.0712/0.0735/0.1146）。

**结论**：
1. **过滤方向与"strong 有效"直觉相反**：weak 是唯一 validation 段 saEx ≥ 0.05 的 regime——
   **弱市里 S/A 档（追强）稀缺但有正增量信息**（跨三段 0.0712/0.0735/0.1146 方向稳定）；
   strong 状态反而失效（validation −0.0202），与阶段 6 "A_MAIN 触发=高位出货、追强 h8 归零"结论一致
   ——强市追强是高位接盘，弱市追强才有区分度。
2. **全窗口 validation 失效根因定位**：2026-07-09~08-14 窗口 strong+normal 桶贡献负/弱 excess
   （normal val 0.0131、strong val −0.0202），weak 桶（占 24%）保持正区分度——不是共振参数问题，
   是**市场状态结构**问题。
3. **weak 桶置信度限制**：validation 段 S 档仅 12 样本（<30），saEx 0.1146 统计置信度有限；
   resonance 单维在 weak 状态横截面不足（validation res unknown 69.1%），单维不可用，
   synergy 投票仍有效（趋势/量价维提供信号）。
4. **共振参数建议在 weak 桶不恶化且小幅改善**（0.0712→0.0748；组合 val 0.1259 最高）。

**建议**（不改代码/默认值，延续 §7.4）：
- **weak 状态可作为"四维观察信号可信度"补充口径**：弱市 S/A 档更有区分度、强市追强为高位风险
  （如需前端/观察层标注，另行立项）；
- 共振参数（`JumpFreshnessMin` 0.6）单独采纳仍不满足样本外绝对验收（weak 桶 S 样本不足、
  其余 regime 验证失效）；如需落地需先延长样本外窗口或接入 weak 过滤后重估 S 档样本量。

### 7.6 weak 状态 S 档样本量重估（quarter_hour 长窗口，2026-08-17）

**背景**：§7.5 的 weak 桶 validation 段（half_hour，2026-07-09~08-14）S 档仅 12 样本，
置信度不足。为验证"更长样本外窗口能否重估 S 档显著性"，用**唯一更长历史窗口
quarter_hour（2026-03-27~07-31，1399 帧）**重跑（显式研究口径，非默认 half_hour；
脚本 `backend/operations/diagnose_weak_regime_sampling.py`，报告
`data/reports/weak-regime-sampling.json`）。

**weak 桶 synergy h1（quarter_hour，train 1007 帧 03-27~06-18 / validation 392 帧 06-22~07-31）**：

| 配置 | 段 | S | A | B | saEx | pass |
|---|---|---|---|---|---|---|
| baseline | all | 184 | 1314 | 8810 | 0.0623 | True |
| baseline | train | 163 | 1174 | 7968 | 0.0734 | True |
| baseline | validation | **21** | 140 | 842 | **−0.0096** | False |
| `jump_min_0.6` | validation | 20 | 137 | 828 | −0.0122 | False |
| `jump_min_0.6 + reversal_0.4` | validation | 20 | 139 | 859 | −0.0229 | False |

**validation 段拆分（baseline weak 桶）**：

| 子窗口 | 帧数 | S | A | saEx | S exAcc | A exAcc |
|---|---|---|---|---|---|---|
| 06-22~07-08 | 180 | 19 | 126 | **0.0017** | +0.023 | −0.002 |
| 07-09~07-31 | 212 | **2** | 14 | **0.2398** | **+0.561** | +0.194 |
| 全段 06-22~07-31 | 392 | 21 | 140 | −0.0096 | +0.035 | −0.016 |

**重估结论**：
1. **S 档样本不足是结构性的，不是窗口长度问题**：quarter_hour 帧密度翻倍 + 前移 3 周，
   weak 桶 validation S 档仍仅 21 样本（07-09 后更只有 2 个）——**弱市 S 档（Jump 驱动的追强档）
   本身极稀缺**，无法获得 ≥30 的统计置信。
2. **weak 状态 synergy 区分度样本外不稳定**：07-09~07-31 段 S 方向精度极高（exAcc +0.56）
   但仅 2 样本（half_hour 的 0.1146/S=12 同属此现象——方向强、样本稀）；06-22~07-08 段
   S=19 却无区分度（0.0017）。**样本外 weak 桶 S 档表现随样本量剧烈波动，无统计显著性**。
3. **样本内（train/全窗口）weak 桶稳定成立**（saEx 0.062~0.079，S 163-184，pass=True）——
   弱市追强有正增量的样本内证据充分，但样本外无法证实（数据历史不足）。
4. **"weak 过滤 + 更长窗口"不足以支撑共振参数采纳**；维持 §7.4/§7.5 结论不变。

**后续**：如需证实"弱市稀缺追强信号"方向（07-09 后 S exAcc +0.56 的提示），需更长历史数据
或更宽 S 档定义（如放宽 Jump 新鲜度门槛增加 S 样本）后重估；当前 5 个月数据不足以定论。

## 阶段 8：核心信号参数逐参数 3 档扫描（2026-08-17）

> 状态：扫描完成；结论 = 趋势核心改善点在**多周期动量周期组合**（快周期），
> 零线交叉/MACD 权重周期与 Jump reset/sustain 无独立调参空间。
> 脚本：`backend/operations/optimize_core_signal_parameters.py`（每个参数 3 档单变量扫描）
> 报告：`quant-board/data/reports/core-signal-parameter-groups.json`

### 8.1 背景与决策

用户 2026-08-17：档位（S/A/B/C/D/E）层面参数（tierResonance*/tierRankTrend* 等）扫描
已穷尽、基本无调参可能，**深入核心指标参数构成**——【趋势】多周期动量 / 零线交叉 / MACD、
【共振】Jump 跳跃值参数（delta/reset/sustain），**每个参数分别定义 3 档候选值**逐参数扫描
（非打包 3 组配置）。

配套代码改动（TDD，golden 不漂移）：`detect_rank_jumps` 的 reset_lookback（原硬编码 3）
与 sustain_count（原硬编码 2）参数化进 `RankTrendConfig`（`jumpResetLookback`/`jumpSustainCount`），
新增 `tests/test_ranktrend_jump_detection.py`（4 用例，默认行为不变，回归 32 passed）。

### 8.2 扫描结果（769 帧，h1；score=阶段 7 公式；表格为 score / synergy saEx / 关注维 saEx）

**趋势（rankTrend focus）**：

| 参数 | 档 1（默认） | 档 2 | 档 3 | 判定 |
|---|---|---|---|---|
| `momentumPeriods` | [3,5,8,13,21]：1.0854/0.0651/0.0455 | **[2,3,5,8,13]：1.1112/0.0673/0.0477** | [5,8,13,21,34]：1.0716/0.0558/0.046 | ✅ 唯一显著改善 |
| `momentumWeights` | [0.15,0.2,0.25,0.25,0.15] | [0.25,…快]：1.0524/0.0628/0.0427 | [0.1,…慢]：1.0884/0.0641/0.046 | ❌ 权重非瓶颈 |
| `crossWeight` | 0.2：1.0854 | 0.35：1.0723/0.0641/0.0444 | **0.1：1.0988/0.0657/0.0467** | ⚪ 弱化微升 |
| `macdWeight` | 0.25 | 0.35：1.0757/0.0653/0.0445 | 0.15：1.0873/0.0651/0.0457 | ⚪ 持平 |
| `macdFast` | 13 | 9：1.0706/0.0646/0.0441 | 17：1.087/0.0648/0.0457 | ⚪ 持平 |
| `macdSlow` | 21 | 26：1.0962/**0.0619**/0.0472 | 17：1.0708/0.0636/0.0444 | ⚪ trend 升但 synergy 降 |
| `macdSignal` | 8 | 5：1.0684/0.065/0.0438 | 12：1.0801/0.0645/0.0451 | ⚪ 持平 |

**共振 Jump（resonance focus）**：

| 参数 | 档 1（默认） | 档 2 | 档 3 | 判定 |
|---|---|---|---|---|
| `jumpDeltaPct` | 15：0.5864/0.0651/−0.0162 | **20：0.592/0.0679/−0.0146** | 10：0.5849/0.0643/−0.0193 | ✅ 严格化微升（延续 §7.2） |
| `jumpResetLookback` | 3 | 5：0.5898/0.0668/−0.0196 | 2：0.5894/0.0666/−0.0156 | ⚪ 微弱 |
| `jumpSustainCount` | 2 | 3：0.5864（完全一致） | 1：0.5864（完全一致） | ❌ 无影响（事件分布不敏感） |

**组合验证**：

| 组合 | score | synergy saEx | trend saEx |
|---|---|---|---|
| base | 1.0854 | 0.0651 | 0.0455 |
| `mom_fast`（periods 快） | 1.1112 | 0.0673 | 0.0477 |
| `mom_fast + jump20` | 1.112 | 0.0677 | 0.0477（可叠加） |
| **`mom_fast + cross01`** | **1.1177** | 0.067 | **0.0484** |

### 8.3 结论

1. **趋势核心改善点 = `momentumPeriods` 快周期 [2,3,5,8,13]**：单参数 synergy saEx +3.4%、
   rankTrend saEx +4.8%（0.0455→0.0477）——热榜排名动量是短周期现象，更快周期捕捉更及时；
   慢周期 [5,8,13,21,34] 反而拖累 synergy（0.0651→0.0558）。
2. **零线交叉 / MACD 的权重与周期参数无独立调参空间**（各档基本持平或 trade-off）——
   其内部硬编码阈值（零线 0.7/0.3/0.15、MACD gap 阈值）尚未 config 化，如需深入须先参数化
   内部阈值（另行立项）。
3. **Jump 严格化（`jumpDeltaPct` 20）延续 §7.2 结论**（synergy 0.0679，可与快周期叠加）；
   `jumpResetLookback` 微弱、`jumpSustainCount` 无影响（当前数据事件分布不敏感）。
4. **建议参数**（不写回默认值，golden 不变）：首选 `momentumPeriods=[2,3,5,8,13]`；
   可选叠加 `jumpDeltaPct=20`（synergy）或 `crossWeight=0.1`（trend saEx 最接近 0.05 线）。
   采纳仍需样本外复核 + golden 变更流程。

### 8.4 趋势因子硬编码参数化 + 每个因子 5 档扫描（2026-08-17）

**背景**：用户要求【趋势】信号每个因子构成的参数找全，硬编码阈值先参数化，然后
每个因子单独跑 5 档（防过拟合——多档位观察单调性/峰值稳定性，避免单点过拟合）。

**参数化落地（TDD，默认值=原硬编码，golden 不漂移）**：18 个硬编码阈值进 `RankTrendConfig`——
动量方向 `momentumDirectionThreshold`(0.2)/`momentumSignalShareMin`(0.6)/`momentumLongOpposeThreshold`(0.25)/
`momentumLongAgreeThreshold`(0.15)/`momentumDirectionShareBoost`([0.5,0.5])；
动量加速度 `momentumAccelThreshold`(0.18)/`momentumAccelShareBoost`([0.7,0.3])；
momentum_data `momentumScoreThreshold`(35)/`momentumConfidenceSlope`(0.45)；
零线交叉 `momentumZeroWeights`([0.7,0.3])/`momentumZeroConfirmThreshold`(0.15)/
`momentumZeroStrongConfirmThreshold`(0.15)/`momentumZeroStrongConfirmBonus`(5)；
MACD `macdGoldenStrongGapMin`(0.2)/`macdGoldenGapScaleRatio`(0.18)/`macdDeathGapScaleRatio`(0.12)/
`macdDeathStrongGapMin`(0.18)/`macdRawScoreWeights`([0.7,0.3])。
`_STRATEGY_LIST_KEYS` 补 4 个 list 字段；新增 `tests/test_ranktrend_trend_factor_config.py`（4 用例）。
验证：相关 pytest 78 passed 无回归 + 新测试 4 passed。

**5 档扫描（8 参数 × 5 档 = 32 次全量评估；score / synergy saEx / trend saEx）**：

| 因子 | 参数 | 5 档结果（score 序列） | 判定 |
|---|---|---|---|
| F1 动量·方向 | `momentumDirectionThreshold` | 0.1:1.0817 / 0.15:1.0814 / **0.2:1.0854** / 0.25:1.0829 / 0.3:1.0838 | ⚪ 默认最优，各档持平 |
| F1 动量·方向 | `momentumSignalShareMin` | 0.4:1.0865 / 0.5:1.0867 / 0.6:1.0854 / 0.7:1.0843 / **0.8:1.0885** | ⚪ 0.8 微升 |
| F2 动量·加速度 | **`momentumAccelThreshold`** | 0.1:1.0625 / 0.14:1.0765 / 0.18:1.0854 / 0.22:1.0994 / **0.26:1.1093** | ✅ **单调上升唯一显著** |
| F2 动量·加速度 | `momentumLongOpposeThreshold` | 0.15:1.0847 / 0.2:1.0854 / 0.25:1.0854 / 0.3:1.0843 / 0.35:1.0844 | ⚪ 默认最优 |
| F3 零线交叉 | `momentumZeroConfirmThreshold` | 0.05:1.0852 / 0.1:1.0865 / 0.15:1.0854 / **0.2:1.0904 / 0.25:1.0906** | ⚪ 提高微升（syn 0.066） |
| F3 零线交叉 | `momentumZeroStrongConfirmThreshold` | 全部 1.0854（完全一致） | ❌ 仅影响 confidence 不影响档位 |
| F4 MACD | `macdGoldenStrongGapMin` | 0.1:1.0852 / 0.15:1.0852 / 0.2:1.0854 / 0.25:1.0864 / **0.3:1.0881** | ⚪ 提高微升 |
| F4 MACD | `macdGoldenGapScaleRatio` | 0.1:1.0854 / 0.14:1.0854 / 0.18:1.0854 / 0.22:1.0862 / **0.26:1.0878** | ⚪ 提高微升 |

**结论**：
1. **`momentumAccelThreshold` 0.18→0.26 是唯一显著改善参数**：5 档单调上升（1.0625→1.1093，
   非单点尖峰 → 方向稳健、防过拟合证据强）；trend saEx 0.0455→**0.0478**（+5.1%）、synergy 0.0651→0.0658。
   语义：加速度信号判定更严格（更强加速度才触发 buy/sell），过滤弱加速度噪声。
2. **方向阈值默认 0.2 最优**、`momentumLongOpposeThreshold` 默认最优——方向判定当前阈值合理。
3. **`momentumZeroStrongConfirmThreshold` 完全无影响**（各档一致）——该参数只影响 zero_conf
   （confidence），不影响 zero_signal/zero_score → 不参与档位判定（属冗余可调参数）。
4. **MACD 阈值提高微升**（0.3/0.26），幅度小（score +0.2%~0.3%）。
5. **建议参数**（不写回默认值，golden 不变）：首选 `momentumAccelThreshold=0.26`；
   可选微调 `momentumZeroConfirmThreshold=0.25`、`macdGoldenStrongGapMin=0.3`、
   `momentumSignalShareMin=0.8`。采纳仍需样本外复核 + golden 变更流程。

### 8.5 momentumAccelThreshold=0.26 样本外复核（2026-08-17）

**方法**：同 §7.4（chronological 切分，validation_ratio 0.3）→
train=2026-04-15~07-07（537 帧）/ validation=2026-07-09~08-14（232 帧）；
每配置全量 769 帧 replay 一次（信号含完整历史上下文），train/validation 段分别统计
**rankTrend / synergy** h1 tier（本参数影响趋势维，重点看 rankTrend 单维 + synergy 合并档）。

**配置**：`baseline` / `momentumAccelThreshold=0.26`（5 档扫描唯一单调显著参数）。

| 配置 | train trend saEx | train syn saEx | validation trend saEx | validation syn saEx |
|---|---|---|---|---|
| baseline | 0.0636（pass=True） | 0.0902（pass=True） | −0.0081（pass=False） | −0.0112（pass=False） |
| `accel_0.26` | **0.0665（pass=True）** | **0.0922（pass=True）** | **−0.0079（pass=False）** | −0.014（pass=False） |

**复核结论**：
1. **样本内改善可复现**：train 段 trend saEx 0.0636→0.0665（+4.6%）、synergy 0.0902→0.0922
   （+2.2%）——与全窗口 5 档扫描的 in-sample 改善方向一致；
2. **趋势维样本外无反转且微改善**：validation trend saEx −0.0081→−0.0079（方向稳健）；
3. **但 synergy 合并档样本外略恶化**：−0.0112→−0.014（−25%），加速度严格化对 synergy 投票
   样本外无正贡献；
4. **validation 段绝对区分度失效是窗口性**（同 §7.4/§7.5）：baseline 的 validation trend/syn
   saEx 均为负（−0.0081/−0.0112，passHard=False）——2026-07-09~08-14 窗口四维信号整体失效
   （市场状态结构问题，非本参数可解）。
5. **最终判定**：`momentumAccelThreshold=0.26` 样本内显著改善、趋势维样本外方向稳健，
   但 synergy 样本外无正贡献且绝对验收线不可达 → **不满足样本外采纳标准**；
   维持"不写回默认值"，与 §8.4 建议（作候选参数观察）一致。

### 8.6 momentumPeriods 快周期样本外复核（2026-08-17）

**方法**：同 §8.5/§7.4（chronological 切分，validation_ratio 0.3）→
train=2026-04-15~07-07（537 帧）/ validation=2026-07-09~08-14（232 帧）；
全量 769 帧 replay 一次，train/validation 段分别统计 rankTrend / synergy h1 tier。
baseline 数值引用 §8.5 复核产出（同一次切分口径）。

**配置**：`baseline` / `mom_fast`（`momentumPeriods=[2,3,5,8,13]`，阶段 8 发现的唯一显著参数）。

| 配置 | train trend saEx | train syn saEx | validation trend saEx | validation syn saEx |
|---|---|---|---|---|
| baseline | 0.0636（pass=True） | 0.0902（pass=True） | −0.0081（pass=False） | −0.0112（pass=False） |
| `mom_fast` | **0.0654（pass=True）** | **0.0936（pass=True）** | **−0.0055（pass=False）** | −0.0136（pass=False） |

**复核结论**：
1. **样本内改善可复现**：train 段 trend saEx 0.0636→0.0654（+2.8%）、synergy 0.0902→0.0936
   （+3.8%）——与阶段 8 全窗口扫描（synergy +3.4%）一致；
2. **趋势维样本外改善幅度最大**：validation trend saEx −0.0081→−0.0055（改善 32%），
   优于 accel_0.26（−0.0081→−0.0079）——快周期对趋势维样本外方向更稳健、改善更大；
3. **synergy 合并档样本外略恶化**：−0.0112→−0.0136（−21%，与 §8.5 accel_0.26 同类）——
   动量快化对 synergy 投票样本外无正贡献；
4. **validation 段绝对区分度失效是窗口性**（同 §7.4/§8.5）：baseline validation saEx 为负、
   passHard=False——2026-07-09~08-14 窗口四维信号整体失效（市场状态结构问题）。
5. **最终判定**：`momentumPeriods=[2,3,5,8,13]` 样本内显著改善、趋势维样本外改善（三个复核
   参数中最佳），但 synergy 样本外无正贡献且绝对验收线不可达 → **不满足样本外采纳标准**；
   维持"不写回默认值"，与 §8.4 建议（作候选参数观察）一致。

### 8.7 mom_fast + accel_0.26 组合样本外复核（2026-08-17）

**方法**：同 §8.5/§8.6/§7.4（chronological 切分，validation_ratio 0.3）→
train=2026-04-15~07-07（537 帧）/ validation=2026-07-09~08-14（232 帧）；
全量 769 帧 replay 一次，train/validation 段分别统计 rankTrend / synergy h1 tier。
baseline/mom_fast/accel_0.26 数值引用 §8.5/§8.6 复核产出。

**配置**：`mom_fast + accel_0.26`（`momentumPeriods=[2,3,5,8,13]` + `momentumAccelThreshold=0.26`），
对照三个既有配置。

| 配置 | train trend saEx | train syn saEx | validation trend saEx | validation syn saEx |
|---|---|---|---|---|
| baseline | 0.0636 | 0.0902 | −0.0081 | −0.0112 |
| `mom_fast` | 0.0654 | **0.0936** | **−0.0055** | −0.0136 |
| `accel_0.26` | 0.0665 | 0.0922 | −0.0079 | −0.014 |
| **`combo`** | **0.0666** | 0.0934 | −0.0071 | **−0.0183** |

**复核结论**：
1. **样本内小幅叠加**：combo train trend 0.0666（四配置最高，+4.7% vs baseline）、synergy 0.0934
   （接近 mom_fast 的 0.0936）——两参数样本内趋势维叠加基本成立；
2. **样本外趋势维不叠加、被 accel_0.26 拖累**：combo validation trend −0.0071，介于
   mom_fast（−0.0055 最佳）与 accel_0.26（−0.0079）之间——组合未继承 mom_fast 的最佳样本外
   改善，反而恶化 29%（−0.0055→−0.0071）；
3. **样本外 synergy 负面放大（最差）**：combo validation syn −0.0183，劣于全部既有配置
   （baseline −0.0112 / mom_fast −0.0136 / accel_0.26 −0.014）——两参数的样本外 synergy
   负面贡献叠加放大；
4. **validation 段绝对区分度失效是窗口性**（同 §7.4/§8.5/§8.6），不改变相对对比结论。
5. **最终判定**：**组合不成立**——样本内趋势维小幅叠加不足以抵消样本外 synergy 负面放大与
   趋势维回退；两参数维持各自独立观察（§8.4 候选），**组合方案不建议采纳**，均不写回默认值。

### 8.8 共振 Jump 参数 5 档扫描 + 组合样本外复核（2026-08-17）

**背景**：趋势参数研究收敛（§8.4-§8.7），转向【共振】Jump 参数组合。
沿用逐参数 5 档方法论（防过拟合）对 Jump 参数构成（delta/reset/sustain）扫描，
再对显著参数与档位层有效参数（§7.3 `JumpFreshnessMin` 0.6）组合验证 + 样本外复核。
报告：`data/reports/core-signal-parameter-jump.json`。

**5 档扫描（3 参数 × 5 档 = 12 次非默认全量评估；score / synergy saEx / resonance saEx）**：

| 参数 | 5 档结果（score / syn saEx / res saEx） | 判定 |
|---|---|---|
| **`jumpDeltaPct`** | 10:0.5849/0.0643/−0.0193 · 12.5:0.5874/0.0656/−0.0181 · 15:0.5864/0.0651/−0.0162 · 20:0.592/0.0679/−0.0146 · **25:0.6008/0.0723/−0.013** | ✅ **严格化单调显著**（15→25 synergy +11.1%） |
| `jumpResetLookback` | 2:0.5894/0.0666/−0.0156 · 3:0.5864/0.0651 · 4:0.5856/0.0647 · 5:0.5898/0.0668 · 6:0.5853/0.0645 | ⚪ 非单调微弱 |
| `jumpSustainCount` | 1/2/3/4/5 全部 0.5864/0.0651/−0.0162 | ❌ 完全无影响（冗余参数确认） |

**组合验证（全窗口 769 帧）**：

| 配置 | synergy saEx | resonance saEx |
|---|---|---|
| baseline | 0.0651 | −0.0162 |
| `delta25` | 0.0723（+11.1%） | −0.013 |
| **`delta25 + freshness06`** | **0.0753（+15.7%）** | **−0.0079（改善 51%）** |
| `delta25 + reset2` | 0.0724 | −0.0105 |

核心参数（delta 严格化）与档位参数（freshness 严格化）方向一致 → **叠加有效**，为共振维度
首次强组合信号。

**单调边界探测（2026-08-17 补充，delta 25 基础上探 30/35）**：

| 配置 | synergy saEx | resonance saEx |
|---|---|---|
| `delta25` | **0.0723** | −0.013 |
| `delta30` | 0.0669（回落） | −0.0135 |
| `delta35` | 0.0655（≈baseline） | −0.0135 |
| `delta30 + freshness06` | 0.0698 | −0.0088 |

**边界结论**：`jumpDeltaPct` 单调曲线 10→25 上升、25→35 下降，**25 为真实峰值/拐点**
（非扫描边界假峰值——防过拟合确认）；delta≥30 过度过滤导致 jump 事件减少、贡献回落，
delta 组合（30+freshness06 0.0698）亦劣于 25 组合（0.0753）。**最优档锁定 delta=25**。

**样本外复核（chronological train=537/validation=232，resonance/synergy h1）**：

| 配置 | train res saEx | train syn saEx | validation res saEx | validation syn saEx |
|---|---|---|---|---|
| baseline | −0.0093 | 0.0902 | −0.0369 | −0.0112 |
| `delta25 + freshness06` | **−0.0037**（+60%） | **0.0993**（+10.1%） | **−0.0191**（+48%） | **+0.0024（转正）** |

**复核结论**：
1. **样本内大幅改善**：train res −0.0093→−0.0037（+60%）、syn 0.0902→0.0993（+10.1%）——
   共振单维与 synergy 合并档双双显著改善，可复现；
2. **样本外 res 单维改善 48%**（−0.0369→−0.0191，仍负但大幅接近 0）；
3. **样本外 synergy 转正（关键突破）**：validation syn −0.0112→**+0.0024**——**所有复核参数
   （趋势 accel/mom_fast、Jump 单参数、共振 Phase 1/2 建议）中首个样本外 synergy 转正者**；
   虽未达 0.05 验收线、passHard 仍 False，但方向正确（相对改善 121%）；
4. validation res unknown 29.9% 与 baseline 相同（窗口性未知率上升，同 §7.4）；
5. **最终判定**：`jumpDeltaPct=25 + tierResonanceJumpFreshnessMin=0.6` 是当前研究最强候选
   （样本内 +10.1%、样本外 synergy 转正）；**绝对验收线样本外仍不可达**，维持不写回默认值；
   如需推进：延长样本外窗口（quarter_hour 1399 帧显式口径）或 weak regime 桶复核后再走
   golden 变更流程。











