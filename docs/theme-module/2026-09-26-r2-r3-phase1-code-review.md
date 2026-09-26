# ThemeTrend R2/R3/Phase 1 整体 Code Review 报告

- 日期：2026-09-26
- 审查范围：`docs/theme-module/plans/task_plan_r2.md` / `task_plan_r3.md` / `task_plan_phase1.md` 三阶段的全部代码与测试（base 62e4e6a6 之后），以 main 最新态为准（含 d407fb08 regime 重构）。
- 审查方式说明：**子代理周配额实测未恢复**（错误信息显示重置时间为 2026-09-27 17:36:50，handoff 中"已恢复"有误），沿用上一对话先例降级为主代理按独立审查清单逐条执行。降级影响：审查者与实现者为同一上下文，独立性弱于子代理方案；缓解措施：严格按 spec→quality 两遍法逐文件通读 + 全仓消费点 rg 验证 + 测试实跑。
- 验证：`pytest tests/ -q -k "theme"` → **437 passed**（含本次补强 3 用例），未跑全量（既定裁决）。

## 复核点结论（handoff 指定）

| # | 复核点 | 结论 |
|---|--------|------|
| 1 | regime 重构后旧 classify_regime 仅诊断对照、无生产消费路径 | ✅ 通过。模块 docstring + 函数级 `[仅诊断对照]` 标注清晰；rg 全仓消费点仅 R2 诊断 runner 与 tests；R3 runner 消费的是权威口径 top1_streaks/rotation_state_context |
| 2 | `_theme_sg_inputs` entities 黑名单（排除 rotation_main_line）收双 entityType | ✅ 通过。注释明确"白名单会在任一环境漏收（2026-09-26 调试实证）"；真实 hot_theme 与测试夹具 sector 均收。第三种 entityType 误收风险仅污染 SG2 序列键空间，不匹配任何股票 themeName，无行为影响 |
| 3 | spearman 并列平均秩语义；题材 change 百分数单位 | ✅ 通过。平均秩 + 秩上 Pearson 实现正确（测试精确断言 0.94868/0.8）；有并列时单调查 \|IC\|<1 被测试锁定为正确行为；runner meta.forwardReturn 显式声明"change 为落库百分数单位，Q5-Q1 差与单位相同；IC 无量纲" |
| 4 | SQLite H4 兜底塞空列表 vs 生产 Mongo 差异是否污染测试 | ✅ 通过。test_theme_backtest.py 注释明确该差异，断言刻意环境中性（d2 只断言 tier 与 `engine_mainline_day` 不在 reasons，不断言 missing_mainlines）；两环境 tier 语义一致（都走补涨臂） |
| 5 | `_theme_execution_signals` 加分支后既有三策略零变化 | ✅ 通过。diff hunks 确认基线分支未触碰；sg_inputs 默认 None；THEME_SG_STRATEGIES 恰为 {chase, hybrid}；trade_defaults_for_strategy 对新变体回退 DEFAULT_TRADE_CONFIG；有回归保护用例（test_theme_sg_variants_not_used_by_baseline_strategy）+ 既有用例 |

## 分级清单

### Critical（0 项）

无。

### Important（1 项，已修复）

1. **hybrid 主线臂"不在名单→N_NEUTRAL"分支零测试覆盖**——共享夹具 `make_theme_sg_bundle` 只有单一题材且在 d3 mainLines 名单内，`not_in_engine_mainlines` 门控、`missing_mainlines` 补涨臂（A_MAIN 被覆盖为 B_IGNITION/N_NEUTRAL）、chase 拥挤优先三个决策路径均无断言。修复：test_theme_backtest.py 追加 3 个静态方法直调用例（commit beda7206）。

### Minor（6 项，登记不修）

1. **sg3 positive_min_days≥2 时断链后正段第 k 天误标 False**（`rotation/signals.py:111`）——代码与自身 docstring"断链后的正段无前置证据 → None"矛盾：pos_run==k 但 seg_evidence=False 时输出 False（断言"可判定未触发"），实际前置证据因缺口不可验证应为 None。生产唯一取值 k=1 语义正确（首日后各天 False 成立），无下游影响（False/None 均不触发）；若未来开放 k≥2 研究需先修。
2. **hybrid 主线日非名单股的 D_EXIT_RISK 被覆盖为 N_NEUTRAL**（`backtest_service.py:1466`）——计划原文语义（"不在名单 N_NEUTRAL"），但 D_EXIT_RISK 是档位退出触发器（execution.py:1399），主线日非名单持仓的档位退出被抑制（止损/止盈/maxHolding 兜底仍在）。mainLines 非空仅 8 天，对 R3 对照结论影响有限；登记为 hybrid 变体的语义特征，避免后续归因误读。
3. **`top3_jaccard_and_switch` 首个可比日计为一次切换 + 幽灵日 Jaccard=1.0**（`diagnose_theme_regime_r2.py:97`）——prev_top1 初值 None 使首日必计切换（分子 +1，约 2% 偏置）；空名单日与相邻非空日对贡献 Jaccard 1.0（数据缺口计为全量轮动）。继承自计划原文，样本量下影响可忽略。
4. **Phase 1 runner `--dataset` 参数被接受但查询硬编码 DATASET_ID**（`diagnose_sentiment_momentum_phase1.py:40`）——非默认取值时报告 meta.dataset 与实际查询库不一致；默认运行无影响。
5. **Phase 1 报告缺 per-day 情绪取数来源**——计划风险节要求"source 字段逐日落报告"，实际只落聚合分布（coverage.sentimentSourceDays），无法回查单日回退槽位；盘中药效代表性存疑日需重跑补查。
6. **rrg_quadrants docstring 错字**（`rotation/signals.py:30`）——"动量>=0 讱上行"应为"记上行"；另计划原文"长度不一致→全 None"与括号内"返回长度=min 长度"自相矛盾，实现取后者（合理偏离，已有测试钉死）。

## Spec Compliance 总评

- **R2**：五项 runner 产出齐全；4a3da04a 排序键规范化彻底（三个候选 + runner none 分支全部 `(-score, key)` 化）；9b6227a9 的 rank Top10 口径切换与 d407fb08 引擎权威口径重构均有报告声明与代码标注；transitions_to_json 兑现 tuple 键序列化要求。
- **R3**：SG 三算子合同（True/False/None）与断链口径逐函数符合计划；chase/hybrid tier 决策优先级与计划一致（crowding/outflow 优先、补涨不给 A_MAIN、mainLines 三态处理）；进场规则三 key 共用；runner 串行+gc+分变体 try/except fail-visible、复用 `_theme_sg_inputs` 避免第二事实源；既有三策略与默认参数零变化。
- **Phase 1**：回退序（daily:15:30 → half_hour 倒序排除 09:30/10:00 → insufficient）与容错路径逐条符合；五分位/T+1/两维分组/n<3 打标/按月分布齐全；phase_unknown 与 missing_15h_frame 两态区分是超计划的加分处理。

## 结论

**通过，可进入 Phase 2。** 无 Critical；唯一 Important（测试缺口）已修复并独立提交；Minor 6 项登记于本报告。R2/R3/Phase 1 的实证结论（R2 报告的 regime 双轴前提不成立、R3 的 chase 跑输/hybrid 小幅占优、Phase 1 的情绪相位方向性支持）未因本次审查动摇。
