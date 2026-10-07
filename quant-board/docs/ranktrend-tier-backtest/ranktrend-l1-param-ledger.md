# RankTrend L1 自由参数定值档案

> **【已封存 2026-09-30】**复核登记职能随旧月度批次体系封存——本文转为**默认值变更史**（§1-§17 即完整历史，不再新增复核章节）。新体系：`ranktrend-phase-acceptance-design.md`。

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
| maWeight | 0.0（关）→ **0.2（2026-09-13 落默认，见 §9）** | 阶段 17 三窗 7 trial | **缺复核暂不采纳（已失效，被 §9 落默认取代）**：共存第 5 分量连续效应量 trend saEx Δ +0.0046/+0.0172/−0.0104（2 正 1 负），score 摆动主体是 trend pass 0.05 线二值放大 |
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
| jumpConfirmChangeMin | 3.0 | G4（half_hour Jump 事件 0） | **2026-09-15 断线修复后真实生效**（§15.6）；此前未实触（门断线） |
| jumpConfirmVolumeRatioMin | 1.0 | G4 | 同上（断线修复后真实生效） |
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

## 9. MA 交叉因子落默认——五因子化（2026-09-13 阶段 21.8，取代 §2c maWeight 暂不采纳裁定；五权重数值已被 §10 取代）

| 参数 | 旧默认 | 新默认 | 来源 | 状态 |
|---|---|---|---|---|
| maWeight | 0.0（关） | **0.2** | 阶段 20.4/20.5 ma_join 实证口径（设计值 0.25 五权重归一化） | **落默认**（2026-09-13 用户决策：架构对称 + MA 金叉三窗方向一致性优先，接受 OBSERVE 增益幅度） |
| directionWeight | 0.30 | 0.24 | 归一化精确值 | 联动（相对比例不变） |
| accelerationWeight | 0.25 | 0.20 | 归一化精确值 | 联动 |
| crossWeight | 0.20 | 0.16 | 归一化精确值 | 联动 |
| macdWeight | 0.25 | 0.20 | 归一化精确值 | 联动（MACD 分量/票位/链路全保留） |
| maFastPeriod / maSlowPeriod | 10 / 20 | 不变 | 用户指定 | 不变 |
| maCrossTrendBuy | False | False | 阶段 17 零增量已证 | 不变（保持关闭） |

- **落默认口径锚（端到端已验证）**：track2 harness 重跑 baseline 三窗全字段逐位复现
  ma_join 读数（decision 0.0835 / oos1 0.0657 / oos2 0.0572）；实现取"默认值直接写
  归一化精确值"设计（`__post_init__` 归一化会污染 from_patch 相对语义，弃用），
  TS `normalizeRankTrendRuntimeConfig` 同构扩展 5 权重（幂等锚已测试锁定）。
- **TS 合同同步**：归一化合同 4 权重→5 权重（rankTrendDefaults.ts）；TS 买票计数
  4 票→5 票（+MA 金叉，与 py compose_decision 分量对齐）；signalSnapshot/对照快照
  补 maCross 字段。
- **回退**：`maWeight: 0`（TS/py 同构）→ 其余四权重按比例归一化回填旧四因子口径；
  或整体 revert 本次提交。
- 实施详情见长测计划 §21.8；判定报告 `data/reports/track2-candidates.json`
  （落默认前基线备份 `track2-candidates-pre5factor.json`）。

## 10. 技术信号五权重实证重定义（2026-09-13 阶段 22.8，取代 §9 归一化继承口径）

五权重自阶段 21.8 落默认后经两层实证重评估（层 1 事件级区分度 + 层 2 留一/半权/
剂量扫描边际贡献，decision/oos1/oos2 三窗，57 次全量 replay；harness
`backend/operations/evaluate_ts_factor_weights.py`，报告
`data/reports/ts-factor-weights.json`），用户决策采纳 **p2_aggressive** 档。

| 参数 | 旧默认（§9） | 新默认 | 来源 | 状态 |
|---|---|---|---|---|
| directionWeight | 0.24 | **0.06** | 阶段 22 三窗边际贡献：2/3 窗强负（loo +13.9%/+17.0%），剂量单调 | **落默认**（2026-09-13 用户决策） |
| accelerationWeight | 0.20 | **0.04** | 唯一三窗一致负（+2.6%/+7.0%/+6.8%） | **落默认**（同上） |
| crossWeight | 0.16 | **0.24** | decision 正贡献（loo −3.1%），余量吸收 | **落默认**（同上） |
| macdWeight | 0.20 | **0.29** | decision 正贡献最强（loo −4.1%）；oos 上探受损故升幅受控 | **落默认**（同上） |
| maWeight | 0.20 | **0.37** | 唯一 ×1.5 上探三窗全正（+1.4%/+0.9%/+1.6%） | **落默认**（同上） |

