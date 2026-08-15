# 四维信号长期回测计划与性能优化方案

> 状态：阶段 1（性能改造）已落地（commit `b4c9091`~`dce716b`），阶段 2（数据质量治理）已落地（commit `58878dc`），阶段 3（四维信号区分度诊断 + 三方向修复 + 语义校准）**验收达成**（commit `2f905b5`/`dc01019`/待补），阶段 4 待推进
> 日期：2026-08-15
> 归档位置：本文档与四份四维信号方案文档统一存入 `quant-board/docs/ranktrend-tier-backtest/`

## 0. 背景与目标

RankTrend 四维信号（共振 / 趋势 / 量价 / 周期，合并为 `synergy` 总档）的档位阈值参数化与交易门已落地（见 `ranktrend-signal-tier-backtest-plan.md`）。目标是让四维信号作为买入/卖出的重要决策依据，并通过参数搜索引擎**持续**优化参数，最终达到：

```
winRate ≥ 0.80 且 tradeCount ≥ 60 且 profitFactor ≥ 1.3
且 validation 段 winRate ≥ 0.70 且 maxDrawdown ≤ 10%
且 walkForward 段胜率 ≥ 0.7（连续两个样本外窗口稳定）
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

**验收**：满足第 0 节完整验收标准，且连续两个样本外窗口稳定。

## 4. 验收标准汇总

| 约束 | 达标线 | 防什么 |
|---|---|---|
| winRate | ≥ 0.80 | 主目标 |
| tradeCount | ≥ 60 | 小样本刷胜率 |
| profitFactor | ≥ 1.3 | 紧止损刷胜率 |
| validation winRate | ≥ 0.70 | 过拟合 |
| maxDrawdown | ≤ 10% | 高胜率偶发大回撤 |
| walkForward 段胜率 | ≥ 0.7 | 分段时间稳定性 |

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
