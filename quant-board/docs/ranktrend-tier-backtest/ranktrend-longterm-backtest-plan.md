# 四维信号长期回测计划与性能优化方案

> 命名注记（2026-09-06，WP3.1）：本文"四维"为历史命名；当前口径为 **5 投票维（res/rank/vp/cs + 热榜情绪）+ 1 环境门（lifecycle）**，lifecycle 不进投票、以 veto/降档影响合成。

> 状态：阶段 1-5 已落地，阶段 6（四维信号有效性研究）完成，**生命周期分层重构落地**：
> 默认策略 rank_trend_candidate 入场主轴切换为 four_dim（synergy S/A + 资金 zljzb>=0 + 非 veto），
> 交易模拟 pf>1（maxPos10 1.038）、样本外 7/7 段全胜基线（commit `8f28324`/`d60f019`）。
> 阶段 1（性能改造）已落地（commit `b4c9091`~`dce716b`），阶段 2（数据质量治理）已落地（commit `58878dc`），阶段 3（四维信号区分度诊断 + 三方向修复 + 语义校准）**验收达成**（commit `2f905b5`/`dc01019`/`40ddc7f`），阶段 4（参数搜索）**四线碰壁归档**（commit `1fb7384`/`cf73491`/`4a6a443`/`a31af1b`/`1adf47b`），验收口径调整为**胜率×盈亏比组合**，阶段 5（信号→收益映射缺口诊断）**已落地，缺口归属=退出机制（exit）**，阶段 6 待立项
> 日期：2026-08-15（最新补充 2026-08-19：§11.4e 前瞻口径验证——h1 为 RankTrend 信号本征时间尺度，
> 维持 h1 评估口径；§11.4f 组合优化三方向 A/B/C 全部数据验证——方向 A（regime×crossSection）
> 假设否定、方向 B（排名时序×横截面）互补非冗余、方向 C（门控强度）现状全禁最优；
> 新增 banStrongA/banStrongB 研究开关）
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












## 阶段 9：量价因子参数回测与优化（2026-08-17）

> 状态：参数化 + 5 档扫描 + 组合样本外复核完成；`fund10 + over2` 为**参数研究以来样本外
> 最强候选**（validation synergy 转正 +0.0165）；不写回默认值，采纳待进一步复核
> 脚本：`backend/operations/optimize_core_signal_parameters.py`（第 3 轮，量价）
> 报告：`data/reports/core-signal-parameter-volumeprice.json`

### 9.1 参数化（TDD，默认值=原硬编码，golden 不漂移）

量价因子已有 config 参数（`volumePriceBase=50`/`OverVolumeRatio=2.5`/`AbnormalFundRatio=20`/
`ShrinkRatio=0.95`/`MildRatio=1.05`）；新增硬编码参数化 2 个：
- `volumePriceDirectionBuckets=[15,12,10,8,6,4,2,1]`（方向八档分值，原硬编码于 `_direction_bucket`）
- `volumePriceNormalRatio=2.0`（量比正常上限，原硬编码 `vr<=2.0` 边界）

测试 +3（默认值断言/方向八档生效/量比边界生效），`test_volume_price_score.py` 17 passed。

### 9.2 5 档扫描（7 参数 × 5 档 = 28 次全量评估；synergy saEx）

| 参数 | 5 档结果（synergy saEx） | 判定 |
|---|---|---|
| **`volumePriceAbnormalFundRatio`** | **10:0.0759 / 15:0.0666 / 20:0.0651 / 25:0.0667 / 30:0.0677** | ✅ **10 显著（+16.6%，pass=T 保持）** |
| `volumePriceOverVolumeRatio` | 1.5:0.0788(pass=F) / 2.0:0.0683 / 2.5:0.0651 / 3.0:0.0615 / 3.5:0.0628 | ⚪ 2.0 略升（1.5 破坏 passHard） |
| `volumePriceMildRatio` | 0.95:0.0622 / 1.0:0.0633 / 1.05:0.0651 / 1.1:0.0657 / 1.15:0.0657 | ⚪ 1.1/1.15 微升 |
| `volumePriceShrinkRatio` | 0.75~1.15：0.0643~0.0651 | ⚪ 持平/略降 |
| `volumePriceBase` | 40~60 全部 0.0651（完全一致） | ❌ 仅平移 score 不影响档位 |
| `volumePriceNormalRatio` | 全部 0.0651（完全一致） | ❌ 同上 |
| `volumePriceDirectionBuckets` | ×0.8~1.2 全部 0.0651（完全一致） | ❌ 方向分平移不影响档位（象限决定档位） |

**关键洞察**：量价档位由 **quadrant（量比×涨跌）+ fund（资金）** 决定——方向八档/基准分/量比
正常边界仅平移 score，**无档位影响**；真正可调的是**资金对倒阈值**（识别 E 档假信号的敏感度）
与**过度放量阈值**。

### 9.3 组合验证 + 样本外复核（chronological train=537/validation=232）

| 配置 | 全窗口 h1 syn saEx | train h1 | validation h1 |
|---|---|---|---|
| baseline | 0.0651（pass=T） | 0.0902 | −0.0112 |
| `fund10` | 0.0759（+16.6%） | 0.1022 | **+0.0044（转正）** |
| **`fund10 + over2`** | **0.0808（+24.1%）** | 0.1031 | **+0.0165（转正）** |
| `fund10 + mild1.15` | 0.075 | 0.1032 | −0.0009（不叠加） |

**复核结论**：
1. **`fund10 + over2`（AbnormalFundRatio 20→10 + OverVolumeRatio 2.5→2.0）是参数研究以来
   样本外最强候选**：全窗口 syn +24.1%（passHard=True 保持）、validation syn −0.0112→**+0.0165**
   （转正，优于 Jump 组合 delta25+freshness06 的 +0.0024）；
2. **语义**：资金对倒阈值更敏感（zljzb>10% 即判异常）→ E 档假信号（对倒出货/过度放量）更早
   识别，量价档位对 synergy 投票的正贡献提升；over 阈值 2.0 与 fund10 方向一致可叠加；
3. **fund10 + mild1.15 不叠加**（validation 回落）——mild 阈值与 fund 无协同；
4. **绝对验收线（≥0.05 且 passHard）样本外仍不可达**（+0.0165 < 0.05），维持不写回默认值；
   但方向正确、train/validation 一致改善，为**采纳优先级最高的候选**（高于 Jump/趋势组合）。

### 9.4 quarter_hour 交叉复核（2026-08-17，查漏补缺）

**背景**：复盘发现 fund10+over2 的样本外证据仅来自 half_hour 单窗口（validation 07-09~08-14），
用 quarter_hour 1399 帧（03-27~07-31，显式研究口径，唯一更长窗口）交叉复核稳健性。

| 配置 | quarter_hour all h1 syn | train | validation |
|---|---|---|---|
| baseline | 0.0769（pass=T） | 0.0914 | −0.0002 |
| `fund10+over2` | 0.0767（pass=T） | 0.0941（+3%） | **−0.0031（未转正）** |

**结论（降级）**：quarter_hour 窗口下 fund10+over2 **样本外未转正**（validation −0.0031，
劣于 baseline −0.0002）——与 half_hour 的 +0.0165 转正**矛盾**。train 段一致改善（+3%/+24%）
说明 in-sample 方向真实，但**样本外改善不具备跨窗口稳健性**（half_hour validation 的 +0.0165
含窗口特有成分）。

**最终判定更新**：`fund10+over2` 从"采纳优先级最高"**降级为"in-sample 方向真实、
样本外跨窗口不稳健、证据不足"**——不满足采纳标准，不写回默认值。**目前四维全部候选
（量价/共振/趋势）均无跨窗口稳健的样本外证据，golden 变更无对象**；fund10+over2 若需
推进，须先解决样本外窗口性失效问题（与 §7.4 共振参数同因：7 月后市场状态结构变化）。

> **2026-08-17 用户洞察修正（§9.5）**：§9.4 的降级结论基于含 **7 月股灾月**的窗口切分，
> 已被 §9.5 的 8 月独立复核**推翻**（fund10+over2 8 月样本外 +438%）；quarter_hour 复核的
> validation 段同样含股灾月，其 −0.0031 亦为股灾污染。以下 §9.4 判定作废，以 §9.5 为准。

### 9.5 8 月独立样本外复核（2026-08-17，用户关键洞察）

**背景**：用户指出 **7 月为股灾月**——此前所有 validation 切分（chronological 30% =
07-09~08-14）含股灾样本，污染样本外结论。**单独跑 8 月数据**（干净窗口）：
train=2026-04-15~07-31（659 帧，含 7 月作 in-sample 上下文）/
validation=2026-08-03~08-14（110 帧，10 交易日）。

| 配置 | h1 train syn | **h1 val 8月 syn** | 相对 baseline |
|---|---|---|---|
| baseline | 0.0802 | 0.0069 | — |
| **`fund10+over2`** | 0.0925 | **0.0371** | **+438%（5.4 倍）** |
| `jump25+fresh06` | 0.0878 | **0.0264** | +283% |
| `mom_fast` | 0.0822 | 0.0087 | +26% |
| `accel_0.26` | 0.0816 | 0.0051 | −26%（劣） |

**结论（翻案，用户洞察成立）**：
1. **7 月股灾确实污染了此前样本外结论**——8 月干净窗口下 baseline val syn 仅 0.0069
   （此前 07-09~08-14 混合窗口 −0.0112 的负值主要来自股灾月）；
2. **`fund10+over2` 8 月样本外 h1 syn 0.0371（+438%），跨窗口（half_hour train + 8 月
   validation）首次显著正向**——接近 0.05 验收线；passHard 仍 False、0.0371 < 0.05，
   仍不满足绝对验收，但**证据强度大幅提升**（此前降级结论作废）；
3. **`jump25+fresh06` 8 月 +283%（0.0264）**——同样显著改善，两个候选方向一致；
4. `mom_fast` 微弱（+26%）、`accel_0.26` 劣（−26%）——趋势候选维持证据不足；
5. **修正后判定**：`fund10+over2` 与 `jump25+fresh06` 升为**跨窗口样本外最强候选**（8 月
   干净窗口显著正向），但未达 0.05 验收线且 8 月仅 110 帧（单窗口仍需谨慎）——维持
   **不写回默认值**；采纳路径：扩充 8 月后数据（09 月以后）或 regime 条件化后复验。

## 阶段 10：核心算法升级方向 A——横截面相对强弱因子 crossSection（2026-08-17）

> 状态：首次验证**显著有效**（参数搜索无实质进展后的算法结构升级）；观察因子已挂载
> （observation.crossSection），**第 5 维投票默认打开**（2026-08-17 用户决策，阶段 11 已生效；实证 all +10%/8月 +237%）
> 代码：`backend/analysis/ranktrend/cross_section.py`（纯函数）+ engine.py 挂载 +
> `tier_monotonicity.py` DIMENSION_PATHS 新增 crossSection
> 测试：`tests/test_cross_section.py` 9 passed；golden 全回归 103 passed（不漂移）

### 10.1 背景（为什么参数搜索无实质进展）

第一轮四维参数扫描（阶段 7/8/9）穷尽全部参数后无候选达 0.05 验收线。根因分析（数据实证）：
- **热榜排名未进主信号**：engine.py 的 frame_cross_section（avgRankNum 横截面 percentile）
  只用于市场 median 环境门（frame_market_median），个股主信号（动量/MACD/量比）全是纯时序
  自回归——Dragon Board 核心资产（八平台热榜合并排名）的**横截面信息被浪费**；
- **synergy A 档自身无增量**（本阶段实证）：synergy A 档 4538 样本 excessDirectionAccuracy≈0
  ——四维投票组合的强势档相对分位桶基线无信息增量，参数再怎么调也无法突破；
- 用户决策（2026-08-17）：核心算法升级方向 A = **横截面相对强弱进主信号**。

### 10.2 因子设计（参数化，golden 不漂移）

个股横截面 percentile 序列（engine histories item[2]，avgRankNum 越小 percentile 越高）：
- `percentile`：当前帧横截面 percentile（0-100）
- `percentileDelta`：percentile − 上一帧（正 = 热度排名上升）
- `relativeToMarket`：percentile − 市场 median percentile
- 档位：A 强（percentile≥85 且 delta≥5）/ B 偏强（≥70 或 delta≥15）/ C 偏弱（≤30 或 delta≤−15）/
  D 弱（≤15 且 delta≤−5）/ unknown（不在横截面）；首帧缺 delta 降级绝对档（A/D 需 delta 确认）；
  市场 median 缺失 → relativeToMarket=None，绝对档照常（fail-visible）
