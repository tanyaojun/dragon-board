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
| lifecycleTimeGapStrictness | off → **cross_day** | P1/P3 预登记合同（Opus 4.8 两轮审定，语料 §11/§11.2）全链：诊断 ER=3.33[CI 3.18-3.49]（velocity>18 帧 42% 为跨日假动量，集中驱动状态跃迁）；trial G1 三窗 saEx 相对线全过 + veto 误伤 −6.8% 三窗一致（可归因=跨日跳变驱动的 reversal 误判消除）+ bd +1.0% 带内；Track 1 交易层中性（decision 窗 wrxpf +0.9%、166→172 笔、maxDD 改善；oos2 80→76 笔 wrxpf −3.8% 带内，两窗合并读法=中性，见语料 §11——两窗均小样本噪声量级）。用户裁决理由：热榜环境门否决过多、早有错判误杀嫌疑 | patch `lifecycleTimeGapStrictness="off"`（诊断对照臂，配置面保留） | gen-g1-gap / cd26347b 后续落默认 commit |

- **基线锚换代登记**：10 月帧字段回填（e77907bb/cacf4ab8 代际）致绝对锚 0.1044/0.0918/0.0933 不可复现（今日 a0=0.1472/0.1016/0.1071，wrxpf 基线 0.4702→0.4104 同源漂移）——本参数判定全程改用**同代际相对线**（容差不变 −0.005/−0.003）；**G1 新基线锚（今日代际）= 0.1450/0.0983/0.1172**，后续 harness/月度复验自动跟随。**锚取代关系：§17 第七代锚 0.1472/0.1016/0.0981/0.0698 属 G1 前默认配置（off）的绝对锚，自本节起仅用于 G1 前代际对照，月度复验以本节 G1 新锚为准。**
- **行为语义**：相邻序列元素跨交易日 → 该步 velocity/acceleration/shock 缺证据（输出 null + temporalGap 标记，不插值），raw 沿袭前帧（封死 NaN 比较全 False 静默滑 cooling 路径）；risk 动量分量中性化（`analyze_risk` 入口统一防）；normalize 照常（状态自然沿袭）。
- **G2（non_adjacent）未落默认**：oos1 贴线差 0.0001 FAIL，按合同 G3 不试；如需重开须在 G1 新基线上重新预登记（用户「再看 G2」= 待新代际复扫，非自动翻案）。
- **TS 同步**：types.ts cycle.metrics 增 temporalGap?: boolean + 动量字段 number|null；DataTable 周期列 tooltip 增缺口标注（fail-visible）；无镜像阈值。
- **golden**：快照重录（configRepr + 场景输出真变化：gap 帧 metrics null/标记、假降温修复、risk overheat 中性化；diff 逐字段审查全在 G1 语义预期内）。

### 18.1 code review 修复（2026-10-07 当日，双 subagent 审定 a44d965f）

- **P1 live/快照落库链接线补齐**：`_analyze_frames→_analyze_one_stock` 此前未传时间键，G1 默认在 live API 与快照 analyze 链静默失效（golden/backtest 新口径 vs live 旧口径两代际分裂）——补时间键/帧索引接线（frameKey→tradingDate/帧索引反查映射，复制尾 trim 同步），新增 `test_live_analyze_chain_wires_time_keys` 守卫。
- **P0 前端标注可达性**：temporalGap 缺口标注原写在 `getTierReasonsOf` 兜底分支（周期列 tooltip 走 `showTierTooltip` 显式分支，永不消费）——移入显式分支并删死代码，补防回归断言两则；文档「已生效」表述随修复成立。
- **fail-visible 两处**：strictness≠off 但时间键缺失/长度不匹配 → decision reasons 显式标注（不静默降级）；空键步不判 gap（不误报）且计数标注。
- **防御修正**：`neutralize_gap_metrics` 改按值判据（键存在且 None/NaN → 0），不依赖 temporalGap 标记（旧快照无标记 None 不再 TypeError），缺键不悄悄补 0。
- **测试修复**：raw 沿袭同义反复断言改独立前帧对照；TestEngineWiring 虚假覆盖改 live 链真接线；analyze_api 判别锚夹具三帧改同日多槽（G1 下跨日差分不再充当动量证据，锚失效根因修复）。
- 后端全量 3261 过（ranktrend 620）+ 前端 vue-tsc/vitest 专项过。

## 19. 四投票信号研讨轮（2026-10-07，五案行为步全部不晋升；新参数全默认零行为）

> 语料 `reasoning-corpus-voting-signals.md`（§11 双模型 A/B 审定+§12.0 预登记+§12.1 R1+§12.2 合同+§12.3 执行报告）；双模型（用户执行投喂）审定后用户三裁决开跑。B0 锚=G1 代际 0.1450/0.0983/0.1172（T2 runner 逐位自证 PASS；population=09-12 帧截止口径与锚同源）。

