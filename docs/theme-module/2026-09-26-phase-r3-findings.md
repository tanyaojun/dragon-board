# Phase R3 实证报告：轮动补涨策略变体对照回测

- 日期：2026-09-26（周六，非交易时段运行）
- 数据窗：2026-07-06 ~ 09-24（54 个 half_hour 交易日，dragonboard_live）
- 代码版本：main `9fc589f1`（变体接线 + runner）
- 报告产物：`quant-board/data/reports/theme-r3-variants.json`（gitignore，不提交）
- **样本量声明**：54 天、每变体 63-74 笔交易的探索性对照，非正式判定；无统计显著性检验，结论强度为方向性证据。
- 前置裁决：轮动信号消费**引擎 mainline 口径**（rotationSummary.mainLines）；regime 消费引擎权威口径（rotationState + Top1 稳定性）；MainlineScore 判定链降级为诊断（§5.5 第四轮裁决，回写 cdbb9f21）。

## 0. 执行摘要

1. **"主线不明环境下轮动补涨占优"假设在本窗总体被否定**：纯 SG 驱动补涨（chase）总收益 **-8.02%**、最大回撤 -13.03%、profitFactor 0.72，全面差于基线 theme_rotation（+1.71% / -5.62% / 1.11）。
2. **状态门控混合（hybrid）小幅占优**：+3.32%、回撤 -7.68%、PF 1.16——门控在主线日走主线确认、无主线日走 SG 补涨的结构带来了正贡献，但幅度未达定版门槛（54 天探索窗）。
3. **亏损集中在 cooling 相位与 headStable=True（Top1 霸榜）日**：chase 在头部稳定日均笔 -3.38%、胜率 15%——Top1 霸榜时追 SG 触发的次级题材是被打的主要场景；hybrid 门控把该组亏损缓解到 -1.71%。**门控的价值实证支持**。
4. **Top1 rotationState=emerging（新主线萌发）是补涨唯一有效子集**：三变体 emerging 组均正收益（+2.2%~+3.4%/笔、胜率 0.80-0.86），但 n=5-7 不足以定版。
5. SG1 RRG 象限迁移在本窗**结构性不可用**（0 触发）：daily change 序列 7 月仅覆盖 15 天，全窗完整性检查按设计失败（fail-visible 打标 248 题材）；SG2（33 触发日）/SG3（36 触发日）正常工作。

## 1. 三变体对照（同一窗、同一 seed=20260430、默认交易参数）

| 变体 | 总收益 | 最大回撤 | 胜率 | 交易数 | profitFactor | runId |
|---|---|---|---|---|---|---|
| theme_rotation（基线，不变） | **+1.71%** | **-5.62%** | 0.4603 | 63 | 1.1139 | 见报告 JSON |
| theme_rotation_chase（SG 驱动补涨） | -8.02% | -13.03% | 0.3944 | 71 | 0.7173 | 同上 |
| theme_state_hybrid（状态门控） | +3.32% | -7.68% | 0.4595 | 74 | **1.1636** | 同上 |

- chase 进场规则与基线完全相同（tier A/B + regime≠weak），差异只在候选池构造（SG 触发才给 B_IGNITION、补涨语义不给 A_MAIN）——亏损可归因于**进场时机选择**而非交易规则差异。
- hybrid 门控日分布：引擎主线日 8 天（走主线确认臂）、引擎判定无主线日 31 天（走 SG 补涨臂）、mainLines 键缺失 15 天（补涨臂 + missing 打标）。

## 2. 分层评估（trades 按 entry 日市场状态分组）

### 2.1 market_phase（half_hour 15:00 帧真值）

| 相位 | 基线 n/avg | chase n/avg | hybrid n/avg |
|---|---|---|---|
| cooling | 48 / -0.75% | 51 / **-1.51%** | 53 / -1.33% |
| chaos | 12 / +1.39% | 12 / -0.93% | 13 / **+1.45%** |
| rising | 1 / +1.10% | 3 / +1.96% | 3 / +1.69% |
| climax | 2 / +4.41% | 5 / +2.15% | 5 / +2.15% |

- 三变体绝大多数交易落在 cooling 相位（窗内弱势环境主导）；
- **cooling 是 chase 的亏损放大器**（-1.51% vs 基线 -0.75%）；hybrid 在 chaos/rising 相位与基线同向为正、cooling 段亏损小于 chase——门控没有能力在退潮期把补涨做成正收益，只是少亏。

### 2.2 Top1 rotationState（引擎权威口径）与 headStable（Top1 连续保持 ≥3 天）