- config 8 字段：crossSectionStrongMin=85 / StrongDeltaUp=5 / MidMin=50 / MidDeltaUp=15 /
  WeakMax=15 / WeakDeltaDown=−5 / MidMax=50 / MidDeltaDown=−15（默认=设计值）

### 10.3 区分度验证（tier_forward_returns，h1 excessDirectionAccuracy）

| 维度 | h1 all exAcc | h1 8月 exAcc | unknown 占比 |
|---|---|---|---|
| **crossSection A** | **+0.0996**（n=1964） | **+0.0724**（n=278） | **0%** |
| crossSection B | +0.0153 | +0.0129 | — |
| crossSection C | −0.0133 | −0.0111 | — |
| volumePrice A（对照） | +0.0125 | −0.0138 | 18.75% |
| rankTrend（整体） | 0.0455 | 0.007 | — |
| synergy A 档 | ≈0（n=4538） | ≈0（n=928） | — |

**关键结论**：
1. **crossSection A 档 h1 exAcc +0.0996 为迄今最强单档信号**（volumePrice A 的 8 倍、
   rankTrend 整体 2 倍、synergy A 档自身≈0）——"高位 + 热度排名上升"个股下一帧相对排名
   显著走强；
2. **8 月干净窗口 +0.0724 稳定**（不依赖股灾月；样本 278 偏少需 9 月累积复核）；
3. **unknown=0**（100% 覆盖率，优于 volumePrice 18.75%）——数据可用性完美；
4. **单调性良好**：A(+0.0996) > B(+0.0153) > C(−0.0133)；D 档因均值回归特殊（低位反弹）；
5. **h8 衰减**（A 档转负）——与 volumePrice 同模式（高热度短前瞻有效、4 小时后均值回归）；
6. **叠加分析**：synergy A 档自身 exAcc≈0 → crossSection 提供 synergy 之外增量
   （8 月 synergy 未覆盖的 crossSection A 个股 exAcc +0.0563/+0.1328，样本偏少）。

### 10.4 判定与下一步

- **判定**：非证伪、非冗余——**"缺复核"偏"证实候选"**（区分度显著但 8 月单窗口样本 278
  偏少 + h8 衰减需确认）；
- ~~不进 synergy 投票~~（阶段 10 初版决策）——**阶段 11 已修订：第 5 维投票默认打开**（用户决策，实证 +10%/+237%）；
- **下一步**：9 月数据累积后复核 A 档（目标样本 >500），确认跨窗口稳定后：
  ① 作为第 5 维投票加入 synergy（golden 变更流程）；② 或与 fund10+over2 组合验证。

## 阶段 11：核心算法审计缺口 G1-G7 修复（2026-08-17）

> 状态：G1-G7 全部处理完成（实现 + 实证 + golden 补强）；**G2 默认打开（用户决策），
> G1 实证负贡献保留观察不进投票，G4 实现默认开但 Jump 事件稀疏**；不写回其它默认值
> 代码：cross_section.py / price_momentum.py / engine.py / volume_price.py / shared.py /
> tier_monotonicity.py；测试：+25（price_momentum 7 + synergy_vote 8 + confirm_jump 10），全量 110 passed

### 11.1 审计根因（为什么参数研究无实质进展）

四维算法不是没实现，而是**排名时序独大、价格时序缺失、横截面浪费**：
- 趋势维度（momentum/MA5/MA10/MACD/zeroCross）输入 100% 是排名百分位时序——**价格信息
  完全没进趋势主信号**（change 只在量价单帧与 fallback 降级用）；
- 个股横截面 avgRankNum 只算市场 median 环境门（阶段 10 已证 crossSection A 档 +0.0996）；
- 成交额 amount 快照已有（8 月 99.7%）但回测字段列表漏读（全窗口 29% 是字段缺口非数据缺口）；
- Jump 事件在 half_hour 数据上**为 0**（detect_rank_jumps 未触发）——共振维实际无事件样本。

### 11.2 修复与实证结论

| 缺口 | 修复 | 实证结论 |
|---|---|---|
| **G1 价格动量** | price_momentum.py 观察因子（change 均线/动量档位 A-D）+ 挂载 observation.priceMomentum | **投票负贡献**（all syn 0.0651→0.0441 −32%、8月 −0.0054）——**保留观察不进投票**（tierSynergyPriceMomentumVote=0）；价格动量与热榜排名收益在短前瞻下无正协同 |
| **G2 crossSection 投票** | _synergy_tier 第 5 维（cs A/B 正 C/D 负 × 权重） | **有效，默认打开**（tierSynergyCrossSectionVote=1.0，用户决策）：all syn 0.0651→0.0716（+10%）、8月 0.0069→0.0232（**+237%**） |
| **G3 amount** | shared.py 补字段 + **跨帧成交额量比落地（2026-08-18）**：amount_histories 累积 + compute_amount_ratio（当前/前 N 帧均额）进 compute_volume_price_score（≥1.5 放量资金 +5 分 / ≤0.5 缩量 -5 分） | 快照已有（8 月 99.7%）；amountRatio 可算 20.7%（需 ≥2 帧连续 amount，早期缺失 fail-visible）、量价增强生效 3.6%（8 月后新数据逐步生效）；测试 +9（amount_ratio 计算/阈值/fail-visible） |
| **G4 Jump 确认** | _confirm_jump（change≥3% 且 volumeRatio≥1 确认，默认开；不满足降级 hold+unconfirmed） | **Jump 事件在 half_hour 为 0**——无实际影响（实现保留防未来假 Jump；resonance 维事件稀疏另见 §7.6） |
| **G5 MACD 口径** | factor-calibration §12.1 | MACD 金死叉 = 排名百分位计算（非价格），价格 MACD 不在范围 |
| **G6 样本门槛** | factor-calibration §12.2 | momentum 可计算门槛（14 帧）与 MACD 预热分离，sampleQuality.ok 用 momentum 门槛 |
| **G7 市场环境** | factor-calibration §12.3 | 市场环境 = 热榜横截面 median（无大盘指数，引用不得外推） |

### 11.3 golden 补强（用户反馈：golden 形同虚设）

- 此前 golden 测试无 synergy 档位断言（G2 投票变更 38 passed 不报错）；
- 新增 `tests/test_synergy_vote.py` 8 用例：默认投票含 crossSection / A 升 S / D 降 B /
  C 降档 / unknown 忽略 / 权重 0 回归旧语义 / 硬风险优先 / pm 投票默认关——**防算法变更悄悄漂移**。

### 11.4 当前 synergy 投票构成（六维 → 五维有效）

res（rank Jump） + rankTrend + volumePrice + lifecycle + **crossSection（第 5 维，默认开）**；
priceMomentum 观察不投票（负贡献实证）；Jump 确认默认开（事件稀疏无实际影响）。

### 11.4b 前端链路同步（2026-08-18 补）

- **问题**：前端【四维】字段数据源 = POST /api/ranktrend/analyze（ranktrend_routes._analyze_one_stock，
  assemble=False）——crossSection 仅挂载于 replay 链路（assemble=True），API 链路 cs_tier=None
  → 第 5 维投票不生效 → **前端档位停留在旧投票口径**（回测改进未同步前端）；
- **修复**：_analyze_one_stock 在 assemble_observation 前补挂载 observation.crossSection
  （percentiles + market_median_percentile 已在 args，与 replay 链路同源）；验证：
  API 链路输出含 crossSection 档位 + synergy 含第 5 维投票；
- **结论**：前端【四维】字段**跟随后端 py 核心算法**（现算链路，非回测研究限定）；
  快照存储为原始数据（collector 不计算 rankTrend），四维分析全部现算——无需回放迁移。

### 11.4c 价格-排名背离因子 priceRankDivergence（2026-08-18，G1 相位差方案）

- **背景**：G1 价格动能裸投票实证负贡献（−32%）——根因是价格 vs 排名 Jump 的相位差
  （排名先行/价格兑现，h1 无独立预测力）；正确用法是观察**背离**而非并列投票；
- **state 四态**（priceDir × rankDir 交叉）：confirm_up（价升+排名升）/ rank_lead（排名升+价跌，
  关注度先行）/ confirm_down（价跌+排名跌）/ price_lead_warn（价升+排名跌，出货预警）；
- **档位映射由数据验证决定（非拍脑袋）**——h1 synergy 桶内 excessDirectionAccuracy：

| state | 分布 | synergy A 档样本 | 证据 → 档位 |
|---|---|---|---|
| confirm_up | 33.1% | 4102，**+0.0242** | A（唯一强正，4102 样本） |
| rank_lead | 18.9% | 138，+0.0097 | B（弱正，样本少） |
| confirm_down | 18.9% | 0（无 A） | C（弱势集中） |
| price_lead_warn | 24.9% | 116，**−0.0086** | D（强档也失效=出货预警成立） |

- **投票验证（2026-08-18，数据驱动）**：dv 投票 0.5→all 0.0626（−12.6%）/1.0→all 0.0535（−25%）、
  8 月 0.0181/0.0139（−22%/−40%）——**实证负贡献，保持观察不进投票**（与 G1 priceMomentum 同因：
  与 crossSection/rankTrend 排名信息高度冗余，重复投票扭曲档位）；
  tierSynergyDivergenceVote=0.0 默认（机制已实现 dv_tier 第 6 维，权重数据定）；
- 测试 +8（四态/阈值/fail-visible）；golden 60 passed 不漂移。

### 11.4d 环境门 regime 优化（2026-08-18，缺口 H 落地，数据驱动）

- **口径统一（第 1 阶）**：market_regime 情绪阶段改读 hotlistSentiment（stage/riskLevel——
  热榜池同源），全市场 sentiment 降为对照（不再打分）；riskLevel 高 −8/低 +3；缺失标注
  fail-visible。修复原混合口径（热榜池打分 + 全市场情绪阶段）。
- **门控数据验证（第 2 阶，结论与预期相反）**：regime 分布 strong 16.9%/normal 56.7%/
  weak 24.2%/retreat 2.2%。synergy A 档 h1 exAcc：**strong −0.0045（负）**/normal +0.0767/
  weak +0.0597/retreat +0.2353（样本少）。candidateTier 桶：A_MAIN strong synA **−0.0739**、
  B_IGNITION strong −0.0172、weak B_IGNITION **+0.077（最强）**——**现有 not weak_market
  （weak/retreat 禁）规则与数据相反：该禁 strong（普涨无区分度+追高），weak 弱市选强更稀缺有效**。
- **门控实现（第 3 阶）**：A_MAIN/B_IGNITION 改 
regime not in (strong, retreat) 禁
  （
regimeGateStrongBan=True 默认，False 回退旧规则）；weak 市场放开 A/B；reasons 标注
  强/退潮降级。效果验证：B_IGNITION all +0.0249→**+0.0416（+67%）**/8 月 −0.0387→−0.0029、
  A_MAIN 8 月 +0.0252→+0.0589（all −0.0119 为 weak 新增样本拖累，弱市选强逻辑正确）。
- **7 月股灾说明**：7 月 regime 分布 strong 3075/normal 14292/weak 6324/retreat 132——股灾
  主要在 normal/weak，weak 放开后 A 档 +0.0597 有效（弱市选强正确应对）；strong 禁防的是
  普涨无区分度而非股灾本身。


### 11.4e 前瞻口径验证与统一说明（2026-08-19，P0-2/P1）

- **P0-2 日线前瞻验证（h1 不是噪声，是信号本征时间尺度）**：769 帧聚合 81 交易日，
  tier_forward_returns dimension=synergy 对比：

| 口径 | saEx | A 档 exAcc（n） |
|---|---|---|
| all h1（30 分钟帧） | **0.0716 pass=True** | +0.0603（4360） |
| all h3（90 分钟帧） | 0.0111 | +0.0091 |
| daily 1d（日线） | 0.0106 | +0.0274（466） |
| daily 3d（3 日） | −0.0339 | −0.0263 |

  > 注：h3 有两类口径——帧级 3 帧（90 分钟）与日线 3 日，数值不可直接比较。
