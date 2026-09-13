# RankTrend L1 自由参数定值档案

> 2026-08-19 建（防过拟合 E 项）；口径：L1 = 被数据调过的参数（≈50）。
> 字段：当前值 / 定值 commit / 定值数据窗口 / 样本外状态 / 备注。
> 纪律：8 月（FINAL）自 2026-08-19 起冻结，任何参数不得以 8 月为调参依据（见 overfitting-audit.md §6-A）。

## 1. 共振参数（阶段 7，12 个）

| 参数 | 当前值 | 定值 commit | 窗口 | 样本外 |
|---|---|---|---|---|
| resonanceShortWindowBars | 3 | 阶段 7（2026-08-17） | 769 帧 | walk-forward 复核 |
| resonanceMidWindowBars | 8 | 同上 | 769 帧 | walk-forward |
| resonancePathWindowBars | 8 | 同上 | 769 帧 | walk-forward |
| resonanceMomentumScale | 15.0 | 同上 | — | 结构缩放 |
| resonanceAccelerationScale | 15.0 | 同上 | — | 结构缩放 |
| resonancePathDirectionWeight | 0.2 | 同上 | 769 帧 | walk-forward |
| resonanceDirectionThreshold | 0.1 | 同上 | 769 帧 | walk-forward |
| resonanceWeights | [0.35,0.25,0.2,0.2,0.2] | 同上 | 769 帧 | walk-forward |
| resonanceReversalSwitchWeight | 0.6 | 同上 | — | 结构权重 |
| resonanceReversalDrawdownWeight | 0.4 | 同上 | — | 结构权重 |
| resonanceJumpFreshnessDecay | 3.0 | 同上 | 769 帧 | 5 档扫描+样本外 |
| resonanceEntryStrengthScale | 25.0 | 同上 | — | 结构缩放 |

## 2. 核心信号参数（阶段 8，~10 个）

| 参数 | 当前值 | 定值 commit | 窗口 | 样本外 |
|---|---|---|---|---|
| momentumAccelThreshold | 0.18 | 阶段 8（2026-08-17） | 769 帧 | 8.5 样本外复核（0.26 未采纳） |
| momentumPeriods | [3,5,8,13,21] | 阶段 8 | 769 帧 | 8.6 快周期复核 |
| tierAMainMidMomentumMin | 4.0 | 阶段 3/8 | 历史 | 语义校准（40ddc7f） |
| tierBIgnitionShortMomentumMin | 3.0 | 阶段 3/8 | 历史 | 语义校准 |
| tierBIgnitionAccelMin | 0.5 | 阶段 3/8 | 历史 | 语义校准 |
| tierCrowdedLongMomentumMin | 4.0 | 阶段 3/8 | 历史 | 语义校准 |
| tierExitRisk* | 3 个 | 阶段 3 | 历史 | 语义校准 |
| jumpDeltaPct | 15.0 | 阶段 7/8 | 769 帧 | 8.8 5 档扫描+组合复核 |
| jumpResetLookback | 3 | 阶段 7/8 | 769 帧 | 8.8 |
| jumpSustainCount | 2 | 阶段 7/8 | 769 帧 | 8.8 |

### 2b. 趋势因子参数补录（8.4 扫描 2026-08-17，2026-09-09 补录入账）

| 参数 | 当前值 | 定值来源 | 窗口 | 样本外 |
|---|---|---|---|---|
| momentumDirectionThreshold | 0.2 | 8.4 五档扫描 | 769 帧 | 默认最优（各档持平）；窗口含 8 月，按现纪律待复核 |
| momentumSignalShareMin | 0.6 | 8.4 | 769 帧 | 0.8 微升未采纳；同上待复核 |
| momentumLongOpposeThreshold | 0.25 | 8.4 | 769 帧 | 默认最优 |
| momentumZeroConfirmThreshold | 0.15 | 8.4 | 769 帧 | 0.25 微升未采纳 |
| momentumZeroStrongConfirmThreshold | 0.15 | 8.4 | 769 帧 | **零效应**（只影响 confidence 不影响档位） |
| macdGoldenStrongGapMin | 0.2 | 8.4 | 769 帧 | 0.3 微升未采纳 |
| macdGoldenGapScaleRatio | 0.18 | 8.4 | 769 帧 | 0.26 微升未采纳 |

