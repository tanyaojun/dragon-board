---
name: four-dim-algorithm-research
description: 四维信号核心算法研发与优化流程——新增/修改 synergy 投票维度、观察因子（priceMomentum/priceRankDivergence/amountRatio 类）、投票权重、regime 门控或评估口径时使用。从因子设计（参数化 golden 不漂移）→ 区分度验证（h1 exAcc）→ 投票/门控接线 → 数据驱动决策（正贡献落默认/负贡献 vote=0 关闭）→ rolling walk-forward 组合验证（8 月冻结纪律）→ golden 回归 → 定值档案更新。与 ranktrend-tier-longterm-test（参数扫描）互补：本 skill 管"加不加因子/开不开投票/怎么门控"，长测 skill 管"已有参数怎么调"。第一轮实践见 quant-board/docs/ranktrend-tier-backtest/overfitting-audit.md 与 longterm-backtest-plan.md 阶段 10/11。
---

# 四维信号核心算法研发与优化流程

## Overview

对 synergy 投票维度、观察因子、投票权重、门控规则的**结构性改动**（不是调已有参数）：
走"设计 → 实证 → 决策 → 纪律"闭环。全程**不写回默认值**（golden 不变），只有用户明确决策
才落默认；负贡献因子一律**关闭观察**（vote=0），不删实现。

## 触发条件

- 新增投票维度 / 观察因子（如量名背离、价格-排名背离、横截面）
- 调整投票权重（tierSynergy*Vote）或 synergy 档位语义
- 新增/修改门控规则（regime 禁放、Jump 确认、weak 放开）
- 评估口径争议（h1 前瞻 vs 日线）
- 对现有因子做"加不加/开不开"的结构性论证（非参数扫描——那是 ranktrend-tier-longterm-test）

## 前置纪律（每次必须确认，防过拟合 A-E）

- **8 月冻结**：`backend/optimization/data_windows.py` 定义 train(4-15~5-31)/val(6 月)/
  test(7 月)/final(8 月冻结)。任何参数/因子决策**禁止引用 8 月数据**——扫描前调
  `assert_not_frozen(frames, purpose="scan")`；8 月只允许 `purpose="report"` 最终呈现。
- **7 月股灾样本外排除**：test 窗口含 7 月极端行情的验证结论不代表参数无效。
- **golden 基线**：改动前先跑 `pytest tests/test_ranktrend_golden_alignment.py` 锁定基线；
  参数化默认值=原硬编码（golden 不漂移）是第一步验收。
- **机理优先**：热榜池内**相对强弱口径（排名/横截面）有效，绝对口径（全市场/价格/金额）
  冗余或噪声**（G1 价格动量 −32%、dv 投票 −25% 实证）——新因子先问"是否与排名信息冗余"。

## 标准流程（9 步）

### 1. 因子设计（参数化，golden 不漂移）
- 沿调用链定位因子计算点；硬编码阈值参数化进 `RankTrendConfig`（默认值=原值，golden 不变）；
- 字段语义命名（如 `priceRankChangeMin`/`amountRatioHigh`）；list 字段同步
  `search_space._STRATEGY_LIST_KEYS`；新增测试：默认值断言 + 参数生效测试（改参数→输出变化）；
- 数据异常显式处理（0/None/NaN/样本不足 → 返回 None/unknown，**fail-visible 不吞不伪造**）。

### 2. 区分度验证（h1 exAcc）
- `tier_forward_returns(signals, frames, horizon=1, dimension=<维度>)` → 分档
  exAcc / excessMeanFutureReturn；
- 看 A 档样本量门槛（n<500 结论降级为观察项，如双强共振 n=264 未落地）；
- 若为投票维度：先验证**独立区分度**（synergy 分档），再验证**边际贡献**（加投票 vs 不加）。

### 3. 投票/门控接线
- 新维度进 `compute_synergy_state` 档位（如 cs_tier/dv_tier）；`tier_monotonicity.py`
  `DIMENSION_PATHS` 登记（否则 tier_forward_returns 无法按新维度分档）；
- 门控规则改 `compose_analysis_candidate_tier`（ban 分支）；保留旧规则回退开关
  （如 `regimeGateStrongBan=False` 逐字符回退）；
- 新字段自动进信号缓存键（`_STRATEGY_SCALAR_KEYS` 动态收集，无需手改）；
- 测试：档位判定用例 + 门控分层用例（禁/放行/回退三态）。

### 4. 数据驱动决策（核心步骤，不拍脑袋）
- 多档/多态实证（如四态背离、三模式门控对比），看**单调性/峰值稳定性**，非单点；
- **正贡献** → 候选默认值（等用户决策落地）；**负贡献/冗余** → `vote=0` 关闭观察
  （机制保留，记录实证数据）；
- 假设必须可证伪：先列假设与判定标准，再跑数据（方向 A/B/C 三连否定教训：
  假设"strong 失效/冗余/门控强度"均被数据否定，**不要预设结论**）。

### 5. 组合验证（rolling walk-forward）
- 按 `data_windows.rolling_windows()`：候选在 train 校准 → val 单调性 → test 样本外确认；
- 8 月 FINAL 只读（report），**不得因 FINAL 结果回改参数**；
- 跨窗口一致性检查（all vs test；必要时 quarter_hour 对照）。

### 6. golden 回归 + 全量测试
- `pytest tests/test_ranktrend_golden_alignment.py tests/test_market_regime.py
  tests/test_ranktrend_engine.py`（+ 相关新测试）全绿，golden 无漂移；
- 行为变更必须 golden 显式断言（如 regime 消费 hotlistSentiment 时同步改 golden 预期）。

### 7. 文档 + 定值档案
- 结论写入 longterm-backtest-plan.md 对应阶段（含**证伪/否定结论**，翻案记录明确
  如"§9.4 作废以 §9.5 为准"）；
- L1 参数更新 `ranktrend-l1-param-ledger.md`（commit/数据窗口/样本外状态）；
- 防过拟合审计项更新 `overfitting-audit.md`（若涉 8 月污染历史，如实标注）。

### 8. 前端链路同步（若涉展示）
- 新维度/门控若影响行情列表四维列、synergy.state 展示 → 同步前端
  （`src/components/common/DataTable.vue` 徽章样式、RankTrendPanel 口径）；
- 展示口径与算法口径分离要文档化（如趋势列 crossSection 徽章=展示口径，
  rankTrend.signalTier=算法维度，有意分离不冲突）。

### 9. 提交纪律
- conventional commits（feat/fix/style/docs），中文描述含"数据/实证依据"；
- 一组逻辑一个 commit；工作区干净收尾；临时脚本清理（.tmp 不留）。

## 关键文件索引

- 引擎/config：`quant-board/backend/analysis/ranktrend/engine.py`（RankTrendConfig + compose）
- 投票/档位：`quant-board/backend/analysis/ranktrend/volume_price.py`（compute_synergy_state）
- 因子模块：`price_rank_divergence.py`/`amount`（compute_amount_ratio）等新建因子放同目录
- 分档统计：`quant-board/backend/analysis/ranktrend/tier_monotonicity.py`（DIMENSION_PATHS）
- 数据窗口：`quant-board/backend/optimization/data_windows.py`（冻结守卫）
- 测试基准：`quant-board/tests/test_ranktrend_golden_alignment.py`（golden 不漂移）
- 档案/审计：`quant-board/docs/ranktrend-tier-backtest/ranktrend-l1-param-ledger.md`、
  `overfitting-audit.md`、`ranktrend-longterm-backtest-plan.md`