| 8 月 h1 | 0.0453 | +0.041 |

  结论：RankTrend（排名/热度）信号**本征时间尺度是 h1（30 分钟兑现）**——短前瞻最有效、
  拉长衰减，日线 A 档仅残余 +0.0274。**维持 h1 评估口径**；该链不适合中长线持有
  （若做日频信号需另建，不在此链）；"h1 噪声"命题不成立，无需"解决"。
- **P1 口径统一文档化**：
  - A2 命名：列表列名/面板标题"四维"为历史命名，synergy 实际投票 5 维
    （resonance/rankTrend/volumePrice/lifecycle/crossSection）+ priceMomentum/amountRatio/
    priceRankDivergence 观察维度——文档口径以"5 维投票 + 观察因子"为准，UI 命名待后续同步；
  - A4 展示口径：趋势列显示 crossSection 徽章（用户决策）为**展示口径**，算法维度
    observation.rankTrend.signalTier（saEx 0.0455 独立有区分度）仍独立存在——展示与算法
    维度分离是**有意为之**（列表聚焦横截面相对强弱，算法保留排名时序），两者不冲突。


### 11.4f 环境算法升级方向：排名时序 + 横截面 + regime 门控组合优化（2026-08-19）

**结构性结论（本轮全部证据）**：热榜池内**相对强弱口径（排名时序/横截面）有效，绝对口径
（全市场/价格/金额）冗余或噪声**——G1 价格动量负（−32%）、dv 投票负（−25%）、全市场情绪被
移除、strong 普涨无区分度。升级聚焦三个有效维度的**组合**：

- **方向 A：regime × 横截面交互（优先）**——验证 crossSection A（高位+排名上升）在
  strong 市场是否失效（普涨下"高位"无区分度）。若成立 → crossSection 投票权重按 regime
  条件化（strong 降权/weak 升权），替代当前固定权重 1.0。
- **方向 B：排名时序 × 横截面冗余消解**——rankTrend（动量均线）与 crossSection（percentile
  delta）均基于排名，测两维档位相关性/共现率；若高冗余 → 正交化（如 crossSection 保留
  delta、rankTrend 专注绝对分位趋势）或合并为单维，避免重复计分扭曲档位。
- **方向 C：regime 门控强度参数化**——strong 市场 A 档（−0.0739）与 B 档（−0.0172）衰减
  不同：二元禁入可升级为强度门控（strong 时 A 禁/B 降观察档），弱市场（weak B +0.077）
  保持放开。验证 A 禁 B 观察 vs 全禁的 synergy 提升。

**验证流程（沿用数据驱动不拍脑袋）**：每方向先跑 baseline vs 候选的 synergy saEx
（all + 8 月），多档单调性/峰值稳定性防过拟合，正贡献才落默认值。


**方向验证结论（2026-08-19，全部数据驱动，假设均被数据检验）**：

- **方向 A（regime × crossSection 交互）——假设否定**：cs A 全 regime 正（strong +0.0345
  最低/normal +0.132 最强），strong 未失效（横截面是相对口径，普涨不影响相对强弱）——
  **不降权，保持固定权重 1.0**；
- **方向 B（排名时序 × 横截面冗余）——假设否定（互补非冗余）**：A×A 共现仅 0.6%（档位
  不同构）；rt=C（中性）时 cs 补充关键信息（synA +0.0762）；rt=A 时 cs 反向区分
  （csA −0.0469 vs csC +0.0413）——**正交化会破坏互补信息，保持双维并存**；
- **方向 C（regime 门控强度参数化）——验证现状最优**：M0 全不禁（B 8 月 −0.0387）/
  M1 A 禁 B 观察（无改善 −0.0387）/M2 A+B 全禁（**+0.0416/−0.0029**）——**strong B 同样
  该禁，现状全禁已是正确选择**；banStrongA/banStrongB=True 默认（保留可调字段）。

**组合结论**：三方向验证一致指向——现有配置（cs 固定权重 1.0 + strong 全禁 A/B + 双维并存）
已接近该数据窗口的组合最优；无需结构性改动。新信息补充仅一处：
**rt=A cs=A（双强）synA −0.0469（n=264）**——rankTrend 买 + crossSection 高位双强共振
疑似过热，可作后续观察项（样本少，暂不动）。

### 11.5 下一步

- crossSection 投票为**首次核心算法默认变更**（用户决策）；9 月数据累积后复核
  （A 档样本 >500 + 新窗口 synergy 稳定 >0.05）；
- **rt=A cs=A 双强共振**（synA −0.0469，n=264）疑似过热——9 月复核
  （样本 >500 后验证“双强降级”是否成立）；
- 前端四维面板：crossSection/priceMomentum 观察字段可扩展展示（视用户需求）。

## 阶段 12：环境门去噪参数扫描（WP2 2c，2026-09-09）

### 12.1 背景与扫描前缺陷修复

- 2c 目标：对环境门三个去噪参数做单变量扫描（longterm-test 8 步流程）——
  K（lifecycleConfirmFrames∈{2,3}）、α（regimeScoreEmaAlpha∈{0.9,0.75,0.5,0.25}）、
  迟滞（regimeStateHysteresis=True × band∈{2.5,5.0,7.5}）；效果度量 = WP3.2 三类
  翻转率前后对比 + h1 tier 统计（synergy 主 / 关注维 rankTrend，score 公式与阶段 7/8 一致）。
- **扫描暴露实现缺陷（TDD 修复，commit d34f71bb）**：RegimeSmoother 首版非直通路径
  `state = raw_state` 原样透传（缺陷源头是计划文档自身的代码片段），α<1 时 state 不随
  平滑分数变化，违反 spec §2b"state 由 EMA 后的分数判定"。首次扫描四档 α 与 baseline
  逐位一致才暴露。修复后 state 由 EMA 分数按 market_regime 同源阈值（70/50/30）整体
  重判，strong 迟滞带仅叠加在退出侧；直通路径（α≥1 且迟滞关）保持同一引用返回，
  golden 无漂移（smoother 9/9 + golden/门控/引擎回归 70/70）。失效缓存清除后重扫。
- 窗口纪律：决策扫描 2026-04-15~07-31（TRAIN/VAL/TEST，659 帧，`assert_not_frozen`
  守卫，FINAL 8/1-8/14 未进入决策）；准样本外 08-15~08-31（决策期后生成）；未见窗
  09-01~09-09（9/7 前无槽位情绪文档 → EOD stale 回退，各档一致不影响相对比较）。
- harness：`backend/operations/optimize_gate_denoise_parameters.py`（单次 replay 同时
  产出翻转率 + h1 tier 统计；报告 JSON 可 resume；报告落 `data/reports/`，不入库）。

### 12.2 扫描结果（score / synergy saEx / passHard / veto / bd / regime 翻转率）

**决策窗 04-15~07-31**（659 帧 / 132078 信号 / 可比对 129285；regime 翻转为市场级计数/率）：

| 档位 | score | syn saEx | pass | veto | bd | regime |
|---|---|---|---|---|---|---|
| baseline | 1.3623 | 0.0811 | True | 0.12703 | 0.06930 | 0.00142（183 次） |
| K=2 | 1.3077 | 0.0539 | True | 0.02286 | 0.05199 | 0.00142 |
| K=3 | -0.0091 | 0.0454 | **False** | 0.00956 | 0.04248 | 0.00142 |
| α=0.9 / 0.75 / 0.5 / 0.25 | 1.3623 | 0.0811 | True | 0.12703 | 0.06930 | 0.00132 / 0.00116 / 0.00078 / 0.00038（49 次） |
| 迟滞 band 2.5 / 5.0 / 7.5 | 1.3623 | 0.0811 | True | 0.12703 | 0.06930 | 0.00139 / 0.00138（178 次）/ 0.00138 |
| 组合 K2+α0.5+迟滞5 | 1.3077 | 0.0539 | True | 0.02286 | 0.05199 | 0.00073 |

**准样本外 08-15~08-31**（121 帧）：baseline score -0.2963 / saEx 0.0713 / pass False /
veto 0.14314 / bd 0.08083 / regime 0.00096；K=2 → -0.3496 / 0.0447 / veto 0.02548；
K=3 → -0.3720 / 0.0335 / veto 0.00999；α 各档交易指标与 baseline 一致（regime 降至
0.00091/0.00086/0.00055/0.00025）；迟滞三档全部逐位一致。

**未见窗 09-01~09-09**（77 帧）：baseline score -0.3022 / saEx 0.0422 / pass False /
veto 0.14094 / bd 0.07753 / regime 0.00108；K=2 → -0.3406 / 0.0230 / veto 0.02587；
K=3 → -0.3308 / 0.0279 / veto 0.01117；α 各档交易指标与 baseline 一致（regime 降至
0.00108/0.00098/0.00078/0.00020）；迟滞三档全部逐位一致。

### 12.3 机制解释（决策窗诊断，`extract_gate_states` 口径）

- **veto/bd 翻转源自 lifecycle 门控，与 regime state 无关**——三参数中只有 K 能动它
  （K=2/3 使 veto 翻转 -82%/-92%）；α/迟滞的 veto/bd 计数三窗完全一致（16423/8960）。
- α 平滑实际大幅改变 state 流：baseline 信号级分布 weak 35589 / normal 74323 /
  retreat 2833 / strong 19333，strong 边界转换 43 次；α=0.25 下 28% 信号 state 变化，
  strong 降至 9416、边界转换 11 次、retreat 归零。迟滞则延长 strong 保持
  （19333→21407 信号）。
- 但 h1 聚合统计 4 位小数下不可分辨：regime strong 禁入 A/B 仅边缘生效——strong 期间
  档位实际全为 D_EXIT_RISK 8354 / N_NEUTRAL 9785 / C_CROWDED 1194（A/B=0，上游
  crowded/exit 条件先于禁入命中）；α=0.25 仅改变 1150/132078=0.87% 档位赋值，不足以
  移动 synergy/rankTrend 的 saEx 与 passHard。
- 组合验证：K2+α0.5+迟滞5 与 K=2 单变量交易指标逐位一致 → α/迟滞与 K 无交互。

### 12.4 四类判定

| 参数 | 判定 | 依据 |
|---|---|---|
| lifecycleConfirmFrames（K=2/3） | **证伪** | 去噪收益真实（veto 翻转大幅下降）但 synergy saEx 三窗一致单调恶化（0.0811→0.0539→0.0454；0.0713→0.0447→0.0335；0.0422→0.0230→0.0279），OOS 两窗全部 <0.05、K=3 决策窗掉 passHard——被滤掉的"单帧噪声 veto"里含真实信息 |
| regimeScoreEmaAlpha（α<1） | **冗余**（采纳口径） | 交易指标三窗与默认一致、无 synergy 改善；展示层 state 去噪有效（market 翻转 183→49），保留为可调参数 |
| regimeStateHysteresis + band | **冗余** | OOS 两窗逐位一致，决策窗仅 regime 翻转微降（183→178）；strong 保持效应存在但不产生采纳收益 |
| regimeStrongHysteresisBand | 跟随迟滞 | 同上 |

- **默认值全部不变**（K=1 / α=1.0 / 迟滞关）；golden 无漂移。
- 采纳判定门槛（spec §2c）无人达标：需"干净窗口样本外 synergy saEx ≥0.05 且 passHard
  且跨窗稳健"，仅 baseline 决策窗自身满足，任何去噪档位均未改善。
- 复核触发：regime 门禁扩展消费非 strong 状态时重扫 α/迟滞；K 结论随 9 月数据按
  L1 §6 滚动重验。
- 同步记录：L1 台账 §7 四参数状态已更新（含缺陷修复 commit d34f71bb 注记）。

## 阶段 13：趋势因子参数补扫（2026-09-09）

### 13.1 背景（用户审阅发现台账缺口）

- 用户指出 L1 台账 §2 核心信号参数缺趋势维度 MA/MACD/zeroCross——核实结论：
  ① 8.4 已扫的 8 个参数（方向/加速度/zeroCross confirm/MACD 金叉侧阈值）当时未录入
  台账（文档债，已补 §2b）；② MACD 周期本体（macdFast/Slow/Signal）、死叉侧 3 参数、
  zeroCross 合成 2 参数、buyScoreThreshold/sellScoreThreshold 确实从未扫描；
  ③ **MA5/MA10 裁定为显示字段不扫**：technical.py `movingAverage` 全后端无决策消费方
  （不进 direction/acceleration/zeroCross/macd 信号与档位判定），趋势维决策主承载是
  momentumPeriods（8.6 已扫）与 direction 阈值（8.4 已扫）。