- **提案判定卡（Track 2 同口径）**：p2_aggressive = PASS_CANDIDATE——C1 决策窗
  saEx rel +12.5%；C2 oos 双窗同向 +30.0%/+28.9%；C3 passHard 保持；附加卡 C4
  retreat 桶 −0.045（已知代价，用户知情采纳）、weak 桶 +0.021；C5 翻转率不变
  （veto 走 lifecycle 层，与五权重解耦）。
- **端到端新锚（已验证）**：落默认 baseline 三窗逐位复现 p2 读数（decision
  0.0939 / oos1 0.0854 / oos2 0.0737）。
- **maJoin 历史 patch 锚保留**：`from_patch(设计值 1.25)` 归一化仍得
  0.24/0.20/0.16/0.20/0.20（归一化只看 patch 自身和，与默认解耦，测试锁定）。
- **TS 同步**：`rankTrendDefaults.ts` 五权重同值；maWeight=0 回填语义随比例联动
  （其余四权重 ÷0.63），不再是旧四因子口径。
- **回退**：五权重恢复 0.24/0.20/0.16/0.20/0.20（py/TS 各一处 + 测试锚），或整体
  revert 本次提交。
- 实施详情见长测计划 §22.8；buyScoreThreshold 不变（S+A 触发率预期 −22%，
  观察期 <3.5% 再评估，见长测计划 §22.6）。

## 11. 周期（lifecycle）维参数贡献率评估（2026-09-13 阶段 23，OBSERVE 不落默认）

评估 harness `backend/operations/evaluate_lifecycle_dimension.py`（三窗 51 trial/窗，
报告 `data/reports/lifecycle-dimension.json`）；口径与判定详见长测计划阶段 23。
**结论：B 组阈值族整体钝感（组合提案 OBSERVE，C1 decision +0.3~0.6% 远低于 +3% 线），
A 组展示分权重 5/5 逐位零效应判冗余——全部维持默认，零默认值改动。**

| 参数 | 默认值 | 阶段 23 评估结论 |
|---|---|---|
| lifecycleMidLongCommitmentMin | 15.0 | **钝感（唯一三窗全正方向）**：收紧 ×1.5~×3 oos2 +3.5~+7.1% 剂量单调、oos1 +0.9%，但 decision 恒 <1% 不达 C1 +3%；复核=9 月全月重扫 |
| lifecycleWeakPathCommitmentMax | 0.45 | **U 型谷底最优**：放宽侧 oos1 −5~−7.6%、收紧侧 decision −0.9%，维持不动 |
| lifecycleVelocityMin | 18.0 | 收紧止步 ×1.25（×1.75 decision/oos1 转负），跨窗不稳，维持不动 |
| lifecycleAccelMin / AccelCommitmentMin / LowVisibility* | 12.0/8.0/0.7/18.0 | 钝感（±1% 内、跨窗不一致） |
| lifecycleHighRiskPressureMin | 0.75 | 默认已在"基本不触发"位（×1.5/×2 零效应）；×0.5 放宽 veto decision −2.3% 不划算 |
| lifecycleHighRiskDivergenceMin / OverheatMin | 0.8/0.7 | 结构性零效应（背离∧过热组合分支从未触发）；前提=pressure 门 0.75 不活跃，门变活跃需重扫 |
| riskPressureWeights | [0.58,0.42] | 结构性零效应（±0.12 漂移不跨任何活跃消费阈值） |
| decisionReversalPressureMin/OverheatMin/MarginMax | 0.78/0.7/0.05 | **saEx 口径结构性盲区**：final 信号不进 synergy 投票链，只进交易层；交易层效应需 Track 1 口径另评 |
| decisionReversalFinalConfCap | 62.0 | confidence-only 不入扫（不改信号方向） |
| lifecycleWeights | [0.35,0.25,0.2,0.2] | **判冗余（signal-neutral）**：5/5 trial 三窗对 synergy saEx/passHard/翻转率/信号量逐位零效应；只承担 observation.lifecycle.score 展示分，默认保留 |
| lifecycleMomentumWeights | [0.3,0.45,0.25] | 同上（判冗余，展示分面） |
| decisionRiskPenaltyWeights | [11,9,5] | 同上（判冗余，confidence-only 面） |

- **范围排除重申**：cycleRaw*/cycleNorm*/cycleConf* 50 结构参数维持 §5.1 D 项裁定
  （不扫描）；lifecycleConfirmFrames 维持阶段 12 证伪结论（K=1）。