| 参数/结构 | 状态 | 判定依据 |
|---|---|---|
| resonanceWarmingEnabled / resonanceWarmingTierCap | **新增，默认 off/none**（T3 warming 补票开关） | D1 假设线过（warming buy h8 +0.0142）但判定卡 FAIL_C1：W1 −1.0%/+5.2%/0.0%、W2 −2.0%/+3.2%/0.0%（cap 越深 decision 越伤）；存档不晋升 |
| crossSectionPersistIndependentTier / tierSynergyCsPersistStrength | **新增，默认 False/0.5**（T4 A_PERSIST 独立档+三态票值） | D1 阶段1 过线（diff +0.0218 strong/retreat 同向）但三态判定卡全 FAIL：正态 decision **−11.7%** 重伤（D1 h8 分层好≠加权后 saEx 好，saEx 教训镜像案例）、零态逐位一致 PASS_IDENTICAL（纯标签保留待裁）、负态 oos2 −13.3% |
| 新入榜 S 死分支（runtime analyze_rank_resonance） | **已删除（T5a 零行为）** | len==1 < detect_rank_jumps len≥3 ⇒ freshness 恒 0 恒不可达（模型A 发现，主会话代码核实）；G4 断线先例=静默激活风险；逐位验证三窗 saEx 逐位一致+644 绿；两测试锚更新（函数级直注 events 亦不判 S）；T5b「入榜即事件」归档（would_syn_S=0，len1 cs≤B 封顶 2.8<3.0 结构性） |
| jumpConfirmVolumeRatioMin 1.25/1.5 | **维持 1.0，观察池** | T2 判定卡 FAIL_C1（+1.4%/−0.4% decision）但 oos2 连续两代双位数正（+9.8%/+10.3%）+护栏全过（resS/synS 半数线）+Track 1 −2.0%（未触终止）——N1 同款命运，待下代际复验 |
| 四维时间正规化（T1 五臂） | **立项关闭，monitor_only 归档** | D1 前置步裁决：跨日分量 h8 后验优于日内（cs_delta CD +0.0350 vs SD −0.0005、res_short +0.0169 vs −0.0064、rank_p3 +0.0175 vs −0.0037）——「隔夜=噪声」被反杀，热榜语境隔夜跳空=注意力延续信号；与 lifecycle 跨日假动量（G1 依据）方向相反=同原料不同维消费分化，本轮最重要结构发现 |

- **结构读数沉淀**（D1，`data/reports/voting-signals-d1.json` 本地）：synergy S 仅 127 帧（0.08%）且 127/127 由 cs 正票撑进（「cs 守门维」实证）；vp E 档 19.9%（远超预估）；res D∧buy 6.6%（strength 倒挂实体）；双动量一致率 91.8%/82.4%；fallback 覆盖 36.5%；新入榜 P(确认门)=19.3%。
- **golden**：快照重录一次（configRepr 新增 4 字段文本，场景输出零漂移）；全量 644 绿。
- **回退**：全部新参数默认即现行为；T5a 为代码删除（git 回退唯一路径）。

## 20. 四信号结构重设计 W0（2026-10-07，计划 ranktrend-vote-structure-redesign-plan.md 两案：一阻一达线）

> 执行线报告：W0-1 被 Q1 并行线活进程阻断（计划前提「与 Q1 唯一交叠=无」有误，见下）；W0-2 判定线达标。产物 `data/reports/voting-signals-amount-leverage-w02.json`（本地不入库，全窗 04-15~10-07，1071 帧/24.57 万股帧，255s）。

| 案 | 状态 | 判定依据 |
|---|---|---|
| W0-1 删 pm/dv 死票位 | **推迟（Q1 收官后补做）** | 实测发现 Q1 合同机制二 C-a 正是 dv 投票权重接线（`tierSynergyDivergenceVote` 0.25/0.5/0.75 三臂，`evaluate_lifecycle_q1_trials.py`），trial 活进程中（checkpoint partial，19:25 起跑）且后续 C-a×C-c 组合臂仍需消费该字段；合同 C-8 明文要求该配置面保留作回退。dv 摘除=毁三预登记臂；pm 摘除虽零行为但 trial 中途不动引擎文件（config.py/volume_price.py 均在 trial 导入图）。计划文档「唯一交叠=无」前提已在该文档协调表勘误。 |
| W0-2 amount 杠杆重估 | **达立项线→L2 预登记候选（待用户裁决）** | 预声明线（冻结于跑数前）：可算率<20% 归档 / ≥20% 且分层差≥0.02 立项。实测：可算率 decision 72.4%（全窗 81.4%；7 月仅 23.8%=补采月数据缺口，4 月 64.4%=序列起点无基准，5/6/8/9 月 93-96%）——旧归档前提 6.12% 已被回填推翻；h8 分层（excess_mean，decision 窗）：放量(≥1.5) −0.0127 / 中间带 +0.0043 / 缩量(≤0.5) +0.0146，三对差 |max|=0.0273（high−low）≥0.02；**四窗方向全部一致单调（放量最差、缩量最好）**，oos1/oos2 端-中差达 0.036-0.0385 更强。方向语义=放量资金帧排名 8 帧后验走弱（退潮保护向），与 vp E 短路 −32% wrxpf 保护同族。 |