- 无生产代码改动（全部参数已在 config），纯扫描 + 台账补全。
- harness：`backend/operations/optimize_trend_factor_parameters.py`（复用
  `evaluate_gate` 口径：h1 tier score + WP3.2 三类翻转率；窗口纪律同阶段 12）。

### 13.2 扫描结果（20 档 × 三窗口；score / synergy saEx）

**决策窗 04-15~07-31**（baseline score 1.3623 / saEx 0.0811 / pass True）：

| 组 | 档位 → score（saEx） |
|---|---|
| MACD 周期 | Fast 11→1.3630(0.0815) / 15→1.3624(0.0812)；Slow 17→1.3629(0.0815) / **26→1.3591(0.0795) 最差**；Signal 5→1.3624(0.0812) / 12→1.3631(0.0815) |
| 死叉侧 | deathScale 0.06→1.3623 / 0.24→1.3626；deathStrong 0.10 / 0.26 → **1.3623 逐位一致**；rawW [0.5,0.5]→1.3623 / [0.9,0.1]→1.3624 |
| zeroCross | zeroW [0.6,0.4]→1.3628 / [0.8,0.2]→1.3624；bonus 0 / 10 → **1.3623 逐位一致** |
| 决策阈值 | **buyThr 0.08→1.3616(0.0808) / 0.18→1.3699(0.0849) 最大变动**；sellThr −0.08→1.3623 / −0.18→1.3626 |

**OOS-1 08-15~08-31**（baseline −0.2963 / 0.0713）：buyThr=0.18 → −0.2926 / **0.0732**（同向改善，bd 0.0808→0.0783）；macdSlow=26 → −0.2592（score 最好但 saEx 0.0706 微降）；其余 ±0.005 内。

**OOS-2 09-01~09-09**（baseline −0.3022 / 0.0422）：**buyThr=0.18 → −0.3051 / 0.0407（反向）**；macdSlow=26 → −0.0085 / 0.0458（score 大幅改善由 trend 维驱动，与决策窗方向矛盾）；macdFast=15 → −0.2510 / 0.0431；其余平坦。

### 13.3 四类判定

| 参数 | 判定 | 依据 |
|---|---|---|
| MACD 周期（Fast/Slow/Signal） | **冗余** | 决策窗各档波动 <±0.25%；macdSlow=26 跨窗方向矛盾（决策窗最差 vs OOS 最好）不采纳 |
| 死叉侧（deathScale/deathStrong/rawW） | **冗余** | deathStrong 两档三窗逐位一致（零效应）；其余微弱 |
| zeroCross（zeroW/bonus） | **冗余** | bonus 三窗逐位一致（复现 8.4 confidence-only 结论）；zeroW ±0.0005 |
| buyScoreThreshold | **缺复核** | 0.18 两窗同向（决策窗 +0.0076、OOS-1 +0.0037）但 OOS-2 反向（−0.0029），幅度 <0.5% saEx，不满足"跨窗稳健"+passHard 门槛；9 月样本扩展后复扫 |
| sellScoreThreshold | **冗余** | 各档平坦 |
| buyThr=0.18 采纳判定 | 不采纳 | baseline 自身 OOS passHard=False 未解决；0.18 不改变 passHard 任何窗口 |

- **默认值全部不变**；golden 无漂移（无生产代码改动）。
- **平坦机制**：MACD 仅以二值金叉参与 trend_buy（`direction buy OR acceleration buy
  OR macd golden` 三选一 OR 之一），gap 阈值/权重只动 rawScore/confidence 展示层；
  周期参数虽改变金叉时机，但被 OR 结构与档位上游条件（stage/momentum）稀释。
  buyScoreThreshold 消费于决策合成（runtime L298-307），对档位/翻转率同样边缘生效。
- **实盘观察的对齐说明**：趋势维"信号重要"的决策承载是 momentumPeriods + direction
  阈值（已扫，8.4/8.6）与 crossSection 投票（已上线）；MACD/zeroCross 参数面在当前
  结构下对采纳指标近乎无感——这与实盘体感不矛盾（实盘看到的是信号输出，不是参数
  弹性）。
- 复核触发：buyThr=0.18 随 9 月样本扩展复扫（与 crossSection 复核、双强降级验证
  同批，见 §11.5/阶段 12 触发条件）。

## 阶段 14：OOS 失败解剖复核——regime 分桶 × saEx 分解（2026-09-10）

### 14.1 背景与方法

- OOS-1/OOS-2 两窗 baseline passHard=False、score 为负。会话解剖提出三机制假说：
  ① 决策窗 strong 内部本就塌陷（A 档 exAcc≈0、B>A 反序、saEx 0.0224），OOS-2 strong
  占比 15%→25.7% 放大拖累；② OOS-1 唯一反序 A>S（"好消息型失败"）；③ B/C/D 三窗
  一致无区分度。本阶段用 regime 分桶分解逐项复核后落盘。
- harness：`backend/operations/diagnose_regime_saex_decomposition.py`（只读诊断）。
  baseline replay（`RankTrendPythonEngine(config=RankTrendConfig()).replay(frames, meta={})`）
  → 按 `rankTrend.strategy.regime.state`（市场级，同帧全股相同）分桶 → 每桶
  `tier_forward_returns(horizon=1, dimension="synergy", signal_filter=...)`（分位桶基线
  在桶内重算）→ raw directionAccuracy 按桶×样本数加权重构校验 + 逐日 strong 帧占比表。
  报告：`data/reports/regime-saex-decomposition.json`。
- 样本覆盖说明（fail-visible）：replay 有 warm-up（`get_technical_min_samples`≥30 →
  前 29 帧不产出信号，引擎设计行为非数据缺失）。OOS-2 加载 77 帧但信号实际覆盖
  09-03~09-09 五天（09-01/09-02 的 22 帧为热身）；阶段 12/13 同口径，可比性不受影响。

### 14.2 三窗分解结果（桶内 saEx / S、A 档 exAcc / 反序）

**ALL 对照**（与阶段 12 报告一致）：决策窗 0.0811 pass=True / OOS-1 0.0713 pass=False /
OOS-2 0.0422 pass=False；OOS-2 spearman=1.0（无反序）。

| 窗口 | state | 信号占比 | saEx | S exAcc (n) | A exAcc (n) | 反序 |
|---|---|---|---|---|---|---|
| 决策窗 | normal | 56.3% | 0.0988 | 0.1183 (795) | 0.0904 (1830) | 无（spearman 1.0，pass=True） |
| 决策窗 | weak | 27.0% | 0.0684 | 0.1029 (503) | 0.0525 (1092) | 无（pass=True） |
| 决策窗 | strong | 14.6% | **0.0224** | 0.0788 (222) | **0.0001 (562)** | B>A gap 0.0022（pass=False） |
| 决策窗 | retreat | 2.1% | 0.1888 | 0.0921 (88) | 0.2655 (111) | A>S gap 0.0129 |
| OOS-1 | normal | 76.3% | 0.0908 | 0.0408 (179) | 0.1091 (490) | **A>S gap 0.0085** |
| OOS-1 | weak | 12.1% | **-0.0659** | **-0.1216 (33)** | -0.0397 (70) | A>S、B>A |
| OOS-1 | strong | 9.4% | **0.1139** | **0.1943 (29)** | 0.0888 (93) | 无（spearman 1.0） |
| OOS-1 | retreat | 2.2% | 0.0242 | 0.0777 (15) | -0.0045 (28) | 无 |
| OOS-2 | normal | 66.4% | 0.0676 | 0.1468 (81) | 0.0307 (174) | B>A gap 0.0025 |
| OOS-2 | weak | 5.8% | **-0.0406** | 0.0143 (33) | -0.0938 (34) | A>S gap 0.0014 |
| OOS-2 | strong | 25.7% | **0.0271** | 0.0226 (38) | 0.0285 (125) | A>S gap 0.0019（spearman -0.5） |
| OOS-2 | retreat | 2.1% | —（S=0，A n=1 不足） | — | — | — |

- raw directionAccuracy 加权重构：三窗 S/A/B 全部 match=true（桶划分完备的数学证明）。
- exAcc 不可跨桶线性重构（分位桶基线桶内重算）；saEx 近似加权和与 ALL 的残差即
  基线组间差异（OOS-2 ≈0.0495 vs 0.0422）。
- 逐日表（详见报告 JSON）：strong 占比高日 saEx 有偏低倾向但非决定论——决策窗
  5/6 占比 0.9→saEx 0.0688、6/25 占比 0.2→0.2646 为反例；7 月末股灾日
  （7/29~7/31 占比 0.18~1.0）saEx -0.10~-0.14；OOS-2 内 9/7（占比 0.73→0.0343）、
  9/8（0.36→0.0147）低于 strong=0% 的 9/4（0.0799）、9/9（0.0961），9/3 反例
  （占比 0→-0.0667）。

### 14.3 解剖假说核对结论

| 假说 | 判定 | 复核依据 |
|---|---|---|
| ① strong 塌陷 × 占比放大拖累 OOS-2 | **确认（带边界修正）** | 决策窗 strong saEx 0.0224/A exAcc 0.0001/B>A 精确复现；OOS-2 strong 0.0271 拖累 ALL 至 0.0422。**但 OOS-1 strong 不塌陷反而全窗最强（0.1139，S exAcc 0.1943）——strong 状态非同质** |
| ② OOS-1 A>S 反序（好消息型失败） | **确认** | normal 桶 A>S gap 0.0085 精确复现；A 档 0.0853 强于决策窗 A（0.0699）。另 retreat（决策窗 0.0129）与 weak/strong 桶内亦有微弱 A>S |
| ③ B/C/D 三窗无区分度 | **确认** | B 档三窗各桶 exAcc ∈ [-0.027, +0.011]，C 更弱或为负；体系价值集中 S/A |

**新增发现（超出原解剖）**：

1. **strong 状态是双峰的**：塌陷（决策窗 A 档死、OOS-2 S/A 皆弱）与强劲（OOS-1 全窗
   最强）并存，8/27 strong 占比 0.73 的交易日 saEx 0.0625 也不差。塌陷与 strong 期
   结构（持续时长/上游 crowded·exit 触发/市况性质）有关，非状态本身决定。
2. **OOS-2 strong 期 exMean 全负**（S -0.0040 / A -0.0021 / B -0.0038，分位基线
   0.42 亦低于 normal 0.44-0.45）：strong 期追强是负 alpha（高位拥挤/均值回归）。
   OOS-2 失败是"量"的失败（saEx 距 0.05 门槛的缺口），不是"序"的失败（spearman 1.0）。
3. **OOS-1 的失败源与 strong 无关**：weak 桶 S exAcc -0.1216（acc 0.2424，弱市追强
   强负 alpha）+ normal 桶 A>S 反序。
4. **决策窗 ALL pass=True 的掩盖被定量证实**：同窗 strong 桶 passHard=False
   （saEx 0.0224 + B>A），ALL 被 normal/weak 的体量稀释——分状态报告的必要性成立。

### 14.4 对结构性方案的修正意见（评估结论，未实施）

- **"strong 下放宽 S≥A≥B 硬序"不对症，不采纳**：OOS-2 失败是量不是序（放宽硬序
  不能补 saEx 0.0271→0.05 的缺口）；OOS-1 strong 序完全正常（放宽无对象）；决策窗
  strong 反序 gap 仅 0.0022（修正价值微小）。
- **"strong 期一刀切降级/禁入"同样不采纳**：OOS-1 strong 是全窗最好的桶
  （0.1139），禁入将错过 8/27 类交易日。
- **站稳的方向**（后续课题，需另行设计评审）：
  1. 寻找区分"塌陷 strong / 强劲 strong"的可观测变量（上游 crowded/exit 触发状态、
     strong 持续时长、市况内部结构），先做分状态观察研究再谈门控；
  2. passHard 分状态诊断报告（原队列 3）：决策窗 ALL=True 掩盖 strong=False 的盲区
     已定量证实，属评估基建改造，不动生产判定；
  3. 接受体系价值边界：S/A 价值集中在 normal/weak 期与部分 strong 期，weak 期追强
     的负 alpha（OOS-1 S exAcc -0.1216）本身是独立研究课题。
- 默认值零变更；golden 无漂移（无生产代码改动，纯只读诊断）。

### 14.5 遗留与复核触发