- **五维闭环注记**：共振/量价/周期维存量候选全部 OBSERVE，唯一落默认=趋势五权重
  （§10 p2_aggressive）；saEx 口径参数空间接近饱和，后续增益优先找口径/因子层抓手。
- **复核触发**：① 9 月全月重扫 MidLongCommitmentMin（oos2 信号全月复现则重出提案）；
  ② HighRisk pressure 门变活跃时重扫 HighRisk 三参数 + riskPressureWeights；
  ③ decisionReversal* 交易层评估走 Track 1 独立任务。

## 12. synergy 维度票权重与档位强度（2026-09-14 阶段 23.9，已落默认）

| 参数 | 旧默认 | 新默认 | 来源 | 状态 |
|---|---|---|---|---|
| tierSynergyResonanceVote | 1.0 | **0.75** | 阶段 23.9 两轮扫描（×0.5/×0.625/×0.75 三窗全正，单轴最强 +8.3/+18.4/+17.4） | **落默认**（2026-09-14 用户决策 combo_three_quarter） |
| tierSynergyRankVote | 1.0 | **0.75** | ×0.5/×0.625/×0.75 三窗全正 | **落默认**（同上） |
| tierSynergyVolumePriceVote | 1.0 | **1.0（不变）** | 两轮证据：窄峰（×0.75 oos2 −6.4、×1.25 OBSERVE、×0 oos1 −64.4、×1.5 dec −30.5） | 维持（唯一不动轴） |
| tierSynergyCrossSectionVote | 1.0 | **0.75** | ×0.5/×0.75 三窗全正（×0.75：+6.2/+13.7/+3.0） | **落默认**（同上） |
| tierSynergyVoteStrengths | — | [1.2,1.0,0.8,0.5,1.0,1.0] | 2026-09-14 参数化（原 _VOTE_STRENGTH，v4 实证值） | 结构参数登记，未扫描 |
| tierSynergyCsStrengths | — | [1.0,0.5,−0.5,−1.0] | 同上（原 _CS_STRENGTH） | 同上 |

- **落默认口径锚（端到端已验证）**：新默认三窗 replay 逐位复现 combo_three_quarter
  实证读数（decision 0.1044 / oos1 0.0918 / oos2 0.0933）；判定卡 C1 +11.2% /
  C2 oos +7.5%/+26.6% / C3 passHard 保持 / C4 regime 四桶 \|Δ\|≤0.01（retreat −0.0091）/
  C5 veto Δ=0、bd Δ=−0.029 改善。
- **结构性下限（已实证）**：三轴同减至 ≤0.5 → v 上限 2.6 < A 线 2 → S/A 档塌缩、
  saEx 统计退化（三窗 None）——票权与档位线（tierSynergyVote*）耦合，减票权的
  同减下限是 0.75。
- **TS 同步**：`tierDisplay.ts` 悬停票值改加权分值（res/rank ×0.75、vp ×1.0、cs ×0.75）；
  后端 py 为唯一 golden 计算链，TS 无生产投票职责。
- **硬编码参数化清点（2026-09-14，同批）**：synergy 档位强度/量价阶梯/风险阶梯与
  regime 五因子/技术 fallback/展示面共 ~90 项 config 化（默认值=原值零漂移），
  登记为结构参数未扫描；清单见长测计划 §23.9。
- **运维注记**：S 档触发收紧（v≥3 需 vp 强票同向）；单维反向票不再触发 D 档
  （reverse 线 −1，反向确认需两维同向）；oos2 passHard 边缘失效为 9 月全月复验
  第一观察项（10 月上旬 Track 2 三窗重跑复现方可保持）。
- **回退**：py 三字段还原 1.0 + TS tierDisplay 权重常量还原，或整体 revert 本次提交；
  config_hash 天然区分两代口径，历史数据不迁移不重算。
- 实施详情见长测计划 §23.9/§23.9.1；报告 `data/reports/dimension-voting-power.json`。

## 13. 生命周期环境门干预形态参数（2026-09-14 阶段 24，参数化+全轴扫描，默认=hard 不变）

