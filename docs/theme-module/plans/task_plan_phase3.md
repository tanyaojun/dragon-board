# Phase 3 实施计划：D2/D3/F1 逐因子区分度验证

- 日期：2026-09-26
- 设计依据：`2026-09-26-themetrend-v12-upgrade-design.md` §5.1 D2/D3、§5.2 F1、§6.1 Track 因子线 Phase 3。
- 研究问题：**风险调整动量、动量连续性、资金流持续性三个候选因子，对 T+1 题材收益的区分度是否优于现有原始动量（momentumScore）**——正因子，高分预期 T+1 更好（Q5−Q1 预期为正，与 Phase 2 拥挤度负因子方向相反）。
- 纪律：TDD；momentum_validation 范式（Phase 1/2 面板）；探索性结论不落默认；fail-visible。

## 接口事实（2026-09-26 生产库实测，勿凭记忆修改）

1. **F1 数据源修正（与设计 §5.2 不符，以实测为准）**：`services/theme/fund_cache.py` 双源缓存是 **Redis 运行态**（TTL 900s、跨日清理、无逐日历史）——F1 持久序列源 = `snapshot_sector_rows`（type=daily）`mainNetInflow`（SG3 同款，窗口内 70.8% 覆盖、7-21~7-29 整段缺）。`fund_flow_l2` 集合为个股级 L2 资金（8-07 起 35 天，需映射聚合），不作 F1 源（登记）。
2. **D2 无既有算子**：`analysis/theme/**` 无 sharpe/波动类函数，新写纯函数无双源风险。夏普动量 = trailing 窗 mean/std（尺度不变：百分数与小数口径的 Sharpe 排序完全一致，无需单位换算；零 std → None 不伪造）。
3. **D2 窗口现实**：设计口径 20/60 日；题材 change 序列实测最长 58 天（15:00 日历）→ **60 日结构性 insufficient（登记，不硬造）**；本批 20 日主档 + 40 日副档（40 日档评估日约 13 天，薄样本如实打标）。
4. **D2 序列源**：frames 15:00 收盘槽题材 change（R3b 同款日历，58 天；trailing 观测=有值观测，缺失日不入窗）。
5. **D3 排序源**：momentumScore 落库值（daily hot_theme rows 100% 覆盖）。streak 语义：None=题材当日未观测（断链，同 top1_streaks 口径）；0=观测但不在 Top 五分位；n=连续保持天数。
6. **前向收益**：T+1 daily change 等权（Phase 1/2 同口径）；评估窗 = daily 行日历（约 7-13..09-24，54 天）。

## 非目标

- 不接线生产（`theme_daily_factors` 落库属 Phase 4）；不动 v2 动量口径与任何默认参数；
- 60 日夏普动量不硬造（结构 insufficient 登记）；不做参数扫描（每因子一档）；
- S2 晋级率持久化（§5.3）归 Phase 4 前置项，不在本批。

## Task 1：因子时间序列小模块（TDD）

**文件**：`backend/analysis/theme/factor_series.py`（新建）；测试 `quant-board/tests/test_theme_factor_series.py`（新建）。

1. `sharpe_momentum(changes_by_day, *, window=20, min_periods=20) -> dict[str, float | None]`：trailing window 个有值观测的 mean/std（总体 std）；观测数不足或 std=0 → None。
2. `top_membership_streak(top_by_day, observed_by_day, theme) -> dict[str, int | None]`：逐日连续保持 Top 集合成员的计数（缺勤日 None 断链、观测但落选归 0）。
3. `positive_streak(values_by_day, *, threshold=0.0) -> dict[str, int | None]`：连续 >0 天数（None 断链、≤0 归零、断链后首个正值=1 不回补）。

测试 ≥12 用例：窗口截断、std=0、观测不足、缺勤断链、落选归零、断链后重计、乱序输入、边界（恰=threshold 不算正）。

**验收**：`pytest tests/test_theme_factor_series.py -q` 全绿。

## Task 2：逐因子区分度 runner（只读）

**文件**：`backend/operations/diagnose_factor_discrimination_phase3.py`（新建，范式同 diagnose_crowding_caliber_phase2.py）；产物 `data/reports/theme-phase3-factor-discrimination.json`（gitignore）。

1. **因子面板**（同一评估窗，T+1 daily change 前向）：
   - `momentumScore`（基线复算，同窗对照）；`sharpe_20`（主档）；`sharpe_40`（副档，薄样本）；`d3_streak`（momentumScore Top 五分位连续天数）；`f1_streak`（mainNetInflow 连续为正天数）；`inflow_level`（mainNetInflow 原始水平对照——检验"持续性"相对"水平"的增量）。
2. **统计**（正因子方向声明）：五分位 Q5−Q1 与胜率（预期 >0）、逐日 spearman IC 均值与 IC>0 占比、n<3 insufficient_sample、按月分解（极端月感知）。
3. **D3 条件视图**：momentumScore Top 五分位题材内，按 streak 中位数二分的 T+1 差（"高动量+高持续 vs 高动量+不稳定"——业界动量连续性过滤的直接检验）。
4. fail-visible：60 日窗口 insufficient 登记、sharpe std=0 计数、inflow 缺失断链计数、thin cross-section、映射外题材计数。

**验收**：真实数据跑通落 JSON；控制台打印六因子对照表 + D3 条件视图。

## Task 3：findings + 文档回写 + 记忆

1. `docs/theme-module/2026-09-26-phase3-findings.md`：核心裁决（三因子谁有区分度、相对基线是否增量）、六因子对照、D3 条件视图、样本量声明、Phase 4 因子清单建议；
2. 设计文档 §10 回写；更新持久记忆 `themetrend-upgrade-plan.md`；
3. 提交分组：Task 1 模块 / Task 2 runner / Task 3 报告，各自独立 commit。

## 风险与回退

- sharpe_40 评估日约 13 天（薄）→ insufficient 如实打标，不强行结论；
- mainNetInflow 7-21~7-29 缺口 → f1_streak 全体断链重计，7 月下旬因子值 None（fail-visible）；
- D3 streak 与 momentumScore 同源自相关（streak 由 momentumScore 排名派生）——条件视图是其主消费形态，独立五分位仅作参考，报告声明；
- 回退 = 纯新增文件 revert，无既有行为耦合。