- 9/10 当天快照未入库（当日查询 0 帧）；9 月数据累积后 OOS-2 结论随队列 4 复扫
  （buyThr=0.18 / crossSection）同批滚动重验。
- cs tier 提取路径修复 + §11.5 双强降级复核（原队列 2）不受本阶段影响，仍待执行。
- 9/1、9/2 无槽位情绪文档（EOD stale 回退）+ warm-up 覆盖：OOS-2 有效样本 5 天，
  月内数据扩展后 n<500 的桶（本阶段 strong S n=38、OOS-1 retreat n=15 等）结论
  保持观察级。


## 阶段 15：§11.5 双强降级复核——口径澄清与三窗重判（2026-09-10，原队列 2）

### 15.1 口径澄清（上会话"cs tier 提取路径不对"的真相）

- **cs tier 提取本身无问题**：`tier_signal_of(signal, "crossSection")` 走
  `DIMENSION_PATHS` 公开路径（`rankTrend.observation.crossSection.signalTier`），
  决策窗 132078 信号 0 缺失（A 1692 / B 41309 / C 82567 / D 6510）。
- **真正的口径差是 synA 交集**：§11.4f 的 n=264 是 **synA ∩ rt=A ∩ cs=A**（先圈
  synergy=A 档，再交叉 rt×cs），不是 rt×cs 共现全集——rt=A × cs=A 信号级共现
  838/132078=0.63%，与 §11.4f "A×A 共现仅 0.6%" 精确吻合。上会话直接用共现全集
  复核所以测不到。
- 本次决策窗双强有效样本 233（vs §11.4f 264，差 12%：8/19 后引擎有修复
  ——RegimeSmoother d34f71bb 等影响 gate→veto→syn tier 分布），量级一致可对照。

### 15.2 方法与一个重要统计口径认知

- harness：`backend/operations/diagnose_dual_strength_syna.py`（只读，报告落
  `data/reports/dual-strength-syna-review.json`）。分组统计复用
  `tier_forward_returns(signal_filter=...)`，h1、synergy 主口径。
- **分桶基线塌缩认知**：`tier_forward_returns` 的 signal_filter 基线是"过滤后同口径
  重算"（`tests/test_tier_monotonicity.py::test_tier_forward_returns_signal_filter_buckets`
  锁定的合同行为）。synA 信号全集中在最高分位段 → 同质小组（synA ∩ rt=A × cs=X）
  的分位桶基线退化为组自身 → 组内 excess 恒 0，无信息量。该口径仅对覆盖全分位段的
  大组有意义（阶段 14 regime 分桶未受影响）。**主判定口径改用原始
  meanFutureReturn / directionAccuracy 组间差**（同 synA 同 rt=A 背景下均值回归
  背景近似相同，组间原始差即 cs 维增量信息）。
- §11.4f 的 −0.0469 统计口径无存档脚本可考（当时为会话内临时统计），按当前可复现
  口径重判，不复现过期数字。

### 15.3 三窗结果（synA 内 rt=A 行按 cs 分层，原始 h1 口径）

| 组 | 决策窗 n / dirAcc / meanRet | OOS-1 n / dirAcc / meanRet | OOS-2 n / dirAcc / meanRet |
|---|---|---|---|
| 双强 cs=A | 233 / 0.4378 / −0.0061 | 32 / 0.2812 / −0.0102 | 18 / 0.3333 / −0.0077 |
| cs=B | 803 / 0.4471 / −0.0096 | 114 / 0.4474 / −0.0186 | 47 / 0.5319 / −0.0089 |
| cs=C | 259 / 0.4749 / −0.0074 | 57 / 0.4561 / −0.0378 | 33 / 0.3939 / −0.0474 |
| rt=A 全 cs | 1295 / 0.4510 / −0.0086 | 203 / 0.4236 / −0.0227 | 98 / 0.4490 / −0.0216 |
| synA 全体 | 3595 / 0.4498 / −0.0055 | 681 / 0.5066 / −0.0133 | 334 / 0.4551 / −0.0248 |

- meanRet(csA−csC)：决策窗 +0.0013 / OOS-1 +0.0276 / OOS-2 +0.0397——**三窗一致
  非负，双强不比 cs=C 差，OOS 两窗反而更好**。三窗合并加权复核（样本数加权）：
  csA −0.0067（n=283）vs csC −0.0161（n=349），合并差 +0.0095，方向不变。
- dirAcc(csA−csC)：三窗均为负（−0.0371 / −0.1749 / −0.0606）——双强方向精度一致
  偏低但收益不弱（追强档位靠少数大赢单机制；OOS-1 差值 n=32 无统计意义）。
- regime 视图样本不足（双强@strong：决策窗 12 / OOS-1 2 / OOS-2 1），"strong 期
  双强更差"与阶段 14 双峰假说的交叉检验**无法进行**，如实记录不强行解读。

### 15.4 判定

- **正式判定：缺复核**——三窗双强有效样本合计 283 < §11.5 触发线 500。
- **方向证据不支持"双强降级"**：可获得样本上三窗 meanRet 全部 csA≥csC，无一个窗
  支持过热降级；§11.4f −0.0469 在可复现口径下不复现（决策窗 csA meanRet 仅 −0.0061）。
  若样本累积后仍维持该方向，将转为正式证伪。
- **默认值零变更**；触发线维持 n>500。按 OOS 双强共现速率（OOS-2 约 3.6/日），自然
  累积到 500 需一年以上——建议后续复扫改为"三窗合并滚动统计"（合并 283+新累积），
  或接受该观察项长期挂起为低优先级。
- 队列 2 就此收口：cs tier 提取路径确认无缺陷（tier_signal_of 合同正常），§11.5
  复核以"缺复核 + 现有证据方向相反"落盘。队列 3（passHard 分状态诊断报告）与
  队列 4（buyThr=0.18 / crossSection 随 9 月数据复扫）保持待办。


## 阶段 16：passHard 分状态诊断视图接入评估基建（2026-09-10，原队列 3）

### 16.1 背景与目标

阶段 14 定量证实：决策窗 ALL passHard=True 掩盖同窗 strong 桶 passHard=False
（ALL 被 normal/weak 体量稀释）。本阶段把分状态视图从一次性诊断脚本
（diagnose_regime_saex_decomposition.py）提升为评估基建的常驻输出——未来任何
gate/tier 扫描的报告自动带上分状态摘要，防"均值掩盖"复发。评估基建改造，
不动生产判定。

### 16.2 改动（TDD）

- 新增纯函数模块 `backend/analysis/ranktrend/research/regime_saex.py`：
  `regime_saex_stats(signals, frames, horizon, dimension)` 按 market regime state
  分桶输出 tier_forward_returns 统计集合；state 走 extract_gate_states 公开路径；
  state 缺失信号计入 `<missing>` 计数不产出桶（fail-visible）；桶内 passHard 为
  桶内口径（样本不足 S<30 如实判 False，与阶段 14 口径一致）。
  测试 `tests/test_regime_saex.py` 4 例：路径读取/分桶守恒/缺失计数/空信号。
- 接线 `backend/operations/optimize_gate_denoise_parameters.py`：
  `evaluate_gate` result 新增 `regimeView`（synergy 主口径分状态 _tier_summary）
  与 `regimeStateCounts`；`_fmt` 打印分状态摘要（旧缓存报告 resume 缺该字段时
  不打印，不崩）。rankTrend 关注维不重复分桶（控制扫描成本）。

### 16.3 接线自检（decision 窗 baseline-only，659 帧）

- ALL 口径与阶段 12 baseline **逐位一致**：score=1.3623 / syn saEx=0.0811 /
  pass=True / flip(veto=0.12703 bd=0.06930 regime=0.00142)——接线未破坏原口径。
- 分状态视图与阶段 14 **逐位一致**：weak 0.0684 / normal 0.0988 / retreat 0.1888 /
  **strong 0.0224 pass=False**——掩盖的盲区现在直接出现在扫描打印里。
  retreat pass=False 属样本不足型（S<30），按 distribution 区分。
- pytest：`test_regime_saex` 4 例 + tier 相关回归 22 例全绿；全量 collect-only
  1990 collected 无 import 断裂。

### 16.4 边界与遗留

- 默认值零变更；golden 无漂移（新增纯函数 + harness 输出字段，无生产判定改动）。
- 旧扫描缓存报告（阶段 12/13 的 gate-denoise-scan JSON）不含 regimeView，重跑
  对应档位即可补齐；score 判定字段不受影响。
- 队列 3 就此收口。队列 4（buyThr=0.18 / crossSection 复扫）等 9 月数据累积，
  复扫时自动产出分状态视图。

## 阶段 17：均线 MA10×MA20 交叉因子贡献度评估——与 MACD 同台对比（2026-09-12）

### 17.1 背景（用户命题）

用户审阅 RankTrend 观察弹窗技术结构（四子分：方向一致性/多周期加速度/零线交叉/MACD）后
提出：技术结构漏了均线 MA 因子，趋势技术结构进展不明显，要求评估 MA（参数定 10/20）与
MACD 在回测中的贡献度，决定是否加入技术信号。

与阶段 13 裁定的差异：MA5/MA10（`movingAverage` 显示字段）因全后端无决策消费方而"不参数化
不扫描"；本次是新增**有决策消费方**的 MA10×MA20 交叉因子（排名百分位序列上的快慢均线金叉/
死叉，与 MACD 同输入、同二值交叉参与语义），从零实现并三窗口评估。

### 17.2 因子实现与零漂移保障（TDD，four-dim-algorithm-research 步骤 1）

- 纯函数 `backend/analysis/ranktrend/trend/technical.py::calculate_ma_cross(percentiles, config)`：
  fast/slow = 排名百分位序列简单均线（maFastPeriod/maSlowPeriod，默认 10/20）；样本不足
  （len < slow）→ fast/slow=None、state="unknown"（fail-visible 不伪造 0）；rawScore 仅交叉帧
  ±1（golden +1 / death −1），其余 0——镜像 MACD 二值参与语义；强度加权有意省略（阶段 13
  实证 MACD gap 阈值面全冗余，不引入新参数）。
- `RankTrendConfig` 新增 4 字段：`maFastPeriod=10` / `maSlowPeriod=20` / `maWeight=0.0` /
  `maCrossTrendBuy=False`；from_patch 校验周期 ≥1、slow≤fast 自动修正（镜像 MACD），
  归一化总权重计入 maWeight（=0 时归一化结果与今日逐位一致）。
- 三处接线（默认全关）：compose_decision 第 5 分量（maWeight>0 才追加，避免 buy_count
  计数漂移）；compose_strategy 与 compose_analysis_candidate_tier 的 trend_buy OR 链
  （maCrossTrendBuy=True 才参与）。
- 测试 `tests/test_ranktrend_ma_cross_factor.py` 11 例（默认值/交叉检测/样本不足/参数生效/
  周期修复/接线生效/零漂移/缺字段容忍）；golden alignment 10 例 + MA 11 例 = 21 passed。
  **默认值零变更，golden 逐位不漂移。**

### 17.3 评估方法（三口径 × 三窗口，评估 harness `backend/operations/evaluate_ma_factor_contribution.py`）

- A 事件级：MA 金叉/死叉帧 vs MACD 金叉/死叉帧子集 h1 synergy saEx（tier_forward_returns +
  signal_filter，分位桶基线子集内重算，与阶段 14 regime 分桶同口径）；
- B 状态级：MA 多头排列(fast>slow) vs MACD 多头(dif>dea) 同上；
- C 边际贡献：evaluate_gate 7 组 trial——baseline / macd_off / ma_join（MA 第 5 分量并存）/
  ma_replace（MA 替代 MACD 决策分量）/ ma_replace_full（+trend_buy 位）/ ma_trendbuy /
  ma_full；权重类走 from_patch 5 权重归一化保证同量纲。
- 窗口纪律沿用阶段 13/14：决策窗 04-15~07-31（655 帧）、OOS-1 08-15~08-31（110 帧）、
  OOS-2 09-01~09-09（70 帧）；FINAL(8/1-8/14) 冻结（assert_not_frozen purpose=scan）。
  报告 `data/reports/ma-factor-contribution.json`（增量落盘可 resume）。

### 17.4 事件级/状态级区分度（h1 synergy saEx / n / passHard）