- **趋势因子未扫参数（2026-09-09 阶段 13 补扫完成，20 档 × 三窗口）**：

| 参数 | 当前值 | 来源 | 结果 |
|---|---|---|---|
| macdFast / macdSlow / macdSignal | 13 / 21 / 8 | 阶段 13 补扫 | **冗余**（各档 score 波动 <±0.25%；macdSlow=26 决策窗最差、OOS 两窗反而最好——跨窗方向矛盾不采纳） |
| macdDeathGapScaleRatio / macdDeathStrongGapMin | 0.12 / 0.18 | 阶段 13 补扫 | **冗余**（deathStrong 两档三窗逐位一致=零效应；deathScale 微弱） |
| macdRawScoreWeights | [0.7,0.3] | 阶段 13 补扫 | **冗余** |
| momentumZeroWeights | [0.7,0.3] | 阶段 13 补扫 | **冗余**（微弱 ±0.0005） |
| momentumZeroStrongConfirmBonus | 5.0 | 阶段 13 补扫 | **零效应**（三窗逐位一致，复现 8.4 confidence-only 结论） |
| buyScoreThreshold | 0.12 | 阶段 13 补扫 | **缺复核**：0.18 决策窗 score +0.0076 / saEx 0.0811→0.0849、OOS-1 同向（0.0713→0.0732），但 OOS-2 反向（→0.0407）；幅度 <0.5% saEx，不满足采纳门槛；9 月样本扩展后复扫 |
| sellScoreThreshold | −0.12 | 阶段 13 补扫 | **冗余** |

- **平坦机制**：MACD 仅以二值金叉参与 trend_buy（三选一 OR 条件之一），gap 阈值/权重
  只动 rawScore/confidence 展示层；buyScoreThreshold 只在决策合成边缘生效。趋势维的
  决策主承载是 momentumPeriods（8.6 已扫）与 direction 阈值（8.4 已扫）。
- **MA5/MA10 不参数化不扫描**：technical.py `movingAverage` 为显示字段，全后端无决策
  消费方（不进 direction/acceleration/zeroCross/macd 信号与档位判定）；趋势维决策入口
  是 momentumPeriods（8.6 已扫）与 direction 阈值（8.4 已扫）。
- 其余动量侧未扫：momentumScoreThreshold(35)/momentumConfidenceSlope(0.45)/
  momentumLongAgreeThreshold(0.15)/momentumDirectionShareBoost/momentumAccelShareBoost。

### 2c. MA 交叉因子（阶段 17，2026-09-12：新增观察因子，默认全关）

排名百分位序列上的 MA10×MA20 金叉/死叉（`technical.py::calculate_ma_cross`，与 MACD
同输入同二值交叉参与语义）；与上面"MA5/MA10 显示字段不扫描"裁定不冲突——本次因子
有决策消费方（compose_decision 第 5 分量 + trend_buy OR 链两个接线位）。

| 参数 | 当前值 | 来源 | 阶段 17 评估结论 |
|---|---|---|---|
| maFastPeriod | 10 | 用户指定（10/20） | 未扫（单点评估，参数面未开） |
| maSlowPeriod | 20 | 用户指定（10/20） | 未扫（同上；slow≤fast 自动修正） |
| maWeight | 0.0（关） | 阶段 17 三窗 7 trial | **缺复核暂不采纳**：共存第 5 分量连续效应量 trend saEx Δ +0.0046/+0.0172/−0.0104（2 正 1 负），score 摆动主体是 trend pass 0.05 线二值放大 |
| maCrossTrendBuy | False（关） | 阶段 17 4 组对照 | **冗余**：三窗逐位一致；MA 金叉帧 65-68% 已被既有 trend_buy OR 链覆盖，余量未传导 |

- 事件级证据（支持保留观察）：MA 金叉事件三窗 saEx 0.0899(T)/0.0141/0.0411，2/3 窗优于
  MACD 金叉事件（0.0834 未过硬门 / 0.0240 / **−0.0716**），事件重叠仅 3-4%（独立信息源）。
- 替代路线证伪：ma_replace 一致优于 macd_off 但 OOS-2 vs baseline −0.20，替代不划算。
- 复核触发见长测计划 §17.7（MACD 金叉 OOS-2 负超额复现 → 重估 ma_replace；9 月样本
  扩展 → 重跑 ma_join）。报告 `data/reports/ma-factor-contribution.json`。

