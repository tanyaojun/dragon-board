# Phase 2 实施计划：拥挤度口径对比（现有 crowding 惩罚 vs 60 日分位数）

- 日期：2026-09-26
- 设计依据：`docs/theme-module/2026-09-26-themetrend-v12-upgrade-design.md` §5.1 D1 / §6.1 Track 因子线 Phase 2；Phase 0 spike 裁决（一年分位数不可行，60 日起步）。
- 研究问题：**分位数化拥挤度对"次日退潮"的区分度，是否优于现有瞬时 crowdingRisk 口径**（负向因子：高分应预测更差的 T+1）。
- 纪律：TDD；momentum_validation 范式（Phase 1 同款五分位+IC）；探索性结论不落默认；fail-visible；非交易时段运行。

## 接口事实（2026-09-26 生产库实测，勿凭记忆修改）

1. **现有口径公式**（`analysis/theme/heat.py:145 _crowding_risk`）：crowdingRisk = (min(volumeRatio,10) 均值−2.5)⁺×12 + change≥7 股占比×28，经 `_score` 0-100 归一——**纯瞬时合成，无历史基线**。消费侧：动量惩罚 `crowding_penalty_start=60 / max=15`（momentum_config.py:36）+ 回测执行硬层 `crowdedRiskThreshold=75→C_CROWDED`。
2. **daily hot_theme rows**：13,503 行（4-15~9-24）；窗口内 13,433 行 crowdingRisk 覆盖 99.5%；momentumScore/change 100%（Phase 1 已证）。T+1 前向收益原料直接可用。
3. **daily stock rows**：窗口内（7-06~09-24）54 天 **amount 每日 100% 覆盖**（每日 198-442 只，采集池动态）；turnoverRate 全窗 100%。总覆盖 50.4% 的缺口全部在 4 月窗口外（无 crowdingRisk 的 70 行同源）。
4. **theme_stock_mappings**：13,395 平铺对（stockCode×themeId，无 themeName 字段）；245 themeId 与窗口 entityKey 交集 **245/245 全可 join**。entityKey→entityName 有 2 个改名主题（219 量子科技/量子信息、349 海南封关/海南自贸）——统计在 entityKey ID 空间做（R1 先例），展示名取最新行。
5. **映射时点偏差**：映射是当前时点快照（每日 longhuvip 刷新），回溯 7 月带成员重构偏差——与设计文档腾讯回溯同款已声明偏差，只作探索性对照。
6. **分母口径**：题材成交额占比 = 题材成员股 amount 和 / 当日采集池 amount 总和（**非真实全市场**，池外成员计 0）；跨日跨题材同口径，分位数语义不受影响，报告须声明。

## 非目标

- 不接线生产（`theme_daily_factors` 落库属 Phase 4）；不动 75 硬层与动量惩罚默认参数；
- 腾讯日 K 回溯交叉验证另批（需网络拉取多年个股日 K，且只验水位不作区分度主证据）；
- 不做参数扫描（window/min_periods 各跑一档敏感性即止）；不做显著性检验。

## Task 1：分位数拥挤度小模块（TDD）

**文件**：`backend/analysis/theme/crowding_percentile.py`（新建）；测试 `quant-board/tests/test_theme_crowding_percentile.py`（新建）。

1. `theme_amount_share(stock_amounts: dict[str, float], theme_members: dict[str, set[str]]) -> dict[str, float]`：成员 amount 和 / 池总和；一股多题材重复计入（份额和可 >1，白名单口径）；池总和 0 → 返回 {}。
2. `theme_turnover_mean(stock_turnover, theme_members) -> dict[str, float | None]`：成员等权均值（缺位成员跳过并计数职责归调用方）；无可用成员 → None。
3. `rolling_percentile(values: dict[str, float], *, window: int = 60, min_periods: int = 10) -> dict[str, float | None]`：按日期升序，当日值在含当日的 trailing window 观测内的弱占比分位（<= 口径，0-100）；观测数 < min_periods → None（不伪造 50 中性）。
4. `combine_equal_weight(p1: dict, p2: dict) -> dict[str, float | None]`：两序列等权均值，单侧 None 取另一侧，双侧 None → None。

测试 ≥10 用例：重复计入和 >1、池总和 0、成员缺位均值、新高压 100 / 新低 = 1/n、min_periods 不足 None、全并列（弱占比 = 100）、合成单/双侧 None、乱序输入按日期序。

**验收**：`pytest tests/test_theme_crowding_percentile.py -q` 全绿。

## Task 2：口径对比 runner（只读）

**文件**：`backend/operations/diagnose_crowding_caliber_phase2.py`（新建，范式同 diagnose_sentiment_momentum_phase1.py）；产物 `data/reports/theme-phase2-crowding-caliber.json`（gitignore）。

1. **装载**：daily sector rows（crowdingRisk/momentumScore/change，entityKey 空间）+ daily stock rows（amount/turnoverRate）+ mappings（themeId→codes）；entityKey→展示名取最新行。
2. **口径**：A=crowdingRisk 落库值；B1=成交额占比 60 日分位；B2=换手率均值 60 日分位；BC=B1/B2 等权合成（无分位日如实 None）。
3. **统计**（各口径同表，momentum_validation 范式）：五分位 Q5−Q1 T+1 等权 change 差与胜率（负向因子预期 Q5<Q1）；逐日 spearman IC 均值与 IC<0 占比；n<3 打 insufficient_sample。
4. **对照项**：①75 硬层组（crowdingRisk≥75）vs 其余的次日 change 差与组频；②分位口径 ≥90 高压组 vs 其余（泡沫预警语义对照）；③口径间逐日横截面 spearman（A vs B1/B2/BC 均值）——两口径是否同一信号；④按月分解（极端月感知）。
5. fail-visible：min_periods 不足日计数、映射未覆盖题材计数、thin cross-section、缺 change/amount 行计数；只用 Python 本地计算，不触发回测。

**验收**：真实数据跑通落 JSON；控制台打印四口径对照表 + 硬层/高压组对照。

## Task 3：findings 报告 + 文档回写 + 记忆

1. `docs/theme-module/2026-09-26-phase2-findings.md`：核心问题裁决（分位数口径区分度是否占优）、四口径对照、硬层/高压组、口径相关性、样本量声明（约 40 个可评估日，探索性）、局限；
2. 设计文档 §10 追加 Phase 2 完成状态与结论；
3. 更新持久记忆 `themetrend-upgrade-plan.md`；
4. 提交分组：Task 1 模块 / Task 2 runner / Task 3 报告，各自独立 commit。

## 风险与回退

- **分位数前段窗口短**：min_periods=10 → 首个可评估日约 7-17，有效评估约 40 日；早段分位数粗糙（10 观测的分位粒度 10pp）——如实打标，不省略；
- **映射回溯偏差**（接口事实 5）与**分母为采集池**（接口事实 6）——报告显著位置声明；
- **A 口径 75 硬层组可能极小**（≥75 题材日频率未知）→ n<3 如实 insufficient；
- 回退 = 纯新增文件 revert，无既有行为耦合。