| 分组 | 基线 n/avg | chase n/avg | hybrid n/avg |
|---|---|---|---|
| emerging | 7 / **+3.40%**（胜率 0.86） | 5 / **+2.15%**（0.80） | 5 / **+2.15%**（0.80） |
| inflow | 43 / -0.49% | 53 / -1.16% | 58 / -0.51% |
| mainline | 9 / -0.91% | 11 / -0.06% | 8 / +0.11% |
| headStable=False | 46 / +0.11% | 58 / -0.47% | 60 / -0.20% |
| headStable=True | 17 / -0.84% | 13 / **-3.38%**（胜率 0.15） | 14 / -1.71% |

- **emerging（新主线萌发）态是轮动补涨假设唯一被数据支持的场景**：新 Top1 出现后的萌发期进场三变体全部正收益。样本不足，列为下一批唯一候选验证点；
- **headStable=True（AI硬件式霸榜日）追补涨被系统性惩罚**：chase 该组均笔 -3.38%、胜率 0.15；hybrid 门控缓解一半。与 §2.1 cooling 结论同构——**头部稳定 + 退潮期 = 补涨策略最差环境**；
- 与既有"市场状态依赖"四次复现结论同构：收益由市场状态主导，变体差异是二阶项。

## 3. SG 触发分布

| 信号 | 触发日数 | 高频题材（hits） |
|---|---|---|
| SG1 RRG 象限迁移 | **0**（248 题材 insufficient） | — |
| SG2 rotationState 切换 | 33 | SRAM存储概念/光伏辅材/减肥药概念（各 11） |
| SG3 资金转正初现 | 36 | 800V快充（13）/军工信息化（12）/可控核聚变（12） |

- **SG1 结构性不可用的口径说明**：SG1 依赖 daily change 全窗完整序列，而 7 月 daily 类型仅覆盖 15 天（R2 已固化的事实）；half_hour 窗 54 天为轴时完整性检查按设计失败。改进方向（后续批）：SG1 改用 half_hour 收盘槽（15:30/15:00）change 序列替代 daily 序列——本窗按现状如实报告 0 触发，不影响 SG2/SG3 驱动的 chase 臂结论成立（chase 在 SG2/SG3 驱动下已显著跑输）。

## 4. 结论与下一步

1. **R3 假设裁决（本窗证据内）**："主线不明环境下轮动补涨占优"**不成立**；"主线确认与轮动补涨按状态门控切换"以小幅优势胜过纯主线确认，但幅度不足定版；
2. **门控结构保留、参数不定版**：hybrid 是三变体中唯一 PF>1.13 且收益高于基线的变体，但 54 天样本不足以落默认——按 `ranktrend-signal-research` 纪律，一次一候选：**hybrid 门控列为观察池候选**（绑定锚代际：本轮 runId 见 JSON；触发条件：后续月度复验）；
3. **emerging 态补涨**：列为独立候选验证点（下一批用更多窗口积累 emerging 组样本）；
4. **SG1 口径改进**：改用收盘槽序列（后续批，属算子输入口径修正，不改算子语义）；
5. MainlineScore 判定链维持降级诊断不变（第四轮裁决）；其合成层结构改造仍为暂缓候选。

## 5. 局限（如实）

- 54 天单一行情周期，结论不能外推（尤其未见图景：单边牛市/普涨反弹）；
- 未计资金容量与涨停买不进约束之外的冲击成本；交易成本用默认 fee/slippage；
- 三变体共享默认交易参数（未对 chase/hybrid 单独调参）——对照公平但未必是各自最优形态；
- market_phase 有 1 天 15:00 帧缺失（2026-07-06 属窗首，fail-visible 打标）；mainLines 键缺失 15 天按补涨臂处理并打标；
- 分层组样本普遍偏小（多数组 n<15），组内均值对个别大额交易敏感。

## 6. 代码与验证

- SG 算子：`backend/analysis/theme/rotation/signals.py`（27 用例）；
- 变体接线：`core/backtest/strategy.py` 白名单 +2、`services/backtest_service.py`（`_theme_sg_inputs` 预计算 + `_theme_execution_signals` chase/hybrid 分支）、`core/backtest/execution.py` 进场规则三 key 共用；
- runner：`backend/operations/diagnose_theme_r3_variants.py`（只读研究 runner，SG 统计复用 service 同一实现避免第二事实源）；
- 合同测试：`tests/test_theme_backtest.py` +3（chase/hybrid 门控/基线回归保护）；theme 域 421 用例全绿。