| 参数 | 当前值 | 来源 | 结果 |
|---|---|---|---|
| lifecycleVetoGateMode | "hard" | 阶段 24 两轮扫描 | **hard 为峰**：软化 decision 单调受损（0.375/0.75 档 −4.6/−3.2%），强负票 1.5/2.25 零效应；与阶段 12 K 实验、23.8 归零三重同向 |
| lifecycleVetoPathMode | "all_soft" | 阶段 24 | reversal_hard/highrisk_hard 分流三窗逐位零效应（负票不进链） |
| lifecycleVetoVoteStrength | 1.5 | 阶段 24 | 仅 soft 模式消费（默认 hard 不生效） |
| lifecycleDowngradeGateMode | "hard" | 阶段 24 | penalty 剂量 U 型峰=1.0（数学等价硬降档）；0.25~0.75 与 1.25~off 全受损；降档关闭 −39/−34/−5.8% |
| lifecycleDowngradePenalty | 0.5 | 阶段 24 | 仅 soft 模式消费（默认 hard 不生效） |
| volumePriceGateMode | "hard" | 阶段 24 | off 档 saEx +9.8/−3.0/+33.4% 但 Track 1 交易复核主窗 wrxpf −32%、maxDD 加深——**交易层否决维持 hard**；soft 逐位=hard（vp E 负票落 D 同档） |

- 组合 p2（vp off × veto 负票 0.75）：saEx 三窗全正 PASS_CANDIDATE，Track 1 主窗否决，
  入观察池（复核触发：9 月全月复验与 §12 挂起复验同批）；
- 方案 B 连续环境分（lifecycle.score）方向内容 FAIL（U 形，spearman −0.1）——score 保持
  展示/解释语义，不得升级为门控输入（否则 §4.2.2 台账变更义务触发）。

## 14. 维度信号再审视四方案（2026-09-15 阶段 25，全部零默认值改动）

### 14.1 synergy 维度票权（23.9.1 临时默认的 Track 1 直验，方案 A）

| 参数 | 当前值 | 交易层直验（decision 窗，w1_old 臂） | 状态 |
|---|---|---|---|
| tierSynergyResonance/Rank/CrossSectionVote | 0.75/0.75/0.75 | wrxpf 0.4702 vs 旧 1.0 票权 0.2913（−38%） | **0.75 获交易层直验证据**；L1 §12 补记挂起至 9 月全月复验（m2） |
| 四维票权（归零臂） | — | 归零受损 23~55%（res/rank/vp/cs），无翻转 | 票权>0 交易层证据存档 |

### 14.2 cs 档位强度表（方案 B 扫描）

| 参数 | 当前值 | 结果 |
|---|---|---|
| tierSynergyCsStrengths | [1.0, 0.5, −0.5, −1.0] | **现值即峰**：csC 两侧全负（松绑触发回灌兑现）、csD 结构惰性、csA OOS 全负；csB_025 C1+C2 但 C3 硬门失败（passHard=False）；B2 等价对照对（整表缩放 ≡ 票权轴）三窗逐位验证含崩溃面 |

### 14.3 vp 量价批 2 字段（方案 C-b 扫描，取代 23.9"未扫描"登记）

| 字段族 | 结果 |
|---|---|
| volumeScoreUp(14)/Down(4)/fundScore(5)/directionThresholds/amountScoreStep | **10/10 零效应（结构性）**：全部为分值幅度面——×正缩放不改符号比较（fund_score>0 A/B 分界）与阈值比较（对倒/过度放量由 AbnormalFundRatio/OverVolumeRatio 触发）；档位决定面 = 阶段 9 已扫的 4 个 ratio 阈值。冗余归档（23.3 A 组模式，不删实现） |

### 14.4 vp C-a 新基线复核（阶段 9 旧结论存活对照）

| 参数 | 当前值 | 新基线三窗（dec/oos1/oos2） | 结果 |
|---|---|---|---|
| volumePriceAbnormalFundRatio | **10.0**（2026-09-15 用户决策落默认，原 20.0） | **+7.3/−4.1/+1.9%**，Track 1 decision wrxpf +2.9%（oos2 23 笔观察级 −39%） | **已落默认**：端到端新锚 decision 0.1120 / oos1 0.0880 / oos2 0.0951 逐位复现实证读数；回退 = 还原 20.0；主计划 §25.7 |
| volumePriceOverVolumeRatio | 2.5 | 0.0/−22.2/−34.5% | 基线漂移失效，维持 2.5 |
| fund10+over2 | — | +11.4/−25.2/−31.2% | 观察池方向未恢复，维持挂起 |
| volumePriceMildRatio | 1.05 | −2.7/+7.7/+14.7% | 跨窗矛盾 OBSERVE |

### 14.5 共振频率轴与展示面（方案 D）