- **读数细节**：ar 分布 decision p10-p90 = 0.353/0.853/1.179/1.372/1.627（中位 1.18≈量纲健康）；amount_score≠0 帧占比（可算帧内）21.7-28.3%；`vp_tier_drift`=0（二次调用逐帧自证 tier 不消费 score，喂 tier 立项方向的前提成立）；s_gate PASS；引擎自证 rank/synergy 622/70（rate 0.899）与归档 D1 报告**逐位相同**=既有口径差非本次引入（vp/cs/res 692/0 满分）——**遗留观察项：D1 框架 rank 复刻在 9 月下旬帧 10.1% mismatch 根因未查，W1-2 若扩展 D1 框架须先补此洞**。分层差严格口径注记：decision 窗端-中差（high−mid −0.0169 / low−mid +0.0103）单看均 <0.02，过线靠 high−low 0.0273；oos1/oos2 端-中差独立过线；判定按预声明操作口径（三对取 |max|）执行。
- **立项方向预注**（L2 合同起草时展开）：amount 进档位判定=喂 tier（gate/分层形态），非调 score（amount_score 只进 score 的根因 §4.2 量价①）；与 W2-2 价格确认门、W1-1 D∧buy 修复无原料冲突，语料包 v2 组装时并入本读数。
- **回退**：零行为零参数改动，无需回退；`diagnose_voting_signals_exposure.py` 扩展为纯增列（主 vp 调用不传 amount_ratio，存量读数零漂移）。

## 21. W1 批（2026-10-07 晚：W1-2 rank 稀疏诊断达立项线；W1-1 合同备料待审定；rank 自证根因修复）

> 承 §20（W0）。产物 `data/reports/voting-signals-w12-rank-sparse.json`（本地，951→1071 帧全窗口径同 D1）。

| 项 | 状态 | 读数/依据 |
|---|---|---|
| rank 自证 70 假 mismatch | **根因修复（零读数漂移）** | 根因=`attention_rank_lookup` 过滤 avgRankNum≤0，07-07 补采两帧各 35 只股票 rank 有值但 avgRankNum 缺失→引擎正确不产信号，诊断逐股幻影链（ln=0 fallback 驱动）出假 C 档与之比对；R1 检查帧恰无此类股票故曾显示满分。修复=自证比对跳过无引擎信号股票（skipped_rank_less/alarm 双计数器 fail-visible）+len_buckets 增 rank_less 计数；冻结 population 不变（幻影仍进存量列，幅度 <1% 稀释）。修复后五维自证 622/0 全 1.0 |
| W1-2 rank 稀疏票诊断 | **达立项线→rank 阈值面 L2 预登记候选（待用户裁决）** | 预声明线（冻结于跑数前）：差一票或近阈值占 C 档 >10% 立项。实测（decision 窗）：**buy_count=1「差一票」占 C 档 31.9%**（midgap/oos1/oos2=33.0/32.8/32.4% 四窗稳定）；分值空间近阈值(<0.02)仅 0.5%——**缺的是共识票不是分数**（buy_count 分布 0/1/2=52.9/31.9/14.8%，agreement 挡下 vs 分数挡下）；缺位分量=direction 55%/acceleration 38%（动量族），macd/ma 极少；C 档内 buy_count=2（共识够分数不够）15.3%；ln=1 新入榜 100% C 档（结构性无 rank 信号）；C 档 res insufficient 层 24.3%。方向=立项「共识面/阈值面」L2（buyScoreThreshold 0.18 曾 OOS 反向旧账，须新代际重验） |
| W1-1 res D∧buy 倒挂票 | **合同备料完成待审定** | `vote-w11-res-dbuy-preregistration.md`（判定线冻结于跑数前）：单参三态 `tierSynergyResonanceDbuyMode` off/cap_b/abstain，两剂量臂+baseline=3 replay+2 Track 1；机制勘误=**候选 c 与 b 数学等价**（D∧buy⟺reversal_penalty≥0.6 驱动，D∧sell 为独立路径不动）并案；票值算术核实 +0.75>B +0.525（强度表 [1.2,1.0,0.7,0.5,1.0,1.0]×res 权重 0.75）；**接线须待 Q1 线收官**（config.py 缠绕+trial 活进程） |

- **判定线操作口径注记**：W1-2「差一票」以 count 空间（buy_count==1）为主读数、score 空间（距阈<0.02）同列披露；主 population=ln≥2（ln=0 幻影不入列、ln=1 单列），C 档分母含 res insufficient 层（fallback 分层单列）。
- **回退**：零行为零参数改动；自证修正为比对面修复（git 回退唯一路径）。

## 22. 生命周期 Q1 价量证据喂入 trial（2026-10-07 深夜：全臂 FAIL 阴性登记，零默认改动）