| 子集 | 决策窗 | OOS-1 | OOS-2 |
|---|---|---|---|
| all | 0.0821 / 115724 / T | 0.0654 / 16023 / F | 0.0568 / 8021 / T |
| MA 金叉事件 | **0.0899 / 2384 / T** | 0.0141 / 361 / F | **0.0411 / 160 / F** |
| MACD 金叉事件 | 0.0834 / 2616 / F | 0.0240 / 400 / F | **−0.0716 / 184 / F** |
| MA 死叉事件 | 0.0398 / 2739 / F | −0.1178 / 389 / F | None / 198 / F |
| MACD 死叉事件 | None / 3071 / F | None / 498 / F | None / 241 / F |
| MA 多头排列 | 0.0873 / 33294 / T | 0.0308 / 4597 / F | 0.0595 / 2389 / T |
| MA 空头排列 | 0.0847 / 41753 / T | 0.0868 / 6438 / F | −0.0148 / 3063 / F |
| MACD 多头 | 0.0888 / 32194 / T | 0.0562 / 4628 / F | 0.0515 / 2149 / F |
| MACD 空头 | 0.0997 / 41433 / T | 0.0861 / 6250 / F | 0.0402 / 3223 / F |
| 两者同帧金叉 | 0.0439 / 80 / F | 0.3888 / 14 / F | None / 4 / F |

- **MA 金叉事件三窗口均 ≥0 且 2/3 窗口优于 MACD 金叉**（决策窗 0.0899 过硬门 vs MACD
  0.0834 未过；OOS-2 +0.041 vs −0.072；OOS-1 打平均弱、全窗市场性走弱）。
- 事件重叠仅 3-4%（决策窗 both=84/maGolden=2504=3.4%；OOS-1 3.7%；OOS-2 2.4%）——
  MA 不是 MACD 的影子，是独立事件源。
- **MACD 金叉事件 OOS-2 负超额 −0.0716**：与阶段 13"MACD 参数面全冗余"互证，事件级也现疑点。
- 决策窗 MACD 多空状态反序复现（bear 0.0997 > bull 0.0888，与阶段 13 结论一致）；
  MA 状态级区分度弱（bull 0.0873 ≈ bear 0.0847）。
- saEx=None 均为 spearman=±1.0 完全单调/反单调下的统计退化（如决策窗 MACD 死叉反单调、
  死叉帧 52-68% 集中 D 档——单调方向本身正确），非数据缺失；OOS-2 both_golden 仅 4 样本降级观察。
- unknown 率：MA 36-39%（样本不足 20 帧的短历史标的），与 MACD 同量级，如实披露。

### 17.5 边际贡献（evaluate_gate 7 组 trial，score / syn saEx / trend saEx）

| trial | 决策窗 | OOS-1 | OOS-2 |
|---|---|---|---|
| baseline | 1.3642 / 0.0821 T / 0.0565 | −0.3275 / 0.0654 F / 0.0342 | 1.3135 / 0.0568 T / 0.0540 |
| macd_off | 1.1167 / 0.0803 T / 0.0456 | −0.4005 / 0.0657 F / 0.0268 | 0.9946 / 0.0544 T / 0.0386 |
| ma_join | 1.3671 / 0.0835 T / 0.0611 | 0.0314 / 0.0657 F / 0.0514 | 1.0471 / 0.0556 T / 0.0436 |
| ma_replace | 1.3601 / 0.0801 T / 0.0539 | −0.3214 / 0.0670 F / 0.0345 | 1.1112 / 0.0582 T / 0.0495 |
| ma_replace_full | 同 ma_replace 逐位 | 同 ma_replace 逐位 | 同 ma_replace 逐位 |
| ma_trendbuy | 同 baseline 逐位 | 同 baseline 逐位 | 同 baseline 逐位 |
| ma_full | 同 ma_join 逐位 | 同 ma_join 逐位 | 同 ma_join 逐位 |

机制解释（数据驱动）：

- **ma_join score 摆动被 trend pass(0.05) 线二值放大**：连续效应量 = trend saEx Δ 仅
  +0.0046 / +0.0172 / −0.0104（决策窗/OOS-1/OOS-2，2 正 1 负）；OOS-1 从 0.0342 跨线到
  0.0514 拿回 +0.2（score −0.33→+0.03），OOS-2 从 0.0540 跌线到 0.0436 失去 0.2
  （score 1.31→1.05）。表面 ±0.3 的摆动主体是门槛效应，不是 MA 本身的稳定增益。
- **trend_buy 接线位零增量的机制**：MA 金叉帧 64.9%/65.2%/67.6% 已被既有 OR 链
  （direction buy / acceleration buy / MACD 金叉）覆盖；其余 ~35% 帧的 trend_buy 变化
  未传导到候选分层/决策指标（其余门条件未满足）。
- macd_off 三窗口全受损（score −0.25/−0.07/−0.32，trend saEx 全降）→ MACD 决策分量证实有效。
- ma_replace 一致优于 macd_off（+0.24/+0.08/+0.12）→ MA 作为决策分量的信号质量不差；
  但 vs baseline：决策窗 −0.004、OOS-1 +0.006、OOS-2 **−0.20** → 替代不划算。

### 17.6 四类判定

| 命题 | 判定 | 依据 |
|---|---|---|
| MACD 决策分量保留 | **证实** | macd_off 三窗全受损，trend saEx 全降 |
| MA 替代 MACD | **证伪** | OOS-2 score −0.20；虽一致优于 macd_off，替代不如共存 |
| trend_buy 接线位（maCrossTrendBuy） | **冗余** | 4 组对照（含共存/替代两场景）三窗逐位一致；65% 事件帧已被覆盖 |
| MA 共存第 5 分量（ma_join） | **缺复核，暂不采纳** | 连续效应量 ±0.01 量级且 2 正 1 负；score 摆动主体是 pass 线二值放大 |
| MA 金叉事件独立信息 | **证实** | 三窗重叠仅 3-4%；事件质量 2/3 窗优于 MACD 金叉、1/3 打平 |

**结论（回答用户命题）**：MA10×MA20 因子**暂不加入技术信号默认链**。事件级证据支持
"MA 金叉有独立信息且质量不劣于 MACD"，但决策级边际贡献小、跨窗口不稳定，不满足
"正贡献仅成候选默认值"的稳定标准。实现与接线全部保留（默认全关），随时可从 patch
开启复核，golden 零漂移。

### 17.7 遗留与复核触发

- 复核触发一：OOS-2"MACD 金叉事件负超额（−0.0716）"若在 9 月后续数据中复现，
  优先重估"MA 替换 MACD 决策分量"（ma_replace 路线），而非 ma_join 共存。
- 复核触发二：9 月样本扩展后（OOS-2 当前仅 70 帧/8021 信号）重跑 ma_join 三窗口，
  观察 trend saEx 连续效应量是否收敛为一致正。
- 事件级用法（金叉事件作为独立加分项而非决策权重）未评估，留待后续队列。
- 前端链路（技术结构面板 MA 子分展示）按 skill 步骤 8 仅在采纳后处理，当前不做。
- 报告：`data/reports/ma-factor-contribution.json`（7 trial × 3 窗 + 11 子集 × 3 窗，
  含 fail-visible 的 unknown 率与 saEx=None 退化说明）。

### 17.8 附带收口：avgRankNum 重排口径合一（2026-09-12，防口径漂移）

MA 因子评估引出的口径审计：avgRankNum→序号/百分位在 Python 端存在两份等价实现
（`frame_cross_section` 横截面环境门 vs `attention_rank_lookup + percentile_rank` 趋势
replay/routes 权威口径），过滤（finite>0）、排序键 `(avgRankNum, code)` 升序、百分位
公式（先除后乘，1 ULP 级）逐位一致但代码重复，存在漂移风险。avgRankNum 是核心资产
（全量化计算原始材料），收口如下：

- **Python 端 2→1**：`frame_cross_section` 重构为委托 `attention_rank_lookup +
  percentile_rank`（runtime.py，import 原已存在）；rank=idx+1 代入 percentile_rank
  与原实现逐位一致。三处调用方（frame_market_median / frame_market_median_percentile）
  零改动。
- **回归护栏**：新增 `tests/test_avg_ranknum_percentile_unification.py` 6 例——
  与权威口径等价、锚点值（锁先除后乘计算顺序，golden 逐位对齐下计算顺序即合同）、
  tie-break、脏数据过滤（缺失/非数值/≤0/NaN/Inf/空 code/非 dict 行）、空池/单元素、
  percentile_rank 守卫。
- **全链路侦察结论**（消费端非重排语义不动）：comprehensive_rank（五维合成）、
  回测退出判据（avgRankNum 相对恶化）、存储透传/门禁/migration、main.py warmup
  组装——不涉及重排口径，无合并对象。routes 两处（current 帧/attention series）
  原本已复用权威实现；crossSection 第 5 维消费的 percentile 亦来自该口径。
- **TS 端第三份实现**（`src/services/dataLoader/RankTrendSignalService.ts::
  buildAttentionRankMap`）与 Python 权威口径同构，tie-break 为 `localeCompare`
  （6 位数字 code 下与码点比较等价）。**运行时角色澄清（2026-09-12 用户复核指出）**：
  前端 golden 计算链已全部切至 Python analyze API（RankTrendAnalyzer.ts
  "前端不再保留本地 golden 计算链"，analysisSource='py_golden'），该函数不是 golden——
  rank 值仅两处残存用途：① getRankTrends 入参只取 code 列表（rank 不发送，后端用
  G3 权威算法自算）；② stock.attentionRank 仅作 RankTrendPanel 展示排序第三级
  fallback（attentionRank ?? meta.currentRank ?? rank）。过滤口径（isFinite && >0）
  两端语义一致，漂移影响面 = 展示排序兜底次序，非分析计算。本次不动。
- 验证：新口径 6 例 + replay_resonance + golden alignment + MA + api authoritative
  + analyze_api = 59 passed；全量 collect-only 2083 collected 无 import 断裂。
  默认值零变更、API/存储合同零变更。

## 阶段 18：crossSection 持续高位 A 档替代路径实证——H2 证伪不落默认（2026-09-13）

### 18.1 背景（用户命题 + 方案1 修复后的数学边界）

用户实盘观察热度（crossSection）A 档从未出现。方案1（2026-09-13 delta 复活修复，
commit bb04c0a9）解决了两条供给链路的 delta≡0（入库同帧重复 append + live 复制尾），
但数学边界仍在：delta = pct[-1] − pct[-2] ≤ 100 − pct[-1]，pct > 95 的强势股
（榜首 pct=100）永远无法满足 A 档 delta≥5 上升确认——它们没有"继续上升"的空间，
强势体现在"持续停留高位"。方案2 给 A 档加替代路径并实证其信息量是否撑得起 strong 票。

### 18.2 因子实现与零漂移保障（TDD，four-dim-algorithm-research 步骤 1）

- `compute_cross_section` 新增持续高位分支：pct ≥ `crossSectionPersistMin`(90) 且
  近 `crossSectionPersistFrames` 帧 attention percentile 均值 ≥ `crossSectionPersistMeanMin`(85)
  且窗口满帧合法值（非法值/NaN 断窗，证据不足不伪造持续性，fail-visible）；
- 判定顺序 A-delta > A-persist > 原 B/C/D 分支——开启后变更面 = 纯增量（部分 B 升 A），
  原 A/B/C/D 输出与文案零漂移；结构性事实：persist 窗口含 [-2] 项 ⟹ persist 非 None 时
  delta 必非 None，首帧/单点/新股天然不触发；
- **默认 `crossSectionPersistFrames=0`（关闭）→ golden 不漂移**；文案"持续高位（近N帧均值 XX.X）"；
- 回归护栏：`tests/test_cross_section_persist_tier.py` 13 例（默认关闭锚点、A 触发、
  部分窗/均值不足/当前值回落/非法值断窗/单点不触发、delta 路径优先、live 去尾端到端
  默认 B vs 开启 A、technical/observation 两挂载一致）+ 既有 crossSection 19 例全绿；
  golden alignment + market_regime + engine 30 passed（默认关闭零漂移）。

### 18.3 实证方法（评估 harness `backend/analysis/ranktrend/research/cross_section_persist_research.py`）

- 数据：dragonboard_live/half_hour，决策窗 2026-04-15~07-31（655 帧，`assert_not_frozen`
  守卫）+ FINAL 08-01~08-14（100 帧，只读 report）；同 key 重复帧去重（保留后出现，
  与方案1 同帧跳过语义一致）；