| 参数 | 当前值 | 结果 |
|---|---|---|
| resonanceMinMarketSampleCount | 20 | **结构性惰性**（10/40 两档三窗逐位=baseline；缺票帧由 NaN median 拦截非计数值） |
| resonanceMidWindowBars | 8 | 跨窗矛盾（mid6 oos2 −18.3% 确认 H1 保护机制；mid10 OOS 双正但 decision −0.7% 不过 C1） |
| resonanceLabelThresholds / resonanceWeights | [85,67,50,27] / [0.35,0.25,0.2,0.2,0.2] | **zero_effect_redundant**（23.3 A 组模式收口；代码事实：只进 raw_score→score 展示分）——"批 5 展示面未扫描"状态关闭 |

- D-a 结构普查修正：res 真实投票率 72-79%（三窗），23.8"~44%"勘误口径作废；缺票主导
  分支 = 排名序列不足（13-15%）；H1 保护机制成立（回收反事实三窗全负），H2 线索
  （NaN median 帧 exAcc +5.7%）属代码级课题；
- 投票率分母口径注记：D-a 的 72.2%（decision）分母 = 有 res 数据的信号（弃权按缺票
  原因分解）；D-b `resonanceParticipation`（decision 69.0%）分母 = 全部信号（含无
  res 数据帧，记空方向）。两数分母不同不可直接对照，缺票结构对照以 D-a 分解表为准；
- fund10 已落默认（§14.4）；23.9.1 §12 补记挂起至 9 月复验；锚点代际：23.9.1 锚（0.1044/0.0918/0.0933）属 pre-fund10 口径，当前基线锚 = 0.1120/0.0880/0.0951（post-fund10）。

## 15. 六案参数缺口补扫（2026-09-15 阶段 26，方案 ranktrend-param-gap-scan-plan.md，全部零默认值改动）

> 判定卡：C1 decision saEx rel ≥+3% ∧ C2 OOS ≥1 窗同向为正 ∧ C3 decision passHard 不降。
> 基线锚 post-fund10（0.1120/0.0880/0.0951）三案全窗扫描逐位复现。
> **关键方法论发现：saEx = S/A 两档合并加权 excessDirectionAccuracy
> （optimize_resonance_parameters.py `sa_excess_of`），B/C/D 档完全不在统计集——
> 凡只迁移负票/中性档的阈值线，saEx 结构性不可见（本批 3 处实证，见 §15.2/15.3/15.5）。**

### 15.1 cs 档位阈值族（P1，37 trial 全窗 + P1-0 参数化 crossSectionStrongAbsMin）

| 参数 | 默认 | 扫描结论 |
|---|---|---|
| crossSectionStrongAbsMin | 70.0（本轮参数化，原硬编码） | **默认即跨窗权衡峰**：收紧 75/80 decision +4.2/+12.0% 但 oos 双大负（−13.3/−19.8 / −2.2/−20.5）；放宽 60/65 decision −3.2/+0.3 而 oos1 +9.0/+9.9。维持 70 |
| crossSectionStrongMin | 85 | strongMin_80 唯一 C1 过线（+3.0%）但 oos 双负 C2 失败；维持 |
| crossSectionStrongDeltaUp | 5 | 全档弱（≤±2.4%），维持 |
| crossSectionMidMin / MidDeltaUp | 50 / 15 | decision 弱、oos 矛盾方向（midMin_60 oos2 +16.6% 但 decision 0.0/oos1 −11.4%）；维持 |
| crossSectionMidMax / MidDeltaDown | 50 / −15 | **真惰性**（8 trial 三窗 cs 档位分布逐位 identical，移动区间无分布密度）；归档 |
| crossSectionWeakMax / WeakDeltaDown | 15 / −5 | **C/D 归类活跃但下游零传导**（weakMax_20 D 档 6477→8170 +26% 而 A/B 桶逐位不动，效应链终止于投票输入）；归档 |

### 15.2 synergy 三线与档位强度（P2，33 trial 全窗 + Track 1 复核 ×2）

| 参数 | 默认 | 结论 |
|---|---|---|
| tierSynergyVoteStrengths[2]（B 档强度） | 0.8 | **vsB_070/060 唯一三卡全过**（C1 +8.7/+6.4%、C2 oos +14.2/+10.3/+7.4、C3 保持）；Track 1 复核：vsb070 wrxpf +0.9%（149 笔，中性）→ **OBSERVE 观察池**；vsb060 wrxpf −7.9%、ret −10.2%、dd −23.8% → 拒绝。剂量自洽：降越深交易层入场面收缩越狠（−1/−21 笔）。复核触发挂 9 月全月复验同批 |
| tierSynergyVoteStrengths[0]（S 档强度） | 1.2 | vsS_100 三窗全正但 C3 违反（档位单调性硬约束破）；维持 |
| tierSynergyVoteStrengths[1/3/4/5]（A/C/D/E） | 1.0/0.5/1.0/1.0 | vsA decision 全负；vsC 跨窗反向；vsD 无信号；维持 |
| tierSynergyVoteStrong | 3 | 2.25/2.5 档 saEx 剂量升（+4.5/+23.8%）但 passHard 三窗全崩 + oos2 负；**维持 3** |
| tierSynergyVoteWeak | 1 | **saEx 盲区非惰性**：weak_150 使 B 档腰斩（12181→5962）三窗同向，但 S/A 桶逐位不动 → 效应面=候选池构成，Track 1 口径课题 |
| tierSynergyVoteReverse | −1 | 同上：reverse_neg050 使 D 档 +21%（C→D 迁移），saEx 不可见；Track 1 口径课题 |