> 合同 `lifecycle-q1-preregistration.md` v1.1（Opus 审定 R1-R9 落实，判定线冻结于跑数前）；用户令「按审定回执修正后开跑」。产物 `data/reports/lifecycle-q1-trials.json`（98MB 本地不入库，4674s，15 臂×4 窗 replay+Track1；逐臂 checkpoint 机制=首轮算完在最终序列化一步崩掉 Track1 全失的教训）。接线：`lifecycleGapPriceVolumeMode`（off/direction_gate，默认 off）+ `lifecycleGapPriceVolumeProxyP/VrGate` + dv `gap_step` temporalGap 防御 + `analyze_cycle` 价量等长入参 + annotations 独立标注通道 + live/replay 双链接线；全部默认零行为（golden 重录 diff 审查：configRepr 6+annotations 691+priceRankDivergence 528 全部「任意态→unknown」零反向，决策链零漂移；后端 3285/前端 1175 全绿）。

| 机制 | 臂 | 判定 | 关键读数（decision/oos1/oos2 saEx 相对基线） |
|---|---|---|---|
| C-a dv 权重 | 0.25/0.5/0.75 | **全 FAIL**（C-4.1 无害线+提交线、C-4.2 双 FAIL） | −0.0095/−0.0202/−0.0301（oos1 +0.0228/+0.0271/+0.0124 虚高）；Track1 wrxpf −0.10~−0.12、maxDD 恶化 4.9~8.0pp、笔数 172→123-140 |
| C-c direction_gate | vrGate{1.0,1.5,2.0}×P{3,5,8} | **无害线 PASS、提交线 FAIL=零效应**（C-4.5 阴性登记） | vr15 最优 mean +0.00136 < +0.002；Track1 wrxpf −0.0028 容差内+maxDD 22.31%→21.73% 微改善+笔数不变 |

- **结构性发现一（P 剂量轴退化）**：P∈{3,5,8} 九臂塌缩三有效臂，同 vrGate 三档读数逐位相同——现阈值结构下 ±P 只经符号起作用：recovery/ignition 需 accel≥−1.2 而 proxy 步 accel 恒 NaN（合同红线②不伪造多帧证据的结构性代价），+P 永远点不着点火路径；velocity>18 高阈值 P 全够不着（合同 P-vs-18 注记兑现）。**若未来重开剂量面，须先解 accel 置缺与点火判据的相容问题**。
- **结构性发现二（C-a 扩档拉动）**：dv 权重臂 S/A 帧数 1229→2079/2812/3683（+68%/+129%/+200%）单调膨胀而 excess 反向——扩档非判别改善，C-4.1 档位计数披露义务正中要害；dv 效度（D3 单帧分辨力显著）≠投票增益（进 synergy 后稀释+扩容负效应）。**dv 维保持观察位（权重 0.0），「效度验证→给权重」路径证伪**。
- **C-4.3 侵蚀监控**：C-c veto 相对回升 +0.46%~+0.49%（<< 3.4% 交裁线）；翻转分列（修正 flip 键反解后）：added 352-380 步主落 drop 桶（242-261=68%，价跌步 −P 判 reversal=机制设计方向）、released 305-332 步 85% 在人群外=normalize 状态机传导效应（proxy 改 raw 后后续帧级联，合同预期内）；C-a 臂 veto/翻转零变化（dv 不触 veto，读数自洽）。
- **C-4.4 分离度**：注入人群（跨日步∧|Δpct|≥10，19,645 步）价升/价跌 fwd 分离 +0.5378（数据层常量，对全部臂同值；与 D3 桶内读数 +2.31/+2.04 不可直比=混合人群）。
- **runner 两 verdict 计算 bug 跑后修正**（读数零影响）：maxDD 负数域直比（把回撤改善判成恶化）+flip 分列键反解缺失（全落 unclassified）；判定表以修正版为准。
- **回退**：`lifecycleGapPriceVolumeMode="off"` + `tierSynergyDivergenceVote=0.0`（=现默认）双开关即回基线；无数据删除面；基线锚 decision 0.14503 与 G1 §18 新锚 0.1450 一致（a0 自证）。
- **落默认裁决**：按 C-4.5 全 FAIL=不提交、零默认改动；**Q1 主线至此闭环**（原料→诊断→预登记→审定→trial→阴性登记）。后续可选：P5 双轴重设计（在「+P 点不着火」结构事实上重开）、W0-1 dv/pm 死票位摘除（现在无 trial 冲突，但 dv 摘除与本轮「保持观察位」结论一致须用户裁决）。

## 23. 三裁决执行批（2026-10-07 深夜：Q1 闭环后用户三立项的 L2 执行——amount 合同备料完成、rank 前置诊断阴性否决）

> 承 §20-§22。用户裁决原文「Q1已闭环，请执行以上3项」=①amount 喂 tier L2 立项 ②rank 阈值面 L2 立项 ③W1-1 开跑。开跑授权覆盖「接线→专项测试→trial→判定→登记→提交」，落默认仍须用户裁决。③W1-1 接线因 P5 并行线活进程（`lifecycle-p5-preregistration.md`，同晚用户授权，接线+golden 已完成、trial 跑完 baseline 臂后进程中断悬置中）暂缓——config.py 为 P5 未提交改动文件，Q1/W0-1 先例同款处置（trial/半成品期不动引擎文件），P5 收官后开跑。