- 档位输入序列：每股出现序列 attention percentile（与 `_build_code_attention_series`
  同构）；h1 收益与 tier_forward_returns 同口径（相邻帧 rank 字段 `_percentile` 差/100 +
  每 10 分位桶基线去趋势）；分桶 delta_A / persist_only_A（B 升 A 增量）/ high_B
  （留 B 且 pct≥85 对照）/ C / D；
- 假设（先列判定标准再跑数据）：H1 persist_only_A exDirAcc>0 且 >high_B；
  H2 persist_only_A ≥ delta_A−0.02（不稀释）；H3 persist_only_A n≥500；
- 变体：V0 主候选 (90,85,N=3) / V1 长窗 (90,85,N=5) / V2 宽松 (88,82,N=3) /
  V3 严格 (92,88,N=3)。

### 18.4 三窗结果（exDirAcc / exMeanRet / n）

| 变体 | persist_only_A 三窗 exDirAcc | high_B 三窗 exDirAcc | delta_A 三窗 exDirAcc | persist n 合计 |
|---|---|---|---|---|
| V0 (90,85,3) | +0.0091 / +0.0105 / +0.0092 | −0.0090 / −0.0142 / +0.0072 | +0.0998 / +0.1455 / +0.0151 | 11,555 |
| V1 (90,85,5) | +0.0140 / +0.0137 / +0.0059 | −0.0154 / −0.0188 / +0.0134 | 同上 | 11,018 |
| V2 (88,82,3) | +0.0058 / +0.0087 / +0.0128 | −0.0074 / −0.0225 / −0.0083 | 同上 | 13,707 |
| V3 (92,88,3) | +0.0084 / +0.0140 / +0.0109 | −0.0031 / −0.0113 / +0.0057 | 同上 | 9,361 |

FINAL（8 月，V0 只读 report）：persist_only_A +0.0093（n=2070）vs high_B +0.0158
（n=1006）——high_B 反超，同样不支持落地。

### 18.5 判定（数据驱动决策）

- **H1 成立（微弱但跨窗口稳健）**：persist_only_A 全部 12 个决策窗口点 exDirAcc 为正
  （+0.0058~+0.0140）且全部高于 high_B 对照——"持续高位"携带真实增量信息，不是噪声；
- **H2 证伪（全部变体一致）**：persist_only_A ≈ +0.01 vs delta_A ≈ +0.087，差距 ~0.077
  为量级差距；门槛收紧（V3）与窗口拉长（V1）均不改善——"上升确认"的信息量在热榜语境
  下结构性强于"持续高位"（上升驱动关注涌入 → 次日惯性；持续高位 → 关注饱和）；
- **H3 达标**：n ≈ 9,400~13,700，非样本不足问题；
- **决策：不落默认**（`crossSectionPersistFrames=0` 关闭观察，机制保留）。理由：
  ① 合并稀释——888 个 delta_A + ~11.5k persist 合并后 A 档 exAcc 被拉到 ~0.02，
  跌破 saExcessAccuracy≥0.05 硬约束线；② 投票语义——A=strong 正票，+0.01 的信息
  强度撑不起 strong 权重，该样本现为 B（weak 正票），升 A 无增量收益、有稀释成本；
  ③ FINAL 反向（high_B 反超）。
- **副证（方案1 修复有效性）**：重算序列（无复制尾）下 delta_A 样本充足
  （train 888 / val 606 / test 157 / FINAL 276）——A 档在修复后的生产链路真实可达，
  历史 snapshot_analysis A=0 纯属供给链 bug 而非因子无效。

### 18.6 遗留与复核触发

- 机制保留（参数化完整），若未来 synergy 投票引入"分强度正票"（如 B+/A− 中间档）
  或 A 档语义拆分（delta_A 与 persist_A 分开计票），可重新评估落地；
- D 档对称边界（pct<5 时 delta≤−5 不可达）未扩路径：D 为卖出/风险标记，miss 代价低
  （C 档兜底），且低分位已属均值回归目标变量性质（阶段 3 修复方向 3 口径），不扩；
- 验证：persist 13 例 + 既有 crossSection/delta_revival 19 例 + golden/regime/engine
  30 例全绿；全量 pytest 见阶段 18 提交说明。

## 阶段 19：验收口径双轨制修订与正向信号生产上线方案（2026-09-13，用户命题，方案未实施）

> 状态：**评估结论与上线方案设计，未实施**（默认值/golden 零变更）。用户命题：
> "0.05 硬约束线怎么定义的？它把有正向提升的因子参数都挡在 golden 外——单个信号
> 收益可能很少，多个信号组合产生的偏离会非常大。请重新梳理长测计划所有正向信号，
> 给出生产上线方案。"

### 19.1 0.05 验收线溯源：它是什么、怎么来的、管什么

**定义**（`tier_monotonicity.py MIN_SA_EXCESS_ACCURACY = 0.05`）：
S/A 档合并加权 **excessDirectionAccuracy ≥ 0.05** —— 档位方向精度减去样本所在分位桶
（每 10 分位）全样本基线方向精度，要求超额 ≥ 5 个百分点。即"该档位选出的股票下一帧
方向正确率，要比同分位桶里闭眼猜高 5pp"。它进 `passHardConstraint`，被 objective
`tier_risk_adjusted` 惩罚、evaluate_gate 采纳判定、长测四类判定引用。

**演变史**（两步走，非一次性拍脑袋）：

1. 回测方案 §5.2 原始硬约束（4 条）：S≥30 样本 + S>A>B>C 单调不反转 + D/E 显著低于 C +
   **S/A 绝对方向精度 ≥60%** + unknown<5%——注意原始口径是**绝对精度 60%**；
2. 阶段 3 修复（分位条件化）：实证发现绝对 60% 对追强档位**数学不可达**——排名收益强均值
   回归，高分位桶（90-99 分位）基线方向精度仅 0.33~0.36（"排名靠前的股下一帧继续升"
   的基线概率本身就低），绝对线永不可能满足 → 改为**相对超额 ≥0.05**（对照同分位桶基线，
   消除均值回归后档位自身的增量信息）。

**本质与适用边界**：0.05 是**单维档位语义验收线**——回答"这个档位的定义本身是否成立"
（A 档是否真的强于 B 档）。它**不是**"该因子/参数是否值得进生产"的验收线——后者是组合层
问题（见 19.3）。**项目实际存在两套验收口径并存但无明文边界**：唯一一次核心算法默认变更
（crossSection 第 5 维投票，2026-08-17 用户决策）落地依据是**组合 A/B 对比**
（all syn +10% / 8月 +237%），而非单维 0.05 线——crossSection B 档 exAcc 仅 +0.0153，
本身不过 0.05 线，但它作为投票维度的组合增量是真实的。大量参数候选则被 0.05 线
（或"样本外绝对 saEx≥0.05 且 passHard"的采纳门槛）挡住——口径混用是候选积压的机制性原因。

**0.05 线的第二个机制性缺陷（用户命题的准确化）**：阶段 7.4 已证明"样本外绝对验收不可达"
是**窗口性市场状态问题**（validation 段基线自身也 passHard=False、saEx −0.0112），阶段 14
进一步定位为 strong 状态塌陷 × 占比放大（决策窗 strong 桶 saEx 0.0224/A 档 exAcc 0.0001，
OOS-2 strong 占比 25.7% 拖累 ALL 至 0.0422）。用一条**非条件化绝对线**卡所有窗口，等于要求
候选在市场失效期也有效——超出任何信号的能力，正常候选因此被系统性拒绝。

### 19.2 长测计划全量正向信号盘点（阶段 4.1/7-18 全扫描，11 项）

**A 类｜组合层证据充分，被"绝对验收线"挡住（最接近上线）**：

| # | 候选 | 正向证据 | 挡住机制 | 文档 |
|---|---|---|---|---|
| 1 | **`fund10+over2`**（volumePriceAbnormalFundRatio 20→10 + OverVolumeRatio 2.5→2.0） | 决策窗 syn saEx +24.1%（0.0651→0.0808，passHard 保持）；half_hour validation 转正 +0.0165；8 月干净窗 **+438%**（0.0069→0.0371） | 0.0371<0.05 绝对线；8 月仅 110 帧单窗 | §9.2-9.5 |
| 2 | **`jump25+fresh06`**（jumpDeltaPct 严格化 + tierResonanceJumpFreshnessMin 0.5→0.6） | 8 月干净窗 **+283%**（0.0264）；单旋钮全窗 saEx +5.8%；样本外（混合窗）相对基线改善 45%~79% 无反转 | 同上（绝对线不可达系窗口性问题，基线同败） | §7.2-7.4、§9.5 |
| 3 | **`synergyEntryTierMin="a"`**（交易层 S/A 入场门，非算法参数） | 交易层粗搜最大区分因子：winRate 0.4286→0.5441（+11.5pp）、totalReturn −0.1296→**+0.006 转正**、回撤 −0.162→−0.096 减半 | trade_config 默认仍 "none"，未走生产落地评审 | 阶段 4.1 |
| 4 | **`momentumPeriods=[2,3,5,8,13]`**（趋势快周期） | 单参数 syn saEx +3.4%、组合 mom_fast+cross01 score +3.0%；8 月窗 +26% | 8 月证据微弱（+26%），"趋势候选证据不足" | §8.2-8.3、§9.5 |

**B 类｜单维证据中等、组合层增量未测（用户命题的直接对象）**：

| # | 候选 | 正向证据 | 挡住机制 |
|---|---|---|---|
| 5 | **crossSectionPersistFrames（方案2 持续高位 A 档）** | 单维 exDirAcc 12 决策窗口点全正（+0.006~+0.014）且全部 >high_B 对照 | 仅测了单维档位区分度即否决（H2 vs delta_A 量级差）；**开启 persist 投票后 synergy 组合边际变化从未测过**——"多维组合偏离"正是未做的实验 |
| 6 | **MA10×MA20 金叉事件独立信息** | 事件级证实：与 MACD 金叉重叠仅 3-4%（独立事件源）、质量 2/3 窗优于 MACD 金叉（0.0899 vs 0.0834；+0.041 vs −0.072） | 决策级边际 ±0.01 量级 2正1负；trend_buy 接线位零增量（65% 事件帧已被既有 OR 链覆盖）；ma_join 共存"缺复核暂不采纳"——**事件级用法（加分项非权重）未评估** |
| 7 | **buyScoreThreshold=0.18** | 两窗同向（决策窗 +0.0076 / OOS-1 +0.0037 saEx） | OOS-2 反向（−0.0029），"缺复核"，随 9 月复扫 |

**C 类｜regime 条件化依赖（全局验收线不适配的分状态信号）**：

| # | 发现 | 证据 | 状态 |
|---|---|---|---|
| 8 | **weak 桶追强区分度** | weak 是唯一 validation 段 saEx≥0.05 的 regime（0.1146，跨三段 0.0712/0.0735/0.1146 方向稳定）；strong 反而失效（OOS-2 −0.0202） | S 档样本结构性稀缺（12~21 个）无统计置信；"weak 过滤+更长窗口"不足以采纳（§7.6） |
| 9 | **strong 状态双峰**（塌陷/强劲并存） | OOS-1 strong 全窗最强（0.1139）vs 决策窗塌陷（0.0224）；塌陷与 strong 期结构相关 | 区分"塌陷/强劲 strong"的可观测变量未找到——阶段 14.4 后续课题 |
| 10 | **双强共振 rt=A×cs=A 无过热证据** | §11.4f 疑似过热（−0.0469）被阶段 15 三窗复核翻案（meanRet csA≥csC 全窗一致） | "缺复核"维持观察（n=283<500），**降级命题方向证据相反** |

**D 类｜已落地先例（口径参照）**：

| # | 已落地 | 依据口径 |
|---|---|---|
| 11 | crossSection 第 5 维投票（tierSynergyCrossSectionVote=1.0，2026-08-17 用户决策） | **组合 A/B 对比**：all syn +10%、8 月 +237%——非单维 0.05 线（crossSection B 档 exAcc 仅 +0.0153 不过线） |

负贡献对照（保持关闭，不在上线清单）：priceMomentum 投票（−32%）、divergence 投票（−25%）、
WP2 K=2/3（saEx 单调恶化）、MACD 参数面/zeroCross（冗余）、accel_0.26（−26%）。

### 19.3 双轨验收制设计（修订 §5.2 口径的适用边界，代码 0.05 常量保留）