### 15.3 regime/risk 线位（P3，P3-0 活跃度诊断 + smoke 12 trial，全窗扫描取消）

| 线位 | 裁定 | 依据 |
|---|---|---|
| regimeStrongScore | 70 | **非惰性，saEx 盲区** → Track 1 交易层课题（禁入门面）。smoke 分桶强区分度：strong 桶 saEx 0.079→0.272 单调（60→75 档）、桶样本 6728→460 |
| regimeNormalScore / WeakScore | 50 / 30 | 惰性免扫（±10 迁移 <1%；默认 regimeGateStrongBan=True 下 normal↔weak 迁移不接门，runtime.py:787-796） |
| risk Overheat/Divergence Sell/Hold 四线 | — | **消费面收口**：唯一消费方 execution.py:1441 回测展示文本，决策面零消费 |
| riskSynergyOverheat/DivergenceSevMin | 0.65 / 0.6 | **confidence-only 面冗余**（final_conf 不回写方向 runtime.py:311-312 + 双门 AND 触发率 0.38-0.72%）；smoke 8 档 oos2 逐位=baseline |

### 15.4 vp 量价 amount 族（P4，zero_effect 收口，全窗取消）

volumePriceAmountScoreStep/AmountScoreWeight 等 amount 族：**zero_effect**（消费链：amount_score→score 而 `_volume_price_tier` 不消费 score，`_synergy_tier` 只吃各维 signalTier；decision 窗 amount 可算率仅 6.12% 低杠杆、oos2 95.82% 排除假惰性）。冗余归档不删实现。

### 15.5 趋势漏网（P5，23 trial 全窗 + 消费链核实）

| 参数 | 默认 | 结论 |
|---|---|---|
| buyThresholds/sellThresholds（镜像缩放） | [2.5,4,6.5,10.5,17] | decision 全负 −0.2~−2.2%；oos1 剂量正（×1.5 +17.5%）但跨窗矛盾不达 C1；维持 |
| trendLongAgreeMin | — | **dead output**（config 定义、引擎零消费点）；冗余归档（同 momentumConfidenceSlope 模式） |
| momentumScoreThreshold | 35 | **零效应**（25↔45 全区间 candidateTier 逐信号 diff=0 + saEx 三窗逐位；消费真实 technical.py:219 但档位区间不可达）；归档，未来动此参数需先查 momentum score 分布 |
| directionThresholds/accelerationThresholds 重加权 | — | 弱负/零，维持 |
| requireMacdGoldenCross | False | 对照确认默认关闭正确（开启 decision −9.4%）；关闭对照存档 |

### 15.6 ATR/Jump（P6，诊断 + smoke，不开发）

- **P6-a ATR 确认门**：三窗 unknown 60.7/67.7/72.8% 全 >50% 硬判据 → 数据不足不开发；根因=轮动断档 gapResets 82.3 万（比 missingBars 高一个量级），oos 两窗覆盖已修复至 98%+，未来全月复验时重测；
- **P6-c Jump 确认门断线（结构性发现）**：生产枚举 direction="buy"/"sell"/"hold"（runtime.py:176）vs 确认门只匹配 "up"/"down"（runtime.py:220-241），10936 事件全部落 `else: ok=True` 无条件放行——确认门自上线起未实际过滤。接线修复属 engine 行为变更，**登记后续课题待用户决策**（修复后确认参数才有扫描意义）。
- **P6-c 断线已修复（2026-09-15 当日，用户决策"请修复"）**：`_confirm_jump` 确认分支改按生产枚举匹配
  （`buy`/`up` → 向上确认；`sell`/`down` → 向下确认；`hold`/None/未知仍视为无确认需求放行，audit
  2026-08-18 语义不变），G4 确认门（jumpConfirmChangeMin=3.0 / jumpConfirmVolumeRatioMin=1.0）自修复起
  真实生效。TDD：test_confirm_jump.py 追加 8 个生产枚举用例（RED 5 失败精确暴露断线面 → GREEN 全绿，
  17 passed）；harness 断线锁定测试翻转为接线修复回归锚（test_confirm_gate_wiring_fixed）；影响面
  130 个相关测试全绿（jump/engine/golden_alignment/v5_live_contract/replay/signal_tiers/resonance/
  synergy_gate 等）。**行为影响**：修复后默认输出信号序列与断线代际不同（弱确认 buy/sell Jump 降级
  hold，不进共振票）；evaluate_jump_confirm_parameters 既有 baseline 锚为断线代际读数，修复后重跑
  锚漂移 raise 属预期；修复后代际效应量化 = data/reports/jump-confirm-postfix-baseline.json
  （decision 窗）。