## 3. 量价参数（阶段 9，7 个，commit 2f8e1a1）

| 参数 | 当前值 | 窗口 | 样本外 |
|---|---|---|---|
| volumePriceBase | 50.0 | 537 train | 9.3 validation + 9.5 8 月独立复核 |
| volumePriceOverVolumeRatio | 2.5 | 5 档扫描 | 同上 |
| volumePriceAbnormalFundRatio | 20.0 | 5 档扫描 | 同上 |
| volumePriceShrinkRatio | 0.95 | 5 档扫描 | 同上 |
| volumePriceMildRatio | 1.05 | 5 档扫描 | 同上 |
| volumePriceDirectionBuckets | [15..1.0] | 5 档扫描 | 同上 |
| volumePriceNormalRatio | 2.0 | 5 档扫描 | 同上 |

## 4. 横截面参数（阶段 10，8 个）

| 参数 | 当前值 | 定值方式 | 样本外 |
|---|---|---|---|
| crossSectionStrongMin | 85.0 | 因子设计（percentile 语义） | 10.3 区分度 + 方向 A 验证 |
| crossSectionStrongDeltaUp | 5.0 | 设计 | 同上 |
| crossSectionMidMin | 50.0 | 设计 | 同上 |
| crossSectionMidDeltaUp | 15.0 | 设计 | 同上 |
| crossSectionWeakMax | 15.0 | 设计 | 同上 |
| crossSectionWeakDeltaDown | -5.0 | 设计 | 同上 |
| crossSectionMidMax | 50.0 | 设计 | 同上 |
| crossSectionMidDeltaDown | -15.0 | 设计 | 同上 |

## 5. 本轮研究参数（G1-G7/方向 A-C，~15 个，commit f55be15/697546e）

| 参数 | 当前值 | 定值依据 | 样本外/备注 |
|---|---|---|---|
| tierSynergyCrossSectionVote | 1.0 | G2 实证（all +10%/8 月 +237%） | 8 月已冻结（不再作调参依据） |
| tierSynergyDivergenceVote | 0.0 | dv 投票实证负（−25%） | 关闭观察 |
| tierSynergyPriceMomentumVote | 0.0 | G1 实证负（−32%） | 关闭观察 |
| regimeGateStrongBan | True | 数据修正（strong 负贡献） | 方向 C 验证现状最优 |
| banStrongA / banStrongB | True / True | 方向 C 三模式验证（M2 最优） | 分层可调 |
| jumpConfirmChangeMin | 3.0 | G4（half_hour Jump 事件 0） | 未实触 |
| jumpConfirmVolumeRatioMin | 1.0 | G4 | 未实触 |
| amountRatioPeriod | 5 | G3 方案 C 设计 | **未扫描**（C 项：冻结前窗口零差异） |
| amountRatioHigh | 1.5 | G3 设计 | 未扫描（同上） |
| amountRatioLow | 0.5 | G3 设计 | 未扫描（同上） |
| priceRankChangeMin | 0.0 | G1 背离方案 | 观察（vote=0） |
| priceRankDeltaMin | 0.0 | G1 背离方案 | 观察（vote=0） |

## 6. 风险与复核触发

- **8 月污染历史**：1-4 组参数定值时 8 月尚为"独立复核窗口"，本轮（组 5）部分参数
  （crossSection 投票/regime）定值直接引用了 8 月数据——自 2026-08-19 起冻结，后续
  新参数不得再引用；
- **复核触发**：9 月数据累积后（train 窗口自然扩展），对组 5 参数重新走 rolling
  walk-forward（A/B 纪律）；A 档样本 >500 后复核双强观察项；
- **2026-09-06 WP1c 修复 regime 情绪注入 lookahead；组 5 参数结论待 9 月数据积累后按 §6 重验**；

- **golden 约束**：任何参数改动不得破坏 golden（test_ranktrend_golden_alignment 全绿）。

## 7. 环境门去噪参数（WP2，2026-09-06）