| 项 | 状态 | 读数/依据 |
|---|---|---|
| ① amount 喂 tier L2 | **预登记合同备料完成（并入语料包 v2 待审定）** | `vote-l2-vp-amount-tier-preregistration.md`（判定线冻结于跑数前）：单参三态 `volumePriceAmountTierMode` off/high_demote/both，两剂量臂+baseline=3 replay+2 Track 1；门限复用现有 `amountRatioHigh(1.5)/amountRatioLow(0.5)`（W0-2 分层读数即按此两档测得，零新阈值参数）；主臂=放量奖励撤回（ar≥1.5 ∧ rise_volume → A→B/B→C，收缩面保护向），对照臂=双向门（+缩量升档，扩张面先验不利=Q1 C-a 扩档拉动教训，阴性也归档）；E 短路/缩量涨停 reasons 优先级不动；市况分桶列高危项（强情绪期放量降档可能错杀）。接线面核实：`_volume_price_tier` 唯一调用点（volume_price.py:243）、amount_ratio 生产链已通（runtime:1462→observation.amountRatio→assemble_observation），零新序列传递 |
| ② rank 共识面/阈值面 L2 | **前置诊断阴性 → 立项否决归档（行为步不起草）** | 按 W0-2 先例先跑零成本前置诊断补剂量面证据洞（「差一票占比高≠放进来有增益」）。预声明线（冻结于跑数前）：dbuy1−c_rest excess_mean ≥ +0.01 且 ≥3 窗同向 → 立项；否则归档。实测（`data/reports/voting-signals-w12r-consensus-h8.json`，1071 帧，h8 分位桶校正）：**四窗 4/4 反向**——decision −0.0219 / midgap −0.0152 / oos1 −0.0214 / oos2 −0.0044，excess_acc 同向（dbuy1 −0.0159 vs c_rest +0.0120）——差一票帧是 h8 后验更差人群，共识门槛 ≥2 票挡下=正确设计；dbuy2p（共识够分数不够）同样负向。判定=坚决不过线且方向反转，登记 `vote-l2-rank-consensus-preregistration.md`（含覆盖面：阴性覆盖「放行差一票帧」前提的全部形态+分数轴松动；不覆盖反向命题「差一票作负向信号」（新票位，登记语料观察线索待独立预登记）+原料面重设计+新代际复验）。结构解释与 §10 五权重实证互证：0.90 权重压交叉事件/动量族 0.10 的贬权设计与 h8 后验一致 |
| ③ W1-1 res D∧buy | **暂缓（P5 并行线半成品期，非取消）** | 接线面/合同不变（`vote-w11-res-dbuy-preregistration.md`）；用户已给开跑授权（含「外部模型审定跳过=用户明示简化」已在合同 §五 登记）；P5 收官（提交）后立即开跑：接线→专项测试→golden 重录→harness（`evaluate_vote_w11_res_dbuy.py`）→trial→判定→登记→提交，W1-1 提交后顺路补做 W0-1（删 pm/dv 死票位；C-a 三臂全灭后 dv 维持观察位，Q1 §22 已证无回退价值） |

- **诊断脚本扩展**：`diagnose_voting_signals_exposure.py` W1-2.1 增补（三 h8 cell：w12r|dbuy1/dbuy2p/c_rest+文件头预声明线）——operations 纯增列，存量读数零漂移，与引擎/试线零接触。
- **并行线状态**：P5（lifecycle allow 分位带门，6 replay+1 baseline）21:26 起 trial 进程中断（baseline 臂已完成：saEx=0.14503 与 G1 锚一致+track1 完成；A3-B2 五剂量臂未跑）——其会话恢复续跑或用户处置前，本线不动 config.py/runtime.py/lifecycle.py/golden 快照四共享面。
- **回退**：零行为零参数改动（诊断增列+文档），无需回退。

## 24. 语料包 v2 审定轮 + W2 前置判定批（2026-10-08：amount 合同 v1.1、W2-2 立项备料、W2-1 挂起、rank 否决维持）

> 审定输出归档 `voting-signals-corpus-v2-review.md`（用户亲自投喂执行，档案静态比对零硬幻觉）；语料 §14 战报。本批全零行为零默认改动（前置诊断+合同+登记），开跑类动作均待用户裁决。