- **修复后门效应量化（decision 窗单窗首跑，280s；窗口已消费 M3 折扣，oos 双窗未跑——锚漂移即停纪律）**：
  syn saEx **0.1323** vs 断线代际锚 0.1120（**相对 +18.1%**），passHard=True 保持；G4 降级率
  **84496/105064 = 80.42%**（门真实拦截的直接读数，断线代际恒为 0——此前八万余假 Jump 全部
  放行进共振票）；核验后放行 20568（19.58%）；jumpVoteShare 10.95%（断线代际 D-a 基线 12-14%，
  过滤后下降方向符合）。**解读纪律**：单窗读数非落默认证据（本次为 bug 修复使 G4 已评审设计生效，
  默认值未动，判定卡流程不适用）；jumpConfirm 两参的剂量扫描在修复后代际重新立项（§26.10 遗留 2）。

### 15.7 交易层口径课题清单（本批合并登记，均 saEx 盲区、效应面=交易层）

1. **tierSynergyVoteWeak / tierSynergyVoteReverse**（P2：B 档 ±51% / D 档 +21% 分布迁移）；
2. **regimeStrongScore**（P3：禁入门面，分桶 saEx 单调区分）；
3. **decisionReversalPressureMin/OverheatMin/MarginMax**（§11 既有登记）；
- 三项共用 Track 1 口径（track1_lifecycle_gate_trade --extra-arm / track1_dimension_power，M2 30 笔门槛）；
建议同批立项一次跑完；9 月全月复验（10 月上旬）时 vsB_070 观察池结论同批裁决。

## 16. B-202610 正式复跑批次（2026-09-30，阶段 27 台账面）

> 第四代正式四窗锚：decision 0.1323 / oos1 0.0862 / oos2 全月 0.0841 / oos2u 0.0534，passHard 全 True（注册表 accedac2）。判定卡与裁决见长测阶段 27；本节记参数台账面结论。

| 项 | 结论 |
|---|---|
| R1-R4 回退复核 | 四项回退 trial 判定卡全线不成立 → 已落默认全部保持（C1 负 + C4 strong 大降为共性） |
| R6 tp0.06×be0.02 | 保持确认：oos2 全月少亏 25.5pp（−14.27% vs −39.73%），decision 两栈逐位同（市场状态依赖第六次复现）；M2 未达披露 |
| O3 tierSynergyVoteStrengths[2]=0.7 | **PASS_CANDIDATE 进用户决策队列**：Track 2 全卡过（C1 +5.97% ∧ 三 OOS 全正）+ Track 1 oos2 全月 80 笔逐位同 baseline（中性不受伤，M2 达） |
| O6 lifecycleMidLongCommitmentMin ×3 | 触发成立且增强，x30 提案重出（C1 +3.93%/C2 三 OOS 全正/C3/C5 过；C4 待补）；c1/c2 组合 C1 未过 OBSERVE |
| N1 jumpConfirmVolumeRatioMin 紧侧 | monitor_only 立项建议：vr1.25/1.5 三窗全正（oos2 +5.35/+6.90%）；chg 轴不干净；松侧无收益 |
| N8 degradedSampleFloor 5→3 | 终判链闭合：insufficient 三窗 h1/h8 复现 −5.4~−5.9pp；Track 1 80 笔无伤害；A 档 h8 优势不稳 + B 档样本偏小 + 幸存者偏差标注 → 落默认提案条件具备（用户决策，一次一候选） |
| O7/O8/O10 | 维持挂起（触发不成立 / 合并 n=439 方向翻转增强 / 断板 0 触发） |
| 台账落痕核对（阶段 5.4） | P1-b persist 交叉对照 trial：未在本批发现执行落痕；persist_on 判定卡 OBSERVE（C1 −11.26% + C4 strong −25.35%）——crossSectionPersistFrames 维持关闭（与 N13 一致） |
| 新增工程注记 | track2 BASELINE_ANCHORS 四窗激活 trial 级断言；ma_join/ma_full trial 定义疑重复待去重；lifecycle_dimension 死常量锚仍待切注册表（本批读数级人工对照替代） |