| 参数 | 默认值 | 语义 | 状态 |
|---|---|---|---|
| lifecycleConfirmFrames | 1 | veto/B-D 降档连续确认帧数（1=单帧即触发，现行为） | **证伪**（2026-09-09 2c 三窗扫描）：veto 去噪真实（0.127→0.023/0.010）但 synergy saEx 三窗一致恶化，OOS 全部 <0.05，K=3 决策窗掉 passHard |
| regimeScoreEmaAlpha | 1.0 | regime score EMA 系数（1=直通） | **冗余**（采纳口径，2026-09-09 2c）：交易指标三窗 4 位小数下与默认一致；仅展示层 state 去噪（market 翻转 183→49 次@α=0.25）+ 0.87% 边缘档位赋值变化、无收益 |
| regimeStateHysteresis | false | strong 边界迟滞开关 | **冗余**（2026-09-09 2c）：OOS 两窗逐位一致，决策窗仅 market 翻转微降（183→178）；strong 保持效应存在（信号 19333→21407）但不产生采纳收益 |
| regimeStrongHysteresisBand | 5.0 | strong 退出阈值 = 进入阈值(70.0) − band | 跟随 regimeStateHysteresis（冗余） |

- 扫描前置条件：WP1c lookahead 修复 + WP3.2 翻转率基线；K∈{1,2,3}、α 档位单变量。
- 默认零漂移验证（2026-09-06 WP2 Task 6）：K=1/α=1.0/迟滞关下 8 月冻结段端到端重跑
  `diagnose_gate_flip_rate`，翻转率与 WP3.2 基线逐位一致（veto=0.13760 / bd=0.08345 /
  regime_state=0.00103，202 帧 / 45686 信号 / 1813 code）→ 接线本身零行为变化。
- **扫描执行**（2026-09-09 WP2 2c，longterm-test 8 步）：harness
  `backend/operations/optimize_gate_denoise_parameters.py`（可 resume）；决策窗
  2026-04-15~07-31（659 帧）+ 准样本外 08-15~08-31 + 未见窗 09-01~09-09；报告
  `data/reports/gate-denoise-scan_*.json`（本地运行产物，不入库）。扫描表与判定详见
  `ranktrend-longterm-backtest-plan.md` 阶段 12。
- **扫描暴露实现缺陷（已修复，commit d34f71bb）**：RegimeSmoother 首版 state=raw_state
  原样透传，α<1 时 state 不随平滑分数变化（违反 spec §2b），α 轴首扫全档与 baseline
  逐位一致才暴露；修复后 state 由 EMA 分数按 market_regime 同源阈值（70/50/30）整体重判，
  直通路径（α≥1 且迟滞关）保持同一引用，golden 无漂移。
- **机制注记**：veto/bd 翻转源自 lifecycle 门控，与 regime state 无关——三参数中只有 K
  能动它；regime strong 禁入 A/B 仅边缘生效（α 改变 1150/132078=0.87% 档位赋值），
  h1 聚合统计 4 位小数下不可分辨。
- **复核触发**：regime 门禁若扩展消费非 strong 状态（normal/weak/retreat），α/迟滞轴
  需重扫；K 结论待 9 月数据积累后按 §6 滚动重验。
- 冻结纪律：未经 longterm-test 流程"证实"，默认值不得变更。

## 8. crossSection 持续高位 A 档替代路径（2026-09-13 方案2）

| 参数 | 默认值 | 语义 | 状态 |
|---|---|---|---|
| crossSectionPersistFrames | 0 | 持续高位窗口 N（近 N 帧 attention percentile 均值）；0=关闭 | **不落默认/关闭观察**（2026-09-13 阶段 18 实证：H1 成立（exDirAcc +0.006~+0.014 跨 12 窗口点全正且 >high_B）但 H2 证伪（vs delta_A 0.087 量级差距，门槛收紧不改善），合并稀释 A 档跌破 0.05 线，FINAL high_B 反超；机制保留待投票语义拆分后重评） |
| crossSectionPersistMin | 90.0 | 当前 pct 门槛（路径开启时生效） | 跟随 Frames（关闭） |
| crossSectionPersistMeanMin | 85.0 | 近 N 帧均值门槛（窗口满帧合法值才触发） | 跟随 Frames（关闭） |

- 默认 Frames=0 = golden 不漂移（`test_cross_section_persist_tier.py` 13 例锚点）；
- 实证 harness：`backend/analysis/ranktrend/research/cross_section_persist_research.py`
  （4 变体 × train/val/test + FINAL 只读；8 月冻结纪律全程遵守，决策仅引用 4-15~07-31）。