| 项 | 状态 | 读数/依据 |
|---|---|---|
| amount L2 合同 | **v1.1（审定有条件通过，五项全落实）** | A1 接线依赖声明（待 P5 收官解锁）/A2 oos2 Track1 披露（基线 76 笔 0.1660 在档）/A5 retreat 桶 n<50 降级三项必改+A3 oos1 −5% 止损带+A4 配对披露/按月可算率/b 臂方向标注两项建议；待用户裁决开跑 |
| rank 共识面否决 | **审定维持**；反向命题保持观察线索（不可双重消费+三重冗余面未测+oos2 衰减 5 倍） | 未来立项补强条件已登记入否决登记文档 |
| W2-2 价格确认门 | **前置四窗 4/4 强同向过线 → 合同备料完成** | rank buy∧S/A 帧 change<0 组 h8 −0.0665 vs ≥0 组 +0.0006（差 −0.0671，线值 6-10 倍；midgap/oos1/oos2=−0.110/−0.075/−0.098）；res 侧同构全负；触发面 20.8%；合同 `vote-w22-price-gate-preregistration.md`（tierConfirmPriceGateMode off/rank/rank_res，θ=0 单帧降档门，审定判定卡骨架全款）；冗余面（dv/pm 共线）=trial 前置补跑条款 |
| W2-1 隔夜延续门 | **挂起（市况先验过、靶人群分解无靶）** | 市况先验：四桶 CD−SDa 全正（strong +0.0355/retreat +0.0083，retreat 股帧 n=356-1459>50）挂起条款不触发；靶分解：res 侧断裂 16,050 帧 brk−cont≈0（四窗零散）+rank 侧断裂四窗合计仅 43 帧微样本反向——「跨日 cs_delta 有信息」（T1）≠「跨日帧内断裂符号有判别力」（实测零），前置省掉注定零效应的 trial；不覆盖姿势登记（幅度分位定义/交互/反向形态/新代际） |

- **执行教训**：诊断扩展的 h8 cell 代码必须置于 `h8s=h8_of(fi,code)` 赋值之后——首跑 W2-2 列曾置于赋值前，Python 跨帧残留值静默错位一格（非崩溃），发现后废跑重计（废数据已删）；多案前置尽量同脚本一次 replay 出数。
- **通用判定卡条款沉淀**：触发率披露（<2%/=0 → 零效应不提交）+retreat 桶 n<50 股帧降级只披露（帧数≠股帧样本数口径澄清）——后续门类合同全款继承。
- **回退**：零行为零参数改动，无需回退；`voting-signals-w2x-gates.json` 本地不入库。

## 25. 生命周期 P5 双轴重设计·allow 腿分位带门 trial（2026-10-08：全臂 FAIL 阴性登记，零默认改动；原编 §23 与三裁决执行批撞号，2026-10-08 勘误为 §25）

> 合同 `lifecycle-p5-preregistration.md`（判定线冻结于跑数前；用户令「请执行 P5 双轴重设计」）。前置诊断
> `diagnose_lifecycle_p5_dual_axis.py`（D1 stage×pct MI=0.2894 vs shuffle 0.0002=「stage≈分位带函数」定量实锤；
> D4 allow 帧 fwd1=−1.47 比 caution +0.40 差=机制立项依据）。产物 `data/reports/lifecycle-p5-trials.json`
> （6 臂 1950s+Track1；checkpoint 逐臂落盘）。接线：`lifecycleAllowBandGateMode`（off/pct_band/pct_velocity）+
> 两门限字段 + `apply_allow_band_gate`（`_build_signal` 内 analyze_cycle_with_risk 之后单点改写，replay/live
> 两链天然同口径）——全部默认 off 零行为（golden 重录仅 configRepr 6 处文本，场景输出零漂移；后端 3297 绿）。

| 臂 | 结构守卫 | 信号面判定 | Track1（decision 窗） |
|---|---|---|---|
| a3_pct70（保守 1D） | PASS（veto/exit_watch 逐位不变、改写 9687=allow 降幅） | **FAIL**：saEx rel −0.0167/+0.0053/−0.0169（两窗负且一窗<−0.005） | wrxpf **+0.0111**、dd 22.31%→21.36%、笔数 172→149 |
| a1_pct60（中间 1D） | PASS（改写 13537） | FAIL：−0.0015/+0.0162/−0.0154 混合 | wrxpf −0.0204 FAIL、dd 微善、笔数 143 |
| a2_pct50（激进 1D） | PASS（改写 17123） | FAIL：三窗 saEx=None（A 档 17732→609 塌缩样本不足） | wrxpf −0.0823 FAIL、笔数 132 |
| b1_f5_s7 / b2_f5_s6（2D 门） | PASS | FAIL：同上 None | wrxpf −0.090/−0.082 FAIL；两臂成交集逐指标相同=差异帧（低动量中分位）execution 零入选（对账非串臂） |

- **判定**：C-3.5 全 FAIL=阴性登记，零默认改动（单开关 `lifecycleAllowBandGateMode="off"` 即现默认，本来也没动）。
- **核心结构发现（比结论值钱）**：D4 诊断的「allow 帧比 caution 差」在 saEx（分位桶 excess 校正）口径下
  **反向**——高分位 allow 帧是正 excess 贡献者，其 fwd1 负值几乎全由均值回归基线贡献（合同 C-10② 预警
  兑现：fwd 原始读数≠excess 校正后读数，raw fwd 诊断不能单独作降档立项依据）。**P5 的「非单调离散门」
  论证在 excess 口径被证伪：门的作用轴（分位带）上，放行帧的相对表现并不差。**