**轨道 1｜档位语义验收（现行，保留）**：`MIN_SA_EXCESS_ACCURACY=0.05` + S 样本 + 单调 +
unknown 率。只回答"档位定义本身是否成立"。适用：新增观察维、档位阈值结构改动、
档位合并/拆分。**不再**作为参数/因子上生产的否决线。

**轨道 2｜生产上线验收（新增，组合层）**：回答"开/关该候选，生产组合指标是否改善"。
验收指标（全部相对基线、非绝对线）：

1. **组合区分度**：决策窗（04-15~07-31）synergy h1 saEx 相对基线 ≥ +3%（历史可见改善下限，
   fund10+over2 +24.1% / jump25+fresh06 +5.8% / 快周期 +3.4% 均在此线之上）且 passHard 不掉档；
2. **干净样本外方向一致**：≥1 个非股灾样本外窗（8 月段 / 9 月起累积窗）相对基线改善
   （相对改善 ≥10% 或绝对转正），不要求 ≥0.05 绝对线；跨 2 个干净窗一致性更佳；
3. **分状态不恶化**：regime 分桶（strong/normal/weak，阶段 14 口径）各桶 saEx 变化
   ≥ −0.01（容差）——防"整体改善由单一状态贡献、其它状态恶化被平均掩盖"
   （阶段 14 已证明 ALL 口径会掩盖 strong 塌陷）；
4. **翻转率不恶化**：WP3.2 三类翻转率（veto/bd/regime_state）容差内；
5. **交易层复核**：evaluate 交易粗搜（win_rate_pf）确认候选叠加 synergyEntryTierMin 后
   winRate/回撤不劣于基线组合。

**为什么这样设计**：轨道 2 直接度量用户命题的"多信号组合偏离"——单维微弱信号在投票
加总里的真实作用（压秤跨门槛/稀释/重复计票）只能靠组合 A/B 实验回答，任何单维线都
推定不了。同时保留 4 条相对性约束防组合噪声：同源信号叠加会被"分状态不恶化 +
方向一致"拦住（重复计票通常在特定 regime 集中恶化）。

### 19.4 分级上线路径（一次一候选，不打包）

| 优先级 | 候选 | 路径 |
|---|---|---|
| **P1 直接推进** | fund10+over2 | 9 月数据复验（第 2 个干净样本外窗）→ 方向保持 → 走 golden 变更流程落默认（config 默认值 20→10 / 2.5→2.0 + golden 回归 + L1 档案更新） |
| **P1 同批复验** | jump25+fresh06 | 与 fund10+over2 同批跑 9 月复验；两候选叠加交互检查（fund10+over2+jump25+fresh06 四参组合 trial）→ 择优或分批落 |
| **P1 交易层** | synergyEntryTierMin="a"（+maxPositions=3/stopLoss/takeProfit 组合） | 不进 golden（算法合同不动）——走 trade_config 生产默认评审：长测框架 trade_journal 实盘对齐（Layer 3）后落交易默认 |
| **P2 组合实验轨** | crossSectionPersistFrames（方案2）| **补做组合 A/B**：persist 开/关的 evaluate_gate trial（决策窗 + 两 OOS 窗 + regime 分桶 + 翻转率）——用轨道 2 证据重判（单维 H2 证伪不再是否决理由） |
| **P2 组合实验轨** | momentumPeriods 快周期 | 与 P1 候选叠加 trial（mom_fast + fund10+over2 ± jump），观察交互后决定 |
| **P3 事件级评估** | MA 金叉事件 | 按 §17.7 遗留：评估"金叉事件作为独立加分项"（非决策权重、非 trend_buy 接线位）的组合贡献 |
| **P4 条件化课题** | weak 桶追强 / strong 双峰 | 分状态门控设计（另行设计评审，阶段 14.4 方向）：找区分塌陷/强劲 strong 的可观测变量；weak 状态作为观察信号可信度标注先行（展示层） |
| **维持现状** | buyThr=0.18 / 双强共振 | 9 月复扫 / 滚动累积（触发条件不变） |
| **保持关闭** | 负贡献/冗余清单 | priceMomentum、divergence、WP2 K、MACD 参数面——机制保留 vote=0/默认关 |

**实施纪律**：① 一次只落一个候选（P1 两个候选也分两个 commit，避免交互污染归因）；
② 每次落默认走完整 golden 变更流程（全回归 + 显式断言 + L1 档案 + 本计划同步）；
③ 上线后 9 月滚动复验（阶段 12 触发条件沿用），负贡献即回退（默认值回滚 + 档案记录）；
④ 组合实验全部用 evaluate_gate harness（决策窗 + OOS-1 + OOS-2 + FINAL 只读），
8 月冻结纪律不变——**本方案不引用 8 月数据作新参数决策，仅复核既有 8 月证据**。

### 19.5 风险与边界（诚实声明）

1. **放宽≠取消**：轨道 2 仍要求相对改善 + 方向一致 + 分桶不恶化——fund10+over2 若 9 月
   复验反向，照样不落；本方案放行的是"证据格式正确的候选"，不是"所有正向候选"；
2. **P2 组合实验可能证伪用户假设**：persist 单维 +0.01 在投票加总里可能确实起不了压秤
   作用（crossSection 投票落地时单维 A 档是 +0.0996 量级）——但这正是必须做实验的原因，
   单维线推定不了组合效应，两个方向都可能；
3. **绝对线的历史价值**：0.05 线在轨道 1（档位语义）仍然正确——crossSection A 档
   +0.0996 的强区分度正是靠它筛出来的；被它挡住的应是"档位语义不成立"的候选，
   而非"组合有增量"的候选——本次修订就是把两类决策分开；
4. **样本外窗口仍薄**：8 月 110 帧、9 月仅数日——P1 落地前 9 月复验窗口可能仍不足
   （fund10+over2 的 8 月证据单窗 +438% 极强但仍单窗），若 9 月数据累积不足，
   接受"延迟落地"而非降低证据标准。

### 19.6 用户决策与流程简化（2026-09-13，方案获批）

用户对 §19.3/§19.4 三项决策：

1. **双轨验收制通过，但简化流程 + 增加多信号组合验证**；
2. **P1 即刻启动**——9 月已有 10 个交易日数据，满足复验要求（不等待继续累积）；
3. **P2 安排 A/B 实验**（persist 开/关组合面复验）。

**简化后的轨道 2 流程 = 一张判定卡**（替代"逐条人工汇总多份报告"）：

统一 harness `backend/operations/evaluate_track2_candidates.py`（evaluate_gate 口径，
一次 trial 自动产出全部验收数据），判定卡五条全自动判定：

| 判据 | 标准 | 数据来源（evaluate_gate 内建） |
|---|---|---|
| C1 决策窗改善 | synergy saEx 相对 baseline ≥ +3% | synergy.saEx |
| C2 样本外方向 | OOS-1/OOS-2 ≥1 窗同向为正 | 同上（分窗） |
| C3 硬约束不破 | passHard 不降（True→False 一票否决） | synergy.passHard |
| C4 分桶不恶化 | regime 四桶 saEx 降幅 ≤ 0.01（绝对差） | regimeView（strong/normal/weak/retreat） |
| C5 翻转不恶化 | veto/bd_downgrade 升幅 ≤ +0.01（绝对差） | flipRates（WP3.2） |

结论：C1∧C2∧C3 = **PASS_CANDIDATE**（进入交易层复核 + golden 变更流程）；
C3 False = REJECT；其余 = OBSERVE。交易层复核（§19.4 ⑤）只在落默认前最后一步执行。

**多信号组合验证为必选项**：单因子 trial（fund10_over2 / jump25_fresh06 / persist_on）
与组合 trial（combo_p1 四参叠加 / combo_all 加 persist）同批跑；判定卡输出
combo vs 最优单因子交互行（combo ≥ best = 叠加有效；< best = 相互抵消，观察）。
落默认仍一次一候选（§19.4 纪律不变），组合验证只用于归因与交互检测。

**P1 复验窗口**：OOS-2 扩为 2026-09-01~09-12（9 月 10 个交易日，用户批准）；
FINAL（8/1-8/14）冻结纪律不变，不进判定。 Trial 表与判定结果见阶段 20。

## 阶段 20：Track 2 统一判定 harness + P1 复验/P2 A/B 判定结果（2026-09-13）

> 状态：harness 落地（`backend/operations/evaluate_track2_candidates.py`，§19.6 判定卡
> 自动产出）；6 trial × 3 窗（decision 655 帧 / oos1 110 帧 / oos2 86 帧，9 月 9 个
> 交易日入库：9/1-9/11，9/10 已补录 10 帧、9/11 收 6 帧）全部完成；
> **判定结论：全部 OBSERVE，无一 PASS_CANDIDATE，无一进 golden 变更流程**；
> 报告：`data/reports/track2-candidates.json`（含 verdict 卡）
> 8 月冻结纪律：FINAL(8/1-8/14) 未参与判定。

### 20.1 绝对量级表（synergy saEx / passHard / 样本）

| trial | decision | oos1 08-15~31 | oos2 09-01~12 |
|---|---|---|---|
| baseline | 0.0821 (T) | 0.0654 | 0.0571 |
| **fund10_over2** | **0.0947 (T)** | **0.0462（−0.019）** | **0.0302（−0.027）** |
| jump25_fresh06 | 0.0812 (T) | 0.0640 | 0.0554 |
| combo_p1 | 0.0941 (T) | 0.0462 | 0.0369 |
| persist_on | 0.0752 (T) | 0.0627 | 0.0627 |
| combo_all | 0.0861 (T) | 0.0453 | 0.0376 |

决策窗样本 n=115724；oos2 n=11196（量级充足）。

### 20.2 判定卡结论（C1-C5 全自动）

1. **fund10_over2（P1）**：决策窗 +15.4%（C1✓）但 **OOS 双窗反向**（−29.4%/−47.1%，
   绝对 −0.019/−0.027）→ C2✗ OBSERVE。**9 月复验负验成立**：阶段 9.5 的 8 月上旬
   证据（+438%）确认无法跨窗复现，8/03-14 为窗口特异；维持不落默认，回观察池；
   C3/C4/C5 全过（passHard 保持、regime 桶改善、翻转率下降）——问题不在风控面，
   在方向不稳；
2. **jump25_fresh06（P1）**：三窗全负（−1.1%/−2.1%/−3.0%，绝对 −0.001~−0.002 轻微
   但方向一致）→ 观察池；strong 桶 +24.2% 但 normal/retreat 微负，无落默认理由；
3. **combo_p1（多信号组合验证）**：决策窗 +14.6% 但 OOS 双反 + retreat 桶 −6.1%
   （C4✗）；**组合交互：combo 0.0941 < 最优单因子 0.0947**——jump25 在决策窗为负
   贡献，叠加轻微抵消，"多信号叠加增益"假设在本样本上不成立；
4. **persist_on（P2 A/B）**：决策窗 −8.4%、strong 桶 −29.2%（C4✗）但 oos2 +9.8%
   （C2✓）——方向分裂；与阶段 18 结论一致（单维 H1 成立、组合面贡献不稳），
   **维持默认关闭**（crossSectionPersistFrames=0），机制保留；
5. **combo_all**：全组合 0.0861 < 最优单因子 0.0947，OOS 双反——persist 进组合后
   决策窗增益被稀释（+4.9% vs fund10_over2 单独 +15.4%）。

### 20.3 背景事实与后续

- **strong 桶塌陷延续**：oos2 baseline strong 桶 saEx = −0.0192（decision 窗 +0.024）——
  阶段 14 发现的强态区分度塌陷在 9 月仍在持续，是全局背景而非候选特异；P4 条件化
  课题（§19.4）优先级因此上升；
- **判定卡流程验证**：18 trial 一次跑完（含断点续跑），判定卡自动产出——§19.6 简化
  流程成立，后续候选复验沿用本 harness（加 trial 行即可）；
- **P1 后续**：fund10_over2 维持"观察池最高优先"标注（决策窗 +15.4% 是全部候选中
  最强正信号），但落默认需要 OOS 方向恢复——触发条件：新月度窗口复验 C2 通过；
- **P2 后续**：persist 维持关闭；momentumPeriods 快周期堆叠 trial 未跑（P1 组合已
  证伪叠加增益假设，快周期堆叠预期收益低，暂缓）；
- **无 golden 变更**：本阶段零代码默认值改动；L1 档案无新落默认项。
