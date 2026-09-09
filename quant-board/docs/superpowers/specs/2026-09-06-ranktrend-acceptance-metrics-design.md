# 验收口径与噪音度量修正（WP3）设计

状态：待批准（2026-09-06）
依赖：3.2 无前置（**先于 WP2 实施以产出基线**，排序已获用户确认）；3.1 独立；3.3 独立（可并行）。

## 动机

1. h1 单一口径验收放大了帧间噪音敏感度；four_dim pf 1.0377（`ranktrend-lifecycle-layer-rearchitecture-design.md:149` §7，769 帧 TradeSimulator）距盈亏平衡线很近，成本假设微调就可能翻转结论——成本敏感性从未被系统扫描。
2. "half_hour 噪音太多"缺少量化刻度：门控翻转频率无任何文档量化过——WP2 的效果度量没有基线。
3. 命名矛盾：五维信号（res/rank/vp/cs 投票 + lifecycle 环境门）与"四维"历史命名并存，overfitting-audit §2.1 还把 lifecycle 列为"投票"维。

## 现状锚点（侦察已确认）

- `tier_forward_returns(signals, frames, horizon=3, ...)`（`analysis/ranktrend/research/tier_monotonicity.py:77`）horizon 已参数化；h1 由调用方传 `horizon=1`（`operations/optimize_core_signal_parameters.py:92-95` 四维度全用 1）。
- 回测报告 `OutcomeEvaluator.evaluate(..., horizons=[1,3,5,10])`（`core/backtest/evaluator.py:92-131`，帧数口径）；**后端无"持有到收盘"口径**（全库检索无 hold-to-close 实现）。
- 交易成本模型：`core/backtest/config.py:5 DEFAULT_TRADE_CONFIG`——`slippageRate=0.001`、`feeRate=0.0003`、`stampTaxRate=0.0005`；成交模型 `execution.py:1058 _match_order`。**缺口：`fallbackSlippageRate` 未在 DEFAULT_TRADE_CONFIG 定义，运行时默认取 0**。
- 诊断脚本惯例：`backend/operations/diagnose_*.py`（diagnose_tier_discrimination / diagnose_signal_return_gap / diagnose_weak_regime_sampling / diagnose_trend_reversal_jump 等）。
- 交易侧 lifecycle 消费：`execution.py:883 _lifecycle_decision_action`（veto 门 L892、caution 扣分 L954、退出 L1019）；four_dim 入场 veto 门 execution.py:510-512。

## 范围 3.2：门控翻转率指标（先行，WP2 基线）

- 新增 `backend/operations/diagnose_gate_flip_rate.py`（跟随 diagnose_* 惯例：CLI 参数 dataset/snapshot_type/date 范围）。
- 逻辑：加载帧序列 → 引擎 replay 逐帧提取三类门控状态：lifecycle veto（per-stock）、synergy B/D 降档（per-stock）、regime state（市场级）→ 统计帧间翻转频率：总体翻转率、分股票 Top-N、分阶段（stage）分布、逐帧时间序列。
- 输出：结构化结果（JSON 落盘 + 控制台摘要），文件名含日期范围便于 WP2 前后对比存档。
- 明确只读诊断，不改引擎行为；WP2 编码完成前后各跑一次产出对比基线。

## 范围 3.1：验收口径修正

### a1. 持有到收盘口径（新增）

- 语义：entry 帧入场 → 当日收盘槽（15:30）强制出场的收益口径；跨帧信号质量评估不再只看 h1。
- 落点：`OutcomeEvaluator` 就近扩展（新增 hold-to-close 评估模式，与现有 horizons 并列输出），回测报告与诊断脚本可选启用。
- 验收口径声明：h1 降级为诊断口径（本征尺度）；策略/门控验收 = h4/h8 + 持有到收盘。口径声明落 `docs/ranktrend-tier-backtest/ranktrend-signal-tier-backtest-plan.md`（写计划时打开核实该文档结构，就近放验收口径节）。

### a2. 成本敏感性扫描（新增脚本）

- 新增 `backend/operations/diagnose_cost_sensitivity.py`：four_dim 等既有策略在 slippageRate×feeRate 档位网格（如 {0.0005, 0.001, 0.002}×{0.0003, 0.0006}）上重跑 TradeSimulator，产出 pf/胜率/总收益对成本的弹性表。
- **缺口修复**：`fallbackSlippageRate` 补进 `DEFAULT_TRADE_CONFIG` 并显式定值（评估现运行时默认 0 是否合理；改动需在文档声明）。
- 结论用途：验证 pf 1.0377 类近盈亏平衡结论对成本的稳健性；8 月冻结纪律适用——不回改历史结论，只声明口径切换点。

## 范围 3.3：命名与口径同步

- 文档：`docs/ranktrend-tier-backtest/**` 涉及"四维/lifecycle 投票"的表述统一为**"5 投票维 + 1 环境门"**；对 overfitting-audit §2.1 等历史文档**加勘误注记**（不重写历史结论正文）。
- 前端 UI：`rg` 定位根项目显示"四维"文案的组件（长测 §11.4e A2 待办），同步为一致命名；只改文案不改逻辑。
- L1 档案与相关计划文档的"四维 column plan"等标题加注新旧命名映射，不批量重命名文件。

## 非范围

- 不重算历史回测结论、不回改已固化报告数字。
- 不改 `tier_monotonicity` 硬约束达标线数值（MIN_SA_EXCESS_ACCURACY=0.05 不动）——只增加验收口径种类。
- 不改策略参数默认值（成本扫描只产出弹性表，调参走 longterm-test 流程）。

## 测试策略（TDD）

1. 3.2：翻转计数纯函数单测（合成信号序列：已知翻转次数断言统计正确）；真实数据运行人工复核输出结构。
2. 3.1：hold-to-close 评估单测（合成帧：entry 帧与 15:30 收盘价已知 → 收益正确；当日无收盘槽的边界）；成本扫描脚本冒烟（小样本跑通网格）。
3. 3.3：文档勘误人工审；前端文案改动跑 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。

## 风险与回退

- 口径切换造成历史对比断裂：文档显式声明切换点与新旧口径映射（用户原始风险清单已列）。
- 翻转率指标依赖 replay 全量帧跑：只读诊断脚本，不进交易链路，无生产风险。
- 回退：三项均为新增脚本/口径/文档，revert 即净移除；fallbackSlippageRate 定值如引发成交价变化需在改动说明中声明并保留回退注释。