- **对照发现（如实登记非准入）**：a3 保守门交易面改善（wrxpf +0.0111/dd −0.95pp）与信号面恶化并存——
  与「环境门价值主体在负向过滤与出场、saEx 部分测不到」已知结构互为镜像（降档价值在 Track1 不在标签
  纯度）。**不构成落默认依据**（C-3.5 要求双线同过）；若未来重开，唯一合法路径=新合同以 Track1 为主
  判定面重新预登记（跑后调线=违规）。
- **双轴拆分本体否证**：D4 action×stage 交叉近完全映射（action×pct MI 0.2465≈stage×pct 0.2894）——
  gate-redesign-proposal §4 的「path×action 拆轴」在现实现下无信息增量，action 轴独立发布（gateAction
  字段）永久搁置有据。
- **runner 工程**：checkpoint 逐臂落盘沿用 Q1 机制（首启被环境中断后重启零状态损失降为可接受）；诊断
  MI 用 shuffle 基线（seed 20261007）；2D 门读数塌缩暴露 saEx 对 A 档样本量的敏感性（<2000 帧→None），
  后续剂量设计须预先核对最小样本量。
- **回退**：零行为零默认改动；golden 重录仅 configRepr 文本。基线锚自证（0.1450/0.0983/0.1057）与 G1 §18/Q1 §22 一致。

## 26. W1-1 共振 D∧buy 倒挂票 trial 收官（2026-10-08：全臂 FAIL_C1 阴性登记，零默认改动；Track1 双正对照发现）

> 合同 `vote-w11-res-dbuy-preregistration.md`（判定线冻结于跑数前；外部审定=用户明示简化已登记 §五）。产物 `data/reports/vote-w11-res-dbuy-trials.json`（本地不入库；3 臂×3 窗+2 Track1，逐臂 checkpoint）+迁移矩阵补丁 `vote-w11-migration-patch.json`（harness 取键 bug 修复后补跑披露面）。

| 臂 | rel（decision/oos1/oos2） | 判定 | Track1（decision 窗） |
|---|---|---|---|
| cap_b（D∧buy 封顶 B +0.525） | −0.58% / +1.98% / +0.49% | **FAIL_C1**（C2/C3 过） | wrxpf 0.4358 vs 0.4140=**+5.27%**；maxDD −0.2202 vs −0.2231 改善；174 vs 172 笔 |
| abstain（D∧buy 弃权票 0） | −0.10% / +0.15% / +1.05% | **FAIL_C1**（C2/C3 过） | wrxpf +4.28%；maxDD −0.2213 改善；174 笔 |

- **B0 自证三窗逐位 PASS**（0.14503/0.09825/0.11716）；护栏满值：resS 14,370（=基线）、synS 127、**res tier 分布逐位一致**（res 维不动实现守卫兑现）；retreat 桶 saEx 逐位相同 0.2197（改判不触 retreat 桶 S/A 面），strong 桶信号面降（0.1189/0.1167 vs 0.1234）——两臂同向非反号，不触挂起。
- **S 档守门结构完好（披露义务核心项）**：两臂 S→S 全保 127/127；改判面 cap_b 606 帧（6.1%：B→C 554/A→B 15/C→D 37）、abstain 4,369 帧（44%：C→D 2,973/B→C 1,373 等）——剂量递增符合机制预期。
- **判定（合同 W1-1.3 冻结）**：全臂 C1 不过 → 阴性登记不提交，零默认改动（`tierSynergyResonanceDbuyMode="off"` 单开关即现默认，本来未动）。倒挂票语义资产保留在展示层（_resonance_tier 不变）。
- **对照发现（如实登记非准入）**：信号面 C1 不过而 **Track1 双臂正**（wrxpf +5.27%/+4.28%+maxDD 双改善）——D∧buy 倒挂票修正的收益在**交易面（入场质量/回撤）不在信号面（excess 判别）**，与 P5 a3 对照发现（Track1 +0.0111 与信号面恶化并存）跨线互证=「修正票值类机制的价值主要在负向过滤成交面」的第二个独立证据。**重开唯一合法路径=新合同以 Track1 为主判定面重新预登记**（P5 台账同款处置）。
- **接线与测试**：`tierSynergyResonanceDbuyMode`（off/cap_b/abstain，默认 off 零行为）+ `_synergy_tier` res 投票点分支（cap_b 读强度表 min(D,B)、长度≠6 断言报错不走 fallback；abstain 票 0；D∧sell 真反向/非 D 档/其他维零触碰）；专项 11 过（行为等价断言法：cap_b≡B∧buy 原路径、abstain≡res 不计票）；golden 重录 diff 干净（configRepr 6 处 +1 字段文本，场景输出零漂移）；ranktrend 667 全绿；Redis analyze 键清+8000 已重启。
- **harness 教训（登记防再犯）**：per_signal 存取键错位（`temp_per.get("decision")` 应按臂名取）——判定面数据完好，披露面（迁移矩阵）首轮为空；修复后 3×decision 窗 replay 补跑补全。harness 首跑前只验证了编译+import，数据流键位未经验证——**披露义务类代码路径应在 smoke 臂上先验一遍**。
- **回退**：单开关 off 即基线（未落默认，无回退需求）。