## 17. B-202610 批次落默认三连（2026-09-30 用户当批裁决）

| 参数 | 变更 | 判定依据 | 回退路径 | 代际/commit |
|---|---|---|---|---|
| tierSynergyVoteStrengths[2]（B 档票强度） | 0.8 → **0.7** | Track 2 全卡过（C1 +5.97% ∧ 三 OOS 全正）+ Track 1 80 笔中性；用户裁决转正 | index2 patch 0.8（track2 O3_revert_vsB080 对照臂） | gen-vsb070 / eabf4b44 |
| degradedSampleFloor | 5 → **3** | insufficient 三窗 h1/h8 复现 −5.4~−5.9pp + Track 1 80 笔无伤害 + A 档 h8/B 档样本/幸存者偏差三标注；用户裁决转正 | patch 5（repool FLOORS[0] 显式基线臂） | gen-floor3 / dfbf849b |
| lifecycleMidLongCommitmentMin | 15 → **45**（×3） | §23.7 触发成立且增强 + C1/C2/C3/C5 过 + C4 补测过；用户裁决转正 | patch 15（lifecycle 剂量臂显式基线） | gen-midlong-x30 / 29f96c9f |

- 第七代锚（三参组合实跑）：0.1472/0.1016/0.0981/0.0698，passHard T/F/T/T；此后全部 harness 自动跟随。
- R1-R6"防反悔"复检用户确认不反悔（2026-09-30），本台账 §14/§16 各"保持"结论转正式确认。
- TS 同步：tierDisplay VOTE_STRENGTH B=0.7；另两参数无 TS 镜像（核实）。
- 首日人工验证待用户：B 档展示一致性 / 周期列样本不足占比 / 中长承诺信号触发率与 S+A 触发率（<3.5% 预警线）。

## 18. 生命周期时间正规化 G1 落默认（2026-10-07 用户裁决）

| 参数 | 变更 | 判定依据 | 回退路径 | 代际/commit |
|---|---|---|---|---|
| lifecycleTimeGapStrictness | off → **cross_day** | P1/P3 预登记合同（Opus 4.8 两轮审定，语料 §11/§11.2）全链：诊断 ER=3.33[CI 3.18-3.49]（velocity>18 帧 42% 为跨日假动量，集中驱动状态跃迁）；trial G1 三窗 saEx 相对线全过 + veto 误伤 −6.8% 三窗一致（可归因=跨日跳变驱动的 reversal 误判消除）+ bd +1.0% 带内；Track 1 交易层中性（decision wrxpf +0.9%、166→172 笔、maxDD 改善）。用户裁决理由：热榜环境门否决过多、早有错判误杀嫌疑 | patch `lifecycleTimeGapStrictness="off"`（诊断对照臂，配置面保留） | gen-g1-gap / cd26347b 后续落默认 commit |

- **基线锚换代登记**：10 月帧字段回填（e77907bb/cacf4ab8 代际）致绝对锚 0.1044/0.0918/0.0933 不可复现（今日 a0=0.1472/0.1016/0.1071，wrxpf 基线 0.4702→0.4104 同源漂移）——本参数判定全程改用**同代际相对线**（容差不变 −0.005/−0.003）；**G1 新基线锚（今日代际）= 0.1450/0.0983/0.1172**，后续 harness/月度复验自动跟随。
- **行为语义**：相邻序列元素跨交易日 → 该步 velocity/acceleration/shock 缺证据（输出 null + temporalGap 标记，不插值），raw 沿袭前帧（封死 NaN 比较全 False 静默滑 cooling 路径）；risk 动量分量中性化（`analyze_risk` 入口统一防）；normalize 照常（状态自然沿袭）。
- **G2（non_adjacent）未落默认**：oos1 贴线差 0.0001 FAIL，按合同 G3 不试；如需重开须在 G1 新基线上重新预登记（用户「再看 G2」= 待新代际复扫，非自动翻案）。
- **TS 同步**：types.ts cycle.metrics 增 temporalGap?: boolean + 动量字段 number|null；DataTable 周期列 tooltip 增缺口标注（fail-visible）；无镜像阈值。
- **golden**：快照重录（configRepr + 场景输出真变化：gap 帧 metrics null/标记、假降温修复、risk overheat 中性化；diff 逐字段审查全在 G1 语义预期内）。