## 27. W0-1 删 pm/dv 死票位（2026-10-08 顺路补做：架构诚实七维账面→五维实态，零行为验证逐位一致）

> 计划 W0-1 案（两度被并行线阻断后解锁：Q1 收官解 dv 半边合理性〔C-a 三臂全 FAIL=「效度验证→给权重」路径证伪，dv 维持观察位无回退价值〕→P5 收官解引擎文件锁→W1-1 提交后顺路执行，handoff 授权链完整）。Q1 合同 C-8「配置面保留作回退」已随 Q1 收官失效。

- **摘除面**：`_synergy_tier` 签名收窄（pm_tier/dv_tier 两参）+pm/dv 两加性块+`assemble_observation` 传参链；config 删 `tierSynergyPriceMomentumVote`/`tierSynergyDivergenceVote` 两字段+_validate 负值校验环两项。**观察因子本体不动**（price_momentum/price_rank_divergence 照常算、照常进 observation 展示与研究消费；dv 四态语义资产 rank_lead/price_lead_warn 保留在观察层）。
- **归档 runner 守卫（fail-visible）**：`evaluate_lifecycle_q1_trials.py` 模块级断言——ca_* 三臂消费的 `tierSynergyDivergenceVote` 已摘除，`from_patch` 对未知键静默跳过=臂会静默塌缩成 baseline 假读数（G4 断线先例同族风险），字段若重现即 raise（重开 dv 面唯一路径=新合同重新预登记，不得复用归档 runner）。
- **零行为验收（全过）**：三窗 saEx **逐位一致**（0.14502883031301483/0.09825280898876404/0.11716262626262626）+resS/synS 逐位（14370/2018/1608、127/29/24）+Track 1 逐位（172 笔/wrxpf 0.414/dd −0.2231）=票权本就 0 的架构诚实化；golden 重录 diff 干净（configRepr 6 处 −2 字段文本、其余逐位一致，场景输出零漂移）；ranktrend 667 全绿（test_synergy_vote 断言更新：字段不存在性+签名收窄 co_varnames 断言）；Redis 清键+8000 已重启。
- **收益**：架构诚实（消除「价格信息已参与投票」误读）；**回退=git revert 唯一路径**（字段删除非开关）。

## 28. L2 amount 喂量价档位 trial 收官（2026-10-08：双臂 FAIL 阴性登记，零默认改动；C1 首过但 oos 崩盘）

> 合同 `vote-l2-vp-amount-tier-preregistration.md` v1.1（双模型审定有条件通过，用户开跑令）。接线：
> `volumePriceAmountTierMode`（off/high_demote/both 默认 off）+ `_volume_price_tier` 门分支（E/缩量涨停
> 优先级不动、fail-visible 标注、score 链零改动）；专项 15 过+golden 重录仅 configRepr 6 处文本+后端
> 3323 过。trial（951 帧口径，B0 锚三窗逐位自证 PASS；runner `evaluate_vote_l2_vp_amount.py` checkpoint
> 逐臂落盘）。

| 臂 | decision | oos1 | oos2 | Track1（decision） | 判定 |
|---|---|---|---|---|---|
| a_high_demote（改判 2932 帧/2.24%） | **+3.52% C1 首过** | **−23.7% 触 A3 止损带** | −4.4% C2 反向 | wrxpf −8.2%+dd 恶化 | FAIL |
| b_both（改判 6663 帧/5.08%；升档腿独占 3731） | +4.16% | **−25.7% 触 A3 止损带** | −4.8% | wrxpf −9.6%+dd 恶化 | FAIL |

- **判定（L2-3）**：全 FAIL=阴性登记不提交，零默认改动（off=现默认，开关保留诊断对照面）。
- **核心发现**：①**C1 首次过线**（全研究轮第一个 decision saEx ≥+3% 臂——W0-2 立项读数在判定口径
  decision 面复现），但 oos 全面崩（oos1 −23.7%/−25.7%、oos2 −4.4%/−4.8%）=决策窗改善零外推；
  ②A3 止损带（v1.1 审定增补）精确履职——没有它 C1 单线误判过线，**判定卡多窗结构（C1+C2+A3）是
  in-sample 改善与可部署之间的唯一防线，后续合同默认保留**；③vp 迁移符合预期方向（A+B 面↓C 面↑
  双级联、b 臂 B +3731 升档腿独立）但方向对不等于外推成立；④护栏过线但 synS 127→98/103（S 档
  −20% 如实登记）；⑤市况分桶 retreat 桶逐位相同（改判不触 retreat）、strong 微降——oos1 崩盘机制
  未定位（分桶未覆盖 oos 窗），与 C10①「强情绪期错杀」相容非证实，留观察线索。
- **runner 教训**：signal 顶层 regime 是字符串（runtime:1559）非 dict，市况 filter 首跑崩（baseline
  轮白跑 ~4 分钟）——披露类取数先 smoke 臂验证（W1-1 教训第二例）。
- **回退**：`volumePriceAmountTierMode="off"` 单开关即现默认；基线锚自证与 §18/§22/§26 一致
  （0.14503/0.09825/0.11716）。
